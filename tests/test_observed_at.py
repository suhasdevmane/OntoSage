# -*- coding: utf-8 -*-
"""`latest_evidence_at` must say when the reading was TAKEN, not when we fetched it (V6-T03).

The field existed, was documented, was read by the freshness gate — and was never written.
`_sources_from` set no `observed_at`, so `latest_evidence_at` was always None and nothing in
the system could tell a reading taken a minute ago from one taken seven weeks ago. On this
building that is not a corner case: 2,796 of 2,796 declared sensors have rows and 683 report
inside 24 hours (CAVEAT-233), so most available evidence is historical and no answer said so.

Three ways deriving it from rows could be dishonest, one test each, because each of them
would produce a plausible number rather than an obvious failure:

1. **The wide-table row.** One timestamp, a column per sensor, nearly all null. Counting such
   a row regardless would date a silent sensor to whenever *any* sensor last reported — the
   per-table-max illusion of CAVEAT-233 rebuilt inside the evidence record.
2. **The naive timestamp.** Rows come back without a timezone while `retrieved_at` is UTC,
   so the naive value has to be made comparable somehow. This file originally required it to
   be read as BUILDING-LOCAL, and that was right about the risk and wrong about the direction:
   at the time, the publisher was stamping rows in BST, so reading them as BST cancelled the
   error and hid it. BUG-403 pinned every writer to UTC — the convention `mysql_adapter` had
   always claimed — which turned the compensation into the whole error, and a co2 reading
   three minutes old was scored 63 minutes old against a 5-minute policy. A stored reading is
   now read as UTC; a time a HUMAN or the ontology expressed stays building-local, because
   "between 9 and 5" means nine and five in the building.
3. **The future timestamp.** Bookings and schedules carry times too. A lane that mixed one in
   would make an answer look fresher than the data behind it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from shared.config import settings


def _fired(rec):
    """Gate verdicts recorded on a record, whichever bucket they landed in.

    A gate's verdict goes to `gates_advisory` while it only observes and to `gates_applied`
    once it acts. These tests are about whether the gate RAN, so they must read both — they
    asserted on `gates_advisory` alone and broke the moment freshness began enforcing
    (CAVEAT-361), reporting "the gate is still not being called" about a gate that had just
    downgraded the answer.
    """
    return list(getattr(rec, "gates_applied", []) or []) + list(
        getattr(rec, "gates_advisory", []) or []
    )


pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def _rec(sql_rows, **extra):
    results = {"sql_result": {"results": {"data": sql_rows}}, "uuids": ["u-1"], **extra}
    return build_evidence_record(results, now=NOW)


def test_it_reads_the_observation_time_off_the_rows():
    rec = _rec(
        [
            {"datetime": "2026-08-22T09:15:00+00:00", "value": 21.4},
            {"datetime": "2026-08-22T10:45:00+00:00", "value": 21.9},
        ]
    )
    assert rec.latest_evidence_at == datetime(2026, 8, 22, 10, 45, tzinfo=timezone.utc)


def test_retrieved_at_and_latest_evidence_at_are_different_facts():
    """The whole point of the pair. A seven-week-old reading fetched now is stale, and only
    the gap between these two fields can say so."""
    rec = _rec([{"datetime": "2026-07-04T08:00:00+00:00", "value": 3.0}])
    assert rec.retrieved_at == NOW
    assert rec.latest_evidence_at < rec.retrieved_at
    assert (rec.retrieved_at - rec.latest_evidence_at) > timedelta(days=40)


def test_an_all_null_wide_row_is_not_an_observation():
    """A wide table is one timestamp and a column per sensor. If a row with no values still
    counted, a sensor that stopped reporting in July would be dated to today — exactly the
    per-table illusion CAVEAT-233 is about, rebuilt one level down."""
    rec = _rec(
        [
            {"datetime": "2026-07-04T08:00:00+00:00", "sensor_a": 3.0},
            {"datetime": "2026-08-22T11:59:00+00:00", "sensor_a": None},
        ]
    )
    assert rec.latest_evidence_at == datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc), (
        "a row carrying only a timestamp was counted as an observation, so a silent sensor "
        "is being reported as current"
    )


def test_a_naive_reading_is_read_as_utc_because_that_is_how_it_was_stored(monkeypatch):
    """This test asserted the OPPOSITE until 2026-09-03, and both versions were defensible
    against the system as it stood at the time.

    A naive row value has to be made comparable with an aware `retrieved_at`. The original
    rule — read it as building-local — was chosen to avoid inventing freshness equal to the
    building's offset. It happened to be correct only because the writer was ALSO
    building-local: the publisher stamped narrow rows with SQL NOW() on a BST session, so
    two opposite errors cancelled and neither was visible.

    BUG-403 pinned every writer to UTC, which is the convention `mysql_adapter` had asserted
    all along. That made this compensation the entire error, and it showed immediately: a co2
    reading taken three minutes earlier was scored 63 minutes old against a 5-minute policy
    and a current answer was downgraded to INFERRED.

    Pinned with a non-UTC building timezone so the assertion is about the RULE and not about
    where this building happens to be — under the old behaviour this reads 09:15+05:30.
    """
    monkeypatch.setattr(settings, "BUILDING_TIMEZONE", "Asia/Kolkata", raising=False)
    rec = _rec([{"datetime": "2026-08-22 09:15:00", "value": 21.4}])
    assert rec.latest_evidence_at is not None
    assert rec.latest_evidence_at.tzinfo is not None, "naive timestamps cannot be compared"
    assert rec.latest_evidence_at == datetime(2026, 8, 22, 9, 15, tzinfo=timezone.utc)


def test_a_future_timestamp_is_not_treated_as_an_observation():
    """Schedules and bookings have times. One mixed into an observation lane would make the
    answer look fresher than its data."""
    rec = _rec(
        [
            {"datetime": "2026-08-22T10:00:00+00:00", "value": 20.0},
            {"datetime": "2026-09-01T10:00:00+00:00", "value": 20.0},
        ]
    )
    assert rec.latest_evidence_at == datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


def test_small_clock_skew_is_tolerated():
    """The database server's clock is not this process's clock. A reading two minutes 'ahead'
    is a real reading, and dropping it would understate freshness."""
    ahead = (NOW + timedelta(minutes=2)).isoformat()
    rec = _rec([{"datetime": ahead, "value": 20.0}])
    assert rec.latest_evidence_at is not None


def test_a_lane_that_declares_its_own_observation_time_still_wins():
    """Lane-declared provenance outranks anything inferred from rows — the lane knows which
    uuid each row belonged to and the bus does not."""
    declared = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)
    rec = build_evidence_record(
        {
            "sql_result": {
                "results": {"data": [{"datetime": "2026-08-22T10:00:00+00:00", "v": 1}]}
            },
            "_prov_stores": [{"source_id": "u-1", "kind": "sensor", "store": "mysql:co2_data"}],
            "evidence": {"latest_evidence_at": declared},
        },
        now=NOW,
    )
    assert rec.latest_evidence_at == declared


def test_a_documentary_answer_gets_no_observation_time():
    """A passage from a manual was not observed at a moment. Inventing one would let a policy
    lookup claim currency it cannot have."""
    rec = build_evidence_record({"capability_result": {"answer": "the policy says ..."}}, now=NOW)
    assert rec.latest_evidence_at is None


def test_rows_with_no_recognisable_time_column_leave_it_unset():
    """Unknown is a legitimate answer and must not be replaced by `now`, which would assert
    freshness the data never claimed."""
    rec = _rec([{"label": "Room 2.14", "count": 7}])
    assert rec.latest_evidence_at is None


def test_the_sources_carry_the_time_too():
    """A reader holding one source should not have to go back to the record to learn its age."""
    rec = _rec([{"datetime": "2026-08-22T10:45:00+00:00", "value": 21.9}])
    sensors = [s for s in rec.sources if s.kind == "sensor"]
    assert sensors and all(s.observed_at is not None for s in sensors)


# ── attribution: the live failure this nearly shipped with ───────────────────


def test_a_live_sensor_cannot_certify_a_stale_one():
    """The defect a live probe caught minutes after wiring, and the reason observed_at is
    attributed per sensor rather than maxed over the result set.

    Asking "what is the CO2 in the lecture theatre right now?" produced
    `latest_evidence_at` forty seconds old while the answer's own prose cited a reading
    "measured at 09:51 AM". Both were real: narrow `co2_data` stops two days back and is what
    the answer rests on, while wide `sensor_data` runs to now because of the intentional dev
    top-up, and a row of it for an UNRELATED sensor shared the result set. Taking the maximum
    certified a two-day-old answer as current — the precise dishonesty the field exists to
    prevent, and a freshness gate fed that number would have passed the answer it exists to
    catch.
    """
    stale = "2026-08-20T09:51:00+00:00"  # the CO2 sensor the answer actually used
    fresh = "2026-08-22T11:59:20+00:00"  # an unrelated sensor in the same result set
    rec = build_evidence_record(
        {
            "sql_result": {
                "results": {
                    "data": [
                        {"uuid": "co2-sensor", "datetime": stale, "value": 939.0},
                        {"uuid": "other-sensor", "datetime": fresh, "value": 21.0},
                    ]
                }
            },
            "_prov_stores": [
                {"source_id": "co2-sensor", "kind": "sensor", "store": "mysql:co2_data"},
                {"source_id": "other-sensor", "kind": "sensor", "store": "mysql:sensor_data"},
            ],
        },
        now=NOW,
    )
    by_id = {s.source_id: s.observed_at for s in rec.sources}
    assert by_id["co2-sensor"] == datetime(
        2026, 8, 20, 9, 51, tzinfo=timezone.utc
    ), "the stale sensor was given another sensor's timestamp"
    assert by_id["other-sensor"] == datetime(2026, 8, 22, 11, 59, 20, tzinfo=timezone.utc)


def test_a_wide_row_attributes_each_column_to_its_own_sensor():
    """In the wide table the uuid IS the column name, so a row is attributable without
    guessing — and a NULL column is not an observation of that sensor."""
    rec = build_evidence_record(
        {
            "sql_result": {
                "results": {
                    "data": [
                        {
                            "Datetime": "2026-08-22T11:00:00+00:00",
                            "00000000-ac01-0000-0000-000000000001": 21.0,
                            "00000000-ac01-0000-0000-000000000002": None,
                        },
                        {
                            "Datetime": "2026-08-22T11:30:00+00:00",
                            "00000000-ac01-0000-0000-000000000001": 21.5,
                            "00000000-ac01-0000-0000-000000000002": None,
                        },
                    ]
                }
            },
            "_prov_stores": [
                {"source_id": "00000000-ac01-0000-0000-000000000001", "kind": "sensor"},
                {"source_id": "00000000-ac01-0000-0000-000000000002", "kind": "sensor"},
            ],
        },
        now=NOW,
    )
    by_id = {s.source_id: s.observed_at for s in rec.sources}
    assert by_id["00000000-ac01-0000-0000-000000000001"] == datetime(
        2026, 8, 22, 11, 30, tzinfo=timezone.utc
    )
    assert by_id["00000000-ac01-0000-0000-000000000002"] is None, (
        "a sensor whose column was null in every row was dated anyway — a silent sensor "
        "reported as reporting"
    )


def test_the_freshness_gate_judges_the_stalest_ingredient():
    """`latest_evidence_at` keeps its documented meaning (the NEWEST observation), and the
    gate deliberately asks a different question, because an answer is only as current as the
    oldest thing it rests on."""
    rec = build_evidence_record(
        {
            "sql_result": {
                "results": {
                    "data": [
                        {"uuid": "a", "datetime": "2026-06-01T00:00:00+00:00", "value": 1.0},
                        {"uuid": "b", "datetime": "2026-08-22T11:59:00+00:00", "value": 2.0},
                    ]
                }
            },
            "concepts": [{"brick_classes": ["brick:Air_Temperature_Sensor"]}],
            "_prov_stores": [
                {"source_id": "a", "kind": "sensor"},
                {"source_id": "b", "kind": "sensor"},
            ],
        },
        now=NOW,
    )
    assert rec.latest_evidence_at == datetime(2026, 8, 22, 11, 59, tzinfo=timezone.utc)
    assert _fired(rec), (
        "a nearly-three-month-old contributing reading raised no freshness verdict — the gate "
        "is still judging the newest evidence instead of the oldest"
    )
    assert any("freshness" in g for g in _fired(rec))
