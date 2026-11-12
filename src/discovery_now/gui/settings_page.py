"""The settings screen.

A change takes effect the moment it is made: there is no Save button, because
there is nothing here a person would want to half-change and then abandon.

Two files are behind this screen. What the window looks like and remembers goes
to ``gui.ini``; anything that changes what a scan does goes to ``config.toml``,
the same file the command line reads, so the two never disagree.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..config import Settings, config_path, data_dir
from ..net import TargetError, parse_network
from . import theme
from .prefs import INTERVALS, Preferences
from .widgets import Card, Segmented, hint


def interval_label(minutes: int) -> str:
    if minutes == 60:
        return "every hour"
    return "every minute" if minutes == 1 else f"every {minutes} minutes"


def parse_subnets(text: str) -> list[str]:
    """The subnets a person typed, checked.

    Raises :class:`discovery_now.net.TargetError` naming the first piece that is
    not a network, so the screen can say which one is wrong.
    """
    found: list[str] = []
    for piece in text.replace(";", ",").split(","):
        cleaned = piece.strip()
        if not cleaned:
            continue
        parse_network(cleaned)  # raises TargetError when it is not one
        found.append(cleaned)
    return found


class Swatch(QPushButton):
    """One accent to choose from, drawn as a disc of that colour."""

    def __init__(self, accent: theme.Accent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.accent = accent
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(accent.name)
        self.setFlat(True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        tokens = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QRectF(self.rect()).center()

        if self.isChecked():
            ring = QPen(QColor(tokens.text))
            ring.setWidthF(1.6)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 13.0, 13.0)
        elif self.underMouse():
            ring = QPen(QColor(tokens.border_strong))
            ring.setWidthF(1.4)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 13.0, 13.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(self.accent.fill(dark=tokens.dark))))
        painter.drawEllipse(centre, 9.5, 9.5)

    def enterEvent(self, event: object) -> None:  # noqa: N802 - Qt's name
        self.update()

    def leaveEvent(self, event: object) -> None:  # noqa: N802 - Qt's name
        self.update()


class SettingsPage(QScrollArea):
    """Everything the user can change, in one scrolling column."""

    #: The appearance or accent changed; the window restyles itself.
    appearance_changed = Signal()
    #: Automatic scanning was turned on or off, or its interval changed.
    schedule_changed = Signal()
    #: Something a scan depends on changed, and has been saved to config.toml.
    scan_changed = Signal()
    #: Somewhere to open: the settings file or the data folder.
    open_path = Signal(str)

    def __init__(
        self,
        prefs: Preferences,
        settings: Settings,
        *,
        can_notify: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._prefs = prefs
        self._settings = settings
        self._loading = True

        body = QWidget()
        tokens = theme.current()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, tokens.gap, 0)
        column.setSpacing(tokens.gap + 2)
        column.addWidget(self._appearance_card())
        column.addWidget(self._scanning_card())
        column.addWidget(self._alerts_card(can_notify=can_notify))
        column.addWidget(self._files_card())
        column.addWidget(self._about_card())
        column.addStretch(1)

        self.setWidget(body)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._load()
        self._loading = False

    # -- the cards ---------------------------------------------------------

    def _appearance_card(self) -> Card:
        card = Card("Appearance", "palette")

        self._mode = Segmented()
        for mode in theme.Mode:
            self._mode.add(mode.value, mode.label)
        self._mode.picked.connect(lambda key: self._set_mode(theme.Mode(key)))
        card.add_row("Theme", self._mode)

        swatches = QWidget()
        row = QHBoxLayout(swatches)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)
        self._swatches: list[Swatch] = []
        for accent in theme.ACCENTS:
            swatch = Swatch(accent)
            swatch.clicked.connect(lambda _c=False, a=accent: self._set_accent(a))
            row.addWidget(swatch)
            self._swatches.append(swatch)
        card.add_row("Accent", swatches, "Colours the main button and the selected row.")
        return card

    def _scanning_card(self) -> Card:
        card = Card("Scanning", "scan")

        schedule = QWidget()
        row = QHBoxLayout(schedule)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)
        self._auto = QCheckBox("Scan on its own")
        self._auto.toggled.connect(self._on_schedule)
        self._interval = QComboBox()
        self._interval.setFixedWidth(150)
        for minutes in INTERVALS:
            self._interval.addItem(interval_label(minutes), minutes)
        self._interval.currentIndexChanged.connect(self._on_schedule)
        row.addWidget(self._auto)
        row.addWidget(self._interval)
        card.add_row("Keep watching", schedule)

        self._subnets = QLineEdit()
        self._subnets.setPlaceholderText("Worked out from this machine's interfaces")
        self._subnets.editingFinished.connect(self._on_subnets)
        card.add_row(
            "Networks to scan",
            self._subnets,
            "Leave empty to use the networks this machine is on. "
            "Several go in a list: 192.168.1.0/24, 10.0.0.0/24",
            wide=True,
        )
        self._subnets_error = hint("")
        self._subnets_error.setObjectName("muted")
        self._subnets_error.hide()
        card.add(self._subnets_error)

        self._names = QCheckBox("Ask the network for each device's name")
        self._names.toggled.connect(self._on_scan_values)
        card.add_row("Names", self._names)

        self._offline_after = QSpinBox()
        self._offline_after.setRange(1, 20)
        self._offline_after.setSuffix(" missed scans")
        self._offline_after.setFixedWidth(170)
        self._offline_after.valueChanged.connect(self._on_scan_values)
        card.add_row(
            "Call a device offline after",
            self._offline_after,
            "Phones sleep and miss a scan. More than one miss means it really left.",
        )

        self._new_days = QSpinBox()
        self._new_days.setRange(1, 90)
        self._new_days.setSuffix(" days")
        self._new_days.setFixedWidth(170)
        self._new_days.valueChanged.connect(self._on_scan_values)
        card.add_row("Keep the NEW tag for", self._new_days)
        return card

    def _alerts_card(self, *, can_notify: bool) -> Card:
        card = Card("Alerts and privacy", "bell")
        self._notify = QCheckBox("Tell me when a new device appears")
        self._notify.toggled.connect(self._on_notify)
        self._notify.setEnabled(can_notify)
        card.add_row(
            "Notifications",
            self._notify,
            "A notification when something joins a network already known. The first "
            "scan of all never announces what it finds."
            + ("" if can_notify else "  This desktop has no notification area."),
        )

        self._redact = QCheckBox("Hide private details in exports")
        self._redact.toggled.connect(self._on_redact)
        card.add_row(
            "Exports",
            self._redact,
            "Hides the unique half of every MAC address, and all names and notes. "
            "Turn it on before sharing an export with anyone.",
        )
        return card

    def _files_card(self) -> Card:
        card = Card("Files", "folder")
        card.add_row("Settings", self._path_row(config_path(), "Open file"))
        card.add_row("Inventory", self._path_row(data_dir(), "Open folder"))
        card.add(
            hint(
                "The inventory holds the addresses and names of everything on your "
                "network. It never leaves this computer."
            )
        )
        return card

    def _path_row(self, path: Path, action: str) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        label = QLabel(str(path))
        label.setObjectName("muted")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)
        button = QPushButton(action)
        button.clicked.connect(lambda _c=False, p=path: self.open_path.emit(str(p)))
        line.addWidget(label, 1)
        line.addWidget(button)
        return row

    def _about_card(self) -> Card:
        card = Card("About", "info")
        name = QLabel(f"{APP_NAME} {__version__}")
        name.setObjectName("section")
        card.add(name)
        card.add(
            hint(
                "Finds what is connected to your network, keeps a record of it, and "
                "tells you when something new appears. It only looks: it never signs "
                "in to a device, changes one, or listens to traffic, and it needs no "
                "administrator rights."
            )
        )
        card.add(hint("MIT licence · TrueScaleTech"))
        return card

    # -- reading and writing -----------------------------------------------

    def _load(self) -> None:
        self._mode.choose(self._prefs.mode.value)
        for swatch in self._swatches:
            swatch.setChecked(swatch.accent.key == self._prefs.accent)
        self._auto.setChecked(self._prefs.auto_scan)
        self._interval.setCurrentIndex(INTERVALS.index(self._prefs.interval_minutes))
        self._interval.setEnabled(self._prefs.auto_scan)
        self._notify.setChecked(self._prefs.notifications)
        self._redact.setChecked(self._prefs.redact_exports)
        self._subnets.setText(", ".join(self._settings.subnets))
        self._names.setChecked(self._settings.resolve_hostnames)
        self._offline_after.setValue(self._settings.offline_after)
        self._new_days.setValue(self._settings.new_device_days)

    def _set_mode(self, mode: theme.Mode) -> None:
        self._prefs.mode = mode
        self._mode.choose(mode.value)
        self.appearance_changed.emit()

    def _set_accent(self, accent: theme.Accent) -> None:
        self._prefs.accent = accent.key
        for swatch in self._swatches:
            swatch.setChecked(swatch.accent.key == accent.key)
        self.appearance_changed.emit()

    def _on_schedule(self, *_ignored: object) -> None:
        if self._loading:
            return
        self._prefs.auto_scan = self._auto.isChecked()
        self._prefs.interval_minutes = int(self._interval.currentData())
        self._interval.setEnabled(self._auto.isChecked())
        self.schedule_changed.emit()

    def _on_notify(self, checked: bool) -> None:
        if not self._loading:
            self._prefs.notifications = checked

    def _on_redact(self, checked: bool) -> None:
        if not self._loading:
            self._prefs.redact_exports = checked

    def _on_subnets(self) -> None:
        if self._loading:
            return
        try:
            self._settings.subnets = parse_subnets(self._subnets.text())
        except TargetError as error:
            self._subnets_error.setText(f"Not saved: {error}")
            self._subnets_error.show()
            return
        self._subnets_error.hide()
        self._save_scan_settings()

    def _on_scan_values(self, *_ignored: object) -> None:
        if self._loading:
            return
        self._settings.resolve_hostnames = self._names.isChecked()
        self._settings.offline_after = self._offline_after.value()
        self._settings.new_device_days = self._new_days.value()
        self._save_scan_settings()

    def _save_scan_settings(self) -> None:
        self._settings.save()
        self.scan_changed.emit()

    def restyle(self) -> None:
        """Take the spacing now in use, and redraw."""
        tokens = theme.current()
        body = self.widget()
        layout = body.layout() if body is not None else None
        if layout is not None:
            layout.setSpacing(tokens.gap + 2)
        for card in self.findChildren(Card):
            card.restyle()
        self.update()
