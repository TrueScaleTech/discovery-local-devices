"""Where everything sits on the network map.

The arithmetic lives here, with no Qt in it, so the shape of the map can be
tested without a window.

What the map claims is worth being careful about. Discovery Now never sees which
switch port a device is plugged into, so it cannot draw the real wiring. What it
does know is that a home network is normally one flat segment behind one router,
and that is what the map shows: the gateway in the middle, everything else around
it, grouped by what each device is. Anything the program is unsure of (which
address is the gateway, what a device is) is worked out from evidence and said
plainly rather than drawn as if it were certain.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from ..fingerprint import kind_of
from ..models import Device
from .viewmodel import address_key

#: How far apart two neighbours on a ring should be, in scene units.
SPACING = 118.0
#: The radius of the first ring of devices around the gateway.
FIRST_RING = 215.0
#: How much further out each ring after the first sits.
RING_STEP = 150.0


@dataclass(frozen=True, slots=True)
class Node:
    """One thing on the map."""

    label: str
    ip: str
    kind: str | None
    online: bool
    is_new: bool
    approved: bool
    #: "gateway", "this machine" or "device".
    role: str
    x: float
    y: float
    device_id: int | None = None

    @property
    def is_gateway(self) -> bool:
        return self.role == "gateway"


@dataclass(frozen=True, slots=True)
class Map:
    """Everything the map draws: the nodes, and what joins them."""

    nodes: tuple[Node, ...]
    #: Pairs of indices into ``nodes``. Every edge starts at the gateway.
    edges: tuple[tuple[int, int], ...]
    gateway: int | None

    @property
    def radius(self) -> float:
        """How far the furthest node sits from the middle."""
        return max((math.hypot(n.x, n.y) for n in self.nodes), default=0.0)


def looks_like_gateway(device: Device, *, gateways: Sequence[str] = ()) -> bool:
    """Whether this device is the way out of the network.

    The operating system's own routing table decides it when we have it. Without
    it, a device the fingerprint calls a router, or one answering DNS and a web
    page, is the next best evidence.
    """
    if device.ip in gateways:
        return True
    if gateways:
        # The routing table answered; do not then guess at something else.
        return False
    kind = (kind_of(device) or "").lower()
    if "router" in kind or "gateway" in kind:
        return True
    ports = set(device.open_ports)
    return 53 in ports and bool(ports & {80, 443})


def choose_gateway(devices: Sequence[Device], *, gateways: Sequence[str] = ()) -> Device | None:
    """The one device to put in the middle, or None when nothing looks like one."""
    found = [device for device in devices if looks_like_gateway(device, gateways=gateways)]
    if not found:
        return None
    # More than one match: the lowest address, which is the usual home router.
    return sorted(found, key=lambda device: address_key(device.ip))[0]


def ring_capacity(radius: float) -> int:
    """How many nodes fit on a ring before they start to touch."""
    return max(6, int((2 * math.pi * radius) // SPACING))


def _rings(count: int) -> list[tuple[float, int]]:
    """The radius of each ring, and how many nodes it holds, for ``count`` nodes."""
    plan: list[tuple[float, int]] = []
    placed = 0
    index = 0
    while placed < count:
        radius = FIRST_RING + RING_STEP * index
        room = min(ring_capacity(radius), count - placed)
        plan.append((radius, room))
        placed += room
        index += 1
    return plan


def _order(device: Device, local: Sequence[str]) -> tuple[str, tuple[int, ...]]:
    """Group the ring by what each device is, so like sits beside like."""
    if device.ip in local:
        return ("", address_key(device.ip))
    return ((kind_of(device) or "~unknown").lower(), address_key(device.ip))


def plan(
    devices: Sequence[Device],
    *,
    new_within: timedelta,
    local_ips: Sequence[str] = (),
    gateways: Sequence[str] = (),
) -> Map:
    """Work out where every device goes.

    The gateway takes the middle. Everything else is laid out on rings around it,
    sorted so that devices of the same kind end up next to each other, and each
    ring holds only as many as fit.
    """
    gateway = choose_gateway(devices, gateways=gateways)
    others = sorted(
        (device for device in devices if device is not gateway),
        key=lambda device: _order(device, local_ips),
    )

    def build(device: Device, role: str, x: float, y: float) -> Node:
        return Node(
            label=device.name,
            ip=device.ip,
            kind=kind_of(device),
            online=device.online,
            is_new=device.is_new(new_within),
            approved=device.approved,
            role=role,
            x=x,
            y=y,
            device_id=device.id,
        )

    nodes: list[Node] = []
    gateway_index: int | None = None
    if gateway is not None:
        gateway_index = 0
        nodes.append(build(gateway, "gateway", 0.0, 0.0))

    placed = 0
    for radius, room in _rings(len(others)):
        # Start each ring at the top, and offset every other ring by half a step
        # so neighbouring rings do not line up into spokes.
        twist = math.pi / room if len(nodes) % 2 else 0.0
        for seat in range(room):
            device = others[placed + seat]
            angle = -math.pi / 2 + twist + seat * (2 * math.pi / room)
            role = "this machine" if device.ip in local_ips else "device"
            nodes.append(build(device, role, radius * math.cos(angle), radius * math.sin(angle)))
        placed += room

    edges: tuple[tuple[int, int], ...] = ()
    if gateway_index is not None:
        edges = tuple((gateway_index, index) for index in range(1, len(nodes)))
    return Map(nodes=tuple(nodes), edges=edges, gateway=gateway_index)


#: How far the view may be zoomed when fitting a map to the window.
MIN_SCALE = 0.12
MAX_SCALE = 1.6


def fit_scale(radius: float, width: float, height: float, *, margin: float = 90.0) -> float:
    """The zoom that brings a map of this size into a window of that size."""
    if radius <= 0:
        return 1.0
    room = min(width, height) / 2 - margin
    if room <= 0:
        # A window too small to hold the margin: as far out as the view goes.
        return MIN_SCALE
    return max(MIN_SCALE, min(MAX_SCALE, room / radius))
