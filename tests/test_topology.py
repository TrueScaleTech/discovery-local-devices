"""Where the network map puts things, worked out without a window."""

from __future__ import annotations

import math
from datetime import timedelta

from discovery_now.gui.topology import (
    choose_gateway,
    fit_scale,
    looks_like_gateway,
    plan,
    ring_capacity,
)
from discovery_now.models import Device, utcnow

WEEK = timedelta(days=7)


def device(
    ident: int,
    ip: str,
    *,
    hostname: str | None = None,
    ports: tuple[int, ...] = (),
    online: bool = True,
    approved: bool = True,
    age: timedelta = timedelta(days=30),
    label: str | None = None,
) -> Device:
    moment = utcnow()
    return Device(
        id=ident,
        key=f"ip:{ip}",
        ip=ip,
        mac=None,
        hostname=hostname,
        vendor=None,
        label=label,
        notes=None,
        first_seen=moment - age,
        last_seen=moment,
        online=online,
        approved=approved,
        misses=0,
        open_ports=ports,
    )


ROUTER = device(1, "192.168.1.254", hostname="router.home", ports=(53, 80, 443))
LAPTOP = device(2, "192.168.1.10", hostname="laptop-office.home")
PRINTER = device(3, "192.168.1.9", hostname="hp-printer.home", ports=(9100,))


class TestFindingTheGateway:
    def test_the_routing_table_has_the_last_word(self) -> None:
        # Even a device that looks nothing like a router is the gateway if the
        # system says that address is the way out.
        assert looks_like_gateway(LAPTOP, gateways=["192.168.1.10"])
        assert not looks_like_gateway(ROUTER, gateways=["192.168.1.10"])

    def test_without_the_routing_table_the_fingerprint_decides(self) -> None:
        assert looks_like_gateway(ROUTER)
        assert not looks_like_gateway(LAPTOP)

    def test_dns_and_a_web_page_together_mean_a_router(self) -> None:
        assert looks_like_gateway(device(9, "10.0.0.1", ports=(53, 443)))
        assert not looks_like_gateway(device(9, "10.0.0.1", ports=(53,)))

    def test_the_lowest_address_wins_when_several_match(self) -> None:
        other = device(4, "192.168.1.1", hostname="fritz.box")
        found = choose_gateway([ROUTER, other])
        assert found is not None
        assert found.ip == "192.168.1.1"

    def test_a_network_with_no_router_in_it(self) -> None:
        assert choose_gateway([LAPTOP, PRINTER]) is None


class TestTheShapeOfTheMap:
    def test_the_gateway_sits_in_the_middle(self) -> None:
        drawn = plan([ROUTER, LAPTOP], new_within=WEEK)
        assert drawn.gateway == 0
        assert (drawn.nodes[0].x, drawn.nodes[0].y) == (0.0, 0.0)
        assert drawn.nodes[0].role == "gateway"

    def test_everything_is_joined_to_the_gateway(self) -> None:
        drawn = plan([ROUTER, LAPTOP, PRINTER], new_within=WEEK)
        assert drawn.edges == ((0, 1), (0, 2))

    def test_with_no_gateway_nothing_is_joined(self) -> None:
        drawn = plan([LAPTOP, PRINTER], new_within=WEEK)
        assert drawn.gateway is None
        assert drawn.edges == ()
        assert len(drawn.nodes) == 2

    def test_an_empty_network_maps_to_nothing(self) -> None:
        drawn = plan([], new_within=WEEK)
        assert drawn.nodes == ()
        assert drawn.radius == 0.0

    def test_devices_are_spread_around_the_gateway(self) -> None:
        others = [device(i, f"192.168.1.{i}") for i in range(10, 18)]
        drawn = plan([ROUTER, *others], new_within=WEEK)
        away = {round(math.hypot(node.x, node.y)) for node in drawn.nodes[1:]}
        assert away == {215}  # one ring, every device the same distance out

    def test_a_crowd_spills_onto_a_second_ring(self) -> None:
        others = [device(i, f"192.168.1.{i}") for i in range(10, 50)]
        drawn = plan([ROUTER, *others], new_within=WEEK)
        rings = {round(math.hypot(node.x, node.y)) for node in drawn.nodes[1:]}
        assert len(rings) > 1
        assert drawn.radius > 215

    def test_a_ring_holds_only_what_fits(self) -> None:
        assert ring_capacity(215) == 11
        assert ring_capacity(1000) > ring_capacity(215)
        assert ring_capacity(1) == 6  # never less than a handful

    def test_like_is_placed_beside_like(self) -> None:
        # Two printers and two laptops, listed interleaved by address.
        devices = [
            ROUTER,
            device(10, "192.168.1.11", hostname="printer-one", ports=(9100,)),
            device(11, "192.168.1.12", hostname="laptop-one"),
            device(12, "192.168.1.13", hostname="printer-two", ports=(9100,)),
            device(13, "192.168.1.14", hostname="laptop-two"),
        ]
        order = [node.label for node in plan(devices, new_within=WEEK).nodes[1:]]
        assert order.index("laptop-two") - order.index("laptop-one") == 1
        assert order.index("printer-two") - order.index("printer-one") == 1

    def test_this_machine_is_marked_as_such(self) -> None:
        drawn = plan([ROUTER, LAPTOP], new_within=WEEK, local_ips=["192.168.1.10"])
        roles = {node.ip: node.role for node in drawn.nodes}
        assert roles["192.168.1.10"] == "this machine"
        assert roles["192.168.1.254"] == "gateway"

    def test_a_node_carries_what_the_map_has_to_show(self) -> None:
        fresh = device(
            5,
            "192.168.1.50",
            hostname="ana-sphone.home",
            online=False,
            approved=False,
            age=timedelta(hours=2),
            label="Ana's phone",
        )
        node = plan([ROUTER, fresh], new_within=WEEK).nodes[1]
        assert node.label == "Ana's phone"  # the name the user gave it
        assert node.kind == "phone"
        assert (node.online, node.approved, node.is_new) == (False, False, True)
        assert node.device_id == 5


class TestFittingTheView:
    def test_a_bigger_map_is_zoomed_further_out(self) -> None:
        assert fit_scale(1000, 800, 600) < fit_scale(300, 800, 600)

    def test_an_empty_map_is_left_alone(self) -> None:
        assert fit_scale(0, 800, 600) == 1.0

    def test_the_zoom_stays_within_reach(self) -> None:
        assert 0.12 <= fit_scale(99_999, 800, 600) <= 1.6
        assert fit_scale(10, 40, 40) >= 0.12  # a window too small for the margin
