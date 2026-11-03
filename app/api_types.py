"""Типы Chat API, общие для настоящего клиента и локальной заглушки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class ChatApiError(Exception):
    """API недоступен или ответил ошибкой."""


class NotChattingError(ChatApiError):
    """У пользователя уже нет активного диалога."""


class NotPremiumError(ChatApiError):
    """Медиа может отправить только пользователь с премиумом."""


@dataclass(frozen=True)
class SendResult:
    delivered: bool
    phase: str


@dataclass(frozen=True)
class PremiumLink:
    """Личная ссылка на оплату (действует 24 часа) и текущий срок премиума."""

    url: str
    premium_active: bool
    premium_until: datetime | None
