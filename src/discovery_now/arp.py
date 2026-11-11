"""Reading the system's ARP cache to put a MAC address on an IP.

Discovery Now does not send its own ARP requests, which would need raw sockets and
therefore administrator rights. It probes the subnet first and then reads the cache
the operating system filled while those probes went out. The result is the same
mapping, obtained without asking the user for privileges.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from .net import find_ipv4, normalize_mac

#: Linux keeps the cache in a text file; reading it beats spawning a process.
_PROC_ARP = Path("/proc/net/arp")

#: Keeps a stuck command from hanging a scan.
_COMMAND_TIMEOUT = 5.0


def _run(command: list[str]) -> str | None:
    """Run a command and return its output, or None if it is unavailable."""
    flags = 0
    if platform.system() == "Windows":
        # Without this every probe would flash a console window, which would make
        # the desktop app unusable.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        # Fixed argument lists, never a shell string: nothing user-supplied reaches here.
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=_COMMAND_TIMEOUT,
            check=False,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Console output is localized and not always UTF-8, and we only read the
    # numbers out of it, so undecodable bytes are replaced rather than fatal.
    return completed.stdout.decode("utf-8", errors="replace")


def parse_table(text: str) -> dict[str, str]:
    """Pull IP and MAC pairs out of a table, whatever words surround them.

    The output of ``arp`` and ``ip neigh`` is translated on localized systems and
    its columns differ between platforms, but an IPv4 address and a MAC address
    look the same everywhere. Matching on their shape rather than on column
    positions is what makes this work on an Italian Windows and an English Linux
    without two parsers.
    """
    table: dict[str, str] = {}
    for line in text.splitlines():
        ip = find_ipv4(line)
        mac = normalize_mac(line)
        if ip and mac:
            table[ip] = mac
    return table


def _read_proc() -> dict[str, str]:
    """Read the Linux ARP cache from /proc."""
    try:
        text = _PROC_ARP.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    # The first line is the header; parse_table ignores it since it holds no address.
    return parse_table(text)


def arp_table() -> dict[str, str]:
    """The current IP to MAC mapping known to this machine.

    Sources are tried cheapest first and merged, because on Linux ``ip neigh`` can
    hold entries that /proc/net/arp has already aged out, and the other way round.
    """
    system = platform.system()
    table: dict[str, str] = {}

    if system == "Linux":
        table.update(_read_proc())
        for command in (["ip", "-4", "neigh", "show"], ["arp", "-an"]):
            output = _run(command)
            if output:
                table.update(parse_table(output))
        return table

    if system == "Windows":
        output = _run(["arp", "-a"])
        return parse_table(output) if output else {}

    # macOS and the BSDs.
    output = _run(["arp", "-an"])
    return parse_table(output) if output else {}
