"""flow.yaml цел: схема, ссылки, картинки, лимиты Telegram, реестры кода и сообщения об ошибках."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DEV"] = "false"

import yaml  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

from app import events, flow, handlers  # noqa: E402

FLOW_YAML = flow.FLOW_DIR / "flow.yaml"


def base_data() -> dict:
    return yaml.load(FLOW_YAML.read_text(encoding="utf-8"), Loader=flow._Loader)


class RealFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = flow.load()

    def test_schema_is_valid_draft_2020_12(self) -> None:
        schema = json.loads((flow.FLOW_DIR / "flow.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("/v1/", schema["$id"])

    def test_every_screen_has_title_and_unique_pos(self) -> None:
        positions = []
        for screen in self.flow.screens.values():
            self.assertTrue(screen.title, screen.id)
            self.assertIsNotNone(screen.pos, screen.id)
            positions.append(screen.pos)
        self.assertEqual(len(positions), len(set(positions)))

    def test_links_and_files(self) -> None:
        self.assertIn(self.flow.start, self.flow.screens)
        for screen in self.flow.screens.values():
            for target in (screen.next, screen.buttons_from):
                self.assertTrue(target is None or target in self.flow.screens, screen.id)
            for row in screen.buttons:
                for button in row:
                    for target in (button.goto, button.next):
                        self.assertTrue(target is None or target in self.flow.screens, button.text)
            if screen.image:
                self.assertTrue((flow.FLOW_DIR / screen.image).is_file(), screen.image)
                self.assertLessEqual(len(screen.text or ""), 1024, screen.id)
        images = {p.name for p in (flow.FLOW_DIR / "images").iterdir()}
        used = {Path(s.image).name for s in self.flow.screens.values() if s.image}
        self.assertEqual(images, used, "лишние или недостающие файлы в flow/images")

    def test_telegram_limits(self) -> None:
        for screen in self.flow.screens.values():
            self.assertLessEqual(len(screen.text or ""), 4096, screen.id)
            for row in screen.buttons:
                self.assertTrue(1 <= len(row) <= 8)
                for button in row:
                    self.assertTrue(1 <= len(button.text) <= 64)
            if screen.options:
                for key in screen.options.items:
                    self.assertLessEqual(len(screen.options.data(key).encode()), 64, key)

    def test_registries_match_code(self) -> None:
        self.assertEqual(self.flow.actions(), handlers.ACTIONS)
        self.assertEqual(self.flow.handlers(), handlers.HANDLERS)
        self.assertEqual(self.flow.events(), events.EVENTS)

    def test_commands(self) -> None:
        for command in self.flow.commands(dev=True):
            self.assertRegex(command.command, r"^[a-z_]{1,32}$")
            self.assertTrue(1 <= len(command.description) <= 256)
        prod = {c.command for c in self.flow.commands(dev=False)}
        dev = {c.command for c in self.flow.commands(dev=True)}
        self.assertEqual(dev - prod, {"dev_leave", "dev_notice"})

    def test_ids_and_text_keys(self) -> None:
        pattern = re.compile(r"^[a-z][a-z0-9_]*$")
        for key in [*self.flow.screens, *self.flow.texts]:
            self.assertRegex(key, pattern)

    def test_text_formatting(self) -> None:
        self.assertEqual(self.flow.text("toast_city", city="X"), "Город: X")
        with self.assertRaises(flow.FlowError):
            self.flow.text("no_such_text")

    def test_cli_summary_and_exit_code(self) -> None:
        with patch("builtins.print") as printed:
            self.assertEqual(flow.main(), 0)
        self.assertRegex(printed.call_args.args[0], r"^flow загружен: \d+ экранов, \d+ текстов$")
        with patch.object(flow, "load", side_effect=flow.FlowError("x")), patch("builtins.print"):
            self.assertEqual(flow.main(), 1)


class BrokenFlowTests(unittest.TestCase):
    """Любая правка CRM, ломающая связи, даёт FlowError с путём до поля."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(flow.FLOW_DIR / "images", self.tmp / "images")

    def write(self, data: dict | str) -> Path:
        path = self.tmp / "flow.yaml"
        text = data if isinstance(data, str) else yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        path.write_text(text, encoding="utf-8")
        return path

    def assert_error(self, data: dict | str, *needles: str) -> None:
        with self.assertRaises(flow.FlowError) as ctx:
            flow.load(self.write(data))
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))

    def test_valid_copy_loads(self) -> None:
        flow.load(self.write(base_data()))

    def test_broken_yaml(self) -> None:
        self.assert_error("screens: [unclosed\n  - : :")

    def test_missing_file(self) -> None:
        with self.assertRaises(flow.FlowError):
            flow.load(self.tmp / "nope.yaml")

    def test_duplicate_yaml_key(self) -> None:
        self.assert_error("version: 1\nversion: 1\n", "version")

    def test_unknown_field(self) -> None:
        data = base_data()
        data["screens"]["main"]["colour"] = "red"
        self.assert_error(data, "colour")

    def test_goto_to_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0] = {"text": "Куда", "goto": "nowhere"}
        self.assert_error(data, "screens.main.buttons[0][0].goto", "nowhere")

    def test_next_to_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["settings"]["next"] = "nowhere"
        self.assert_error(data, "screens.settings.next", "nowhere")

    def test_button_next_to_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0]["next"] = "nowhere"
        self.assert_error(data, "buttons[0][0].next")

    def test_buttons_from_missing_screen(self) -> None:
        data = base_data()
        data["screens"]["menu"]["buttons_from"] = "nowhere"
        self.assert_error(data, "screens.menu.buttons_from")

    def test_start_missing(self) -> None:
        data = base_data()
        data["start"] = "nowhere"
        self.assert_error(data, "start")

    def test_missing_image(self) -> None:
        data = base_data()
        data["screens"]["main"]["image"] = "images/absent.jpg"
        self.assert_error(data, "screens.main.image")

    def test_bad_image_path(self) -> None:
        data = base_data()
        data["screens"]["main"]["image"] = "../greeting.jpg"
        self.assert_error(data, "image")

    def test_caption_too_long(self) -> None:
        data = base_data()
        data["screens"]["main"]["text"] = "я" * 1025
        self.assert_error(data, "screens.main.text")

    def test_callback_too_long(self) -> None:
        data = base_data()
        data["screens"]["rooms"]["options"]["callback"] = "r" * 60 + ":{key}"
        self.assert_error(data, "screens.rooms.options.callback")

    def test_duplicate_token_with_different_action(self) -> None:
        data = base_data()
        data["screens"]["chat"]["buttons"][0][0] = {"text": "🔍 Найти собеседника", "action": "next"}
        self.assert_error(data, "уже занят")

    def test_button_needs_exactly_one_of_action_goto_url(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0] = {"text": "Две цели", "action": "find", "goto": "chat"}
        self.assert_error(data, "buttons[0][0]")

    def test_url_must_be_https_or_premium_placeholder(self) -> None:
        data = base_data()
        data["screens"]["premium"]["buttons"][0][0]["url"] = "http://evil.example/"
        self.assert_error(data, "url")

    def test_reply_keyboard_has_no_url_buttons(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0][0] = {"text": "Ссылка", "url": "https://example.com/"}
        self.assert_error(data, "url")

    def test_buttons_from_cycle(self) -> None:
        data = base_data()
        data["screens"]["menu"]["buttons_from"] = "age"
        data["screens"]["age"]["buttons_from"] = "menu"
        self.assert_error(data, "цикл")

    def test_options_default_must_exist(self) -> None:
        data = base_data()
        data["screens"]["rooms"]["options"]["default"] = "mars"
        self.assert_error(data, "default")

    def test_bad_screen_id(self) -> None:
        data = base_data()
        data["screens"]["Bad-Id"] = copy.deepcopy(data["screens"]["notice"])
        self.assert_error(data, "Bad-Id")

    def test_row_limit(self) -> None:
        data = base_data()
        data["screens"]["main"]["buttons"][0] = [{"text": f"b{i}", "goto": "chat"} for i in range(9)]
        self.assert_error(data, "buttons[0]")

    def test_unknown_handler_is_flow_error_at_registry_check(self) -> None:
        data = base_data()
        data["screens"]["rooms"]["handler"] = "nowhere"
        loaded = flow.load(self.write(data))
        with self.assertRaises(flow.FlowError):
            loaded.check_registries(actions=handlers.ACTIONS, handlers=handlers.HANDLERS, events=events.EVENTS)

    def test_options_screen_needs_handler(self) -> None:
        data = base_data()
        del data["screens"]["rooms"]["handler"]
        self.assert_error(data, "screens.rooms.options", "handler")

    def test_unknown_text_field_is_flow_error(self) -> None:
        data = base_data()
        data["texts"]["toast_city"] = "Город: {dat}"
        self.assert_error(data, "texts.toast_city", "dat")
        data = base_data()
        data["texts"]["searching"] = "Ищем {who}"
        self.assert_error(data, "texts.searching", "who")

    def test_missing_text_field_and_bad_template(self) -> None:
        data = base_data()
        data["texts"]["partner_message"] = "Собеседник"
        self.assert_error(data, "texts.partner_message", "text")
        data = base_data()
        data["texts"]["searching"] = "Ищем {"
        self.assert_error(data, "texts.searching")
        data = base_data()
        data["texts"]["searching"] = "Ищем {0}"
        self.assert_error(data, "texts.searching")

    def test_on_key_stays_a_string(self) -> None:
        """В YAML 1.1 on — булево значение; загрузчик flow его не превращает."""
        self.assertEqual(flow.load(self.write(FLOW_YAML.read_text(encoding="utf-8"))).screens["chat"].on, "partner_found")


if __name__ == "__main__":
    unittest.main()
