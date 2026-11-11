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

from app import flow
from app.api_client import ChatApiError, NotChattingError, chat_api
from app.config import DEV
from app.flow import ACTION_PREFIX, GOTO_PREFIX
from app.gateway import gateway
from app.media import has_tg_media, store_tg_media
from app.mock_api import MockChatApi
from app.paylink import premium_offer
from app.peer import Peer
from app.ui import (
    AGE_TEXT,
    DATING_TEXT,
    DEFAULT_ROOM,
    DEV_NOTICE_TEXT,
    FOUND_TEXT,
    GENDERS,
    MEDIA_FAILED_TEXT,
    MEDIA_PREMIUM_TEXT,
    MENU_TEXT,
    NO_PARTNERS_TEXT,
    PARTNER_LEFT_TEXT,
    PARTNER_NO_PREMIUM_TEXT,
    REPORT_SENT_TEXT,
    ROOMS,
    ROOMS_TEXT,
    SEARCHING_TEXT,
    SERVICE_DOWN_TEXT,
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

# Действия, которые код умеет выполнять. Кнопка или команда во flow.yaml с другим action — ошибка CI.
ACTIONS = frozenset(
    {
        "start",
        "next",
        "stop",
        "report",
        "find",
        "dating",
        "dating_find",
        "dating_rooms",
        "dating_settings",
        "main",
        "premium",
        "dev_leave",
        "dev_notice",
    }
)
# Пока человек вводит возраст, эти действия (и любая /команда) прерывают ввод и выполняются как обычно.
# Остальное (подписи «Следующий собеседник», «Закончить диалог», «Пожаловаться») получает подсказку про возраст.
_AGE_PASSTHROUGH = frozenset(
    {"start", "find", "dating", "dating_find", "dating_rooms", "dating_settings", "main", "premium"}
)
# Сколько экранов подряд по полю next отправляется за один переход (защита от цикла).
_MAX_SCREEN_CHAIN = 8

router = Router(name="chat")
router.message.filter(F.chat.type == ChatType.PRIVATE)


def _command(text: str) -> str:
    """Первое слово в нижнем регистре без @имя_бота: «/start@bot payload» → «/start»."""
    lowered = text.strip().lower()
    if not lowered.startswith("/"):
        return lowered
    return lowered.split()[0].split("@", 1)[0]


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
    action = flow.get().action_for(_command(text))
    mock = cast(MockChatApi, chat_api)
    if action == "dev_leave":
        await mock.simulate_partner_left(peer)
        return True
    if action == "dev_notice":
        await mock.simulate_notice(peer, DEV_NOTICE_TEXT)
        return True
    return False


async def handle_stop(peer: Peer, action: str | None, active: bool) -> bool:
    """Заканчивает диалог или поиск и возвращает основное меню."""
    if action != "stop":
        return False
    if active:
        await chat_api.stop(peer)
        await gateway.send(peer, STOPPED_TEXT, "main")
        return True
    await gateway.send_greeting(peer)
    return True


async def handle_next(peer: Peer, action: str | None, searching: bool) -> bool:
    """Кнопка «Следующий собеседник» запускает новый поиск."""
    if action != "next":
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
    if media_state in ("premium", "partner_premium"):
        await send_media_premium(peer, partner=media_state == "partner_premium")
    elif media_state == "failed":
        await gateway.send(peer, MEDIA_FAILED_TEXT, "chat")
    return True


async def handle_incoming(
    peer: Peer,
    text: str,
    handle: str | None = None,
    uploader: Callable[[], Awaitable[str]] | None = None,
) -> None:
    """Записывает визит и маршрутизирует сообщение."""
    try:
        await chat_api.visit(peer, handle)
    except ChatApiError as exc:
        logger.warning("Не записал визит %s: %s", peer, exc)
    await _dispatch(peer, text, uploader)


async def _dispatch(
    peer: Peer,
    text: str,
    uploader: Callable[[], Awaitable[str]] | None = None,
) -> None:
    """Маршрутизирует сообщение: старт, меню разделов, переходы из flow, настройки, затем диалог."""
    current = flow.get()
    command = _command(text)
    action = current.action_for(command)
    target = current.goto_for(command)
    try:
        if peer in _awaiting_age:
            age = parse_age(text)
            if age is not None:
                _awaiting_age.discard(peer)
                _age_choice[peer] = age
                await send_premium_gate(peer)
                return
            if action not in _AGE_PASSTHROUGH and target is None and not command.startswith("/"):
                await gateway.send(peer, AGE_TEXT, "dating")
                return
            _awaiting_age.discard(peer)
        if action == "start":
            await connect_with_partner(peer)
            return
        if action == "report":
            await handle_report(peer)
            return
        if action == "premium":
            await _show_premium(peer)
            return
        if action == "find":
            await connect_with_partner(peer)
            return
        if action == "dating_find":
            await handle_dating_find(peer)
            return
        if action == "dating":
            await handle_dating(peer)
            return
        if action == "dating_rooms":
            await _show_rooms(peer)
            return
        if action == "dating_settings":
            await _show_settings(peer)
            return
        if action == "main":
            await gateway.send(peer, MENU_TEXT, "main")
            return
        if target is not None:
            await show_screen(peer, target)
            return
        phase = await chat_api.phase(peer)
        if await handle_stop(peer, action, phase != "idle"):
            return
        if await handle_next(peer, action, phase == "searching"):
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


async def _show_premium(peer: Peer) -> None:
    await gateway.send_premium(peer, await premium_offer(peer))


async def _show_rooms(peer: Peer) -> None:
    await gateway.send_rooms(peer, peer_room(peer))


async def _show_settings(peer: Peer) -> None:
    await gateway.send_settings(peer, _gender_choice.get(peer, ""))


# Экраны с handler рисует код: во flow.yaml для них описаны текст, картинка и варианты.
_HANDLER_RUNNERS: dict[str, Callable[[Peer], Awaitable[None]]] = {
    "premium_offer": _show_premium,
    "rooms": _show_rooms,
    "settings": _show_settings,
}
HANDLERS = frozenset(_HANDLER_RUNNERS)


async def show_screen(peer: Peer, screen_id: str) -> None:
    """Показывает экран из flow (переход goto). Экран с handler рисует код, остальные общий рендер.

    Если у экрана без handler есть next, следом сразу уходит следующий экран; цикл обрывается.
    """
    current = flow.get()
    seen: set[str] = set()
    next_id: str | None = screen_id
    while next_id is not None and next_id not in seen and len(seen) < _MAX_SCREEN_CHAIN:
        seen.add(next_id)
        screen = current.screen(next_id)
        if screen.handler is not None:
            runner = _HANDLER_RUNNERS.get(screen.handler)
            if runner is None:
                logger.warning("Нет обработчика %s для экрана %s", screen.handler, next_id)
                return
            await runner(peer)
            return
        await gateway.send_screen(peer, next_id)
        next_id = screen.next


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
    """Inline-кнопки городов, пола и переходов из flow. Галочку переносим в том же сообщении."""
    if callback.from_user is None or callback.from_user.is_bot:
        return
    peer = Peer(str(callback.bot.id), callback.from_user.id)
    data = callback.data or ""
    try:
        current = flow.get()
        rooms_prefix = current.screen("rooms").options.prefix
        gender_prefix = current.screen("settings").options.prefix
        if data.startswith(rooms_prefix):
            await choose_room(peer, callback, data.removeprefix(rooms_prefix))
        elif data.startswith(gender_prefix):
            await choose_gender(peer, callback, data.removeprefix(gender_prefix))
        elif data.startswith(GOTO_PREFIX) and data.removeprefix(GOTO_PREFIX) in current.screens:
            await callback.answer()
            await show_screen(peer, data.removeprefix(GOTO_PREFIX))
        elif data.startswith(ACTION_PREFIX) and current.token_for(data.removeprefix(ACTION_PREFIX)):
            await callback.answer()
            await _dispatch(peer, current.token_for(data.removeprefix(ACTION_PREFIX)) or "")
        else:
            await callback.answer()
    except Exception:  # ошибка кнопки не должна ронять polling
        logger.exception("Ошибка кнопки %s для %s", data, peer)


async def choose_room(peer: Peer, callback: CallbackQuery, room: str) -> None:
    """Нажатие города: запоминает выбор, переносит галочку и показывает тост."""
    if room not in ROOMS:
        # Кнопка из старого сообщения со списком комнат: показываем вместо него города.
        if callback.message is not None:
            try:
                await callback.message.edit_text(ROOMS_TEXT, reply_markup=build_rooms_keyboard(peer_room(peer)))
            except Exception as exc:  # noqa: BLE001 — старое сообщение можно и не обновить
                logger.warning("Не обновил старый список %s: %s: %s", peer, type(exc).__name__, exc)
        await callback.answer(text=flow.get().text("toast_cities_refreshed"))
        return
    changed = _room_choice.get(peer) != room
    _room_choice[peer] = room
    if changed and callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=build_rooms_keyboard(room))
        except Exception as exc:  # noqa: BLE001 — клавиатуру можно и не обновить
            logger.warning("Не обновил город %s: %s: %s", peer, type(exc).__name__, exc)
    await callback.answer(text=flow.get().text("toast_city", city=ROOMS[room]))


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
    """Текст «нужен Премиум» и сразу промо с личной кнопкой оплаты. С премиумом — только срок."""
    offer = await premium_offer(peer)
    if not offer.premium_active:
        await gateway.send(peer, DATING_TEXT, "dating")
    await gateway.send_premium(peer, offer)


async def send_media_premium(peer: Peer, *, partner: bool = False) -> None:
    """Chat API не принял медиа из-за премиума.

    partner — Chat API прямо сказал, что премиума нет у собеседника: ссылку не запрашиваем.
    Есть премиум у автора — значит, его нет у собеседника, продавать нечего.
    """
    if partner:
        await gateway.send(peer, PARTNER_NO_PREMIUM_TEXT, "chat")
        return
    offer = await premium_offer(peer)
    if offer.premium_active:
        await gateway.send(peer, PARTNER_NO_PREMIUM_TEXT, "chat")
        return
    await gateway.send_pay_button(peer, MEDIA_PREMIUM_TEXT, offer.url)


async def handle_dating_find(peer: Peer) -> None:
    """Кнопка «Пошлый чат»: без премиума поиск не начинается — текст и промо."""
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
