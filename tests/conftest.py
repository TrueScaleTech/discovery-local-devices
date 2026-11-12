"""Shared fixtures.

Every test runs against throwaway directories. A tool that keeps an inventory of
someone's network must never have its test suite read or write the real one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# The desktop tests draw real widgets; no display is needed or wanted.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from discovery_now import oui
from discovery_now.store import Store


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the configuration and data directories at a temporary place."""
    monkeypatch.setenv("DISCOVERY_NOW_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("DISCOVERY_NOW_DATA_DIR", str(tmp_path / "data"))
    oui.reset_cache()
    yield
    oui.reset_cache()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    """An empty inventory in a temporary file."""
    with Store(tmp_path / "inventory.db") as opened:
        yield opened
