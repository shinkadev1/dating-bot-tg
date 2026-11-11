"""Тексты, подписи кнопок и клавиатуры Telegram.

Сами тексты, подписи, списки, раскладка клавиатур и картинки лежат в app/content/content.json
(редактируются в Bot CRM). Здесь — только сборка клавиатур и имена, которые использует код.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app import content
from app.content import button, items, text

GREETING = text("GREETING")
START_BTN = button("START_BTN")
MENU_TEXT = text("MENU_TEXT")

FIND_BTN = button("FIND_BTN")
DATING_BTN = button("DATING_BTN")
PREMIUM_STATUS_BTN = button("PREMIUM_STATUS_BTN")

DATING_FIND_BTN = button("DATING_FIND_BTN")
DATING_ROOMS_BTN = button("DATING_ROOMS_BTN")
DATING_SETTINGS_BTN = button("DATING_SETTINGS_BTN")
MAIN_MENU_BTN = button("MAIN_MENU_BTN")

CHAT_BTN_NEXT = button("CHAT_BTN_NEXT")
CHAT_BTN_STOP = button("CHAT_BTN_STOP")
NEW_PARTNER_BTN = button("NEW_PARTNER_BTN")
PREMIUM_BTN = button("PREMIUM_BTN")
REPORT_BTN = button("REPORT_BTN")

SEARCHING_TEXT = text("SEARCHING_TEXT")
NO_PARTNERS_TEXT = text("NO_PARTNERS_TEXT")
FOUND_TEXT = text("FOUND_TEXT")
STOPPED_TEXT = text("STOPPED_TEXT")
PARTNER_LEFT_TEXT = text("PARTNER_LEFT_TEXT")
REPORT_SENT_TEXT = text("REPORT_SENT_TEXT")
UNDELIVERED_TEXT = text("UNDELIVERED_TEXT")
SERVICE_DOWN_TEXT = text("SERVICE_DOWN_TEXT")
MEDIA_FAILED_TEXT = text("MEDIA_FAILED_TEXT")

# Запасная ссылка, если Chat API не выдал личную. Ссылки уходят только кнопкой, не текстом.
PREMIUM_URL = "https://pay.chatwithyou.site/"
MEDIA_PREMIUM_TEXT = text("MEDIA_PREMIUM_TEXT")
PARTNER_NO_PREMIUM_TEXT = text("PARTNER_NO_PREMIUM_TEXT")
PREMIUM_STATUS_TEXT = text("PREMIUM_STATUS_TEXT")
PREMIUM_ACTIVE_TEXT = text("PREMIUM_ACTIVE_TEXT")
PREMIUM_ACTIVE_UNTIL_TEXT = text("PREMIUM_ACTIVE_UNTIL_TEXT")
DATING_TEXT = text("DATING_TEXT")
# Раньше здесь были комнаты; имена ROOMS/room оставлены, теперь это города.
ROOMS_TEXT = text("ROOMS_TEXT")
ROOMS: dict[str, str] = items("ROOMS")
# Раскладка городов берётся из клавиатуры ROOMS_KEYBOARD.
ROOM_ROWS = tuple(tuple(cell["item"] for cell in row) for row in content.keyboard("ROOMS_KEYBOARD")["rows"])
DEFAULT_ROOM = "spb"
SETTINGS_TEXT = text("SETTINGS_TEXT")
GENDERS: dict[str, str] = items("GENDERS")
AGE_TEXT = text("AGE_TEXT")
ROOMS_REFRESHED_TOAST = text("ROOMS_REFRESHED_TOAST")
CITY_SELECTED_TOAST = text("CITY_SELECTED_TOAST")
COMMAND_START = text("COMMAND_START")
COMMAND_NEXT = text("COMMAND_NEXT")
COMMAND_STOP = text("COMMAND_STOP")

# Команды только для DEV=true: проверка экранов, которые иначе приходят от собеседника.
DEV_LEAVE_COMMAND = "/dev_leave"
DEV_NOTICE_COMMAND = "/dev_notice"
DEV_NOTICE_TEXT = "Уведомление из заглушки. Клавиатура диалога не меняется."

# Telegram принимает только эти цвета кнопок. Другое значение отклоняет всю клавиатуру.
_BUTTON_STYLES = {"primary", "success", "danger"}


def _style(cell: dict) -> str | None:
    """Цвет из content.json в стиль Telegram; «secondary» и пусто — обычная кнопка."""
    color = cell.get("color")
    return color if color in _BUTTON_STYLES else None


def _button(text: str, *, style: str | None = None) -> KeyboardButton:
    """Цветная кнопка, если клиент Telegram понимает style. Иначе обычная."""
    if style not in _BUTTON_STYLES or "style" not in getattr(KeyboardButton, "model_fields", {}):
        return KeyboardButton(text=text)
    try:
        return KeyboardButton(text=text, style=style)
    except (TypeError, ValueError):
        return KeyboardButton(text=text)


def _reply_keyboard(name: str) -> ReplyKeyboardMarkup:
    """Нижняя клавиатура из content.json."""
    rows = content.keyboard(name)["rows"]
    return ReplyKeyboardMarkup(
        keyboard=[[_button(content.label(cell), style=_style(cell)) for cell in row] for row in rows],
        resize_keyboard=True,
    )


# Нижняя клавиатура не умеет ссылки, поэтому премиум здесь — кнопка с текстом:
# нажатие уходит в обработчик и он присылает промо с кнопкой оплаты.
IDLE_KEYBOARD = _reply_keyboard("IDLE_KEYBOARD")
DATING_KEYBOARD = _reply_keyboard("DATING_KEYBOARD")
CHAT_KEYBOARD = _reply_keyboard("CHAT_KEYBOARD")
PARTNER_LEFT_KEYBOARD = _reply_keyboard("PARTNER_LEFT_KEYBOARD")

# Даты премиума показываем по Москве.
_PREMIUM_TZ = timezone(timedelta(hours=3))


# Тарифы: (plan, подпись кнопки). Подписи и цены — в content.json, lists.PREMIUM_PLANS.
PREMIUM_PLANS: tuple[tuple[str, str], ...] = tuple(items("PREMIUM_PLANS").items())


def with_plan(url: str, plan: str) -> str:
    """Добавляет plan в query ссылки оплаты, сохраняя остальные параметры."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "plan"]
    query.append(("plan", plan))
    return urlunsplit(parts._replace(query=urlencode(query)))


def build_premium_keyboard(url: str, *, trial: bool = True) -> InlineKeyboardMarkup:
    """Кнопки тарифов по раскладке PREMIUM_KEYBOARD.

    trial=False (премиум уже активен) — без пробного, только продление.
    """
    rows = [
        [
            InlineKeyboardButton(text=content.label(cell), url=with_plan(url, cell["item"]))
            for cell in row
            if trial or cell["item"] != "trial"
        ]
        for row in content.keyboard("PREMIUM_KEYBOARD")["rows"]
    ]
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def format_premium_active(until: datetime | None) -> str:
    """Статус для того, у кого премиум уже есть."""
    if until is None:
        return PREMIUM_ACTIVE_TEXT
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return PREMIUM_ACTIVE_UNTIL_TEXT.replace("{date}", f"{until.astimezone(_PREMIUM_TZ):%d.%m.%Y}")


def build_rooms_keyboard(selected: str) -> InlineKeyboardMarkup:
    """Inline-выбор города: выбранный отмечен галочкой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=content.label(cell) + (" ✅" if cell["item"] == selected else ""),
                    callback_data=f"room:{cell['item']}",
                )
                for cell in row
            ]
            for row in content.keyboard("ROOMS_KEYBOARD")["rows"]
        ]
    )


def build_settings_keyboard(selected: str) -> InlineKeyboardMarkup:
    """Inline-выбор пола собеседника: выбранный вариант отмечен галочкой."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=content.label(cell) + (" ✅" if cell["item"] == selected else ""),
                    callback_data=f"gender:{cell['item']}",
                    style=_style(cell),
                )
                for cell in row
            ]
            for row in content.keyboard("SETTINGS_KEYBOARD")["rows"]
        ]
    )


def city_selected_toast(room: str) -> str:
    """Всплывающая подсказка после выбора города."""
    return CITY_SELECTED_TOAST.replace("{city}", ROOMS[room])


def format_partner(text: str) -> str:
    """Оформляет реплику так, будто её прислал собеседник."""
    return content.text("PARTNER_MESSAGE").replace("{text}", text)
