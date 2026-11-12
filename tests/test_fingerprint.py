"""The device-type guess."""

from __future__ import annotations

import pytest

from discovery_now.fingerprint import PRIVATE_ADDRESS, guess_kind, kind_of
from discovery_now.models import Device, Observation, utcnow


class TestPortSignals:
    def test_a_raw_printing_port_means_a_printer(self) -> None:
        assert guess_kind(open_ports=[80, 9100]) == "printer"

    def test_the_iphone_sync_port_is_recognised(self) -> None:
        assert guess_kind(open_ports=[62078]) == "iPhone / iPad"

    def test_a_streaming_port_suggests_a_camera(self) -> None:
        assert guess_kind(open_ports=[554]) == "camera"

    def test_dns_plus_a_web_page_is_the_router(self) -> None:
        # Checked before the camera rule: a home router often exposes both, and
        # it is the router, not a camera.
        assert guess_kind(open_ports=[53, 80, 443, 445, 554]) == "router or gateway"


class TestVendorSignals:
    def test_a_known_iot_maker_is_a_smart_device(self) -> None:
        assert guess_kind(vendor="Espressif Inc.") == "smart device"

    def test_a_board_maker_is_a_single_board_computer(self) -> None:
        assert guess_kind(vendor="Raspberry Pi Trading Ltd") == "single-board computer"

    def test_a_network_vendor_is_network_equipment(self) -> None:
        assert guess_kind(vendor="TP-Link Systems Inc") == "network equipment"

    def test_a_hypervisor_prefix_means_a_virtual_machine(self) -> None:
        assert guess_kind(vendor="VMware, Inc.") == "virtual machine"


class TestFallbacks:
    def test_a_telling_hostname_is_enough(self) -> None:
        assert guess_kind(hostname="fritz.box") == "router or gateway"

    def test_windows_sharing_ports_are_a_file_host(self) -> None:
        assert guess_kind(open_ports=[139, 445]) == "file sharing host"

    def test_ssh_alone_suggests_a_server(self) -> None:
        assert guess_kind(open_ports=[22]) == "server"

    def test_nothing_known_is_an_honest_nothing(self) -> None:
        assert guess_kind() is None


class TestHostnameSignals:
    @pytest.mark.parametrize(
        ("hostname", "kind"),
        [
            ("ana-sphone.home", "phone"),
            ("Marias-iPhone", "iPhone / iPad"),
            ("tablet-ana.home", "tablet"),
            ("Galaxy-Tab-S9", "tablet"),
            ("Galaxy-S24", "phone"),
            ("pixel-8", "phone"),
            ("laptop-office.home", "laptop"),
            ("Marias-MacBook-Air", "laptop"),
            ("DESKTOP-ABC123", "computer"),
            ("mum-pc", "computer"),
            ("hp-printer", "printer"),
            ("garden-cam", "camera"),
            ("living-room-tv", "TV or media player"),
            ("home-nas", "NAS"),
        ],
    )
    def test_the_name_says_what_the_device_is(self, hostname: str, kind: str) -> None:
        assert guess_kind(hostname=hostname) == kind

    def test_a_name_beats_the_makers_label(self) -> None:
        # An Apple tablet is a tablet; "Apple device" would say less.
        assert guess_kind(vendor="Apple, Inc.", hostname="tablet-ana.home") == "tablet"

    def test_a_computer_name_beats_the_file_sharing_ports(self) -> None:
        assert guess_kind(hostname="DESKTOP-ABC123", open_ports=[139, 445]) == "computer"

    def test_ports_still_win_over_a_name(self) -> None:
        assert guess_kind(hostname="my-phone", open_ports=[9100]) == "printer"

    def test_a_short_word_only_counts_as_a_whole_word(self) -> None:
        # "nas" and "tv" appear inside names that mean nothing of the kind.
        assert guess_kind(hostname="canasta") is None
        assert guess_kind(hostname="activity-hub") is None

    def test_a_name_that_says_nothing_says_nothing(self) -> None:
        assert guess_kind(hostname="s24-of-ana.home") is None

    def test_an_address_as_a_name_is_not_read_for_words(self) -> None:
        assert guess_kind(hostname="192.168.1.254") is None


class TestPrivateAddress:
    def test_a_made_up_mac_with_nothing_else_is_named_for_what_it_is(self) -> None:
        assert guess_kind(mac="ce:11:22:33:44:55") == PRIVATE_ADDRESS

    def test_the_wording_is_exactly_as_asked(self) -> None:
        assert PRIVATE_ADDRESS == "Private address auto-assigned"

    def test_a_real_mac_with_nothing_else_stays_unknown(self) -> None:
        assert guess_kind(mac="00:11:22:33:44:01") is None

    def test_any_other_clue_wins_over_it(self) -> None:
        assert guess_kind(mac="ce:11:22:33:44:55", hostname="ana-sphone") == "phone"
        assert guess_kind(mac="ce:11:22:33:44:55", open_ports=[22]) == "server"

    def test_a_missing_mac_adds_nothing(self) -> None:
        assert guess_kind(mac=None) is None


class TestKindOf:
    def test_reads_a_stored_device(self) -> None:
        moment = utcnow()
        device = Device(
            id=1,
            key="ce:11:22:33:44:55",
            ip="192.168.1.24",
            mac="ce:11:22:33:44:55",
            hostname="ana-sphone.home",
            vendor=None,
            label=None,
            notes=None,
            first_seen=moment,
            last_seen=moment,
            online=True,
            approved=False,
            misses=0,
        )
        assert kind_of(device) == "phone"

    def test_reads_a_fresh_scan_result(self) -> None:
        assert kind_of(Observation(ip="192.168.1.9", mac="ae:11:22:33:44:55")) == PRIVATE_ADDRESS

    def test_a_scan_result_and_a_stored_device_agree(self) -> None:
        # What a scan prints and what the inventory shows must not differ.
        scanned = Observation(ip="192.168.1.9", mac="ce:11:22:33:44:55", hostname="tablet-ana")
        assert kind_of(scanned) == "tablet"
