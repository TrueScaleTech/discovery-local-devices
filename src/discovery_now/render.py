"""Turning devices, events and scans into something to look at, or into JSON.

Both shapes live together on purpose: every command can be read by a person or by
a script, and keeping the two renderings side by side is what stops them drifting
apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from rich.table import Table
from rich.text import Text

from .fingerprint import kind_of
from .models import Device, Event, Observation, utcnow

_NO_VALUE = Text("-", style="dim")


def local_time(moment: datetime) -> str:
    """A stored UTC timestamp, shown in the reader's own time."""
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def humanize(delta: timedelta) -> str:
    """A short, approximate "how long ago"."""
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _ports(ports: Sequence[int]) -> Text:
    return Text(", ".join(str(port) for port in ports)) if ports else _NO_VALUE


def _optional(value: str | None) -> Text:
    return Text(value) if value else _NO_VALUE


def status_text(device: Device, *, new_within: timedelta, now: datetime | None = None) -> Text:
    """The state column: online or not, and whether this device is new or unvetted."""
    moment = now or utcnow()
    text = Text("online", style="green") if device.online else Text("offline", style="dim red")
    if device.is_new(new_within, now=moment):
        text.append("  NEW", style="bold magenta")
    elif not device.approved:
        text.append("  ?", style="yellow")
    return text


def devices_table(
    devices: Sequence[Device],
    *,
    new_within: timedelta,
    now: datetime | None = None,
    title: str | None = None,
) -> Table:
    """The inventory as a table."""
    moment = now or utcnow()
    table = Table(title=title, header_style="bold", expand=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("State")
    table.add_column("Address")
    table.add_column("MAC")
    table.add_column("Name")
    table.add_column("Vendor")
    table.add_column("Kind")
    table.add_column("Ports")
    table.add_column("Last seen", justify="right")

    for device in devices:
        kind = kind_of(device)
        table.add_row(
            str(device.id),
            status_text(device, new_within=new_within, now=moment),
            device.ip,
            _optional(device.mac),
            _optional(device.label or device.hostname),
            _optional(device.vendor),
            _optional(kind),
            _ports(device.open_ports),
            humanize(moment - device.last_seen),
        )
    return table


def observations_table(observations: Sequence[Observation], *, title: str | None = None) -> Table:
    """What a single scan saw, before it is folded into the inventory."""
    table = Table(title=title, header_style="bold")
    table.add_column("Address")
    table.add_column("MAC")
    table.add_column("Name")
    table.add_column("Vendor")
    table.add_column("Kind")
    table.add_column("Ports")
    table.add_column("Found via")
    table.add_column("RTT", justify="right")

    for item in observations:
        kind = kind_of(item)
        table.add_row(
            item.ip,
            _optional(item.mac),
            _optional(item.hostname),
            _optional(item.vendor),
            _optional(kind),
            _ports(item.open_ports),
            ", ".join(sorted(item.methods)) or "-",
            f"{item.rtt_ms:.0f} ms" if item.rtt_ms is not None else "-",
        )
    return table


def events_table(
    events: Sequence[Event],
    names: dict[int, str],
    *,
    title: str | None = None,
) -> Table:
    """A history log, newest first."""
    table = Table(title=title, header_style="bold")
    table.add_column("When")
    table.add_column("Device")
    table.add_column("Event")
    table.add_column("Detail")

    styles = {
        "discovered": "bold magenta",
        "online": "green",
        "offline": "red",
        "approved": "cyan",
    }
    for event in events:
        table.add_row(
            local_time(event.at),
            names.get(event.device_id, f"#{event.device_id}"),
            Text(event.kind.value, style=styles.get(event.kind.value, "yellow")),
            event.detail or "",
        )
    return table


def summary_table(counts: dict[str, int]) -> Table:
    """The headline numbers."""
    table = Table.grid(padding=(0, 3))
    table.add_column(style="bold")
    table.add_column(justify="right")
    table.add_row("Devices known", str(counts["total"]))
    table.add_row(Text("Online", style="green"), str(counts["online"]))
    table.add_row(Text("Offline", style="dim"), str(counts["offline"]))
    table.add_row(Text("New", style="magenta"), str(counts["new"]))
    table.add_row(Text("Not approved", style="yellow"), str(counts["unapproved"]))
    return table


def device_detail(device: Device, events: Sequence[Event], *, new_within: timedelta) -> Table:
    """Everything known about one device."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", justify="right")
    table.add_column()

    kind = kind_of(device)
    rows: list[tuple[str, Any]] = [
        ("Name", device.name),
        ("State", status_text(device, new_within=new_within)),
        ("Address", device.ip),
        ("MAC", device.mac or "unknown"),
        ("Vendor", device.vendor or "unknown"),
        ("Kind", kind or "unknown"),
        ("Hostname", device.hostname or "-"),
        ("Open ports", ", ".join(str(port) for port in device.open_ports) or "none"),
        ("First seen", f"{local_time(device.first_seen)}  ({humanize(device.age())})"),
        ("Last seen", f"{local_time(device.last_seen)}  ({humanize(utcnow() - device.last_seen)})"),
        ("Approved", "yes" if device.approved else "no"),
        ("Notes", device.notes or "-"),
    ]
    for label, value in rows:
        table.add_row(label, value)
    if events:
        table.add_row("", "")
        table.add_row("History", local_time(events[0].at) + "  " + events[0].kind.value)
        for event in events[1:]:
            detail = f"  {event.detail}" if event.detail else ""
            table.add_row("", f"{local_time(event.at)}  {event.kind.value}{detail}")
    return table


# -- JSON-safe shapes --------------------------------------------------------


def device_as_dict(device: Device, *, new_within: timedelta) -> dict[str, Any]:
    """A device as plain data, for ``--json`` and for exports."""
    return {
        "id": device.id,
        "name": device.name,
        "ip": device.ip,
        "mac": device.mac,
        "hostname": device.hostname,
        "vendor": device.vendor,
        "kind": kind_of(device),
        "label": device.label,
        "notes": device.notes,
        "open_ports": list(device.open_ports),
        "first_seen": device.first_seen.isoformat(),
        "last_seen": device.last_seen.isoformat(),
        "online": device.online,
        "approved": device.approved,
        "is_new": device.is_new(new_within),
    }


def observation_as_dict(observation: Observation) -> dict[str, Any]:
    """A scan result as plain data."""
    return {
        "ip": observation.ip,
        "mac": observation.mac,
        "hostname": observation.hostname,
        "vendor": observation.vendor,
        "kind": kind_of(observation),
        "open_ports": list(observation.open_ports),
        "methods": sorted(observation.methods),
        "rtt_ms": observation.rtt_ms,
    }


def event_as_dict(event: Event) -> dict[str, Any]:
    """A history entry as plain data."""
    return {
        "id": event.id,
        "device_id": event.device_id,
        "kind": event.kind.value,
        "detail": event.detail,
        "at": event.at.isoformat(),
    }
