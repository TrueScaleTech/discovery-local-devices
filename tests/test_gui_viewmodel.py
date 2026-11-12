"""What the desktop window shows, decided without any Qt."""

from __future__ import annotations

from datetime import timedelta

from discovery_now.gui.viewmodel import (
    Filter,
    address_key,
    ago,
    automatic_name,
    counts,
    event_title,
    matches_query,
    passes,
    scan_summary,
    stage_title,
)
from discovery_now.models import Device, Event, EventKind, utcnow

WEEK = timedelta(days=7)


def device(
    *,
    ident: int = 1,
    ip: str = "192.168.1.10",
    online: bool = True,
    approved: bool = False,
    age: timedelta = timedelta(days=30),
    **extra: object,
) -> Device:
    moment = utcnow()
    values: dict[str, object] = {
        "key": f"ip:{ip}",
        "mac": None,
        "hostname": None,
        "vendor": None,
        "label": None,
        "notes": None,
        "misses": 0,
    }
    values.update(extra)
    return Device(
        id=ident,
        ip=ip,
        online=online,
        approved=approved,
        first_seen=moment - age,
        last_seen=moment,
        **values,  # type: ignore[arg-type]
    )


class TestQuickFilters:
    def test_all_lets_everything_through(self) -> None:
        assert passes(device(), Filter.ALL, new_within=WEEK)

    def test_online_and_offline_split_the_list(self) -> None:
        assert passes(device(online=True), Filter.ONLINE, new_within=WEEK)
        assert not passes(device(online=False), Filter.ONLINE, new_within=WEEK)
        assert passes(device(online=False), Filter.OFFLINE, new_within=WEEK)

    def test_new_means_recently_first_seen(self) -> None:
        assert passes(device(age=timedelta(days=1)), Filter.NEW, new_within=WEEK)
        assert not passes(device(age=timedelta(days=30)), Filter.NEW, new_within=WEEK)

    def test_unapproved_means_not_yet_vetted(self) -> None:
        assert passes(device(approved=False), Filter.UNAPPROVED, new_within=WEEK)
        assert not passes(device(approved=True), Filter.UNAPPROVED, new_within=WEEK)

    def test_the_counts_match_the_filters(self) -> None:
        listed = [
            device(ident=1, online=True, approved=True),
            device(ident=2, online=False, age=timedelta(hours=2)),
            device(ident=3, online=True),
        ]
        tally = counts(listed, new_within=WEEK)
        assert tally == {
            Filter.ALL: 3,
            Filter.ONLINE: 2,
            Filter.OFFLINE: 1,
            Filter.NEW: 1,
            Filter.UNAPPROVED: 2,
        }


class TestSearch:
    def test_an_empty_search_matches_everything(self) -> None:
        assert matches_query(device(), "")
        assert matches_query(device(), "   ")

    def test_finds_by_name_address_mac_and_vendor(self) -> None:
        found = device(
            ip="192.168.1.77",
            mac="00:11:22:33:44:05",
            hostname="hp-printer.home",
            vendor="Example Print Co",
        )
        for query in ("printer", "1.77", "33:44", "example print"):
            assert matches_query(found, query), query

    def test_finds_by_the_guessed_kind(self) -> None:
        # The kind is not stored anywhere: it is worked out, and still searchable.
        assert matches_query(device(hostname="tablet-ana.home"), "tablet")

    def test_finds_by_notes_and_label(self) -> None:
        found = device(label="Family NAS", notes="hallway cabinet")
        assert matches_query(found, "family")
        assert matches_query(found, "cabinet")

    def test_every_word_has_to_match(self) -> None:
        found = device(hostname="hp-printer.home")
        assert matches_query(found, "printer home")
        assert not matches_query(found, "printer camera")

    def test_case_does_not_matter(self) -> None:
        assert matches_query(device(hostname="Marias-iPhone"), "MARIAS")


class TestWording:
    def test_addresses_sort_numerically(self) -> None:
        assert address_key("192.168.1.9") < address_key("192.168.1.10")

    def test_an_unreadable_address_sorts_last(self) -> None:
        assert address_key("fe80::1") > address_key("192.168.1.1")

    def test_ago_uses_the_words_a_person_would(self) -> None:
        now = utcnow()
        assert ago(now - timedelta(seconds=20), now=now) == "just now"
        assert ago(now - timedelta(minutes=5), now=now) == "5 min ago"
        assert ago(now - timedelta(hours=3), now=now) == "3 h ago"
        assert ago(now - timedelta(days=4), now=now) == "4 d ago"

    def test_the_automatic_name_prefers_the_hostname_then_the_maker(self) -> None:
        assert automatic_name(device(hostname="nas.home", vendor="Example")) == "nas.home"
        assert automatic_name(device(vendor="Example Storage")) == "Example Storage"
        assert automatic_name(device(ip="192.168.1.9")) == "192.168.1.9"

    def test_every_kind_of_event_has_a_title(self) -> None:
        for kind in EventKind:
            event = Event(id=1, device_id=1, kind=kind, detail="", at=utcnow())
            title = event_title(event)
            assert title
            assert "_" not in title  # never the raw stored word

    def test_a_scan_is_summarised_in_one_line(self) -> None:
        assert scan_summary(1) == "1 device answered"
        assert scan_summary(8, new=2, gone=1) == "8 devices answered, 2 new, 1 went offline"

    def test_scan_stages_read_as_plain_words(self) -> None:
        assert stage_title("ping sweep") == "Looking for devices"
        assert stage_title("something else") == "Something else"
