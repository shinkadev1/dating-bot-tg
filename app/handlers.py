"""Сценарии входящих сообщений: меню, премиум, комнаты, настройки поиска и диалог."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import cast

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message

from app.api_client import ChatApiError, NotChattingError, chat_api
from app.config import DEV
from app.gateway import gateway
from app.media import has_tg_media, store_tg_media
from app.mock_api import MockChatApi
from app.peer import Peer
from app.ui import (
    AGE_TEXT,
    CHAT_BTN_NEXT,
    CHAT_BTN_STOP,
    DATING_BTN,
    DATING_FIND_BTN,
    DATING_ROOMS_BTN,
    DATING_SETTINGS_BTN,
    DATING_TEXT,
    DEFAULT_ROOM,
    DEV_LEAVE_COMMAND,
    DEV_NOTICE_COMMAND,
    DEV_NOTICE_TEXT,
    FIND_BTN,
    FOUND_TEXT,
    GENDERS,
    MAIN_MENU_BTN,
    MEDIA_FAILED_TEXT,
    MEDIA_PREMIUM_TEXT,
    MENU_TEXT,
    NEW_PARTNER_BTN,
    NO_PARTNERS_TEXT,
    PARTNER_LEFT_TEXT,
    PREMIUM_BTN,
    PREMIUM_STATUS_BTN,
    REPORT_BTN,
    REPORT_SENT_TEXT,
    ROOMS,
    SEARCHING_TEXT,
    SERVICE_DOWN_TEXT,
    START_BTN,
    STOPPED_TEXT,
    build_rooms_keyboard,
    build_settings_keyboard,
)

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_SECONDS = 30
_search_timeouts: dict[Peer, asyncio.Task[None]] = {}

# Выбор комнаты и настроек поиска живёт в памяти процесса: в Chat API он пока не уходит.
_room_choice: dict[Peer, str] = {}
_gender_choice: dict[Peer, str] = {}
_age_choice: dict[Peer, str] = {}
_awaiting_age: set[Peer] = set()
_AGE_RE = re.compile(
    r"^\s*(\d{1,2})\s*(?:\+|-\s*(\d{1,2}))?\s*(?:лет|года|год|л\.?)?\s*$",
    re.IGNORECASE,
)

_START_COMMANDS = {"/start", "/search", START_BTN.lower(), NEW_PARTNER_BTN.lower()}
_NEXT_COMMANDS = {"/next", CHAT_BTN_NEXT.lower()}
_STOP_COMMANDS = {"/stop", CHAT_BTN_STOP.lower()}
_REPORT_COMMANDS = {"/report", REPORT_BTN.lower(), "пожаловаться"}

# Нижняя клавиатура Telegram не умеет payload: маршрут определяем по тексту кнопки.
_BUTTON_ROUTES = {
    FIND_BTN.lower(): "find",
    "найти собеседника": "find",
    DATING_BTN.lower(): "dating",
    "чат знакомств": "dating",
    DATING_FIND_BTN.lower(): "dating_find",
    "найти девушку": "dating_find",
    DATING_ROOMS_BTN.lower(): "dating_rooms",
    "выбрать комнату": "dating_rooms",
    DATING_SETTINGS_BTN.lower(): "dating_settings",
    "настроить поиск": "dating_settings",
    MAIN_MENU_BTN.lower(): "main",
    "главное меню": "main",
    PREMIUM_STATUS_BTN.lower(): "premium",
    "премиум статус": "premium",
    PREMIUM_BTN.lower(): "premium",
    "купить премиум": "premium",
}

router = Router(name="chat")
router.message.filter(F.chat.type == ChatType.PRIVATE)


def _command(text: str) -> str:
    """Первое слово в нижнем регистре без @имя_бота: «/start@bot payload» → «/start»."""
    lowered = text.strip().lower()
    if not lowered.startswith("/"):
        return lowered
    return lowered.split()[0].split("@", 1)[0]


def _route(text: str) -> str | None:
    """Раздел меню по тексту нажатой кнопки. None — обычное сообщение."""
    return _BUTTON_ROUTES.get(text.strip().lower())


def peer_room(peer: Peer) -> str:
    """Комната, которую человек выбрал. По умолчанию — встречи в Петербурге."""
    return _room_choice.get(peer, DEFAULT_ROOM)


def parse_age(text: str) -> str | None:
    """Возраст из «26», «26+» или «24-34». None — не похоже на возраст."""
    match = _AGE_RE.match(text)
    if not match:
        return None
    low = int(match.group(1))
    high = int(match.group(2)) if match.group(2) else None
    if not 14 <= low <= 99:
        return None
    if high is not None and not low <= high <= 99:
        return None
    return f"{low}+" if high is None else f"{low}-{high}"


async def _handle_dev_command(peer: Peer, text: str) -> bool:
    """DEV: экраны, которые на проде приходят только от собеседника или рассылки."""
    command = _command(text)
    mock = cast(MockChatApi, chat_api)
    if command == DEV_LEAVE_COMMAND:
        await mock.simulate_partner_left(peer)
        return True
    if command == DEV_NOTICE_COMMAND:
        await mock.simulate_notice(peer, DEV_NOTICE_TEXT)
        return True
    return False


async def handle_stop(peer: Peer, command: str, active: bool) -> bool:
    """Заканчивает диалог или поиск и возвращает основное меню."""
    if command not in _STOP_COMMANDS:
        return False
    if active:
        await chat_api.stop(peer)
        await gateway.send(peer, STOPPED_TEXT, "main")
        return True
    await gateway.send_greeting(peer)
    return True


async def handle_next(peer: Peer, command: str, searching: bool) -> bool:
    """Кнопка «Следующий собеседник» запускает новый поиск."""
    if command not in _NEXT_COMMANDS:
        return False
    if searching:
        await gateway.send(peer, SEARCHING_TEXT, "chat")
        return True
    await connect_with_partner(peer)
    return True


async def handle_chat_line(
    peer: Peer,
    text: str,
    chatting: bool,
    uploader: Callable[[], Awaitable[str]] | None = None,
) -> bool:
    """Пересылает текст и медиа собеседнику."""
    if not chatting:
        return False
    media_state = await uploader() if uploader is not None else "none"
    if media_state == "left":
        await gateway.send(peer, PARTNER_LEFT_TEXT, "partner_left")
        return True
    if text:
        try:
            delivered = (await chat_api.send_message(peer, text)).delivered
        except NotChattingError:
            delivered = False
        if not delivered:
            await gateway.send(peer, PARTNER_LEFT_TEXT, "partner_left")
            return True
    if media_state == "premium":
        await gateway.send(peer, MEDIA_PREMIUM_TEXT, "chat")
    elif media_state == "failed":
        await gateway.send(peer, MEDIA_FAILED_TEXT, "chat")
    return True


async def handle_incoming(
    peer: Peer,
    text: str,
    handle: str | None = None,
    uploader: Callable[[], Awaitable[str]] | None = None,
) -> None:
    """Маршрутизирует сообщение: старт, меню разделов, настройки, затем диалог."""
    try:
        await chat_api.visit(peer, handle)
    except ChatApiError as exc:
        logger.warning("Не записал визит %s: %s", peer, exc)
    command = _command(text)
    route = _route(text)
    try:
        if peer in _awaiting_age:
            age = parse_age(text)
            if age is not None:
                _awaiting_age.discard(peer)
                _age_choice[peer] = age
                await send_premium_gate(peer)
                return
            if route is None and command not in _START_COMMANDS and not command.startswith("/"):
                await gateway.send(peer, AGE_TEXT, "dating")
                return
            _awaiting_age.discard(peer)
        if command in _START_COMMANDS:
            await connect_with_partner(peer)
            return
        if command in _REPORT_COMMANDS:
            await handle_report(peer)
            return
        if route == "premium":
            await gateway.send_premium(peer)
            return
        if route in {"find", "dating_find"}:
            await handle_dating_find(peer)
            return
        if route == "dating":
            await handle_dating(peer)
            return
        if route == "dating_rooms":
            await gateway.send_rooms(peer, peer_room(peer))
            return
        if route == "dating_settings":
            await gateway.send_settings(peer, _gender_choice.get(peer, ""))
            return
        if route == "main":
            await gateway.send(peer, MENU_TEXT, "main")
            return
        phase = await chat_api.phase(peer)
        if await handle_stop(peer, command, phase != "idle"):
            return
        if await handle_next(peer, command, phase == "searching"):
            return
        if await handle_chat_line(peer, text, phase == "chatting", uploader):
            return
        if phase == "searching":
            await gateway.send(peer, SEARCHING_TEXT, "chat")
            return
        await gateway.send_greeting(peer)
    except ChatApiError as exc:
        logger.warning("Chat API недоступен для %s: %s", peer, exc)
        await gateway.send(peer, SERVICE_DOWN_TEXT, "main")


@router.message()
async def on_message(message: Message) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return
    peer = Peer(str(message.bot.id), message.from_user.id)
    username = (message.from_user.username or "").strip()
    handle = f"@{username}" if username else None
    text = (message.text or message.caption or "").strip()
    uploader = None
    if has_tg_media(message):

        async def uploader() -> str:
            return await store_tg_media(message, peer)

    try:
        if DEV and await _handle_dev_command(peer, text):
            return
        await handle_incoming(peer, text, handle, uploader)
    except Exception:  # ошибка одного сообщения не должна ронять polling
        logger.exception("Ошибка ответа %s", peer)


@router.callback_query()
async def on_callback(callback: CallbackQuery) -> None:
    """Inline-кнопки комнат и пола. Галочку переносим в том же сообщении."""
    if callback.from_user is None or callback.from_user.is_bot:
        return
    peer = Peer(str(callback.bot.id), callback.from_user.id)
    data = callback.data or ""
    try:
        if data.startswith("room:"):
            await choose_room(peer, callback, data.removeprefix("room:"))
        elif data.startswith("gender:"):
            await choose_gender(peer, callback, data.removeprefix("gender:"))
        else:
            await callback.answer()
    except Exception:  # ошибка кнопки не должна ронять polling
        logger.exception("Ошибка кнопки %s для %s", data, peer)


async def choose_room(peer: Peer, callback: CallbackQuery, room: str) -> None:
    """Нажатие комнаты: запоминает выбор, переносит галочку и показывает тост."""
    if room not in ROOMS:
        await callback.answer()
        return
    changed = _room_choice.get(peer) != room
    _room_choice[peer] = room
    if changed and callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=build_rooms_keyboard(room))
        except Exception as exc:  # noqa: BLE001 — клавиатуру можно и не обновить
            logger.warning("Не обновил комнату %s: %s: %s", peer, type(exc).__name__, exc)
    await callback.answer(text=f"Комната: {ROOMS[room]}")


async def choose_gender(peer: Peer, callback: CallbackQuery, gender: str) -> None:
    """Нажатие пола: запоминает выбор, обновляет клавиатуру и спрашивает возраст."""
    if gender not in GENDERS:
        await callback.answer()
        return
    changed = _gender_choice.get(peer) != gender
    _gender_choice[peer] = gender
    if changed and callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=build_settings_keyboard(gender))
        except Exception as exc:  # noqa: BLE001 — клавиатуру можно и не обновить
            logger.warning("Не обновил пол %s: %s: %s", peer, type(exc).__name__, exc)
    await callback.answer()
    _awaiting_age.add(peer)
    await gateway.send(peer, AGE_TEXT, "dating")


async def send_premium_gate(peer: Peer) -> None:
    """Текст «нужен Премиум» и сразу промо с кнопкой оплаты."""
    await gateway.send(peer, DATING_TEXT, "dating")
    await gateway.send_premium(peer)


async def handle_dating_find(peer: Peer) -> None:
    """Кнопка «Найти собеседника»: без премиума поиск не начинается — текст и промо."""
    await send_premium_gate(peer)


async def handle_dating(peer: Peer) -> None:
    """Кнопка «Чат знакомств»: меняет нижнюю клавиатуру на меню раздела."""
    await gateway.send(peer, DATING_TEXT, "dating")


def cancel_search_timeout(peer: Peer) -> None:
    """С поиска уже сняли: найден собеседник или диалог закончен."""
    previous = _search_timeouts.pop(peer, None)
    if previous is not None:
        previous.cancel()


async def _leave_queue_later(peer: Peer) -> None:
    """Через SEARCH_TIMEOUT_SECONDS снимает с поиска, если пара так и не нашлась."""
    try:
        await asyncio.sleep(SEARCH_TIMEOUT_SECONDS)
        if await chat_api.phase(peer) != "searching":
            return
        await chat_api.stop(peer)
        await gateway.send(peer, NO_PARTNERS_TEXT, "main")
    except asyncio.CancelledError:
        raise
    except Exception:  # фоновая задача, иначе ошибка потеряется
        logger.exception("Не снял с поиска %s", peer)
    finally:
        if _search_timeouts.get(peer) is asyncio.current_task():
            del _search_timeouts[peer]


async def handle_report(peer: Peer) -> None:
    """Жалоба в живом диалоге закрывает его и ищет дальше. После ухода — только подтверждение."""
    phase = await chat_api.phase(peer)
    if phase == "searching":
        await gateway.send(peer, SEARCHING_TEXT, "chat")
        return
    if phase != "chatting":
        await gateway.send(peer, REPORT_SENT_TEXT, "partner_left")
        return
    try:
        phase = await chat_api.report(peer)
    except NotChattingError:
        await gateway.send(peer, REPORT_SENT_TEXT, "partner_left")
        return
    await gateway.send(peer, REPORT_SENT_TEXT, "chat")
    cancel_search_timeout(peer)
    if phase == "chatting":
        await gateway.send(peer, FOUND_TEXT, "chat")
        return
    await gateway.send(peer, SEARCHING_TEXT, "chat")
    _search_timeouts[peer] = asyncio.create_task(_leave_queue_later(peer))


async def connect_with_partner(peer: Peer) -> None:
    """Ставит в поиск. Второй стороне о паре и прежнему собеседнику об уходе пишет Chat API."""
    phase = await chat_api.search(peer)
    await gateway.send(peer, SEARCHING_TEXT, "chat")
    cancel_search_timeout(peer)
    if phase == "chatting":
        await gateway.send(peer, FOUND_TEXT, "chat")
        return
    _search_timeouts[peer] = asyncio.create_task(_leave_queue_later(peer))
