"""The command line, exercised without touching the network."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from discovery_now import __version__
from discovery_now.cli import app
from discovery_now.models import Observation
from discovery_now.store import Store

runner = CliRunner()


class TestBasics:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.stdout

    def test_help_lists_the_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for command in ("scan", "watch", "devices", "events", "status"):
            assert command in result.stdout


class TestGuards:
    def test_a_public_subnet_is_refused_before_any_packet(self) -> None:
        result = runner.invoke(app, ["scan", "--subnet", "8.8.8.0/24"])
        assert result.exit_code == 1

    def test_an_oversized_subnet_is_refused(self) -> None:
        result = runner.invoke(app, ["scan", "--subnet", "10.0.0.0/8"])
        assert result.exit_code == 1

    def test_nonsense_targets_are_refused(self) -> None:
        result = runner.invoke(app, ["scan", "--subnet", "my-network"])
        assert result.exit_code == 1


class TestInventoryCommands:
    def test_an_empty_inventory_says_so(self) -> None:
        result = runner.invoke(app, ["devices", "list"])
        assert result.exit_code == 0
        assert "No devices" in result.stdout

    def test_listing_devices_as_json(self) -> None:
        with Store() as store:
            store.record_scan([Observation(ip="192.168.1.10", mac="aa:bb:cc:dd:ee:01")])
        result = runner.invoke(app, ["devices", "list", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload[0]["ip"] == "192.168.1.10"
        assert payload[0]["is_new"] is True

    def test_renaming_and_approving(self) -> None:
        with Store() as store:
            store.record_scan([Observation(ip="192.168.1.10", mac="aa:bb:cc:dd:ee:01")])
        assert runner.invoke(app, ["devices", "rename", "192.168.1.10", "Printer"]).exit_code == 0
        assert runner.invoke(app, ["devices", "approve", "Printer"]).exit_code == 0
        result = runner.invoke(app, ["devices", "show", "Printer", "--json"])
        payload = json.loads(result.stdout)
        assert payload["label"] == "Printer"
        assert payload["approved"] is True

    def test_an_unknown_device_is_an_error(self) -> None:
        result = runner.invoke(app, ["devices", "show", "203.0.113.9"])
        assert result.exit_code == 1

    def test_status_counts_as_json(self) -> None:
        with Store() as store:
            store.record_scan([Observation(ip="192.168.1.10", mac="aa:bb:cc:dd:ee:01")])
        result = runner.invoke(app, ["status", "--json"])
        assert json.loads(result.stdout)["total"] == 1

    def test_events_are_listed(self) -> None:
        with Store() as store:
            store.record_scan([Observation(ip="192.168.1.10", mac="aa:bb:cc:dd:ee:01")])
        result = runner.invoke(app, ["events", "--json"])
        assert json.loads(result.stdout)[0]["kind"] == "discovered"


class TestConfigCommands:
    def test_init_writes_a_commented_file(self) -> None:
        result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        result = runner.invoke(app, ["config", "show"])
        assert json.loads(result.stdout)["offline_after"] == 3
