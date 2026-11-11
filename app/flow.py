"""Карта бота из flow/flow.yaml: экраны, кнопки, тексты, переходы и меню команд.

Файл читается один раз при старте, проверяется по flow/flow.schema.json и по связям
(экраны, картинки, лимиты Telegram). Любая ошибка — FlowError с путём до поля.
`python -m app.flow` печатает сводку и возвращает код 1 при ошибке: так flow проверяет CI.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

logger = logging.getLogger(__name__)

FLOW_DIR = Path(__file__).resolve().parent.parent / "flow"
SCHEMA_NAME = "flow.schema.json"

# Лимиты Telegram.
CALLBACK_MAX_BYTES = 64
CAPTION_MAX = 1024

# Префиксы callback_data у кнопок, которые строит общий рендер экрана.
GOTO_PREFIX = "go:"
ACTION_PREFIX = "act:"


class FlowError(Exception):
    """flow.yaml не прошёл проверку."""


@dataclass(frozen=True)
class Button:
    text: str
    action: str | None = None
    goto: str | None = None
    url: str | None = None
    style: str | None = None
    aliases: tuple[str, ...] = ()
    next: str | None = None
    payload: dict[str, Any] | None = None
    plan: str | None = None


@dataclass(frozen=True)
class Options:
    """Динамическая inline-клавиатура: варианты из items, выбранный отмечается selected_mark."""

    callback: str
    items: dict[str, str]
    rows: tuple[tuple[str, ...], ...]
    default: str | None = None
    selected_mark: str = ""
    styles: dict[str, str] = field(default_factory=dict)

    @property
    def prefix(self) -> str:
        """Начало callback_data до ключа: «room:» из «room:{key}»."""
        return self.callback.split("{key}", 1)[0]

    def data(self, key: str) -> str:
        return self.callback.replace("{key}", key)


@dataclass(frozen=True)
class Screen:
    id: str
    title: str
    text: str | None = None
    image: str | None = None
    keyboard: str | None = None
    buttons: tuple[tuple[Button, ...], ...] = ()
    buttons_from: str | None = None
    next: str | None = None
    handler: str | None = None
    on: str | None = None
    options: Options | None = None
    pos: tuple[int, int] | None = None
    dev: bool = False

    @property
    def kind(self) -> str:
        """Вид клавиатуры: reply по умолчанию."""
        return self.keyboard or "reply"


@dataclass(frozen=True)
class Command:
    command: str
    description: str
    action: str
    dev: bool = False


def _norm(token: str) -> str:
    return token.strip().lower()


class Flow:
    def __init__(
        self,
        *,
        version: int,
        bot: str,
        start: str,
        screens: dict[str, Screen],
        texts: dict[str, str],
        dev_texts: frozenset[str],
        commands: tuple[Command, ...],
        root: Path,
        action_tokens: dict[str, str],
        goto_tokens: dict[str, str],
    ) -> None:
        self.version = version
        self.bot = bot
        self.start = start
        self.screens = screens
        self.texts = texts
        self.dev_texts = dev_texts
        self.root = root
        self._commands = commands
        self._action_tokens = action_tokens
        self._goto_tokens = goto_tokens
        self._images: dict[str, bytes | None] = {}

    def screen(self, screen_id: str) -> Screen:
        try:
            return self.screens[screen_id]
        except KeyError:
            raise FlowError(f"нет экрана {screen_id!r}") from None

    def text(self, key: str, **fmt: object) -> str:
        """Служебный текст. Поля {имя} подставляются из fmt; без fmt текст возвращается как есть."""
        try:
            template = self.texts[key]
        except KeyError:
            raise FlowError(f"нет текста {key!r}") from None
        return template.format(**fmt) if fmt else template

    def image(self, screen_id: str) -> bytes | None:
        """Байты картинки экрана. Нет картинки или файла — None: текст важнее баннера."""
        if screen_id not in self._images:
            name = self.screen(screen_id).image
            data: bytes | None = None
            if name:
                try:
                    data = (self.root / name).read_bytes() or None
                except OSError as exc:
                    logger.warning("Нет картинки %s: %s", name, exc)
            self._images[screen_id] = data
        return self._images[screen_id]

    def action_for(self, token: str) -> str | None:
        """Действие по тексту кнопки, её алиасу или «/команде» (регистр и пробелы по краям не важны)."""
        return self._action_tokens.get(_norm(token))

    def goto_for(self, token: str) -> str | None:
        """Экран, на который ведёт кнопка goto с таким текстом."""
        return self._goto_tokens.get(_norm(token))

    def token_for(self, action: str) -> str | None:
        """Любой токен действия (для повторного запуска из inline-кнопки)."""
        for token, name in self._action_tokens.items():
            if name == action:
                return token
        return None

    def actions(self) -> frozenset[str]:
        found = {b.action for s in self.screens.values() for row in s.buttons for b in row if b.action}
        found |= {c.action for c in self._commands}
        return frozenset(found)

    def handlers(self) -> frozenset[str]:
        return frozenset(s.handler for s in self.screens.values() if s.handler)

    def events(self) -> frozenset[str]:
        return frozenset(s.on for s in self.screens.values() if s.on)

    def commands(self, dev: bool = False) -> list[Command]:
        return [c for c in self._commands if dev or not c.dev]


# ---------------------------------------------------------------- загрузка


class _Loader(yaml.SafeLoader):
    """YAML без сюрпризов: bool только true/false (on/yes/no остаются строками), дубли ключей — ошибка."""

    def construct_mapping(self, node, deep=False):  # type: ignore[no-untyped-def]
        seen: set[object] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise FlowError(f"строка {key_node.start_mark.line + 1}: повторяется ключ {key!r}")
            seen.add(key)
        return super().construct_mapping(node, deep)


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))


def _path(parts: Any) -> str:
    out = ""
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "<root>"


def _read_schema() -> dict[str, Any]:
    return json.loads((FLOW_DIR / SCHEMA_NAME).read_text(encoding="utf-8"))


def _validate(data: Any) -> None:
    validator = Draft202012Validator(_read_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        first = errors[0]
        raise FlowError(f"{_path(first.absolute_path)}: {first.message}")


def _resolve_buttons(raw: dict[str, Any], sid: str, chain: tuple[str, ...] = ()) -> tuple[tuple[Button, ...], ...]:
    """Кнопки экрана: свои или скопированные из buttons_from (цепочка и циклы проверяются)."""
    source = raw[sid]
    if "buttons_from" not in source:
        return tuple(
            tuple(
                Button(
                    text=b["text"],
                    action=b.get("action"),
                    goto=b.get("goto"),
                    url=b.get("url"),
                    style=b.get("style"),
                    aliases=tuple(b.get("aliases", ())),
                    next=b.get("next"),
                    payload=b.get("payload"),
                    plan=b.get("plan"),
                )
                for b in row
            )
            for row in source.get("buttons", ())
        )
    ref = source["buttons_from"]
    if ref not in raw:
        raise FlowError(f"screens.{sid}.buttons_from: нет экрана {ref!r}")
    if ref in chain or ref == sid:
        raise FlowError(f"screens.{sid}.buttons_from: цикл через {ref!r}")
    return _resolve_buttons(raw, ref, (*chain, sid))


def _build_options(raw: dict[str, Any]) -> Options:
    items = dict(raw["items"])
    rows = tuple(tuple(r) for r in raw.get("rows") or [[k] for k in items])
    return Options(
        callback=raw["callback"],
        items=items,
        rows=rows,
        default=raw.get("default"),
        selected_mark=raw.get("selected_mark", ""),
        styles=dict(raw.get("styles", {})),
    )


def load(path: Path | str | None = None) -> Flow:
    """Читает и проверяет flow.yaml. Картинки ищутся относительно каталога файла."""
    flow_path = Path(path) if path is not None else FLOW_DIR / "flow.yaml"
    try:
        text = flow_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FlowError(f"{flow_path}: не прочитать файл: {exc}") from exc
    try:
        data = yaml.load(text, Loader=_Loader)  # noqa: S506 — SafeLoader с запретом дублей
    except yaml.YAMLError as exc:
        raise FlowError(f"{flow_path}: неверный YAML: {exc}") from exc
    _validate(data)

    root = flow_path.parent
    raw_screens: dict[str, Any] = data["screens"]
    start = data["start"]
    if start not in raw_screens:
        raise FlowError(f"start: нет экрана {start!r}")

    screens: dict[str, Screen] = {}
    for sid, raw in raw_screens.items():
        pos = raw.get("pos")
        screens[sid] = Screen(
            id=sid,
            title=raw["title"],
            text=raw.get("text"),
            image=raw.get("image"),
            keyboard=raw.get("keyboard"),
            buttons=_resolve_buttons(raw_screens, sid),
            buttons_from=raw.get("buttons_from"),
            next=raw.get("next"),
            handler=raw.get("handler"),
            on=raw.get("on"),
            options=_build_options(raw["options"]) if "options" in raw else None,
            pos=(pos["x"], pos["y"]) if pos else None,
            dev=raw.get("dev", False),
        )

    action_tokens: dict[str, str] = {}
    goto_tokens: dict[str, str] = {}
    owner: dict[str, str] = {}

    def register(token: str, kind: str, value: str, where: str) -> None:
        key = _norm(token)
        label = f"{kind}:{value}"
        if key in owner and owner[key] != label:
            raise FlowError(f"{where}: токен {token!r} уже занят ({owner[key]}), здесь {label}")
        owner[key] = label
        (action_tokens if kind == "action" else goto_tokens)[key] = value

    for sid, raw in raw_screens.items():
        screen = screens[sid]
        where = f"screens.{sid}"
        for field_name in ("next", "buttons_from"):
            target = getattr(screen, field_name)
            if target is not None and target not in screens:
                raise FlowError(f"{where}.{field_name}: нет экрана {target!r}")
        if screen.image and not (root / screen.image).is_file():
            raise FlowError(f"{where}.image: нет файла {screen.image}")
        if screen.image and screen.text and len(screen.text) > CAPTION_MAX:
            raise FlowError(f"{where}.text: подпись к картинке длиннее {CAPTION_MAX} символов")
        if screen.options:
            options = screen.options
            if "{key}" not in options.callback:
                raise FlowError(f"{where}.options.callback: нет {{key}}")
            for key in options.items:
                if len(options.data(key).encode()) > CALLBACK_MAX_BYTES:
                    raise FlowError(f"{where}.options.callback: для {key!r} длиннее {CALLBACK_MAX_BYTES} байт")
            for index, row in enumerate(options.rows):
                for key in row:
                    if key not in options.items:
                        raise FlowError(f"{where}.options.rows[{index}]: нет варианта {key!r} в items")
            if options.default is not None and options.default not in options.items:
                raise FlowError(f"{where}.options.default: нет варианта {options.default!r} в items")
            for key in options.styles:
                if key not in options.items:
                    raise FlowError(f"{where}.options.styles: нет варианта {key!r} в items")
        own = "buttons_from" not in raw_screens[sid]
        for r, row in enumerate(screen.buttons):
            for b, button in enumerate(row):
                spot = f"{where}.buttons[{r}][{b}]"
                if not own:
                    spot = f"{where}.buttons_from -> {spot}"
                for field_name in ("goto", "next"):
                    target = getattr(button, field_name)
                    if target is not None and target not in screens:
                        raise FlowError(f"{spot}.{field_name}: нет экрана {target!r}")
                if screen.kind == "reply":
                    if button.url:
                        raise FlowError(f"{spot}.url: в reply-клавиатуре нет кнопок-ссылок")
                    tokens = (button.text, *button.aliases)
                    for token in tokens:
                        if button.action:
                            register(token, "action", button.action, f"{spot}.text")
                        elif button.goto:
                            register(token, "goto", button.goto, f"{spot}.text")
                elif button.goto and len(f"{GOTO_PREFIX}{button.goto}".encode()) > CALLBACK_MAX_BYTES:
                    raise FlowError(f"{spot}.goto: callback длиннее {CALLBACK_MAX_BYTES} байт")
                elif button.action and len(f"{ACTION_PREFIX}{button.action}".encode()) > CALLBACK_MAX_BYTES:
                    raise FlowError(f"{spot}.action: callback длиннее {CALLBACK_MAX_BYTES} байт")

    commands: list[Command] = []
    for index, raw in enumerate(data.get("commands", ())):
        command = Command(raw["command"], raw["description"], raw["action"], raw.get("dev", False))
        register("/" + command.command, "action", command.action, f"commands[{index}].command")
        commands.append(command)

    texts: dict[str, str] = {}
    dev_texts: set[str] = set()
    for key, value in data.get("texts", {}).items():
        if isinstance(value, dict):
            texts[key] = value["text"]
            if value.get("dev"):
                dev_texts.add(key)
        else:
            texts[key] = value

    return Flow(
        version=data["version"],
        bot=data["bot"],
        start=start,
        screens=screens,
        texts=texts,
        dev_texts=frozenset(dev_texts),
        commands=tuple(commands),
        root=root,
        action_tokens=action_tokens,
        goto_tokens=goto_tokens,
    )


# ---------------------------------------------------------------- общий экземпляр

_flow: Flow | None = None


def get() -> Flow:
    """Загруженная карта: читается и проверяется один раз."""
    global _flow
    if _flow is None:
        _flow = load()
    return _flow


def main() -> int:
    try:
        current = load()
    except FlowError as exc:
        print(f"FlowError: {exc}", file=sys.stderr)
        return 1
    print(f"flow загружен: {len(current.screens)} экранов, {len(current.texts)} текстов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
