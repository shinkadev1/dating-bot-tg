"""Личная ссылка оплаты: клиент Chat API, запасная ссылка и кнопки бота."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

os.environ["DEV"] = "false"

import httpx  # noqa: E402

from app import handlers, media, paylink  # noqa: E402
from app.api_client import ChatApiClient, ChatApiError, NotPremiumError, PremiumLink  # noqa: E402
from app.gateway import Gateway  # noqa: E402
from app.peer import Peer  # noqa: E402
from app.ui import (  # noqa: E402
    MEDIA_PREMIUM_TEXT,
    PARTNER_NO_PREMIUM_TEXT,
    PREMIUM_URL,
    build_premium_keyboard,
    format_premium_active,
    with_plan,
)

PEER = Peer("123", 42)
CHECKOUT = "https://pay.example.test/checkout/tok?utm_source=tg&utm_campaign=premium"
PAY_URL = "https://pay.example.test/?utm_source=tg&utm_campaign=premium&utm_content=tok"


def client_with(handler) -> ChatApiClient:
    client = ChatApiClient("https://api.example.test", {"Authorization": "Bearer test"})
    client._http = httpx.AsyncClient(
        base_url="https://api.example.test/api/v1",
        headers={"Authorization": "Bearer test"},
        transport=httpx.MockTransport(handler),
    )
    return client


def button_url(markup) -> str:
    return markup.inline_keyboard[0][0].url


def layout(markup) -> list[list[str]]:
    return [[b.text for b in row] for row in markup.inline_keyboard]


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_route_and_parsing(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={"url": PAY_URL, "premium_active": True, "premium_until": "2026-12-01T10:00:00Z"},
            )

        link = await client_with(handler).premium_link(PEER)
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(seen[0].url.path, "/api/v1/peers/tg/123/42/premium/link")
        self.assertEqual(seen[0].headers["authorization"], "Bearer test")
        self.assertEqual(link.url, PAY_URL)
        self.assertTrue(link.premium_active)
        self.assertEqual(link.premium_until, datetime(2026, 12, 1, 10, tzinfo=timezone.utc))

    async def test_null_until(self) -> None:
        link = await client_with(
            lambda _: httpx.Response(200, json={"url": PAY_URL, "premium_active": False, "premium_until": None})
        ).premium_link(PEER)
        self.assertIsNone(link.premium_until)

    async def test_503_and_bad_body_raise(self) -> None:
        with self.assertRaises(ChatApiError):
            await client_with(lambda _: httpx.Response(503, json={"detail": "x"})).premium_link(PEER)
        with self.assertRaises(ChatApiError):
            await client_with(lambda _: httpx.Response(200, json={"premium_active": False})).premium_link(PEER)


class OfferTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_to_static_url(self) -> None:
        api = AsyncMock()
        api.premium_link.side_effect = ChatApiError("HTTP 503")
        with patch.object(paylink, "chat_api", api), self.assertLogs("app.paylink", "WARNING"):
            offer = await paylink.premium_offer(PEER)
        self.assertEqual(offer, PremiumLink(PREMIUM_URL, False, None))

    async def test_personal_url(self) -> None:
        api = AsyncMock()
        api.premium_link.return_value = PremiumLink(PAY_URL, False, None)
        with patch.object(paylink, "chat_api", api):
            self.assertEqual((await paylink.premium_offer(PEER)).url, PAY_URL)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = AsyncMock()
        self.gateway = Gateway()
        self.gateway.bind(self.bot)

    async def test_promo_carries_personal_button_not_text(self) -> None:
        await self.gateway.send_premium(PEER, PremiumLink(PAY_URL, False, None))
        call = self.bot.send_photo.call_args
        markup = call.kwargs["reply_markup"]
        self.assertEqual(
            layout(markup),
            [["🎁 Пробный 3 дня — 1 ₽"], ["Неделя — 299 ₽", "Месяц — 999 ₽"], ["Год — 2999 ₽"]],
        )
        self.assertEqual(button_url(markup), PAY_URL + "&plan=trial")
        self.assertNotIn("http", call.kwargs["caption"])

    async def test_active_premium_shows_status_without_sale(self) -> None:
        until = datetime(2026, 12, 1, 22, tzinfo=timezone.utc)
        await self.gateway.send_premium(PEER, PremiumLink(PAY_URL, True, until))
        self.bot.send_photo.assert_not_called()
        args = self.bot.send_message.call_args
        self.assertEqual(args.args[1], "💎 Премиум активен до 02.12.2026")
        markup = args.kwargs["reply_markup"]
        self.assertEqual(layout(markup), [["Неделя — 299 ₽", "Месяц — 999 ₽"], ["Год — 2999 ₽"]])
        urls = [b.url for row in markup.inline_keyboard for b in row]
        self.assertEqual(urls, [PAY_URL + f"&plan={p}" for p in ("week", "month", "year")])

    def test_plan_urls(self) -> None:
        markup = build_premium_keyboard(CHECKOUT)
        urls = [b.url for row in markup.inline_keyboard for b in row]
        self.assertEqual(urls, [CHECKOUT + f"&plan={p}" for p in ("trial", "week", "month", "year")])
        fallback = build_premium_keyboard(PREMIUM_URL)
        self.assertEqual(button_url(fallback), PREMIUM_URL + "?plan=trial")
        self.assertEqual(with_plan(CHECKOUT + "&plan=old", "year"), CHECKOUT + "&plan=year")

    async def test_pay_button(self) -> None:
        await self.gateway.send_pay_button(PEER, MEDIA_PREMIUM_TEXT, PAY_URL)
        args = self.bot.send_message.call_args
        self.assertNotIn("http", args.args[1])
        self.assertEqual(len(args.kwargs["reply_markup"].inline_keyboard), 3)
        self.assertEqual(button_url(args.kwargs["reply_markup"]), PAY_URL + "&plan=trial")


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_premium_reply_has_pay_button(self) -> None:
        gw = AsyncMock()
        offer = AsyncMock(return_value=PremiumLink(PAY_URL, False, None))
        with patch.object(handlers, "gateway", gw), patch.object(handlers, "premium_offer", offer):
            await handlers.send_media_premium(PEER)
        gw.send_pay_button.assert_awaited_once_with(PEER, MEDIA_PREMIUM_TEXT, PAY_URL)

    async def test_media_premium_with_active_premium_blames_partner(self) -> None:
        gw = AsyncMock()
        offer = AsyncMock(return_value=PremiumLink(PAY_URL, True, None))
        with patch.object(handlers, "gateway", gw), patch.object(handlers, "premium_offer", offer):
            await handlers.send_media_premium(PEER)
        gw.send.assert_awaited_once_with(PEER, PARTNER_NO_PREMIUM_TEXT, "chat")
        gw.send_pay_button.assert_not_called()

    async def test_gate_skips_sale_text_for_active_premium(self) -> None:
        gw = AsyncMock()
        active = PremiumLink(PAY_URL, True, None)
        with patch.object(handlers, "gateway", gw), patch.object(handlers, "premium_offer", AsyncMock(return_value=active)):
            await handlers.send_premium_gate(PEER)
        gw.send.assert_not_called()
        gw.send_premium.assert_awaited_once_with(PEER, active)

    async def test_partner_detail_skips_pay_link(self) -> None:
        gw = AsyncMock()
        offer = AsyncMock()
        with patch.object(handlers, "gateway", gw), patch.object(handlers, "premium_offer", offer):
            await handlers.send_media_premium(PEER, partner=True)
        offer.assert_not_called()
        gw.send.assert_awaited_once_with(PEER, PARTNER_NO_PREMIUM_TEXT, "chat")
        gw.send_pay_button.assert_not_called()

    def test_media_state_from_403_detail(self) -> None:
        partner = NotPremiumError('{"detail":"Собеседник без премиума не может получать медиа"}')
        own = NotPremiumError('{"detail":"Фото, видео и аудио можно отправлять только с премиумом"}')
        self.assertEqual(media._premium_state(PEER, partner), "partner_premium")
        self.assertEqual(media._premium_state(PEER, own), "premium")

    def test_status_without_date(self) -> None:
        self.assertEqual(format_premium_active(None), "💎 Премиум активен")


if __name__ == "__main__":
    unittest.main()
