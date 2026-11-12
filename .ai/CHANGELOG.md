# История важных изменений

## 2026-10-31 — оркестрация и фиксация контекста

Добавлены .codex/config.toml и explorer/planner/developer/reviewer/reporter, правила routing и workflow в AGENTS.md. Модель planner/reviewer — gpt-6-astra/high по подтверждённому выбору пользователя. Обновлены правила и память; контекст и конфигурация сохраняются отдельным локальным коммитом без прикладных изменений и push. Проверки: 42 TOML, строгая загрузка конфигураций в 7 корнях, diff check, reviewer PASS; mobile typecheck прошёл. Запуск всех ролей и ESLint не проверены (ESLint не настроен).

## 2026-10-31 — локальный контекст репозитория

Добавлены PROJECT, ARCHITECTURE, CONVENTIONS, CURRENT_TASK, STATE и CHANGELOG в .ai/; AGENTS.md направляет к ним будущие сессии. Комплект описывает именно dating-bot-tg и не требует соседних репозиториев для начала работы. Существующие инструкции сохранены.

Код и деплой не менялись. Проверки контекста и ограничения отражены в [STATE.md](STATE.md).

Историческая точка исходников: `master` / `2eb955a`. Это не подтверждение деплоя или отсутствия незакоммиченных изменений.

## 2026-11-03 — личная ссылка оплаты премиума

Кнопки «Купить премиум» (промо, гейт «Найти девушку», ответ на медиа без премиума) открывают личную ссылку из `GET /api/v1/peers/tg/{bot_key}/{user_id}/premium/link` (vk-bot, ветка payments) вместо постоянной `PREMIUM_URL`. Ссылка действует 24 часа, запрашивается на каждый показ и уходит только inline-кнопкой, не текстом. При ошибке или 503 — предупреждение в лог и постоянная `PREMIUM_URL`; DEV-заглушка всегда отвечает как 503. С активным премиумом бот показывает срок (дата по UTC+3) вместо продажи; отказ медиа при активном премиуме у автора объясняется отсутствием премиума у собеседника. Ветка `paylink`, файлы: `app/api_client.py`, `app/api_types.py`, `app/mock_api.py`, `app/paylink.py`, `app/ui.py`, `app/gateway.py`, `app/handlers.py`, `tests/test_paylink.py`. Проверки: `python -m unittest discover -s tests` — 12 тестов OK; `compileall app tests` OK. Не проверено: настоящий Chat API и Telegram.

## 2026-11-11 — flow/flow.yaml

Пользовательские тексты, кнопки, клавиатуры, картинки, переходы и меню команд бота переехали в `flow/flow.yaml` (+ `flow/flow.schema.json`, `flow/images`): CRM «Постдеск» читает и правит файл в GitHub и рисует карту бота. Поведение для пользователя не менялось: эквивалентность подтверждена снимком кода до перехода (`tests/fixtures/ui_snapshot.json`). Новое: `app/flow.py` (загрузка, схема, проверки), общий рендер экранов goto/next без кода, реестры `ACTIONS`/`HANDLERS`/`EVENTS`, тест «нет пользовательских литералов в коде», job `validate` в CI. Файлы: `app/flow.py`, `app/ui.py`, `app/handlers.py`, `app/gateway.py`, `app/events.py`, `app/main.py`, `flow/`, `tests/`, `Dockerfile`, `requirements.txt`, `.github/workflows/deploy.yml`, `deploy/update.sh`. Проверки: `python -m app.flow`, `python -m unittest discover -s tests -v`. Не проверено: docker build, деплой.

## 2026-11-11 — защитные проверки flow (доработка по ревью)

Inline-кнопка `act:<действие>` выполняется напрямую раннером по имени (`run_action`, реестр `_ACTION_RUNNERS`), а не через текст кнопки: при ожидании возраста `next/stop/report` не превращаются в подсказку про возраст; `dev_*` — только при DEV. Новое во flow-загрузке: `Flow.check_registries` (сверка action/handler/on с кодом в обе стороны; вызывается при импорте `app.main` и в `python -m app.flow`), `_check_texts`/`TEXT_FIELDS` (поля шаблонов texts), экран с `options` без `handler` — FlowError. `aiogram>=3.31,<3.32` (снимок model_dump). Схема не менялась. Проверки: `python -m app.flow`, `python -m unittest discover -s tests` (85 OK), импорт `app.main` с DEV=true/false.

## Формат следующих записей

Дата, изменение и причина, затронутые контракты, коммит/файлы и реальные проверки. Текущие планы хранить в CURRENT_TASK; актуальные ограничения — в STATE.

## 2026-11-12 — промо премиума после 10 диалогов (не выкачено)

Событие `promo` в `app/events.py` (EVENTS), экран `premium_promo` во `flow/flow.yaml`, `send_screen(..., premium_url=)` в `app/gateway.py`, тест `tests/test_promo_event.py`. При активном премиуме ничего не отправляется. Проверки: `python -m app.flow`, unittest 90 OK.
