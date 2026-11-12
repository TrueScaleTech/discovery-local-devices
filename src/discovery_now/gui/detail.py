"""The panel that shows one device and lets you name, annotate and approve it."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..fingerprint import kind_of
from ..models import Device, Event
from . import theme
from .viewmodel import ago, automatic_name, clock, event_title, ports_text

_NOTHING = "—"


class DetailPanel(QFrame):
    """One device in full, with the few things a person can change about it."""

    #: Device id and the new name; an empty string clears the name.
    renamed = Signal(int, str)
    #: Device id and the notes text.
    notes_saved = Signal(int, str)
    #: Device id and whether the device is now approved.
    approval_changed = Signal(int, bool)
    #: Device id of the device to remove from the inventory.
    forget_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self._device: Device | None = None
        self._saved_label = ""
        self._saved_notes = ""

        pages = QStackedLayout(self)
        pages.addWidget(self._build_empty())
        pages.addWidget(self._build_content())
        self._pages = pages
        self.setMinimumWidth(290)

    # -- construction ------------------------------------------------------

    def _build_empty(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("Select a device to see its details,\nname it and add notes.")
        label.setObjectName("muted")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return page

    def _build_content(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._name = QLineEdit()
        name_font = QFont(self._name.font())
        name_font.setPointSizeF(name_font.pointSizeF() + 3)
        name_font.setBold(True)
        self._name.setFont(name_font)
        self._name.setToolTip("Give this device a name you will recognise")
        self._name.editingFinished.connect(self._commit_name)
        layout.addWidget(self._name)

        self._subtitle = QLabel()
        self._subtitle.setObjectName("muted")
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        self._state = QLabel()
        self._state.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._state)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        self._fields: dict[str, QLabel] = {}
        for row, key in enumerate(
            ("Address", "MAC", "Hostname", "Open ports", "First seen", "Last seen")
        ):
            heading = QLabel(key)
            heading.setObjectName("muted")
            value = QLabel()
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(heading, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, row, 1)
            self._fields[key] = value
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        notes_heading = QLabel("Notes")
        notes_heading.setObjectName("heading")
        layout.addWidget(notes_heading)
        self._notes = QPlainTextEdit()
        self._notes.setPlaceholderText("Where it is, who uses it, anything worth remembering")
        self._notes.setFixedHeight(84)
        self._notes.installEventFilter(self)
        layout.addWidget(self._notes)

        buttons = QGridLayout()
        buttons.setHorizontalSpacing(8)
        self._approve = QPushButton("Approve")
        self._approve.setToolTip("Mark this device as one you recognise")
        self._approve.clicked.connect(self._toggle_approval)
        self._forget = QPushButton("Forget")
        self._forget.setObjectName("danger")
        self._forget.setToolTip("Remove this device and its history from the inventory")
        self._forget.clicked.connect(self._ask_forget)
        buttons.addWidget(self._approve, 0, 0)
        buttons.addWidget(self._forget, 0, 1)
        layout.addLayout(buttons)

        history_heading = QLabel("History")
        history_heading.setObjectName("heading")
        layout.addWidget(history_heading)
        self._history = QListWidget()
        self._history.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._history.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history.setTextElideMode(Qt.TextElideMode.ElideRight)
        layout.addWidget(self._history, 1)
        return page

    # -- showing a device --------------------------------------------------

    @property
    def device_id(self) -> int | None:
        return self._device.id if self._device else None

    def show_device(
        self, device: Device | None, events: Sequence[Event] = (), *, new_within: timedelta
    ) -> None:
        """Fill the panel, or empty it when nothing is selected.

        When the same device is shown again after a scan, fields the user may be in
        the middle of editing are left alone.
        """
        if device is None:
            self._device = None
            self._pages.setCurrentIndex(0)
            return

        same = self._device is not None and self._device.id == device.id
        self._device = device
        self._pages.setCurrentIndex(1)

        self._name.setPlaceholderText(automatic_name(device))
        self._saved_label = device.label or ""
        if not (same and self._name.hasFocus()):
            self._name.setText(self._saved_label)
        self._saved_notes = device.notes or ""
        if not (same and self._notes.hasFocus()):
            self._notes.setPlainText(self._saved_notes)

        kind = kind_of(device)
        self._subtitle.setText(
            " · ".join(part for part in (kind, device.vendor) if part) or "Unidentified device"
        )
        self._state.setText(self._state_html(device, new_within))

        self._fields["Address"].setText(device.ip)
        self._fields["MAC"].setText(device.mac or _NOTHING)
        self._fields["Hostname"].setText(device.hostname or _NOTHING)
        self._fields["Open ports"].setText(ports_text(device.open_ports) or "none found")
        for key, moment in (("First seen", device.first_seen), ("Last seen", device.last_seen)):
            self._fields[key].setText(f"{clock(moment)}  ({ago(moment)})")

        self._approve.setText("Withdraw approval" if device.approved else "Approve")
        self._fill_history(events)

    @staticmethod
    def _state_html(device: Device, new_within: timedelta) -> str:
        tokens = theme.current()
        if device.online:
            parts = [f'<span style="color:{tokens.online}">● Online</span>']
        else:
            parts = [f'<span style="color:{tokens.offline}">○ Offline</span>']
        if device.is_new(new_within):
            parts.append(
                f'<span style="color:{tokens.new}"><b>NEW</b> · appeared '
                f"{ago(device.first_seen)}</span>"
            )
        if device.approved:
            parts.append("Approved")
        else:
            parts.append(f'<span style="color:{tokens.warn}">Not approved</span>')
        return " &nbsp;·&nbsp; ".join(parts)

    def _fill_history(self, events: Sequence[Event]) -> None:
        self._history.clear()
        for event in events:
            detail = f"  {event.detail}" if event.detail else ""
            line = f"{clock(event.at)}   {event_title(event)}{detail}"
            item = QListWidgetItem(line)
            item.setToolTip(line)
            self._history.addItem(item)

    # -- editing -----------------------------------------------------------

    def flush(self) -> None:
        """Hand any edit in progress to the window, before the panel changes subject.

        Both edits are read first and sent after: the first one sent makes the window
        refresh this panel, and the second must not be lost to that.
        """
        if self._device is None:
            return
        device_id = self._device.id
        name = self._name.text().strip()
        notes = self._notes.toPlainText().strip()
        send_name = name != self._saved_label
        send_notes = notes != self._saved_notes
        if send_name:
            self._saved_label = name
        if send_notes:
            self._saved_notes = notes
        if send_name:
            self.renamed.emit(device_id, name)
        if send_notes:
            self.notes_saved.emit(device_id, notes)

    def _commit_name(self) -> None:
        self.flush()

    def _commit_notes(self) -> None:
        self.flush()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._notes and event.type() == QEvent.Type.FocusOut:
            self._commit_notes()
        return super().eventFilter(watched, event)

    def _toggle_approval(self) -> None:
        if self._device is not None:
            self.approval_changed.emit(self._device.id, not self._device.approved)

    def _ask_forget(self) -> None:
        if self._device is not None:
            self.forget_requested.emit(self._device.id)
