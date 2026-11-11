"""Поведение бота на flow.yaml совпадает со снимком кода до перехода (tests/fixtures/ui_snapshot.json).

Снимок снят с кода, где тексты, клавиатуры и маршруты были константами в app/ui.py и app/handlers.py.
Тест заново собирает то же самое (tests/snapshot_collect.py) и сравнивает: тексты, клавиатуры,
форматы, меню команд, классификацию входящих, ответы на нажатия, исходящие вызовы Telegram и события.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

os.environ["DEV"] = "false"

import snapshot_collect  # noqa: E402

from app import flow, handlers  # noqa: E402

SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "ui_snapshot.json").read_text(encoding="utf-8"))
_DEV_ACTIONS = {"/dev_leave": "dev_leave", "/dev_notice": "dev_notice"}

NEW: dict = {}


def setUpModule() -> None:
    collected = snapshot_collect.collect_all(inputs=list(SNAPSHOT["routing"]))
    NEW.update(json.loads(json.dumps(collected, ensure_ascii=False)))


class SnapshotTests(unittest.TestCase):
    def assert_section(self, section: str) -> None:
        old, new = SNAPSHOT[section], NEW[section]
        missing = [key for key in old if key not in new]
        self.assertEqual(missing, [], f"{section}: нет ключей")
        for key, expected in old.items():
            self.assertEqual(new[key], expected, f"{section}: {key}")

    def test_texts(self) -> None:
        self.assert_section("texts")

    def test_keyboards(self) -> None:
        self.assert_section("keyboards")

    def test_formats(self) -> None:
        self.assert_section("formats")

    def test_bot_commands_prod_and_dev(self) -> None:
        self.assertEqual(NEW["commands"], SNAPSHOT["commands"])

    def test_incoming_messages(self) -> None:
        """Каждый вход × фаза × ожидание возраста × режим даёт те же вызовы Telegram и Chat API."""
        self.assert_section("incoming")

    def test_callbacks_and_toasts(self) -> None:
        self.assert_section("callbacks")

    def test_gateway_output(self) -> None:
        """Тексты, подписи, клавиатуры и байты картинок (sha256) в вызовах Bot API."""
        self.assert_section("gateway")

    def test_events(self) -> None:
        self.assert_section("events")


class RoutingTests(unittest.TestCase):
    def test_classification_matches_old_tables(self) -> None:
        current = flow.get()
        for text, expected in SNAPSHOT["routing"].items():
            command = handlers._command(text)
            self.assertEqual(command, expected["command"], text)
            action = current.action_for(command)
            if command in _DEV_ACTIONS:
                self.assertEqual(action, _DEV_ACTIONS[command], text)
                continue
            old_action = expected["sets"][0] if expected["sets"] else expected["route"]
            self.assertEqual(action, old_action, text)

    def test_age_passthrough_matches_old_condition(self) -> None:
        current = flow.get()
        for text, expected in SNAPSHOT["routing"].items():
            command = handlers._command(text)
            action = current.action_for(command)
            passes = (
                action in handlers._AGE_PASSTHROUGH
                or current.goto_for(command) is not None
                or command.startswith("/")
            )
            self.assertEqual(passes, expected["age_passthrough"], text)

    def test_passthrough_actions_exist(self) -> None:
        self.assertTrue(handlers._AGE_PASSTHROUGH <= handlers.ACTIONS)


if __name__ == "__main__":
    unittest.main()
