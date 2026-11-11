"""Target selection and the guards around it."""

from __future__ import annotations

import ipaddress

import pytest

from discovery_now import net


class TestNormalizeMac:
    def test_accepts_the_windows_dash_form(self) -> None:
        assert net.normalize_mac("AA-BB-CC-DD-EE-01") == "aa:bb:cc:dd:ee:01"

    def test_accepts_the_colon_form(self) -> None:
        assert net.normalize_mac("aa:bb:cc:dd:ee:01") == "aa:bb:cc:dd:ee:01"

    def test_finds_a_mac_inside_a_line_of_output(self) -> None:
        line = "  192.168.1.1          00-11-22-33-44-01     dinamico"
        assert net.normalize_mac(line) == "00:11:22:33:44:01"

    @pytest.mark.parametrize(
        "value",
        ["", None, "not a mac", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"],
    )
    def test_rejects_non_addresses_and_placeholders(self, value: str | None) -> None:
        assert net.normalize_mac(value) is None


class TestFindIpv4:
    def test_finds_an_address_in_a_line(self) -> None:
        assert net.find_ipv4("? (192.168.1.254) at 00:11:22:33:44:02 [ether]") == "192.168.1.254"

    def test_ignores_impossible_octets(self) -> None:
        assert net.find_ipv4("version 999.1.1.1 build") is None

    def test_returns_none_without_an_address(self) -> None:
        assert net.find_ipv4("Interface: wlan0") is None


class TestCheckAllowed:
    def test_private_subnets_are_allowed(self) -> None:
        net.check_allowed(
            ipaddress.IPv4Network("192.168.1.0/24"), allow_public=False, max_hosts=4096
        )

    def test_public_subnets_are_refused_by_default(self) -> None:
        with pytest.raises(net.TargetError, match="private address space"):
            net.check_allowed(
                ipaddress.IPv4Network("8.8.8.0/24"), allow_public=False, max_hosts=4096
            )

    def test_public_subnets_can_be_allowed_deliberately(self) -> None:
        net.check_allowed(ipaddress.IPv4Network("8.8.8.0/24"), allow_public=True, max_hosts=4096)

    def test_oversized_subnets_are_refused(self) -> None:
        with pytest.raises(net.TargetError, match="more than the limit"):
            net.check_allowed(
                ipaddress.IPv4Network("10.0.0.0/8"), allow_public=False, max_hosts=4096
            )


class TestHosts:
    def test_skips_network_and_broadcast_addresses(self) -> None:
        assert list(net.hosts(ipaddress.IPv4Network("192.168.1.0/30"))) == [
            "192.168.1.1",
            "192.168.1.2",
        ]

    def test_keeps_both_addresses_of_a_point_to_point_link(self) -> None:
        assert list(net.hosts(ipaddress.IPv4Network("192.168.1.0/31"))) == [
            "192.168.1.0",
            "192.168.1.1",
        ]

    def test_a_single_address_is_scanned_on_its_own(self) -> None:
        assert list(net.hosts(ipaddress.IPv4Network("192.168.1.7/32"))) == ["192.168.1.7"]


class TestResolveTargets:
    def test_uses_the_configured_subnets(self) -> None:
        targets = net.resolve_targets(
            ["192.168.1.0/24", "10.0.0.0/24"], allow_public=False, max_hosts=4096
        )
        assert [str(target) for target in targets] == ["192.168.1.0/24", "10.0.0.0/24"]

    def test_drops_duplicates(self) -> None:
        targets = net.resolve_targets(
            ["192.168.1.0/24", "192.168.1.0/24"], allow_public=False, max_hosts=4096
        )
        assert len(targets) == 1

    def test_a_host_address_is_widened_to_its_subnet(self) -> None:
        targets = net.resolve_targets(["192.168.1.55/24"], allow_public=False, max_hosts=4096)
        assert str(targets[0]) == "192.168.1.0/24"

    def test_rejects_text_that_is_not_a_subnet(self) -> None:
        with pytest.raises(net.TargetError):
            net.resolve_targets(["my-network"], allow_public=False, max_hosts=4096)
