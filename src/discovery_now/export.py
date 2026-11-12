"""Turning the inventory into a file someone else can open.

Two formats: CSV, which a spreadsheet opens directly, and JSON, which a script
reads. Both carry the same fields, built from the same source as ``--json`` on the
other commands, so a device looks the same wherever it is shown.

An inventory is a record of a real home: it holds hardware addresses, device names
and notes that identify people. Exporting is the moment it can leave the machine,
so this module is where that is made safe: a redacted mode for sharing, and
neutralized cells so a hostile device name cannot turn a CSV into a formula.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from .models import Device
from .render import device_as_dict


class ExportFormat(StrEnum):
    """The file formats an export can be written in."""

    CSV = "csv"
    JSON = "json"


#: Column order of a CSV export, and the key order of a JSON one.
COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "ip",
    "mac",
    "hostname",
    "vendor",
    "kind",
    "label",
    "notes",
    "open_ports",
    "first_seen",
    "last_seen",
    "online",
    "approved",
    "is_new",
)

#: A spreadsheet treats a cell that starts with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def redact_mac(mac: str | None) -> str | None:
    """Hide the part of a MAC that identifies one physical device.

    The first three bytes name the maker and are shared by millions of devices, so
    they stay. The last three are what makes the address unique, so they go.
    """
    if not mac:
        return mac
    parts = mac.split(":")
    if len(parts) != 6:
        return "xx:xx:xx:xx:xx:xx"
    return ":".join([*parts[:3], "xx", "xx", "xx"])


def _redacted(row: dict[str, Any]) -> dict[str, Any]:
    """The same row with everything that names a person or a unit removed.

    The name is rebuilt from the device number, because the usual name is the
    label or the hostname, and both are exactly what is being hidden.
    """
    hidden = dict(row)
    hidden["mac"] = redact_mac(row["mac"])
    hidden["hostname"] = None
    hidden["label"] = None
    hidden["notes"] = None
    hidden["name"] = f"device-{row['id']}"
    return hidden


def rows(
    devices: Sequence[Device],
    *,
    new_within: timedelta,
    redact: bool = False,
) -> list[dict[str, Any]]:
    """The devices as plain rows, in the column order above."""
    result: list[dict[str, Any]] = []
    for device in devices:
        row = device_as_dict(device, new_within=new_within)
        if redact:
            row = _redacted(row)
        result.append({column: row[column] for column in COLUMNS})
    return result


def neutralize(value: str) -> str:
    """Stop a spreadsheet from running a cell as a formula.

    A hostname is chosen by the device that announces it, so on a hostile network
    it can be ``=HYPERLINK(...)``. A leading apostrophe makes every spreadsheet
    show the text instead of evaluating it.
    """
    return "'" + value if value.startswith(_FORMULA_STARTS) else value


def _cell(value: Any) -> str:
    """One value as the text of a CSV cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    return neutralize(str(value))


def to_csv(table: Sequence[dict[str, Any]]) -> str:
    """The rows as CSV text, header included."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in table:
        writer.writerow([_cell(row[column]) for column in COLUMNS])
    return buffer.getvalue()


def to_json(table: Sequence[dict[str, Any]]) -> str:
    """The rows as a JSON array."""
    return json.dumps(list(table), indent=2, ensure_ascii=False) + "\n"


def render(table: Sequence[dict[str, Any]], fmt: ExportFormat) -> str:
    """The rows in the requested format."""
    return to_csv(table) if fmt is ExportFormat.CSV else to_json(table)


def write(path: Path, text: str, fmt: ExportFormat) -> None:
    """Save rendered rows to a file, creating its folder if needed.

    A byte-order mark makes Excel on Windows read accents correctly in a CSV; JSON
    has none.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if fmt is ExportFormat.CSV else "utf-8"
    with path.open("w", encoding=encoding, newline="") as handle:
        handle.write(text)
