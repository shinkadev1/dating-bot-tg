"""Доставка текста пользователю Telegram."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

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


gateway = Gateway()
