"""The settings file: what it writes, and that it reads back the same."""

from __future__ import annotations

from pathlib import Path

from discovery_now.config import Settings


class TestWritingTheFile:
    def test_what_is_written_reads_back_the_same(self, tmp_path: Path) -> None:
        # The desktop app writes this file and the command line reads it, so a
        # round trip has to be exact or the two would disagree.
        settings = Settings(
            subnets=["192.168.1.0/24", "10.0.0.0/24"],
            allow_public_ranges=True,
            max_hosts_per_subnet=512,
            workers=64,
            timeout=1.5,
            ports=[22, 80, 443],
            resolve_hostnames=False,
            offline_after=5,
            new_device_days=14,
            watch_interval=900,
        )
        target = settings.save(tmp_path / "config.toml")
        assert Settings.load(target) == settings

    def test_the_defaults_round_trip_too(self, tmp_path: Path) -> None:
        settings = Settings()
        assert Settings.load(settings.save(tmp_path / "config.toml")) == settings

    def test_every_value_is_written_out(self, tmp_path: Path) -> None:
        # Not just the ones that differ from the default: the file should say
        # what the program will do, without the reader knowing the defaults.
        text = Settings().save(tmp_path / "config.toml").read_text(encoding="utf-8")
        for key in (
            "subnets",
            "allow_public_ranges",
            "max_hosts_per_subnet",
            "workers",
            "timeout",
            "resolve_hostnames",
            "ports",
            "offline_after",
            "new_device_days",
            "watch_interval",
        ):
            assert f"{key} = " in text, key

    def test_saving_replaces_what_was_there(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        Settings(watch_interval=60).save(target)
        Settings(watch_interval=1800).save(target)
        assert Settings.load(target).watch_interval == 1800

    def test_the_folder_is_made_if_it_is_missing(self, tmp_path: Path) -> None:
        target = Settings().save(tmp_path / "deep" / "er" / "config.toml")
        assert target.is_file()

    def test_an_empty_list_of_networks_is_written_as_one(self, tmp_path: Path) -> None:
        text = Settings(subnets=[]).save(tmp_path / "config.toml").read_text(encoding="utf-8")
        assert "subnets = []" in text


class TestTheCommentedTemplate:
    def test_write_default_never_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        Settings(watch_interval=1800).save(target)
        Settings().write_default(target)
        assert Settings.load(target).watch_interval == 1800
