"""Сценарии входящих сообщений: меню, поиск и диалог."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from app.api_client import ChatApiError, NotChattingError, chat_api
from app.gateway import gateway
from app.media import has_tg_media, store_tg_media
from app.peer import Peer
from app.ui import (
    CHAT_BTN_NEXT,
    CHAT_BTN_STOP,
    FOUND_TEXT,
    GREETING,
    MEDIA_FAILED_TEXT,
    MEDIA_PREMIUM_TEXT,
    NEW_PARTNER_BTN,
    NO_PARTNERS_TEXT,
    PARTNER_LEFT_TEXT,
    REPORT_BTN,
    REPORT_SENT_TEXT,
    SEARCHING_TEXT,
    SERVICE_DOWN_TEXT,
    START_BTN,
    STOPPED_TEXT,
)

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_SECONDS = 30
_search_timeouts: dict[Peer, asyncio.Task[None]] = {}

_START_COMMANDS = {"/start", "/search", START_BTN.lower(), NEW_PARTNER_BTN.lower()}
_NEXT_COMMANDS = {"/next", CHAT_BTN_NEXT.lower()}
_STOP_COMMANDS = {"/stop", CHAT_BTN_STOP.lower()}
_REPORT_COMMANDS = {"/report", REPORT_BTN.lower(), "пожаловаться"}

router = Router(name="chat")
router.message.filter(F.chat.type == ChatType.PRIVATE)


def _command(text: str) -> str:
    """Первое слово в нижнем регистре без @имя_бота: «/start@bot payload» → «/start»."""
    lowered = text.strip().lower()
    if not lowered.startswith("/"):
        return lowered
    return lowered.split()[0].split("@", 1)[0]


async def handle_stop(peer: Peer, command: str, active: bool) -> bool:
    """Заканчивает диалог или поиск и возвращает основное меню."""
    if command not in _STOP_COMMANDS:
        return False
    if active:
        await chat_api.stop(peer)
    await gateway.send(peer, STOPPED_TEXT if active else GREETING, "main")
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
    """Маршрутизирует сообщение: старт, затем меню или диалог."""
    try:
        await chat_api.visit(peer, handle)
    except ChatApiError as exc:
        logger.warning("Не записал визит %s: %s", peer, exc)
    command = _command(text)
    try:
        if command in _START_COMMANDS:
            await connect_with_partner(peer)
            return
        if command in _REPORT_COMMANDS:
            await handle_report(peer)
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
        await gateway.send(peer, GREETING, "main")
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
        await handle_incoming(peer, text, handle, uploader)
    except Exception:  # ошибка одного сообщения не должна ронять polling
        logger.exception("Ошибка ответа %s", peer)


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
