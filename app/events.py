"""Доставка событий Chat API в Telegram. События идут по WebSocket `/api/v1/events/tg`."""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import quote

from websockets.asyncio.client import connect

from app.api_client import ChatApiError, chat_api
from app.config import CHAT_API_URL, EVENTS_CONSUMER, chat_api_headers
from app.gateway import NeedBytes, gateway
from app.handlers import cancel_search_timeout
from app.peer import Peer
from app.ui import FOUND_TEXT, PARTNER_LEFT_TEXT, UNDELIVERED_TEXT, format_partner

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECONDS = 3.0
# Живые реплики идут тем же ботом. 10 сообщений/с оставляют запас под диалоги.
_NOTICE_INTERVAL = 0.1


async def _deliver(body: dict) -> None:
    """Шлёт событие адресату. Если Telegram не принял, API закрывает его диалог."""
    to = body["to"]
    peer = Peer(str(to["bot_key"]), int(to["user_id"]))
    kind = body.get("type")
    if kind == "partner_found":
        cancel_search_timeout(peer)
        delivered = await gateway.send(peer, FOUND_TEXT, "chat")
    elif kind == "message":
        delivered = await gateway.send(peer, format_partner(str(body.get("text") or "")), "chat")
    elif kind == "media":
        media_id = str(body.get("media_id") or "")
        tg_file_id = str(body.get("tg_file_id") or "")
        if not media_id and not tg_file_id:
            logger.warning("Событие media без файла для %s", peer)
            return
        file_kind = str(body.get("kind") or "")
        content_type = str(body.get("content_type") or "")
        try:
            delivered = await gateway.send_media(
                peer,
                file_kind,
                content_type,
                b"",
                tg_file_id=tg_file_id or None,
                tg_method=str(body.get("tg_method") or "") or None,
            )
        except NeedBytes:
            if not media_id:
                logger.warning("Telegram не принял файл без байтов для %s", peer)
                return
            try:
                data, content_type, file_kind = await chat_api.fetch_media(media_id)
            except ChatApiError as exc:
                logger.warning("Не скачал медиа %s для %s: %s", media_id, peer, exc)
                return
            delivered = await gateway.send_media(peer, file_kind, content_type, data)
    elif kind == "partner_left":
        cancel_search_timeout(peer)
        if body.get("reason") == "undeliverable":
            await gateway.send(peer, UNDELIVERED_TEXT, "main")
        else:
            await gateway.send(peer, PARTNER_LEFT_TEXT, "partner_left")
        return
    else:
        logger.warning("Неизвестное событие Chat API: %s", kind)
        return
    if delivered:
        return
    try:
        await chat_api.delivery_failed(peer)
    except ChatApiError as exc:
        logger.warning("Не сообщил API о недоставке %s: %s", peer, exc)


async def _handle(event: dict) -> None:
    try:
        await _deliver(event)
    except Exception:  # битое событие не должно стопорить очередь
        logger.exception("Не обработал событие %r", event)


async def _deliver_notice(body: dict) -> None:
    """Пишет уведомление в диалог и не меняет кнопки. Недоступный человек остаётся в своём диалоге."""
    if body.get("type") != "notice":
        return
    to = body.get("to") or {}
    text = str(body.get("text") or "").strip()
    if not text or "bot_key" not in to or "user_id" not in to:
        return
    peer = Peer(str(to["bot_key"]), int(to["user_id"]))
    await asyncio.sleep(_NOTICE_INTERVAL)
    await gateway.send_notice(peer, text, photo=await _notice_photo(body))


async def _notice_photo(body: dict) -> bytes | None:
    media_id = str(body.get("media_id") or "")
    if not media_id:
        return None
    try:
        data, _content_type, kind = await chat_api.fetch_media(media_id)
    except ChatApiError:
        logger.exception("Не скачал фото уведомления %s", media_id)
        return None
    if kind != "photo" or not data:
        return None
    return data


async def _handle_notice(event: dict) -> None:
    try:
        await _deliver_notice(event)
    except Exception:
        logger.exception("Не обработал уведомление %r", event)


async def _listen(path: str, handler) -> None:
    """Держит WebSocket: каждое событие доставляется и подтверждается по порядку."""
    url = f"{CHAT_API_URL.replace('http', 'ws', 1)}{path}?consumer={quote(EVENTS_CONSUMER)}"
    while True:
        try:
            async with connect(
                url,
                additional_headers=chat_api_headers(),
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
            ) as socket:
                logger.info("Читаю события Chat API: %s", url)
                async for raw in socket:
                    message = json.loads(raw)
                    await handler(message["event"])
                    await socket.send(json.dumps({"ack": message["id"]}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — обрыв или перезапуск Chat API
            logger.warning("WebSocket событий: %s: %s", type(exc).__name__, exc)
        await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


async def consume_events() -> None:
    await _listen("/api/v1/events/tg", _handle)


async def consume_broadcasts() -> None:
    await _listen("/api/v1/broadcasts/tg", _handle_notice)
