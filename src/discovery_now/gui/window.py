"""The main window."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
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

from .. import APP_NAME, __version__
from .. import export as exporting
from ..config import Settings, config_dir, config_path, data_dir
from ..discovery import ScanReport
from ..models import Device, ScanOutcome, utcnow
from ..store import Store
from . import models as m
from .detail import DetailPanel
from .icons import app_icon
from .models import CellDelegate, DevicesModel, DevicesProxy, EventsModel
from .prefs import INTERVALS, Preferences, snap_interval
from .viewmodel import Filter, ago, counts, scan_summary, stage_title
from .worker import ScanRunner

_PAGE_EMPTY, _PAGE_TABLE, _PAGE_NO_MATCH = range(3)
_TAB_DEVICES, _TAB_ACTIVITY = range(2)


def _interval_label(minutes: int) -> str:
    if minutes == 60:
        return "1 hour"
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


class MainWindow(QMainWindow):
    """Devices, activity, and the controls that keep the inventory fresh."""

    def __init__(
        self,
        settings: Settings,
        *,
        store_path: Path | None = None,
        prefs: Preferences | None = None,
        autostart: bool = True,
        use_tray: bool = True,
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

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self._fit_to_screen()
        self.setMinimumSize(900, 520)

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

        self.reload()
        self._apply_auto_scan()
        self._refresh_status()
        if autostart and self._prefs.auto_scan:
            QTimer.singleShot(400, lambda: self.scan(manual=False))

    def _fit_to_screen(self) -> None:
        """Open at a comfortable size, but never larger than the screen allows."""
        screen = self.screen()
        room = screen.availableGeometry() if screen else None
        width = min(1320, room.width() - 40) if room else 1320
        height = min(800, room.height() - 60) if room else 800
        self.resize(width, height)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 14, 20, 10)
        outer.setSpacing(12)
        outer.addLayout(self._build_header())

        self._banner = self._build_banner()
        outer.addWidget(self._banner)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_devices_page())
        self._pages.addWidget(self._build_activity_page())
        outer.addWidget(self._pages, 1)
        self.setCentralWidget(root)
        self._build_status_bar()

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        title = QLabel(APP_NAME)
        title.setObjectName("title")
        row.addWidget(title)
        row.addSpacing(24)

        group = QButtonGroup(self)
        self._tab_buttons: list[QPushButton] = []
        for index, text in ((_TAB_DEVICES, "Devices"), (_TAB_ACTIVITY, "Activity")):
            button = QPushButton(text)
            button.setObjectName("tab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self.show_tab(i))
            group.addButton(button, index)
            row.addWidget(button)
            self._tab_buttons.append(button)
        self._tab_buttons[_TAB_DEVICES].setChecked(True)
        row.addStretch(1)

        self._auto_check = QCheckBox("Scan every")
        self._auto_check.setToolTip("Keep the inventory up to date by scanning on its own")
        self._interval = QComboBox()
        for minutes in INTERVALS:
            self._interval.addItem(_interval_label(minutes), minutes)
        row.addWidget(self._auto_check)
        row.addWidget(self._interval)
        row.addSpacing(10)

        self._export_button = QPushButton("Export")
        self._export_button.setToolTip("Save the inventory as a file")
        self._export_button.setMenu(self._build_export_menu())
        row.addWidget(self._export_button)

        self._more_button = QPushButton("More")
        self._more_button.setMenu(self._build_more_menu())
        row.addWidget(self._more_button)

        self._scan_button = QPushButton("Scan now")
        self._scan_button.setObjectName("primary")
        self._scan_button.setToolTip("Look for devices on your network (F5)")
        self._scan_button.setMinimumWidth(110)
        row.addWidget(self._scan_button)
        return row

    def _build_export_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Export as CSV…", lambda: self.export(exporting.ExportFormat.CSV))
        menu.addAction("Export as JSON…", lambda: self.export(exporting.ExportFormat.JSON))
        menu.addSeparator()
        self._redact_action = menu.addAction("Hide private details in exports")
        self._redact_action.setCheckable(True)
        self._redact_action.setToolTip(
            "Hide the unique half of each MAC address, and every name and note"
        )
        return menu

    def _build_more_menu(self) -> QMenu:
        menu = QMenu(self)
        self._notify_action = menu.addAction("Notify me about new devices")
        self._notify_action.setCheckable(True)
        menu.addSeparator()
        menu.addAction("Open settings file", self._open_settings_file)
        menu.addAction("Open data folder", self._open_data_folder)
        menu.addSeparator()
        menu.addAction(f"About {APP_NAME}", self._about)
        return menu

    def _build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("banner")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 8, 8, 8)
        self._banner_text = QLabel()
        self._banner_text.setWordWrap(True)
        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(banner.hide)
        layout.addWidget(self._banner_text, 1)
        layout.addWidget(dismiss)
        banner.hide()
        return banner

    def _build_devices_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._chips: dict[Filter, QPushButton] = {}
        chip_group = QButtonGroup(self)
        chip_group.setExclusive(True)
        for quick in Filter:
            chip = QPushButton(quick.label)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _checked=False, q=quick: self.set_filter(q))
            chip_group.addButton(chip)
            bar.addWidget(chip)
            self._chips[quick] = chip
        self._chips[Filter.ALL].setChecked(True)
        bar.addStretch(1)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search name, address, MAC, vendor…   (Ctrl+F)")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(320)
        bar.addWidget(self._search)
        layout.addLayout(bar)

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
        self._split.setSizes([960, 300])
        layout.addWidget(self._split, 1)
        return page

    def _build_table(self) -> QTableView:
        table = QTableView()
        table.setModel(self._proxy)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setSortingEnabled(True)
        table.setWordWrap(False)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.setItemDelegate(CellDelegate(table))
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(40)
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
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel("No devices yet")
        heading.setObjectName("title")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(
            "Scan your network to see what is connected.\n"
            "Nothing is installed on the devices and no administrator rights are needed."
        )
        text.setObjectName("muted")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_scan = QPushButton("Scan now")
        self._empty_scan.setObjectName("primary")
        self._empty_scan.setMinimumWidth(140)
        layout.addWidget(heading)
        layout.addWidget(text)
        layout.addSpacing(10)
        layout.addWidget(self._empty_scan, 0, Qt.AlignmentFlag.AlignCenter)
        return page

    def _build_no_match(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel("No device matches the filter or the search.")
        text.setObjectName("muted")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clear = QPushButton("Show all devices")
        clear.clicked.connect(self.clear_filters)
        layout.addWidget(text)
        layout.addSpacing(8)
        layout.addWidget(clear, 0, Qt.AlignmentFlag.AlignCenter)
        return page

    def _build_activity_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._activity_empty = QLabel("Nothing has happened yet. Scan the network first.")
        self._activity_empty.setObjectName("muted")
        self._activity_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._activity = QTableView()
        self._activity.setModel(self._events)
        self._activity.setShowGrid(False)
        self._activity.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._activity.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._activity.verticalHeader().hide()
        self._activity.verticalHeader().setDefaultSectionSize(36)
        header = self._activity.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self._activity_empty)
        layout.addWidget(self._activity, 1)
        return page

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self._status = QLabel()
        bar.addWidget(self._status, 1)
        self._progress = QProgressBar()
        self._progress.setFixedWidth(180)
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
        # Initial values go in before the signals are connected: setting them is not
        # a change by the user and must not overwrite what is remembered.
        self._auto_check.setChecked(self._prefs.auto_scan)
        self._interval.setCurrentIndex(INTERVALS.index(self._prefs.interval_minutes))
        self._redact_action.setChecked(self._prefs.redact_exports)
        self._notify_action.setChecked(self._prefs.notifications)

        self._scan_button.clicked.connect(lambda: self.scan(manual=True))
        self._empty_scan.clicked.connect(lambda: self.scan(manual=True))
        self._search.textChanged.connect(self._on_search)
        self._auto_check.toggled.connect(self._on_auto_changed)
        self._interval.currentIndexChanged.connect(self._on_auto_changed)
        self._redact_action.toggled.connect(self._on_redact_toggled)
        self._notify_action.toggled.connect(self._on_notify_toggled)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        self._detail.renamed.connect(self._on_renamed)
        self._detail.notes_saved.connect(self._on_notes)
        self._detail.approval_changed.connect(self._on_approval)
        self._detail.forget_requested.connect(self._on_forget)

        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)

        shortcuts = (
            ("F5", lambda: self.scan(manual=True)),
            ("Ctrl+R", lambda: self.scan(manual=True)),
            ("Ctrl+F", self._focus_search),
            ("Ctrl+1", lambda: self.show_tab(_TAB_DEVICES)),
            ("Ctrl+2", lambda: self.show_tab(_TAB_ACTIVITY)),
        )
        for keys, action in shortcuts:
            QShortcut(QKeySequence(keys), self).activated.connect(action)

    def _restore_layout(self) -> None:
        geometry = self._prefs.geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter = self._prefs.splitter()
        if splitter is not None:
            self._split.restoreState(splitter)

    # ------------------------------------------------------------- navigation

    def show_tab(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._tab_buttons[index].setChecked(True)

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
        self.show_tab(_TAB_DEVICES)
        self._search.setFocus()
        self._search.selectAll()

    def keyPressEvent(self, event: object) -> None:  # noqa: N802
        from PySide6.QtGui import QKeyEvent

        if (
            isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and self._search.text()
        ):
            self._search.clear()
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]

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

    def selected_device(self) -> Device | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._model.device_at(self._proxy.mapToSource(rows[0]).row())

    def _on_selection_changed(self, *_ignored: object) -> None:
        device = self.selected_device()
        self._selected_id = device.id if device else None
        # Whatever was being typed belongs to the device that is leaving. The id above
        # is already the new one, so the refresh this triggers does not pull the
        # selection back to the old row.
        self._detail.flush()
        self._show_selected()

    def _show_selected(self) -> None:
        device = self.selected_device()
        events = self._store.events(device_id=device.id, limit=40) if device else []
        self._detail.show_device(device, events, new_within=self._new_within)

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

    def _column_menu(self, position: QPoint) -> None:
        """Let the user choose which columns the table shows."""
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

    def _context_menu(self, position: QPoint) -> None:
        index = self._table.indexAt(position)
        if not index.isValid():
            return
        self._table.selectRow(index.row())
        device = self.selected_device()
        if device is None:
            return
        menu = QMenu(self)
        clipboard = QGuiApplication.clipboard()
        menu.addAction("Copy address", lambda: clipboard.setText(device.ip))
        if device.mac:
            menu.addAction("Copy MAC", lambda: clipboard.setText(device.mac or ""))
        menu.addSeparator()
        menu.addAction(
            "Withdraw approval" if device.approved else "Approve",
            lambda: self._on_approval(device.id, not device.approved),
        )
        menu.addAction("Forget…", lambda: self._on_forget(device.id))
        menu.exec(self._table.viewport().mapToGlobal(position))

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
        self._scan_button.setEnabled(not busy)
        self._scan_button.setText("Scanning…" if busy else "Scan now")
        self._empty_scan.setEnabled(not busy)
        self._empty_scan.setText("Scanning…" if busy else "Scan now")
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

    # ------------------------------------------------------------- auto scan

    def _on_auto_changed(self, *_ignored: object) -> None:
        self._prefs.auto_scan = self._auto_check.isChecked()
        self._prefs.interval_minutes = int(self._interval.currentData())
        self._apply_auto_scan()

    def _apply_auto_scan(self) -> None:
        self._interval.setEnabled(self._auto_check.isChecked())
        if self._auto_check.isChecked():
            self._auto.start(int(self._interval.currentData()) * 60_000)
        else:
            self._auto.stop()

    def _on_redact_toggled(self, checked: bool) -> None:
        self._prefs.redact_exports = checked

    def _on_notify_toggled(self, checked: bool) -> None:
        self._prefs.notifications = checked

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
        redact = self._redact_action.isChecked()
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

    def on_theme_changed(self) -> None:
        """Redraw what is painted with colours after the system switched appearance."""
        self._model.refresh()
        self._events.layoutChanged.emit()
        self._show_selected()

    def _bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_clicked(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._bring_to_front()

    def _open_settings_file(self) -> None:
        path = Settings().write_default(config_path())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_data_folder(self) -> None:
        folder = data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> {__version__}<br><br>"
            "Finds the devices on your own network, keeps an inventory and tells you "
            "when something new appears.<br><br>"
            "It only looks: it reads the network's own answers and never logs in to, "
            "changes or listens to any device. Everything stays on this computer.<br><br>"
            f"Settings: {config_dir()}<br>Data: {data_dir()}<br><br>"
            "MIT licence · TrueScaleTech",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
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
