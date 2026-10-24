"""Типы Chat API, общие для настоящего клиента и локальной заглушки."""

from __future__ import annotations

from dataclasses import dataclass


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
