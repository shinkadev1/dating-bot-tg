# Бот Telegram

Принимает сообщения Telegram и передаёт их в Dating API (репозиторий `dating-api`).
Очередь и пары живут в Chat API. Бот ходит по HTTPS `https://api.chatwithyou.site`
через Cloudflare Access и получает события по WebSocket `/api/v1/events/tg`.

На проде контейнер `dating-tg-bot` работает на сервере chat-engine, не рядом с Chat API.

## Локально

Без Docker и без Chat API:

```sh
pip install -r requirements.txt
# в .env: TELEGRAM_BOT_TOKEN=... и DEV=true
python -m app.main
```

`.env` рядом с репозиторием читается сам. Переменные окружения процесса важнее файла,
поэтому на сервере всё работает как раньше. Токен бота берётся у @BotFather.

## DEV=true: заглушка Chat API

`DEV=true` подменяет весь обмен с Chat API (`app/mock_api.py`): REST и оба WebSocket
работают в памяти процесса, Postgres и Redis не нужны. Telegram остаётся настоящим,
чтобы проверять клавиатуру, тексты и порядок экранов.

- `/start` — фаза `searching`, через `DEV_PARTNER_DELAY` секунд приходит `partner_found`;
- сообщение собеседнику возвращается эхом через `DEV_REPLY_DELAY` (или случайной репликой при `DEV_ECHO=false`);
- фото, видео, кружок, голосовое и аудио возвращаются тем же файлом;
- `/stop`, `/next`, `/report`, жалоба и таймаут поиска работают как на проде;
- приветствие — это `flow/images/greeting.jpg` с подписью и нижней клавиатурой одним сообщением;
  если фото не ушло, приходит только текст;
- `🔍 Найти собеседника` и `🔥 Пошлый чат` показывают гейт премиума и промо
  из `flow/images/premium.png` с кнопкой оплаты; в заглушке это постоянная
  ссылка `premium_url` из `flow/flow.yaml`, с настоящим Chat API — личная ссылка
  `GET /peers/tg/{bot_key}/{user_id}/premium/link` (24 часа, только кнопкой);
  в поиск по-прежнему ставит `/start` и `Начать`;
- `📍 Выбрать город` и `⚙️ Настроить поиск` (пол → возраст) хранят выбор
  в памяти процесса и в Chat API пока не уходят, как и в боте ВК;
- `/dev_leave` — собеседник уходит, видно экран с «Новый собеседник» и «Пожаловаться»;
- `/dev_notice` — тестовая рассылка: приходит без смены клавиатуры;
- если запустить бота под двумя аккаунтами, заглушка сведёт их друг с другом;
- `CHAT_API_TG_TOKEN` и `CF_ACCESS_*` в DEV не нужны.

Все настройки заглушки — `DEV`, `DEV_PARTNER_DELAY`, `DEV_REPLY_DELAY`, `DEV_ECHO` —
описаны в `.env.example`. На проде оставьте `DEV=false`: `deploy/update.sh` не передаёт
эти переменные в контейнер.

## Тексты и кнопки: flow/flow.yaml

Все тексты, кнопки, клавиатуры, картинки (`flow/images/`), переходы и меню команд лежат в `flow/flow.yaml`,
структура описана в `flow/flow.schema.json` (version 1). Файл читает и правит CRM «Постдеск».

- Экран = узел карты (`title` и `pos` обязательны), кнопка `goto`/`next` = ребро. Кнопка с `action` вызывает код,
  с `goto` показывает другой экран без правок кода, с `url` открывает ссылку (только inline-экраны).
- Текст кнопки, её `aliases` и `/команда` — токены: один токен не может означать два разных действия.
- Новое `action`, `handler` или `on` сначала добавляется в код (`ACTIONS`/`HANDLERS` в `app/handlers.py`, `EVENTS` в `app/events.py`),
  затем во flow. Ломающие изменения формата — только с повышением `version`.
- Проверка: `python -m app.flow` (выводит «flow загружен: N экранов, M текстов», при ошибке — код 1 и путь до поля)
  и `python -m unittest discover -s tests -v`. Бот с битым flow не стартует; CI запускает обе проверки до сборки образа.

## Прод

Push в `master` собирает образ `dating-tg-bot` и перезапускает контейнер на сервере chat-engine.

Секреты GitHub:

- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- `ENV_FILE` — блок из `.env.example`: токен @BotFather, токен Chat API и сервисный токен Cloudflare Access
- `TG_DEPLOY_HOST`, `TG_DEPLOY_USER`, `TG_DEPLOY_SSH_KEY` — SSH на сервер chat-engine
- `TG_DEPLOY_PATH` — каталог бота, по умолчанию `~/dating-bot-tg`
