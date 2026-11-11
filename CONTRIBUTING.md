# Contributing

Thanks for taking a look. Issues and pull requests are welcome.

## Getting set up

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

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

## What belongs here, and what does not

Discovery Now discovers and inventories. Features that authenticate to devices,
exploit them, capture traffic or change their configuration are out of scope, and
so is anything that sends a user's inventory off their machine.

Please do not include real network data in issues or tests: MAC addresses,
hostnames and device names identify people. Invent examples instead.
