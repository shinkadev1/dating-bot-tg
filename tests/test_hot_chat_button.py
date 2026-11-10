"""Кнопка «🔥 Пошлый чат» (бывшая «❤️ Найти девушку»)."""

from __future__ import annotations

import os
import unittest

os.environ["DEV"] = "false"

from app.handlers import _route  # noqa: E402
from app.ui import DATING_FIND_BTN, DATING_KEYBOARD  # noqa: E402


class HotChatButtonTests(unittest.TestCase):
    def test_new_label_routes_to_dating_find(self) -> None:
        self.assertEqual(DATING_FIND_BTN, "🔥 Пошлый чат")
        self.assertEqual(_route(DATING_FIND_BTN), "dating_find")
        self.assertEqual(_route("пошлый чат"), "dating_find")

    def test_old_label_still_works_from_stale_keyboards(self) -> None:
        self.assertEqual(_route("❤️ Найти девушку"), "dating_find")
        self.assertEqual(_route("Найти девушку"), "dating_find")

    def test_dating_keyboard_shows_new_label(self) -> None:
        text = str(DATING_KEYBOARD)
        self.assertIn("🔥 Пошлый чат", text)
        self.assertNotIn("Найти девушку", text)


if __name__ == "__main__":
    unittest.main()
