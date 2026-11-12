"""What the desktop app remembers between runs.

Kept in a plain ``.ini`` file next to the configuration file rather than in the
Windows registry, so everything Discovery Now remembers lives in two folders the
user can see, copy and delete.

Only the app's own preferences live here. Anything that changes what a scan does
belongs in ``config.toml``, which the command line reads too.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from ..config import config_dir
from .theme import ACCENTS, DEFAULT_ACCENT, Mode

#: Choices offered for how often to scan on its own, in minutes.
INTERVALS = (1, 5, 15, 30, 60)


def prefs_path() -> Path:
    return config_dir() / "gui.ini"


class Preferences:
    """Read and write what the window remembers."""

    def __init__(self, path: Path | None = None, *, default_interval: int = 5) -> None:
        target = path or prefs_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        self._settings = QSettings(str(target), QSettings.Format.IniFormat)
        self._default_interval = default_interval

    def _text(self, key: str, fallback: str) -> str:
        value = self._settings.value(key, fallback)
        return value if isinstance(value, str) else fallback

    def _flag(self, key: str, fallback: bool) -> bool:
        return bool(self._settings.value(key, fallback, type=bool))

    # -- appearance --------------------------------------------------------

    @property
    def mode(self) -> Mode:
        """Light, dark, or whatever the system is asking for."""
        try:
            return Mode(self._text("appearance", Mode.SYSTEM.value))
        except ValueError:
            return Mode.SYSTEM

    @mode.setter
    def mode(self, value: Mode) -> None:
        self._settings.setValue("appearance", value.value)

    @property
    def accent(self) -> str:
        """The key of the chosen accent, always one we actually offer."""
        chosen = self._text("accent", DEFAULT_ACCENT.key)
        return chosen if any(a.key == chosen for a in ACCENTS) else DEFAULT_ACCENT.key

    @accent.setter
    def accent(self, value: str) -> None:
        self._settings.setValue("accent", value)

    # -- switches ----------------------------------------------------------

    @property
    def auto_scan(self) -> bool:
        return self._flag("auto_scan", True)

    @auto_scan.setter
    def auto_scan(self, value: bool) -> None:
        self._settings.setValue("auto_scan", value)

    @property
    def interval_minutes(self) -> int:
        value = self._settings.value("interval_minutes", self._default_interval, type=int)
        return value if isinstance(value, int) and value in INTERVALS else self._default_interval

    @interval_minutes.setter
    def interval_minutes(self, value: int) -> None:
        self._settings.setValue("interval_minutes", value)

    @property
    def notifications(self) -> bool:
        return self._flag("notifications", True)

    @notifications.setter
    def notifications(self, value: bool) -> None:
        self._settings.setValue("notifications", value)

    @property
    def redact_exports(self) -> bool:
        return self._flag("redact_exports", False)

    @redact_exports.setter
    def redact_exports(self, value: bool) -> None:
        self._settings.setValue("redact_exports", value)

    # -- layout ------------------------------------------------------------

    def hidden_columns(self, *, default: tuple[int, ...] = ()) -> set[int]:
        """Table columns the user has hidden, by number."""
        raw = self._settings.value("hidden_columns")
        if not isinstance(raw, str):
            return set(default)
        return {int(part) for part in raw.split(",") if part.strip().isdigit()}

    def save_hidden_columns(self, columns: set[int]) -> None:
        self._settings.setValue("hidden_columns", ",".join(str(c) for c in sorted(columns)))

    def node_positions(self) -> dict[int, tuple[float, float]]:
        """Where the user has dragged map nodes to, by device id."""
        raw = self._settings.value("map_positions")
        if not isinstance(raw, str):
            return {}
        try:
            loaded = json.loads(raw)
        except ValueError:
            return {}
        found: dict[int, tuple[float, float]] = {}
        if not isinstance(loaded, dict):
            return found
        for key, value in loaded.items():
            try:
                found[int(key)] = (float(value[0]), float(value[1]))
            except (ValueError, TypeError, IndexError):
                continue
        return found

    def save_node_positions(self, positions: dict[int, tuple[float, float]]) -> None:
        text = json.dumps({str(k): [round(x, 1), round(y, 1)] for k, (x, y) in positions.items()})
        self._settings.setValue("map_positions", text)

    def geometry(self) -> QByteArray | None:
        value = self._settings.value("geometry")
        return value if isinstance(value, QByteArray) else None

    def save_geometry(self, value: QByteArray) -> None:
        self._settings.setValue("geometry", value)

    def splitter(self) -> QByteArray | None:
        value = self._settings.value("splitter")
        return value if isinstance(value, QByteArray) else None

    def save_splitter(self, value: QByteArray) -> None:
        self._settings.setValue("splitter", value)

    def sync(self) -> None:
        self._settings.sync()


def snap_interval(minutes: int) -> int:
    """The offered interval closest to a number of minutes (for a config value)."""
    return min(INTERVALS, key=lambda choice: abs(choice - minutes))
