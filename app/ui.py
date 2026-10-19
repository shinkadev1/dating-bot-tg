"""Тексты, подписи кнопок и клавиатуры Telegram."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

GREETING = (
    "👋 Привет! Это чат для анонимных знакомств, флирта и легкого общения\n"
    "Найди собеседника прямо сейчас. Нажми кнопку «Начать»"
)
START_BTN = "Начать"

CHAT_BTN_NEXT = "➡️ Следующий собеседник"
CHAT_BTN_STOP = "🛑 Закончить диалог"
NEW_PARTNER_BTN = "🔍 Новый собеседник"
REPORT_BTN = "🚫 Пожаловаться"

SEARCHING_TEXT = "🔎 Ищем собеседника..."
NO_PARTNERS_TEXT = "Сейчас собеседников нет, приходите чуть позже 😔"
FOUND_TEXT = "💬 Собеседник найден. Вы можете писать ему сюда 👇"
STOPPED_TEXT = "Диалог остановлен. Нажми «Начать», чтобы начать снова."
PARTNER_LEFT_TEXT = (
    "Собеседник закончил диалог 😔\n\n"
    "Пожалуйста, нажмите Пожаловаться, если встретили спам."
)
REPORT_SENT_TEXT = "Жалоба отправлена. Спасибо, что сообщили."
UNDELIVERED_TEXT = "❌ Собеседник недоступен, диалог закончен.\nНажми «Начать», чтобы найти нового собеседника."
SERVICE_DOWN_TEXT = "Сервис временно недоступен. Попробуй через минуту."
MEDIA_FAILED_TEXT = "Не получилось сохранить медиа. Отправь ещё раз."


def _button(text: str, *, style: str | None = None) -> KeyboardButton:
    """Синяя кнопка, если клиент Telegram понимает style. Иначе обычная."""
    if not style or "style" not in getattr(KeyboardButton, "model_fields", {}):
        return KeyboardButton(text=text)
    try:
        return KeyboardButton(text=text, style=style)
    except (TypeError, ValueError):
        return KeyboardButton(text=text)


IDLE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=START_BTN)]],
    resize_keyboard=True,
)
CHAT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=CHAT_BTN_NEXT)], [KeyboardButton(text=CHAT_BTN_STOP)]],
    resize_keyboard=True,
)
PARTNER_LEFT_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [_button(NEW_PARTNER_BTN, style="primary")],
        [_button(REPORT_BTN)],
    ],
    resize_keyboard=True,
)


def format_partner(text: str) -> str:
    """Оформляет реплику так, будто её прислал собеседник."""
    return f"👤 Собеседник:\n{text}"
