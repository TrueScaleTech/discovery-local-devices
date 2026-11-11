"""The two ways Discovery Now asks "is anything at this address?".

Neither needs administrator rights, which is the point. A tool that only works
elevated is a tool people stop running. ICMP goes through the system's own ``ping``
command, and the TCP probe is an ordinary connection attempt.
"""

from __future__ import annotations

import math
import platform
import re
import socket
import subprocess
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

#: Ports used only to decide whether a silent host exists at all. Kept very short:
#: this runs against every address in the subnet, most of which are empty.
LIVENESS_PORTS: tuple[int, ...] = (80, 443, 22, 445, 62078)

_TTL_RE = re.compile(r"ttl\s*[=:]\s*\d+", re.IGNORECASE)
_RTT_RE = re.compile(r"[<=]\s*([\d.,]+)\s*ms", re.IGNORECASE)

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class PingResult:
    """What a single ping told us."""

    alive: bool
    rtt_ms: float | None = None


@dataclass(frozen=True, slots=True)
class PortResult:
    """What knocking on a host's ports told us."""

    open_ports: tuple[int, ...] = ()
    #: True when something answered at all, including an outright refusal. A
    #: refused connection is proof that a host is there: only a live IP stack
    #: bothers to say no.
    responded: bool = False


def _no_window_flags() -> int:
    """Keep Windows from flashing a console for every ping."""
    if platform.system() == "Windows":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _ping_command(ip: str, timeout: float) -> list[str]:
    """The platform's way of sending exactly one echo request."""
    system = platform.system()
    if system == "Windows":
        return ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
    if system == "Darwin":
        return ["ping", "-c", "1", "-n", "-W", str(int(timeout * 1000)), ip]
    # Linux and the BSDs: -W counts whole seconds, and zero would mean "no wait".
    return ["ping", "-c", "1", "-n", "-W", str(max(1, math.ceil(timeout))), ip]


def parse_ping_output(returncode: int, output: str) -> PingResult:
    """Decide whether a ``ping`` run actually reached the device.

    The exit code alone is not enough: a router answering "destination host
    unreachable" on behalf of an absent device makes ``ping`` succeed on Windows.
    A TTL field in the output is what distinguishes a reply from the device
    itself, and it is one of the few parts of that output no locale translates.
    The round-trip time is read the same way, by shape rather than by wording,
    so "time=4ms" and "durata=4ms" both work.
    """
    if returncode != 0 or not _TTL_RE.search(output):
        return PingResult(alive=False)
    rtt: float | None = None
    match = _RTT_RE.search(output)
    if match:
        try:
            rtt = float(match.group(1).replace(",", "."))
        except ValueError:
            rtt = None
    return PingResult(alive=True, rtt_ms=rtt)


def ping(ip: str, *, timeout: float = 1.0) -> PingResult:
    """Send one echo request and read the answer."""
    try:
        # Fixed argument list, no shell: the address comes from our own target list.
        completed = subprocess.run(
            _ping_command(ip, timeout),
            capture_output=True,
            timeout=timeout + 2.0,
            check=False,
            creationflags=_no_window_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return PingResult(alive=False)

    return parse_ping_output(
        completed.returncode, completed.stdout.decode("utf-8", errors="replace")
    )


def ping_sweep(
    ips: Sequence[str],
    *,
    timeout: float = 1.0,
    workers: int = 128,
    progress: ProgressCallback | None = None,
) -> dict[str, PingResult]:
    """Ping every address in parallel and return the ones that answered."""
    results: dict[str, PingResult] = {}
    if not ips:
        return results
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(ips)))) as pool:
        futures = {pool.submit(ping, ip, timeout=timeout): ip for ip in ips}
        for future in as_completed(futures):
            ip = futures[future]
            result = future.result()
            if result.alive:
                results[ip] = result
            done += 1
            if progress:
                progress(done, len(ips))
    return results


def probe_port(ip: str, port: int, *, timeout: float = 1.0) -> str:
    """Try one TCP port. Returns ``open``, ``refused`` or ``silent``."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return "open"
    except ConnectionRefusedError:
        return "refused"
    except (TimeoutError, OSError):
        return "silent"


def tcp_sweep(
    ips: Iterable[str],
    ports: Sequence[int],
    *,
    timeout: float = 1.0,
    workers: int = 128,
    progress: ProgressCallback | None = None,
) -> dict[str, PortResult]:
    """Knock on a set of ports for every address, in parallel.

    Every address-port pair is one task rather than one task per address, so a
    subnet full of silent addresses does not leave most threads idle waiting on
    the few hosts that are there.
    """
    targets = list(ips)
    results: dict[str, PortResult] = {}
    if not targets or not ports:
        return results

    pairs = [(ip, port) for ip in targets for port in ports]
    open_by_ip: dict[str, list[int]] = {}
    responded: set[str] = set()
    done = 0

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pairs)))) as pool:
        futures = {
            pool.submit(probe_port, ip, port, timeout=timeout): (ip, port) for ip, port in pairs
        }
        for future in as_completed(futures):
            ip, port = futures[future]
            outcome = future.result()
            if outcome == "open":
                open_by_ip.setdefault(ip, []).append(port)
                responded.add(ip)
            elif outcome == "refused":
                responded.add(ip)
            done += 1
            if progress:
                progress(done, len(pairs))

    for ip in responded:
        results[ip] = PortResult(
            open_ports=tuple(sorted(open_by_ip.get(ip, ()))),
            responded=True,
        )
    return results
