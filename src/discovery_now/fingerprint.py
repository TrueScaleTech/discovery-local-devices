"""A rough guess at what kind of thing a device is.

This is a heuristic and it is presented as one. The point is not to be right every
time: it is to turn a wall of addresses into something a person can skim, so the
printer looks like a printer and the one unexplained line stands out.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from .oui import is_locally_administered

#: What a device that picked its own MAC address is called when nothing else is known.
PRIVATE_ADDRESS = "Private address auto-assigned"

#: Ports that say a lot on their own, strongest signal first.
_PORT_SIGNS: tuple[tuple[frozenset[int], str], ...] = (
    (frozenset({9100, 515, 631}), "printer"),
    (frozenset({62078}), "iPhone / iPad"),
    (frozenset({8006}), "Proxmox host"),
    (frozenset({554}), "camera"),
    (frozenset({1883}), "home automation"),
    (frozenset({3389}), "Windows PC"),
)

#: Vendor names that place a device without any port being open.
_VENDOR_SIGNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("espressif", "tuya", "shelly", "sonoff"), "smart device"),
    (("raspberry",), "single-board computer"),
    (("synology", "qnap"), "NAS"),
    (("sonos", "roku", "chromecast"), "media player"),
    (("philips lighting", "signify"), "smart lighting"),
    (("ubiquiti", "mikrotik", "aruba", "zyxel", "avm"), "network equipment"),
    (("cisco", "fortinet", "juniper", "check point", "palo alto"), "network equipment"),
    (("tp-link", "netgear", "d-link", "asustek", "huawei"), "network equipment"),
    (("apple",), "Apple device"),
    (("vmware", "oracle virtualbox", "qemu", "microsoft hyper-v", "xen"), "virtual machine"),
    (("hewlett-packard", "brother", "canon", "seiko epson"), "printer or PC"),
    (("nintendo", "sony"), "game console"),
    (("amazon", "google"), "smart speaker or streamer"),
)

#: Hostnames routers usually answer with for themselves.
_GATEWAY_HINTS = ("router", "gateway", "fritz", "livebox", "homeassistant", "openwrt")

#: Words in a hostname that say what a device is, most specific first. A "stem" is
#: looked for anywhere in the name, because people glue words together ("ana-sphone"
#: is a phone). A "token" must be a whole word, because "tv" or "nas" would
#: otherwise turn up inside names that mean nothing of the sort.
#:
#: Windows calls laptops and desktops alike "DESKTOP-xxxx", so that one only says
#: "computer".
_NAME_RULES: tuple[tuple[str, str, str], ...] = (
    ("stem", "iphone", "iPhone / iPad"),
    ("stem", "ipad", "iPhone / iPad"),
    ("stem", "tablet", "tablet"),
    ("token", "tab", "tablet"),
    ("stem", "phone", "phone"),
    ("stem", "android", "phone"),
    ("stem", "galaxy", "phone"),
    ("stem", "pixel", "phone"),
    ("stem", "macbook", "laptop"),
    ("stem", "laptop", "laptop"),
    ("stem", "notebook", "laptop"),
    ("stem", "thinkpad", "laptop"),
    ("stem", "imac", "computer"),
    ("stem", "desktop", "computer"),
    ("token", "pc", "computer"),
    ("stem", "printer", "printer"),
    ("stem", "camera", "camera"),
    ("token", "cam", "camera"),
    ("stem", "chromecast", "media player"),
    ("stem", "appletv", "media player"),
    ("stem", "roku", "media player"),
    ("token", "tv", "TV or media player"),
    ("token", "nas", "NAS"),
)


class Identified(Protocol):
    """Anything that carries what a scan learns about a device."""

    @property
    def mac(self) -> str | None: ...

    @property
    def vendor(self) -> str | None: ...

    @property
    def hostname(self) -> str | None: ...

    @property
    def open_ports(self) -> Sequence[int]: ...


def _kind_from_name(hostname: str) -> str | None:
    """What the hostname says the device is, if it says anything."""
    name = hostname.lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", name) if token}
    for how, needle, label in _NAME_RULES:
        if (how == "stem" and needle in name) or (how == "token" and needle in tokens):
            return label
    return None


def guess_kind(
    *,
    vendor: str | None = None,
    hostname: str | None = None,
    open_ports: Sequence[int] = (),
    mac: str | None = None,
) -> str | None:
    """Best guess at the device type, or None when nothing points anywhere.

    The clues are weighed from the strongest to the weakest: the ports it answers
    on, the name it gives itself, the company that made its network chip, and last
    the shape of what it exposes. When none of them says anything and the MAC
    address was made up by the device, that is itself the one thing worth saying.
    """
    ports = set(open_ports)

    # A device answering DNS and serving a web page is the router, even though it
    # may also expose a camera or file-sharing port. Checked first because those
    # other ports would otherwise claim it.
    if 53 in ports and ports & {80, 443}:
        return "router or gateway"

    for signs, label in _PORT_SIGNS:
        if ports & signs:
            return label

    name = (hostname or "").lower()
    if any(hint in name for hint in _GATEWAY_HINTS):
        return "router or gateway"

    # Before the vendor on purpose: "tablet-ana" made by Apple is a tablet, which
    # says more than "Apple device".
    from_name = _kind_from_name(name)
    if from_name:
        return from_name

    maker = (vendor or "").lower()
    for needles, label in _VENDOR_SIGNS:
        if any(needle in maker for needle in needles):
            return label

    # Nothing identifying, so fall back to the shape of what is exposed.
    if {53, 80} <= ports or {53, 443} <= ports:
        return "router or gateway"
    if {445, 139} & ports:
        return "file sharing host"
    if 22 in ports:
        return "server"
    if ports & {80, 443, 8080, 8443}:
        return "web interface"

    # A phone or laptop that invented its own address on this network gives us
    # nothing else to go on. The address itself is the honest answer: it names what
    # we know, not a device type we would be guessing.
    if mac and is_locally_administered(mac):
        return PRIVATE_ADDRESS
    return None


def kind_of(thing: Identified) -> str | None:
    """The guessed kind of a stored device or a fresh scan result alike.

    Every place that shows a kind goes through here, so none of them can forget one
    of the clues.
    """
    return guess_kind(
        vendor=thing.vendor,
        hostname=thing.hostname,
        open_ports=thing.open_ports,
        mac=thing.mac,
    )
