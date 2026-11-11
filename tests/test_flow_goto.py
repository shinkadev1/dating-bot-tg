"""Правки из CRM доходят до пользователя: новый экран и кнопка goto работают без изменений кода."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["DEV"] = "false"

import yaml  # noqa: E402

from app import flow, handlers  # noqa: E402
from app.api_types import PremiumLink  # noqa: E402
from app.gateway import Gateway  # noqa: E402
from app.peer import Peer  # noqa: E402

PEER = Peer("123", 42)
PAY_URL = "https://pay.example.test/?x=1"


def build_flow(tmp: Path) -> flow.Flow:
    """Боевой flow.yaml плюс новые экраны и кнопки, как после правки в CRM."""
    data = yaml.load((flow.FLOW_DIR / "flow.yaml").read_text(encoding="utf-8"), Loader=flow._Loader)
    shutil.copytree(flow.FLOW_DIR / "images", tmp / "images")
    screens = data["screens"]
    screens["main"]["buttons"] += [
        [{"text": "🎁 Акция", "goto": "promo"}],
        [{"text": "Цикл", "goto": "loop_a"}],
        [{"text": "К тарифам", "goto": "premium"}],
    ]
    screens["promo"] = {
        "title": "Акция",
        "text": "Скидка недели",
        "image": "images/greeting.jpg",
        "keyboard": "inline",
        "buttons": [[{"text": "Сайт", "url": "https://example.com/"}, {"text": "Назад", "goto": "main"}]],
        "next": "thanks",
        "pos": {"x": 0, "y": 540},
    }
    screens["thanks"] = {
        "title": "Спасибо",
        "text": "Спасибо, что заглянули",
        "keyboard": "reply",
        "buttons": [[{"text": "Вернуться", "goto": "promo"}]],
        "pos": {"x": 320, "y": 540},
    }
    screens["loop_a"] = {"title": "A", "text": "экран A", "next": "loop_b", "pos": {"x": 0, "y": 720}}
    screens["loop_b"] = {"title": "B", "text": "экран B", "next": "loop_a", "pos": {"x": 320, "y": 720}}
    path = tmp / "flow.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return flow.load(path)


class GotoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.flow = build_flow(tmp)
        patcher = patch.object(flow, "get", return_value=self.flow)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.bot = AsyncMock()
        self.real_gateway = Gateway()
        self.real_gateway.bind(self.bot)
        self.api = MagicMock()
        self.api.visit = AsyncMock()
        self.api.phase = AsyncMock(return_value="idle")
        offer = AsyncMock(return_value=PremiumLink(PAY_URL, False, None))
        for name, value in (("gateway", self.real_gateway), ("chat_api", self.api), ("premium_offer", offer)):
            p = patch.object(handlers, name, value)
            p.start()
            self.addCleanup(p.stop)
        handlers._awaiting_age.clear()
        self.addCleanup(handlers._awaiting_age.clear)

    def callback(self, data: str) -> MagicMock:
        cb = MagicMock()
        cb.data = data
        cb.from_user = SimpleNamespace(id=PEER.user_id, is_bot=False)
        cb.bot = SimpleNamespace(id=PEER.bot_key)
        cb.answer = AsyncMock()
        return cb

    async def test_reply_button_goto_sends_screen_then_next(self) -> None:
        await handlers.handle_incoming(PEER, "🎁 Акция")
        photo = self.bot.send_photo.call_args
        self.assertEqual(photo.kwargs["caption"], "Скидка недели")
        markup = photo.kwargs["reply_markup"]
        row = markup.inline_keyboard[0]
        self.assertEqual([b.text for b in row], ["Сайт", "Назад"])
        self.assertEqual(row[0].url, "https://example.com/")
        self.assertEqual(row[1].callback_data, "go:main")
        # next: thanks — следующий экран уходит сразу, с нижней клавиатурой из flow.
        message = self.bot.send_message.call_args
        self.assertEqual(message.args[1], "Спасибо, что заглянули")
        self.assertEqual([[b.text for b in r] for r in message.kwargs["reply_markup"].keyboard], [["Вернуться"]])
        self.api.phase.assert_not_called()

    async def test_token_is_case_and_space_insensitive(self) -> None:
        await handlers.handle_incoming(PEER, "  🎁 АКЦИЯ ")
        self.bot.send_photo.assert_awaited_once()

    async def test_goto_from_the_new_screen_button(self) -> None:
        await handlers.handle_incoming(PEER, "Вернуться")
        self.bot.send_photo.assert_awaited_once()

    async def test_next_loop_is_cut(self) -> None:
        await handlers.handle_incoming(PEER, "Цикл")
        texts = [c.args[1] for c in self.bot.send_message.call_args_list]
        self.assertEqual(texts, ["экран A", "экран B"])

    async def test_goto_handler_screen_uses_its_code(self) -> None:
        await handlers.handle_incoming(PEER, "К тарифам")
        self.bot.send_photo.assert_awaited_once()
        self.assertEqual(self.bot.send_photo.call_args.kwargs["caption"], self.flow.screen("premium").text)
        urls = [b.url for row in self.bot.send_photo.call_args.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertEqual(urls[0], PAY_URL + "&plan=trial")

    async def test_goto_interrupts_age_prompt(self) -> None:
        handlers._awaiting_age.add(PEER)
        await handlers.handle_incoming(PEER, "🎁 Акция")
        self.assertNotIn(PEER, handlers._awaiting_age)
        self.assertEqual(self.bot.send_photo.call_args.kwargs["caption"], "Скидка недели")

    async def test_inline_goto_callback(self) -> None:
        cb = self.callback("go:promo")
        await handlers.on_callback(cb)
        cb.answer.assert_awaited_once()
        self.bot.send_photo.assert_awaited_once()
        self.assertEqual(self.bot.send_message.call_args.args[1], "Спасибо, что заглянули")

    async def test_unknown_goto_callback_only_answers(self) -> None:
        cb = self.callback("go:nowhere")
        await handlers.on_callback(cb)
        cb.answer.assert_awaited_once()
        self.bot.send_photo.assert_not_called()
        self.bot.send_message.assert_not_called()

    async def test_inline_action_callback_runs_the_action(self) -> None:
        cb = self.callback("act:premium")
        await handlers.on_callback(cb)
        cb.answer.assert_awaited_once()
        self.bot.send_photo.assert_awaited_once()

    async def test_inline_action_runs_directly_while_age_is_awaited(self) -> None:
        """act:next/stop/report не превращаются в подсказку про возраст."""
        self.api.stop = AsyncMock()
        self.api.search = AsyncMock(return_value="searching")
        self.api.phase.return_value = "chatting"
        handlers._awaiting_age.add(PEER)
        await handlers.on_callback(self.callback("act:stop"))
        self.api.stop.assert_awaited_once()
        texts = [c.args[1] for c in self.bot.send_message.call_args_list]
        self.assertNotIn(handlers.AGE_TEXT, texts)
        self.assertIn(handlers.STOPPED_TEXT, texts)
        self.assertIn(PEER, handlers._awaiting_age)

        self.bot.send_message.reset_mock()
        self.api.phase.return_value = "idle"
        await handlers.on_callback(self.callback("act:next"))
        self.api.search.assert_awaited_once()
        self.assertNotIn(handlers.AGE_TEXT, [c.args[1] for c in self.bot.send_message.call_args_list])

        self.bot.send_message.reset_mock()
        await handlers.on_callback(self.callback("act:report"))
        self.assertIn(handlers.REPORT_SENT_TEXT, [c.args[1] for c in self.bot.send_message.call_args_list])

    async def test_inline_passthrough_action_cancels_age_wait(self) -> None:
        handlers._awaiting_age.add(PEER)
        await handlers.on_callback(self.callback("act:premium"))
        self.assertNotIn(PEER, handlers._awaiting_age)

    async def test_inline_dev_action_only_in_dev(self) -> None:
        mock = MagicMock()
        mock.simulate_partner_left = AsyncMock()
        with patch.object(handlers, "chat_api", mock):
            with patch.object(handlers, "DEV", False):
                await handlers.on_callback(self.callback("act:dev_leave"))
                mock.simulate_partner_left.assert_not_called()
            with patch.object(handlers, "DEV", True):
                await handlers.on_callback(self.callback("act:dev_leave"))
                mock.simulate_partner_left.assert_awaited_once()

    async def test_inline_unknown_action_only_answers(self) -> None:
        cb = self.callback("act:fly")
        await handlers.on_callback(cb)
        cb.answer.assert_awaited_once()
        self.bot.send_message.assert_not_called()
        self.bot.send_photo.assert_not_called()

    async def test_gateway_screen_without_text_and_image_is_skipped(self) -> None:
        with self.assertLogs("app.gateway", "WARNING"):
            await self.real_gateway.send_screen(PEER, "notice")
        self.bot.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
