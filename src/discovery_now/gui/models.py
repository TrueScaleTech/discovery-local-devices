"""The device list and the activity log, as Qt table models."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QPointF,
    QRectF,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from ..fingerprint import kind_of
from ..models import Device, Event, EventKind, utcnow
from . import theme
from .icons import status_dot
from .viewmodel import (
    Filter,
    address_key,
    ago,
    clock,
    display_name,
    event_title,
    matches_query,
    passes,
    ports_text,
)

#: What a sort compares: a Python value picked per column, not the text on screen.
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
#: The small tag drawn after a name ("NEW"), or an empty string.
BADGE_ROLE = Qt.ItemDataRole.UserRole + 2
#: The :class:`Device` behind a row.
DEVICE_ROLE = Qt.ItemDataRole.UserRole + 3

COLUMNS = (
    "Name",
    "Status",
    "Address",
    "MAC",
    "Vendor",
    "Kind",
    "Ports",
    "First seen",
    "Last seen",
)
NAME, STATUS, ADDRESS, MAC, VENDOR, KIND, PORTS, FIRST_SEEN, LAST_SEEN = range(len(COLUMNS))

_NOTHING = "—"

#: Columns that start hidden: they are in the detail panel, and the table is tight.
HIDDEN_BY_DEFAULT = (VENDOR, PORTS, FIRST_SEEN)

#: Starting width of every column but the name, which takes whatever is left.
COLUMN_WIDTHS = {
    STATUS: 78,
    ADDRESS: 126,
    MAC: 148,
    VENDOR: 130,
    KIND: 168,
    PORTS: 120,
    FIRST_SEEN: 96,
    LAST_SEEN: 84,
}


def _monospace() -> QFont:
    """A fixed-width font that is compact enough for a MAC address in a table.

    The system's own choice on Windows is Courier New, which is thin and wide. The
    first of these that is installed wins; the system font is the last resort.
    """
    families = set(QFontDatabase.families())
    for name in ("Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Menlo", "Liberation Mono"):
        if name in families:
            font = QFont(name)
            font.setStyleHint(QFont.StyleHint.Monospace)
            return font
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


class DevicesModel(QAbstractTableModel):
    """Every device in the inventory, one per row."""

    def __init__(self, new_within: timedelta, parent: Any = None) -> None:
        super().__init__(parent)
        self._devices: list[Device] = []
        self._new_within = new_within
        self._mono = _monospace()

    # -- content -----------------------------------------------------------

    def set_devices(self, devices: Sequence[Device]) -> None:
        """Replace the content, keeping selection and scroll when only values changed."""
        fresh = list(devices)
        same_rows = [d.id for d in fresh] == [d.id for d in self._devices]
        if same_rows and fresh:
            self._devices = fresh
            self.dataChanged.emit(self.index(0, 0), self.index(len(fresh) - 1, len(COLUMNS) - 1))
            return
        self.beginResetModel()
        self._devices = fresh
        self.endResetModel()

    def set_new_window(self, new_within: timedelta) -> None:
        self._new_within = new_within
        self.refresh()

    def refresh(self) -> None:
        """Redraw every cell, for a clock tick or a change of colours."""
        if self._devices:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._devices) - 1, len(COLUMNS) - 1)
            )

    def device_at(self, row: int) -> Device:
        return self._devices[row]

    def row_of(self, device_id: int) -> int | None:
        for row, device in enumerate(self._devices):
            if device.id == device_id:
                return row
        return None

    @property
    def new_within(self) -> timedelta:
        return self._new_within

    # -- Qt model interface ------------------------------------------------

    def rowCount(  # noqa: N802 - Qt's name
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(self._devices)

    def columnCount(  # noqa: N802
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def sort_key(self, row: int, column: int) -> Any:
        """What column ``column`` of this row is ordered by."""
        device = self._devices[row]
        keys: dict[int, Any] = {
            NAME: display_name(device).casefold(),
            STATUS: (not device.online, device.name.casefold()),
            ADDRESS: address_key(device.ip),
            MAC: device.mac or "",
            VENDOR: (device.vendor or "").casefold(),
            KIND: (kind_of(device) or "").casefold(),
            PORTS: tuple(device.open_ports),
            FIRST_SEEN: device.first_seen,
            LAST_SEEN: device.last_seen,
        }
        return keys[column]

    def _text(self, device: Device, column: int) -> str:
        now = utcnow()
        values: dict[int, str | None] = {
            NAME: display_name(device),
            STATUS: "Online" if device.online else "Offline",
            ADDRESS: device.ip,
            MAC: device.mac,
            VENDOR: device.vendor,
            KIND: kind_of(device),
            PORTS: ports_text(device.open_ports),
            FIRST_SEEN: ago(device.first_seen, now=now),
            LAST_SEEN: ago(device.last_seen, now=now),
        }
        return values[column] or _NOTHING

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return None
        device = self._devices[index.row()]
        column = index.column()
        tokens = theme.current()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(device, column)
        if role == SORT_ROLE:
            return self.sort_key(index.row(), column)
        if role == DEVICE_ROLE:
            return device
        if role == BADGE_ROLE:
            return "NEW" if column == NAME and device.is_new(self._new_within) else ""
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == STATUS:
                return QBrush(QColor(tokens.online if device.online else tokens.offline))
            if column == NAME:
                return QBrush(QColor(tokens.text if device.online else tokens.muted))
            if self._text(device, column) == _NOTHING or column in (FIRST_SEEN, LAST_SEEN):
                return QBrush(QColor(tokens.muted))
            return None
        if role == Qt.ItemDataRole.FontRole and column in (ADDRESS, MAC):
            font = QFont(self._mono)
            font.setPointSizeF(max(9.5, QApplication.font().pointSizeF() - 0.5))
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(device, column)
        return None

    def _tooltip(self, device: Device, column: int) -> str | None:
        if column == NAME and device.is_new(self._new_within):
            return f"New: first seen {ago(device.first_seen)} ({clock(device.first_seen)})"
        if column == FIRST_SEEN:
            return clock(device.first_seen)
        if column == LAST_SEEN:
            return clock(device.last_seen)
        if column == KIND:
            note = "A guess from the name, the ports and the maker of the network chip."
            # The longest kinds are elided in the column, so say it in full here.
            kind = kind_of(device)
            return f"{kind} — {note}" if kind else note
        return None


class DevicesProxy(QSortFilterProxyModel):
    """Sorting, the quick filter and the search box on top of the device model."""

    def __init__(self, source: DevicesModel, parent: Any = None) -> None:
        super().__init__(parent)
        self._model = source
        self._quick = Filter.ALL
        self._query = ""
        self.setSourceModel(source)
        self.setDynamicSortFilter(True)
        self.setSortRole(SORT_ROLE)

    def set_quick(self, quick: Filter) -> None:
        self._quick = quick
        self.invalidate()

    def set_query(self, query: str) -> None:
        self._query = query
        self.invalidate()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        device = self._model.device_at(source_row)
        return passes(device, self._quick, new_within=self._model.new_within) and matches_query(
            device, self._query
        )

    def lessThan(  # noqa: N802
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        column = left.column()
        a = self._model.sort_key(left.row(), column)
        b = self._model.sort_key(right.row(), column)
        return bool(a < b)


class CellDelegate(QStyledItemDelegate):
    """Draws a cell in its own colour even when selected, and the NEW tag after a name.

    A selected row would otherwise repaint every cell in one highlight colour and the
    green of "Online" would be lost exactly when you are looking at that row.
    """

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        badge = str(index.data(BADGE_ROLE) or "")
        rect = opt.rect.adjusted(8, 0, -8, 0)
        metrics = opt.fontMetrics

        if index.column() == STATUS:
            device = index.data(DEVICE_ROLE)
            if device is not None:
                tokens = theme.current()
                centre = QPointF(rect.left() + 5, rect.center().y() + 1)
                dot = tokens.online if device.online else tokens.offline
                status_dot(painter, centre, dot, online=device.online)
                rect = rect.adjusted(16, 0, 0, 0)

        pill_font = QFont(opt.font)
        pill_font.setPointSizeF(max(7.5, opt.font.pointSizeF() - 2))
        pill_font.setBold(True)
        pill_metrics = None
        pill_width = 0
        if badge:
            from PySide6.QtGui import QFontMetrics

            pill_metrics = QFontMetrics(pill_font)
            pill_width = pill_metrics.horizontalAdvance(badge) + 12

        room = rect.width() - pill_width - 6
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, room)
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(opt.palette.color(QPalette.ColorRole.Text))
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(foreground, QBrush):
            painter.setPen(foreground.color())
        painter.drawText(
            rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided
        )

        if badge and pill_metrics is not None:
            left = rect.left() + metrics.horizontalAdvance(elided) + 8
            height = pill_metrics.height() + 2
            top = rect.top() + (rect.height() - height) / 2
            tag = QRectF(left, top, pill_width, height)
            colour = QColor(theme.current().new)
            fill = QColor(colour)
            fill.setAlpha(36)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(tag, height / 2, height / 2)
            painter.setPen(colour)
            painter.setFont(pill_font)
            painter.drawText(tag, int(Qt.AlignmentFlag.AlignCenter), badge)
        painter.restore()


EVENT_COLUMNS = ("When", "Device", "Event", "Detail")


class EventsModel(QAbstractTableModel):
    """The activity log, newest first."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._events: list[Event] = []
        self._names: dict[int, str] = {}

    def set_events(self, events: Sequence[Event], names: dict[int, str]) -> None:
        self.beginResetModel()
        self._events = list(events)
        self._names = dict(names)
        self.endResetModel()

    def rowCount(  # noqa: N802
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(self._events)

    def columnCount(  # noqa: N802
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(EVENT_COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return EVENT_COLUMNS[section]
        return None

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return None
        event = self._events[index.row()]
        column = index.column()
        tokens = theme.current()
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                clock(event.at),
                self._names.get(event.device_id, f"#{event.device_id}"),
                event_title(event),
                event.detail,
            )[column]
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == 0:
                return QBrush(QColor(tokens.muted))
            if column == 2:
                return QBrush(QColor(self._colour_for(event.kind, tokens)))
        return None

    @staticmethod
    def _colour_for(kind: EventKind, tokens: theme.Tokens) -> str:
        if kind is EventKind.DISCOVERED:
            return tokens.new
        if kind is EventKind.ONLINE:
            return tokens.online
        if kind is EventKind.OFFLINE:
            return tokens.offline
        if kind in (EventKind.IP_CHANGED, EventKind.PORTS_CHANGED, EventKind.HOSTNAME_CHANGED):
            return tokens.warn
        return tokens.text
