"""The inventory: a single SQLite file holding devices, their history and past scans.

One file is the whole database. It can be copied to another machine, backed up by
copying it, and inspected with any SQLite browser, which matters for a tool whose
job is to be trusted with a record of your own network.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from .config import database_path
from .models import Device, Event, EventKind, Observation, ScanOutcome, utcnow

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id         INTEGER PRIMARY KEY,
    key        TEXT    NOT NULL UNIQUE,
    ip         TEXT    NOT NULL,
    mac        TEXT,
    hostname   TEXT,
    vendor     TEXT,
    label      TEXT,
    notes      TEXT,
    open_ports TEXT    NOT NULL DEFAULT '',
    first_seen TEXT    NOT NULL,
    last_seen  TEXT    NOT NULL,
    online     INTEGER NOT NULL DEFAULT 1,
    approved   INTEGER NOT NULL DEFAULT 0,
    misses     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_devices_mac ON devices (mac);
CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices (ip);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    kind      TEXT    NOT NULL,
    detail    TEXT    NOT NULL DEFAULT '',
    at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_device ON events (device_id, at DESC);

CREATE TABLE IF NOT EXISTS scans (
    id         INTEGER PRIMARY KEY,
    started_at TEXT    NOT NULL,
    networks   TEXT    NOT NULL,
    probed     INTEGER NOT NULL,
    found      INTEGER NOT NULL,
    duration   REAL    NOT NULL
);
"""


def _iso(moment: datetime) -> str:
    """Store a timestamp as UTC ISO 8601 text."""
    return moment.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    """Read a stored timestamp, assuming UTC when a file predates the tz suffix."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _ports_to_text(ports: Sequence[int]) -> str:
    return ",".join(str(port) for port in sorted(set(ports)))


def _ports_from_text(text: str | None) -> tuple[int, ...]:
    if not text:
        return ()
    return tuple(int(part) for part in text.split(",") if part.strip().isdigit())


class Store:
    """Read and write the inventory."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        # The desktop app will read while a background scan writes; WAL lets that
        # happen without the reader blocking.
        self._db.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        """Create the schema, and record its version for future upgrades."""
        self._db.executescript(_SCHEMA)
        current = int(self._db.execute("PRAGMA user_version").fetchone()[0])
        if current < SCHEMA_VERSION:
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.commit()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- reading -----------------------------------------------------------

    @staticmethod
    def _to_device(row: sqlite3.Row) -> Device:
        return Device(
            id=int(row["id"]),
            key=str(row["key"]),
            ip=str(row["ip"]),
            mac=row["mac"],
            hostname=row["hostname"],
            vendor=row["vendor"],
            label=row["label"],
            notes=row["notes"],
            first_seen=_parse(row["first_seen"]),
            last_seen=_parse(row["last_seen"]),
            online=bool(row["online"]),
            approved=bool(row["approved"]),
            misses=int(row["misses"]),
            open_ports=_ports_from_text(row["open_ports"]),
        )

    def devices(
        self,
        *,
        online: bool | None = None,
        approved: bool | None = None,
        new_within: timedelta | None = None,
        now: datetime | None = None,
    ) -> list[Device]:
        """Every device in the inventory, filtered and sorted by address."""
        clauses: list[str] = []
        params: list[Any] = []
        if online is not None:
            clauses.append("online = ?")
            params.append(int(online))
        if approved is not None:
            clauses.append("approved = ?")
            params.append(int(approved))
        if new_within is not None:
            clauses.append("first_seen >= ?")
            params.append(_iso((now or utcnow()) - new_within))
        # Every clause is a literal written above; the values travel as bound
        # parameters, so nothing from outside this method reaches the SQL text.
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._db.execute(f"SELECT * FROM devices{where}", params).fetchall()  # noqa: S608
        devices = [self._to_device(row) for row in rows]
        devices.sort(key=_address_order)
        return devices

    def get(self, device_id: int) -> Device | None:
        row = self._db.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        return self._to_device(row) if row else None

    def find(self, selector: str) -> Device | None:
        """Look a device up the way a person would name it.

        Accepts the number shown in the table, an IP, a MAC, or part of a label or
        hostname. An ambiguous name matches nothing rather than the wrong device.
        """
        selector = selector.strip()
        if not selector:
            return None
        if selector.isdigit():
            found = self.get(int(selector))
            if found:
                return found
        exact = self._db.execute(
            "SELECT * FROM devices WHERE ip = ? OR mac = ? OR label = ?",
            (selector, selector.lower(), selector),
        ).fetchall()
        if len(exact) == 1:
            return self._to_device(exact[0])
        pattern = f"%{selector.lower()}%"
        fuzzy = self._db.execute(
            "SELECT * FROM devices WHERE LOWER(label) LIKE ? OR LOWER(hostname) LIKE ?",
            (pattern, pattern),
        ).fetchall()
        return self._to_device(fuzzy[0]) if len(fuzzy) == 1 else None

    def events(self, *, device_id: int | None = None, limit: int = 50) -> list[Event]:
        """The most recent history entries, newest first."""
        if device_id is None:
            rows = self._db.execute(
                "SELECT * FROM events ORDER BY at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM events WHERE device_id = ? ORDER BY at DESC, id DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
        return [
            Event(
                id=int(row["id"]),
                device_id=int(row["device_id"]),
                kind=EventKind(row["kind"]),
                detail=str(row["detail"]),
                at=_parse(row["at"]),
            )
            for row in rows
        ]

    def summary(self, *, new_within: timedelta, now: datetime | None = None) -> dict[str, int]:
        """The counts a dashboard needs."""
        moment = now or utcnow()
        total, online, unapproved = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(online), 0), COALESCE(SUM(1 - approved), 0) FROM devices"
        ).fetchone()
        fresh = self._db.execute(
            "SELECT COUNT(*) FROM devices WHERE first_seen >= ?",
            (_iso(moment - new_within),),
        ).fetchone()[0]
        return {
            "total": int(total),
            "online": int(online),
            "offline": int(total) - int(online),
            "new": int(fresh),
            "unapproved": int(unapproved),
        }

    # -- writing -----------------------------------------------------------

    def _log(self, device_id: int, kind: EventKind, detail: str, at: datetime) -> None:
        self._db.execute(
            "INSERT INTO events (device_id, kind, detail, at) VALUES (?, ?, ?, ?)",
            (device_id, kind.value, detail, _iso(at)),
        )

    def _row_for(self, observation: Observation) -> sqlite3.Row | None:
        """Find the stored row this observation belongs to, reconciling identities.

        A device first seen before its MAC was known is stored under its IP. Once
        the ARP cache catches up we recognise it, and the two records have to
        become one instead of the inventory showing the same device twice.
        """
        row: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM devices WHERE key = ?", (observation.key,)
        ).fetchone()
        if row or not observation.mac:
            return row

        ip_key = f"ip:{observation.ip}"
        stale = self._db.execute("SELECT * FROM devices WHERE key = ?", (ip_key,)).fetchone()
        if stale is None:
            return None
        # Promote the IP-keyed record to the MAC we have just learned.
        self._db.execute(
            "UPDATE devices SET key = ?, mac = ? WHERE id = ?",
            (observation.mac, observation.mac, stale["id"]),
        )
        promoted: sqlite3.Row | None = self._db.execute(
            "SELECT * FROM devices WHERE id = ?", (stale["id"],)
        ).fetchone()
        return promoted

    def record_scan(
        self,
        observations: Iterable[Observation],
        *,
        offline_after: int = 3,
        now: datetime | None = None,
    ) -> ScanOutcome:
        """Fold one scan into the inventory and report what changed."""
        moment = now or utcnow()
        stamp = _iso(moment)
        outcome = ScanOutcome()
        seen_ids: set[int] = set()

        for observation in observations:
            outcome.seen += 1
            row = self._row_for(observation)
            ports = _ports_to_text(observation.open_ports)

            if row is None:
                cursor = self._db.execute(
                    "INSERT INTO devices (key, ip, mac, hostname, vendor, open_ports,"
                    " first_seen, last_seen, online, misses)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)",
                    (
                        observation.key,
                        observation.ip,
                        observation.mac,
                        observation.hostname,
                        observation.vendor,
                        ports,
                        stamp,
                        stamp,
                    ),
                )
                device_id = int(cursor.lastrowid or 0)
                seen_ids.add(device_id)
                self._log(device_id, EventKind.DISCOVERED, observation.ip, moment)
                created = self.get(device_id)
                if created:
                    outcome.discovered.append(created)
                continue

            device_id = int(row["id"])
            seen_ids.add(device_id)
            self._note_changes(row, observation, moment, outcome)
            self._db.execute(
                "UPDATE devices SET ip = ?, hostname = COALESCE(?, hostname),"
                " vendor = COALESCE(?, vendor), open_ports = ?, last_seen = ?,"
                " online = 1, misses = 0 WHERE id = ?",
                (
                    observation.ip,
                    observation.hostname,
                    observation.vendor,
                    ports,
                    stamp,
                    device_id,
                ),
            )
            if not row["online"]:
                self._log(device_id, EventKind.ONLINE, observation.ip, moment)
                device = self.get(device_id)
                if device:
                    outcome.back_online.append(device)

        self._age_out(seen_ids, offline_after=offline_after, moment=moment, outcome=outcome)
        self._db.commit()
        return outcome

    def _note_changes(
        self,
        row: sqlite3.Row,
        observation: Observation,
        moment: datetime,
        outcome: ScanOutcome,
    ) -> None:
        """Record the differences between what we stored and what we just saw."""
        device_id = int(row["id"])
        changes: list[tuple[EventKind, str]] = []

        if row["ip"] != observation.ip:
            changes.append((EventKind.IP_CHANGED, f"{row['ip']} -> {observation.ip}"))
        if observation.hostname and row["hostname"] != observation.hostname:
            changes.append(
                (EventKind.HOSTNAME_CHANGED, f"{row['hostname'] or '-'} -> {observation.hostname}")
            )
        if observation.vendor and row["vendor"] and row["vendor"] != observation.vendor:
            changes.append((EventKind.VENDOR_CHANGED, f"{row['vendor']} -> {observation.vendor}"))

        before = set(_ports_from_text(row["open_ports"]))
        after = set(observation.open_ports)
        if before != after:
            opened = sorted(after - before)
            closed = sorted(before - after)
            parts = []
            if opened:
                parts.append("opened " + ", ".join(str(port) for port in opened))
            if closed:
                parts.append("closed " + ", ".join(str(port) for port in closed))
            changes.append((EventKind.PORTS_CHANGED, "; ".join(parts)))

        if not changes:
            return
        device = self.get(device_id)
        for kind, detail in changes:
            self._log(device_id, kind, detail, moment)
            if device:
                outcome.changed.append((device, kind, detail))

    def _age_out(
        self,
        seen_ids: set[int],
        *,
        offline_after: int,
        moment: datetime,
        outcome: ScanOutcome,
    ) -> None:
        """Count a miss for everything we did not see, and retire the persistent ones.

        A device is not declared offline on the first miss. Phones sleep, wifi
        drops a frame, a scan races a DHCP renewal: one silent round means nothing,
        several in a row mean the device really went away.
        """
        rows = self._db.execute("SELECT * FROM devices WHERE online = 1").fetchall()
        for row in rows:
            device_id = int(row["id"])
            if device_id in seen_ids:
                continue
            misses = int(row["misses"]) + 1
            if misses >= offline_after:
                self._db.execute(
                    "UPDATE devices SET online = 0, misses = ? WHERE id = ?", (misses, device_id)
                )
                self._log(device_id, EventKind.OFFLINE, f"missed {misses} scans", moment)
                device = self.get(device_id)
                if device:
                    outcome.went_offline.append(device)
            else:
                self._db.execute("UPDATE devices SET misses = ? WHERE id = ?", (misses, device_id))

    def record_scan_run(
        self,
        *,
        networks: Sequence[str],
        probed: int,
        found: int,
        duration: float,
        now: datetime | None = None,
    ) -> None:
        """Keep a line about the scan itself, for the history and for statistics."""
        self._db.execute(
            "INSERT INTO scans (started_at, networks, probed, found, duration)"
            " VALUES (?, ?, ?, ?, ?)",
            (_iso(now or utcnow()), json.dumps(list(networks)), probed, found, duration),
        )
        self._db.commit()

    def set_label(self, device_id: int, label: str | None) -> None:
        self._db.execute("UPDATE devices SET label = ? WHERE id = ?", (label, device_id))
        self._log(device_id, EventKind.RENAMED, label or "(cleared)", utcnow())
        self._db.commit()

    def set_notes(self, device_id: int, notes: str | None) -> None:
        self._db.execute("UPDATE devices SET notes = ? WHERE id = ?", (notes, device_id))
        self._db.commit()

    def set_approved(self, device_id: int, approved: bool) -> None:
        self._db.execute("UPDATE devices SET approved = ? WHERE id = ?", (int(approved), device_id))
        self._log(
            device_id,
            EventKind.APPROVED,
            "approved" if approved else "approval withdrawn",
            utcnow(),
        )
        self._db.commit()

    def forget(self, device_id: int) -> None:
        """Remove a device and its history from the inventory."""
        self._db.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        self._db.commit()


def _address_order(device: Device) -> tuple[int, ...]:
    """Sort devices the way a network is read: by address, numerically."""
    try:
        return tuple(int(part) for part in device.ip.split("."))
    except ValueError:
        return (999, 999, 999, 999)
