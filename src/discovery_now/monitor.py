"""Watch mode: scan on a schedule and report only what changed."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .config import Settings
from .discovery import ScanReport, run_scan
from .models import ScanOutcome
from .store import Store

#: Called after every round with what the scan saw and what it changed.
RoundCallback = Callable[[ScanReport, ScanOutcome], None]

#: How often the sleep between rounds checks whether it has been asked to stop.
_WAKE_INTERVAL = 0.25


def watch(
    settings: Settings,
    store: Store,
    *,
    on_round: RoundCallback,
    stop: threading.Event | None = None,
    rounds: int | None = None,
) -> int:
    """Scan repeatedly until asked to stop, returning the number of rounds run.

    The waiting between rounds is broken into short naps rather than one long
    sleep, so a stop request is honoured within a moment instead of at the end of
    the interval. ``rounds`` bounds the loop, which is what makes this testable
    and what a scheduled one-shot run uses.
    """
    signal = stop or threading.Event()
    completed = 0

    while not signal.is_set():
        report = run_scan(settings)
        outcome = store.record_scan(report.observations, offline_after=settings.offline_after)
        store.record_scan_run(
            networks=[str(network) for network in report.networks],
            probed=report.addresses_probed,
            found=report.found,
            duration=report.duration,
        )
        on_round(report, outcome)
        completed += 1

        if rounds is not None and completed >= rounds:
            break
        if not _sleep(signal, settings.watch_interval):
            break

    return completed


def _sleep(signal: threading.Event, seconds: float) -> bool:
    """Wait, waking early if asked to stop. False means "stop now"."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if signal.wait(timeout=min(_WAKE_INTERVAL, max(0.0, deadline - time.monotonic()))):
            return False
    return True
