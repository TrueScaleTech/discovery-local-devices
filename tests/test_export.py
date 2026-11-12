"""Exporting the inventory: the fields, the formats, and what is hidden when sharing."""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from discovery_now import export as exporting
from discovery_now.cli import app
from discovery_now.models import Observation
from discovery_now.store import Store

WEEK = timedelta(days=7)
runner = CliRunner()


def populate(store: Store) -> None:
    """Two devices, the first with everything a real one has plus a label and a note."""
    store.record_scan(
        [
            Observation(
                ip="192.168.1.10",
                mac="00:11:22:33:44:01",
                hostname="mum-phone.home",
                vendor="Acme",
                open_ports=(80, 443),
            ),
            Observation(ip="192.168.1.11", mac="00:11:22:33:44:02"),
        ]
    )
    first = store.devices()[0]
    store.set_label(first.id, "Mum's phone")
    store.set_notes(first.id, "Kitchen, charges overnight")


def table_for(store: Store, *, redact: bool = False) -> list[dict[str, object]]:
    return exporting.rows(store.devices(), new_within=WEEK, redact=redact)


class TestRows:
    def test_columns_come_in_the_documented_order(self, store: Store) -> None:
        populate(store)
        assert tuple(table_for(store)[0]) == exporting.COLUMNS

    def test_carries_what_the_inventory_knows(self, store: Store) -> None:
        populate(store)
        row = table_for(store)[0]
        assert row["ip"] == "192.168.1.10"
        assert row["mac"] == "00:11:22:33:44:01"
        assert row["open_ports"] == [80, 443]
        assert row["label"] == "Mum's phone"
        assert row["is_new"] is True


class TestRedaction:
    def test_hides_the_unique_half_of_a_mac(self) -> None:
        assert exporting.redact_mac("00:11:22:33:44:55") == "00:11:22:xx:xx:xx"

    def test_leaves_a_missing_mac_alone(self) -> None:
        assert exporting.redact_mac(None) is None

    def test_a_malformed_mac_is_hidden_entirely(self) -> None:
        assert exporting.redact_mac("not-a-mac") == "xx:xx:xx:xx:xx:xx"

    def test_removes_everything_that_names_a_person(self, store: Store) -> None:
        populate(store)
        row = table_for(store, redact=True)[0]
        assert row["mac"] == "00:11:22:xx:xx:xx"
        assert row["hostname"] is None
        assert row["label"] is None
        assert row["notes"] is None

    def test_the_name_no_longer_leaks_the_label_or_hostname(self, store: Store) -> None:
        # The name is normally the label, then the hostname: the very things hidden.
        populate(store)
        first = store.devices()[0]
        row = table_for(store, redact=True)[0]
        assert row["name"] == f"device-{first.id}"
        assert "Mum" not in json.dumps(row)

    def test_keeps_what_is_useful_to_someone_else(self, store: Store) -> None:
        populate(store)
        row = table_for(store, redact=True)[0]
        assert row["vendor"] == "Acme"
        assert row["open_ports"] == [80, 443]
        assert row["online"] is True


class TestNeutralize:
    @pytest.mark.parametrize(
        "value",
        ["=1+1", "+39 333 000", "-2+3", "@SUM(A1)", "\tcmd", '=HYPERLINK("http://x","y")'],
    )
    def test_a_cell_that_would_be_a_formula_is_defanged(self, value: str) -> None:
        assert exporting.neutralize(value) == "'" + value

    @pytest.mark.parametrize("value", ["printer", "192.168.1.10", "a=b", ""])
    def test_ordinary_text_is_untouched(self, value: str) -> None:
        assert exporting.neutralize(value) == value

    def test_a_hostile_hostname_is_defanged_in_the_csv(self, store: Store) -> None:
        # A device chooses its own hostname, so on a hostile network this is input.
        hostile = "=cmd|' /C calc'!A0"
        store.record_scan(
            [Observation(ip="192.168.1.50", mac="00:11:22:33:44:09", hostname=hostile)]
        )
        text = exporting.to_csv(table_for(store))
        cells = next(csv.DictReader(io.StringIO(text)))
        assert cells["hostname"].startswith("'=")
        assert cells["name"].startswith("'=")


class TestCsv:
    def test_round_trips_through_a_csv_reader(self, store: Store) -> None:
        populate(store)
        text = exporting.to_csv(table_for(store))
        records = list(csv.DictReader(io.StringIO(text)))
        assert [r["ip"] for r in records] == ["192.168.1.10", "192.168.1.11"]
        assert tuple(records[0]) == exporting.COLUMNS

    def test_booleans_and_ports_are_readable(self, store: Store) -> None:
        populate(store)
        text = exporting.to_csv(table_for(store))
        record = next(csv.DictReader(io.StringIO(text)))
        assert record["online"] == "true"
        assert record["approved"] == "false"
        assert record["open_ports"] == "80;443"

    def test_missing_values_are_empty_cells(self, store: Store) -> None:
        populate(store)
        text = exporting.to_csv(table_for(store))
        second = list(csv.DictReader(io.StringIO(text)))[1]
        assert second["hostname"] == ""
        assert second["label"] == ""

    def test_an_empty_inventory_is_just_the_header(self) -> None:
        assert exporting.to_csv([]).strip() == ",".join(exporting.COLUMNS)


class TestJson:
    def test_keeps_real_types(self, store: Store) -> None:
        populate(store)
        data = json.loads(exporting.to_json(table_for(store)))
        assert data[0]["open_ports"] == [80, 443]
        assert data[0]["online"] is True
        assert data[1]["hostname"] is None

    def test_an_empty_inventory_is_an_empty_list(self) -> None:
        assert json.loads(exporting.to_json([])) == []


class TestCommand:
    @staticmethod
    def seed() -> None:
        with Store() as store:
            populate(store)

    def test_prints_csv_by_default(self) -> None:
        self.seed()
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 0
        assert result.stdout.splitlines()[0] == ",".join(exporting.COLUMNS)
        assert "192.168.1.10" in result.stdout

    def test_prints_nothing_but_the_data(self) -> None:
        # So that it can be piped or redirected without cleaning anything up.
        self.seed()
        result = runner.invoke(app, ["export", "--format", "json"])
        assert json.loads(result.stdout)[0]["ip"] == "192.168.1.10"

    def test_writes_a_file(self, tmp_path: Path) -> None:
        self.seed()
        target = tmp_path / "devices.csv"
        result = runner.invoke(app, ["export", "-o", str(target)])
        assert result.exit_code == 0
        assert "Exported 2 device(s)" in result.stdout
        assert "192.168.1.10" in target.read_text(encoding="utf-8-sig")

    def test_csv_files_start_with_a_byte_order_mark_for_excel(self, tmp_path: Path) -> None:
        self.seed()
        target = tmp_path / "devices.csv"
        runner.invoke(app, ["export", "-o", str(target)])
        assert target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_the_format_follows_the_file_extension(self, tmp_path: Path) -> None:
        self.seed()
        target = tmp_path / "devices.json"
        runner.invoke(app, ["export", "-o", str(target)])
        assert json.loads(target.read_text(encoding="utf-8"))[0]["ip"] == "192.168.1.10"
        assert not target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_an_explicit_format_beats_the_extension(self, tmp_path: Path) -> None:
        self.seed()
        target = tmp_path / "devices.json"
        runner.invoke(app, ["export", "-o", str(target), "--format", "csv"])
        assert target.read_text(encoding="utf-8-sig").startswith("id,name")

    def test_never_overwrites_by_accident(self, tmp_path: Path) -> None:
        self.seed()
        target = tmp_path / "devices.csv"
        target.write_text("precious", encoding="utf-8")
        result = runner.invoke(app, ["export", "-o", str(target)])
        assert result.exit_code == 1
        assert target.read_text(encoding="utf-8") == "precious"

    def test_force_overwrites(self, tmp_path: Path) -> None:
        self.seed()
        target = tmp_path / "devices.csv"
        target.write_text("old", encoding="utf-8")
        result = runner.invoke(app, ["export", "-o", str(target), "--force"])
        assert result.exit_code == 0
        assert "192.168.1.10" in target.read_text(encoding="utf-8-sig")

    def test_creates_missing_folders(self, tmp_path: Path) -> None:
        self.seed()
        target = tmp_path / "reports" / "2026" / "devices.csv"
        assert runner.invoke(app, ["export", "-o", str(target)]).exit_code == 0
        assert target.is_file()

    def test_redacts_on_request(self) -> None:
        self.seed()
        result = runner.invoke(app, ["export", "--redact"])
        assert "00:11:22:xx:xx:xx" in result.stdout
        assert "mum-phone" not in result.stdout
        assert "Mum" not in result.stdout
        assert "Kitchen" not in result.stdout

    def test_says_when_it_redacted_a_file(self, tmp_path: Path) -> None:
        self.seed()
        result = runner.invoke(app, ["export", "-o", str(tmp_path / "x.csv"), "--redact"])
        assert "hidden" in result.stdout

    def test_filters_like_the_listing(self) -> None:
        self.seed()
        with Store() as store:
            store.set_approved(store.devices()[0].id, True)
        result = runner.invoke(app, ["export", "--unapproved", "--format", "json"])
        assert [row["ip"] for row in json.loads(result.stdout)] == ["192.168.1.11"]

    def test_an_empty_inventory_still_exports_cleanly(self) -> None:
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 0
        assert result.stdout.strip() == ",".join(exporting.COLUMNS)

    def test_an_unknown_format_is_rejected(self) -> None:
        assert runner.invoke(app, ["export", "--format", "xml"]).exit_code != 0


class TestWrite:
    def test_a_csv_gets_a_byte_order_mark_so_excel_reads_accents(self, tmp_path: Path) -> None:
        target = tmp_path / "a.csv"
        exporting.write(target, "name\ncafé\n", exporting.ExportFormat.CSV)
        assert target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_json_has_none(self, tmp_path: Path) -> None:
        target = tmp_path / "a.json"
        exporting.write(target, "[]\n", exporting.ExportFormat.JSON)
        assert not target.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_the_folder_is_created_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "er" / "a.json"
        exporting.write(target, "[]\n", exporting.ExportFormat.JSON)
        assert target.is_file()
