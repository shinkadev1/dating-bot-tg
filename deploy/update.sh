#!/bin/sh
# Бот Telegram на сервере chat-engine: пишет .env из секрета ENV_FILE, скачивает образ и перезапускает.
set -eu

cd "$(dirname "$0")/.."

# Строка KEY=value из секрета ENV_FILE. Комментарии и пустые строки не попадают в выборку.
secret_value() {
  key=$1
  if [ -n "${ENV_FILE_B64:-}" ]; then
    printf '%s' "$ENV_FILE_B64" | base64 -d | tr -d '\r'
  elif [ -n "${ENV_FILE:-}" ]; then
    printf '%s\n' "$ENV_FILE" | tr -d '\r'
  fi | sed -n "s/^[[:space:]]*${key}=//p" | tail -n 1 | sed 's/^"//;s/"$//'
}

# Уже заданная переменная окружения важнее файла: так локальный запуск не ломается.
require_setting() {
  key=$1
  eval "value=\${$key:-}"
  if [ -z "$value" ]; then
    value=$(secret_value "$key")
  fi
  if [ -z "$value" ]; then
    echo "В ENV_FILE нет ${key}." >&2
    exit 1
  fi
  printf '%s=%s\n' "$key" "$value"
}

if [ -z "${TG_BOT_IMAGE:-}" ]; then
  echo "Не задан TG_BOT_IMAGE." >&2
  exit 1
fi

chat_api_url=$(secret_value CHAT_API_URL)
if [ -z "$chat_api_url" ]; then
  chat_api_url=${CHAT_API_URL:-https://api.chatwithyou.site}
fi

umask 077
{
  printf 'TG_BOT_IMAGE=%s\n' "$TG_BOT_IMAGE"
  require_setting TELEGRAM_BOT_TOKEN
  printf 'CHAT_API_URL=%s\n' "$chat_api_url"
  require_setting CHAT_API_TG_TOKEN
  require_setting CF_ACCESS_CLIENT_ID
  require_setting CF_ACCESS_CLIENT_SECRET
} > .env

compose() {
  docker compose -p dating-tg-bot -f docker-compose.yml --env-file .env "$@"
}

if [ -n "${DOCKERHUB_USERNAME:-}" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
  printf '%s' "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
fi
compose pull
docker logout >/dev/null 2>&1 || true
compose up -d --force-recreate --remove-orphans

sleep 10
docker logs dating-tg-bot --tail 30 2>&1 | grep -E "Бот @|Читаю события|WebSocket|Не задан|Unauthorized|ERROR|Traceback" || true
restarts=$(docker inspect -f '{{.RestartCount}}' dating-tg-bot)
running=$(docker inspect -f '{{.State.Running}}' dating-tg-bot)
if [ "$running" != "true" ] || [ "$restarts" -gt 0 ]; then
  echo "Бот Telegram не запустился (running=${running}, restarts=${restarts})." >&2
  exit 1
fi

# Старые образы бота. Образы chat-engine на этом сервере не трогаются.
current_tag=${TG_BOT_IMAGE##*:}
docker images --format '{{.Repository}}:{{.Tag}}' | grep '/dating-tg-bot:' | grep -v ":${current_tag}\$" \
  | xargs -r docker rmi >/dev/null 2>&1 || true
