"""Running one scan: from a subnet to a list of observations.

The order of the steps matters. Probing comes first and reading the ARP cache
comes after, because the probes are what make the operating system fill that cache
in the first place.
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import arp, net, oui, probes
from .config import Settings
from .models import Observation

#: Called with the name of the current stage, work done and work total.
ProgressCallback = Callable[[str, int, int], None]

STAGE_PING = "ping sweep"
STAGE_TCP = "tcp probe"
STAGE_PORTS = "service probe"
STAGE_NAMES = "name lookup"


@dataclass(slots=True)
class ScanReport:
    """Everything one scan found, plus what it took to find it."""

    observations: list[Observation] = field(default_factory=list)
    networks: list[ipaddress.IPv4Network] = field(default_factory=list)
    addresses_probed: int = 0
    duration: float = 0.0

    @property
    def found(self) -> int:
        """How many devices answered."""
        return len(self.observations)


def _liveness_timeout(timeout: float) -> float:
    """A shorter wait for the sweep that runs against every empty address.

    The full timeout is right for a host we believe exists; spending it on each of
    two hundred empty addresses is just waiting.
    """
    return max(0.3, timeout / 2)


def run_scan(
    settings: Settings,
    *,
    networks: list[ipaddress.IPv4Network] | None = None,
    progress: ProgressCallback | None = None,
) -> ScanReport:
    """Scan the configured subnets and return what answered.

    Raises :class:`discovery_now.net.TargetError` if a target is not one we are
    willing to scan.
    """
    started = time.monotonic()
    targets = networks or net.resolve_targets(
        settings.subnets,
        allow_public=settings.allow_public_ranges,
        max_hosts=settings.max_hosts_per_subnet,
    )

    addresses: list[str] = []
    for network in targets:
        addresses.extend(net.hosts(network))

    def stage(name: str) -> probes.ProgressCallback | None:
        if progress is None:
            return None
        return lambda done, total: progress(name, done, total)

    # 1. Ping everything. Most devices answer, and it costs one packet each.
    pings = probes.ping_sweep(
        addresses,
        timeout=settings.timeout,
        workers=settings.workers,
        progress=stage(STAGE_PING),
    )

    # 2. Many devices are configured not to answer ping. Knock on a few ports to
    #    find the ones that stayed silent.
    silent = [ip for ip in addresses if ip not in pings]
    tcp_alive = probes.tcp_sweep(
        silent,
        probes.LIVENESS_PORTS,
        timeout=_liveness_timeout(settings.timeout),
        workers=settings.workers,
        progress=stage(STAGE_TCP),
    )

    alive = sorted(
        set(pings) | set(tcp_alive),
        key=lambda ip: tuple(int(part) for part in ip.split(".")),
    )

    # 3. Now that we know who is there, look at what they expose. This runs
    #    against a handful of hosts, so the full port list is affordable.
    services = probes.tcp_sweep(
        alive,
        settings.ports,
        timeout=settings.timeout,
        workers=settings.workers,
        progress=stage(STAGE_PORTS),
    )

    # 4. The probes above have populated the system's ARP cache, so the MAC
    #    addresses are there for the reading. This machine is not in its own
    #    cache, so its interfaces are added from the system's own tables.
    macs = {**arp.arp_table(), **net.local_macs()}

    # 5. Names, for the devices that have one.
    hostnames = _resolve_names(
        alive,
        enabled=settings.resolve_hostnames,
        timeout=settings.timeout,
        workers=settings.workers,
        progress=stage(STAGE_NAMES),
    )

    observations: list[Observation] = []
    for ip in alive:
        mac = macs.get(ip)
        methods: set[str] = set()
        if ip in pings:
            methods.add("icmp")
        if ip in tcp_alive or ip in services:
            methods.add("tcp")
        if mac:
            methods.add("arp")
        ping_result = pings.get(ip)
        observations.append(
            Observation(
                ip=ip,
                mac=mac,
                hostname=hostnames.get(ip),
                vendor=oui.lookup(mac),
                open_ports=services.get(ip, probes.PortResult()).open_ports,
                methods=frozenset(methods),
                rtt_ms=ping_result.rtt_ms if ping_result else None,
            )
        )

    return ScanReport(
        observations=observations,
        networks=list(targets),
        addresses_probed=len(addresses),
        duration=time.monotonic() - started,
    )


def _resolve_names(
    ips: list[str],
    *,
    enabled: bool,
    timeout: float,
    workers: int,
    progress: probes.ProgressCallback | None = None,
) -> dict[str, str]:
    """Reverse-resolve the live addresses, in parallel and best effort."""
    if not enabled or not ips:
        return {}
    names: dict[str, str] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(ips)))) as pool:
        lookups = pool.map(lambda address: net.reverse_dns(address, timeout=timeout), ips)
        for ip, name in zip(ips, lookups, strict=True):
            if name:
                names[ip] = name
            done += 1
            if progress:
                progress(done, len(ips))
    return names
