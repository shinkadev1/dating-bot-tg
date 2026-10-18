"""Настройки запуска: токен бота Telegram и доступ к Chat API."""

import os

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

# Логика чата живёт в Chat API. Бот вызывает его REST и получает события по WebSocket.
CHAT_API_URL = (os.getenv("CHAT_API_URL") or "https://api.chatwithyou.site").strip().rstrip("/")
# Токен Chat API для бота Telegram: действует только за пользователей tg.
CHAT_API_TG_TOKEN = (os.getenv("CHAT_API_TG_TOKEN") or "").strip()
# Сервисный токен Cloudflare Access перед api.chatwithyou.site. Внутри Docker Compose не нужен.
CF_ACCESS_CLIENT_ID = (os.getenv("CF_ACCESS_CLIENT_ID") or "").strip()
CF_ACCESS_CLIENT_SECRET = (os.getenv("CF_ACCESS_CLIENT_SECRET") or "").strip()
# Имя потребителя событий. Постоянное, чтобы после перезапуска дочитать неподтверждённые события.
EVENTS_CONSUMER = (os.getenv("EVENTS_CONSUMER") or "tg-bot").strip()


def chat_api_headers() -> dict[str, str]:
    """Заголовки каждого запроса к Chat API: токен бота и, если задан, токен Cloudflare Access."""
    headers = {"Authorization": f"Bearer {CHAT_API_TG_TOKEN}"}
    if CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET:
        headers["CF-Access-Client-Id"] = CF_ACCESS_CLIENT_ID
        headers["CF-Access-Client-Secret"] = CF_ACCESS_CLIENT_SECRET
    return headers
