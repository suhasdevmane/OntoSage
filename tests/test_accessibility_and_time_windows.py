# -*- coding: utf-8 -*-
"""Accessibility hard filter (V6-T38) and recurring time windows (V6-T40).

**T38 is the highest-consequence logic in V6.** Every other failure here produces a wrong
number; this one strands a person. The asymmetry is deliberate: filter rather than rank,
exclude rather than caveat, and treat an explained empty result as a valid answer.

**T40** unlocks a family of questions that are currently unanswerable for a structural
reason rather than a data one -- night baselines, after-hours energy, "full by lunchtime".
The two traps are wrapping windows (22:00-06:00 is not a range) and inventing a schedule for
a building that never declared one.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.accessibility import (
    AccessibilityRequirement,
    AccessibleOption,
    filter_options,
)
from orchestrator.services.evidence.time_windows import (
    HourMask,
    detect_mask,
    filter_samples,
    nightly_minimums,
)

pytestmark = pytest.mark.unit


# ── T38: accessibility ───────────────────────────────────────────────────────

STEP_FREE = AccessibilityRequirement(step_free=True)


def test_unverified_route_is_excluded_not_caveated():
    """A caveat is read after the person has decided to take the route, if at all."""
    res = filter_options([AccessibleOption("r1", "West stair route", verified=False)], STEP_FREE)
    assert res.admissible == []
    assert not res.has_answer
    assert "not been verified" in res.explain_empty()


def test_verified_route_is_admissible():
    res = filter_options([AccessibleOption("r1", "Lift route", verified=True)], STEP_FREE)
    assert len(res.admissible) == 1


def test_a_failed_lift_invalidates_a_verified_route():
    """A verified route through a failed lift is not a verified route TODAY.

    Checked before verification because the verification record is the thing most likely to
    mislead: it was true when it was written.
    """
    res = filter_options(
        [AccessibleOption("r1", "Lift route", verified=True, depends_on=("lift1",))],
        STEP_FREE,
        out_of_service={"lift1"},
    )
    assert res.admissible == []
    assert "out of service" in res.explain_empty()


def test_both_failing_yields_an_explained_empty_result():
    """The catalogues ask for neither to be recommended AND for that to be said."""
    res = filter_options(
        [
            AccessibleOption("r1", "Route A", verified=False),
            AccessibleOption("r2", "Route B", verified=True, depends_on=("lift1",)),
        ],
        STEP_FREE,
        out_of_service={"lift1"},
    )
    assert not res.has_answer
    text = res.explain_empty("Estates on x1234")
    assert "Route A" in text and "Route B" in text
    assert "x1234" in text


def test_empty_explanation_says_why_it_refuses_when_no_contact_is_known():
    res = filter_options([AccessibleOption("r1", "Route A", verified=False)], STEP_FREE)
    assert "stranded" in res.explain_empty()


def test_a_required_feature_that_is_absent_rejects_the_option():
    res = filter_options(
        [AccessibleOption("r1", "Room 2.15", verified=True, kinds=("accessible_wc",))],
        AccessibilityRequirement(kinds=("hearing_loop",)),
    )
    assert not res.has_answer
    assert "does not provide hearing_loop" in res.explain_empty()


def test_no_requirement_means_no_filtering():
    """The hard filter must not quietly narrow questions that never mentioned accessibility."""
    opts = [AccessibleOption("r1", verified=False), AccessibleOption("r2", verified=False)]
    res = filter_options(opts, AccessibilityRequirement())
    assert len(res.admissible) == 2


def test_nothing_recorded_is_distinct_from_nothing_qualifying():
    res = filter_options([], STEP_FREE)
    assert "No route or facility of that kind is recorded" in res.explain_empty()


# ── T40: recurring windows ───────────────────────────────────────────────────


def test_night_window_wraps_midnight():
    """22:00-06:00 is not a range; treating it as one silently returns nothing."""
    m = HourMask(22, 6)
    assert m.wraps
    assert m.covers(datetime(2026, 8, 21, 23, 0))
    assert m.covers(datetime(2026, 8, 21, 2, 0))
    assert not m.covers(datetime(2026, 8, 21, 12, 0))


def test_ordinary_window_does_not_wrap():
    m = HourMask(9, 17)
    assert not m.wraps
    assert m.covers(datetime(2026, 8, 21, 12, 0))
    assert not m.covers(datetime(2026, 8, 21, 20, 0))


def test_sql_predicate_handles_both_shapes():
    assert " OR " in HourMask(22, 6).sql_predicate()
    assert " AND " in HourMask(9, 17).sql_predicate()


def test_predicate_is_pushed_down_not_filtered_in_python():
    """Filtering after the fetch drags a month of rows over the wire for six hours of data."""
    sql = HourMask(22, 6).sql_predicate("ts")
    assert "HOUR(ts)" in sql


def test_weekday_and_weekend_restrictions():
    weekday = HourMask(0, 24, weekdays_only=True)
    saturday = datetime(2026, 8, 22, 12, 0)
    assert saturday.weekday() == 5
    assert not weekday.covers(saturday)
    assert HourMask(0, 24, weekends_only=True).covers(saturday)


@pytest.mark.parametrize(
    "phrase,expect_wrap",
    [("what is our overnight water flow", True), ("usage at night", True)],
)
def test_night_phrases_are_detected(phrase, expect_wrap):
    m = detect_mask(phrase)
    assert m is not None and m.wraps is expect_wrap


def test_lunchtime_and_morning_are_detected():
    assert detect_mask("are the bins full by lunchtime").start_hour == 11
    assert detect_mask("how busy is it in the morning").start_hour == 6


def test_a_question_with_no_recurring_window_returns_none():
    """None means 'no window asked for', never 'use business hours'."""
    assert detect_mask("what is the temperature in room 2.15") is None


def test_after_hours_declines_without_the_buildings_own_schedule():
    """Guessing a schedule answers a different question and looks authoritative doing it."""
    assert detect_mask("after hours energy use") is None


def test_after_hours_uses_the_buildings_declared_schedule():
    m = detect_mask("after hours energy use", occupied_start_hour=7, occupied_end_hour=21)
    assert m is not None
    assert m.start_hour == 21 and m.end_hour == 7
    assert m.wraps


def test_in_hours_uses_the_buildings_schedule_and_weekdays():
    m = detect_mask("during working hours", occupied_start_hour=7, occupied_end_hour=21)
    assert m.start_hour == 7 and m.end_hour == 21
    assert m.weekdays_only


def test_filter_samples_applies_the_mask():
    day = datetime(2026, 8, 21, 0, 0)
    samples = [(day + timedelta(hours=h), float(h)) for h in range(24)]
    kept = filter_samples(samples, HourMask(22, 6))
    assert {t.hour for t, _ in kept} == {22, 23, 0, 1, 2, 3, 4, 5}


def test_filter_samples_without_a_mask_keeps_everything():
    samples = [(datetime(2026, 8, 21, h), 1.0) for h in range(24)]
    assert len(filter_samples(samples, None)) == 24


def test_nightly_minimums_bucket_a_night_to_the_day_it_started():
    """02:00 Tuesday belongs to Monday night.

    Bucketing by calendar date would split every night in two and halve the apparent
    minimum -- which is the number the whole slow-leak test depends on.
    """
    mask = HourMask(22, 6)
    samples = [
        (datetime(2026, 8, 21, 23, 0), 5.0),
        (datetime(2026, 8, 22, 1, 0), 3.0),
        (datetime(2026, 8, 22, 23, 0), 4.0),
    ]
    out = dict(nightly_minimums(samples, mask))
    assert len(out) == 2
    assert out["2026-08-21"] == 3.0  # both sides of midnight in one bucket


def test_nightly_minimums_ignore_daytime_samples():
    mask = HourMask(22, 6)
    samples = [(datetime(2026, 8, 21, 12, 0), 0.1), (datetime(2026, 8, 21, 23, 0), 5.0)]
    assert dict(nightly_minimums(samples, mask)) == {"2026-08-21": 5.0}
