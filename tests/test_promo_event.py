"""Промо премиума каждый 10-й диалог: флаг promo в partner_left и в ответе /stop."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DEV"] = "false"

from app import events, flow, handlers  # noqa: E402
from app.api_types import PremiumLink, StopResult  # noqa: E402
from app.peer import Peer  # noqa: E402
from app.ui import PARTNER_LEFT_TEXT, STOPPED_TEXT, UNDELIVERED_TEXT  # noqa: E402

PEER = Peer("123", 42)
TO = {"bot_key": "123", "user_id": 42}
PITCH = (
    "💎 Так и не нашёл, кого искал? Попробуй с премиумом — фото, видео и голосовые в чате "
    "и никакой рекламы.\n🔥 Пошлый чат\n📍 Поиск по городу\n👫 Выбор пола партнёра\n\n"
    "Пробный период — 1 ₽."
)


def offer(active: bool = False) -> PremiumLink:
    return PremiumLink(url="https://pay.example.test/", premium_active=active, premium_until=None)


class PartnerLeftPromoTests(unittest.IsolatedAsyncioTestCase):
    async def deliver(self, event: dict, premium: PremiumLink):
        gateway = AsyncMock()
        gateway.send_screen.return_value = False
        api = AsyncMock()
        paylink = AsyncMock(return_value=premium)
        with (
            patch.object(events, "gateway", gateway),
            patch.object(events, "chat_api", api),
            patch.object(events, "premium_offer", paylink),
            patch.object(events, "cancel_search_timeout"),
        ):
            await events._deliver(event)
        return gateway, api, paylink

    async def test_promo_without_premium(self) -> None:
        gateway, api, _ = await self.deliver({"type": "partner_left", "to": TO, "promo": True}, offer())
        gateway.send_screen.assert_awaited_once_with(PEER, "partner_left_promo")
        gateway.send.assert_not_called()
        api.delivery_failed.assert_not_called()

    async def test_promo_with_premium_is_plain(self) -> None:
        gateway, _, _ = await self.deliver({"type": "partner_left", "to": TO, "promo": True}, offer(True))
        gateway.send_screen.assert_not_called()
        gateway.send.assert_awaited_once_with(PEER, PARTNER_LEFT_TEXT, "partner_left")

    async def test_no_flag_skips_premium_offer(self) -> None:
        gateway, _, paylink = await self.deliver({"type": "partner_left", "to": TO}, offer())
        paylink.assert_not_called()
        gateway.send.assert_awaited_once_with(PEER, PARTNER_LEFT_TEXT, "partner_left")

    async def test_undeliverable_with_promo(self) -> None:
        gateway, _, paylink = await self.deliver(
            {"type": "partner_left", "to": TO, "promo": True, "reason": "undeliverable"}, offer()
        )
        paylink.assert_not_called()
        gateway.send_screen.assert_not_called()
        gateway.send.assert_awaited_once_with(PEER, UNDELIVERED_TEXT, "main")


class StopPromoTests(unittest.IsolatedAsyncioTestCase):
    async def stop(self, result: StopResult, premium: PremiumLink):
        gateway = AsyncMock()
        api = AsyncMock()
        api.stop.return_value = result
        with (
            patch.object(handlers, "gateway", gateway),
            patch.object(handlers, "chat_api", api),
            patch.object(handlers, "premium_offer", AsyncMock(return_value=premium)),
        ):
            self.assertTrue(await handlers.handle_stop(PEER, "stop", True))
        return gateway

    async def test_promo(self) -> None:
        gateway = await self.stop(StopResult(True, True), offer())
        gateway.send_screen.assert_awaited_once_with(PEER, "stopped_promo")
        gateway.send.assert_not_called()

    async def test_promo_with_premium(self) -> None:
        gateway = await self.stop(StopResult(True, True), offer(True))
        gateway.send_screen.assert_not_called()
        gateway.send.assert_awaited_once_with(PEER, STOPPED_TEXT, "main")

    async def test_no_promo(self) -> None:
        gateway = await self.stop(StopResult(True, False), offer())
        gateway.send_screen.assert_not_called()
        gateway.send.assert_awaited_once_with(PEER, STOPPED_TEXT, "main")


class FlowTests(unittest.TestCase):
    def check(self, name: str, head: str, texts: list[str], actions: list[str]) -> None:
        screen = flow.get().screen(name)
        self.assertEqual(screen.text, f"{head}\n\n{PITCH}")
        self.assertEqual(screen.image, "images/premium.png")
        self.assertEqual(screen.kind, "reply")
        self.assertLessEqual(len(screen.text), 1024)
        buttons = [b for row in screen.buttons for b in row]
        self.assertEqual([b.text for b in buttons], texts)
        self.assertEqual([b.action for b in buttons], actions)
        self.assertEqual(buttons[0].next, "premium")

    def test_partner_left_promo(self) -> None:
        self.check(
            "partner_left_promo",
            "Собеседник закончил диалог 😔",
            ["💎 Купить премиум", "🔍 Новый собеседник", "🚫 Пожаловаться"],
            ["premium", "start", "report"],
        )
        self.assertIsNone(flow.get().screen("partner_left_promo").on)

    def test_stopped_promo(self) -> None:
        self.check("stopped_promo", "Диалог остановлен.", ["💎 Купить премиум", "🔍 Новый собеседник"], ["premium", "start"])
        self.assertIsNone(flow.get().screen("stopped_promo").on)

    def test_old_artifacts_removed(self) -> None:
        self.assertNotIn("promo", events.EVENTS)
        with self.assertRaises(Exception):
            flow.get().screen("premium_promo")


if __name__ == "__main__":
    unittest.main()
