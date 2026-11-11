"""Vendor lookup, including the addresses that have no vendor."""

from __future__ import annotations

import pytest

from discovery_now import oui


class TestLocallyAdministered:
    @pytest.mark.parametrize("mac", ["ae:11:22:33:44:55", "ce:11:22:33:44:55", "3e:11:22:33:44:55"])
    def test_randomized_addresses_are_recognised(self, mac: str) -> None:
        # Phones randomize their MAC on networks they do not trust. The second
        # bit of the first octet is what says so.
        assert oui.is_locally_administered(mac)

    @pytest.mark.parametrize("mac", ["00:11:22:33:44:01", "b8:27:eb:00:11:22", "3c:97:0e:00:11:22"])
    def test_assigned_addresses_are_not(self, mac: str) -> None:
        assert not oui.is_locally_administered(mac)

    def test_the_familiar_aabbcc_example_is_itself_locally_administered(self) -> None:
        # Worth pinning down: the MAC everyone writes in examples has the bit set,
        # so it would never resolve to a vendor.
        assert oui.is_locally_administered("aa:bb:cc:dd:ee:ff")


class TestLookup:
    def test_resolves_a_prefix_from_the_built_in_list(self) -> None:
        assert oui.lookup("b8:27:eb:12:34:56") == "Raspberry Pi Foundation"

    def test_is_case_insensitive(self) -> None:
        assert oui.lookup("B8:27:EB:12:34:56") == "Raspberry Pi Foundation"

    def test_a_randomized_address_has_no_vendor(self) -> None:
        assert oui.lookup("ae:11:22:33:44:55") is None

    def test_an_unknown_prefix_returns_nothing(self) -> None:
        # Universally administered, so it reaches the table and is simply absent.
        assert oui.lookup("3c:11:22:98:76:54") is None

    def test_no_address_returns_nothing(self) -> None:
        assert oui.lookup(None) is None

    def test_the_built_in_list_is_loaded(self) -> None:
        assert oui.table_size() > 50


class TestDownloadedRegistry:
    def test_a_downloaded_file_adds_prefixes(self) -> None:
        cache = oui.oui_cache_path()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("# test\n3C1122,Acme Networks\n", encoding="utf-8")
        oui.reset_cache()
        assert oui.lookup("3c:11:22:98:76:54") == "Acme Networks"
        assert oui.using_full_registry()

    def test_plain_http_is_refused(self) -> None:
        with pytest.raises(ValueError, match="HTTPS"):
            oui.update("http://standards-oui.ieee.org/oui/oui.csv")
