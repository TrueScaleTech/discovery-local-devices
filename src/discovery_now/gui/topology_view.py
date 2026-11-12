"""The Network Topology screen: the map, and what you can do on it."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Device
from . import icons, theme
from .topology import Map, Node, fit_scale, plan
from .viewmodel import ports_text

#: How big a node is drawn on screen, before zoom is taken into account.
_GATEWAY_RADIUS = 30.0
_NODE_RADIUS = 21.0
#: Below this zoom the labels are dropped: they would overlap into a grey mass.
_LABEL_FLOOR = 0.5


class Canvas(QWidget):
    """Draws the map and handles the mouse.

    Positions are kept in the map's own units and turned into screen points as
    they are drawn, so text stays the same size however far the map is zoomed.
    """

    #: A node was clicked, by device id.
    selected = Signal(object)
    #: A node was double-clicked.
    opened = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._map = Map(nodes=(), edges=(), gateway=None)
        self._scale = 1.0
        self._pan = QPointF(0, 0)
        self._hover: int | None = None
        self._selected_id: int | None = None
        self._drag_from: QPointF | None = None
        self._dragged = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumHeight(320)

    # -- content -----------------------------------------------------------

    def set_map(self, value: Map, *, keep_view: bool = True) -> None:
        self._map = value
        if not keep_view:
            self.fit()
        self.update()

    @property
    def node_count(self) -> int:
        return len(self._map.nodes)

    def select_device(self, device_id: int | None) -> None:
        self._selected_id = device_id
        self.update()

    def selected_node(self) -> Node | None:
        for node in self._map.nodes:
            if node.device_id is not None and node.device_id == self._selected_id:
                return node
        return None

    # -- the view ----------------------------------------------------------

    def fit(self) -> None:
        """Bring the whole map into view, centred."""
        self._scale = fit_scale(self._map.radius, self.width(), self.height())
        self._pan = QPointF(0, 0)
        self.update()

    def zoom_by(self, factor: float) -> None:
        self._scale = max(0.12, min(2.4, self._scale * factor))
        self.update()

    def _centre(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2) + self._pan

    def _screen(self, node: Node) -> QPointF:
        centre = self._centre()
        return QPointF(centre.x() + node.x * self._scale, centre.y() + node.y * self._scale)

    def _radius(self, node: Node) -> float:
        base = _GATEWAY_RADIUS if node.is_gateway else _NODE_RADIUS
        return max(7.0, min(base, base * self._scale * 1.25))

    def _at(self, point: QPointF) -> int | None:
        for index in reversed(range(len(self._map.nodes))):
            node = self._map.nodes[index]
            at = self._screen(node)
            distance = math.hypot(point.x() - at.x(), point.y() - at.y())
            if distance <= self._radius(node) + 3:
                return index
        return None

    # -- drawing -----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        tokens = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(tokens.sunken))
        if not self._map.nodes:
            return

        self._draw_edges(painter, tokens)
        labels = self._scale >= _LABEL_FLOOR
        for index, node in enumerate(self._map.nodes):
            self._draw_node(painter, tokens, index, node, labels=labels)

    def _draw_edges(self, painter: QPainter, tokens: theme.Tokens) -> None:
        for start, end in self._map.edges:
            first, second = self._map.nodes[start], self._map.nodes[end]
            lit = self._hover in (start, end) or (
                second.device_id is not None and second.device_id == self._selected_id
            )
            pen = QPen(QColor(tokens.accent if lit else tokens.border_strong))
            pen.setWidthF(2.0 if lit else 1.3)
            painter.setPen(pen)
            painter.drawLine(self._screen(first), self._screen(second))

    def _draw_node(
        self, painter: QPainter, tokens: theme.Tokens, index: int, node: Node, *, labels: bool
    ) -> None:
        centre = self._screen(node)
        radius = self._radius(node)
        chosen = node.device_id is not None and node.device_id == self._selected_id
        edge = tokens.online if node.online else tokens.border_strong

        if chosen:
            halo = QPen(QColor(tokens.accent))
            halo.setWidthF(2.0)
            painter.setPen(halo)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, radius + 5, radius + 5)

        painter.setPen(QPen(QColor(edge), 2.0 if node.online else 1.4))
        painter.setBrush(QBrush(QColor(tokens.raised if index == self._hover else tokens.surface)))
        painter.drawEllipse(centre, radius, radius)

        if radius >= 12:
            glyph = QRectF(
                centre.x() - radius * 0.56,
                centre.y() - radius * 0.56,
                radius * 1.12,
                radius * 1.12,
            )
            colour = tokens.text if node.online else tokens.muted
            icons.paint(painter, icons.device_icon(node.kind), glyph, colour, width=2.2)

        if node.is_new:
            painter.setPen(QPen(QColor(tokens.new), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, radius + 2.5, radius + 2.5)
        if not node.approved and not node.is_gateway:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(tokens.warn)))
            corner = QPointF(centre.x() + radius * 0.72, centre.y() - radius * 0.72)
            painter.drawEllipse(corner, 3.4, 3.4)

        if labels:
            self._draw_label(painter, tokens, node, centre, radius)

    def _draw_label(
        self,
        painter: QPainter,
        tokens: theme.Tokens,
        node: Node,
        centre: QPointF,
        radius: float,
    ) -> None:
        name = QFont(self.font())
        name.setPointSizeF(max(8.0, self.font().pointSizeF() - 0.5))
        name.setBold(node.is_gateway)
        painter.setFont(name)
        metrics = painter.fontMetrics()
        text = metrics.elidedText(node.label, Qt.TextElideMode.ElideRight, 150)
        box = QRectF(centre.x() - 80, centre.y() + radius + 5, 160, metrics.height())
        painter.setPen(QColor(tokens.text if node.online else tokens.muted))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignHCenter), text)

        small = QFont(name)
        small.setPointSizeF(max(7.0, name.pointSizeF() - 1.2))
        small.setBold(False)
        painter.setFont(small)
        painter.setPen(QColor(tokens.faint))
        under = QRectF(box.left(), box.bottom(), box.width(), metrics.height())
        painter.drawText(under, int(Qt.AlignmentFlag.AlignHCenter), node.ip)

    # -- mouse -------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's name
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = QPointF(event.position())
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's name
        point = QPointF(event.position())
        if self._drag_from is not None:
            shift = point - self._drag_from
            if abs(shift.x()) + abs(shift.y()) > 3:
                self._dragged = True
                self._pan += shift
                self._drag_from = point
                self.update()
            return
        found = self._at(point)
        if found != self._hover:
            self._hover = found
            over = found is not None
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.OpenHandCursor
            )
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's name
        was_dragging = self._dragged
        self._drag_from = None
        self._dragged = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if was_dragging or event.button() != Qt.MouseButton.LeftButton:
            return
        found = self._at(QPointF(event.position()))
        node = self._map.nodes[found] if found is not None else None
        self._selected_id = node.device_id if node else None
        self.update()
        self.selected.emit(self._selected_id)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's name
        found = self._at(QPointF(event.position()))
        if found is None:
            self.fit()
            return
        node = self._map.nodes[found]
        if node.device_id is not None:
            self.opened.emit(node.device_id)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt's name
        steps = event.angleDelta().y() / 120
        if steps:
            self.zoom_by(1.12**steps)


class InfoCard(QFrame):
    """What one node is, shown over the map when it is clicked."""

    approve = Signal(int, bool)
    open_device = Signal(int)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self._device: Device | None = None
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 12, 12, 12)
        column.setSpacing(6)

        top = QHBoxLayout()
        self._name = QLabel()
        self._name.setObjectName("section")
        shut = QPushButton("Close")
        shut.setObjectName("quiet")
        shut.clicked.connect(self.closed)
        top.addWidget(self._name, 1)
        top.addWidget(shut)
        column.addLayout(top)

        self._subtitle = QLabel()
        self._subtitle.setObjectName("muted")
        self._facts = QLabel()
        self._facts.setObjectName("muted")
        self._facts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self._subtitle)
        column.addWidget(self._facts)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._approve = QPushButton("Approve")
        self._approve.clicked.connect(self._toggle)
        self._open = QPushButton("Show in Devices")
        self._open.clicked.connect(self._show)
        buttons.addWidget(self._approve)
        buttons.addWidget(self._open)
        buttons.addStretch(1)
        column.addLayout(buttons)
        self.setFixedWidth(330)

    def show_device(self, device: Device | None, *, new_within: timedelta) -> None:
        self._device = device
        if device is None:
            self.hide()
            return
        from ..fingerprint import kind_of

        tokens = theme.current()
        self._name.setText(device.name)
        parts = [part for part in (kind_of(device), device.vendor) if part]
        self._subtitle.setText(" · ".join(parts) or "Unidentified device")
        state = (
            f'<span style="color:{tokens.online}">Online</span>'
            if device.online
            else f'<span style="color:{tokens.offline}">Offline</span>'
        )
        if device.is_new(new_within):
            state += f' · <span style="color:{tokens.new}">NEW</span>'
        if not device.approved:
            state += f' · <span style="color:{tokens.warn}">Not approved</span>'
        ports = ports_text(device.open_ports) or "none found"
        self._facts.setText(
            f"{state}<br>{device.ip}<br>{device.mac or 'MAC unknown'}<br>Ports: {ports}"
        )
        self._approve.setText("Withdraw approval" if device.approved else "Approve")
        self.show()
        self.adjustSize()

    def _toggle(self) -> None:
        if self._device is not None:
            self.approve.emit(self._device.id, not self._device.approved)

    def _show(self) -> None:
        if self._device is not None:
            self.open_device.emit(self._device.id)


class TopologyPage(QWidget):
    """The map, with its legend, its controls and the card for one device."""

    approve = Signal(int, bool)
    open_device = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._devices: list[Device] = []
        self._new_within = timedelta(days=7)

        self.canvas = Canvas(self)
        self.empty = QLabel(
            "Nothing to map yet.\nScan your network and the devices will appear here.",
            self,
        )
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.legend = _legend_panel(self)
        self.card = InfoCard(self)
        self.card.hide()
        self.card.closed.connect(self._clear_selection)
        self.card.approve.connect(self.approve)
        self.card.open_device.connect(self.open_device)

        self.controls = QFrame(self)
        self.controls.setObjectName("panel")
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(4)
        for name, tip, action in (
            ("minus", "Zoom out", lambda: self.canvas.zoom_by(1 / 1.25)),
            ("plus", "Zoom in", lambda: self.canvas.zoom_by(1.25)),
            ("fit", "Fit the whole network", self.canvas.fit),
        ):
            button = QPushButton()
            button.setObjectName("quiet")
            button.setToolTip(tip)
            button.setFixedSize(30, 30)
            button.clicked.connect(action)
            button.setProperty("iconName", name)
            row.addWidget(button)
        self._control_buttons = self.controls.findChildren(QPushButton)

        self.canvas.selected.connect(self._on_selected)
        self.canvas.opened.connect(self.open_device)
        self.restyle()

    # -- content -----------------------------------------------------------

    def set_devices(
        self,
        devices: Sequence[Device],
        *,
        new_within: timedelta,
        gateways: Sequence[str] = (),
        local_ips: Sequence[str] = (),
    ) -> None:
        """Lay the map out again. The view only jumps to fit on the first set."""
        first = not self._devices
        self._devices = list(devices)
        self._new_within = new_within
        drawn = plan(
            self._devices,
            new_within=new_within,
            local_ips=local_ips,
            gateways=gateways,
        )
        self.canvas.set_map(drawn, keep_view=not first)
        self.empty.setVisible(not self._devices)
        self.canvas.setVisible(bool(self._devices))
        self._refresh_card()

    def select_device(self, device_id: int | None) -> None:
        self.canvas.select_device(device_id)
        self._refresh_card()

    def _on_selected(self, _device_id: object) -> None:
        self._refresh_card()

    def _clear_selection(self) -> None:
        self.canvas.select_device(None)
        self.card.hide()

    def _refresh_card(self) -> None:
        node = self.canvas.selected_node()
        if node is None or node.device_id is None:
            self.card.hide()
            return
        found = next((d for d in self._devices if d.id == node.device_id), None)
        self.card.show_device(found, new_within=self._new_within)
        self._place()

    # -- layout ------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt's name
        self.canvas.setGeometry(self.rect())
        self.empty.setGeometry(self.rect())
        self._place()

    def _place(self) -> None:
        margin = 14
        self.legend.adjustSize()
        self.legend.move(self.width() - self.legend.width() - margin, margin)
        self.controls.adjustSize()
        self.controls.move(
            self.width() - self.controls.width() - margin,
            self.height() - self.controls.height() - margin,
        )
        if self.card.isVisible():
            self.card.adjustSize()
            self.card.move(margin, self.height() - self.card.height() - margin)

    def restyle(self) -> None:
        """Redraw the parts that are painted rather than styled."""
        tokens = theme.current()
        for button in self._control_buttons:
            name = button.property("iconName")
            if name:
                button.setIcon(icons.icon(str(name), tokens.muted, 18))
        _fill_legend(self.legend)
        self.canvas.update()


def _legend_panel(parent: QWidget) -> QFrame:
    panel = QFrame(parent)
    panel.setObjectName("panel")
    column = QVBoxLayout(panel)
    column.setContentsMargins(12, 10, 12, 10)
    column.setSpacing(4)
    for text in ("Online", "Offline", "New", "Not approved"):
        label = QLabel(text)
        label.setProperty("legend", text)
        column.addWidget(label)
    return panel


#: What each legend row's dot means, and which token colours it.
_LEGEND_ROLES = {
    "Online": "online",
    "Offline": "border_strong",
    "New": "new",
    "Not approved": "warn",
}


def _fill_legend(panel: QFrame) -> None:
    tokens = theme.current()
    for label in panel.findChildren(QLabel):
        key = str(label.property("legend") or "")
        role = _LEGEND_ROLES.get(key)
        if not role:
            continue
        colour = str(getattr(tokens, role))
        label.setText(
            f'<span style="color:{colour}">●</span> <span style="color:{tokens.muted}">{key}</span>'
        )
