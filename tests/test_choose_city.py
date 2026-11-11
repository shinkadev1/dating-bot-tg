"""Кнопка «📍 Выбрать город» (бывшая «🌍 Выбрать комнату») и список городов."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ["DEV"] = "false"

from app.handlers import _route, choose_room  # noqa: E402
from app.peer import Peer  # noqa: E402
from app.ui import (  # noqa: E402
    DATING_KEYBOARD,
    DATING_ROOMS_BTN,
    DEFAULT_ROOM,
    ROOM_ROWS,
    ROOMS,
    ROOMS_TEXT,
    build_rooms_keyboard,
)

# Названия городов и раскладка — в app/content/content.json (lists.ROOMS, keyboards.ROOMS_KEYBOARD).
SELECTED = ROOMS["spb"] + " ✅"


class ChooseCityTests(unittest.TestCase):
    def test_button_label_and_routes(self) -> None:
        self.assertIn(DATING_ROOMS_BTN, str(DATING_KEYBOARD))
        for text in (DATING_ROOMS_BTN, "выбрать город", "🌍 Выбрать комнату", "Выбрать комнату"):
            self.assertEqual(_route(text), "dating_rooms", text)

    def test_cities_keyboard(self) -> None:
        self.assertEqual({k for row in ROOM_ROWS for k in row}, set(ROOMS))
        self.assertEqual(DEFAULT_ROOM, "spb")
        rows = build_rooms_keyboard("spb").inline_keyboard
        self.assertEqual([len(r) for r in rows], [len(r) for r in ROOM_ROWS])
        labels = [b.text for r in rows for b in r]
        self.assertIn(SELECTED, labels)
        self.assertEqual(sum("✅" in t for t in labels), 1)
        self.assertTrue(all(b.callback_data.startswith("room:") for r in rows for b in r))


class StaleRoomButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_room_button_shows_cities(self) -> None:
        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        await choose_room(Peer("main", 1), callback, "talk")
        text, = callback.message.edit_text.call_args.args
        self.assertEqual(text, ROOMS_TEXT)
        markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
        self.assertIn(SELECTED, [b.text for r in markup.inline_keyboard for b in r])
        callback.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
