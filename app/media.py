"""Скачивает фото, видео, кружок, аудио или голосовое из Telegram и отдаёт его в Chat API."""

from __future__ import annotations

import logging
from io import BytesIO

from aiogram.types import Message

from app.api_client import ChatApiError, NotChattingError, NotPremiumError, chat_api
from app.peer import Peer

logger = logging.getLogger(__name__)

# Bot API скачивает через getFile не больше 20 МБ. Более крупный файл уходит собеседнику в Telegram по file_id.
_DOWNLOAD_LIMIT = 20 * 1024 * 1024
_LIMITS = {
    "photo": 20 * 1024 * 1024,
    "voice": 20 * 1024 * 1024,
    "audio": 50 * 1024 * 1024,
    "video_note": 32 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
}


def has_tg_media(message: Message) -> bool:
    return _part(message) is not None


def _part(message: Message) -> tuple[str, str, object] | None:
    """Вид для Chat API, способ отправки в Telegram и объект файла."""
    if message.photo:
        return "photo", "photo", message.photo[-1]
    if message.video_note is not None:
        return "video_note", "video_note", message.video_note
    if message.video is not None:
        return "video", "video", message.video
    if message.voice is not None:
        return "voice", "voice", message.voice
    if message.audio is not None:
        return "voice", "audio", message.audio
    document = message.document
    if document is None:
        return None
    mime = (document.mime_type or "").lower()
    if mime.startswith("audio/"):
        return "voice", "audio", document
    if mime.startswith("video/"):
        return "video", "video", document
    return None


def _file_id(source: object) -> str | None:
    value = getattr(source, "file_id", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _over_limit(method: str, kind: str, size: object) -> bool:
    if not isinstance(size, int):
        return False
    return size > _LIMITS["audio" if method == "audio" else kind]


async def store_tg_media(message: Message, peer: Peer) -> str:
    """Сохраняет вложение диалога. ok — ушло собеседнику, failed — не скачалось, left — диалог уже закрыт."""
    part = _part(message)
    if part is None:
        return "none"
    kind, method, source = part
    file_id = _file_id(source)
    size = getattr(source, "file_size", None)
    if _over_limit(method, kind, size):
        logger.warning("Медиа %s %s больше предела: %s байт", peer, method, size)
        return "failed"
    data = b""
    skip_download = isinstance(size, int) and (size > _DOWNLOAD_LIMIT or (method == "audio" and size > _LIMITS["voice"]))
    if not skip_download:
        try:
            buffer = BytesIO()
            await message.bot.download(source, destination=buffer, timeout=180)
            data = buffer.getvalue()
        except Exception:
            logger.exception("Не скачал %s %s", method, peer)
            data = b""
        if data and len(data) > _LIMITS[kind]:
            data = b""
    if data:
        try:
            key = await chat_api.store_media(peer, kind, data, tg_file_id=file_id, tg_method=method)
        except NotChattingError:
            return "left"
        except NotPremiumError:
            logger.info("Медиа только у премиума %s", peer)
            return "premium"
        except ChatApiError as exc:
            if file_id and ("HTTP 413" in str(exc) or "HTTP 415" in str(exc)):
                logger.warning("Байты %s не приняты, отправляю file_id: %s", method, exc)
            else:
                logger.warning("Не сохранил %s %s: %s", method, peer, exc)
                return "failed"
        else:
            logger.info("Медиа сохранено %s %s %s (%s байт)", peer, method, key, len(data))
            return "ok"
    if file_id is None:
        logger.warning("Пустое медиа %s %s", peer, method)
        return "failed"
    try:
        await chat_api.relay_tg_file(peer, kind, file_id, method)
    except NotChattingError:
        return "left"
    except NotPremiumError:
        logger.info("Медиа только у премиума %s", peer)
        return "premium"
    except ChatApiError as exc:
        logger.warning("Не передал %s %s: %s", method, peer, exc)
        return "failed"
    logger.info("Медиа Telegram передано по file_id %s %s", peer, method)
    return "ok"
