"""What the window shows, decided without any Qt.

Filtering, searching, counting and wording live here so they can be tested without
a display and so the window itself stays a layer of drawing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from ..fingerprint import kind_of
from ..models import Device, Event, EventKind, utcnow


class Filter(StrEnum):
    """The quick filters above the device list."""

    ALL = "all"
    ONLINE = "online"
    OFFLINE = "offline"
    NEW = "new"
    UNAPPROVED = "unapproved"

    @property
    def label(self) -> str:
        return {
            Filter.ALL: "All",
            Filter.ONLINE: "Online",
            Filter.OFFLINE: "Offline",
            Filter.NEW: "New",
            Filter.UNAPPROVED: "Not approved",
        }[self]


def passes(
    device: Device, quick: Filter, *, new_within: timedelta, now: datetime | None = None
) -> bool:
    """Whether a device belongs under one of the quick filters."""
    if quick is Filter.ALL:
        return True
    if quick is Filter.ONLINE:
        return device.online
    if quick is Filter.OFFLINE:
        return not device.online
    if quick is Filter.NEW:
        return device.is_new(new_within, now=now)
    return not device.approved


def counts(
    devices: Iterable[Device], *, new_within: timedelta, now: datetime | None = None
) -> dict[Filter, int]:
    """How many devices sit under each quick filter, for the numbers on the buttons."""
    moment = now or utcnow()
    listed = list(devices)
    return {
        quick: sum(1 for d in listed if passes(d, quick, new_within=new_within, now=moment))
        for quick in Filter
    }


def haystack(device: Device) -> str:
    """Everything a search should be able to find a device by, in one lowercase string."""
    parts = (
        device.label,
        device.hostname,
        device.ip,
        device.mac,
        device.vendor,
        kind_of(device),
        device.notes,
    )
    return " ".join(part for part in parts if part).lower()


def matches_query(device: Device, query: str) -> bool:
    """True when every word typed in the search box appears somewhere on the device."""
    words = query.lower().split()
    if not words:
        return True
    text = haystack(device)
    return all(word in text for word in words)


def address_key(ip: str) -> tuple[int, ...]:
    """Sort addresses the way a network is read: numerically, not alphabetically."""
    try:
        return tuple(int(part) for part in ip.split("."))
    except ValueError:
        return (999, 999, 999, 999)


def ports_text(ports: Sequence[int]) -> str:
    return ", ".join(str(port) for port in ports)


def ago(moment: datetime, *, now: datetime | None = None) -> str:
    """A short "how long ago", in the words a person would use."""
    seconds = int(((now or utcnow()) - moment).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    days = seconds // 86400
    return f"{days} d ago"


def clock(moment: datetime) -> str:
    """A stored UTC timestamp, shown in the reader's own time."""
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def display_name(device: Device) -> str:
    """The name a device goes by on screen."""
    return device.name


def automatic_name(device: Device) -> str:
    """What the device would be called if the user had not named it."""
    return device.hostname or device.vendor or device.ip


_EVENT_TITLES: dict[EventKind, str] = {
    EventKind.DISCOVERED: "New device",
    EventKind.ONLINE: "Back online",
    EventKind.OFFLINE: "Went offline",
    EventKind.IP_CHANGED: "Address changed",
    EventKind.HOSTNAME_CHANGED: "Name changed",
    EventKind.PORTS_CHANGED: "Ports changed",
    EventKind.VENDOR_CHANGED: "Vendor changed",
    EventKind.APPROVED: "Approval",
    EventKind.RENAMED: "Renamed",
}


def event_title(event: Event) -> str:
    """A readable name for what happened."""
    return _EVENT_TITLES.get(event.kind, event.kind.value)


def scan_summary(
    found: int, *, new: int = 0, back: int = 0, gone: int = 0, changed: int = 0
) -> str:
    """One line about what a scan turned up, for the status bar."""
    noun = "device" if found == 1 else "devices"
    parts = [f"{found} {noun} answered"]
    if new:
        parts.append(f"{new} new")
    if back:
        parts.append(f"{back} back online")
    if gone:
        parts.append(f"{gone} went offline")
    if changed:
        parts.append(f"{changed} changed")
    return ", ".join(parts)


_STAGE_TITLES = {
    "ping sweep": "Looking for devices",
    "tcp probe": "Trying the quiet ones",
    "service probe": "Checking services",
    "name lookup": "Looking up names",
}


def stage_title(stage: str) -> str:
    """The scan stage in words a person would use."""
    return _STAGE_TITLES.get(stage, stage.capitalize())
