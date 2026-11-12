"""Entry point for the packaged desktop app (``DiscoveryNow.exe``)."""

from __future__ import annotations

import sys

from discovery_now.gui.app import run

if __name__ == "__main__":
    sys.exit(run())
