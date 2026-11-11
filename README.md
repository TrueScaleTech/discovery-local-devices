# Discovery Now

Find out what is actually connected to your network, keep a record of it, and get
told when something changes.

Discovery Now scans a subnet you own, builds an inventory of every device it
finds, and then keeps watching: it remembers when each device first appeared,
flags the ones that are new, and reports when something goes offline, changes
address, or opens a port it did not have yesterday.

It runs as a command-line tool today. A desktop application for Windows and Linux
is next, built on the same engine.

> **Status: early development (v0.1).** The discovery engine, the inventory and
> the CLI work. The desktop app, notifications and the security checks listed in
> the roadmap are not built yet.

## No administrator rights needed

Most discovery tools ask for root or administrator because they craft raw ARP and
ICMP packets themselves. Discovery Now does not:

- it sends ordinary pings through the system's own `ping` command, and makes
  ordinary TCP connections, neither of which is privileged;
- it then reads the ARP cache that those probes just caused the operating system
  to fill, which is where the MAC addresses come from;
- it adds this machine's own interfaces from the system tables, because a machine
  never ARPs for itself.

The result is the same picture, from a normal user account, on Windows and on
Linux.

## Install

Python 3.11 or newer.

```bash
git clone https://github.com/TrueScaleTech/discovery-local-devices.git
cd discovery-local-devices
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .
```

## Quick start

```bash
# Which subnets would be scanned by default?
discovery-now interfaces

# Scan them, and remember what was found
discovery-now scan

# Read the hardware vendor out of every MAC address (optional, ~3 MB, once)
discovery-now oui update

# What is on the network?
discovery-now devices list
```

A scan looks like this (example data):

```
                    7 device(s) on 192.168.1.0/24 (254 addresses probed in 15.4s)
┌──────────────┬───────────────────┬──────────────┬─────────────┬───────────────────┬──────────┐
│ Address      │ MAC               │ Name         │ Vendor      │ Kind              │ Ports    │
├──────────────┼───────────────────┼──────────────┼─────────────┼───────────────────┼──────────┤
│ 192.168.1.1  │ 00:04:0e:00:00:01 │ router.home  │ AVM         │ router or gateway │ 53, 80   │
│ 192.168.1.14 │ b8:27:eb:00:00:02 │ pi-hole      │ Raspberry…  │ single-board com… │ 22, 53   │
│ 192.168.1.22 │ 00:80:77:00:00:03 │ printer      │ Brother     │ printer           │ 631,9100 │
│ 192.168.1.31 │ 24:0a:c4:00:00:04 │ -            │ Espressif   │ smart device      │ 80       │
│ 192.168.1.44 │ 00:11:32:00:00:05 │ nas.home     │ Synology    │ NAS               │ 445,5000 │
│ 192.168.1.60 │ ae:11:22:00:00:06 │ phone.home   │ -           │ -                 │ -        │
│ 192.168.1.88 │ 3c:97:0e:00:00:07 │ desktop.home │ Intel       │ file sharing host │ 139, 445 │
└──────────────┴───────────────────┴──────────────┴─────────────┴───────────────────┴──────────┘

new      192.168.1.31  Espressif
```

That phone has no vendor on purpose: its MAC is randomized, which Discovery Now
recognises rather than guessing wrongly.

## Keeping watch

```bash
discovery-now watch
```

It scans every five minutes and prints only what changed:

```
2026-01-14 21:05  7 online  (15.1s)
new      192.168.1.31  Espressif
offline  192.168.1.22  printer
```

A device is not called offline the first time it misses a scan. Phones sleep and
wifi drops frames; three missed rounds in a row mean something, one does not. The
threshold is yours to set.

## Telling your devices apart

A fresh inventory is a list of strangers. These turn it into something you can
read at a glance, and keep a new arrival from hiding in a crowd of known devices:

```bash
discovery-now devices rename 192.168.1.44 "NAS"
discovery-now devices note 192.168.1.31 "Smart plug, living room"
discovery-now devices approve NAS
discovery-now devices list --unapproved
```

Approving is a statement that a device belongs here. Everything you have not
approved stays flagged, so "I have never looked at this" never looks the same as
"this is mine".

## Commands

| Command | What it does |
| --- | --- |
| `scan` | Scan once and record what is there |
| `watch` | Keep scanning on a schedule, reporting changes |
| `status` | Counts: known, online, offline, new, not approved |
| `interfaces` | The local interfaces and what would be scanned |
| `events` | Recent history across all devices |
| `devices list` | The inventory, with `--online`, `--new`, `--unapproved` |
| `devices show` | Everything known about one device, with its history |
| `devices rename` / `note` / `approve` / `forget` | Annotate the inventory |
| `oui update` / `info` | Manage the hardware vendor list |
| `config init` / `show` / `path` | The configuration file |

Every command that shows something accepts `--json`, so the same tool serves a
person reading a table and a script reading a pipe. `scan --fail-on-new` exits
with status 3 when an unknown device appears, which is enough to drive a cron job
or a CI step.

## Configuration

```bash
discovery-now config init   # writes a commented file
discovery-now config path   # says where it is
```

Worth knowing about:

| Setting | Default | Meaning |
| --- | --- | --- |
| `subnets` | auto | Which subnets to scan. Empty means the active interfaces |
| `offline_after` | 3 | Missed scans before a device counts as offline |
| `new_device_days` | 7 | How long a device keeps its "new" badge |
| `watch_interval` | 300 | Seconds between scans in watch mode |
| `timeout` / `workers` | 1.0 / 128 | How patient and how parallel the probes are |
| `allow_public_ranges` | false | Refuse anything outside private address space |

## Where your data lives

One SQLite file, in the per-user data directory that `discovery-now status`
prints. It holds MAC addresses, hostnames and the history of your network, so
treat it as personal data: it never leaves the machine, there is no telemetry and
no cloud component, and the repository is set up to make committing it difficult.

## Scope

Discovery Now is for networks you own or are authorized to assess. It identifies
hosts and the services they expose; it never authenticates, never exploits, and
never changes anything on the devices it finds. Addresses outside private ranges
are refused unless you turn that off deliberately. See [SECURITY.md](SECURITY.md).

## Roadmap

- [x] Discovery engine, inventory, online/offline monitoring, CLI
- [ ] Notifications: new device, device offline, webhook and desktop
- [ ] Desktop app for Windows and Linux
- [ ] Security checks: MAC and IP changes, ARP anomalies, rogue DHCP, risky ports
- [ ] Packaged builds and a tagged release

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest
```

The test suite needs no network: it parses captured command output, talks to
loopback sockets, and runs the inventory against temporary databases.

## License

[MIT](LICENSE)
