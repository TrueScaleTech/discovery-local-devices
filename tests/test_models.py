"""The small rules that live on the data classes."""

from __future__ import annotations

from datetime import timedelta

from discovery_now.models import Device, Observation, utcnow


class TestObservationKey:
    def test_the_hardware_address_is_the_identity(self) -> None:
        assert Observation(ip="192.168.1.10", mac="aa:bb:cc:dd:ee:01").key == "aa:bb:cc:dd:ee:01"

    def test_without_one_the_address_is_used_and_marked_as_such(self) -> None:
        # Marked so that an IP-identified device is never confused with a MAC.
        assert Observation(ip="192.168.1.10").key == "ip:192.168.1.10"


def _device(**overrides: object) -> Device:
    moment = utcnow()
    base: dict[str, object] = {
        "id": 1,
        "key": "aa:bb:cc:dd:ee:01",
        "ip": "192.168.1.10",
        "mac": "aa:bb:cc:dd:ee:01",
        "hostname": None,
        "vendor": None,
        "label": None,
        "notes": None,
        "first_seen": moment,
        "last_seen": moment,
        "online": True,
        "approved": False,
        "misses": 0,
    }
    base.update(overrides)
    return Device(**base)  # type: ignore[arg-type]


class TestDeviceName:
    def test_a_label_wins(self) -> None:
        assert _device(label="Printer", hostname="prn01", vendor="Brother").name == "Printer"

    def test_then_the_hostname(self) -> None:
        assert _device(hostname="prn01", vendor="Brother").name == "prn01"

    def test_then_the_vendor(self) -> None:
        assert _device(vendor="Brother").name == "Brother"

    def test_and_the_address_as_a_last_resort(self) -> None:
        assert _device().name == "192.168.1.10"


class TestIsNew:
    def test_a_device_seen_today_is_new(self) -> None:
        assert _device().is_new(timedelta(days=7))

    def test_an_old_device_is_not(self) -> None:
        old = _device(first_seen=utcnow() - timedelta(days=10))
        assert not old.is_new(timedelta(days=7))
