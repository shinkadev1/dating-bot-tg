#!/bin/sh
# Бот Telegram на сервере chat-engine: пишет .env из секретов, скачивает образ и перезапускает.
set -eu

cd "$(dirname "$0")/.."

for key in TG_BOT_IMAGE TELEGRAM_BOT_TOKEN CHAT_API_TG_TOKEN CF_ACCESS_CLIENT_ID CF_ACCESS_CLIENT_SECRET; do
  eval "value=\${$key:-}"
  if [ -z "$value" ]; then
    echo "Не задан ${key}." >&2
    exit 1
  fi
done

umask 077
{
  printf 'TG_BOT_IMAGE=%s\n' "$TG_BOT_IMAGE"
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN"
  printf 'CHAT_API_URL=%s\n' "${CHAT_API_URL:-https://api.chatwithyou.site}"
  printf 'CHAT_API_TG_TOKEN=%s\n' "$CHAT_API_TG_TOKEN"
  printf 'CF_ACCESS_CLIENT_ID=%s\n' "$CF_ACCESS_CLIENT_ID"
  printf 'CF_ACCESS_CLIENT_SECRET=%s\n' "$CF_ACCESS_CLIENT_SECRET"
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
