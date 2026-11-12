# Discovery Now

Find out what is actually connected to your network, keep a record of it, and get
told when something changes.

Discovery Now scans a subnet you own, builds an inventory of every device it
finds, and then keeps watching: it remembers when each device first appeared,
flags the ones that are new, and reports when something goes offline, changes
address, or opens a port it did not have yesterday.

It runs as a command-line tool and as a desktop app, both built on the same
engine and sharing the same inventory.

> **Status: early development (v0.1).** The discovery engine, the inventory, the
> CLI and a first version of the desktop app (tested on Windows) work. Linux
> packaging, richer notifications and the security checks listed in the roadmap
> are not built yet.

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

For the desktop app, install the optional `gui` extra, which adds PySide6 (Qt):

```bash
pip install -e ".[gui]"
```

## Quick start

```bash
# Which subnets would be scanned by default?
discoverynow interfaces

# Scan them, and remember what was found
discoverynow scan

# What is on the network?
discoverynow devices list

# Or skip the typing: browse every command and its options in a menu
discoverynow menu

# Or use the window
discoverynow gui
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
│ 192.168.1.60 │ ae:11:22:00:00:06 │ phone.home   │ -           │ phone             │ -        │
│ 192.168.1.88 │ 3c:97:0e:00:00:07 │ desktop.home │ Intel       │ computer          │ 139, 445 │
└──────────────┴───────────────────┴──────────────┴─────────────┴───────────────────┴──────────┘

new      192.168.1.31  Espressif
```

That phone has no vendor on purpose: its MAC is randomized, which Discovery Now
recognises rather than guessing wrongly. Its kind comes from its name instead.

### How the Kind column is worked out

The Kind is a guess, shown as one, made from whatever the device gives away. The
clues are weighed from the strongest to the weakest:

1. **The ports it answers on**: a printing port is a printer, DNS plus a web page is
   a router, and so on.
2. **The name it gives itself**: `phone`, `iphone`, `tablet`, `laptop`, `macbook`,
   `desktop`, `printer`, `camera`, `nas`, `tv` and a few more. Longer words are found
   anywhere in the name (`ana-sphone` is a phone); short ones only as a whole word,
   so `canasta` is not a NAS. A Windows `DESKTOP-xxxx` name only says *computer*,
   because Windows gives that name to laptops too.
3. **The company that made its network chip**, from the built-in list.
4. **The shape of what it exposes**: file sharing, SSH, a web interface.
5. **Last of all**, if none of that says anything and the device chose its own MAC
   address, the Kind reads **Private address auto-assigned**. It describes the
   address, which is all that is known, rather than guessing a type.

A device with none of these clues stays *unknown*. The Kind is only a hint: to keep
track of a device whatever it is called, give it a name of your own with
`discoverynow devices rename`.

## About the vendor list

The first three bytes of a MAC address identify the company that made the network
chip. Discovery Now carries a short list of the makers you are most likely to meet
at home or in a lab (routers, access points, Raspberry Pi, ESP32 smart plugs,
printers, NAS boxes, phones and consoles) and uses it to fill the Vendor column.

- The list is part of the program. It is read locally, and Discovery Now never
  downloads anything.
- A vendor that is not on the list simply shows as unknown.
- Phones and laptops that randomize their MAC address have no vendor on purpose:
  the address was made up by the device, so there is no maker to name.

## Keeping watch

```bash
discoverynow watch
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
discoverynow devices rename 192.168.1.44 "NAS"
discoverynow devices note 192.168.1.31 "Smart plug, living room"
discoverynow devices approve NAS
discoverynow devices list --unapproved
```

Approving is a statement that a device belongs here. Everything you have not
approved stays flagged, so "I have never looked at this" never looks the same as
"this is mine".

## The desktop app

```bash
discoverynow gui
```

The window shows the same inventory as the command line, and both can be used
side by side.

- **Devices.** Every device in a table you can sort by any column, filter with the
  buttons above it (All, Online, Offline, New, Not approved, each with its count)
  and search by name, address, MAC, vendor, guessed kind or notes. New devices
  wear a `NEW` tag until the new-device window passes (7 days by default).
- **One device.** Select a row to see everything known about it. Give it a name,
  write a note, approve it, or forget it. Right-click a row to copy its address or
  MAC. Right-click a column header to show or hide columns (Ports and First seen
  start hidden).
- **Activity.** The history of everything that happened, newest first: devices
  discovered, gone offline, back online, changed address, opened or closed ports.
- **Keeping watch.** The app scans when it starts and then on its own, every 5
  minutes by default (the choice is in the header). A desktop notification tells
  you when a new device appears on a network it already knew. The very first scan
  does not announce every device it finds.
- **Export.** Save the inventory as CSV or JSON, optionally hiding private details.

Shortcuts: `F5` scan now, `Ctrl+F` search, `Ctrl+1` / `Ctrl+2` switch between
Devices and Activity. The window follows the system's light or dark appearance.

What the window remembers (its size, the columns you hid, the scan interval, the
notification switch) is kept in `gui.ini` next to the configuration file, not in
the Windows registry.

### A Windows build with no Python needed

```powershell
.\packaging\build-windows.ps1
```

This produces `dist\DiscoveryNow\DiscoveryNow.exe` and a zip of the folder, built
with PyInstaller. If the repository sits deep inside nested folders, pass a short
output path (`-OutDir C:\dn-build`): Windows stops at 260 characters unless long
paths are switched on. The `.exe` is not signed, so Windows SmartScreen will warn
the first time it is run.

## The interactive menu

```bash
discoverynow menu
```

If you would rather browse than remember, the menu lists every command, lets you
fill in any of its options, and runs the result. Nothing in it is a separate
feature: each entry runs the ordinary command, and the exact command line is shown
as you build it, so the menu is also a quick way of learning the CLI.

```
scan
Scan the network once and record what is there.

  --subnet, -s    192.168.1.0/24
  --timeout       not set
> --workers       32
  --no-dns        off
  --no-store      off
  --json          off
  --fail-on-new   off

  Run             run it with the values above
  Show help       what the command prints for --help
  Back

Parallel probes.
Accepts: a whole number

discoverynow scan --subnet 192.168.1.0/24 --workers 32
```

| Key | What it does |
| --- | --- |
| Up / Down (or `k` / `j`) | Move the cursor |
| Enter | Open a command or group, edit the option under the cursor, or press a button |
| Backspace / Delete | Clear the value of the option under the cursor |
| Esc or Left | Go back one screen. On the first screen, leave the menu |
| `q` | Leave the menu from anywhere |
| Ctrl+C | Leave the menu, or stop a running command such as `watch` |

How the options behave:

- **On/off options** (`--json`, `--force`) flip each time you press Enter.
- **Either-way options** (`--online` / `--offline`) cycle through *not set*, the first
  and the second.
- **Options with a fixed list of values** (`--format`) open a small list to pick from.
- **Everything else** asks you to type the value. Numbers are checked as you type
  them, and an empty answer clears the option.
- **Options you can repeat** (`--subnet`) ask for one value per line; an empty line
  ends the list.
- Options marked `*` are required: *Run* will not start until they are filled in.
- **Global options** at the bottom of the first screen (the `--config` file) are added
  to every command you run from the menu.
- A command remembers what you set while the menu is open, so you can run it again
  with a small change.

After a command runs, its output stays on screen until you press a key, so there is
time to read it. *Show help* on any command prints what `--help` would.

The menu needs a real, interactive terminal. If the output is piped or redirected it
says so and stops; the ordinary commands work everywhere.

The menu reads its commands and options from the command line itself instead of
describing them a second time, so anything added to the CLI appears in the menu
without further work.

## Exporting the device list

```bash
discoverynow export                          # CSV to the terminal
discoverynow export -o devices.csv           # CSV file, opens straight in Excel
discoverynow export -o devices.json          # JSON, picked from the extension
discoverynow export --unapproved --redact -o to-share.csv
```

The same filters as `devices list` apply (`--online`, `--offline`, `--new`,
`--unapproved`). With no `-o` the data goes to the terminal and nothing else does,
so it can be piped. An existing file is never overwritten unless you pass `--force`.

An inventory is a record of a real home, and an export is where it can leave your
machine. Before sharing one, use **`--redact`**: it hides the unique half of every
MAC address (`00:11:22:xx:xx:xx`) and removes hostnames, labels and notes, and it
replaces each device name with `device-<number>`. The vendor, address, open ports
and state stay, which is what someone helping you troubleshoot needs.

CSV cells that a spreadsheet would run as a formula (a hostname that starts with
`=`, for instance, which a device on a hostile network can choose for itself) are
defused with a leading apostrophe.

## Commands

| Command | What it does |
| --- | --- |
| `scan` | Scan once and record what is there |
| `watch` | Keep scanning on a schedule, reporting changes |
| `status` | Counts: known, online, offline, new, not approved |
| `interfaces` | The local interfaces and what would be scanned |
| `events` | Recent history across all devices |
| `export` | Write the device list to a CSV or JSON file |
| `menu` | An interactive menu over every command and option |
| `gui` | Open the desktop app (needs the `gui` extra) |
| `devices list` | The inventory, with `--online`, `--new`, `--unapproved` |
| `devices show` | Everything known about one device, with its history |
| `devices rename` / `note` / `approve` / `forget` | Annotate the inventory |
| `config init` / `show` / `path` | The configuration file |

Every command that shows something accepts `--json`, so the same tool serves a
person reading a table and a script reading a pipe. `scan --fail-on-new` exits
with status 3 when an unknown device appears, which is enough to drive a cron job
or a CI step.

## Configuration

```bash
discoverynow config init   # writes a commented file
discoverynow config path   # says where it is
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

One SQLite file, in the per-user data directory that `discoverynow status`
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
- [x] Desktop app, first version (Windows)
- [ ] Desktop app: more polish, then Linux packaging
- [ ] Notifications: device offline, webhook, and richer desktop alerts
- [ ] Security checks: MAC and IP changes, ARP anomalies, rogue DHCP, risky ports
- [ ] Packaged builds and a tagged release

## Development

```bash
pip install -e ".[dev,gui]"
ruff check . && ruff format --check . && mypy && pytest
```

The test suite needs no network and no display: it parses captured command output,
talks to loopback sockets, runs the inventory against temporary databases, and
drives the desktop window on Qt's invisible `offscreen` platform. The window's
tests skip themselves when PySide6 is not installed.

## License

[MIT](LICENSE)
