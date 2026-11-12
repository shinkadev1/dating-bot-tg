"""Сбор наблюдаемого поведения бота для теста эквивалентности.

Работает и со старым кодом (константы в app/ui.py), и с кодом на flow.yaml: опирается только
на публичные имена app.ui, handlers.handle_incoming, gateway и events. Снимок tests/fixtures/ui_snapshot.json
снят с кода до перехода на flow; тест пересобирает то же самое и сравнивает.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DEV", "false")

ROOT = Path(__file__).resolve().parent.parent
PAY_URL = "https://pay.example/x?a=1&plan=z"
PEER_ARGS = ("main", 7)


def _dump(markup) -> object:
    return None if markup is None else markup.model_dump(exclude_none=True)


def collect_texts() -> dict[str, str]:
    from app import ui

    return {name: value for name, value in vars(ui).items() if name.isupper() and isinstance(value, str)}


def collect_keyboards() -> dict[str, object]:
    from app import ui

    result: dict[str, object] = {
        name: _dump(getattr(ui, name))
        for name in ("IDLE_KEYBOARD", "DATING_KEYBOARD", "CHAT_KEYBOARD", "PARTNER_LEFT_KEYBOARD")
    }
    for key in [*ui.ROOMS, ""]:
        result[f"rooms:{key}"] = _dump(ui.build_rooms_keyboard(key))
    for key in [*ui.GENDERS, ""]:
        result[f"settings:{key}"] = _dump(ui.build_settings_keyboard(key))
    result["premium:trial"] = _dump(ui.build_premium_keyboard(PAY_URL, trial=True))
    result["premium:no_trial"] = _dump(ui.build_premium_keyboard(PAY_URL, trial=False))
    result["rooms_map"] = dict(ui.ROOMS)
    result["room_rows"] = [list(r) for r in ui.ROOM_ROWS]
    result["genders_map"] = dict(ui.GENDERS)
    result["premium_plans"] = [list(p) for p in ui.PREMIUM_PLANS]
    return result


def collect_formats() -> dict[str, str]:
    from app import ui

    return {
        "premium_active_none": ui.format_premium_active(None),
        "premium_active_date": ui.format_premium_active(datetime(2026, 1, 2, 21, 30, tzinfo=timezone.utc)),
        "premium_active_naive": ui.format_premium_active(datetime(2026, 1, 2, 21, 30)),
        "partner": ui.format_partner("hi"),
        "partner_braces": ui.format_partner("{x} {0}"),
    }


def collect_commands() -> dict[str, list[list[str]]]:
    code = (
        "import json; import app.main as m; "
        "print(json.dumps([[c.command, c.description] for c in m._COMMANDS], ensure_ascii=False))"
    )
    result = {}
    for dev in ("false", "true"):
        env = {**os.environ, "DEV": dev, "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=True
        )
        result[dev] = json.loads(out.stdout.strip().splitlines()[-1])
    return result


def _norm(value, peer) -> object:
    if value == peer:
        return "PEER"
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple)):
        return [_norm(v, peer) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v, peer) for k, v in value.items()}
    return repr(value)


def _calls(mock, peer) -> list[list[object]]:
    return [[name, _norm(list(args), peer), _norm(dict(kwargs), peer)] for name, args, kwargs in mock.mock_calls]


def routing_inputs() -> list[str]:
    """Тексты, на которых сверяется маршрутизация: типичные случаи и регистр."""
    return [
        "/start", "/search", "/next", "/stop", "/report", "/START", "/Start@Bot x", "/start@bot x", "/stop@bot",
        "/unknown", "/dev_leave", "/dev_notice", "/premium", "привет", "26+", "24-34", "26", "hello world",
        "Начать", "начать", "НАЧАТЬ", "Найти собеседника", "🔍 НАЙТИ СОБЕСЕДНИКА", "  🔍 Найти собеседника  ",
        "🔍 Новый собеседник", "новый собеседник", "➡️ Следующий собеседник", "🛑 Закончить диалог",
        "🚫 Пожаловаться", "Пожаловаться", "ПОЖАЛОВАТЬСЯ", "👑 Премиум статус", "💎 Купить премиум",
        "Премиум статус", "Купить премиум", "", "   ",
        "💘 Чат знакомств", "Чат знакомств", "🔥 Пошлый чат", "Пошлый чат", "❤️ Найти девушку", "найти девушку",
        "📍 Выбрать город", "Выбрать город", "🌍 Выбрать комнату", "выбрать комнату", "⚙️ Настроить поиск",
        "Настроить поиск", "◀️ Главное меню", "Главное меню",
    ]


def collect_routing_old() -> dict[str, dict]:
    """Только для старого кода: классификация через _BUTTON_ROUTES и наборы команд."""
    from app import handlers as h

    inputs = list(routing_inputs())
    inputs += list(h._BUTTON_ROUTES) + sorted(h._START_COMMANDS | h._NEXT_COMMANDS | h._STOP_COMMANDS | h._REPORT_COMMANDS)
    result = {}
    for text in dict.fromkeys(inputs):
        command = h._command(text)
        route = h._route(text)
        sets = [
            name
            for name, group in (
                ("start", h._START_COMMANDS),
                ("next", h._NEXT_COMMANDS),
                ("stop", h._STOP_COMMANDS),
                ("report", h._REPORT_COMMANDS),
            )
            if command in group
        ]
        passthrough = not (route is None and command not in h._START_COMMANDS and not command.startswith("/"))
        result[text] = {"command": command, "route": route, "sets": sets, "age_passthrough": passthrough}
    return result


def _make_api(phase: str, mode: str) -> MagicMock:
    api = MagicMock()
    api.visit = AsyncMock()
    api.phase = AsyncMock(return_value=phase)
    api.search = AsyncMock(return_value="chatting" if mode == "B" else "searching")
    api.stop = AsyncMock(return_value=SimpleNamespace(was_active=True, promo=False))
    api.report = AsyncMock(return_value="chatting" if mode == "B" else "searching")
    api.send_message = AsyncMock(return_value=SimpleNamespace(delivered=True))
    api.delivery_failed = AsyncMock()
    return api


async def _run_incoming(text: str, phase: str, awaiting: bool, mode: str, uploader_state: str | None = None) -> dict:
    from app import handlers as h
    from app.api_types import PremiumLink
    from app.peer import Peer

    peer = Peer(*PEER_ARGS)
    h._awaiting_age.clear()
    h._age_choice.clear()
    if awaiting:
        h._awaiting_age.add(peer)
    gw = AsyncMock()
    api = _make_api(phase, mode)
    offer = PremiumLink(
        "https://pay.example/p", mode == "C", datetime(2026, 1, 2, tzinfo=timezone.utc) if mode == "C" else None
    )
    uploader = None
    if uploader_state is not None:

        async def uploader() -> str:
            return uploader_state

    with patch.object(h, "gateway", gw), patch.object(h, "chat_api", api), patch.object(
        h, "premium_offer", AsyncMock(return_value=offer)
    ):
        await h.handle_incoming(peer, text, None, uploader)
        await asyncio.sleep(0)
    for task in list(h._search_timeouts.values()):
        task.cancel()
    await asyncio.gather(*h._search_timeouts.values(), return_exceptions=True)
    h._search_timeouts.clear()
    return {
        "gateway": _calls(gw, peer),
        "api": _calls(api, peer),
        "awaiting_after": peer in h._awaiting_age,
        "age_after": h._age_choice.get(peer),
    }


async def collect_incoming(inputs: list[str] | None = None) -> dict[str, dict]:
    from app import handlers as h

    result = {}
    texts = list(dict.fromkeys(inputs if inputs is not None else routing_inputs()))
    if inputs is None and hasattr(h, "_BUTTON_ROUTES"):
        texts += [t for t in h._BUTTON_ROUTES if t not in texts]
    h._room_choice.clear()
    h._gender_choice.clear()
    for text in texts:
        for phase in ("idle", "searching", "chatting"):
            for awaiting in (False, True):
                for mode in ("A", "B", "C"):
                    key = f"{text}|{phase}|{int(awaiting)}|{mode}"
                    result[key] = await _run_incoming(text, phase, awaiting, mode)
    for state in ("none", "ok", "left", "premium", "partner_premium", "failed"):
        for text in ("", "hi"):
            result[f"media:{state}|{text}"] = await _run_incoming(text, "chatting", False, "A", state)
    return result


async def collect_callbacks() -> dict[str, dict]:
    from app import handlers as h
    from app.peer import Peer

    peer = Peer(*PEER_ARGS)
    result = {}
    for kind, keys in (("room", [*h.ROOMS, "talk", ""]), ("gender", [*h.GENDERS, "x", ""])):
        for key in keys:
            for with_message in (True, False):
                h._room_choice.clear()
                h._gender_choice.clear()
                h._awaiting_age.clear()
                cb = MagicMock()
                cb.answer = AsyncMock()
                cb.message.edit_text = AsyncMock()
                cb.message.edit_reply_markup = AsyncMock()
                if not with_message:
                    cb.message = None
                gw = AsyncMock()
                with patch.object(h, "gateway", gw):
                    if kind == "room":
                        await h.choose_room(peer, cb, key)
                    else:
                        await h.choose_gender(peer, cb, key)
                entry = {
                    "answer": _calls(cb.answer, peer),
                    "gateway": _calls(gw, peer),
                    "awaiting": peer in h._awaiting_age,
                }
                if with_message:
                    entry["edit_text"] = [
                        [list(c.args)[:1], {k: _dump(v) for k, v in c.kwargs.items()}]
                        for c in cb.message.edit_text.call_args_list
                    ]
                    entry["edit_markup"] = [
                        {k: _dump(v) for k, v in c.kwargs.items()} for c in cb.message.edit_reply_markup.call_args_list
                    ]
                result[f"{kind}:{key}:{int(with_message)}"] = entry
    # Выбранные город и пол показываются при повторном открытии экранов.
    for room, gender in (("msk", "male"), ("any", "female")):
        h._room_choice.clear()
        h._gender_choice.clear()
        cb = MagicMock()
        cb.answer = AsyncMock()
        cb.message.edit_reply_markup = AsyncMock()
        with patch.object(h, "gateway", AsyncMock()):
            await h.choose_room(peer, cb, room)
            await h.choose_gender(peer, cb, gender)
        result[f"after:{room}:{gender}"] = {
            "rooms": await _run_incoming("📍 Выбрать город", "idle", False, "A"),
            "settings": await _run_incoming("⚙️ Настроить поиск", "idle", False, "A"),
            "peer_room": h.peer_room(peer),
        }
    h._room_choice.clear()
    h._gender_choice.clear()
    h._awaiting_age.clear()
    return result


def _bot_calls(bot) -> list:
    def conv(v):
        if hasattr(v, "filename") and hasattr(v, "data"):
            return {"file": v.filename, "sha256": hashlib.sha256(v.data).hexdigest()}
        if hasattr(v, "model_dump"):
            return _dump(v)
        return v

    return [
        [name, [conv(a) for a in args], {k: conv(v) for k, v in kwargs.items()}]
        for name, args, kwargs in bot.mock_calls
        if name.startswith("send_")
    ]


async def collect_gateway() -> dict[str, list]:
    from aiogram.exceptions import TelegramBadRequest

    from app.api_types import PremiumLink
    from app.gateway import Gateway
    from app.peer import Peer

    peer = Peer(*PEER_ARGS)
    until = datetime(2026, 12, 1, 22, tzinfo=timezone.utc)
    result = {}

    async def run(name: str, fn) -> None:
        bot = AsyncMock()
        gw = Gateway()
        gw.bind(bot)
        await fn(gw)
        result[name] = _bot_calls(bot)

    await run("greeting", lambda g: g.send_greeting(peer))
    await run("premium_inactive", lambda g: g.send_premium(peer, PremiumLink(PAY_URL, False, None)))
    await run("premium_active", lambda g: g.send_premium(peer, PremiumLink(PAY_URL, True, until)))
    await run("premium_active_forever", lambda g: g.send_premium(peer, PremiumLink(PAY_URL, True, None)))
    await run("pay_button", lambda g: g.send_pay_button(peer, "text", PAY_URL))
    for sel in ("", "spb", "any"):
        await run(f"rooms:{sel}", lambda g, s=sel: g.send_rooms(peer, s))
    for sel in ("", "male", "any"):
        await run(f"settings:{sel}", lambda g, s=sel: g.send_settings(peer, s))
    for kb in ("main", "chat", "partner_left", "dating", "notice"):
        await run(f"send:{kb}", lambda g, k=kb: g.send(peer, "тест", k))
    await run("notice_text", lambda g: g.send_notice(peer, "ув", photo=None))
    await run("notice_photo", lambda g: g.send_notice(peer, "ув", photo=b"img"))
    await run("media_photo", lambda g: g.send_media(peer, "photo", "image/jpeg", b"x"))
    # Баннер не ушёл: фолбэк текстом.
    bot = AsyncMock()
    bot.send_photo.side_effect = TelegramBadRequest(method=MagicMock(), message="bad request: wrong file")
    gw = Gateway()
    gw.bind(bot)
    await gw.send_greeting(peer)
    await gw.send_premium(peer, PremiumLink(PAY_URL, False, None))
    result["photo_fallback"] = _bot_calls(bot)
    return result


async def collect_events() -> dict[str, list]:
    from app import events as ev
    from app.peer import Peer

    peer = Peer(*PEER_ARGS)
    to = {"bot_key": "main", "user_id": 7}
    bodies = {
        "partner_found": {"type": "partner_found", "to": to},
        "message": {"type": "message", "to": to, "text": "hello {x}"},
        "partner_left": {"type": "partner_left", "to": to},
        "undeliverable": {"type": "partner_left", "to": to, "reason": "undeliverable"},
        "other_reason": {"type": "partner_left", "to": to, "reason": "left"},
        "unknown": {"type": "zzz", "to": to},
    }
    result = {}
    for name, body in bodies.items():
        for ok in (True, False):
            gw = AsyncMock()
            gw.send = AsyncMock(return_value=ok)
            api = MagicMock()
            api.delivery_failed = AsyncMock()
            with patch.object(ev, "gateway", gw), patch.object(ev, "chat_api", api), patch.object(
                ev, "cancel_search_timeout", MagicMock()
            ):
                await ev._deliver(body)
            result[f"{name}:{int(ok)}"] = {"gateway": _calls(gw, peer), "failed": _calls(api.delivery_failed, peer)}
    notices = {
        "notice": {"type": "notice", "to": to, "text": "  привет  "},
        "notice_empty": {"type": "notice", "to": to, "text": " "},
        "notice_other": {"type": "x", "to": to, "text": "t"},
    }
    for name, body in notices.items():
        gw = AsyncMock()
        with patch.object(ev, "gateway", gw), patch.object(ev, "_NOTICE_INTERVAL", 0), patch.object(
            ev, "_notice_photo", AsyncMock(return_value=None)
        ):
            await ev._deliver_notice(body)
        result[name] = {"gateway": _calls(gw, peer)}
    return result


def collect_all(*, old: bool = False, inputs: list[str] | None = None) -> dict:
    snapshot = {
        "texts": collect_texts(),
        "keyboards": collect_keyboards(),
        "formats": collect_formats(),
        "commands": collect_commands(),
        "incoming": asyncio.run(collect_incoming(inputs)),
        "callbacks": asyncio.run(collect_callbacks()),
        "gateway": asyncio.run(collect_gateway()),
        "events": asyncio.run(collect_events()),
    }
    if old:
        snapshot["routing"] = collect_routing_old()
    return snapshot
