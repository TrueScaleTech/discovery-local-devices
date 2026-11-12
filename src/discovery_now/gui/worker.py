"""Running a scan without freezing the window.

A scan takes seconds and waits on the network almost the whole time, so it runs on
its own thread. That thread opens its own connection to the inventory: a SQLite
connection belongs to the thread that made it, and the database is in WAL mode so
the window can keep reading while the scan writes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta

from PySide6.QtCore import QObject, Signal

from ..config import Settings
from ..discovery import run_scan
from ..net import TargetError, default_gateways, local_macs
from ..store import Store

_ONE_DAY = timedelta(days=1)


class ScanRunner(QObject):
    """Starts scans in the background and reports back on the window's own thread."""

    #: Stage name, work done, work total.
    progress = Signal(str, int, int)
    #: The scan report, what it changed, and whether the inventory was empty before.
    finished = Signal(object, object, bool)
    #: A short explanation of why the scan could not run.
    failed = Signal(str)
    #: The default gateways, and this machine's own addresses, for the map.
    addresses = Signal(list, list)

    def __init__(
        self,
        store_factory: Callable[[], Store] = Store,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store_factory = store_factory
        self._busy = False
        # Connected first, so the busy flag is clear before any other listener runs
        # and a listener may start the next scan straight away.
        self.finished.connect(self._release)
        self.failed.connect(self._release)

    @property
    def running(self) -> bool:
        return self._busy

    def start(self, settings: Settings) -> bool:
        """Begin a scan. Returns False, doing nothing, if one is already running."""
        if self._busy:
            return False
        self._busy = True
        threading.Thread(target=self._run, args=(settings,), name="scan", daemon=True).start()
        return True

    def _release(self, *_ignored: object) -> None:
        self._busy = False

    def find_addresses(self) -> None:
        """Look up the gateways and this machine's addresses, off the window's thread.

        Reading the routing table means starting a command and waiting on it, which
        would hold the window still for as long as it takes.
        """
        threading.Thread(target=self._addresses, name="addresses", daemon=True).start()

    def _addresses(self) -> None:
        try:
            self.addresses.emit(default_gateways(), list(local_macs()))
        except OSError:
            # The map works without this; it falls back to working the gateway
            # out from the devices themselves.
            self.addresses.emit([], [])

    def _run(self, settings: Settings) -> None:
        try:
            with self._store_factory() as store:
                was_empty = store.summary(new_within=_ONE_DAY)["total"] == 0
                report = run_scan(settings, progress=self.progress.emit)
                outcome = store.record_scan(
                    report.observations, offline_after=settings.offline_after
                )
                store.record_scan_run(
                    networks=[str(network) for network in report.networks],
                    probed=report.addresses_probed,
                    found=report.found,
                    duration=report.duration,
                )
        except TargetError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
        else:
            self.finished.emit(report, outcome, was_empty)
