"""Заглушка Chat API для локального запуска: `DEV=true` в `.env`.

Повторяет контракт `app.api_client.ChatApiClient`: те же методы, те же ответы и
те же события, только всё живёт в памяти процесса. События не идут по WebSocket,
а кладутся в очереди `events` и `broadcasts`, которые читает `app.events`.

Собеседник-заглушка нужен, чтобы клавиатуру и сценарии можно было проверить
одним аккаунтом Telegram: пара находится через `DEV_PARTNER_DELAY` секунд,
на каждое сообщение приходит эхо через `DEV_REPLY_DELAY`. Медиа возвращается
автору тем же файлом. Если запустить бота под двумя аккаунтами, заглушка
сведёт их друг с другом как обычная очередь.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.api_types import ChatApiError, NotChattingError, SendResult
from app.config import DEV_ECHO, DEV_PARTNER_DELAY, DEV_REPLY_DELAY
from app.peer import Peer

logger = logging.getLogger(__name__)

# Адрес виртуального собеседника: ни один бот такой ключ не обслуживает.
MOCK_BOT_KEY = "dev-partner"
MOCK_USER_ID = 900_000_001

_WELCOME = "Привет! Я собеседник-заглушка. Напиши что-нибудь, и я повторю."
_REPLIES = [
    "Ага, понятно 🙂",
    "Расскажи подробнее",
    "Интересно! А что было дальше?",
    "Поддерживаю",
    "Ха-ха, точно 😄",
]
_CONTENT_TYPES = {
    "photo": "image/jpeg",
    "video": "video/mp4",
    "video_note": "video/mp4",
    "voice": "audio/ogg",
}


@dataclass
class _PeerState:
    """Состояние одного человека в заглушке."""

    phase: str = "idle"
    partner: Peer | None = None
    handle: str | None = None


class MockChatApi:
    """Chat API в памяти: очередь, пары, медиа и события вместо Postgres и Redis."""

    def __init__(self) -> None:
        # Очереди повторяют два WebSocket-потока: живые события и рассылки.
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.broadcasts: asyncio.Queue[dict] = asyncio.Queue()
        self._states: dict[Peer, _PeerState] = {}
        self._pending: dict[Peer, asyncio.Task[None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._media: dict[str, tuple[bytes, str, str]] = {}

    async def aclose(self) -> None:
        tasks = list(self._pending.values()) + list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._pending.clear()
        self._tasks.clear()

    # --- служебное -------------------------------------------------------

    def _state(self, peer: Peer) -> _PeerState:
        return self._states.setdefault(peer, _PeerState())

    async def _emit(self, queue: asyncio.Queue[dict], recipient: Peer, event: dict) -> None:
        body = {
            "to": {
                "platform": recipient.platform,
                "bot_key": recipient.bot_key,
                "user_id": recipient.user_id,
            },
            **event,
        }
        logger.info("[mock] событие %s → %s", body.get("type"), recipient)
        await queue.put(body)

    async def _push(self, recipient: Peer, event: dict) -> None:
        """Событие адресату, как его отдал бы WebSocket `/api/v1/events/tg`."""
        await self._emit(self.events, recipient, event)

    def _later(self, delay: float, action: Callable[[], Awaitable[None]]) -> asyncio.Task[None]:
        """Отложенное действие: имитация очереди и ответов живого собеседника."""

        async def runner() -> None:
            try:
                await asyncio.sleep(delay)
                await action()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — фоновая задача не должна падать молча
                logger.exception("[mock] фоновая задача")

        task = asyncio.create_task(runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _cancel_pending(self, peer: Peer) -> None:
        task = self._pending.pop(peer, None)
        if task is not None:
            task.cancel()

    async def _close(self, peer: Peer, reason: str) -> None:
        """Закрывает диалог: собеседник получает `partner_left`."""
        state = self._state(peer)
        partner = state.partner
        state.phase = "idle"
        state.partner = None
        if partner is None or partner.bot_key == MOCK_BOT_KEY:
            return
        other = self._state(partner)
        other.phase = "idle"
        other.partner = None
        self._cancel_pending(partner)
        await self._push(partner, {"type": "partner_left", "reason": reason})

    def _waiting_peer(self, peer: Peer) -> Peer | None:
        for other, state in self._states.items():
            if other != peer and other.platform == peer.platform and state.phase == "searching":
                return other
        return None

    async def _pair_with_mock(self, peer: Peer) -> None:
        state = self._states.get(peer)
        if state is None or state.phase != "searching":
            return
        partner = Peer(MOCK_BOT_KEY, MOCK_USER_ID, peer.platform)
        state.phase = "chatting"
        state.partner = partner
        logger.info("[mock] пара %s ↔ собеседник-заглушка", peer)
        await self._push(peer, {"type": "partner_found"})
        await asyncio.sleep(min(1.0, DEV_PARTNER_DELAY))
        current = self._states.get(peer)
        if current is None or current.phase != "chatting" or current.partner != partner:
            return
        await self._push(peer, {"type": "message", "text": _WELCOME})

    async def _mock_reply(self, peer: Peer, text: str) -> None:
        state = self._states.get(peer)
        if state is None or state.phase != "chatting":
            return
        if state.partner is None or state.partner.bot_key != MOCK_BOT_KEY:
            return
        reply = f"🤖 эхо: {text}" if DEV_ECHO else random.choice(_REPLIES)
        await self._push(peer, {"type": "message", "text": reply})

    # --- REST-контракт Chat API ------------------------------------------

    async def visit(self, peer: Peer, handle: str | None = None) -> None:
        state = self._state(peer)
        cleaned = (handle or "").strip()
        if cleaned:
            state.handle = cleaned
        logger.info("[mock] визит %s (%s)", peer, state.handle or "без имени")

    async def register_channel(self, platform: str, external_id: str, title: str) -> None:
        logger.info("[mock] бот %s:%s «%s» подключён", platform, external_id, title)

    async def phase(self, peer: Peer) -> str:
        return self._state(peer).phase

    async def search(self, peer: Peer) -> str:
        self._cancel_pending(peer)
        await self._close(peer, "stopped")
        waiter = self._waiting_peer(peer)
        if waiter is not None:
            state = self._state(peer)
            other = self._state(waiter)
            state.phase = other.phase = "chatting"
            state.partner, other.partner = waiter, peer
            logger.info("[mock] пара %s ↔ %s", peer, waiter)
            await self._push(waiter, {"type": "partner_found"})
            return "chatting"
        self._state(peer).phase = "searching"
        self._pending[peer] = self._later(DEV_PARTNER_DELAY, lambda: self._pair_with_mock(peer))
        return "searching"

    async def stop(self, peer: Peer) -> bool:
        self._cancel_pending(peer)
        state = self._state(peer)
        was_active = state.phase != "idle"
        if state.phase == "chatting":
            await self._close(peer, "stopped")
        else:
            state.phase = "idle"
        return was_active

    async def report(self, peer: Peer) -> str:
        if self._state(peer).phase != "chatting":
            raise NotChattingError("Нет активного диалога")
        await self._close(peer, "reported")
        return await self.search(peer)

    async def send_message(self, peer: Peer, text: str) -> SendResult:
        state = self._state(peer)
        if state.phase != "chatting" or state.partner is None:
            raise NotChattingError("Нет активного диалога")
        if state.partner.bot_key == MOCK_BOT_KEY:
            self._later(DEV_REPLY_DELAY, lambda: self._mock_reply(peer, text))
        else:
            await self._push(state.partner, {"type": "message", "text": text})
        return SendResult(delivered=True, phase="chatting")

    async def store_media(
        self,
        peer: Peer,
        kind: str,
        data: bytes,
        *,
        tg_file_id: str | None = None,
        tg_method: str | None = None,
    ) -> str:
        """Кладёт байты в память и возвращает ключ объекта, как S3."""
        state = self._state(peer)
        if state.phase != "chatting" or state.partner is None:
            raise NotChattingError("Нет активного диалога")
        if not data:
            raise ChatApiError("Пустой файл")
        key = f"dev/{uuid.uuid4().hex}"
        media_id = uuid.uuid4().hex
        content_type = _CONTENT_TYPES.get(kind, "application/octet-stream")
        self._media[media_id] = (data, content_type, kind)
        logger.info("[mock] медиа %s, %s байт → %s", kind, len(data), key)
        recipient = peer if state.partner.bot_key == MOCK_BOT_KEY else state.partner
        await self._push(
            recipient,
            {"type": "media", "media_id": media_id, "kind": kind, "content_type": content_type},
        )
        return key

    async def relay_tg_file(self, peer: Peer, kind: str, tg_file_id: str, tg_method: str) -> None:
        """Байтов нет: событие несёт file_id, как у настоящего Chat API."""
        state = self._state(peer)
        if state.phase != "chatting" or state.partner is None:
            raise NotChattingError("Нет активного диалога")
        logger.info("[mock] медиа %s по file_id %s", kind, tg_file_id)
        recipient = peer if state.partner.bot_key == MOCK_BOT_KEY else state.partner
        await self._push(
            recipient,
            {
                "type": "media",
                "kind": kind,
                "content_type": _CONTENT_TYPES.get(kind, "application/octet-stream"),
                "tg_file_id": tg_file_id,
                "tg_method": tg_method,
            },
        )

    async def fetch_media(self, media_id: str) -> tuple[bytes, str, str]:
        stored = self._media.get(media_id)
        if stored is None:
            raise ChatApiError(f"Нет медиа {media_id}")
        return stored

    async def delivery_failed(self, peer: Peer) -> None:
        logger.info("[mock] недоставка %s", peer)
        await self._close(peer, "undeliverable")

    # --- только для DEV: чего не сделать без второго человека ---------------

    async def simulate_partner_left(self, peer: Peer) -> None:
        """Команда `/dev_leave`: собеседник уходит, приходит `partner_left`."""
        if self._state(peer).phase == "chatting":
            await self._close(peer, "stopped")
        else:
            self._state(peer).phase = "idle"
        self._cancel_pending(peer)
        await self._push(peer, {"type": "partner_left", "reason": "stopped"})

    async def simulate_notice(self, peer: Peer, text: str) -> None:
        """Команда `/dev_notice`: рассылка приходит тем же путём, что и с сервера."""
        await self._emit(self.broadcasts, peer, {"type": "notice", "text": text})
