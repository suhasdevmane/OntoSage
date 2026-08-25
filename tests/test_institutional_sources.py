# -*- coding: utf-8 -*-
"""Institutional-context sources: the R2 unlock (V6-T25).

303 of the supervisors' 480 questions are integration-dependent and timetable/booking is the
most frequently named. Sensors already had a declare-and-connect contract; institutional data
had none, so every "is this room booked" question was blocked on a bespoke integration nobody
would write per building.

The contract is the deliverable, and these are its load-bearing properties:

1. **Declaring a source is config, never code.** A building adds a `timetable` entry to its
   own `feeds.yaml` and the registry dispatches it like any other feed. Design contract #9.
2. **An unknown room is skipped and NAMED, never guessed.** A timetable that silently bound
   "LT-2" to the nearest match would feed confident wrong answers into the availability lane
   — and availability is one of the four entitlement claims that must never be inferred
   (rule R-8).
3. **Records land in the EXISTING events store.** A parallel booking table would need its own
   query path, availability logic and status vocabulary, and would drift from the one the
   events lane already uses — the BUG-210 shape.
4. **The observability matrix reads real declarations.** It previously hardcoded "no booking
   system connected", which was true on the day and would have stayed "true" in the report
   the moment someone connected one.
"""

from datetime import datetime
from pathlib import Path

import pytest

from orchestrator.services.feeds.institutional import (
    SOURCE_KINDS,
    InstitutionalRecord,
    declared_systems,
    parse_csv,
)

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "institutional" / "timetable_sample.csv"
KNOWN = ["Room5.16", "Room5.03", "Room2.14"]


def _parse():
    return parse_csv(
        FIXTURE.read_text(encoding="utf-8"),
        "timetable_2026",
        KNOWN,
        space_field="room",
        start_field="start",
        end_field="end",
        title_field="module",
    )


# ── the contract ─────────────────────────────────────────────────────────────


def test_a_building_declares_a_timetable_the_same_way_it_declares_a_sensor_feed():
    """Config, not code — this sameness IS the R2 unlock."""
    from orchestrator.services.feeds.base import FeedSpec

    spec = FeedSpec(
        id="tt", type="timetable", path="institutional/timetable.csv", space_field="room"
    )
    assert spec.type == "timetable" and spec.space_field == "room"


def test_every_institutional_kind_is_dispatchable():
    """A kind the spec accepts but the registry cannot build is dead config — the shape of
    defect the 2026-08-23 audit found ten times."""
    from orchestrator.services.feeds.registry import _ADAPTER_CLASSES

    for kind in SOURCE_KINDS:
        assert kind in _ADAPTER_CLASSES, f"{kind} is accepted by FeedSpec but has no adapter"


def test_records_become_rows_in_the_existing_events_store():
    recs, _ = _parse()
    ev = recs[0].as_event("bldg1")
    assert ev["event_type"] == "booking", "a parallel store would drift from the events lane"
    assert ev["subject_uuid"], "a timetable row must join to a space like any booking"
    assert ev["status"] == "scheduled"


def test_the_subject_uuid_matches_the_event_frameworks_own_derivation():
    """Same join key the synthetic bookings use, or a timetable row and a booking for the
    same room would never appear in one availability answer."""
    from orchestrator.services.datasource_registry import derive_point_uuid

    recs, _ = _parse()
    expected = derive_point_uuid("bldg1", "evt_subject", "Room5.16")
    assert recs[0].as_event("bldg1")["subject_uuid"] == expected


# ── the honesty property ─────────────────────────────────────────────────────


def test_an_unknown_room_is_skipped_and_named():
    """The fixture contains LT-NOT-A-REAL-ROOM deliberately."""
    recs, report = _parse()
    assert all(r.space_local in KNOWN for r in recs)
    assert "LT-NOT-A-REAL-ROOM" in report.unresolved_spaces
    assert "SKIPPED, not guessed" in report.describe()


def test_an_unparseable_time_is_skipped_rather_than_defaulted():
    """Defaulting to 'now' would schedule a lecture at ingest time."""
    _, report = _parse()
    assert report.bad_rows >= 1


def test_the_report_states_what_it_refused():
    """A silent ingest that drops rows is indistinguishable from a source with fewer rows."""
    _, report = _parse()
    text = report.describe()
    assert "4 record(s) parsed" in text
    assert "LT-NOT-A-REAL-ROOM" in text


def test_a_good_row_survives_alongside_the_bad_ones():
    """One malformed row must not cost the whole import."""
    recs, _ = _parse()
    assert len(recs) == 4
    assert recs[0].title.startswith("CM2101")


# ── the matrix closes its own caveat ─────────────────────────────────────────


def test_declared_systems_reflects_what_the_building_declared():
    from orchestrator.services.feeds.base import FeedSpec

    none_declared = declared_systems([FeedSpec(id="w", type="rest_poll", url="http://x")])
    assert none_declared == []

    with_timetable = declared_systems(
        [
            FeedSpec(id="w", type="rest_poll", url="http://x"),
            FeedSpec(id="tt", type="timetable", path="a.csv"),
        ]
    )
    assert with_timetable == ["booking system"]


def test_a_disabled_source_is_not_a_connected_system():
    """Declared-but-off is not connected; reporting it as connected would tell the matrix a
    gap is closed when nothing is feeding it."""
    from orchestrator.services.feeds.base import FeedSpec

    assert (
        declared_systems([FeedSpec(id="tt", type="timetable", path="a.csv", enabled=False)]) == []
    )


def test_the_matrix_no_longer_hardcodes_an_empty_system_list():
    src = Path("scripts/build_observability_matrix.py").read_text(encoding="utf-8")
    assert (
        'facts["connected_systems"] = []' not in src
    ), "the matrix would keep reporting 'no booking system connected' after one was"
    assert "_declared_systems()" in src


# ── portability ──────────────────────────────────────────────────────────────


def test_a_missing_export_file_is_an_honest_empty_read_not_a_crash():
    """A building that declared a source it has not dropped yet must decline honestly, not
    fail to boot."""
    from orchestrator.services.feeds.base import FeedSpec
    from orchestrator.services.feeds.institutional import InstitutionalFeedAdapter

    adapter = InstitutionalFeedAdapter(
        FeedSpec(id="tt", type="timetable", path="institutional/not_there.csv")
    )
    recs, report = adapter.read(KNOWN)
    assert recs == [] and report.parsed == 0


def test_the_module_carries_no_building_literal():
    src = Path("orchestrator/services/feeds/institutional.py").read_text(encoding="utf-8").lower()
    for literal in ("abacws", "bldg1", "cardiff", "room5.16"):
        assert literal not in src, f"building literal {literal!r} in the institutional adapter"


def test_column_names_are_declared_not_sniffed_widely():
    """Guessing widely is how a column called 'notes' becomes a room name. The default list
    is deliberately short and the spec can override every field."""
    from orchestrator.services.feeds.institutional import _DEFAULT_FIELDS

    for kind, candidates in _DEFAULT_FIELDS.items():
        assert len(candidates) <= 5, f"{kind} default list has grown to {len(candidates)}"


def test_a_declared_field_name_wins_over_the_defaults():
    text = "venue,begins,ends,what\nRoom5.03,2026-09-01 09:00,2026-09-01 10:00,Lecture\n"
    recs, _ = parse_csv(
        text,
        "src",
        KNOWN,
        space_field="venue",
        start_field="begins",
        end_field="ends",
        title_field="what",
    )
    assert len(recs) == 1 and recs[0].space_local == "Room5.03"
    assert recs[0].title == "Lecture"


def test_records_declare_their_source():
    """Provenance travels with the row: a reader must be able to tell a timetable import from
    a hand-entered booking."""
    recs, _ = _parse()
    import json

    attrs = json.loads(recs[0].as_event("bldg1")["attrs"])
    assert attrs["source"] == "timetable_2026"


def test_an_open_ended_record_keeps_a_null_end():
    r = InstitutionalRecord("Room5.16", datetime(2026, 9, 1, 9, 0), None, "Open lab", "src")
    assert r.as_event("bldg1")["end_dt"] is None
