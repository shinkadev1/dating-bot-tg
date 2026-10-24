"""Запуск бота Telegram: Long Polling и доставка событий Chat API."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.api_client import ChatApiError, chat_api
from app.config import CHAT_API_TG_TOKEN, CHAT_API_URL, DEV, TELEGRAM_BOT_TOKEN
from app.events import consume_broadcasts, consume_events
from app.gateway import gateway
from app.handlers import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("tg_bot")

_COMMANDS = [
    BotCommand(command="start", description="Найти собеседника"),
    BotCommand(command="next", description="Следующий собеседник"),
    BotCommand(command="stop", description="Закончить диалог"),
]
if DEV:
    _COMMANDS += [
        BotCommand(command="dev_leave", description="DEV: собеседник уходит"),
        BotCommand(command="dev_notice", description="DEV: тестовая рассылка"),
    ]


async def _run() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Не задан TELEGRAM_BOT_TOKEN.")
    if not CHAT_API_TG_TOKEN and not DEV:
        raise SystemExit("Не задан CHAT_API_TG_TOKEN: без него Chat API не примет запросы бота.")
    if DEV:
        logger.warning("DEV=true: Chat API замокан, очередь и события живут в памяти процесса")

    bot = Bot(TELEGRAM_BOT_TOKEN)
    events: asyncio.Task[None] | None = None
    broadcasts: asyncio.Task[None] | None = None
    try:
        me = await bot.get_me()
        gateway.bind(bot)
        await bot.set_my_commands(_COMMANDS)
        try:
            title = f"@{me.username}" if me.username else ""
            await chat_api.register_channel("tg", str(me.id), title)
        except ChatApiError:
            logger.warning("Не записал бота Telegram в список чатов", exc_info=True)

        dispatcher = Dispatcher()
        dispatcher.include_router(router)

        events = asyncio.create_task(consume_events(), name="chat-events")
        broadcasts = asyncio.create_task(consume_broadcasts(), name="chat-broadcasts")
        logger.info(
            "Бот @%s (id=%s), Chat API %s",
            me.username,
            me.id,
            "заглушка (DEV)" if DEV else CHAT_API_URL,
        )
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        for task in (events, broadcasts):
            if task is not None:
                task.cancel()
        for task in (events, broadcasts):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        await chat_api.aclose()
        await bot.session.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
