# -*- coding: utf-8 -*-
"""BUG-939 — the fetch covers the period the question names, and says when it does not.

WHAT WAS MEASURED, AND WHAT IT ESTABLISHED
------------------------------------------
On 2026-09-29 "Compare energy use this week against last week" reached the store as

    WHERE datetime >= DATE_SUB(NOW(), INTERVAL 30 DAY) ... ORDER BY datetime DESC
    LIMIT 1000                                                              -- per uuid

and the lane's own guard fired: "[sql] group energy_data returned exactly its 1000-row
limit — the set is TRUNCATED". Neither builder is at fault; both apply that 30-day default
only in an `elif not end` branch, so the bounds were never set.

The open question was whether `start_date`/`end_date` were EMPTY on the bus or merely not
forwarded. Measured on 2026-09-30 by calling the classifier directly, six questions, one
per shape — the answer is NEITHER, consistently:

    "Compare energy use this week against last week."       2026-09-16 .. 2026-09-30
                                                            (a rolling 14 days, non-empty
                                                             and not the weeks named)
    "How does the temperature in room 5.01 this week
     compare with last week?"                               null .. null
    "What was the energy use last month?"                    2026-08-01 .. 2026-08-31
                                                            (right dates, and the end has
                                                             no time, so `<=` keeps only
                                                             the first instant of the 31st)
    "Will floor 3 or floor 4 be warmer tomorrow?"            now .. "now+1d"
                                                            (an end no resolver here parses,
                                                             and a start in the FUTURE)

They ARE forwarded — `_orchestrator` reads them off the bus and passes them to
`fetch_data_for_uuids`. The bounds themselves are the defect: the same question shape
yields a wrong window, no window, or a window in the future, depending on wording.

WHAT THESE TESTS PIN
--------------------
  the arithmetic   week / month / quarter / year bounds, built HERE from plain date
                   arithmetic and never by calling the resolver, which would let a wrong
                   resolver certify itself
  the refusals     a trailing duration wearing a calendar word ("over the last week"), two
                   different units, and a named DAY all leave the compiled range alone
  the zone         the period is chosen in the building's zone and CONVERTED to the stores'
                   UTC clock — the rule three withdrawn fixes and a withdrawn P1 came from
  the coupling     the span these bounds produce still buckets by the unit the question
                   named, checked by calling `series_summary._bucket_size` rather than by
                   remembering that it needs 1.5 units
  the future       a window starting in the future is dropped rather than queried
  the cap          a truncated fetch says so, in the answer, with the span it really covers
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents import sql_agent  # noqa: E402
from orchestrator.agents.sql_agent import SQLAgent, resolve_named_window  # noqa: E402
from orchestrator.services.requested_interval import (  # noqa: E402
    STAMP,
    calendar_period_bounds,
    named_period,
    to_store,
)
from orchestrator.services.series_summary import _bucket_size  # noqa: E402

#: A Wednesday in ISO week 2026-W40 — the day BUG-936 and BUG-939 were both measured on,
#: and the worst case for the bucket-size coupling below.
WED = datetime(2026, 9, 30, 5, 30, 0)


def _iso_monday(day: date, weeks_back: int) -> date:
    """Monday of the ISO week `weeks_back` weeks before the one holding `day`."""
    return day - timedelta(days=day.isoweekday() - 1) - timedelta(weeks=weeks_back)


def _expect(start_local: datetime, end_local: datetime, tz: str = None):
    """The bounds a correct resolver must produce, in store (UTC) stamps."""
    return (
        to_store(start_local, tz).strftime(STAMP),
        to_store(end_local, tz).strftime(STAMP),
    )


# ── the arithmetic ───────────────────────────────────────────────────────────


def test_a_week_pair_covers_both_weeks_named():
    """ "this week against last week" — W39 and W40, whole, on a Wednesday inside W40."""
    got = calendar_period_bounds("Compare energy use this week against last week.", None, WED)
    # W38's Monday, because a pair reaches one whole unit further back (see below), through
    # to the last second of W40's Sunday.
    assert got == _expect(
        datetime.combine(_iso_monday(WED.date(), 2), datetime.min.time()),
        datetime.combine(_iso_monday(WED.date(), 0) + timedelta(days=6), datetime.min.time())
        + timedelta(hours=23, minutes=59, seconds=59),
    )
    assert named_period("Compare energy use this week against last week.") == ("week", [0, 1])


def test_the_weeks_named_are_the_two_newest_whole_weeks_in_the_span():
    """The margin is context, not a third period the comparison may pick up.

    `series_summary._names_this_against_last` takes `ordered[-2]` and `ordered[-1]`, so the
    two newest ISO weeks inside these bounds must be exactly the two the question named.
    """
    start, end = calendar_period_bounds("this week against last week", None, WED)
    weeks = sorted(
        {
            (datetime.strptime(start, STAMP) + timedelta(days=d)).isocalendar()[:2]
            for d in range(
                0, (datetime.strptime(end, STAMP) - datetime.strptime(start, STAMP)).days + 1
            )
        }
    )
    assert weeks[-2:] == [(2026, 39), (2026, 40)]


def test_last_month_is_that_whole_month_including_its_final_day():
    """The classifier's own answer ended "2026-08-31" with no time, so `<=` kept 00:00:00
    of the 31st and lost the rest of the day. A month ends at its last second."""
    assert calendar_period_bounds("What was the energy use last month?", None, WED) == _expect(
        datetime(2026, 8, 1, 0, 0, 0), datetime(2026, 8, 31, 23, 59, 59)
    )


def test_a_month_is_not_thirty_days():
    """February proves the point, and a leap February proves it twice."""
    assert calendar_period_bounds("last month", None, datetime(2024, 3, 5, 9, 0)) == _expect(
        datetime(2024, 2, 1, 0, 0, 0), datetime(2024, 2, 29, 23, 59, 59)
    )
    assert calendar_period_bounds("last month", None, datetime(2026, 3, 5, 9, 0)) == _expect(
        datetime(2026, 2, 1, 0, 0, 0), datetime(2026, 2, 28, 23, 59, 59)
    )


def test_a_month_crossing_the_year_boundary():
    assert calendar_period_bounds("last month", None, datetime(2026, 1, 15, 9, 0)) == _expect(
        datetime(2025, 12, 1, 0, 0, 0), datetime(2025, 12, 31, 23, 59, 59)
    )


@pytest.mark.parametrize(
    "asked_at,start,end",
    [
        (datetime(2026, 2, 10, 9, 0), datetime(2025, 10, 1), datetime(2025, 12, 31)),
        (datetime(2026, 5, 10, 9, 0), datetime(2026, 1, 1), datetime(2026, 3, 31)),
        (datetime(2026, 11, 10, 9, 0), datetime(2026, 7, 1), datetime(2026, 9, 30)),
    ],
)
def test_last_quarter_is_a_calendar_quarter(asked_at, start, end):
    assert calendar_period_bounds("last quarter", None, asked_at) == _expect(
        start, end + timedelta(hours=23, minutes=59, seconds=59)
    )


def test_last_year_is_that_calendar_year():
    assert calendar_period_bounds("What was the energy use last year?", None, WED) == _expect(
        datetime(2025, 1, 1, 0, 0, 0), datetime(2025, 12, 31, 23, 59, 59)
    )


def test_a_single_period_gets_no_margin():
    """The margin exists for the pair case only; one period named is fetched as itself."""
    assert calendar_period_bounds("What is the energy use this month?", None, WED) == _expect(
        datetime(2026, 9, 1, 0, 0, 0), datetime(2026, 9, 30, 23, 59, 59)
    )


# ── the refusals ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        # A trailing duration wearing a calendar word. On a Wednesday "over the last week"
        # and ISO week 39 differ by three days at each end, and the module's rule is that a
        # window whose boundaries are in dispute gets no window at all.
        "How has the temperature changed over the last week?",
        "What happened in the past week?",
        "energy use in the last month",
        "energy over the last 2 weeks",
        "the energy use during the previous month",
        # Two different units: there is no single bucket, and the comparison lane refuses
        # this shape too (`_names_this_against_last` requires both halves to name one unit).
        "Compare energy use this week against last month.",
        # A calendar DAY is already resolved, correctly and more narrowly, by
        # `calendar_day_bounds` at the dialogue stage.
        "Show me the CO2 in room 5.01 yesterday",
        "What is the average temperature today?",
        "How does today compare with this week?",
        # Nothing named at all.
        "How many CO2 sensors are there?",
        "",
    ],
)
def test_a_window_in_dispute_gets_no_window(question):
    assert calendar_period_bounds(question, None, WED) is None
    assert named_period(question) is None


# ── the zone ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tz,offset_hours",
    [("Europe/Paris", 2), ("America/New_York", -4), ("Asia/Tokyo", 9)],
)
def test_the_period_is_chosen_locally_and_returned_on_the_stores_clock(tz, offset_hours):
    """CLAUDE.md's CLOCKS rule: pick the LOCAL period, convert its bounds with `to_store`.

    The expectation is built from the offset by hand rather than from `to_store`, so a
    resolver that forgot to convert cannot pass by agreeing with itself.
    """
    start, _end = calendar_period_bounds("last month", tz, WED)
    assert datetime.strptime(start, STAMP) == datetime(2026, 8, 1, 0, 0, 0) - timedelta(
        hours=offset_hours
    )


def test_no_zone_means_no_conversion():
    """The behaviour the system had before a zone was known, rather than a guess."""
    start, end = calendar_period_bounds("last month", None, WED)
    assert (start, end) == ("2026-08-01 00:00:00", "2026-08-31 23:59:59")


def test_an_unknown_zone_falls_back_instead_of_raising():
    assert calendar_period_bounds("last month", "Not/AZone", WED) == (
        "2026-08-01 00:00:00",
        "2026-08-31 23:59:59",
    )


def test_the_resolver_names_no_building_and_no_zone():
    """Design contract #3, and the rule the day resolver is already held to."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "orchestrator/services/requested_interval.py"
    ).read_text(encoding="utf-8")
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "Europe/London"):
        assert literal.lower() not in src.lower()


# ── the coupling these bounds must not break ─────────────────────────────────


@pytest.mark.parametrize(
    "question,unit,asked_at",
    [
        # Every weekday, because the shortfall depends on how far into the current period
        # the question is asked: a 2-week span reaches only 9.2 days on a Wednesday.
        ("this week against last week", "week", datetime(2026, 9, 28, 9, 0)),
        ("this week against last week", "week", datetime(2026, 9, 29, 9, 0)),
        ("this week against last week", "week", datetime(2026, 9, 30, 9, 0)),
        ("this week against last week", "week", datetime(2026, 10, 1, 9, 0)),
        ("this week against last week", "week", datetime(2026, 10, 4, 23, 0)),
        # A month pair asked on the 1st holds 745 hours against the 1,008 a month bucket
        # needs, so it fails the same way the week pair does.
        ("this month against last month", "month", datetime(2026, 9, 1, 9, 0)),
        ("this month against last month", "month", datetime(2026, 9, 28, 9, 0)),
        ("this quarter against last quarter", "quarter", datetime(2026, 7, 1, 9, 0)),
        ("this year against last year", "year", datetime(2026, 1, 1, 9, 0)),
    ],
)
def test_the_span_still_buckets_by_the_unit_the_question_named(question, unit, asked_at):
    """The margin's whole purpose, checked against the code that depends on it.

    `series_summary._bucket_size` chooses from the span of the ROWS, which can only reach
    `now`, and needs 1.5 units before it will bucket by that unit. Fetching exactly the two
    periods named would be bucketed by the unit BELOW, and the comparison would then be
    between two partial buckets — the 291.7% rise BUG-936's fix exists to prevent.
    """
    start, end = calendar_period_bounds(question, None, asked_at)
    rows_end = min(datetime.strptime(end, STAMP), asked_at)
    span_hours = (rows_end - datetime.strptime(start, STAMP)).total_seconds() / 3600.0
    assert _bucket_size(span_hours, question) == unit, (
        f"{question!r} asked at {asked_at} spans {span_hours:.0f} h, which buckets by "
        f"{_bucket_size(span_hours, question)} rather than {unit}"
    )


# ── the lane's own resolution ────────────────────────────────────────────────


def test_a_named_period_overrides_the_compiled_window():
    """The classifier's rolling 14 days loses to the calendar, and the origin says so."""
    start, end, origin = resolve_named_window(
        "Compare energy use this week against last week.",
        "2026-09-16 04:31:05",
        "2026-09-30 04:31:05",
        now=WED,
    )
    assert origin["source"] == "named_period"
    assert origin["unit"] == "week" and origin["offsets"] == [0, 1]
    assert origin["compiled_start"] == "2026-09-16 04:31:05"
    # The arithmetic and the zone conversion are pinned above, against expectations built
    # here. What this pins is that the lane DELEGATES to them and records what it used: the
    # compiled 14-day window is gone, and the bounds returned are the ones on the origin.
    #
    # No absolute date is asserted here on purpose: `calendar_period_bounds` derives the
    # LOCAL now for itself, because `now` here is the STORE clock and using one for the
    # other is the mistake the CLOCKS rule exists about. An absolute expectation would also
    # be a test that decays with the calendar (TODO-484).
    assert (start, end) == (origin["start"], origin["end"])
    assert (start, end) != ("2026-09-16 04:31:05", "2026-09-30 04:31:05")


def test_an_absent_window_is_filled_from_the_period_named():
    """The same request phrased around a room compiled to null/null; it gets bounds now."""
    start, end, origin = resolve_named_window(
        "How does the temperature in room 5.01 this week compare with last week?",
        None,
        None,
        now=WED,
    )
    assert origin["source"] == "named_period"
    assert start and end


def test_a_window_that_starts_in_the_future_is_dropped():
    """ "now+1d" is parsed by no resolver here, so the end vanished and the start was NOW.

    `datetime >= now` selects rows that do not exist yet. `sensor_binder.history_window`
    already covers this for `trend` and `forecast`; "Will floor 3 or floor 4 be warmer
    tomorrow?" classifies as `compare`, so it was not covered.
    """
    start, end, origin = resolve_named_window(
        "Will floor 3 or floor 4 be warmer tomorrow?",
        WED.strftime(STAMP),
        "now+1d",
        now=WED,
    )
    assert (start, end) == (None, None)
    assert origin["source"] == "future_start_dropped"
    assert origin["compiled_end"] == "now+1d"


def test_a_past_window_naming_no_calendar_period_is_passed_through_untouched():
    """This resolver narrows a checkable case; it does not take over time parsing."""
    start, end, origin = resolve_named_window(
        "How has the temperature changed over the last week?",
        "2026-09-23 00:00:00",
        "2026-09-30 00:00:00",
        now=WED,
    )
    assert (start, end) == ("2026-09-23 00:00:00", "2026-09-30 00:00:00")
    assert origin["source"] == "classifier"


def test_no_window_at_all_is_recorded_as_the_builders_own_default():
    _s, _e, origin = resolve_named_window("How many CO2 sensors are there?", None, None, now=WED)
    assert (_s, _e) == (None, None)
    assert origin["source"] == "default_lookback"


def test_a_resolver_failure_never_costs_the_turn(monkeypatch):
    """Fail-open, and the compiled window survives."""
    import orchestrator.services.requested_interval as ri

    def boom(*_a, **_k):
        raise RuntimeError("zone database on fire")

    monkeypatch.setattr(ri, "calendar_period_bounds", boom)
    start, end, origin = resolve_named_window("this week against last week", "2020-01-01", None)
    assert (start, end) == ("2020-01-01", None)
    assert origin["source"] == "classifier"


# ── the lane passes the resolved window on, and states a truncated fetch ─────


@pytest.fixture
def registry(monkeypatch):
    fake = SimpleNamespace(
        is_available=True, _adapters={}, _resolve_storage_key=lambda uri: (uri or "default")
    )
    monkeypatch.setattr(sql_agent, "adapter_registry", fake)
    return fake


async def test_the_aggregate_lane_is_handed_the_resolved_window(registry, monkeypatch):
    """Resolved ABOVE the aggregate lane, because a wrong window is wrong in every lane."""
    seen = {}

    async def fake_lane(self, uuids, question, storage_map, start, end, metadata, *limits):
        seen.update(start=start, end=end)
        return {"success": True, "formatted_response": "answered in the store"}

    monkeypatch.setattr(SQLAgent, "_try_aggregate_lane", fake_lane)
    await SQLAgent.__new__(SQLAgent).fetch_data_for_uuids(
        ["11111111-2222-3333-4444-555555555555"],
        "Compare energy use this week against last week.",
        {},
        "2026-09-16 04:31:05",
        "2026-09-30 04:31:05",
        {},
    )
    assert seen["start"] != "2026-09-16 04:31:05"
    assert seen["start"] and seen["end"]


def test_the_truncation_note_is_emitted_where_the_cap_is_detected():
    """`rows_capped` was on the bus from BUG-479 and exactly ONE module read it.

    `report_agent` did; every other answer narrated the cap as completeness, and on
    2026-09-29 one said "Across **all** 1,000 recorded values".
    """
    import inspect

    src = inspect.getsource(SQLAgent.fetch_data_for_uuids)
    assert "if rows_capped:" in src
    block = src.split("if rows_capped:", 1)[1].split("return {", 1)[0]
    assert "truncation_note" in block and "_row_span" in block


def test_the_wording_lives_in_one_place_so_the_two_appenders_cannot_diverge():
    """The note must also be said when the NARRATION wins the dispatch, not this prose.

    That is the case BUG-939's live example came from ("Across all 1,000 recorded values" is
    model prose, not this lane's). `disclosure_gate` already owns that pattern for the window
    substitution — one reader of the marker, one composer of the sentence, appended in both
    places — so the cap uses the same pair rather than a second wording.
    """
    from orchestrator.services.disclosure_gate import (
        TRUNCATION_KEY,
        truncation_in,
        truncation_note,
    )

    assert TRUNCATION_KEY == "rows_capped"
    marker = {
        "capped": True,
        "row_limit": 1000,
        "requested_label": "the last 30 days",
        "actual_earliest": "2026-09-18 09:00:00",
        "actual_latest": "2026-09-29 16:48:30",
    }
    note = truncation_note(marker)
    assert "full 1000 rows" in note
    assert "SAMPLE" in note and "not a count of what the period holds" in note
    assert "2026-09-18 09:00:00 to 2026-09-29 16:48:30" in note
    assert "newest part of the last 30 days" in note
    # Read off a lane's bus payload, from the marker and never from the prose.
    found = truncation_in(
        {
            "sql_result": {
                "rows_capped": True,
                "row_limit": 1000,
                "rows_earliest": "2026-09-18 09:00:00",
                "rows_latest": "2026-09-29 16:48:30",
                "requested_window": {"label": "the last 30 days"},
            }
        }
    )
    assert found and truncation_note(found) == note
    # An uncapped turn says nothing at all.
    assert truncation_in({"sql_result": {"rows_capped": False, "row_limit": 1000}}) is None
    assert truncation_note(None) == "" and truncation_note({"capped": False}) == ""


def test_the_truncation_note_never_raises_on_a_malformed_marker():
    from orchestrator.services.disclosure_gate import truncation_note

    note = truncation_note({"capped": True, "row_limit": object(), "actual_earliest": 5})
    assert "not a count of what the period holds" in note


def test_the_resolved_window_is_recorded_on_the_bus():
    """So a later gate reads which source set the window instead of parsing the SQL."""
    import inspect

    src = inspect.getsource(SQLAgent.fetch_data_for_uuids)
    assert '"requested_window": dict(requested_window)' in src
    assert '"rows_earliest": _cap_earliest' in src and '"rows_latest": _cap_latest' in src
