"""Кнопка «📍 Выбрать город» (бывшая «🌍 Выбрать комнату») и список городов."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ["DEV"] = "false"

from app.handlers import _route, choose_room  # noqa: E402
from app.peer import Peer  # noqa: E402
from app.ui import DATING_KEYBOARD, DATING_ROOMS_BTN, DEFAULT_ROOM, ROOMS, build_rooms_keyboard  # noqa: E402

CITIES = ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Нижний Новгород", "Любой город"]


class ChooseCityTests(unittest.TestCase):
    def test_button_label_and_routes(self) -> None:
        self.assertEqual(DATING_ROOMS_BTN, "📍 Выбрать город")
        self.assertIn("📍 Выбрать город", str(DATING_KEYBOARD))
        for text in ("📍 Выбрать город", "выбрать город", "🌍 Выбрать комнату", "Выбрать комнату"):
            self.assertEqual(_route(text), "dating_rooms", text)

    def test_cities_keyboard(self) -> None:
        self.assertEqual(list(ROOMS.values()), CITIES)
        self.assertEqual(DEFAULT_ROOM, "spb")
        rows = build_rooms_keyboard("spb").inline_keyboard
        self.assertEqual([len(r) for r in rows], [2, 2, 2, 1])
        labels = [b.text for r in rows for b in r]
        self.assertIn("Санкт-Петербург ✅", labels)
        self.assertEqual(sum("✅" in t for t in labels), 1)
        self.assertTrue(all(b.callback_data.startswith("room:") for r in rows for b in r))


class StaleRoomButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_room_button_shows_cities(self) -> None:
        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        await choose_room(Peer("main", 1), callback, "talk")
        text, = callback.message.edit_text.call_args.args
        self.assertTrue(text.startswith("📍"))
        markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
        self.assertIn("Санкт-Петербург ✅", [b.text for r in markup.inline_keyboard for b in r])
        callback.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
