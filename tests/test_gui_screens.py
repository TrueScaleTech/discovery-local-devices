"""The screens the rail leads to: several devices at once, the map, the settings."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from discovery_now.config import Settings, config_path
from discovery_now.gui import models as m
from discovery_now.gui import theme
from discovery_now.gui.prefs import Preferences
from discovery_now.gui.window import MainWindow, Screen
from discovery_now.models import Observation, utcnow
from discovery_now.store import Store

ROUTER = Observation(
    ip="192.168.1.1", mac="00:11:22:33:44:01", hostname="router.home", open_ports=(53, 80)
)
LAPTOP = Observation(ip="192.168.1.10", mac="00:11:22:33:44:02", hostname="laptop-office.home")
PRINTER = Observation(
    ip="192.168.1.9", mac="00:11:22:33:44:03", hostname="hp-printer.home", open_ports=(9100,)
)


@pytest.fixture(scope="session")
def app() -> QApplication:
    instance = QApplication.instance() or QApplication([])
    assert isinstance(instance, QApplication)
    theme.apply(instance)
    return instance


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
            find_addresses=False,
            **options,
        )
        window.show()
        app.processEvents()
        opened.append(window)
        return window

    yield factory
    for window in opened:
        window.close()
        window.deleteLater()
    # processEvents() alone does not run deferred deletions, so without this the
    # windows pile up: Qt restyles and lays out every widget it still owns, and
    # each later test pays for all the ones before it.
    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    opened.clear()
    # Leave the appearance as the rest of the suite expects to find it.
    theme.apply(app)


def fill(db: Path, *observations: Observation, age: timedelta = timedelta(days=30)) -> None:
    with Store(db) as store:
        store.record_scan(observations, now=utcnow() - age)


def shown_names(window: MainWindow) -> list[str]:
    proxy = window._proxy
    return [str(proxy.index(row, m.NAME).data()) for row in range(proxy.rowCount())]


def select_rows(window: MainWindow, *names: str) -> None:
    """Select several rows at once, the way ctrl-clicking them would."""
    model = window._table.selectionModel()
    flags = model.SelectionFlag.Select | model.SelectionFlag.Rows
    window._table.clearSelection()
    for row in range(window._proxy.rowCount()):
        if str(window._proxy.index(row, m.NAME).data()) in names:
            model.select(window._proxy.index(row, 0), flags)


class TestSeveralAtOnce:
    @pytest.fixture
    def window(self, db: Path, make_window: Callable[..., MainWindow]) -> MainWindow:
        fill(db, ROUTER, LAPTOP, PRINTER)
        return make_window()

    def test_the_bar_stays_away_until_more_than_one_is_picked(self, window: MainWindow) -> None:
        assert window._bulk.isHidden()
        select_rows(window, "router.home")
        assert window._bulk.isHidden()
        select_rows(window, "router.home", "laptop-office.home")
        assert not window._bulk.isHidden()

    def test_the_bar_says_how_many_and_how_many_are_unvetted(
        self, window: MainWindow, db: Path
    ) -> None:
        with Store(db) as store:
            found = store.find("router.home")
            assert found
            store.set_approved(found.id, True)
        window.reload()
        select_rows(window, "router.home", "laptop-office.home", "hp-printer.home")
        assert window._bulk_label.text() == "3 devices selected · 2 not approved"

    def test_one_click_approves_every_selected_device(self, window: MainWindow, db: Path) -> None:
        select_rows(window, "laptop-office.home", "hp-printer.home")
        window._bulk_approve.click()
        with Store(db) as store:
            approved = {d.hostname for d in store.devices() if d.approved}
        assert approved == {"laptop-office.home", "hp-printer.home"}
        assert "Approved 2 devices" in window._status.text()

    def test_approval_can_be_withdrawn_from_several(self, window: MainWindow, db: Path) -> None:
        select_rows(window, "laptop-office.home", "hp-printer.home")
        window._bulk_approve.click()
        select_rows(window, "laptop-office.home", "hp-printer.home")
        window._bulk_withdraw.click()
        with Store(db) as store:
            assert not any(device.approved for device in store.devices())

    def test_approving_only_touches_what_needs_it(self, window: MainWindow, db: Path) -> None:
        with Store(db) as store:
            found = store.find("router.home")
            assert found
            store.set_approved(found.id, True)
        window.reload()
        select_rows(window, "router.home", "laptop-office.home", "hp-printer.home")
        window._bulk_approve.click()
        assert "Approved 2 devices" in window._status.text()

    def test_the_buttons_know_when_there_is_nothing_to_do(self, window: MainWindow) -> None:
        select_rows(window, "laptop-office.home", "hp-printer.home")
        assert window._bulk_approve.isEnabled()
        assert not window._bulk_withdraw.isEnabled()
        window._bulk_approve.click()
        select_rows(window, "laptop-office.home", "hp-printer.home")
        assert not window._bulk_approve.isEnabled()
        assert window._bulk_withdraw.isEnabled()

    def test_forgetting_several_asks_first(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        select_rows(window, "laptop-office.home", "hp-printer.home")
        monkeypatch.setattr(MainWindow, "_confirm", lambda *_args: False)
        window._bulk_forget.click()
        assert len(shown_names(window)) == 3

    def test_forgetting_several_removes_them_all(
        self, window: MainWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        select_rows(window, "laptop-office.home", "hp-printer.home")
        monkeypatch.setattr(MainWindow, "_confirm", lambda *_args: True)
        window._bulk_forget.click()
        assert shown_names(window) == ["router.home"]

    def test_the_details_panel_steps_aside_for_a_group(self, window: MainWindow) -> None:
        select_rows(window, "router.home")
        assert window._detail.device_id is not None
        select_rows(window, "router.home", "laptop-office.home")
        assert window.selected_device() is None
        assert window._detail.device_id is None


class TestTheMap:
    @pytest.fixture
    def window(self, db: Path, make_window: Callable[..., MainWindow]) -> MainWindow:
        fill(db, ROUTER, LAPTOP, PRINTER)
        window = make_window()
        window._gateways = ["192.168.1.1"]
        window.reload()
        return window

    def test_every_device_is_on_the_map(self, window: MainWindow) -> None:
        assert window.topology_page.canvas.node_count == 3

    def test_an_empty_network_says_so(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        assert not window.topology_page.empty.isHidden()
        assert window.topology_page.canvas.isHidden()

    def test_choosing_a_device_shows_its_card(self, window: MainWindow, db: Path) -> None:
        with Store(db) as store:
            found = store.find("hp-printer.home")
        assert found
        window.show_screen(Screen.TOPOLOGY)
        window.topology_page.select_device(found.id)
        assert not window.topology_page.card.isHidden()
        assert "hp-printer" in window.topology_page.card._name.text()

    def test_the_card_goes_away_with_the_selection(self, window: MainWindow) -> None:
        window.topology_page.select_device(None)
        assert window.topology_page.card.isHidden()

    def test_choosing_in_the_list_chooses_on_the_map(self, window: MainWindow) -> None:
        select_rows(window, "hp-printer.home")
        node = window.topology_page.canvas.selected_node()
        assert node is not None
        assert node.ip == "192.168.1.9"

    def test_a_device_on_the_map_can_be_opened_in_the_list(
        self, window: MainWindow, db: Path
    ) -> None:
        with Store(db) as store:
            found = store.find("hp-printer.home")
        assert found
        window.show_screen(Screen.TOPOLOGY)
        window.topology_page.open_device.emit(found.id)
        assert window.screen_shown is Screen.DEVICES
        selected = window.selected_device()
        assert selected is not None
        assert selected.hostname == "hp-printer.home"

    def test_approving_from_the_map_reaches_the_inventory(
        self, window: MainWindow, db: Path
    ) -> None:
        with Store(db) as store:
            found = store.find("hp-printer.home")
        assert found
        window.topology_page.approve.emit(found.id, True)
        with Store(db) as store:
            again = store.get(found.id)
        assert again and again.approved

    def test_zooming_stays_within_reach(self, window: MainWindow) -> None:
        canvas = window.topology_page.canvas
        for _ in range(40):
            canvas.zoom_by(2.0)
        assert canvas._scale <= 2.4
        for _ in range(60):
            canvas.zoom_by(0.5)
        assert canvas._scale >= 0.12


class TestTheSettingsScreen:
    @pytest.fixture
    def window(self, tmp_path: Path, make_window: Callable[..., MainWindow]) -> MainWindow:
        return make_window(prefs=Preferences(tmp_path / "gui.ini"))

    def test_choosing_an_accent_is_remembered_and_applied(
        self, window: MainWindow, tmp_path: Path
    ) -> None:
        window.settings_page._set_accent(theme.accent_for("violet"))
        assert theme.current().accent_key == "violet"
        assert Preferences(tmp_path / "gui.ini").accent == "violet"

    def test_pinning_an_appearance_is_remembered(self, window: MainWindow, tmp_path: Path) -> None:
        window.settings_page._set_mode(theme.Mode.DARK)
        assert theme.current().dark is True
        assert Preferences(tmp_path / "gui.ini").mode is theme.Mode.DARK
        window.settings_page._set_mode(theme.Mode.LIGHT)
        assert theme.current().dark is False

    def test_the_schedule_is_saved_and_armed(self, window: MainWindow) -> None:
        page = window.settings_page
        page._auto.setChecked(True)
        page._interval.setCurrentIndex(page._interval.findData(15))
        assert window._auto.isActive()
        assert window._auto.interval() == 15 * 60_000
        page._auto.setChecked(False)
        assert not window._auto.isActive()
        assert not page._interval.isEnabled()

    def test_a_scan_setting_reaches_the_shared_config_file(self, window: MainWindow) -> None:
        # The command line reads the same file, so it has to be written to disk.
        window.settings_page._new_days.setValue(3)
        assert Settings.load(config_path()).new_device_days == 3
        assert window._new_within == timedelta(days=3)

    def test_networks_are_checked_before_they_are_saved(self, window: MainWindow) -> None:
        page = window.settings_page
        page._subnets.setText("192.168.1.0/24, not-a-network")
        page._on_subnets()
        assert not page._subnets_error.isHidden()
        assert Settings.load(config_path()).subnets == []

    def test_good_networks_are_saved(self, window: MainWindow) -> None:
        page = window.settings_page
        page._subnets.setText("192.168.1.0/24, 10.0.0.0/24")
        page._on_subnets()
        assert page._subnets_error.isHidden()
        assert Settings.load(config_path()).subnets == ["192.168.1.0/24", "10.0.0.0/24"]

    def test_the_switches_are_remembered(self, window: MainWindow, tmp_path: Path) -> None:
        window.settings_page._redact.setChecked(True)
        window.settings_page._notify.setChecked(False)
        again = Preferences(tmp_path / "gui.ini")
        assert again.redact_exports is True
        assert again.notifications is False


class TestTheRail:
    def test_every_screen_can_be_reached(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        for screen in Screen:
            window.show_screen(screen)
            assert window.screen_shown is screen
            assert window._nav[screen].isChecked()
            assert sum(1 for b in window._nav.values() if b.isChecked()) == 1

    def test_the_rail_says_what_the_schedule_is(
        self, tmp_path: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        prefs = Preferences(tmp_path / "gui.ini")
        prefs.auto_scan = True
        prefs.interval_minutes = 15
        window = make_window(prefs=prefs)
        assert window._schedule_note.text() == "Scanning every 15 minutes"
        window.settings_page._auto.setChecked(False)
        assert window._schedule_note.text() == "Automatic scanning is off"
