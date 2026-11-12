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
from .prefs import Preferences
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
    # The saved appearance goes on before any widget exists, so nothing is built
    # with the wrong measurements and then restyled in front of the user.
    prefs = Preferences()
    theme.apply(
        app,
        mode=prefs.mode,
        accent=theme.accent_for(prefs.accent),
    )

    window = MainWindow(Settings.load(), prefs=prefs)

    # Only matters while the appearance is set to follow the system.
    app.styleHints().colorSchemeChanged.connect(window.restyle)
    window.show()
    return app.exec()
