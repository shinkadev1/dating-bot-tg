"""Личная ссылка на оплату премиума из Chat API с запасной постоянной ссылкой."""

from __future__ import annotations

import logging

from app.api_client import ChatApiError, PremiumLink, chat_api
from app.peer import Peer
from app.ui import PREMIUM_URL

logger = logging.getLogger(__name__)


async def premium_offer(peer: Peer) -> PremiumLink:
    """Ссылка действует 24 часа, поэтому запрашивается на каждый показ.

    Chat API недоступен или оплата не настроена (503) — постоянная ссылка и статус «нет премиума».
    """
    try:
        return await chat_api.premium_link(peer)
    except ChatApiError as exc:
        logger.warning("Нет личной ссылки оплаты для %s, отдаю постоянную: %s", peer, exc)
    except Exception as exc:  # noqa: BLE001 — без ссылки кнопка оплаты всё равно нужна
        logger.warning("Нет личной ссылки оплаты для %s: %s", peer, type(exc).__name__)
    return PremiumLink(url=PREMIUM_URL, premium_active=False, premium_until=None)
