"""Тексты, подписи кнопок и клавиатуры Telegram.

Содержимое живёт в flow/flow.yaml; здесь оно только собирается в объекты aiogram.
Публичные имена (GREETING, IDLE_KEYBOARD, ROOMS, build_* …) сохранены для остального кода.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app import flow
from app.flow import Button, Screen


def _screen(screen_id: str) -> Screen:
    return flow.get().screen(screen_id)


def _text(key: str, **fmt: object) -> str:
    return flow.get().text(key, **fmt)


def _screen_text(screen_id: str) -> str:
    return _screen(screen_id).text or ""


def _flow_button(screen_id: str, action: str) -> Button:
    """Кнопка экрана по её действию."""
    for row in _screen(screen_id).buttons:
        for button in row:
            if button.action == action:
                return button
    raise flow.FlowError(f"screens.{screen_id}: нет кнопки с action {action!r}")


def _command_token(action: str) -> str:
    for command in flow.get().commands(dev=True):
        if command.action == action:
            return "/" + command.command
    raise flow.FlowError(f"commands: нет команды с action {action!r}")


GREETING = _screen_text("main")
# «Начать» — алиас кнопки нового собеседника (токен без «/»).
START_BTN = next(a for a in _flow_button("partner_left", "start").aliases if not a.startswith("/"))
MENU_TEXT = _screen_text("menu")

FIND_BTN = _flow_button("main", "find").text
DATING_BTN = _flow_button("main", "dating").text
PREMIUM_STATUS_BTN = _flow_button("main", "premium").text

DATING_FIND_BTN = _flow_button("dating", "dating_find").text
DATING_ROOMS_BTN = _flow_button("dating", "dating_rooms").text
DATING_SETTINGS_BTN = _flow_button("dating", "dating_settings").text
MAIN_MENU_BTN = _flow_button("dating", "main").text

CHAT_BTN_NEXT = _flow_button("chat", "next").text
CHAT_BTN_STOP = _flow_button("chat", "stop").text
NEW_PARTNER_BTN = _flow_button("partner_left", "start").text
PREMIUM_BTN = _flow_button("chat", "premium").text
REPORT_BTN = _flow_button("partner_left", "report").text

SEARCHING_TEXT = _text("searching")
NO_PARTNERS_TEXT = _text("no_partners")
FOUND_TEXT = _screen_text("chat")
STOPPED_TEXT = _text("stopped")
PARTNER_LEFT_TEXT = _screen_text("partner_left")
PHOTO_LOCKED_TEXT = _screen_text("photo_locked")
REPORT_SENT_TEXT = _text("report_sent")
UNDELIVERED_TEXT = _screen_text("undelivered")
SERVICE_DOWN_TEXT = _text("service_down")
MEDIA_FAILED_TEXT = _text("media_failed")

# Запасная ссылка, если Chat API не выдал личную. Ссылки уходят только кнопкой, не текстом.
PREMIUM_URL = _text("premium_url")
MEDIA_PREMIUM_TEXT = _text("media_premium")
PARTNER_NO_PREMIUM_TEXT = _text("partner_no_premium")
PREMIUM_STATUS_TEXT = _screen_text("premium")
DATING_TEXT = _screen_text("dating")
# Раньше здесь были комнаты; имена ROOMS/room оставлены, теперь это города.
ROOMS_TEXT = _screen_text("rooms")
ROOMS: dict[str, str] = dict(_screen("rooms").options.items)
ROOM_ROWS = _screen("rooms").options.rows
DEFAULT_ROOM = _screen("rooms").options.default
SETTINGS_TEXT = _screen_text("settings")
GENDERS: dict[str, str] = dict(_screen("settings").options.items)
AGE_TEXT = _screen_text("age")

# Команды только для DEV=true: проверка экранов, которые иначе приходят от собеседника.
DEV_LEAVE_COMMAND = _command_token("dev_leave")
DEV_NOTICE_COMMAND = _command_token("dev_notice")
DEV_NOTICE_TEXT = _text("dev_notice")

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


def _inline_style(style: str | None) -> str | None:
    return style if style in _BUTTON_STYLES else None


def build_reply(screen_id: str) -> ReplyKeyboardMarkup:
    """Нижняя клавиатура экрана: ряды и цвета из flow."""
    rows = [[_button(b.text, style=b.style) for b in row] for row in _screen(screen_id).buttons]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# Нижняя клавиатура не умеет ссылки, поэтому премиум здесь — кнопка с текстом:
# нажатие уходит в обработчик и он присылает промо с кнопкой оплаты.
IDLE_KEYBOARD = build_reply("main")
DATING_KEYBOARD = build_reply("dating")
CHAT_KEYBOARD = build_reply("chat")
PARTNER_LEFT_KEYBOARD = build_reply("partner_left")

# Даты премиума показываем по Москве.
_PREMIUM_TZ = timezone(timedelta(hours=3))


# Тарифы: (plan, подпись кнопки). Цены меняются только в flow/flow.yaml, экран premium.
PREMIUM_PLANS: tuple[tuple[str, str], ...] = tuple(
    (b.plan, b.text) for row in _screen("premium").buttons for b in row if b.plan
)


def with_plan(url: str, plan: str) -> str:
    """Добавляет plan в query ссылки оплаты, сохраняя остальные параметры."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "plan"]
    query.append(("plan", plan))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _inline_button(button: Button, premium_url: str) -> InlineKeyboardButton:
    """Inline-кнопка: ссылка (с подстановкой {premium_url} и plan), переход go:<экран> или действие act:<имя>."""
    style = _inline_style(button.style)
    if button.url is not None:
        url = button.url.replace("{premium_url}", premium_url)
        if button.plan:
            url = with_plan(url, button.plan)
        return InlineKeyboardButton(text=button.text, url=url, style=style)
    if button.goto is not None:
        return InlineKeyboardButton(text=button.text, callback_data=f"{flow.GOTO_PREFIX}{button.goto}", style=style)
    return InlineKeyboardButton(text=button.text, callback_data=f"{flow.ACTION_PREFIX}{button.action}", style=style)


def build_inline(
    screen_id: str,
    *,
    premium_url: str | None = None,
    skip_plans: frozenset[str] = frozenset(),
) -> InlineKeyboardMarkup:
    """Inline-клавиатура экрана из его кнопок. skip_plans — тарифы, которых в этот раз не показываем."""
    link = premium_url or PREMIUM_URL
    rows = [
        [_inline_button(b, link) for b in row if b.plan not in skip_plans]
        for row in _screen(screen_id).buttons
    ]
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def build_options(screen_id: str, selected: str) -> InlineKeyboardMarkup:
    """Inline-выбор из options экрана: выбранный вариант отмечен selected_mark."""
    options = _screen(screen_id).options
    mark = f" {options.selected_mark}" if options.selected_mark else ""
    rows = [
        [
            InlineKeyboardButton(
                text=options.items[key] + (mark if key == selected else ""),
                callback_data=options.data(key),
                style=_inline_style(options.styles.get(key)),
            )
            for key in row
        ]
        for row in options.rows
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_markup(screen_id: str, *, premium_url: str | None = None) -> ReplyKeyboardMarkup | InlineKeyboardMarkup | None:
    """Клавиатура экрана по его описанию. Нет кнопок — None: прежняя клавиатура остаётся."""
    screen = _screen(screen_id)
    if screen.options is not None:
        return build_options(screen_id, screen.options.default or "")
    if not screen.buttons:
        return None
    if screen.kind == "inline":
        return build_inline(screen_id, premium_url=premium_url)
    return build_reply(screen_id)


def build_premium_keyboard(url: str, *, trial: bool = True) -> InlineKeyboardMarkup:
    """Кнопки тарифов: ряды как в flow (пробный отдельно, неделя и месяц парой, год отдельно).

    trial=False (премиум уже активен) — без пробного, только продление.
    """
    return build_inline("premium", premium_url=url, skip_plans=frozenset() if trial else frozenset({"trial"}))


def format_premium_active(until: datetime | None) -> str:
    """Статус для того, у кого премиум уже есть."""
    if until is None:
        return _text("premium_active")
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return _text("premium_active_until", date=f"{until.astimezone(_PREMIUM_TZ):%d.%m.%Y}")


def build_rooms_keyboard(selected: str) -> InlineKeyboardMarkup:
    """Inline-выбор города: выбранный отмечен галочкой."""
    return build_options("rooms", selected)


def build_settings_keyboard(selected: str) -> InlineKeyboardMarkup:
    """Inline-выбор пола собеседника: выбранный вариант отмечен галочкой."""
    return build_options("settings", selected)


def format_partner(text: str) -> str:
    """Оформляет реплику так, будто её прислал собеседник."""
    return _text("partner_message", text=text)
