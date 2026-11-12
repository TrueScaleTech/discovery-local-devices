"""Turning a MAC address into the name of the company that made the hardware.

The first three octets of a MAC are the OUI, assigned by the IEEE. Resolving them
is what turns a list of numbers into a list you can read: "Espressif" is a smart
plug, "Raspberry Pi" is the thing in the cupboard, and a vendor you do not expect
is worth a second look.

The list ships inside the package and is read from there. Discovery Now never
fetches it, or anything else, from the internet.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

_FALLBACK_RESOURCE = "oui_fallback.csv"


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
    """The built-in vendor table, read once."""
    bundled = resources.files(f"{__package__}.data").joinpath(_FALLBACK_RESOURCE)
    return _read_table(bundled.read_text(encoding="utf-8"))


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
    """How many prefixes are loaded."""
    return len(_table())
