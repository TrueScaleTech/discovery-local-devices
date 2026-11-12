"""The app's own preferences: window layout and a few switches.

Kept in a plain ``.ini`` file next to the configuration file rather than in the
Windows registry, so everything Discovery Now remembers lives in two folders the
user can see, copy and delete.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from ..config import config_dir

#: Choices offered for how often to scan on its own, in minutes.
INTERVALS = (1, 5, 15, 30, 60)


def prefs_path() -> Path:
    return config_dir() / "gui.ini"


class Preferences:
    """Read and write what the window remembers between runs."""

    def __init__(self, path: Path | None = None, *, default_interval: int = 5) -> None:
        target = path or prefs_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        self._settings = QSettings(str(target), QSettings.Format.IniFormat)
        self._default_interval = default_interval

    # -- switches ----------------------------------------------------------

    @property
    def auto_scan(self) -> bool:
        return bool(self._settings.value("auto_scan", True, type=bool))

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
        return bool(self._settings.value("notifications", True, type=bool))

    @notifications.setter
    def notifications(self, value: bool) -> None:
        self._settings.setValue("notifications", value)

    @property
    def redact_exports(self) -> bool:
        return bool(self._settings.value("redact_exports", False, type=bool))

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
