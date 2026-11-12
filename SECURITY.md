# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's
[security advisories](https://github.com/TrueScaleTech/discovery-local-devices/security/advisories/new)
rather than in a public issue. A first reply usually arrives within a few days.

Useful things to include: what you did, what happened, the platform and Python
version, and how serious you think it is.

## What this tool does, and does not do

Discovery Now is a discovery and inventory tool for networks you own or are
authorized to assess. Knowing its limits is part of using it safely.

It does:

- send ICMP echo requests to the addresses of the subnet it is told to scan;
- open and immediately close TCP connections to a short list of common ports;
- read the operating system's own ARP cache and interface table;
- resolve hostnames through the resolver the machine is already configured with;
- download the public IEEE vendor registry, but only when you ask it to.

It does not:

- authenticate, guess credentials, or attempt any exploitation;
- capture or inspect network traffic;
- change anything on the devices it finds;
- send your inventory anywhere. There is no telemetry and no cloud component.

## Guards

- Addresses outside private ranges are refused unless `allow_public_ranges` is
  turned on in the configuration, which is a deliberate statement that you are
  authorized to scan those targets.
- A subnet wider than `max_hosts_per_subnet` is refused, so a mistyped prefix
  cannot start millions of probes.
- No administrator or root privileges are required or requested.

## Your data

The inventory holds MAC addresses, hostnames and IP addresses of devices on your
network, which can identify people and their habits. It is stored only in a local
SQLite file, whose location `discoverynow status` prints. Treat it as personal
data: do not commit it, and think before sharing an export.
