# Contributing

Thanks for taking a look. Issues and pull requests are welcome.

## Getting set up

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,gui]"
```

The `gui` extra is only needed for the desktop app and its tests.

## Before opening a pull request

```bash
ruff check .
ruff format --check .
mypy
pytest
```

CI runs the same four on Linux and Windows, for Python 3.11, 3.12 and 3.13.

## House rules

- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org):
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ci:`, `chore:`. One change per
  commit.
- **Tests** come with behaviour. The suite must not need a network: capture the
  output of a command and parse it, or use a loopback socket.
- **Platforms.** Anything that reads system output has to work on Windows and on
  Linux, and on a system that is not in English. Match on the shape of an address
  rather than on column positions or words.
- **Comments** explain why, not what. A comment that restates the code is noise.

## Adding a command or an option

The interactive menu (`discoverynow menu`) is built from the command line's own
definitions, so a new command or option appears in it automatically. Describe each
option properly where it is declared: its help text is what the menu shows under
the cursor, and its Python type decides how the menu asks for it (a choice list for
an `Enum`, a number check for `int` and `float`, a toggle for `bool | None`).

`tests/test_menu.py` checks that every command and option of the CLI is reachable
from the menu, and pins how a few of them are understood. If a dependency update
changes how the parser reports types, that is where it will show.

## The desktop app

It lives in `src/discovery_now/gui/`. Everything that decides what the window
shows (filters, search, counts, wording) is in `viewmodel.py` and has no Qt in it,
so it is tested without a display in `tests/test_gui_viewmodel.py`. Put new
decisions there, and keep the widgets a thin layer that draws them.

`tests/test_gui.py` drives the real window on Qt's `offscreen` platform: it
selects rows, types into fields and clicks buttons, with the network replaced by a
fake scan. Colours are tokens in `theme.py`; do not hard-code one elsewhere, or
one of the two appearances will go wrong.

## What belongs here, and what does not

Discovery Now discovers and inventories. Features that authenticate to devices,
exploit them, capture traffic or change their configuration are out of scope, and
so is anything that sends a user's inventory off their machine.

Please do not include real network data in issues or tests: MAC addresses,
hostnames and device names identify people. Invent examples instead.
