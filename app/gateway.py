"""Доставка текста и медиа пользователю Telegram."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile

from app.peer import Peer
from app.ui import CHAT_KEYBOARD, IDLE_KEYBOARD, PARTNER_LEFT_KEYBOARD

logger = logging.getLogger(__name__)

Keyboard = Literal["main", "chat", "partner_left", "notice"]
_MAX_TEXT_LENGTH = 4096


class Gateway:
    def __init__(self) -> None:
        self._bot: Bot | None = None

    def bind(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, peer: Peer, text: str, keyboard: Keyboard) -> bool:
        """Отправляет текст и клавиатуру. False, если пользователь недоступен: заблокировал бота или удалён.

        Временные сбои Telegram считаются доставкой, чтобы не обрывать диалог из-за сети.
        """
        if self._bot is None:
            raise RuntimeError("Бот Telegram ещё не запущен")
        if keyboard == "notice":
            markup = None
        elif keyboard == "chat":
            markup = CHAT_KEYBOARD
        elif keyboard == "partner_left":
            markup = PARTNER_LEFT_KEYBOARD
        else:
            markup = IDLE_KEYBOARD
        for attempt in range(2):
            try:
                await self._bot.send_message(peer.user_id, text[:_MAX_TEXT_LENGTH], reply_markup=markup)
                return True
            except TelegramRetryAfter as exc:
                if attempt:
                    break
                await asyncio.sleep(exc.retry_after)
            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                logger.info("Пользователь tg:%s недоступен: %s", peer.user_id, exc)
                return False
            except Exception as exc:  # noqa: BLE001 — сбой сети не должен ронять обработчик
                logger.warning("Не написал tg:%s: %s: %s", peer.user_id, type(exc).__name__, exc)
                return True
        logger.warning("Telegram ограничил отправку tg:%s, сообщение пропущено", peer.user_id)
        return True

    async def send_media(self, peer: Peer, kind: str, content_type: str, data: bytes) -> bool:
        """Кладёт файл в диалог. False — человек недоступен.

        Кружок, который Telegram не принял, уходит обычным видео. Сбой файла диалог не закрывает.
        """
        if self._bot is None:
            raise RuntimeError("Бот Telegram ещё не запущен")
        try:
            await self._send_file(peer.user_id, kind, data, content_type)
            return True
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await self._send_file(peer.user_id, kind, data, content_type)
                return True
            except TelegramRetryAfter:
                logger.warning("Telegram ограничил медиа tg:%s", peer.user_id)
                return True
            except (TelegramForbiddenError, TelegramBadRequest) as retry_exc:
                return not _tg_gone(retry_exc)
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            if _tg_gone(exc):
                logger.info("Пользователь tg:%s недоступен: %s", peer.user_id, exc)
                return False
            logger.warning("Не отправил медиа tg:%s: %s", peer.user_id, exc)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не отправил медиа tg:%s: %s: %s", peer.user_id, type(exc).__name__, exc)
            return True

    async def _send_file(self, user_id: int, kind: str, data: bytes, content_type: str) -> None:
        assert self._bot is not None
        name = _filename(kind, content_type)
        file = BufferedInputFile(data, filename=name)
        if kind == "photo":
            await self._bot.send_photo(user_id, file, reply_markup=CHAT_KEYBOARD)
            return
        if kind == "voice":
            if content_type == "audio/ogg":
                await self._bot.send_voice(user_id, file, reply_markup=CHAT_KEYBOARD)
            else:
                await self._bot.send_audio(user_id, file, reply_markup=CHAT_KEYBOARD)
            return
        if kind == "video_note":
            try:
                await self._bot.send_video_note(user_id, file, reply_markup=CHAT_KEYBOARD)
                return
            except TelegramBadRequest:
                file = BufferedInputFile(data, filename=name)
        await self._bot.send_video(user_id, file, reply_markup=CHAT_KEYBOARD)


def _tg_gone(exc: BaseException) -> bool:
    if isinstance(exc, TelegramForbiddenError):
        return True
    text = str(exc).lower()
    return any(part in text for part in ("blocked", "deactivated", "chat not found", "user not found", "kicked"))


def _filename(kind: str, content_type: str) -> str:
    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/quicktime": "mov",
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
    }.get(content_type, "bin")
    return f"{kind}.{ext}"


gateway = Gateway()
