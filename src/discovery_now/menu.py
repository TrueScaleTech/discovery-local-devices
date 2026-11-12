"""An interactive menu over the command line.

``discoverynow menu`` lists every command, lets you move through them with the
arrow keys, fill in any of their options, and run the result. It is built from the
command line itself rather than described a second time, so a command or an option
added to the CLI shows up here with no extra work, and the two can never disagree.

Everything the menu runs goes through the ordinary command parser, so a value is
checked exactly as it would be on the command line, and the exact command it ran is
shown, which makes the menu a way of learning the CLI as much as of using it.

The module is split so that the parts that matter can be tested without a terminal:
reading the command tree, building the arguments, and the navigation itself, which
talks to a :class:`Terminal` that a test replaces with a scripted one.
"""

from __future__ import annotations

import contextlib
import enum
import os
import pathlib
import shlex
import subprocess
import sys
import types
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import typer
from rich.console import Console, Group, RenderableType
from rich.text import Text

from . import APP_NAME

PROGRAM = "discoverynow"

#: The command that opens this menu is left out of it: it would open itself.
_SKIPPED_COMMANDS = frozenset({"menu"})

#: Options that belong to the program as a whole rather than to one command.
_GLOBAL_NAMES = frozenset({"config"})


# ---------------------------------------------------------------------------
# What a command looks like to the menu
# ---------------------------------------------------------------------------


class Kind(enum.Enum):
    """How a parameter is edited."""

    FLAG = "flag"  # on or off: --force
    TOGGLE = "toggle"  # unset, on or off: --online / --offline
    TEXT = "text"
    INT = "int"
    FLOAT = "float"
    PATH = "path"
    CHOICE = "choice"


@dataclass(slots=True)
class Param:
    """One option or argument of a command, as the menu needs to know it."""

    name: str
    label: str
    kind: Kind
    help: str = ""
    required: bool = False
    multiple: bool = False
    positional: bool = False
    default: Any = None
    choices: tuple[str, ...] = ()
    on: str | None = None
    off: str | None = None
    flag: str | None = None

    @property
    def hint(self) -> str:
        """A short note on what to type, for the line under the form."""
        kinds = {
            Kind.INT: "a whole number",
            Kind.FLOAT: "a number",
            Kind.PATH: "a file or folder path",
            Kind.TEXT: "text",
        }
        if self.kind is Kind.CHOICE:
            return "one of: " + ", ".join(self.choices)
        if self.kind is Kind.TOGGLE:
            return f"{self.on} or {self.off}, or leave unset"
        if self.kind is Kind.FLAG:
            return "on or off"
        base = kinds.get(self.kind, "text")
        return f"{base}, may be given several times" if self.multiple else base


@dataclass(slots=True)
class Node:
    """A command, or a group of commands."""

    name: str
    help: str
    path: tuple[str, ...]
    params: list[Param] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)

    @property
    def is_group(self) -> bool:
        return bool(self.children)


def _first_line(text: str | None) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _base_type(annotation: Any) -> Any:
    """The type that matters inside ``X | None``, ``list[X]`` and friends."""
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _base_type(typing.get_args(annotation)[0])
    if origin in (typing.Union, types.UnionType):
        rest = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        return _base_type(rest[0]) if len(rest) == 1 else None
    if origin in (list, tuple, set, frozenset):
        args = typing.get_args(annotation)
        return _base_type(args[0]) if args else None
    return annotation if isinstance(annotation, type) else None


def _annotation(parameter: Any) -> Any:
    """The Python type a parameter was declared with, when the parser says so.

    Typer keeps it on ``type_descriptor``. Where it is missing or has changed
    shape, the parameter is treated as plain text and the real parser still checks
    what is typed, so a change there makes the menu less helpful, not wrong.
    """
    return getattr(getattr(parameter, "type_descriptor", None), "annotation", None)


def _classify(parameter: Any) -> tuple[Kind, tuple[str, ...]]:
    """Work out how to edit a parameter, and the allowed values if it has a list."""
    if getattr(parameter, "is_flag", False):
        return (Kind.TOGGLE if getattr(parameter, "secondary_opts", None) else Kind.FLAG), ()
    base = _base_type(_annotation(parameter))
    if isinstance(base, type):
        if issubclass(base, enum.Enum):
            return Kind.CHOICE, tuple(str(member.value) for member in base)
        if issubclass(base, bool):
            return Kind.FLAG, ()
        if issubclass(base, int):
            return Kind.INT, ()
        if issubclass(base, float):
            return Kind.FLOAT, ()
        if issubclass(base, pathlib.PurePath):
            return Kind.PATH, ()
    return Kind.TEXT, ()


def _to_param(parameter: Any) -> Param | None:
    """Describe one parser parameter, or None if it is not for the user to set."""
    if getattr(parameter, "hidden", False) or getattr(parameter, "is_eager", False):
        return None
    kind, choices = _classify(parameter)
    positional = getattr(parameter, "param_type_name", "") == "argument"
    name = str(parameter.name)
    default = getattr(parameter, "default", None)
    help_text = str(getattr(parameter, "help", "") or "")

    if positional:
        return Param(
            name=name,
            label=name.upper(),
            kind=kind,
            help=help_text,
            required=bool(getattr(parameter, "required", False)),
            positional=True,
            choices=choices,
        )

    opts = list(getattr(parameter, "opts", []) or [])
    secondary = list(getattr(parameter, "secondary_opts", []) or [])
    long_flags = [opt for opt in opts if opt.startswith("--")]
    return Param(
        name=name,
        label=" / ".join([opts[0], secondary[0]]) if kind is Kind.TOGGLE else ", ".join(opts),
        kind=kind,
        help=help_text,
        required=bool(getattr(parameter, "required", False)),
        multiple=bool(getattr(parameter, "multiple", False)),
        default=default if default not in (None, False, (), []) else None,
        choices=choices,
        on=opts[0] if opts else None,
        off=secondary[0] if secondary else None,
        flag=(long_flags or opts or [None])[0],
    )


def _to_node(name: str, command: Any, path: tuple[str, ...]) -> Node:
    node = Node(name=name, help=_first_line(getattr(command, "help", "")), path=path)
    for parameter in getattr(command, "params", []):
        described = _to_param(parameter)
        if described is not None:
            node.params.append(described)
    subcommands = getattr(command, "commands", None)
    if subcommands:
        for child_name, child in subcommands.items():
            if not path and child_name in _SKIPPED_COMMANDS:
                continue
            node.children.append(_to_node(child_name, child, (*path, child_name)))
    return node


def build_tree(group: Any) -> tuple[Node, list[Param]]:
    """Read the command tree and the program-wide options from the parser."""
    root = _to_node(PROGRAM, group, ())
    global_params = [param for param in root.params if param.name in _GLOBAL_NAMES]
    root.params = []
    return root, global_params


# ---------------------------------------------------------------------------
# Turning choices into a command line
# ---------------------------------------------------------------------------

Values = dict[str, Any]


def _option_arguments(param: Param, value: Any) -> list[str]:
    """The command-line words that express one chosen value."""
    if param.kind is Kind.FLAG:
        return [param.on] if value and param.on else []
    if param.kind is Kind.TOGGLE:
        if value is True and param.on:
            return [param.on]
        if value is False and param.off:
            return [param.off]
        return []

    items = value if isinstance(value, list) else [value]
    flag = param.flag or param.on
    words: list[str] = []
    for item in items:
        text = str(item)
        if flag is None:
            continue
        # A value that starts with a dash would be read as another option.
        words.extend([f"{flag}={text}"] if text.startswith("-") else [flag, text])
    return words


def build_arguments(
    node: Node,
    values: Values,
    global_params: Sequence[Param] = (),
    global_values: Values | None = None,
) -> list[str]:
    """The full argument list for running ``node`` with the chosen values."""
    arguments: list[str] = []
    for param in global_params:
        if param.name in (global_values or {}):
            arguments.extend(_option_arguments(param, (global_values or {})[param.name]))
    arguments.extend(node.path)

    positional: list[str] = []
    for param in node.params:
        value = values.get(param.name)
        if value in (None, "", []):
            continue
        if param.positional:
            positional.extend(value if isinstance(value, list) else [str(value)])
        else:
            arguments.extend(_option_arguments(param, value))

    if positional:
        # So that a value like "-x" is read as an argument and not as an option.
        if any(item.startswith("-") for item in positional):
            arguments.append("--")
        arguments.extend(positional)
    return arguments


def missing_required(node: Node, values: Values) -> list[Param]:
    """The required parameters that have not been given a value."""
    return [
        param
        for param in node.params
        if param.required and values.get(param.name) in (None, "", [])
    ]


def command_line(arguments: Sequence[str]) -> str:
    """The arguments as a line a person could paste into a terminal."""
    if os.name == "nt":
        words = [subprocess.list2cmdline([argument]) for argument in arguments]
        return " ".join([PROGRAM, *words])
    return " ".join([PROGRAM, *(shlex.quote(argument) for argument in arguments)])


def check_value(param: Param, text: str) -> str | None:
    """Why ``text`` is not acceptable for ``param``, or None if it is.

    Only the shape is checked here, so a typo is caught while still typing. The
    command parser has the last word when the command runs.
    """
    try:
        if param.kind is Kind.INT:
            int(text)
        elif param.kind is Kind.FLOAT:
            float(text)
        elif param.kind is Kind.CHOICE and text not in param.choices:
            return "choose one of: " + ", ".join(param.choices)
    except ValueError:
        return "that is not a number"
    return None


# ---------------------------------------------------------------------------
# Keys and the terminal
# ---------------------------------------------------------------------------

_KEYS: dict[str, str] = {
    "\x1b[A": "up", "\x1bOA": "up", "\xe0H": "up", "\x00H": "up",
    "\x1b[B": "down", "\x1bOB": "down", "\xe0P": "down", "\x00P": "down",
    "\x1b[D": "left", "\x1bOD": "left", "\xe0K": "left", "\x00K": "left",
    "\x1b[C": "right", "\x1bOC": "right", "\xe0M": "right", "\x00M": "right",
    "\x1b[H": "home", "\x1bOH": "home", "\xe0G": "home", "\x00G": "home",
    "\x1b[F": "end", "\x1bOF": "end", "\xe0O": "end", "\x00O": "end",
    "\x1b[3~": "delete", "\xe0S": "delete", "\x00S": "delete",
    "\r": "enter", "\n": "enter", "\r\n": "enter",
    "\x1b": "esc",
    "\x7f": "backspace", "\x08": "backspace",
}  # fmt: skip


def normalize_key(raw: str) -> str:
    """Give a key the same name on every platform and terminal.

    Windows and Unix report the arrow keys with different byte sequences; the menu
    only ever sees the names ``up``, ``down``, ``enter`` and so on, or the
    character itself for an ordinary key.
    """
    if raw in _KEYS:
        return _KEYS[raw]
    return raw if len(raw) == 1 else "other"


class Terminal(Protocol):
    """What the menu needs from a screen and a keyboard."""

    @property
    def ascii_only(self) -> bool: ...

    @property
    def height(self) -> int: ...

    def clear(self) -> None: ...
    def show(self, renderable: RenderableType) -> None: ...
    def key(self) -> str: ...
    def ask(self, label: str, default: str = "") -> str: ...


class ConsoleTerminal:
    """The real terminal: a Rich console for output, single key presses for input."""

    def __init__(self, console: Console) -> None:
        self.console = console

    @property
    def ascii_only(self) -> bool:
        return bool(self.console.options.ascii_only)

    @property
    def height(self) -> int:
        return int(self.console.size.height)

    def clear(self) -> None:
        self.console.clear()

    def show(self, renderable: RenderableType) -> None:
        self.console.print(renderable)

    def key(self) -> str:
        return normalize_key(str(typer.getchar()))

    def ask(self, label: str, default: str = "") -> str:
        return str(
            typer.prompt(label, default=default, show_default=bool(default), prompt_suffix=": ")
        )


# ---------------------------------------------------------------------------
# The menu itself
# ---------------------------------------------------------------------------

Runner = Callable[[list[str]], int]

#: Result of a navigation loop.
ENTER, BACK, QUIT, CLEAR = "enter", "back", "quit", "clear"


@dataclass(slots=True)
class _Action:
    """A row in a list that is not a command or a parameter."""

    label: str
    detail: str = ""
    key: str = ""


class Menu:
    """Browse the commands, fill in their options, run them."""

    def __init__(
        self,
        root: Node,
        global_params: Sequence[Param],
        *,
        terminal: Terminal,
        runner: Runner,
    ) -> None:
        self.root = root
        self.global_params = list(global_params)
        self.term = terminal
        self.runner = runner
        self.global_values: Values = {}
        self._memory: dict[tuple[str, ...], Values] = {}

    # -- entry point -------------------------------------------------------

    def run(self) -> None:
        """Show the menu until the user leaves it."""
        with contextlib.suppress(KeyboardInterrupt, EOFError):
            self._browse(self.root)
        self.term.clear()
        self.term.show(Text("Bye.", style="dim"))

    # -- drawing -----------------------------------------------------------

    @property
    def _pointer(self) -> str:
        return ">" if self.term.ascii_only else "\u203a"

    def _row(self, selected: bool, columns: Sequence[Text | str]) -> Text:
        line = Text(f"{self._pointer} " if selected else "  ")
        for index, column in enumerate(columns):
            piece = column if isinstance(column, Text) else Text(str(column))
            if index:
                line.append("  ")
            line.append_text(piece)
        if selected:
            line.stylize("bold reverse")
        return line

    def _window(self, total: int, cursor: int, reserved: int) -> tuple[int, int]:
        """The slice of rows that fits on screen with the cursor inside it."""
        room = max(5, self.term.height - reserved)
        if total <= room:
            return 0, total
        start = min(max(cursor - room // 2, 0), total - room)
        return start, start + room

    def _screen(
        self,
        title: str,
        subtitle: str,
        rows: list[Text],
        cursor: int,
        footer: Sequence[Text | str],
        keys: str,
    ) -> None:
        start, end = self._window(len(rows), cursor, reserved=9 + len(footer))
        body: list[RenderableType] = [
            Text(title, style="bold"),
            Text(subtitle, style="dim") if subtitle else Text(""),
            Text(""),
        ]
        if start > 0:
            body.append(Text("  ...", style="dim"))
        body.extend(rows[start:end])
        if end < len(rows):
            body.append(Text("  ...", style="dim"))
        body.append(Text(""))
        body.extend(Text(line) if isinstance(line, str) else line for line in footer)
        body.append(Text(keys, style="dim"))
        self.term.clear()
        self.term.show(Group(*body))

    # -- navigation --------------------------------------------------------

    def _loop(self, draw: Callable[[int], None], count: int, start: int = 0) -> tuple[str, int]:
        """Move a cursor over ``count`` rows until the user picks something.

        Returns what happened (``enter``, ``back``, ``quit`` or ``clear``) and the
        row the cursor was on.
        """
        cursor = min(start, count - 1)
        while True:
            draw(cursor)
            key = self.term.key()
            if key in ("up", "k"):
                cursor = (cursor - 1) % count
            elif key in ("down", "j"):
                cursor = (cursor + 1) % count
            elif key == "home":
                cursor = 0
            elif key == "end":
                cursor = count - 1
            elif key == "enter":
                return ENTER, cursor
            elif key in ("esc", "left"):
                return BACK, cursor
            elif key in ("q", "Q"):
                return QUIT, cursor
            elif key in ("backspace", "delete"):
                return CLEAR, cursor

    def _browse(self, node: Node) -> bool:
        """List the commands under ``node``. Returns True when the user quit."""
        top = node is self.root
        items: list[Node | _Action] = [*node.children]
        if top:
            if self.global_params:
                items.append(_Action("Global options", "applies to every command", "globals"))
            items.append(_Action("Quit", key="quit"))
        else:
            items.append(_Action("Back", key="back"))

        title = APP_NAME if top else " ".join(node.path)
        subtitle = "Choose a command." if top else node.help

        def draw(at: int) -> None:
            self._screen(
                title,
                subtitle,
                self._browse_rows(items, at),
                at,
                [],
                "up/down move   enter open   esc back   q quit",
            )

        cursor = 0
        while True:
            event, cursor = self._loop(draw, len(items), cursor)
            if event == QUIT:
                return True
            if event == BACK:
                # Esc on the first screen leaves the menu; elsewhere it steps back.
                return top
            if event == CLEAR:
                continue

            chosen = items[cursor]
            if isinstance(chosen, Node):
                if (chosen.is_group and self._browse(chosen)) or (
                    not chosen.is_group and self._form(chosen)
                ):
                    return True
            elif chosen.key == "quit":
                return True
            elif chosen.key == "back":
                return False
            elif chosen.key == "globals" and self._globals():
                return True

    def _browse_rows(self, items: Sequence[Node | _Action], selected: int = -1) -> list[Text]:
        width = max((len(i.name if isinstance(i, Node) else i.label) for i in items), default=0)
        rows: list[Text] = []
        for index, item in enumerate(items):
            if isinstance(item, Node):
                arrow = ">" if self.term.ascii_only else "\u203a"
                name = f"{item.name} {arrow}" if item.is_group else item.name
                detail = item.help
            else:
                name, detail = item.label, item.detail
            rows.append(
                self._row(index == selected, [Text(name.ljust(width + 2)), Text(detail, "dim")])
            )
        return rows

    # -- a command's options -----------------------------------------------

    def _globals(self) -> bool:
        """Edit the options that apply to every command."""
        holder = Node(PROGRAM, "Options that apply to every command.", (), list(self.global_params))
        return self._edit(holder, self.global_values, runnable=False)

    def _form(self, node: Node) -> bool:
        values = self._memory.setdefault(node.path, {})
        return self._edit(node, values, runnable=True)

    def _edit(self, node: Node, values: Values, *, runnable: bool) -> bool:
        """The options of one command. Returns True when the user quit."""
        actions: list[_Action] = []
        if runnable:
            actions = [
                _Action("Run", "run it with the values above", "run"),
                _Action("Show help", "what the command prints for --help", "help"),
            ]
        actions.append(_Action("Back", key="back"))
        rows_count = len(node.params) + len(actions)
        note = ""
        cursor = 0

        while True:
            current_note = note

            def draw(at: int, current_note: str = current_note) -> None:
                self._draw_form(node, values, at, actions, current_note, runnable)

            event, cursor = self._loop(draw, rows_count, cursor)
            note = ""
            if event == QUIT:
                return True
            if event == BACK:
                return False

            if cursor < len(node.params):
                param = node.params[cursor]
                if event == CLEAR:
                    values.pop(param.name, None)
                else:
                    self._edit_param(param, values)
                continue

            if event == CLEAR:
                continue
            action = actions[cursor - len(node.params)]
            if action.key == "back":
                return False
            if action.key == "help":
                self._execute([*node.path, "--help"], show_line=False)
            elif action.key == "run":
                absent = missing_required(node, values)
                if absent:
                    note = "Needed first: " + ", ".join(param.label for param in absent)
                    continue
                self._execute(build_arguments(node, values, self.global_params, self.global_values))

    def _draw_form(
        self,
        node: Node,
        values: Values,
        cursor: int,
        actions: Sequence[_Action],
        note: str,
        runnable: bool,
    ) -> None:
        # One column width for parameters and actions, so the values line up with them.
        width = max(
            (len(row) for row in [*(p.label for p in node.params), *(a.label for a in actions)]),
            default=0,
        )
        rows: list[Text] = []
        for index, param in enumerate(node.params):
            mark = "*" if param.required else " "
            rows.append(
                self._row(
                    index == cursor,
                    [Text(f"{param.label.ljust(width)}{mark}"), self._value_text(param, values)],
                )
            )
        if node.params:
            rows.append(Text(""))
        offset = len(node.params)
        for index, action in enumerate(actions):
            rows.append(
                self._row(
                    offset + index == cursor,
                    [Text(action.label.ljust(width + 1)), Text(action.detail, "dim")],
                )
            )

        footer: list[Text | str] = []
        if cursor < len(node.params):
            param = node.params[cursor]
            footer.append(Text(param.help or "(no description)"))
            footer.append(Text("Accepts: " + param.hint, style="dim"))
            if param.default is not None:
                footer.append(Text(f"Default: {param.default}", style="dim"))
        footer.append(Text(""))
        if runnable:
            line = command_line(
                build_arguments(node, values, self.global_params, self.global_values)
            )
            footer.append(Text(line, style="cyan"))
        elif values:
            footer.append(Text("Used by every command you run from this menu.", style="dim"))
        if note:
            footer.append(Text(note, style="bold yellow"))

        subtitle = node.help + ("   (* needed)" if any(p.required for p in node.params) else "")
        self._screen(
            " ".join(node.path) if node.path else "Global options",
            subtitle,
            rows,
            cursor,
            footer,
            "up/down move   enter edit   backspace clear   esc back   q quit",
        )

    def _value_text(self, param: Param, values: Values) -> Text:
        value = values.get(param.name)
        if param.kind is Kind.FLAG:
            return Text("on", style="green") if value else Text("off", style="dim")
        if param.kind is Kind.TOGGLE:
            if value is True:
                return Text(str(param.on), style="green")
            if value is False:
                return Text(str(param.off), style="green")
            return Text("not set", style="dim")
        if value in (None, "", []):
            return Text("not set", style="dim")
        return Text(", ".join(value) if isinstance(value, list) else str(value), style="green")

    # -- changing one value ------------------------------------------------

    def _edit_param(self, param: Param, values: Values) -> None:
        if param.kind is Kind.FLAG:
            values[param.name] = not values.get(param.name, False)
        elif param.kind is Kind.TOGGLE:
            order = [None, True, False]
            values[param.name] = order[(order.index(values.get(param.name)) + 1) % 3]
        elif param.kind is Kind.CHOICE:
            self._choose(param, values)
        elif param.multiple:
            self._ask_many(param, values)
        else:
            self._ask_one(param, values)

    def _choose(self, param: Param, values: Values) -> None:
        """Pick one of a fixed list of values."""
        options = [*param.choices, "(not set)"]
        current = values.get(param.name)
        start = param.choices.index(current) if current in param.choices else len(param.choices)

        def draw(at: int) -> None:
            rows = [self._row(i == at, [Text(option)]) for i, option in enumerate(options)]
            self._screen(param.label, param.help, rows, at, [], "up/down move   enter choose")

        event, picked = self._loop(draw, len(options), start)
        if event != ENTER:
            return
        if picked == len(param.choices):
            values.pop(param.name, None)
        else:
            values[param.name] = param.choices[picked]

    def _ask_one(self, param: Param, values: Values) -> None:
        """Type one value, asking again until it is acceptable or left empty."""
        self._prompt_header(param)
        current = values.get(param.name)
        while True:
            text = self.term.ask(param.label, str(current) if current not in (None, "") else "")
            text = text.strip()
            if not text or text == "-":
                values.pop(param.name, None)
                return
            problem = check_value(param, text)
            if problem is None:
                values[param.name] = text
                return
            self.term.show(Text(problem, style="yellow"))

    def _ask_many(self, param: Param, values: Values) -> None:
        """Collect several values for an option that may be repeated."""
        self._prompt_header(param, extra="One value per line. Empty line to finish, - to clear.")
        collected: list[str] = list(values.get(param.name) or [])
        while True:
            text = self.term.ask(f"{param.label} #{len(collected) + 1}").strip()
            if not text:
                break
            if text == "-":
                collected = []
                break
            problem = check_value(param, text)
            if problem:
                self.term.show(Text(problem, style="yellow"))
                continue
            collected.append(text)
        if collected:
            values[param.name] = collected
        else:
            values.pop(param.name, None)

    def _prompt_header(self, param: Param, extra: str = "") -> None:
        self.term.clear()
        self.term.show(Text(param.label, style="bold"))
        if param.help:
            self.term.show(Text(param.help))
        self.term.show(Text("Accepts: " + param.hint, style="dim"))
        if extra:
            self.term.show(Text(extra, style="dim"))
        self.term.show(Text("Empty answer clears the value.", style="dim"))
        self.term.show(Text(""))

    # -- running -----------------------------------------------------------

    def _execute(self, arguments: list[str], *, show_line: bool = True) -> None:
        """Run a command and wait, so its output can be read before the menu returns."""
        self.term.clear()
        if show_line:
            self.term.show(Text("$ " + command_line(arguments), style="cyan"))
            self.term.show(Text(""))
        try:
            code = self.runner(arguments)
        except KeyboardInterrupt:
            code = 130
        self.term.show(Text(""))
        if code == 0:
            self.term.show(Text("Done.", style="green"))
        else:
            self.term.show(Text(f"Finished with exit code {code}.", style="yellow"))
        self.term.show(Text("Press any key to return to the menu.", style="dim"))
        self.term.key()


# ---------------------------------------------------------------------------
# Wiring to the real command line
# ---------------------------------------------------------------------------


class MenuUnavailableError(Exception):
    """The menu cannot run here, and the message says why."""


def make_runner(group: Any) -> Runner:
    """A function that runs the real command line in this process."""

    def run(arguments: list[str]) -> int:
        try:
            # standalone_mode lets the parser print usage errors itself and end the
            # run with an exit status, which is caught here rather than letting it
            # close the menu.
            group.main(args=arguments, prog_name=PROGRAM, standalone_mode=True)
        except SystemExit as finished:
            code = finished.code
            return code if isinstance(code, int) else (0 if code is None else 1)
        return 0

    return run


def run_menu(app: typer.Typer, *, console: Console | None = None) -> None:
    """Open the menu for a Typer application."""
    screen = console or Console()
    if not (sys.stdin.isatty() and screen.is_terminal):
        raise MenuUnavailableError(
            "The menu needs an interactive terminal. Run `discoverynow --help` to see "
            "the commands you can call directly."
        )
    group = typer.main.get_command(app)
    root, global_params = build_tree(group)
    Menu(
        root,
        global_params,
        terminal=ConsoleTerminal(screen),
        runner=make_runner(group),
    ).run()
