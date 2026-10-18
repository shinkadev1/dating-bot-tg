# Бот Telegram

Принимает сообщения Telegram и передаёт их в Dating API (репозиторий `dating-api`).
Очередь и пары живут в Chat API. Бот ходит по HTTPS `https://api.chatwithyou.site`
через Cloudflare Access и получает события по WebSocket `/api/v1/events/tg`.

На проде контейнер `dating-tg-bot` работает на сервере chat-engine, не рядом с Chat API.

## Прод

Push в `master` собирает образ `dating-tg-bot` и перезапускает контейнер на сервере chat-engine.

Секреты GitHub:

- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `TELEGRAM_BOT_TOKEN` — токен @BotFather
- `CHAT_API_TG_TOKEN` — тот же токен, что принимает Chat API для пользователей tg
- `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` — сервисный токен Cloudflare Access
- `TG_DEPLOY_HOST`, `TG_DEPLOY_USER`, `TG_DEPLOY_SSH_KEY` — SSH на сервер chat-engine
- `TG_DEPLOY_PATH` — каталог бота, по умолчанию `~/dating-bot-tg`

Локально бот можно запустить без Docker, если Chat API доступен напрямую:

```sh
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:CHAT_API_URL="http://127.0.0.1:8000"
$env:CHAT_API_TG_TOKEN="local-tg-token-change-me"
python -m app.main
```
