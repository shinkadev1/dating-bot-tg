"""app/content/content.json: файл из Bot CRM должен оставаться рабочим для бота."""

from __future__ import annotations

import json
import os
import unittest

os.environ["DEV"] = "false"

from app import content  # noqa: E402


class ContentFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(content.CONTENT_FILE.read_text(encoding="utf-8"))

    def test_format_and_sections(self) -> None:
        self.assertEqual(self.data["format"], content.FORMAT)
        for section in ("texts", "buttons", "lists", "keyboards", "images", "screens"):
            self.assertIsInstance(self.data[section], dict if section != "screens" else list, section)

    def test_all_strings_are_not_empty(self) -> None:
        for section in ("texts", "buttons"):
            for key, value in self.data[section].items():
                self.assertTrue(isinstance(value, str) and value.strip(), f"{section}.{key}")
        for name in self.data["lists"]:
            for key, value in content.items(name).items():
                self.assertTrue(value.strip(), f"lists.{name}.{key}")

    def test_keyboards_reference_existing_labels(self) -> None:
        for name in self.data["keyboards"]:
            kb = content.keyboard(name)  # бросает ContentError при битой ссылке
            self.assertIn(kb["type"], ("reply", "inline"), name)

    def test_images_exist(self) -> None:
        for name in self.data["images"]:
            self.assertTrue(content.image_path(name).is_file(), name)

    def test_screens_reference_existing_items(self) -> None:
        ids = set()
        for screen in self.data["screens"]:
            self.assertNotIn(screen["id"], ids)
            ids.add(screen["id"])
            self.assertIn(screen["text"], self.data["texts"], screen["id"])
            if "keyboard" in screen:
                self.assertIn(screen["keyboard"], self.data["keyboards"], screen["id"])
            if "image" in screen:
                self.assertIn(screen["image"], self.data["images"], screen["id"])

    def test_button_aliases_route_like_current_label(self) -> None:
        from app.handlers import _route

        for key, aliases in self.data.get("button_aliases", {}).items():
            current = _route(content.button(key))
            for alias in aliases:
                self.assertEqual(_route(alias), current, f"{key}: {alias}")

    def test_placeholders_kept(self) -> None:
        for key, placeholder in (
            ("PARTNER_MESSAGE", "{text}"),
            ("PREMIUM_ACTIVE_UNTIL_TEXT", "{date}"),
            ("CITY_SELECTED_TOAST", "{city}"),
        ):
            self.assertIn(placeholder, content.text(key), key)


if __name__ == "__main__":
    unittest.main()
