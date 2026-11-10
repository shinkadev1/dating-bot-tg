"""Кнопка «📍 Выбрать город» (бывшая «🌍 Выбрать комнату») и список городов."""

from __future__ import annotations

import os
import unittest

os.environ["DEV"] = "false"

from app.handlers import _route  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
