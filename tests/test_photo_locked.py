"""Размытое фото собеседника без премиума: событие media с locked."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["DEV"] = "false"

from aiogram.types import BufferedInputFile  # noqa: E402

from app import events, flow  # noqa: E402
from app.api_types import PremiumLink  # noqa: E402
from app.gateway import Gateway  # noqa: E402
from app.peer import Peer  # noqa: E402
from app.ui import PHOTO_LOCKED_TEXT  # noqa: E402

PEER = Peer("123", 42)
TO = {"bot_key": "123", "user_id": 42}
LINK = "https://pay.example.test/personal"


class LockedPhotoEventTests(unittest.IsolatedAsyncioTestCase):
    async def deliver(self, event: dict):
        gateway = AsyncMock()
        gateway.send_locked_photo.return_value = True
        gateway.send_media.return_value = True
        api = AsyncMock()
        api.fetch_media.return_value = (b"blur", "image/jpeg", "photo")
        offer = AsyncMock(return_value=PremiumLink(url=LINK, premium_active=False, premium_until=None))
        with (
            patch.object(events, "gateway", gateway),
            patch.object(events, "chat_api", api),
            patch.object(events, "premium_offer", offer),
        ):
            await events._deliver(event)
        return gateway, api

    async def test_locked_sends_blurred_photo(self) -> None:
        gateway, api = await self.deliver({"type": "media", "to": TO, "locked": True, "media_id": "m1"})
        api.fetch_media.assert_awaited_once_with("m1")
        gateway.send_locked_photo.assert_awaited_once_with(PEER, b"blur", LINK)
        gateway.send_media.assert_not_called()
        api.delivery_failed.assert_not_called()

    async def test_locked_unavailable_reports_failure(self) -> None:
        gateway = AsyncMock()
        gateway.send_locked_photo.return_value = False
        api = AsyncMock()
        api.fetch_media.return_value = (b"blur", "image/jpeg", "photo")
        offer = AsyncMock(return_value=PremiumLink(url=LINK, premium_active=False, premium_until=None))
        with (
            patch.object(events, "gateway", gateway),
            patch.object(events, "chat_api", api),
            patch.object(events, "premium_offer", offer),
        ):
            await events._deliver({"type": "media", "to": TO, "locked": True, "media_id": "m1"})
        api.delivery_failed.assert_awaited_once_with(PEER)

    async def test_regular_media_keeps_old_path(self) -> None:
        gateway, api = await self.deliver(
            {"type": "media", "to": TO, "media_id": "m1", "tg_file_id": "f1", "kind": "photo", "tg_method": "photo"}
        )
        gateway.send_locked_photo.assert_not_called()
        gateway.send_media.assert_awaited_once()
        api.fetch_media.assert_not_called()


class LockedPhotoGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_caption_and_personal_link(self) -> None:
        bot = AsyncMock()
        gw = Gateway()
        gw.bind(bot)
        self.assertTrue(await gw.send_locked_photo(PEER, b"blur", LINK))
        args, kwargs = bot.send_photo.await_args
        self.assertEqual(args[0], 42)
        self.assertIsInstance(args[1], BufferedInputFile)
        self.assertEqual(kwargs["caption"], PHOTO_LOCKED_TEXT)
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.url, LINK)
        self.assertEqual(button.text, "💎 Купить премиум")


class FlowTests(unittest.TestCase):
    def test_screen(self) -> None:
        screen = flow.get().screen("photo_locked")
        self.assertEqual(screen.text, "🔒 Просмотр фото доступен только с премиумом")
        self.assertEqual(screen.kind, "inline")
        self.assertIsNone(screen.on)
        self.assertFalse(screen.image)


if __name__ == "__main__":
    unittest.main()
