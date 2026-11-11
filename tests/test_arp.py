"""Reading ARP tables printed by different systems, in different languages."""

from __future__ import annotations

from discovery_now import arp

WINDOWS_ITALIAN = """
Interfaccia: 192.168.1.88 --- 0xe
  Indirizzo Internet    Indirizzo fisico      Tipo
  192.168.1.46          00-11-22-33-44-01     dinamico
  192.168.1.254         00-11-22-33-44-02     dinamico
  192.168.1.255         ff-ff-ff-ff-ff-ff     statico
  224.0.0.22            01-00-5e-00-00-16     statico
"""

LINUX_IP_NEIGH = """
192.168.1.46 dev wlan0 lladdr 00:11:22:33:44:01 REACHABLE
192.168.1.99 dev wlan0  FAILED
192.168.1.254 dev wlan0 lladdr 00:11:22:33:44:02 STALE
"""

PROC_NET_ARP = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.46     0x1         0x2         00:11:22:33:44:01     *        wlan0
192.168.1.99     0x1         0x0         00:00:00:00:00:00     *        wlan0
"""


class TestParseTable:
    def test_reads_localized_windows_output(self) -> None:
        table = arp.parse_table(WINDOWS_ITALIAN)
        assert table["192.168.1.46"] == "00:11:22:33:44:01"
        assert table["192.168.1.254"] == "00:11:22:33:44:02"

    def test_skips_the_broadcast_entry(self) -> None:
        assert "192.168.1.255" not in arp.parse_table(WINDOWS_ITALIAN)

    def test_reads_ip_neigh_output(self) -> None:
        table = arp.parse_table(LINUX_IP_NEIGH)
        assert table == {
            "192.168.1.46": "00:11:22:33:44:01",
            "192.168.1.254": "00:11:22:33:44:02",
        }

    def test_an_entry_without_an_address_is_left_out(self) -> None:
        assert "192.168.1.99" not in arp.parse_table(LINUX_IP_NEIGH)

    def test_reads_the_proc_table_and_skips_incomplete_rows(self) -> None:
        table = arp.parse_table(PROC_NET_ARP)
        assert table == {"192.168.1.46": "00:11:22:33:44:01"}

    def test_the_header_row_contributes_nothing(self) -> None:
        assert arp.parse_table("IP address HW type Flags HW address Mask Device") == {}

    def test_empty_input_is_an_empty_table(self) -> None:
        assert arp.parse_table("") == {}
