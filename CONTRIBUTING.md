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

It lives in `src/discovery_now/gui/`, and it is built so that most of it can be
tested without a display:

- `viewmodel.py` decides what the devices list shows (filters, search, counts,
  wording) and `topology.py` decides where the map puts things. Neither imports
  Qt. Put new decisions there, and keep the widgets a layer that draws them.
- `theme.py` holds every colour and measurement, built from the two choices the
  user makes (the appearance and the accent). Never hard-code a colour elsewhere: one of the two appearances will
  go wrong, and the contrast tests will not be watching it.
- `icons.py` draws every mark the app shows, on one 24-unit grid. Add an icon
  there rather than reaching for a character from a font.
- `widgets.py` holds the shapes that repeat (a card, a row of settings, a group
  of chips). Use them, so the screens keep one vocabulary.

Tests: `tests/test_gui_viewmodel.py` and `tests/test_topology.py` need neither Qt
nor a display. `tests/test_gui.py` and `tests/test_gui_screens.py` drive the real
window on Qt's `offscreen` platform, with the network replaced by a fake scan:
they select rows, type into fields and click buttons. The contrast of every
accent in both appearances is checked in `tests/test_gui.py`.

## What belongs here, and what does not

Discovery Now discovers and inventories. Features that authenticate to devices,
exploit them, capture traffic or change their configuration are out of scope, and
so is anything that sends a user's inventory off their machine.

Please do not include real network data in issues or tests: MAC addresses,
hostnames and device names identify people. Invent examples instead.
