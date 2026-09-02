# -*- coding: utf-8 -*-
"""A point must not be read from a store that provably predates the question (BUG-378).

Room 5.04 on bldg1 has two temperature points: a real sensor in the wide store holding 1,045
readings on the requested date, and a synthetic `_sat_` overlay point on a narrow table frozen
five days earlier. The lane read the frozen one and said "No data found".

665 of the 728 points on the eight frozen stores are that same synthetic overlay shadowing a
live sensor, so this is a broad selection defect, not one room's bad luck.

The safety property throughout: **unknown is not stale**. A store that cannot be probed must
still be read, because turning a transient adapter error into a skipped sensor is a worse
failure than the one being fixed.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services import store_coverage as sc

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 31, 17, 0, 0)
FROZEN = datetime(2026, 8, 26, 13, 36, 0)


@pytest.fixture(autouse=True)
def _clear():
    sc.reset_cache()
    yield
    sc.reset_cache()


# ── store key normalisation ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "http://abacwsbuilding.cardiff.ac.uk/abacws#temperature_data",
        "bldg:temperature_data",
        "temperature_data",
        "  temperature_data  ",
    ],
)
def test_a_store_is_recognised_however_the_lane_spells_it(raw):
    """The graph carries an IRI, the registry a bare key, prompts sometimes a prefix."""
    assert sc._store_key(raw) == "temperature_data"


def test_an_absent_store_normalises_to_empty_rather_than_raising():
    assert sc._store_key(None) == ""


# ── coverage is tri-state ──────────────────────────────────────────────────────────────


def test_a_store_frozen_before_the_window_provably_cannot_answer():
    assert sc.covers(FROZEN, datetime(2026, 8, 29)) is False


def test_a_current_store_can_answer():
    assert sc.covers(NOW, datetime(2026, 8, 29)) is True


def test_a_store_that_stops_mid_window_is_still_read():
    """It holds part of the answer; excluding it would discard real evidence."""
    assert sc.covers(datetime(2026, 8, 29, 12, 0), datetime(2026, 8, 29)) is True


def test_an_unprobed_store_is_unknown_not_stale():
    assert sc.covers(None, datetime(2026, 8, 29)) is None


def test_an_unbounded_window_is_unknown_not_stale():
    """'What is the temperature?' has no start; nothing can be excluded on that basis."""
    assert sc.covers(FROZEN, None) is None


def test_the_grace_window_tolerates_a_boundary_reading():
    """A store whose last reading is minutes before the window still plausibly covers it."""
    assert sc.covers(datetime(2026, 8, 28, 23, 30), datetime(2026, 8, 29)) is True


# ── partitioning ───────────────────────────────────────────────────────────────────────


def test_the_frozen_point_is_set_aside_and_the_live_one_is_kept():
    """The exact bldg1 room-5.04 shape."""
    usable, skipped, reasons = sc.partition_by_coverage(
        ["live-uuid", "sat-uuid"],
        {"live-uuid": "bldg:database1", "sat-uuid": "bldg:temperature_data"},
        {"database1": NOW, "temperature_data": FROZEN},
        datetime(2026, 8, 29),
    )
    assert usable == ["live-uuid"]
    assert skipped == ["sat-uuid"]
    assert "temperature_data has nothing after 2026-08-26" in reasons["sat-uuid"]


def test_a_point_on_an_unknown_store_is_kept():
    """Unknown is not stale — the safety property."""
    usable, skipped, _ = sc.partition_by_coverage(
        ["u1"], {"u1": "bldg:mystery"}, {}, datetime(2026, 8, 29)
    )
    assert usable == ["u1"] and skipped == []


def test_nothing_is_skipped_when_the_window_is_unbounded():
    usable, skipped, _ = sc.partition_by_coverage(
        ["u1"], {"u1": "bldg:temperature_data"}, {"temperature_data": FROZEN}, None
    )
    assert usable == ["u1"] and skipped == []


def test_every_point_may_be_skipped_and_that_is_reported_not_hidden():
    """When nothing can cover the window the caller must be able to say WHY, not 'no data'."""
    usable, skipped, reasons = sc.partition_by_coverage(
        ["a", "b"],
        {"a": "bldg:co2_data", "b": "bldg:humidity_data"},
        {"co2_data": FROZEN, "humidity_data": FROZEN},
        datetime(2026, 8, 29),
    )
    assert usable == [] and len(skipped) == 2 and len(reasons) == 2


# ── disclosure ─────────────────────────────────────────────────────────────────────────


def test_a_dropped_point_is_named_with_its_store():
    text = sc.describe_skipped(
        {"sat-uuid": "temperature_data has nothing after 2026-08-26 13:36"},
        {"sat-uuid": {"label": "Room5.04_sat_temperature"}},
    )
    assert "Room5.04_sat_temperature" in text
    assert "temperature_data" in text


def test_nothing_dropped_says_nothing():
    assert sc.describe_skipped({}) == ""


def test_many_dropped_points_are_summarised_rather_than_listed_forever():
    reasons = {f"u{i}": "store X is empty" for i in range(9)}
    text = sc.describe_skipped(reasons)
    assert "and 6 more" in text


def test_an_unlabelled_point_still_gets_named_somehow():
    text = sc.describe_skipped({"abcdef1234": "store X is empty"}, {})
    assert "abcdef12" in text


# ── per-sensor freshness beats store-level (2026-09-02) ───────────────────────────────


def test_a_dead_sensor_in_a_live_store_is_still_dropped():
    """noise_data reports today because ONE of its 236 sensors writes; 235 are 8 days dead."""
    usable, skipped, reasons = sc.partition_by_coverage(
        ["dead-sensor", "live-sensor"],
        {"dead-sensor": "bldg:noise_data", "live-sensor": "bldg:noise_data"},
        {"noise_data": NOW},  # the STORE looks current
        datetime(2026, 8, 29),
        latest_by_uuid={"dead-sensor": datetime(2026, 8, 25, 2, 24), "live-sensor": NOW},
    )
    assert usable == ["live-sensor"]
    assert skipped == ["dead-sensor"]
    assert "this sensor" in reasons["dead-sensor"]


def test_a_sensor_with_no_per_uuid_entry_falls_back_to_its_store():
    """Wide tables report store-level only; those points must still be judged."""
    usable, skipped, _ = sc.partition_by_coverage(
        ["wide-uuid"],
        {"wide-uuid": "bldg:temperature_data"},
        {"temperature_data": FROZEN},
        datetime(2026, 8, 29),
        latest_by_uuid={},
    )
    assert usable == [] and skipped == ["wide-uuid"]


def test_a_sensor_with_no_readings_at_all_says_so():
    _, skipped, reasons = sc.partition_by_coverage(
        ["never-written"],
        {"never-written": "bldg:noise_data"},
        {"noise_data": NOW},
        datetime(2026, 8, 29),
        latest_by_uuid={"never-written": None},
    )
    assert skipped == ["never-written"]
    assert "no readings at all" in reasons["never-written"]


def test_a_failed_per_uuid_probe_must_not_mark_every_sensor_dead():
    """The dangerous direction: a transient DB error silencing working sensors.

    The adapter returns an EMPTY map on query failure, never all-None, precisely so this
    cannot happen — a present key with a None value is proof of absence, and a failed query
    proves nothing.
    """
    usable, skipped, _ = sc.partition_by_coverage(
        ["u1", "u2"],
        {"u1": "bldg:noise_data", "u2": "bldg:noise_data"},
        {"noise_data": NOW},
        datetime(2026, 8, 29),
        latest_by_uuid={},  # what a failed probe returns
    )
    assert set(usable) == {"u1", "u2"} and skipped == []
