"""The inventory: how scans become devices, and how devices change state."""

from __future__ import annotations

from datetime import timedelta

from discovery_now.models import EventKind, Observation, utcnow
from discovery_now.store import Store

WEEK = timedelta(days=7)


def seen(ip: str, mac: str | None = None, **extra: object) -> Observation:
    """A short way to write "this was on the network"."""
    return Observation(ip=ip, mac=mac, **extra)  # type: ignore[arg-type]


class TestFirstSight:
    def test_a_scan_creates_a_device(self, store: Store) -> None:
        outcome = store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        assert outcome.seen == 1
        assert len(outcome.discovered) == 1
        assert store.devices()[0].ip == "192.168.1.10"

    def test_the_first_sight_is_recorded_in_the_history(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        assert store.events()[0].kind is EventKind.DISCOVERED

    def test_a_new_device_is_not_approved(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        assert store.devices()[0].approved is False

    def test_a_new_device_carries_the_new_badge(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        assert store.devices()[0].is_new(WEEK)

    def test_the_badge_expires(self, store: Store) -> None:
        store.record_scan(
            [seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], now=utcnow() - timedelta(days=30)
        )
        assert not store.devices()[0].is_new(WEEK)


class TestSeenAgain:
    def test_the_same_device_is_not_stored_twice(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        outcome = store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        assert outcome.discovered == []
        assert len(store.devices()) == 1

    def test_a_device_keeps_its_first_sight_time(self, store: Store) -> None:
        first = utcnow() - timedelta(days=3)
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], now=first)
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        device = store.devices()[0]
        assert device.first_seen < device.last_seen

    def test_a_new_address_for_the_same_hardware_is_recorded(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        store.record_scan([seen("192.168.1.77", "aa:bb:cc:dd:ee:01")])
        devices = store.devices()
        assert len(devices) == 1
        assert devices[0].ip == "192.168.1.77"
        assert any(event.kind is EventKind.IP_CHANGED for event in store.events())

    def test_a_newly_opened_port_is_recorded(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01", open_ports=(80,))])
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01", open_ports=(80, 22))])
        ports = [event for event in store.events() if event.kind is EventKind.PORTS_CHANGED]
        assert ports and "opened 22" in ports[0].detail


class TestGoingOffline:
    def test_one_missed_scan_is_not_enough(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], offline_after=3)
        store.record_scan([], offline_after=3)
        assert store.devices()[0].online is True

    def test_enough_missed_scans_mean_offline(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], offline_after=2)
        store.record_scan([], offline_after=2)
        outcome = store.record_scan([], offline_after=2)
        assert len(outcome.went_offline) == 1
        assert store.devices()[0].online is False

    def test_going_offline_is_recorded_once(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], offline_after=1)
        store.record_scan([], offline_after=1)
        store.record_scan([], offline_after=1)
        offline = [event for event in store.events() if event.kind is EventKind.OFFLINE]
        assert len(offline) == 1

    def test_coming_back_is_reported(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], offline_after=1)
        store.record_scan([], offline_after=1)
        outcome = store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], offline_after=1)
        assert len(outcome.back_online) == 1
        assert store.devices()[0].online is True


class TestIdentity:
    def test_a_device_first_seen_without_a_mac_is_merged_later(self, store: Store) -> None:
        # The ARP cache may not hold the entry on the first pass. When it does,
        # the device must stay one device rather than becoming two.
        store.record_scan([seen("192.168.1.10")])
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        devices = store.devices()
        assert len(devices) == 1
        assert devices[0].mac == "aa:bb:cc:dd:ee:01"

    def test_merging_keeps_the_original_first_sight(self, store: Store) -> None:
        earlier = utcnow() - timedelta(days=2)
        store.record_scan([seen("192.168.1.10")], now=earlier)
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        assert store.devices()[0].first_seen.date() == earlier.date()

    def test_two_different_devices_stay_apart(self, store: Store) -> None:
        store.record_scan(
            [
                seen("192.168.1.10", "aa:bb:cc:dd:ee:01"),
                seen("192.168.1.11", "aa:bb:cc:dd:ee:02"),
            ]
        )
        assert len(store.devices()) == 2


class TestFinding:
    def test_by_number(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        device = store.devices()[0]
        assert store.find(str(device.id)) is not None

    def test_by_address(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        found = store.find("192.168.1.10")
        assert found is not None and found.ip == "192.168.1.10"

    def test_by_hardware_address(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        assert store.find("aa:bb:cc:dd:ee:01") is not None

    def test_by_part_of_the_name(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        store.set_label(store.devices()[0].id, "Office printer")
        assert store.find("printer") is not None

    def test_an_unknown_selector_finds_nothing(self, store: Store) -> None:
        assert store.find("nothing-like-this") is None


class TestAnnotating:
    def test_a_label_becomes_the_name(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        store.set_label(store.devices()[0].id, "Kitchen tablet")
        assert store.devices()[0].name == "Kitchen tablet"

    def test_approving_is_recorded(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        store.set_approved(store.devices()[0].id, True)
        assert store.devices()[0].approved
        assert any(event.kind is EventKind.APPROVED for event in store.events())

    def test_forgetting_removes_the_device_and_its_history(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        device_id = store.devices()[0].id
        store.forget(device_id)
        assert store.devices() == []
        assert store.events(device_id=device_id) == []


class TestSummary:
    def test_counts_every_state(self, store: Store) -> None:
        store.record_scan(
            [
                seen("192.168.1.10", "aa:bb:cc:dd:ee:01"),
                seen("192.168.1.11", "aa:bb:cc:dd:ee:02"),
            ],
            offline_after=1,
        )
        store.set_approved(store.devices()[0].id, True)
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], offline_after=1)

        counts = store.summary(new_within=WEEK)
        assert counts == {"total": 2, "online": 1, "offline": 1, "new": 2, "unapproved": 1}


class TestFiltering:
    def test_only_online_devices(self, store: Store) -> None:
        store.record_scan(
            [
                seen("192.168.1.10", "aa:bb:cc:dd:ee:01"),
                seen("192.168.1.11", "aa:bb:cc:dd:ee:02"),
            ],
            offline_after=1,
        )
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], offline_after=1)
        assert [device.ip for device in store.devices(online=True)] == ["192.168.1.10"]

    def test_only_recently_discovered_devices(self, store: Store) -> None:
        store.record_scan(
            [seen("192.168.1.10", "aa:bb:cc:dd:ee:01")], now=utcnow() - timedelta(days=30)
        )
        store.record_scan([seen("192.168.1.11", "aa:bb:cc:dd:ee:02")])
        recent = store.devices(new_within=WEEK)
        assert [device.ip for device in recent] == ["192.168.1.11"]

    def test_devices_are_listed_in_address_order(self, store: Store) -> None:
        store.record_scan(
            [
                seen("192.168.1.100", "aa:bb:cc:dd:ee:03"),
                seen("192.168.1.9", "aa:bb:cc:dd:ee:04"),
            ]
        )
        assert [device.ip for device in store.devices()] == ["192.168.1.9", "192.168.1.100"]


class TestPersistence:
    def test_the_inventory_survives_reopening(self, store: Store) -> None:
        store.record_scan([seen("192.168.1.10", "aa:bb:cc:dd:ee:01")])
        path = store.path
        store.close()
        with Store(path) as reopened:
            assert len(reopened.devices()) == 1


class TestLastScan:
    def test_none_before_the_first_scan(self, store: Store) -> None:
        assert store.last_scan_at() is None

    def test_the_most_recent_scan_wins(self, store: Store) -> None:
        early = utcnow() - timedelta(hours=2)
        late = utcnow() - timedelta(minutes=5)
        store.record_scan_run(
            networks=["192.168.1.0/24"], probed=254, found=3, duration=1, now=late
        )
        store.record_scan_run(
            networks=["192.168.1.0/24"], probed=254, found=3, duration=1, now=early
        )
        stored = store.last_scan_at()
        assert stored is not None
        assert abs((stored - late).total_seconds()) < 1
