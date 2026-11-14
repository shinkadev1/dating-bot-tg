"""Ежедневная рассылка: notice с полем screen показывает экран flow, а не сырой текст."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DEV"] = "false"

from app import events, flow  # noqa: E402
from app.peer import Peer  # noqa: E402

PEER = Peer("123", 42)
TO = {"bot_key": "123", "user_id": 42}


class DailyPromoNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def deliver(self, body: dict):
        gateway = AsyncMock()
        api = AsyncMock()
        with (
            patch.object(events, "gateway", gateway),
            patch.object(events, "chat_api", api),
            patch.object(events, "_NOTICE_INTERVAL", 0),
        ):
            await events._deliver_notice(body)
        return gateway, api

    async def test_screen_is_sent_as_screen(self) -> None:
        gateway, api = await self.deliver({"type": "notice", "to": TO, "screen": "daily_promo"})
        gateway.send_screen.assert_awaited_once_with(PEER, "daily_promo")
        gateway.send_notice.assert_not_called()
        api.delivery_failed.assert_not_called()

    async def test_screen_wins_over_text(self) -> None:
        gateway, _ = await self.deliver({"type": "notice", "to": TO, "screen": "daily_promo", "text": "x"})
        gateway.send_screen.assert_awaited_once_with(PEER, "daily_promo")
        gateway.send_notice.assert_not_called()

    async def test_without_screen_plain_notice(self) -> None:
        gateway, _ = await self.deliver({"type": "notice", "to": TO, "text": "Привет"})
        gateway.send_screen.assert_not_called()
        gateway.send_notice.assert_awaited_once_with(PEER, "Привет", photo=None)

    async def test_unknown_screen_with_text_falls_back(self) -> None:
        gateway, _ = await self.deliver({"type": "notice", "to": TO, "screen": "no_such", "text": "Привет"})
        gateway.send_screen.assert_not_called()
        gateway.send_notice.assert_awaited_once_with(PEER, "Привет", photo=None)

    async def test_unknown_screen_without_text_is_skipped(self) -> None:
        gateway, api = await self.deliver({"type": "notice", "to": TO, "screen": "no_such"})
        gateway.send_screen.assert_not_called()
        gateway.send_notice.assert_not_called()
        api.delivery_failed.assert_not_called()


class DailyPromoScreenTests(unittest.TestCase):
    def test_screen_shape(self) -> None:
        screen = flow.get().screen("daily_promo")
        self.assertEqual(screen.kind, "inline")
        self.assertFalse(screen.image)
        self.assertTrue(screen.text)
        actions = [b.action for row in screen.buttons for b in row]
        self.assertEqual(actions, ["find", "premium"])

    def test_hello_screen_shape(self) -> None:
        screen = flow.get().screen("daily_hello")
        self.assertEqual(screen.kind, "inline")
        self.assertFalse(screen.image)
        self.assertIn("«Привет»", screen.text)
        labels = [b.text for row in screen.buttons for b in row]
        actions = [b.action for row in screen.buttons for b in row]
        self.assertEqual(labels, ["Давай", "💎 Премиум"])
        self.assertEqual(actions, ["find", "premium"])


if __name__ == "__main__":
    unittest.main()
