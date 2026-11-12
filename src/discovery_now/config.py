"""Where Discovery Now keeps its settings and its database, and what the settings are."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import PlatformDirs

from . import PACKAGE_NAME

_DIRS = PlatformDirs(appname=PACKAGE_NAME, appauthor=False, roaming=False)

#: Ports worth knocking on. Short on purpose: this is a liveness check and a rough
#: "what kind of device is this", not a port scan. Anything longer would be slower
#: and would start to look like one.
DEFAULT_PORTS: tuple[int, ...] = (
    22,  # ssh
    53,  # dns: routers and pi-holes
    80,  # http
    139,  # netbios session: windows
    443,  # https
    445,  # smb: windows, nas
    515,  # printers
    554,  # rtsp: cameras
    631,  # ipp: printers
    1883,  # mqtt: home automation
    3389,  # rdp
    5000,  # synology dsm, upnp, flask-ish dashboards
    8006,  # proxmox
    8080,  # http alternate
    8443,  # https alternate
    9100,  # raw printing
    62078,  # iphone sync
)


def config_dir() -> Path:
    """Directory holding the configuration file."""
    return Path(os.environ.get("DISCOVERY_NOW_CONFIG_DIR") or _DIRS.user_config_dir)


def data_dir() -> Path:
    """Directory holding the inventory database."""
    return Path(os.environ.get("DISCOVERY_NOW_DATA_DIR") or _DIRS.user_data_dir)


def config_path() -> Path:
    """Full path of the configuration file."""
    return config_dir() / "config.toml"


def database_path() -> Path:
    """Full path of the inventory database."""
    return data_dir() / "inventory.db"


@dataclass(slots=True)
class Settings:
    """Everything the user can tune, with defaults that are safe on any network."""

    #: Subnets to scan. Empty means "work it out from the active interfaces".
    subnets: list[str] = field(default_factory=list)
    #: Scanning outside RFC1918 / RFC4193 space is refused unless this is turned on.
    allow_public_ranges: bool = False
    #: Refuse to expand anything larger than this, so a stray /8 cannot start 16M probes.
    max_hosts_per_subnet: int = 4096
    #: Parallel probes. Higher is faster and noisier; 128 keeps a home network calm.
    workers: int = 128
    #: Seconds to wait for a single probe.
    timeout: float = 1.0
    #: Ports used for the TCP fallback probe.
    ports: list[int] = field(default_factory=lambda: list(DEFAULT_PORTS))
    #: Look up names for the hosts that answered.
    resolve_hostnames: bool = True
    #: Consecutive misses before a device is called offline. Phones sleep; one
    #: missed scan means nothing, three in a row means something.
    offline_after: int = 3
    #: How long a device keeps its "new" badge.
    new_device_days: int = 7
    #: Seconds between scans in watch mode.
    watch_interval: int = 300

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Read the configuration file, falling back to defaults when it is absent."""
        target = path or config_path()
        if not target.is_file():
            return cls()
        with target.open("rb") as handle:
            raw: dict[str, Any] = tomllib.load(handle)
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> Settings:
        """Build settings from parsed TOML, ignoring keys we do not know.

        Unknown keys are skipped rather than rejected so that a config file written
        by a newer version still starts an older one.
        """
        known = {f.name for f in cls.__dataclass_fields__.values()}
        scan = raw.get("scan", {})
        monitor = raw.get("monitor", {})
        merged = {**scan, **monitor}
        return cls(**{key: value for key, value in merged.items() if key in known})

    def write_default(self, path: Path | None = None) -> Path:
        """Write a commented configuration file. Never overwrites an existing one."""
        target = path or config_path()
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
        return target


DEFAULT_CONFIG_TEMPLATE = """\
# Discovery Now configuration.
# Every value below is the default; uncomment a line to change it.

[scan]
# Subnets to scan. Leave empty to use the subnets of the active interfaces.
# subnets = ["192.168.1.0/24"]

# Discovery Now refuses to scan anything outside private address space. Turning
# this on means you are stating you are authorized to scan the targets you set.
# allow_public_ranges = false

# max_hosts_per_subnet = 4096
# workers = 128
# timeout = 1.0
# resolve_hostnames = true

# Ports used to find hosts that ignore ping, and to guess what a device is.
# ports = [22, 53, 80, 139, 443, 445, 515, 554, 631, 1883,
#          3389, 5000, 8006, 8080, 8443, 9100, 62078]

[monitor]
# Consecutive missed scans before a device counts as offline.
# offline_after = 3

# How many days a device keeps its "new" badge.
# new_device_days = 7

# Seconds between scans when running `discoverynow watch`.
# watch_interval = 300
"""
