"""Событие promo: промо премиума после каждого 10-го диалога."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DEV"] = "false"

from app import events, flow  # noqa: E402
from app.api_types import PremiumLink  # noqa: E402
from app.gateway import Gateway  # noqa: E402
from app.peer import Peer  # noqa: E402

PEER = Peer("123", 42)
PAY_URL = "https://pay.example.test/?utm_content=tok"
EVENT = {"type": "promo", "to": {"bot_key": "123", "user_id": 42}}
PROMO_TEXT = (
    "💎 Так и не нашёл, кого искал? Попробуй с премиумом — фото, видео и голосовые в чате "
    "и никакой рекламы. Пробный период — 1 ₽."
)


def offer(active: bool = False) -> PremiumLink:
    return PremiumLink(url=PAY_URL, premium_active=active, premium_until=None)


class PromoEventTests(unittest.IsolatedAsyncioTestCase):
    async def deliver(self, premium: PremiumLink) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
        gateway = AsyncMock()
        gateway.send_screen.return_value = False  # даже неудача отправки не должна обрывать что-либо
        api = AsyncMock()
        with (
            patch.object(events, "gateway", gateway),
            patch.object(events, "chat_api", api),
            patch.object(events, "premium_offer", AsyncMock(return_value=premium)),
            patch.object(events, "cancel_search_timeout") as cancel,
        ):
            await events._deliver(EVENT)
        return gateway, api, cancel

    async def test_promo_sends_screen_with_personal_link(self) -> None:
        gateway, api, cancel = await self.deliver(offer())
        gateway.send_screen.assert_awaited_once_with(PEER, "premium_promo", premium_url=PAY_URL)
        api.delivery_failed.assert_not_called()
        cancel.assert_not_called()

    async def test_active_premium_gets_nothing(self) -> None:
        gateway, api, _ = await self.deliver(offer(active=True))
        gateway.send_screen.assert_not_called()
        api.delivery_failed.assert_not_called()

    def test_event_registered(self) -> None:
        self.assertIn("promo", events.EVENTS)

    def test_flow_screen(self) -> None:
        screen = flow.get().screen("premium_promo")
        self.assertEqual(screen.text, PROMO_TEXT)
        self.assertEqual(screen.image, "images/premium.png")
        self.assertEqual(screen.kind, "inline")
        self.assertEqual(screen.on, "promo")
        buttons = [b for row in screen.buttons for b in row]
        self.assertEqual([b.text for b in buttons], ["💎 Купить премиум", "🔍 Новый собеседник"])
        self.assertEqual(buttons[0].url, "{premium_url}")
        self.assertEqual(buttons[1].action, "start")

    async def test_gateway_puts_personal_link_into_button(self) -> None:
        bot = AsyncMock()
        gw = Gateway()
        gw.bind(bot)
        await gw.send_screen(PEER, "premium_promo", premium_url=PAY_URL)
        kwargs = bot.send_photo.call_args.kwargs
        markup = kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].url, PAY_URL)
        self.assertEqual(markup.inline_keyboard[1][0].callback_data, "act:start")


if __name__ == "__main__":
    unittest.main()
