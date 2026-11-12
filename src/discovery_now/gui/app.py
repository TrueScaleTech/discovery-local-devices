"""Starting the desktop app."""

from __future__ import annotations

import contextlib
import ctypes
import sys

from PySide6.QtWidgets import QApplication

from .. import APP_NAME
from ..config import Settings
from . import theme
from .icons import app_icon
from .window import MainWindow

#: Lets Windows group the taskbar button under our icon, not under python.exe's.
_APP_ID = "TrueScaleTech.DiscoveryNow"


def _claim_taskbar_identity() -> None:
    if sys.platform == "win32":
        # Cosmetic only: the app works the same without it.
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)


def run(argv: list[str] | None = None) -> int:
    """Open the window and run until it is closed. Returns the exit status."""
    _claim_taskbar_identity()
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    assert isinstance(app, QApplication)  # noqa: S101 - narrows the type for the checker
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("TrueScaleTech")
    app.setWindowIcon(app_icon())
    theme.apply(app)

    window = MainWindow(Settings.load())

    def restyle() -> None:
        theme.apply(app)
        window.on_theme_changed()

    app.styleHints().colorSchemeChanged.connect(restyle)
    window.show()
    return app.exec()
