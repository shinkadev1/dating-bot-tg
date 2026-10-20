"""Скачивает фото, видео, кружок или голосовое из Telegram и отдаёт байты в Chat API."""

from __future__ import annotations

import logging
from io import BytesIO

from aiogram.types import Message

from app.api_client import NotChattingError, NotPremiumError, chat_api
from app.peer import Peer

logger = logging.getLogger(__name__)

_LIMITS = {
    "photo": 20 * 1024 * 1024,
    "voice": 20 * 1024 * 1024,
    "video_note": 32 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
}


def _part(message: Message) -> tuple[str, object] | None:
    if message.photo:
        return "photo", message.photo[-1]
    if message.video_note is not None:
        return "video_note", message.video_note
    if message.video is not None:
        return "video", message.video
    if message.voice is not None:
        return "voice", message.voice
    return None


async def store_tg_media(message: Message, peer: Peer) -> str:
    """Сохраняет вложение диалога. ok — файл в S3, failed — не скачался, left — диалог уже закрыт."""
    part = _part(message)
    if part is None:
        return "none"
    kind, source = part
    limit = _LIMITS[kind]
    size = getattr(source, "file_size", None)
    if isinstance(size, int) and size > limit:
        logger.warning("Медиа %s %s больше предела: %s байт", peer, kind, size)
        return "failed"
    try:
        buffer = BytesIO()
        await message.bot.download(source, destination=buffer, timeout=180)
        data = buffer.getvalue()
        if not data or len(data) > limit:
            logger.warning("Пустое или слишком большое медиа %s %s", peer, kind)
            return "failed"
        key = await chat_api.store_media(peer, kind, data)
    except NotChattingError:
        return "left"
    except NotPremiumError:
        logger.info("Медиа только у премиума %s", peer)
        return "premium"
    except Exception:
        logger.exception("Не сохранил %s %s", kind, peer)
        return "failed"
    logger.info("Медиа сохранено %s %s %s (%s байт)", peer, kind, key, len(data))
    return "ok"
