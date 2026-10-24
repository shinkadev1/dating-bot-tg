"""Настройки запуска: токен бота Telegram, доступ к Chat API и режим разработки.

Файл `.env` рядом с репозиторием читается сам. Переменные окружения процесса
важнее файла, поэтому в Docker Compose поведение не меняется.
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Добавляет в окружение переменные из `.env`, не затирая уже заданные."""
    paths = [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    for path in dict.fromkeys(paths):
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            if text.startswith("export "):
                text = text[len("export ") :].lstrip()
            key, separator, value = text.partition("=")
            if not separator:
                continue
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


def _env(name: str) -> str | None:
    """Значение переменной без учёта регистра ключа в `.env`."""
    for key in (name, name.upper(), name.lower()):
        value = os.getenv(key)
        if value is not None:
            return value
    return None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip().replace(",", "."))
    except ValueError:
        return default


_load_dotenv()

TELEGRAM_BOT_TOKEN = (_env("TELEGRAM_BOT_TOKEN") or "").strip()

# Логика чата живёт в Chat API. Бот вызывает его REST и получает события по WebSocket.
CHAT_API_URL = (_env("CHAT_API_URL") or "https://api.chatwithyou.site").strip().rstrip("/")
# Токен Chat API для бота Telegram: действует только за пользователей tg.
CHAT_API_TG_TOKEN = (_env("CHAT_API_TG_TOKEN") or "").strip()
# Сервисный токен Cloudflare Access перед api.chatwithyou.site. Внутри Docker Compose не нужен.
CF_ACCESS_CLIENT_ID = (_env("CF_ACCESS_CLIENT_ID") or "").strip()
CF_ACCESS_CLIENT_SECRET = (_env("CF_ACCESS_CLIENT_SECRET") or "").strip()
# Имя потребителя событий. Постоянное, чтобы после перезапуска дочитать неподтверждённые события.
EVENTS_CONSUMER = (_env("EVENTS_CONSUMER") or "tg-bot").strip()

# DEV=true подменяет Chat API заглушкой: REST и WebSocket работают в памяти процесса.
# Telegram остаётся настоящим, чтобы можно было проверять клавиатуру и тексты.
DEV = _env_bool("DEV")
# Через сколько секунд заглушка «находит» собеседника и отвечает на сообщения.
DEV_PARTNER_DELAY = _env_float("DEV_PARTNER_DELAY", 2.0)
DEV_REPLY_DELAY = _env_float("DEV_REPLY_DELAY", 1.5)
# true — собеседник-заглушка повторяет присланный текст.
DEV_ECHO = _env_bool("DEV_ECHO", True)


def chat_api_headers() -> dict[str, str]:
    """Заголовки каждого запроса к Chat API: токен бота и, если задан, токен Cloudflare Access."""
    headers = {"Authorization": f"Bearer {CHAT_API_TG_TOKEN}"}
    if CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET:
        headers["CF-Access-Client-Id"] = CF_ACCESS_CLIENT_ID
        headers["CF-Access-Client-Secret"] = CF_ACCESS_CLIENT_SECRET
    return headers
