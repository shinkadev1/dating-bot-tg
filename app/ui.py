"""Тексты, подписи кнопок и клавиатуры Telegram."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

GREETING = (
    "👋 Привет! Это чат для анонимных знакомств, флирта и легкого общения\n"
    "Найди собеседника прямо сейчас: отправь /start"
)
START_BTN = "Начать"
MENU_TEXT = "Найди собеседника прямо сейчас"

FIND_BTN = "🔍 Найти собеседника"
DATING_BTN = "💘 Чат знакомств"
PREMIUM_STATUS_BTN = "👑 Премиум статус"

DATING_FIND_BTN = "❤️ Найти девушку"
DATING_ROOMS_BTN = "🌍 Выбрать комнату"
DATING_SETTINGS_BTN = "⚙️ Настроить поиск"
MAIN_MENU_BTN = "◀️ Главное меню"

CHAT_BTN_NEXT = "➡️ Следующий собеседник"
CHAT_BTN_STOP = "🛑 Закончить диалог"
NEW_PARTNER_BTN = "🔍 Новый собеседник"
PREMIUM_BTN = "💎 Купить премиум"
REPORT_BTN = "🚫 Пожаловаться"

SEARCHING_TEXT = "🔎 Ищем собеседника..."
NO_PARTNERS_TEXT = "Сейчас собеседников нет, приходите чуть позже 😔"
FOUND_TEXT = "💬 Собеседник найден. Вы можете писать ему сюда 👇"
STOPPED_TEXT = "Диалог остановлен. Отправь /start, чтобы начать снова."
PARTNER_LEFT_TEXT = (
    "Собеседник закончил диалог 😔\n\n"
    "Пожалуйста, нажмите Пожаловаться, если встретили спам."
)
REPORT_SENT_TEXT = "Жалоба отправлена. Спасибо, что сообщили."
UNDELIVERED_TEXT = "❌ Собеседник недоступен, диалог закончен.\nОтправь /start, чтобы найти нового собеседника."
SERVICE_DOWN_TEXT = "Сервис временно недоступен. Попробуй через минуту."
MEDIA_FAILED_TEXT = "Не получилось сохранить медиа. Отправь ещё раз."

PREMIUM_URL = "https://clck.su/cDapp"
MEDIA_PREMIUM_TEXT = f"Чтобы отправлять медиа, получите премиум:\n{PREMIUM_URL}"
PREMIUM_STATUS_TEXT = (
    "⚡ Временная акция, скидка 99%:\n\n"
    "🍓 Настройка поиска: например, только девушки младше 25 лет\n"
    "💋 Комнаты для общения по тематике: флирт, знакомства\n"
    "📹 Отправка и получение любых фото, видео и голосовых без ограничений\n"
    "🔝 Первое место в поиске\n"
    "🚫 Никакой рекламы"
)
DATING_TEXT = "👑 Для продолжения нужен Премиум"
ROOMS_TEXT = "✌️ Выберите комнату, в которой хотите искать собеседников:"
ROOMS: dict[str, str] = {
    "spb": "Встречи в г. Санкт-Петербург",
    "talk": "Общение",
    "photo": "Обмен фото",
    "voice": "Голоса",
    "naughty": "Пошлый",
    "dating": "Знакомства",
}
ROOM_ROWS = (("spb",), ("talk", "photo"), ("voice", "naughty"), ("dating",))
DEFAULT_ROOM = "spb"
SETTINGS_TEXT = (
    "💎 Только для Премиум-пользователей\n\n"
    "👱‍♀️👱 Пожалуйста, выберите желаемый пол собеседника:\n\n"
    "🔍 Бот будет искать собеседников только с заданными параметрами поиска"
)
GENDERS: dict[str, str] = {
    "female": "👱‍♀️ Женский",
    "male": "👱‍♂️ Мужской",
    "any": "Не важно",
}
AGE_TEXT = (
    "✏️ Введите желаемый возраст собеседника\n\n"
    "ℹ️ Вы можете настроить поиск \"от 26\" введя \"26+\", "
    "или указать диапазон поиска, например, \"24-34\""
)

# Команды только для DEV=true: проверка экранов, которые иначе приходят от собеседника.
DEV_LEAVE_COMMAND = "/dev_leave"
DEV_NOTICE_COMMAND = "/dev_notice"
DEV_NOTICE_TEXT = "Уведомление из заглушки. Клавиатура диалога не меняется."

# Telegram принимает только эти цвета кнопок. Другое значение отклоняет всю клавиатуру.
_BUTTON_STYLES = {"primary", "success", "danger"}


def _button(text: str, *, style: str | None = None) -> KeyboardButton:
    """Цветная кнопка, если клиент Telegram понимает style. Иначе обычная."""
    if style not in _BUTTON_STYLES or "style" not in getattr(KeyboardButton, "model_fields", {}):
        return KeyboardButton(text=text)
    try:
        return KeyboardButton(text=text, style=style)
    except (TypeError, ValueError):
        return KeyboardButton(text=text)


# Нижняя клавиатура не умеет ссылки, поэтому премиум здесь — кнопка с текстом:
# нажатие уходит в обработчик и он присылает промо с кнопкой оплаты.
IDLE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [_button(FIND_BTN, style="primary"), _button(DATING_BTN, style="primary")],
        [_button(PREMIUM_STATUS_BTN, style="success")],
    ],
    resize_keyboard=True,
)
DATING_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [_button(DATING_FIND_BTN, style="primary"), _button(DATING_ROOMS_BTN, style="primary")],
        [_button(DATING_SETTINGS_BTN, style="primary"), _button(MAIN_MENU_BTN)],
    ],
    resize_keyboard=True,
)
CHAT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [_button(CHAT_BTN_NEXT)],
        [_button(PREMIUM_BTN, style="success")],
        [_button(CHAT_BTN_STOP)],
    ],
    resize_keyboard=True,
)
PARTNER_LEFT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [_button(NEW_PARTNER_BTN, style="primary")],
        [_button(REPORT_BTN)],
    ],
    resize_keyboard=True,
)

PREMIUM_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text=PREMIUM_BTN, url=PREMIUM_URL)]]
)


def build_rooms_keyboard(selected: str) -> InlineKeyboardMarkup:
    """Inline-выбор комнаты: выбранная отмечена галочкой."""
    rows: list[list[InlineKeyboardButton]] = []
    for row in ROOM_ROWS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=ROOMS[key] + (" ✅" if key == selected else ""),
                    callback_data=f"room:{key}",
                )
                for key in row
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_settings_keyboard(selected: str) -> InlineKeyboardMarkup:
    """Inline-выбор пола собеседника: выбранный вариант отмечен галочкой."""

    def button(key: str, *, style: str | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=GENDERS[key] + (" ✅" if key == selected else ""),
            callback_data=f"gender:{key}",
            style=style,
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[[button("female", style="primary"), button("male", style="primary")], [button("any")]]
    )


def format_partner(text: str) -> str:
    """Оформляет реплику так, будто её прислал собеседник."""
    return f"👤 Собеседник:\n{text}"
