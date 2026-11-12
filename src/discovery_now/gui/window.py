"""The main window: the rail, the four screens, and what ties them together."""

from __future__ import annotations

from datetime import timedelta
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from .. import export as exporting
from ..config import Settings
from ..discovery import ScanReport
from ..models import Device, ScanOutcome, utcnow
from ..store import Store
from . import icons, theme
from . import models as m
from .detail import DetailPanel
from .icons import app_icon, app_image
from .models import CellDelegate, DevicesModel, DevicesProxy, EventsModel
from .prefs import Preferences, snap_interval
from .settings_page import SettingsPage, interval_label
from .topology_view import TopologyPage
from .viewmodel import Filter, ago, counts, scan_summary, stage_title
from .widgets import Icon
from .worker import ScanRunner

_PAGE_EMPTY, _PAGE_TABLE, _PAGE_NO_MATCH = range(3)


class Screen(IntEnum):
    """The four places the rail can take you."""

    DEVICES = 0
    TOPOLOGY = 1
    ACTIVITY = 2
    SETTINGS = 3

    @property
    def title(self) -> str:
        return {
            Screen.DEVICES: "Devices",
            Screen.TOPOLOGY: "Network Topology",
            Screen.ACTIVITY: "Activity",
            Screen.SETTINGS: "Settings",
        }[self]

    @property
    def icon(self) -> str:
        return {
            Screen.DEVICES: "devices",
            Screen.TOPOLOGY: "topology",
            Screen.ACTIVITY: "activity",
            Screen.SETTINGS: "settings",
        }[self]


class MainWindow(QMainWindow):
    """The inventory, the map, the history and the settings."""

    def __init__(
        self,
        settings: Settings,
        *,
        store_path: Path | None = None,
        prefs: Preferences | None = None,
        autostart: bool = True,
        use_tray: bool = True,
        find_addresses: bool = True,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._new_within = timedelta(days=settings.new_device_days)
        self._store = Store(store_path)
        self._prefs = prefs or Preferences(
            default_interval=snap_interval(max(1, settings.watch_interval // 60))
        )
        self._runner = ScanRunner(lambda: Store(store_path), self)
        self._selected_id: int | None = None
        self._last_summary = ""
        self._last_scan = self._store.last_scan_at()
        self._gateways: list[str] = []
        self._local_ips: list[str] = []

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self._fit_to_screen()
        self.setMinimumSize(940, 560)

        self._model = DevicesModel(self._new_within, self)
        self._proxy = DevicesProxy(self._model, self)
        self._events = EventsModel(self)

        self._auto = QTimer(self)
        self._auto.timeout.connect(lambda: self.scan(manual=False))

        self._build()
        self._tray = self._build_tray() if use_tray else None
        self._wire()
        self._restore_layout()

        self._clock = QTimer(self)
        self._clock.setInterval(30_000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

        self.show_screen(Screen.DEVICES)
        self.reload()
        self._apply_schedule()
        self._refresh_status()
        if find_addresses:
            self._runner.find_addresses()
        if autostart and self._prefs.auto_scan:
            QTimer.singleShot(400, lambda: self.scan(manual=False))

    def _fit_to_screen(self) -> None:
        """Open at a comfortable size, but never larger than the screen allows."""
        screen = self.screen()
        room = screen.availableGeometry() if screen else None
        width = min(1360, room.width() - 40) if room else 1360
        height = min(820, room.height() - 60) if room else 820
        self.resize(width, height)

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_rail())

        content = QWidget()
        self._content = QVBoxLayout(content)
        tokens = theme.current()
        self._content.setContentsMargins(tokens.pad + 4, tokens.pad, tokens.pad + 4, tokens.gap)
        self._content.setSpacing(tokens.gap)

        self._banner = self._build_banner()
        self._content.addWidget(self._banner)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_devices_page())
        self._pages.addWidget(self._build_topology_page())
        self._pages.addWidget(self._build_activity_page())
        self._pages.addWidget(self._build_settings_page())
        self._content.addWidget(self._pages, 1)

        row.addWidget(content, 1)
        self.setCentralWidget(root)
        self._build_status_bar()

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(208)
        column = QVBoxLayout(rail)
        column.setContentsMargins(12, 14, 12, 14)
        column.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(9)
        mark = QLabel()
        # Drawn at twice the size and shown at half, so it is sharp on any screen.
        logo = QPixmap.fromImage(app_image(56))
        logo.setDevicePixelRatio(2.0)
        mark.setPixmap(logo)
        name = QLabel(APP_NAME)
        name.setObjectName("brand")
        brand.addWidget(mark)
        brand.addWidget(name, 1)
        column.addLayout(brand)
        column.addSpacing(16)

        self._nav: dict[Screen, QPushButton] = {}
        group = QButtonGroup(self)
        for screen in Screen:
            button = QPushButton(f"  {screen.title}")
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, s=screen: self.show_screen(s))
            group.addButton(button, int(screen))
            self._nav[screen] = button
            # Settings is not a place you work in, so it sits at the foot of the
            # rail, under the main action, rather than among the screens.
            if screen is not Screen.SETTINGS:
                column.addWidget(button)
        column.addStretch(1)

        self._scan_button = QPushButton("Scan now")
        self._scan_button.setObjectName("primary")
        self._scan_button.setToolTip("Look for devices on your network  (F5)")
        self._scan_button.setMinimumHeight(34)
        column.addWidget(self._scan_button)

        self._schedule_note = QLabel()
        self._schedule_note.setObjectName("faint")
        self._schedule_note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._schedule_note.setWordWrap(True)
        column.addWidget(self._schedule_note)
        column.addSpacing(6)
        column.addWidget(self._nav[Screen.SETTINGS])
        return rail

    def _page_header(self, screen: Screen) -> tuple[QWidget, QHBoxLayout]:
        """The title line every screen starts with, and room for its own controls."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        title = QLabel(screen.title)
        title.setObjectName("title")
        row.addWidget(title)
        row.addStretch(1)
        return holder, row

    def _build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("banner")
        row = QHBoxLayout(banner)
        row.setContentsMargins(12, 9, 9, 9)
        row.setSpacing(10)
        self._banner_icon = Icon("info", size=18, role="offline")
        self._banner_text = QLabel()
        self._banner_text.setWordWrap(True)
        dismiss = QPushButton("Dismiss")
        dismiss.setObjectName("quiet")
        dismiss.clicked.connect(banner.hide)
        row.addWidget(self._banner_icon)
        row.addWidget(self._banner_text, 1)
        row.addWidget(dismiss)
        banner.hide()
        return banner

    # -- devices ------------------------------------------------------------

    def _build_devices_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.current().gap)

        header, controls = self._page_header(Screen.DEVICES)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search name, address, MAC, vendor…   (Ctrl+F)")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(300)
        self._export_button = QPushButton("  Export")
        self._export_button.setMenu(self._build_export_menu())
        controls.addWidget(self._search)
        controls.addWidget(self._export_button)
        column.addWidget(header)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self._chips: dict[Filter, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for quick in Filter:
            chip = QPushButton(quick.label)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _c=False, q=quick: self.set_filter(q))
            group.addButton(chip)
            chips.addWidget(chip)
            self._chips[quick] = chip
        self._chips[Filter.ALL].setChecked(True)
        chips.addStretch(1)
        column.addLayout(chips)

        self._bulk = self._build_bulk_bar()
        column.addWidget(self._bulk)

        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.setChildrenCollapsible(False)
        self._list_stack = QStackedWidget()
        self._list_stack.addWidget(self._build_empty_state())
        self._table = self._build_table()
        self._list_stack.addWidget(self._table)
        self._list_stack.addWidget(self._build_no_match())
        self._split.addWidget(self._list_stack)
        self._detail = DetailPanel()
        self._split.addWidget(self._detail)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 0)
        self._split.setSizes([980, 320])
        column.addWidget(self._split, 1)
        return page

    def _build_bulk_bar(self) -> QFrame:
        """The actions that appear once more than one device is selected."""
        bar = QFrame()
        bar.setObjectName("bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 7, 8, 7)
        row.setSpacing(8)
        self._bulk_label = QLabel()
        row.addWidget(self._bulk_label, 1)
        self._bulk_approve = QPushButton("Approve")
        self._bulk_approve.clicked.connect(lambda: self._approve_selected(True))
        self._bulk_withdraw = QPushButton("Withdraw approval")
        self._bulk_withdraw.clicked.connect(lambda: self._approve_selected(False))
        self._bulk_forget = QPushButton("Forget")
        self._bulk_forget.setObjectName("danger")
        self._bulk_forget.clicked.connect(self._forget_selected)
        clear = QPushButton("Clear")
        clear.setObjectName("quiet")
        clear.clicked.connect(self._table_clear_selection)
        for button in (self._bulk_approve, self._bulk_withdraw, self._bulk_forget, clear):
            row.addWidget(button)
        bar.hide()
        return bar

    def _table_clear_selection(self) -> None:
        self._table.clearSelection()

    def _build_table(self) -> QTableView:
        table = QTableView()
        table.setModel(self._proxy)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # More than one at a time, so a handful of devices can be dealt with together.
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setSortingEnabled(True)
        table.setWordWrap(False)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.setItemDelegate(CellDelegate(table))
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(theme.current().row_height)
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSortIndicatorShown(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(60)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(m.NAME, QHeaderView.ResizeMode.Stretch)
        for column, width in m.COLUMN_WIDTHS.items():
            header.resizeSection(column, width)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._column_menu)
        hidden = self._prefs.hidden_columns(default=m.HIDDEN_BY_DEFAULT)
        for column in range(len(m.COLUMNS)):
            table.setColumnHidden(column, column in hidden)
        table.sortByColumn(m.ADDRESS, Qt.SortOrder.AscendingOrder)
        return table

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.setSpacing(6)
        mark = Icon("scan", size=40, role="border_strong")
        heading = QLabel("No devices yet")
        heading.setObjectName("title")
        text = QLabel(
            "Scan your network to see what is connected.\n"
            "Nothing is installed on the devices, and no administrator rights are needed."
        )
        text.setObjectName("muted")
        for widget in (heading, text):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_scan = QPushButton("Scan now")
        self._empty_scan.setObjectName("primary")
        self._empty_scan.setMinimumWidth(150)
        self._empty_scan.setMinimumHeight(34)
        column.addWidget(mark, 0, Qt.AlignmentFlag.AlignCenter)
        column.addSpacing(6)
        column.addWidget(heading)
        column.addWidget(text)
        column.addSpacing(10)
        column.addWidget(self._empty_scan, 0, Qt.AlignmentFlag.AlignCenter)
        return page

    def _build_no_match(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel("No device matches the filter or the search.")
        text.setObjectName("muted")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clear = QPushButton("Show all devices")
        clear.clicked.connect(self.clear_filters)
        column.addWidget(text)
        column.addSpacing(8)
        column.addWidget(clear, 0, Qt.AlignmentFlag.AlignCenter)
        return page

    def _build_export_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Export as CSV…", lambda: self.export(exporting.ExportFormat.CSV))
        menu.addAction("Export as JSON…", lambda: self.export(exporting.ExportFormat.JSON))
        return menu

    # -- the other screens ---------------------------------------------------

    def _build_topology_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.current().gap)
        header, controls = self._page_header(Screen.TOPOLOGY)
        note = QLabel("Everything behind your router, grouped by what it is")
        note.setObjectName("muted")
        controls.insertWidget(1, note)
        column.addWidget(header)
        self.topology_page = TopologyPage()
        self.topology_page.approve.connect(self._on_approval)
        self.topology_page.open_device.connect(self._open_in_devices)
        self.topology_page.canvas.set_placed(self._prefs.node_positions())
        self.topology_page.placed_changed.connect(self._prefs.save_node_positions)
        column.addWidget(self.topology_page, 1)
        return page

    def _build_activity_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.current().gap)
        header, _ = self._page_header(Screen.ACTIVITY)
        column.addWidget(header)

        self._activity_empty = QLabel("Nothing has happened yet. Scan the network first.")
        self._activity_empty.setObjectName("muted")
        self._activity_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._activity = QTableView()
        self._activity.setModel(self._events)
        self._activity.setShowGrid(False)
        self._activity.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._activity.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._activity.verticalHeader().hide()
        self._activity.verticalHeader().setDefaultSectionSize(theme.current().row_height - 6)
        header_view = self._activity.horizontalHeader()
        header_view.setHighlightSections(False)
        header_view.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header_view.setStretchLastSection(True)
        column.addWidget(self._activity_empty)
        column.addWidget(self._activity, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.current().gap)
        header, _ = self._page_header(Screen.SETTINGS)
        column.addWidget(header)
        self.settings_page = SettingsPage(
            self._prefs,
            self._settings,
            can_notify=QSystemTrayIcon.isSystemTrayAvailable(),
        )
        self.settings_page.appearance_changed.connect(self.restyle)
        self.settings_page.schedule_changed.connect(self._apply_schedule)
        self.settings_page.scan_changed.connect(self._on_scan_settings)
        self.settings_page.open_path.connect(self._open_path)
        column.addWidget(self.settings_page, 1)
        return page

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self._status = QLabel()
        bar.addWidget(self._status, 1)
        self._progress = QProgressBar()
        self._progress.setFixedWidth(170)
        self._progress.setTextVisible(False)
        self._progress.hide()
        bar.addPermanentWidget(self._progress)
        self._count = QLabel()
        bar.addPermanentWidget(self._count)

    def _build_tray(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction("Open", self._bring_to_front)
        menu.addAction("Scan now", lambda: self.scan(manual=True))
        menu.addSeparator()
        menu.addAction("Quit", QGuiApplication.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_clicked)
        tray.show()
        return tray

    # ----------------------------------------------------------------- wiring

    def _wire(self) -> None:
        self._scan_button.clicked.connect(lambda: self.scan(manual=True))
        self._empty_scan.clicked.connect(lambda: self.scan(manual=True))
        self._search.textChanged.connect(self._on_search)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self._detail.renamed.connect(self._on_renamed)
        self._detail.notes_saved.connect(self._on_notes)
        self._detail.approval_changed.connect(self._on_approval)
        self._detail.forget_requested.connect(self._on_forget)

        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._runner.addresses.connect(self._on_addresses)

        shortcuts = (
            ("F5", lambda: self.scan(manual=True)),
            ("Ctrl+R", lambda: self.scan(manual=True)),
            ("Ctrl+F", self._focus_search),
            ("Ctrl+1", lambda: self.show_screen(Screen.DEVICES)),
            ("Ctrl+2", lambda: self.show_screen(Screen.TOPOLOGY)),
            ("Ctrl+3", lambda: self.show_screen(Screen.ACTIVITY)),
            ("Ctrl+,", lambda: self.show_screen(Screen.SETTINGS)),
        )
        for keys, action in shortcuts:
            QShortcut(QKeySequence(keys), self).activated.connect(action)
        self.restyle()

    def _restore_layout(self) -> None:
        geometry = self._prefs.geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter = self._prefs.splitter()
        if splitter is not None:
            self._split.restoreState(splitter)

    # ------------------------------------------------------------- navigation

    def show_screen(self, screen: Screen) -> None:
        self._pages.setCurrentIndex(int(screen))
        for which, button in self._nav.items():
            button.setChecked(which is screen)

    @property
    def screen_shown(self) -> Screen:
        return Screen(self._pages.currentIndex())

    def set_filter(self, quick: Filter) -> None:
        self._chips[quick].setChecked(True)
        self._proxy.set_quick(quick)
        self._update_list_page()

    def clear_filters(self) -> None:
        self._search.clear()
        self.set_filter(Filter.ALL)

    def _on_search(self, text: str) -> None:
        self._proxy.set_query(text)
        self._update_list_page()

    def _focus_search(self) -> None:
        self.show_screen(Screen.DEVICES)
        self._search.setFocus()
        self._search.selectAll()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's name
        if event.key() == Qt.Key.Key_Escape and self._search.text():
            self._search.clear()
            return
        super().keyPressEvent(event)

    def _open_in_devices(self, device_id: int) -> None:
        """Jump from the map to the same device in the list."""
        self.show_screen(Screen.DEVICES)
        row = self._model.row_of(device_id)
        if row is None:
            return
        index = self._proxy.mapFromSource(self._model.index(row, 0))
        if index.isValid():
            self._table.selectRow(index.row())
            self._table.scrollTo(index)

    # ---------------------------------------------------------------- loading

    def reload(self) -> None:
        """Read the inventory again and redraw everything that shows it."""
        devices = self._store.devices()
        self._model.set_devices(devices)
        self._update_chips(devices)
        self._events.set_events(
            self._store.events(limit=300), {device.id: device.name for device in devices}
        )
        self._activity_empty.setVisible(self._events.rowCount() == 0)
        self._activity.setVisible(self._events.rowCount() > 0)
        self.topology_page.set_devices(
            devices,
            new_within=self._new_within,
            gateways=self._gateways,
            local_ips=self._local_ips,
        )

        total = len(devices)
        online = sum(1 for device in devices if device.online)
        self._count.setText(f"{total} known · {online} online" if total else "")
        self._update_list_page()
        self._restore_selection()

    def _update_chips(self, devices: list[Device]) -> None:
        tally = counts(devices, new_within=self._new_within)
        for quick, chip in self._chips.items():
            chip.setText(f"{quick.label}  {tally[quick]}")

    def _update_list_page(self) -> None:
        if self._model.rowCount() == 0:
            self._list_stack.setCurrentIndex(_PAGE_EMPTY)
        elif self._proxy.rowCount() == 0:
            self._list_stack.setCurrentIndex(_PAGE_NO_MATCH)
        else:
            self._list_stack.setCurrentIndex(_PAGE_TABLE)

    def _restore_selection(self) -> None:
        """Keep the same device selected after the list was rebuilt."""
        if self._selected_id is not None:
            row = self._model.row_of(self._selected_id)
            if row is not None:
                index = self._proxy.mapFromSource(self._model.index(row, 0))
                if index.isValid():
                    shown = self.selected_device()
                    if shown is None or shown.id != self._selected_id:
                        self._table.selectRow(index.row())
                    self._show_selected()
                    return
            self._selected_id = None
        self._show_selected()

    def selected_devices(self) -> list[Device]:
        """Every device whose row is selected."""
        rows = self._table.selectionModel().selectedRows()
        found = [self._model.device_at(self._proxy.mapToSource(index).row()) for index in rows]
        return sorted(found, key=lambda device: device.id)

    def selected_device(self) -> Device | None:
        """The one selected device, or None when none or several are selected."""
        found = self.selected_devices()
        return found[0] if len(found) == 1 else None

    def _on_selection_changed(self, *_ignored: object) -> None:
        device = self.selected_device()
        self._selected_id = device.id if device else None
        # The id above is already the new one, so the refresh that saving an edit
        # triggers cannot pull the selection back to the row being left.
        self._detail.flush()
        self._show_selected()

    def _show_selected(self) -> None:
        chosen = self.selected_devices()
        many = len(chosen) > 1
        self._bulk.setVisible(many)
        if many:
            unapproved = sum(1 for device in chosen if not device.approved)
            self._bulk_label.setText(
                f"{len(chosen)} devices selected"
                + (f" · {unapproved} not approved" if unapproved else "")
            )
            self._bulk_approve.setEnabled(unapproved > 0)
            self._bulk_withdraw.setEnabled(unapproved < len(chosen))
        device = chosen[0] if len(chosen) == 1 else None
        events = self._store.events(device_id=device.id, limit=40) if device else []
        self._detail.show_device(device, events, new_within=self._new_within)
        self.topology_page.select_device(device.id if device else None)

    # ------------------------------------------------------------------ edits

    def _on_renamed(self, device_id: int, text: str) -> None:
        self._store.set_label(device_id, text or None)
        self.reload()

    def _on_notes(self, device_id: int, text: str) -> None:
        self._store.set_notes(device_id, text or None)
        self.reload()

    def _on_approval(self, device_id: int, approved: bool) -> None:
        self._store.set_approved(device_id, approved)
        self.reload()

    def _approve_selected(self, approved: bool) -> None:
        """Approve, or withdraw approval from, every selected device at once."""
        chosen = [device for device in self.selected_devices() if device.approved != approved]
        for device in chosen:
            self._store.set_approved(device.id, approved)
        self.reload()
        word = "Approved" if approved else "Withdrew approval from"
        count = len(chosen)
        self._status.setText(f"{word} {count} device{'' if count == 1 else 's'}.")

    def _forget_selected(self) -> None:
        chosen = self.selected_devices()
        if not chosen:
            return
        count = len(chosen)
        if not self._confirm(
            f"Forget {count} devices?",
            f"{count} devices and their history will be removed from the inventory.\n"
            "Any that are still on the network will be listed as new at the next scan.",
        ):
            return
        for device in chosen:
            self._store.forget(device.id)
        self._selected_id = None
        self.reload()
        self._status.setText(f"Forgot {count} devices.")

    def _confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_forget(self, device_id: int) -> None:
        device = self._store.get(device_id)
        if device is None:
            return
        if not self._confirm(
            "Forget this device?",
            f"{device.name} and its history will be removed from the inventory.\n"
            "If it is still on the network, the next scan will list it as a new device.",
        ):
            return
        self._store.forget(device_id)
        self._selected_id = None
        self.reload()

    def _context_menu(self, position: QPoint) -> None:
        index = self._table.indexAt(position)
        if not index.isValid():
            return
        chosen = self.selected_devices()
        if len(chosen) <= 1:
            self._table.selectRow(index.row())
            chosen = self.selected_devices()
        if not chosen:
            return
        menu = QMenu(self)
        clipboard = QGuiApplication.clipboard()
        if len(chosen) == 1:
            device = chosen[0]
            menu.addAction("Copy address", lambda: clipboard.setText(device.ip))
            if device.mac:
                menu.addAction("Copy MAC", lambda: clipboard.setText(device.mac or ""))
            menu.addAction("Show on the map", lambda: self._show_on_map(device.id))
            menu.addSeparator()
            menu.addAction(
                "Withdraw approval" if device.approved else "Approve",
                lambda: self._on_approval(device.id, not device.approved),
            )
            menu.addAction("Forget…", lambda: self._on_forget(device.id))
        else:
            menu.addAction(f"Approve {len(chosen)} devices", lambda: self._approve_selected(True))
            menu.addAction("Withdraw approval", lambda: self._approve_selected(False))
            menu.addSeparator()
            menu.addAction(f"Forget {len(chosen)} devices…", self._forget_selected)
        menu.exec(self._table.viewport().mapToGlobal(position))

    def _show_on_map(self, device_id: int) -> None:
        self.show_screen(Screen.TOPOLOGY)
        self.topology_page.select_device(device_id)

    def _column_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        for column, title in enumerate(m.COLUMNS):
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(column))
            action.setEnabled(column != m.NAME)
            action.toggled.connect(lambda shown, c=column: self._show_column(c, shown))
        menu.exec(self._table.horizontalHeader().mapToGlobal(position))

    def _show_column(self, column: int, shown: bool) -> None:
        self._table.setColumnHidden(column, not shown)
        hidden = {c for c in range(len(m.COLUMNS)) if self._table.isColumnHidden(c)}
        self._prefs.save_hidden_columns(hidden)

    # --------------------------------------------------------------- scanning

    def scan(self, *, manual: bool) -> None:
        """Start a scan, unless one is already running."""
        if self._runner.running:
            return
        self._detail.flush()
        self._set_scanning(True)
        self._progress.setRange(0, 0)
        self._status.setText("Scanning your network…")
        self._runner.start(self._settings)
        if manual:
            self._banner.hide()

    def _set_scanning(self, busy: bool) -> None:
        for button in (self._scan_button, self._empty_scan):
            button.setEnabled(not busy)
            button.setText("Scanning…" if busy else "Scan now")
        self._progress.setVisible(busy)

    def _on_progress(self, stage: str, done: int, total: int) -> None:
        self._progress.setRange(0, max(total, 1))
        self._progress.setValue(done)
        self._status.setText(f"{stage_title(stage)}…  {done} of {total}")

    def _on_finished(self, report: ScanReport, outcome: ScanOutcome, was_empty: bool) -> None:
        self._set_scanning(False)
        self._banner.hide()
        self._last_scan = utcnow()
        self._last_summary = scan_summary(
            report.found,
            new=len(outcome.discovered),
            back=len(outcome.back_online),
            gone=len(outcome.went_offline),
            changed=len(outcome.changed),
        )
        self.reload()
        self._refresh_status()
        if outcome.discovered and not was_empty and self._prefs.notifications:
            self._notify_new(outcome.discovered)

    def _on_failed(self, message: str) -> None:
        self._set_scanning(False)
        self._banner_text.setText(f"The scan could not run. {message}")
        self._banner.show()
        self._refresh_status()

    def _notify_new(self, found: list[Device]) -> None:
        if self._tray is None:
            return
        if len(found) == 1:
            body = f"{found[0].name} ({found[0].ip})"
        else:
            body = f"{len(found)} new devices appeared on your network."
        self._tray.showMessage(
            "New device on your network", body, QSystemTrayIcon.MessageIcon.Information, 10_000
        )

    def _on_addresses(self, gateways: list[str], local: list[str]) -> None:
        """The routing table came back: redraw the map around the real gateway."""
        self._gateways = gateways
        self._local_ips = local
        self.topology_page.set_devices(
            self._store.devices(),
            new_within=self._new_within,
            gateways=self._gateways,
            local_ips=self._local_ips,
        )

    # --------------------------------------------------------------- settings

    def _apply_schedule(self) -> None:
        minutes = self._prefs.interval_minutes
        if self._prefs.auto_scan:
            self._auto.start(minutes * 60_000)
            self._schedule_note.setText(f"Scanning {interval_label(minutes)}")
        else:
            self._auto.stop()
            self._schedule_note.setText("Automatic scanning is off")

    def _on_scan_settings(self) -> None:
        """A setting a scan depends on changed, and was saved to config.toml."""
        self._new_within = timedelta(days=self._settings.new_device_days)
        self._model.set_new_window(self._new_within)
        self.reload()

    def _open_path(self, path: str) -> None:
        target = Path(path)
        if target.suffix and not target.exists():
            self._settings.save(target)
        elif not target.suffix:
            target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def restyle(self) -> None:
        """Re-apply the appearance after a preference changed, or the system did.

        Styling the application restyles every widget it owns, so it is only done
        when the appearance in use is not already the one asked for. A window
        opening into the appearance it wants costs nothing.
        """
        app = QApplication.instance()
        if isinstance(app, QApplication):
            accent = theme.accent_for(self._prefs.accent)
            in_use = theme.current()
            wanted = (
                theme.resolve_dark(app, self._prefs.mode),
                self._prefs.mode is theme.Mode.BLACK,
                accent.key,
            )
            if (in_use.dark, in_use.black, in_use.accent_key) != wanted:
                theme.apply(app, mode=self._prefs.mode, accent=accent)
                icons.forget_cached_icons()
        tokens = theme.current()
        for screen, button in self._nav.items():
            button.setIcon(icons.icon(screen.icon, tokens.muted, 18))
        self._export_button.setIcon(icons.icon("export", tokens.muted, 17))
        self._table.verticalHeader().setDefaultSectionSize(tokens.row_height)
        self._activity.verticalHeader().setDefaultSectionSize(tokens.row_height - 6)
        self._content.setContentsMargins(tokens.pad + 4, tokens.pad, tokens.pad + 4, tokens.gap)
        self.topology_page.restyle()
        self.settings_page.restyle()
        self._model.refresh()
        self._events.layoutChanged.emit()
        self._show_selected()
        self.update()

    # ----------------------------------------------------------------- export

    def export(self, fmt: exporting.ExportFormat) -> None:
        """Ask where to save, then write the whole inventory."""
        is_csv = fmt is exporting.ExportFormat.CSV
        suggestion = str(Path.home() / f"devices.{fmt.value}")
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Export devices",
            suggestion,
            "CSV files (*.csv)" if is_csv else "JSON files (*.json)",
        )
        if not chosen:
            return
        devices = self._store.devices()
        redact = self._prefs.redact_exports
        table = exporting.rows(devices, new_within=self._new_within, redact=redact)
        try:
            exporting.write(Path(chosen), exporting.render(table, fmt), fmt)
        except OSError as error:
            self._banner_text.setText(f"Could not save the file. {error}")
            self._banner.show()
            return
        note = " Private details are hidden." if redact else ""
        self._status.setText(f"Exported {len(devices)} devices to {chosen}.{note}")

    # --------------------------------------------------------------- the rest

    def _tick(self) -> None:
        self._model.refresh()
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self._runner.running:
            return
        if self._last_scan is None:
            self._status.setText("No scan yet.")
            return
        text = f"Last scan {ago(self._last_scan)}"
        if self._last_summary:
            text += f" · {self._last_summary}"
        self._status.setText(text)

    def _bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_clicked(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._bring_to_front()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's name
        self._detail.flush()
        self._prefs.save_geometry(self.saveGeometry())
        self._prefs.save_splitter(self._split.saveState())
        self._prefs.sync()
        self._auto.stop()
        self._clock.stop()
        if self._tray is not None:
            self._tray.hide()
        self._store.close()
        super().closeEvent(event)
