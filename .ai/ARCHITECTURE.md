# Архитектура dating-bot-tg

Проверено: **2026-10-31**.

## Поток данных

Telegram → aiogram handlers → HTTPS Chat API через Cloudflare Access. Обратно: `/api/v1/events/tg` и `/api/v1/broadcasts/tg` → gateway → Telegram.

## Точки входа

| Путь | Ответственность |
| --- | --- |
| `app/main.py` | Запуск aiogram и потребителей событий. |
| `app/handlers.py` | Маршрутизация по `flow.action_for`, реестры `ACTIONS`/`HANDLERS`, переходы goto, поиск, премиум, города, настройки. |
| `app/flow.py` | Загрузка и проверка `flow/flow.yaml` по `flow/flow.schema.json`; `python -m app.flow`. |
| `app/ui.py` | Сборка клавиатур aiogram из flow; прежние публичные имена (`GREETING`, `IDLE_KEYBOARD`, `ROOMS` …). |
| `app/gateway.py` | Отправка ответов, баннеров и медиа. |
| `app/api_client.py` | REST Chat API. |
| `app/api_types.py` | Типы API. |
| `app/events.py` | WebSocket-события и рассылки; реестр `EVENTS`. |
| `app/media.py` | Telegram-медиа и ссылки на файлы. |
| `app/paylink.py` | Личная ссылка оплаты премиума из Chat API, запасная `PREMIUM_URL`. |
| `app/mock_api.py` | In-memory заглушка REST/событий. |
| `app/config.py` | Настройки, DEV и заголовки API. |

## Контракты и ограничения

- Кнопка «Найти собеседника» запускает поиск: `handlers.py`, коммит `2eb955a`. README и старый handoff с премиум-гейтом для этой кнопки устарели.
- «🔥 Пошлый чат» (бывшая «❤️ Найти девушку», маршрут dating_find; старая подпись принимается как алиас) — отдельный сценарий премиум-промо; не объединять его поведение с обычным поиском без задачи.
- Комнаты, пол и возраст находятся в памяти процесса, не влияют на серверный подбор.
- Сохранять ack событий, переподключение и раздельную обработку notice и сообщений собеседника.

## Flow

`flow/flow.yaml` описывает экраны (`title`, `pos`, `text`, `image`, `buttons`, `next`, `handler`, `on`, `options`), служебные `texts` и меню `commands`; `flow/images/` — картинки. Схема `flow/flow.schema.json` (version 1) общая с ботом ВК и читается CRM «Постдеск». Код регистрирует `ACTIONS`, `HANDLERS`, `EVENTS`; их равенство набору во flow проверяют тесты и CI. Бот не стартует с битым flow (`FlowError`).

## Развёртывание

Push в `master` запускает `.github/workflows/deploy.yml`: job `validate` (`python -m app.flow`, unittest) → `publish` → `deploy`; серверное обновление — `deploy/update.sh`. Образ копирует `flow/` в `/app/flow`.

Схема описывает репозиторий, а не подтверждённое состояние production.
