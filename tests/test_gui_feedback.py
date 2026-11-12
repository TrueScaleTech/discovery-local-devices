"""Things found by using the app, pinned so they stay fixed.

Most of these drive the real controls (a click on a button, a drag with the mouse)
rather than calling the handler behind them. The handler was fine in every case;
what was broken was the wiring between the control and it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from discovery_now.config import Settings
from discovery_now.gui import icons, theme
from discovery_now.gui import models as m
from discovery_now.gui.prefs import Preferences
from discovery_now.gui.viewmodel import Filter, counts, passes
from discovery_now.gui.window import MainWindow, Screen
from discovery_now.models import Device, Observation, utcnow
from discovery_now.store import Store

ROUTER = Observation(
    ip="192.168.1.1", mac="00:11:22:33:44:01", hostname="router.home", open_ports=(53, 80)
)
LAPTOP = Observation(ip="192.168.1.10", mac="00:11:22:33:44:02", hostname="laptop-office.home")
PRINTER = Observation(
    ip="192.168.1.9", mac="00:11:22:33:44:03", hostname="hp-printer.home", open_ports=(9100,)
)
WEEK = timedelta(days=7)


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
    app.processEvents()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    opened.clear()
    theme.apply(app)


def fill(db: Path, *observations: Observation, age: timedelta = timedelta(days=1)) -> None:
    with Store(db) as store:
        store.record_scan(observations, now=utcnow() - age)


def device(*, approved: bool, age: timedelta) -> Device:
    moment = utcnow()
    return Device(
        id=1,
        key="ip:192.168.1.5",
        ip="192.168.1.5",
        mac=None,
        hostname=None,
        vendor=None,
        label=None,
        notes=None,
        first_seen=moment - age,
        last_seen=moment,
        online=True,
        approved=approved,
        misses=0,
    )


# -- 1. the NEW tag -----------------------------------------------------------


class TestNewEndsOnApproval:
    def test_an_approved_device_is_not_new_even_inside_the_window(self) -> None:
        assert device(approved=False, age=timedelta(hours=2)).is_new(WEEK)
        assert not device(approved=True, age=timedelta(hours=2)).is_new(WEEK)

    def test_it_stays_not_new_after_the_window_too(self) -> None:
        assert not device(approved=False, age=timedelta(days=30)).is_new(WEEK)

    def test_the_new_filter_and_its_count_leave_approved_devices_out(self) -> None:
        fresh = device(approved=False, age=timedelta(hours=1))
        vetted = device(approved=True, age=timedelta(hours=1))
        assert passes(fresh, Filter.NEW, new_within=WEEK)
        assert not passes(vetted, Filter.NEW, new_within=WEEK)
        assert counts([fresh, vetted], new_within=WEEK)[Filter.NEW] == 1

    def test_approving_in_the_window_takes_the_tag_off_the_row(
        self, db: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, ROUTER, PRINTER)
        window = make_window()

        def tags() -> dict[str, object]:
            proxy = window._proxy
            return {
                str(proxy.index(r, m.NAME).data()): proxy.index(r, m.NAME).data(m.BADGE_ROLE)
                for r in range(proxy.rowCount())
            }

        assert tags() == {"router.home": "NEW", "hp-printer.home": "NEW"}
        with Store(db) as store:
            found = store.find("router.home")
            assert found
        window._on_approval(found.id, True)
        assert tags() == {"router.home": "", "hp-printer.home": "NEW"}
        assert window._chips[Filter.NEW].text().endswith("1")


# -- 2. the chips on the settings screen --------------------------------------


class TestTheChipsReallyWork:
    @pytest.fixture
    def window(self, tmp_path: Path, make_window: Callable[..., MainWindow]) -> MainWindow:
        window = make_window(prefs=Preferences(tmp_path / "gui.ini"))
        window.show_screen(Screen.SETTINGS)
        return window

    def test_there_is_no_density_choice_and_the_rows_keep_one_height(
        self, window: MainWindow
    ) -> None:
        assert not hasattr(window.settings_page, "_density")
        assert not hasattr(theme, "Density")
        window.settings_page._mode.button("dark").click()
        assert window._table.verticalHeader().defaultSectionSize() == 44

    @pytest.mark.parametrize("key", ["light", "dark", "black"])
    def test_clicking_an_appearance_applies_and_remembers_it(
        self, window: MainWindow, tmp_path: Path, key: str
    ) -> None:
        window.settings_page._mode.button(key).click()
        assert Preferences(tmp_path / "gui.ini").mode is theme.Mode(key)
        assert theme.current().dark is (key != "light")
        assert theme.current().black is (key == "black")

    def test_a_chip_is_never_left_unchecked_by_clicking_it_twice(self, window: MainWindow) -> None:
        chip = window.settings_page._mode.button("dark")
        chip.click()
        chip.click()
        assert window.settings_page._mode.chosen() == "dark"

    def test_clicking_an_accent_swatch_applies_it(self, window: MainWindow) -> None:
        swatch = window.settings_page._swatches[2]
        swatch.click()
        assert theme.current().accent_key == swatch.accent.key


# -- 3. the black theme -------------------------------------------------------


class TestPureBlack:
    def test_the_page_is_true_black(self) -> None:
        tokens = theme.tokens_for(dark=True, black=True)
        assert tokens.window == "#000000"
        assert tokens.rail == "#000000"
        assert tokens.black and tokens.dark

    def test_ordinary_dark_is_not_black(self) -> None:
        tokens = theme.tokens_for(dark=True)
        assert tokens.window != "#000000"
        assert not tokens.black

    def test_black_means_nothing_on_a_light_appearance(self) -> None:
        tokens = theme.tokens_for(dark=False, black=True)
        assert not tokens.black
        assert tokens.window != "#000000"

    def test_cards_are_still_told_apart_from_the_page(self) -> None:
        tokens = theme.tokens_for(dark=True, black=True)
        assert tokens.surface != tokens.window
        assert tokens.border != tokens.window

    def test_everything_still_reads_on_black(self) -> None:
        tokens = theme.tokens_for(dark=True, black=True)
        for surface in (tokens.window, tokens.surface, tokens.raised, tokens.sunken):
            for colour in (tokens.text, tokens.muted):
                assert theme.contrast(colour, surface) >= 4.5, (colour, surface)
        assert theme.contrast(tokens.faint, tokens.surface) >= 4.5
        for colour in (tokens.online, tokens.offline, tokens.new, tokens.warn):
            assert theme.contrast(colour, tokens.surface) >= 4.5, colour

    def test_every_accent_reads_on_black(self) -> None:
        for accent in theme.ACCENTS:
            tokens = theme.tokens_for(dark=True, accent=accent, black=True)
            assert theme.contrast(tokens.on_accent, tokens.accent) >= 4.5, accent.key
            assert theme.contrast(tokens.accent, tokens.surface) >= 3.0, accent.key

    def test_black_is_one_of_the_choices(self) -> None:
        assert theme.Mode.BLACK in list(theme.Mode)
        assert theme.Mode.BLACK.label == "Black"

    def test_a_saved_black_choice_comes_back(self, tmp_path: Path) -> None:
        prefs = Preferences(tmp_path / "p.ini")
        prefs.mode = theme.Mode.BLACK
        prefs.sync()
        assert Preferences(tmp_path / "p.ini").mode is theme.Mode.BLACK

    def test_going_from_dark_to_black_really_restyles(
        self, tmp_path: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        prefs = Preferences(tmp_path / "gui.ini")
        prefs.mode = theme.Mode.DARK
        window = make_window(prefs=prefs)
        assert not theme.current().black
        window.settings_page._mode.button("black").click()
        assert theme.current().black


# -- 4. settings under the scan button ---------------------------------------


class TestTheRailOrder:
    def test_settings_sits_below_scan_now(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        scan = window._scan_button.mapTo(window, QPoint(0, 0)).y()
        settings = window._nav[Screen.SETTINGS].mapTo(window, QPoint(0, 0)).y()
        assert settings > scan

    def test_the_other_screens_stay_above_scan_now(
        self, make_window: Callable[..., MainWindow]
    ) -> None:
        window = make_window()
        scan = window._scan_button.mapTo(window, QPoint(0, 0)).y()
        for screen in (Screen.DEVICES, Screen.TOPOLOGY, Screen.ACTIVITY):
            assert window._nav[screen].mapTo(window, QPoint(0, 0)).y() < scan

    def test_it_still_leads_to_the_settings(self, make_window: Callable[..., MainWindow]) -> None:
        window = make_window()
        window._nav[Screen.SETTINGS].click()
        assert window.screen_shown is Screen.SETTINGS


# -- 5. dragging nodes on the map --------------------------------------------


class TestDraggingNodes:
    @pytest.fixture
    def window(self, db: Path, make_window: Callable[..., MainWindow]) -> MainWindow:
        fill(db, ROUTER, LAPTOP, PRINTER)
        window = make_window()
        window._gateways = ["192.168.1.1"]
        window.reload()
        window.show_screen(Screen.TOPOLOGY)
        window.topology_page.canvas.fit()
        return window

    def screen_of(self, window: MainWindow, ip: str) -> QPoint:
        canvas = window.topology_page.canvas
        node = next(n for n in canvas._map.nodes if n.ip == ip)
        at = canvas._screen(node)
        return QPoint(round(at.x()), round(at.y()))

    def drag(self, window: MainWindow, start: QPoint, end: QPoint) -> None:
        canvas = window.topology_page.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in range(1, 6):
            at = start + (end - start) * step / 5
            QTest.mouseMove(canvas, QPoint(round(at.x()), round(at.y())))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)

    def test_a_node_follows_the_mouse(self, window: MainWindow) -> None:
        start = self.screen_of(window, "192.168.1.9")
        self.drag(window, start, start + QPoint(70, 55))
        end = self.screen_of(window, "192.168.1.9")
        assert abs(end.x() - (start.x() + 70)) <= 2
        assert abs(end.y() - (start.y() + 55)) <= 2

    def test_only_that_node_moves(self, window: MainWindow) -> None:
        other = self.screen_of(window, "192.168.1.10")
        start = self.screen_of(window, "192.168.1.9")
        self.drag(window, start, start + QPoint(60, 40))
        assert self.screen_of(window, "192.168.1.10") == other

    def test_the_gateway_can_be_moved_as_well(self, window: MainWindow) -> None:
        start = self.screen_of(window, "192.168.1.1")
        self.drag(window, start, start + QPoint(40, 30))
        assert self.screen_of(window, "192.168.1.1") != start

    def test_the_view_does_not_pan_while_a_node_is_dragged(self, window: MainWindow) -> None:
        canvas = window.topology_page.canvas
        before = QPointF(canvas._pan)
        start = self.screen_of(window, "192.168.1.9")
        self.drag(window, start, start + QPoint(50, 50))
        assert canvas._pan == before

    def test_dragging_empty_space_still_pans(self, window: MainWindow) -> None:
        canvas = window.topology_page.canvas
        before = QPointF(canvas._pan)
        self.drag(window, QPoint(8, 8), QPoint(58, 38))
        assert canvas._pan != before
        assert canvas.placed == {}

    def test_a_drag_is_not_a_click(self, window: MainWindow) -> None:
        start = self.screen_of(window, "192.168.1.9")
        self.drag(window, start, start + QPoint(60, 0))
        assert window.topology_page.canvas.selected_node() is None

    def test_a_plain_click_still_selects(self, window: MainWindow) -> None:
        canvas = window.topology_page.canvas
        at = self.screen_of(window, "192.168.1.9")
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at)
        node = canvas.selected_node()
        assert node is not None
        assert node.ip == "192.168.1.9"

    def test_a_node_stays_put_when_the_map_is_refreshed(self, window: MainWindow) -> None:
        start = self.screen_of(window, "192.168.1.9")
        self.drag(window, start, start + QPoint(70, 55))
        moved = self.screen_of(window, "192.168.1.9")
        window.reload()  # what every scan does
        assert self.screen_of(window, "192.168.1.9") == moved

    def test_the_new_position_is_saved(self, window: MainWindow, tmp_path: Path) -> None:
        start = self.screen_of(window, "192.168.1.9")
        self.drag(window, start, start + QPoint(70, 55))
        saved = Preferences(tmp_path / "gui.ini").node_positions()
        assert len(saved) == 1

    def test_it_is_put_back_next_time(
        self, db: Path, tmp_path: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        fill(db, ROUTER, LAPTOP, PRINTER)
        first = make_window(prefs=Preferences(tmp_path / "gui.ini"))
        first.show_screen(Screen.TOPOLOGY)
        first.topology_page.canvas.fit()
        start = self.screen_of(first, "192.168.1.9")
        self.drag(first, start, start + QPoint(70, 55))
        placed = first.topology_page.canvas.placed
        first.close()

        second = make_window(prefs=Preferences(tmp_path / "gui.ini"))
        restored = second.topology_page.canvas.placed
        assert restored.keys() == placed.keys()
        for key, (x, y) in placed.items():
            assert restored[key] == pytest.approx((x, y), abs=0.2)

    def test_reset_layout_brings_the_automatic_placement_back(self, window: MainWindow) -> None:
        original = self.screen_of(window, "192.168.1.9")
        self.drag(window, original, original + QPoint(70, 55))
        window.topology_page.reset_button.click()
        assert window.topology_page.canvas.placed == {}
        assert self.screen_of(window, "192.168.1.9") == original

    def test_reset_is_remembered_too(self, window: MainWindow, tmp_path: Path) -> None:
        start = self.screen_of(window, "192.168.1.9")
        self.drag(window, start, start + QPoint(70, 55))
        window.topology_page.reset_button.click()
        assert Preferences(tmp_path / "gui.ini").node_positions() == {}

    def test_a_forgotten_device_does_not_break_a_saved_layout(
        self, db: Path, tmp_path: Path, make_window: Callable[..., MainWindow]
    ) -> None:
        prefs = Preferences(tmp_path / "gui.ini")
        prefs.save_node_positions({999: (10.0, 20.0)})
        fill(db, ROUTER)
        window = make_window(prefs=prefs)
        assert window.topology_page.canvas.node_count == 1


class TestSavedPositions:
    def test_garbage_in_the_file_is_ignored(self, tmp_path: Path) -> None:
        prefs = Preferences(tmp_path / "p.ini")
        prefs._settings.setValue("map_positions", "not json at all")
        assert prefs.node_positions() == {}

    def test_a_malformed_entry_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        prefs = Preferences(tmp_path / "p.ini")
        prefs._settings.setValue("map_positions", '{"1": [1, 2], "x": [3, 4], "2": "oops"}')
        assert prefs.node_positions() == {1: (1.0, 2.0)}

    def test_positions_round_trip(self, tmp_path: Path) -> None:
        prefs = Preferences(tmp_path / "p.ini")
        prefs.save_node_positions({3: (12.5, -40.0)})
        prefs.sync()
        assert Preferences(tmp_path / "p.ini").node_positions() == {3: (12.5, -40.0)}


# -- 6. the wordmark at every size -------------------------------------------


def white_pixels(image: QImage, *, top: float = 0.0, bottom: float = 1.0) -> int:
    count = 0
    for y in range(int(image.height() * top), int(image.height() * bottom)):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.red() > 200 and colour.green() > 200 and colour.blue() > 200:
                count += 1
    return count


class TestTheWordmark:
    @pytest.mark.parametrize("size", [16, 20, 24, 32, 48, 64, 128, 256])
    def test_the_word_and_the_dot_are_there_at_every_size(
        self, app: QApplication, size: int
    ) -> None:
        image = icons.app_image(size)
        upper = white_pixels(image, top=0.0, bottom=0.55)
        lower = white_pixels(image, top=0.55, bottom=1.0)
        assert upper > 0, "no letters in the upper part"
        assert lower > 0, "no dot in the lower part"

    @pytest.mark.parametrize("size", [16, 24, 32])
    def test_the_small_icons_are_not_a_simpler_picture(self, app: QApplication, size: int) -> None:
        # The letters take more of the icon than a lone arc would: at the smallest
        # sizes the word has to survive, not be replaced by a hint of it.
        image = icons.app_image(size)
        assert white_pixels(image, top=0.0, bottom=0.6) >= size // 2

    def test_the_icon_stays_inside_its_tile(self, app: QApplication) -> None:
        for size in (16, 32, 256):
            image = icons.app_image(size)
            margin = max(1, size // 16)
            for x in range(image.width()):
                for y in list(range(margin)) + list(range(image.height() - margin, image.height())):
                    colour = image.pixelColor(x, y)
                    assert not (colour.red() > 200 and colour.green() > 200 and colour.alpha() > 0)
