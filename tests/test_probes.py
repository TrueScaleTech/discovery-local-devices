"""Reading ping output, and knocking on real sockets."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest

from discovery_now import probes

WINDOWS_REPLY = (
    "Esecuzione di Ping 192.168.1.1 con 32 byte di dati:\r\n"
    "Risposta da 192.168.1.1: byte=32 durata=4ms TTL=64\r\n"
)
WINDOWS_UNREACHABLE = (
    "Esecuzione di Ping 192.168.1.5 con 32 byte di dati:\r\n"
    "Risposta da 192.168.1.1: Host di destinazione non raggiungibile.\r\n"
)
LINUX_REPLY = "64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=0.84 ms\n"


class TestParsePingOutput:
    def test_a_reply_counts_as_alive(self) -> None:
        result = probes.parse_ping_output(0, WINDOWS_REPLY)
        assert result.alive
        assert result.rtt_ms == 4.0

    def test_a_router_saying_unreachable_is_not_the_device(self) -> None:
        # Windows exits 0 here even though nothing answered, which is exactly the
        # case the TTL check exists for.
        assert not probes.parse_ping_output(0, WINDOWS_UNREACHABLE).alive

    def test_reads_linux_output(self) -> None:
        result = probes.parse_ping_output(0, LINUX_REPLY)
        assert result.alive
        assert result.rtt_ms == pytest.approx(0.84)

    def test_a_comma_decimal_separator_is_understood(self) -> None:
        result = probes.parse_ping_output(0, "Antwort von 10.0.0.1: Zeit=1,5ms TTL=128")
        assert result.rtt_ms == pytest.approx(1.5)

    def test_sub_millisecond_replies_are_still_alive(self) -> None:
        assert probes.parse_ping_output(0, "Reply from 10.0.0.1: time<1ms TTL=128").alive

    def test_a_failed_run_is_not_alive(self) -> None:
        assert not probes.parse_ping_output(1, "").alive


@pytest.fixture
def listening_port() -> Iterator[int]:
    """A real TCP socket on loopback, so the probe has something to find."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        yield int(server.getsockname()[1])


@pytest.fixture
def closed_port() -> int:
    """A port nothing is listening on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class TestProbePort:
    def test_finds_an_open_port(self, listening_port: int) -> None:
        assert probes.probe_port("127.0.0.1", listening_port, timeout=2.0) == "open"

    def test_a_closed_port_is_not_open(self, closed_port: int) -> None:
        # Loopback normally refuses outright; a firewall could swallow it instead.
        assert probes.probe_port("127.0.0.1", closed_port, timeout=1.0) in {"refused", "silent"}


class TestTcpSweep:
    def test_reports_the_open_port_of_a_live_host(self, listening_port: int) -> None:
        results = probes.tcp_sweep(["127.0.0.1"], [listening_port], timeout=2.0, workers=4)
        assert results["127.0.0.1"].open_ports == (listening_port,)
        assert results["127.0.0.1"].responded

    def test_nothing_to_do_without_targets_or_ports(self) -> None:
        assert probes.tcp_sweep([], [80], timeout=1.0) == {}
        assert probes.tcp_sweep(["127.0.0.1"], [], timeout=1.0) == {}


class TestPingSweepConcurrency:
    def test_never_runs_more_pings_at_once_than_the_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every ping is a process, and starting too many at once is what made scans
        # hang on Windows. The cap has to hold however many workers are asked for.
        lock = threading.Lock()
        running = 0
        peak = 0

        def slow_ping(ip: str, *, timeout: float = 1.0) -> probes.PingResult:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.02)
            with lock:
                running -= 1
            return probes.PingResult(alive=True)

        monkeypatch.setattr(probes, "ping", slow_ping)
        ips = [f"10.0.0.{n}" for n in range(1, 201)]
        results = probes.ping_sweep(ips, workers=500)

        assert len(results) == 200
        assert peak <= probes.PING_WORKERS_MAX
        assert peak > 1  # still parallel, not accidentally serial
