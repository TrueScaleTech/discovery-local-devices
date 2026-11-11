"""The things Discovery Now talks about: an observation, a device, an event."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum


def utcnow() -> datetime:
    """Current time, timezone-aware and in UTC.

    Everything is stored in UTC and only rendered in local time, so an inventory
    survives travel, daylight saving and being copied between machines.
    """
    return datetime.now(UTC)


class EventKind(StrEnum):
    """What happened to a device. Stored as text so the history stays readable."""

    DISCOVERED = "discovered"
    ONLINE = "online"
    OFFLINE = "offline"
    IP_CHANGED = "ip_changed"
    HOSTNAME_CHANGED = "hostname_changed"
    PORTS_CHANGED = "ports_changed"
    VENDOR_CHANGED = "vendor_changed"
    APPROVED = "approved"
    RENAMED = "renamed"


@dataclass(slots=True)
class Observation:
    """One device as a single scan saw it.

    An observation is a fact about one moment: it is never updated, it is folded
    into the stored device by :class:`discovery_now.store.Store`.
    """

    ip: str
    mac: str | None = None
    hostname: str | None = None
    vendor: str | None = None
    open_ports: tuple[int, ...] = ()
    methods: frozenset[str] = frozenset()
    rtt_ms: float | None = None

    @property
    def key(self) -> str:
        """Stable identity for the device behind this observation.

        The MAC address is the identity whenever we have one, because DHCP hands
        out a different IP to the same device sooner or later. Without a MAC (a
        host on another subnet, or an ARP cache that did not keep the entry) the
        IP is all we have, and the key says so to keep the two kinds apart.
        """
        return self.mac if self.mac else f"ip:{self.ip}"


@dataclass(slots=True)
class Device:
    """A device as the inventory remembers it, across every scan so far."""

    id: int
    key: str
    ip: str
    mac: str | None
    hostname: str | None
    vendor: str | None
    label: str | None
    notes: str | None
    first_seen: datetime
    last_seen: datetime
    online: bool
    approved: bool
    misses: int
    open_ports: tuple[int, ...] = ()

    @property
    def name(self) -> str:
        """What to call this device on screen, best information first."""
        return self.label or self.hostname or self.vendor or self.ip

    def is_new(self, window: timedelta, *, now: datetime | None = None) -> bool:
        """True while the device is still within its "recently appeared" window."""
        return (now or utcnow()) - self.first_seen <= window

    def age(self, *, now: datetime | None = None) -> timedelta:
        """How long this device has been in the inventory."""
        return (now or utcnow()) - self.first_seen


@dataclass(slots=True)
class Event:
    """Something that happened to a device, kept so the history can be replayed."""

    id: int
    device_id: int
    kind: EventKind
    detail: str
    at: datetime


@dataclass(slots=True)
class ScanOutcome:
    """What one scan changed in the inventory."""

    seen: int = 0
    discovered: list[Device] = field(default_factory=list)
    back_online: list[Device] = field(default_factory=list)
    went_offline: list[Device] = field(default_factory=list)
    changed: list[tuple[Device, EventKind, str]] = field(default_factory=list)

    @property
    def has_news(self) -> bool:
        """True when the scan found anything worth telling the user about."""
        return bool(self.discovered or self.back_online or self.went_offline or self.changed)
