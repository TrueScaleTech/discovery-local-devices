"""The desktop window, driven the way a person would, on an invisible display."""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QFileDialog

from discovery_now import export as exporting
from discovery_now.config import Settings
from discovery_now.discovery import ScanReport
from discovery_now.gui import models as m
from discovery_now.gui import theme
from discovery_now.gui.prefs import Preferences
from discovery_now.gui.viewmodel import Filter
from discovery_now.gui.window import (
    _PAGE_EMPTY,
    _PAGE_NO_MATCH,
    _PAGE_TABLE,
    MainWindow,
)
from discovery_now.models import Observation, utcnow
from discovery_now.net import TargetError
from discovery_now.store import Store


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    assert isinstance(instance, QApplication)
    theme.apply(instance)
    return instance


def wait_until(app: QApplication, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Let the event loop run until something becomes true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the window")


def seen(ip: str, mac: str, hostname: str | None = None, **extra: Any) -> Observation:
    return Observation(ip=ip, mac=mac, hostname=hostname, **extra)


ROUTER = seen("192.168.1.1", "00:11:22:33:44:01", "router.home", open_ports=(53, 80))
LAPTOP = seen("192.168.1.10", "00:11:22:33:44:02", "laptop-office.home")
PRINTER = seen("192.168.1.9", "00:11:22:33:44:03", "hp-printer.home", open_ports=(9100,))


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "inventory.db"


@pytest.fixture
def make_window(app: QApplication, db: Path, tmp_path: Path) -> Iterator[Callable[..., MainWindow]]:
    opened: list[MainWindow] = []

    def factory(**options: Any) -> MainWindow:
        window = MainWindow(
            options.pop("settings", Settings()),
            store_path=db,
            prefs=options.pop("prefs", Preferences(tmp_path / "gui.ini")),
            autostart=False,
            use_tray=False,
            **options,
        )
        window.show()
        app.processEvents()
        opened.append(window)
        return window

    yield factory
    for window in opened:
        window.close()


def fill(db: Path, *observations: Observation, age: timedelta = timedelta(days=30)) -> None:
    with Store(db) as store:
        store.record_scan(observations, now=utcnow() - age)


def shown_names(window: MainWindow) -> list[str]:
    proxy = window._proxy
    return [str(proxy.index(row, m.NAME).data()) for row in range(proxy.rowCount())]


class TestTheList:
    def test_an_empty_inventory_invites_the_first_scan(
        self, make_window: Callable[..., MainWindow]
    ) -> None:
        window = make_window()
        assert window._list_stack.currentIndex() == _PAGE_EMPTY

    def test_devices_are_listed_in_address_order(
        self, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, LAPTOP, PRINTER, ROUTER)
        window = make_window()
        assert window._list_stack.currentIndex() == _PAGE_TABLE
        # 9 comes before 10: numeric order, not alphabetical.
        assert shown_names(window) == ["router.home", "hp-printer.home", "laptop-office.home"]

    def test_clicking_a_column_sorts_by_it(
        self, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        from PySide6.QtCore import Qt

        fill(db, LAPTOP, PRINTER, ROUTER)
        window = make_window()
        window._table.sortByColumn(m.NAME, Qt.SortOrder.AscendingOrder)
        assert shown_names(window) == ["hp-printer.home", "laptop-office.home", "router.home"]

    def test_the_guessed_kind_is_shown(
        self, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, PRINTER)
        window = make_window()
        assert window._proxy.index(0, m.KIND).data() == "printer"

    def test_a_missing_value_is_a_dash_not_a_blank(
        self, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, LAPTOP)
        window = make_window()
        assert window._proxy.index(0, m.VENDOR).data() == "—"

    def test_a_device_that_just_appeared_wears_the_new_tag(
        self, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, LAPTOP, age=timedelta(days=40))
        fill(db, PRINTER, age=timedelta(hours=2))
        window = make_window()
        tags = {
            str(window._proxy.index(r, m.NAME).data()): window._proxy.index(r, m.NAME).data(
                m.BADGE_ROLE
            )
            for r in range(window._proxy.rowCount())
        }
        assert tags == {"laptop-office.home": "", "hp-printer.home": "NEW"}

    def test_ports_and_first_seen_start_hidden(
        self, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, LAPTOP)
        window = make_window()
        assert window._table.isColumnHidden(m.PORTS)
        assert window._table.isColumnHidden(m.FIRST_SEEN)
        assert not window._table.isColumnHidden(m.NAME)

    def test_a_hidden_column_stays_hidden_next_time(
        self, db: Path, tmp_path: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, LAPTOP)
        prefs = Preferences(tmp_path / "gui.ini")
        first = make_window(prefs=prefs)
        first._show_column(m.PORTS, True)
        first._show_column(m.VENDOR, False)
        first.close()

        second = make_window(prefs=Preferences(tmp_path / "gui.ini"))
        assert not second._table.isColumnHidden(m.PORTS)
        assert second._table.isColumnHidden(m.VENDOR)


class TestFindingDevices:
    @pytest.fixture
    def window(self, db: Path, make_window: Callable[..., MainWindow]) -> MainWindow:
        fill(db, ROUTER, LAPTOP, PRINTER)
        with Store(db) as store:
            laptop = store.find("laptop-office")
            assert laptop
            store.set_approved(laptop.id, True)
            # Two scans without it: it goes offline.
            store.record_scan([ROUTER, PRINTER], offline_after=1)
        return make_window()

    def test_the_buttons_carry_the_counts(self, window: MainWindow) -> None:
        assert window._chips[Filter.ALL].text().endswith("3")
        assert window._chips[Filter.OFFLINE].text().endswith("1")
        assert window._chips[Filter.UNAPPROVED].text().endswith("2")

    def test_a_filter_narrows_the_list(self, window: MainWindow) -> None:
        window.set_filter(Filter.OFFLINE)
        assert shown_names(window) == ["laptop-office.home"]

    def test_search_narrows_the_list(self, window: MainWindow) -> None:
        window._search.setText("printer")
        assert shown_names(window) == ["hp-printer.home"]

    def test_search_and_filter_work_together(self, window: MainWindow) -> None:
        window.set_filter(Filter.OFFLINE)
        window._search.setText("printer")
        assert shown_names(window) == []

    def test_nothing_matching_says_so_and_offers_a_way_back(self, window: MainWindow) -> None:
        window._search.setText("no such device")
        assert window._list_stack.currentIndex() == _PAGE_NO_MATCH
        window.clear_filters()
        assert window._list_stack.currentIndex() == _PAGE_TABLE
        assert len(shown_names(window)) == 3
        assert window._search.text() == ""


class TestOneDevice:
    @pytest.fixture
    def window(self, db: Path, make_window: Callable[..., MainWindow]) -> MainWindow:
        fill(db, ROUTER, PRINTER)
        return make_window()

    def select(self, window: MainWindow, name: str) -> None:
        for row in range(window._proxy.rowCount()):
            if window._proxy.index(row, m.NAME).data() == name:
                window._table.selectRow(row)
                return
        raise AssertionError(name)

    def test_nothing_is_selected_at_first(self, window: MainWindow) -> None:
        assert window._detail.device_id is None

    def test_selecting_a_row_shows_that_device(self, window: MainWindow) -> None:
        self.select(window, "hp-printer.home")
        assert window._detail.device_id == window.selected_device().id  # type: ignore[union-attr]
        assert window._detail._fields["Address"].text() == "192.168.1.9"
        assert window._detail._subtitle.text() == "printer"

    def test_naming_a_device_is_remembered(self, window: MainWindow, db: Path) -> None:
        self.select(window, "hp-printer.home")
        window._detail._name.setText("Study printer")
        window._detail.flush()
        with Store(db) as store:
            device = store.find("192.168.1.9")
            assert device
            assert device.label == "Study printer"
        assert "Study printer" in shown_names(window)

    def test_clearing_a_name_goes_back_to_the_automatic_one(
        self, window: MainWindow, db: Path
    ) -> None:
        self.select(window, "hp-printer.home")
        window._detail._name.setText("Study printer")
        window._detail.flush()
        window._detail._name.setText("")
        window._detail.flush()
        assert "hp-printer.home" in shown_names(window)

    def test_notes_are_remembered(self, window: MainWindow, db: Path) -> None:
        self.select(window, "router.home")
        window._detail._notes.setPlainText("Behind the TV")
        window._detail.flush()
        with Store(db) as store:
            device = store.find("192.168.1.1")
            assert device
            assert device.notes == "Behind the TV"

    def test_an_edit_in_progress_is_kept_when_another_device_is_picked(
        self, window: MainWindow, db: Path
    ) -> None:
        self.select(window, "router.home")
        window._detail._notes.setPlainText("Behind the TV")
        self.select(window, "hp-printer.home")
        with Store(db) as store:
            device = store.find("192.168.1.1")
            assert device
            assert device.notes == "Behind the TV"
        assert window._detail._notes.toPlainText() == ""

    def test_editing_both_fields_saves_both(self, window: MainWindow, db: Path) -> None:
        self.select(window, "router.home")
        window._detail._name.setText("Main router")
        window._detail._notes.setPlainText("Behind the TV")
        self.select(window, "hp-printer.home")
        with Store(db) as store:
            device = store.find("192.168.1.1")
            assert device
            assert (device.label, device.notes) == ("Main router", "Behind the TV")

    def test_approving_a_device(self, window: MainWindow, db: Path) -> None:
        self.select(window, "router.home")
        window._detail._approve.click()
        with Store(db) as store:
            device = store.find("192.168.1.1")
            assert device
            assert device.approved
        assert window._detail._approve.text() == "Withdraw approval"
        window._detail._approve.click()
        assert window._detail._approve.text() == "Approve"

    def test_the_selection_survives_a_refresh(self, window: MainWindow) -> None:
        self.select(window, "hp-printer.home")
        window.reload()
        selected = window.selected_device()
        assert selected
        assert selected.hostname == "hp-printer.home"

    def test_forgetting_asks_first(
        self, window: MainWindow, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.select(window, "hp-printer.home")
        monkeypatch.setattr(MainWindow, "_confirm", lambda *_args: False)
        window._detail._forget.click()
        assert len(shown_names(window)) == 2

    def test_a_forgotten_device_is_gone(
        self, window: MainWindow, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.select(window, "hp-printer.home")
        monkeypatch.setattr(MainWindow, "_confirm", lambda *_args: True)
        window._detail._forget.click()
        assert shown_names(window) == ["router.home"]
        assert window._detail.device_id is None


def fake_scan(
    observations: list[Observation],
) -> Callable[..., ScanReport]:
    def run(settings: Settings, *, progress: Any = None, **_ignored: Any) -> ScanReport:
        if progress:
            progress("ping sweep", 1, 2)
            progress("ping sweep", 2, 2)
        return ScanReport(
            observations=list(observations),
            networks=[ipaddress.IPv4Network("192.168.1.0/24")],
            addresses_probed=254,
            duration=0.1,
        )

    return run


class FakeTray:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def showMessage(self, title: str, body: str, *_rest: object) -> None:  # noqa: N802
        self.messages.append((title, body))

    def hide(self) -> None:
        pass


class TestScanning:
    def test_a_scan_fills_the_list(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("discovery_now.gui.worker.run_scan", fake_scan([ROUTER, LAPTOP]))
        window = make_window()
        window.scan(manual=True)
        wait_until(app, lambda: window._list_stack.currentIndex() == _PAGE_TABLE)
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert len(shown_names(window)) == 2
        assert "2 devices answered" in window._status.text()

    def test_the_button_is_busy_while_a_scan_runs(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("discovery_now.gui.worker.run_scan", fake_scan([ROUTER]))
        window = make_window()
        window.scan(manual=True)
        assert not window._scan_button.isEnabled()
        assert window._scan_button.text() == "Scanning…"
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert window._scan_button.text() == "Scan now"

    def test_a_second_scan_is_not_started_on_top_of_the_first(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        started: list[int] = []

        def slow(settings: Settings, *, progress: Any = None) -> ScanReport:
            started.append(1)
            time.sleep(0.3)
            return fake_scan([ROUTER])(settings)

        monkeypatch.setattr("discovery_now.gui.worker.run_scan", slow)
        window = make_window()
        window.scan(manual=True)
        window.scan(manual=False)
        window.scan(manual=True)
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert started == [1]

    def test_the_progress_is_shown(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen_text: list[str] = []

        def run(settings: Settings, *, progress: Any = None) -> ScanReport:
            progress("ping sweep", 5, 10)
            time.sleep(0.2)
            return fake_scan([ROUTER])(settings)

        monkeypatch.setattr("discovery_now.gui.worker.run_scan", run)
        window = make_window()
        window._runner.progress.connect(lambda *_a: seen_text.append(window._status.text()))
        window.scan(manual=True)
        wait_until(app, lambda: bool(seen_text))
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert any("Looking for devices" in text and "5 of 10" in text for text in seen_text)

    def test_a_scan_that_cannot_run_says_why(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def refuse(settings: Settings, *, progress: Any = None) -> ScanReport:
            raise TargetError("192.0.2.0/24 is not a private network")

        monkeypatch.setattr("discovery_now.gui.worker.run_scan", refuse)
        window = make_window()
        window.scan(manual=True)
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert not window._banner.isHidden()
        assert "not a private network" in window._banner_text.text()

    def test_an_unexpected_failure_is_shown_not_swallowed(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def explode(settings: Settings, *, progress: Any = None) -> ScanReport:
            raise RuntimeError("the network went away")

        monkeypatch.setattr("discovery_now.gui.worker.run_scan", explode)
        window = make_window()
        window.scan(manual=True)
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert "the network went away" in window._banner_text.text()

    def test_the_next_scan_clears_the_warning(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        window = make_window()
        window._banner_text.setText("old problem")
        window._banner.show()
        monkeypatch.setattr("discovery_now.gui.worker.run_scan", fake_scan([ROUTER]))
        window.scan(manual=True)
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert window._banner.isHidden()

    def test_an_offline_device_comes_back_in_the_list(
        self,
        app: QApplication,
        db: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER, LAPTOP)
        with Store(db) as store:
            store.record_scan([ROUTER], offline_after=1)
        window = make_window()
        assert window._chips[Filter.OFFLINE].text().endswith("1")
        monkeypatch.setattr("discovery_now.gui.worker.run_scan", fake_scan([ROUTER, LAPTOP]))
        window.scan(manual=True)
        wait_until(app, lambda: window._scan_button.isEnabled())
        assert window._chips[Filter.OFFLINE].text().endswith("0")


class TestNotifications:
    def run_scan_with(
        self,
        app: QApplication,
        window: MainWindow,
        monkeypatch: pytest.MonkeyPatch,
        observations: list[Observation],
    ) -> None:
        monkeypatch.setattr("discovery_now.gui.worker.run_scan", fake_scan(observations))
        window.scan(manual=True)
        wait_until(app, lambda: window._scan_button.isEnabled())

    def test_a_new_device_on_a_known_network_is_announced(
        self,
        app: QApplication,
        db: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER)
        window = make_window()
        tray = FakeTray()
        window._tray = tray  # type: ignore[assignment]
        self.run_scan_with(app, window, monkeypatch, [ROUTER, PRINTER])
        assert tray.messages == [("New device on your network", "hp-printer.home (192.168.1.9)")]

    def test_the_very_first_scan_does_not_announce_everything(
        self,
        app: QApplication,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        window = make_window()
        tray = FakeTray()
        window._tray = tray  # type: ignore[assignment]
        self.run_scan_with(app, window, monkeypatch, [ROUTER, PRINTER, LAPTOP])
        assert tray.messages == []

    def test_several_new_devices_are_announced_together(
        self,
        app: QApplication,
        db: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER)
        window = make_window()
        tray = FakeTray()
        window._tray = tray  # type: ignore[assignment]
        self.run_scan_with(app, window, monkeypatch, [ROUTER, PRINTER, LAPTOP])
        assert len(tray.messages) == 1
        assert "2 new devices" in tray.messages[0][1]

    def test_notifications_can_be_turned_off(
        self,
        app: QApplication,
        db: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER)
        window = make_window()
        tray = FakeTray()
        window._tray = tray  # type: ignore[assignment]
        window._notify_action.setChecked(False)
        self.run_scan_with(app, window, monkeypatch, [ROUTER, PRINTER])
        assert tray.messages == []


class TestAutoScan:
    def test_on_by_default_every_five_minutes(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        assert window._auto.isActive()
        assert window._auto.interval() == 5 * 60_000

    def test_it_can_be_turned_off(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        window._auto_check.setChecked(False)
        assert not window._auto.isActive()
        assert not window._interval.isEnabled()

    def test_the_interval_can_be_changed(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        window._interval.setCurrentIndex(window._interval.findData(15))
        assert window._auto.interval() == 15 * 60_000

    def test_the_choice_is_remembered(
        self, tmp_path: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        window = make_window(prefs=Preferences(tmp_path / "gui.ini"))
        window._auto_check.setChecked(False)
        window._interval.setCurrentIndex(window._interval.findData(30))
        window.close()
        again = make_window(prefs=Preferences(tmp_path / "gui.ini"))
        assert not again._auto_check.isChecked()
        assert again._interval.currentData() == 30

    def test_the_config_file_sets_the_first_interval(
        self, tmp_path: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        window = make_window(
            settings=Settings(watch_interval=900),
            prefs=Preferences(tmp_path / "fresh.ini", default_interval=15),
        )
        assert window._interval.currentData() == 15


class TestExport:
    def choose(self, monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(path), ""))

    def test_exports_every_device_as_csv(
        self,
        db: Path,
        tmp_path: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER, PRINTER)
        window = make_window()
        target = tmp_path / "out" / "devices.csv"
        self.choose(monkeypatch, target)
        window.export(exporting.ExportFormat.CSV)
        lines = target.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0].startswith("id,name,ip,mac")
        assert len(lines) == 3
        assert "Exported 2 devices" in window._status.text()

    def test_exports_json(
        self,
        db: Path,
        tmp_path: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        fill(db, ROUTER)
        window = make_window()
        target = tmp_path / "devices.json"
        self.choose(monkeypatch, target)
        window.export(exporting.ExportFormat.JSON)
        assert json.loads(target.read_text(encoding="utf-8"))[0]["ip"] == "192.168.1.1"

    def test_private_details_can_be_hidden(
        self,
        db: Path,
        tmp_path: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER)
        window = make_window()
        window._redact_action.setChecked(True)
        target = tmp_path / "devices.csv"
        self.choose(monkeypatch, target)
        window.export(exporting.ExportFormat.CSV)
        text = target.read_text(encoding="utf-8-sig")
        assert "router.home" not in text
        assert "00:11:22:xx:xx:xx" in text

    def test_cancelling_the_dialog_writes_nothing(
        self,
        db: Path,
        tmp_path: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER)
        window = make_window()
        self.choose(monkeypatch, Path())
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: ("", ""))
        window.export(exporting.ExportFormat.CSV)
        assert not list(tmp_path.glob("*.csv"))

    def test_an_unwritable_place_is_reported(
        self,
        db: Path,
        tmp_path: Path,
        make_window: Callable[..., MainWindow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fill(db, ROUTER)
        window = make_window()
        blocker = tmp_path / "a-file"
        blocker.write_text("x")
        # A folder cannot be created under a regular file.
        self.choose(monkeypatch, blocker / "devices.csv")
        window.export(exporting.ExportFormat.CSV)
        assert not window._banner.isHidden()


class TestTheActivityLog:
    def test_lists_what_happened(self, db: Path, make_window: Callable[..., MainWindow]) -> None:
        fill(db, ROUTER, PRINTER)
        window = make_window()
        assert window._events.rowCount() == 2
        assert window._events.index(0, 2).data() == "New device"

    def test_says_so_when_nothing_happened(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        assert not window._activity_empty.isHidden()
        assert window._activity.isHidden()

    def test_the_tabs_switch_pages(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        window.show_tab(1)
        assert window._pages.currentIndex() == 1
        assert window._tab_buttons[1].isChecked()


class TestAppearance:
    def test_both_appearances_define_every_colour(self) -> None:
        assert theme.LIGHT.__slots__ == theme.DARK.__slots__

    def test_the_window_redraws_after_a_switch(
        self, app: QApplication, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, ROUTER)
        window = make_window()
        window.on_theme_changed()  # must not raise

    def test_the_icon_has_every_size(self, app: QApplication) -> None:
        from discovery_now.gui.icons import app_icon

        sizes = {size.width() for size in app_icon().availableSizes()}
        assert {16, 32, 256} <= sizes

    def test_the_icon_can_be_saved_for_windows(self, app: QApplication, tmp_path: Path) -> None:
        from discovery_now.gui.icons import save_ico

        target = tmp_path / "nested" / "icon.ico"
        save_ico(target)
        assert target.stat().st_size > 0


class TestPreferences:
    def test_defaults(self, tmp_path: Path) -> None:
        prefs = Preferences(tmp_path / "p.ini", default_interval=5)
        assert prefs.auto_scan is True
        assert prefs.interval_minutes == 5
        assert prefs.notifications is True
        assert prefs.redact_exports is False
        assert prefs.hidden_columns(default=(6, 7)) == {6, 7}

    def test_values_survive_a_restart(self, tmp_path: Path) -> None:
        prefs = Preferences(tmp_path / "p.ini")
        prefs.auto_scan = False
        prefs.interval_minutes = 15
        prefs.redact_exports = True
        prefs.save_hidden_columns({3, 4})
        prefs.sync()
        again = Preferences(tmp_path / "p.ini")
        assert again.auto_scan is False
        assert again.interval_minutes == 15
        assert again.redact_exports is True
        assert again.hidden_columns() == {3, 4}

    def test_an_interval_nobody_offered_falls_back(self, tmp_path: Path) -> None:
        prefs = Preferences(tmp_path / "p.ini", default_interval=5)
        prefs.interval_minutes = 7
        assert prefs.interval_minutes == 5

    def test_a_config_value_snaps_to_the_nearest_choice(self) -> None:
        from discovery_now.gui.prefs import snap_interval

        assert snap_interval(300 // 60) == 5
        assert snap_interval(10) in (5, 15)
        assert snap_interval(1000) == 60
