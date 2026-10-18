"""Адресат сообщения: бот Telegram и пользователь."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Peer:
    """Куда слать ответ. bot_key — id бота Telegram."""

    bot_key: str
    user_id: int
    platform: str = "tg"
