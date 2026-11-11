"""The device-type guess."""

from __future__ import annotations

from discovery_now.fingerprint import guess_kind


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
