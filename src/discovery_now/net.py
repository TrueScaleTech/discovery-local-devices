"""Working out what to scan, and refusing to scan what we should not."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Iterator
from dataclasses import dataclass

import psutil

from ._proc import run_capture

_MAC_RE = re.compile(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

#: MACs that mean "no answer" or "everyone" rather than a device.
_PLACEHOLDER_MACS = frozenset({"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"})


class TargetError(Exception):
    """A requested target cannot be scanned, and the message says why."""


@dataclass(frozen=True, slots=True)
class Interface:
    """One local IPv4 interface and the subnet it sits on."""

    name: str
    address: str
    network: ipaddress.IPv4Network


def normalize_mac(raw: str | None) -> str | None:
    """Return a MAC as lowercase colon-separated text, or None if it is not one.

    Systems print MACs in several shapes: Windows uses ``aa-bb-cc-dd-ee-ff``,
    Linux uses colons, and some tools drop leading zeros. One stored shape keeps
    a device from being counted twice.
    """
    if not raw:
        return None
    match = _MAC_RE.search(raw)
    if not match:
        return None
    mac = match.group(0).replace("-", ":").lower()
    return None if mac in _PLACEHOLDER_MACS else mac


def find_mac(text: str) -> str | None:
    """Find the first MAC address in a line of command output."""
    return normalize_mac(text)


def find_ipv4(text: str) -> str | None:
    """Find the first valid IPv4 address in a line of command output."""
    for candidate in _IPV4_RE.findall(text):
        try:
            ipaddress.IPv4Address(candidate)
        except ValueError:
            continue
        return str(candidate)
    return None


def local_interfaces() -> list[Interface]:
    """The usable IPv4 interfaces of this machine.

    Loopback and link-local addresses are left out: nothing lives there that the
    user means by "my network".
    """
    stats = psutil.net_if_stats()
    found: list[Interface] = []
    for name, addresses in psutil.net_if_addrs().items():
        state = stats.get(name)
        if state is not None and not state.isup:
            continue
        for address in addresses:
            if address.family != socket.AF_INET or not address.address or not address.netmask:
                continue
            try:
                interface = ipaddress.ip_interface(f"{address.address}/{address.netmask}")
            except ValueError:
                continue
            if not isinstance(interface.network, ipaddress.IPv4Network):
                continue
            ip = interface.ip
            if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                continue
            found.append(Interface(name=name, address=str(ip), network=interface.network))
    return found


def local_macs() -> dict[str, str]:
    """The MAC address of each of this machine's own IPv4 addresses.

    A machine never ARPs for itself, so its own address is missing from the ARP
    cache and would otherwise be the one device in the inventory with no hardware
    address. The interface table has it.
    """
    table: dict[str, str] = {}
    for addresses in psutil.net_if_addrs().values():
        ipv4 = [a.address for a in addresses if a.family == socket.AF_INET and a.address]
        hardware = [
            normalize_mac(a.address) for a in addresses if a.family == psutil.AF_LINK and a.address
        ]
        mac = next((item for item in hardware if item), None)
        if not mac:
            continue
        for address in ipv4:
            table[address] = mac
    return table


#: The route that means "everything else" in a Windows routing table. It is a
#: token being read, never an address anything binds to.
_ANY_ROUTE = "0.0.0.0"  # noqa: S104


def parse_gateways(text: str) -> list[str]:
    """The default gateways in the output of ``ip route`` or ``route print``.

    Both are read by shape rather than by column or by word, so a translated
    Windows and any iproute2 version are read the same way:

    - ``default via 192.168.1.254 dev wlan0`` (Linux)
    - ``0.0.0.0  0.0.0.0  192.168.1.254  192.168.1.46  35`` (Windows)
    """
    found: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        linux = parts[0] == "default" and parts[1] == "via"
        windows = parts[0] == _ANY_ROUTE and parts[1] == _ANY_ROUTE
        if not (linux or windows):
            continue
        try:
            address = ipaddress.IPv4Address(parts[2])
        except ValueError:
            continue
        if address.is_unspecified or str(address) in found:
            continue
        found.append(str(address))
    return found


def default_gateways(*, timeout: float = 2.0) -> list[str]:
    """Ask the operating system which addresses are its default gateways.

    Returns an empty list when the routing table cannot be read: the map that
    uses this falls back to working the gateway out from the devices themselves.
    """
    commands = (
        ["ip", "-4", "route", "show", "default"],
        ["route", "print", "-4"],
        ["netstat", "-rn"],
    )
    for command in commands:
        result = run_capture(command, timeout=timeout)
        if result is None:
            continue
        status, text = result
        if status != 0:
            continue
        gateways = parse_gateways(text)
        if gateways:
            return gateways
    return []


def parse_network(value: str) -> ipaddress.IPv4Network:
    """Read a subnet written as ``192.168.1.0/24``, or a bare address as a /32."""
    try:
        return ipaddress.IPv4Network(value, strict=False)
    except ValueError as error:
        raise TargetError(f"{value!r} is not an IPv4 subnet") from error


def check_allowed(
    network: ipaddress.IPv4Network,
    *,
    allow_public: bool,
    max_hosts: int,
) -> None:
    """Raise :class:`TargetError` unless this subnet is one we agree to scan.

    Two guards, both deliberate. Scanning addresses that are not yours is at best
    rude and in many places unlawful, so public ranges are refused unless the user
    turns them on explicitly. And a subnet wider than the limit is refused because
    a mistyped prefix should not quietly start millions of probes.
    """
    if not allow_public and not network.is_private:
        raise TargetError(
            f"{network} is outside private address space. Discovery Now only scans "
            "networks you own; set allow_public_ranges in the config if you are "
            "authorized to scan this one."
        )
    size = network.num_addresses if network.prefixlen >= 31 else network.num_addresses - 2
    if size > max_hosts:
        raise TargetError(
            f"{network} holds {size} addresses, more than the limit of {max_hosts}. "
            "Narrow the subnet or raise max_hosts_per_subnet."
        )


def hosts(network: ipaddress.IPv4Network) -> Iterator[str]:
    """Every address worth probing in a subnet.

    A /31 or /32 has no network and broadcast address to skip, which is why the
    point-to-point case is handled apart.
    """
    if network.prefixlen >= 31:
        yield from (str(address) for address in network)
        return
    yield from (str(address) for address in network.hosts())


def resolve_targets(
    subnets: list[str],
    *,
    allow_public: bool,
    max_hosts: int,
) -> list[ipaddress.IPv4Network]:
    """Turn configured subnets, or the local interfaces, into a checked target list."""
    if subnets:
        networks = [parse_network(value) for value in subnets]
    else:
        networks = [interface.network for interface in local_interfaces()]
        if not networks:
            raise TargetError(
                "No active IPv4 interface found. Connect to a network, or set "
                "subnets in the config file."
            )
    unique: list[ipaddress.IPv4Network] = []
    for network in networks:
        if network not in unique:
            unique.append(network)
    for network in unique:
        check_allowed(network, allow_public=allow_public, max_hosts=max_hosts)
    return unique


def reverse_dns(ip: str, *, timeout: float = 1.0) -> str | None:
    """Ask for the name behind an address, giving up quietly if nobody answers."""
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        name, _aliases, _addresses = socket.gethostbyaddr(ip)
    except (OSError, UnicodeError):
        return None
    finally:
        socket.setdefaulttimeout(previous)
    return name or None
