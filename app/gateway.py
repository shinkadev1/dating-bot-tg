"""Доставка текста и медиа пользователю Telegram."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, ReplyKeyboardMarkup

from app.peer import Peer
from app.ui import (
    CHAT_KEYBOARD,
    DATING_KEYBOARD,
    GREETING,
    IDLE_KEYBOARD,
    PARTNER_LEFT_KEYBOARD,
    PREMIUM_KEYBOARD,
    PREMIUM_STATUS_TEXT,
    ROOMS_TEXT,
    SETTINGS_TEXT,
    build_rooms_keyboard,
    build_settings_keyboard,
)

logger = logging.getLogger(__name__)

Keyboard = Literal["main", "chat", "partner_left", "notice", "dating"]
_MAX_TEXT_LENGTH = 4096
_TG_METHODS = {"photo", "audio", "voice", "video", "video_note"}
_KEYBOARDS: dict[str, ReplyKeyboardMarkup | None] = {
    "main": IDLE_KEYBOARD,
    "chat": CHAT_KEYBOARD,
    "partner_left": PARTNER_LEFT_KEYBOARD,
    "dating": DATING_KEYBOARD,
    "notice": None,
}

_ASSETS = Path(__file__).resolve().parent / "assets"
_ASSETS_CACHE: dict[str, bytes] = {}


def _asset(name: str) -> bytes | None:
    """Картинка из `app/assets`. Файла нет — None: текст важнее баннера."""
    if name not in _ASSETS_CACHE:
        try:
            _ASSETS_CACHE[name] = (_ASSETS / name).read_bytes()
        except OSError as exc:
            logger.warning("Нет картинки %s: %s", name, exc)
            _ASSETS_CACHE[name] = b""
    return _ASSETS_CACHE[name] or None


class NeedBytes(Exception):
    """file_id Telegram не принят, нужно отправить сохранённые байты."""


class Gateway:
    def __init__(self) -> None:
        self._bot: Bot | None = None

    def bind(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, peer: Peer, text: str, keyboard: Keyboard) -> bool:
        """Отправляет текст и клавиатуру. False, если пользователь недоступен: заблокировал бота или удалён.

        Временные сбои Telegram считаются доставкой, чтобы не обрывать диалог из-за сети.
        """
        return await self._send_text(peer, text, _KEYBOARDS.get(keyboard))

    async def _send_text(
        self,
        peer: Peer,
        text: str,
        markup: ReplyKeyboardMarkup | InlineKeyboardMarkup | None,
    ) -> bool:
        """Текст с клавиатурой или без неё. False — человек недоступен."""
        if self._bot is None:
            raise RuntimeError("Бот Telegram ещё не запущен")
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

    async def send_greeting(self, peer: Peer) -> bool:
        """Приветствие с баннером, текстом и нижней клавиатурой одним сообщением."""
        sent = await self._send_photo(peer, "greeting.jpg", GREETING, IDLE_KEYBOARD)
        if sent is not None:
            return sent
        return await self.send(peer, GREETING, "main")

    async def send_premium(self, peer: Peer) -> bool:
        """Промо премиума: картинка акции, список возможностей и кнопка оплаты."""
        sent = await self._send_photo(peer, "premium.png", PREMIUM_STATUS_TEXT, PREMIUM_KEYBOARD)
        if sent is not None:
            return sent
        return await self._send_text(peer, PREMIUM_STATUS_TEXT, PREMIUM_KEYBOARD)

    async def send_rooms(self, peer: Peer, selected: str) -> bool:
        """Текст выбора комнаты и inline-клавиатура с отмеченной комнатой."""
        return await self._send_text(peer, ROOMS_TEXT, build_rooms_keyboard(selected))

    async def send_settings(self, peer: Peer, selected: str) -> bool:
        """Текст настроек поиска и inline-клавиатура выбора пола."""
        return await self._send_text(peer, SETTINGS_TEXT, build_settings_keyboard(selected))

    async def _send_photo(
        self,
        peer: Peer,
        name: str,
        caption: str,
        markup: ReplyKeyboardMarkup | InlineKeyboardMarkup,
    ) -> bool | None:
        """Фото с подписью и кнопками. None — фото не ушло, нужен текстовый фолбэк."""
        photo = _asset(name)
        if photo is None:
            return None
        if self._bot is None:
            raise RuntimeError("Бот Telegram ещё не запущен")
        for attempt in range(2):
            try:
                await self._bot.send_photo(
                    peer.user_id,
                    BufferedInputFile(photo, filename=name),
                    caption=caption[:1024],
                    reply_markup=markup,
                )
                return True
            except TelegramRetryAfter as exc:
                if attempt:
                    break
                await asyncio.sleep(exc.retry_after)
            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                if _tg_gone(exc):
                    logger.info("Пользователь tg:%s недоступен: %s", peer.user_id, exc)
                    return False
                logger.warning("Не отправил фото tg:%s: %s", peer.user_id, exc)
                return None
            except Exception as exc:  # noqa: BLE001 — текст уйдёт без баннера
                logger.warning("Не отправил фото tg:%s: %s: %s", peer.user_id, type(exc).__name__, exc)
                return None
        logger.warning("Telegram ограничил отправку фото tg:%s", peer.user_id)
        return None

    async def send_notice(self, peer: Peer, text: str, *, photo: bytes | None) -> None:
        """Текст рассылки и, если есть, фото. Клавиатуру диалога не меняет."""
        if self._bot is None:
            raise RuntimeError("Бот Telegram ещё не запущен")
        if photo:
            caption = text if len(text) <= 1024 else None
            try:
                await self._send_notice_photo(peer.user_id, photo, caption)
                if caption is None:
                    await self.send(peer, text, "notice")
                return
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
                try:
                    await self._send_notice_photo(peer.user_id, photo, caption)
                    if caption is None:
                        await self.send(peer, text, "notice")
                    return
                except (TelegramForbiddenError, TelegramBadRequest) as retry_exc:
                    if _tg_gone(retry_exc):
                        return
                except TelegramRetryAfter:
                    logger.warning("Telegram ограничил уведомление tg:%s", peer.user_id)
                    return
            except (TelegramForbiddenError, TelegramBadRequest) as exc:
                if _tg_gone(exc):
                    logger.info("Пользователь tg:%s недоступен: %s", peer.user_id, exc)
                    return
                logger.warning("Не отправил фото уведомления tg:%s: %s", peer.user_id, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не отправил фото уведомления tg:%s: %s: %s", peer.user_id, type(exc).__name__, exc)
        await self.send(peer, text, "notice")

    async def _send_notice_photo(self, user_id: int, photo: bytes, caption: str | None) -> None:
        assert self._bot is not None
        await self._bot.send_photo(
            user_id,
            BufferedInputFile(photo, filename="photo.jpg"),
            caption=caption,
        )

    async def send_media(
        self,
        peer: Peer,
        kind: str,
        content_type: str,
        data: bytes,
        *,
        tg_file_id: str | None = None,
        tg_method: str | None = None,
    ) -> bool:
        """Кладёт файл в диалог. False — человек недоступен.

        Свой файл Telegram уходит по file_id: кружок остаётся кружком, голосовое — голосовым.
        Чужой файл уходит байтами. Сбой файла диалог не закрывает.
        """
        if self._bot is None:
            raise RuntimeError("Бот Telegram ещё не запущен")
        method = tg_method if tg_method in _TG_METHODS else _method_from_kind(kind, content_type)
        try:
            await self._deliver_file(peer.user_id, method, data, content_type, tg_file_id)
            return True
        except NeedBytes:
            raise
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await self._deliver_file(peer.user_id, method, data, content_type, tg_file_id)
                return True
            except NeedBytes:
                raise
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

    async def _deliver_file(
        self,
        user_id: int,
        method: str,
        data: bytes,
        content_type: str,
        tg_file_id: str | None,
    ) -> None:
        if tg_file_id:
            try:
                await self._send_ref(user_id, method, tg_file_id)
                return
            except TelegramBadRequest as exc:
                if _tg_gone(exc):
                    raise
                logger.warning("Telegram не принял file_id %s: %s", method, exc)
        if not data:
            raise NeedBytes
        await self._send_file(user_id, method, data, content_type)

    async def _send_ref(self, user_id: int, method: str, file_id: str) -> None:
        assert self._bot is not None
        bot = self._bot
        attempts: list = []
        if method == "photo":
            attempts.append(lambda: bot.send_photo(user_id, file_id, reply_markup=CHAT_KEYBOARD))
        elif method == "voice":
            attempts.append(lambda: bot.send_voice(user_id, file_id, reply_markup=CHAT_KEYBOARD))
            attempts.append(lambda: bot.send_audio(user_id, file_id, reply_markup=CHAT_KEYBOARD))
        elif method == "audio":
            attempts.append(lambda: bot.send_audio(user_id, file_id, reply_markup=CHAT_KEYBOARD))
        elif method == "video_note":
            attempts.append(lambda: bot.send_video_note(user_id, file_id, reply_markup=CHAT_KEYBOARD))
            attempts.append(lambda: bot.send_video_note(user_id, file_id))
            attempts.append(lambda: bot.send_video(user_id, file_id, reply_markup=CHAT_KEYBOARD))
        else:
            attempts.append(lambda: bot.send_video(user_id, file_id, reply_markup=CHAT_KEYBOARD))
        attempts.append(lambda: bot.send_document(user_id, file_id, reply_markup=CHAT_KEYBOARD))
        await _try_sends(attempts)

    async def _send_file(self, user_id: int, method: str, data: bytes, content_type: str) -> None:
        assert self._bot is not None
        bot = self._bot
        name = _filename(method, content_type)

        def uploaded() -> BufferedInputFile:
            return BufferedInputFile(data, filename=name)

        attempts: list = []
        if method == "photo":
            attempts.append(lambda: bot.send_photo(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
        elif method == "voice":
            if content_type == "audio/ogg":
                attempts.append(lambda: bot.send_voice(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
            attempts.append(lambda: bot.send_audio(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
        elif method == "audio":
            attempts.append(lambda: bot.send_audio(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
        elif method == "video_note":
            attempts.append(lambda: bot.send_video_note(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
            attempts.append(lambda: bot.send_video_note(user_id, uploaded()))
            attempts.append(lambda: bot.send_video(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
        else:
            attempts.append(lambda: bot.send_video(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
        attempts.append(lambda: bot.send_document(user_id, uploaded(), reply_markup=CHAT_KEYBOARD))
        await _try_sends(attempts)


def _method_from_kind(kind: str, content_type: str) -> str:
    """Файл пришёл не из Telegram: голосовое ogg остаётся голосовым, остальное аудио — песней."""
    if kind == "voice" and content_type != "audio/ogg":
        return "audio"
    if kind in _TG_METHODS:
        return kind
    return "video"


async def _try_sends(attempts: list) -> None:
    last: TelegramBadRequest | None = None
    for send in attempts:
        try:
            await send()
            return
        except TelegramBadRequest as exc:
            if _tg_gone(exc):
                raise
            last = exc
    if last is not None:
        raise last


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
        "audio/wav": "wav",
        "audio/webm": "webm",
    }.get(content_type, "bin")
    return f"{kind}.{ext}"


gateway = Gateway()
