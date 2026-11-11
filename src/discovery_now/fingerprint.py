"""A rough guess at what kind of thing a device is.

This is a heuristic and it is presented as one. The point is not to be right every
time: it is to turn a wall of addresses into something a person can skim, so the
printer looks like a printer and the one unexplained line stands out.
"""

from __future__ import annotations

from collections.abc import Sequence

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


def guess_kind(
    *,
    vendor: str | None = None,
    hostname: str | None = None,
    open_ports: Sequence[int] = (),
) -> str | None:
    """Best guess at the device type, or None when nothing points anywhere."""
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
    return None
