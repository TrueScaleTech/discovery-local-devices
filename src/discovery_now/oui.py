"""Turning a MAC address into the name of the company that made the hardware.

The first three octets of a MAC are the OUI, assigned by the IEEE. Resolving them
is what turns a list of numbers into a list you can read: "Espressif" is a smart
plug, "Raspberry Pi" is the thing in the cupboard, and a vendor you do not expect
is worth a second look.

A short built-in list ships with the package. The full IEEE registry is about
three megabytes and changes constantly, so it is downloaded on request into the
user's data directory rather than committed to this repository.
"""

from __future__ import annotations

import contextlib
import csv
import io
import urllib.request
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .config import data_dir

#: The IEEE MA-L registry: the large assignments, which is what consumer kit uses.
IEEE_OUI_URL = "https://standards-oui.ieee.org/oui/oui.csv"

_FALLBACK_RESOURCE = "oui_fallback.csv"
_CACHE_FILENAME = "oui.csv"
_DOWNLOAD_TIMEOUT = 60.0
#: Refuse an implausible download rather than filling the disk: the registry is
#: a few megabytes, so anything past this is not the file we asked for.
_MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024


def oui_cache_path() -> Path:
    """Where the downloaded registry is kept."""
    return data_dir() / _CACHE_FILENAME


def _prefix(mac: str) -> str:
    """The OUI of a normalized MAC, as six uppercase hex digits."""
    return mac.replace(":", "").replace("-", "").upper()[:6]


def is_locally_administered(mac: str) -> bool:
    """True when the MAC was made up by software rather than assigned to hardware.

    Phones and laptops randomize their MAC on untrusted networks, and virtual
    interfaces invent one. Such an address has no vendor to look up, and it also
    means the device may appear under a new identity next time it connects.
    """
    try:
        first = int(_prefix(mac)[:2], 16)
    except ValueError:
        return False
    return bool(first & 0b10)


def _read_table(text: str) -> dict[str, str]:
    """Read our compact ``prefix,vendor`` format, skipping comments."""
    table: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        prefix, _, vendor = line.partition(",")
        prefix = prefix.strip().upper()
        vendor = vendor.strip()
        if len(prefix) == 6 and vendor:
            table[prefix] = vendor
    return table


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    """The vendor table: the downloaded registry if present, the built-in list otherwise.

    Both are merged, with the download winning, so a prefix we ship stays available
    even if the registry format ever surprises us.
    """
    bundled = resources.files(f"{__package__}.data").joinpath(_FALLBACK_RESOURCE)
    table = _read_table(bundled.read_text(encoding="utf-8"))
    cached = oui_cache_path()
    if cached.is_file():
        with contextlib.suppress(OSError):
            table.update(_read_table(cached.read_text(encoding="utf-8", errors="replace")))
    return table


def reset_cache() -> None:
    """Forget the loaded vendor table, so the next lookup reads it again."""
    _table.cache_clear()


def lookup(mac: str | None) -> str | None:
    """The vendor behind a MAC address, or None when it is unknown."""
    if not mac:
        return None
    if is_locally_administered(mac):
        return None
    return _table().get(_prefix(mac))


def table_size() -> int:
    """How many prefixes are currently loaded."""
    return len(_table())


def using_full_registry() -> bool:
    """True when the downloaded IEEE registry is in use."""
    return oui_cache_path().is_file()


def update(url: str = IEEE_OUI_URL, *, destination: Path | None = None) -> int:
    """Download the IEEE registry and store it in our compact format.

    Returns the number of prefixes written. The IEEE file is a CSV whose rows look
    like ``MA-L,001122,Acme Corp,address``; only the assignment and the name are
    kept, which turns megabytes of text into a file that loads instantly.
    """
    if not url.startswith("https://"):
        raise ValueError("The vendor registry must be downloaded over HTTPS.")
    target = destination or oui_cache_path()
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        headers={"User-Agent": "discovery-now/0.1 (+https://github.com/TrueScaleTech)"},
    )
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:  # noqa: S310
        payload = response.read(_MAX_DOWNLOAD_BYTES + 1)
    if len(payload) > _MAX_DOWNLOAD_BYTES:
        raise ValueError("The vendor registry download was larger than expected; refusing it.")

    rows = csv.reader(io.StringIO(payload.decode("utf-8", errors="replace")))
    entries: dict[str, str] = {}
    for row in rows:
        if len(row) < 3:
            continue
        prefix = row[1].strip().upper()
        vendor = row[2].strip().strip('"')
        if len(prefix) == 6 and vendor and all(c in "0123456789ABCDEF" for c in prefix):
            entries[prefix] = vendor
    if not entries:
        raise ValueError("The downloaded vendor registry held no usable entries.")

    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# IEEE OUI registry fetched from {url}"]
    lines += [f"{prefix},{vendor}" for prefix, vendor in sorted(entries.items())]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reset_cache()
    return len(entries)
