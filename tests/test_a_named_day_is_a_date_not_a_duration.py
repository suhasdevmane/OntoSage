# -*- coding: utf-8 -*-
"""A report headed "Yesterday" described this afternoon (BUG-480).

MEASURED 2026-09-07, live. "Give me a report on the CO2 in room 5.01 yesterday" compiled
to a time bound of `now-24h`. `_resolve_relative_dt` did exactly what it is for and turned
that into a stamp 24 hours old, so the query ran:

    WHERE ... `datetime` >= '2026-09-06 17:16:39' AND `datetime` <= '2026-09-07 17:16:39'

A rolling day ending at the moment of asking — HALF OF IT TODAY — under a report headed
"Room 5.01 – Yesterday".

Every figure in it was real and correctly computed over the rows it fetched. That is what
makes this class hard: there is no tell in the prose, the numbers are internally
consistent, the header names the right day, and the only way to catch it is to check the
window against the question.

"Yesterday" in plain English is a DATE. A reader comparing two days cannot use a window
that slides with the clock, and a report that silently folds in this afternoon is wrong in
a way no amount of correct arithmetic fixes.

SCOPE, DELIBERATELY NARROW
--------------------------
Only words whose day boundaries are not in dispute. "last night" spans two dates, "this
morning" is a part-day, "the weekend" is two days and which two depends on where you are.
Guessing at those would trade one wrong window for another, so `calendar_day_bounds`
returns None for anything it does not recognise and the compiled range stands.

The override runs LAST and beats what the model compiled, because the question is the
authoritative source and the compile is one reading of it — the same lesson as recovering
a floor from the raw query when the compiler left it blank (BUG-472).
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.dialogue_agent import calendar_day_bounds  # noqa: E402

# A fixed "now" so the assertions are about the logic, not about when the suite runs.
NOW = datetime(2026, 9, 7, 17, 16, 39)


def test_yesterday_is_that_whole_day():
    start, end = calendar_day_bounds("report on the CO2 in room 5.01 yesterday", now=NOW)
    assert start == "2026-09-06 00:00:00"
    assert end == "2026-09-06 23:59:59"


def test_yesterday_does_not_reach_into_today():
    """The live failure: a window ending at the moment of asking, half of it today."""
    _, end = calendar_day_bounds("co2 yesterday", now=NOW)
    assert end < "2026-09-07 00:00:00", (
        "the window still runs into today, so a report about yesterday includes this " "afternoon"
    )


def test_yesterday_covers_the_whole_day_not_a_24_hour_span_ending_now():
    start, end = calendar_day_bounds("co2 yesterday", now=NOW)
    assert start != "2026-09-06 17:16:39"
    assert (start, end) == ("2026-09-06 00:00:00", "2026-09-06 23:59:59")


def test_today_starts_at_midnight_not_24_hours_ago():
    start, end = calendar_day_bounds("how is the CO2 today", now=NOW)
    assert start == "2026-09-07 00:00:00"
    assert end == "2026-09-07 23:59:59"


def test_the_end_is_inclusive_because_the_builders_emit_less_than_or_equal():
    """Next-midnight as the end would pull the first instant of the following day in."""
    _, end = calendar_day_bounds("yesterday", now=NOW)
    assert end.endswith("23:59:59")


def test_a_month_boundary_is_handled():
    start, end = calendar_day_bounds("yesterday", now=datetime(2026, 3, 1, 9, 0, 0))
    assert (start, end) == ("2026-02-28 00:00:00", "2026-02-28 23:59:59")


def test_a_leap_day_is_handled():
    start, _ = calendar_day_bounds("yesterday", now=datetime(2028, 3, 1, 9, 0, 0))
    assert start == "2028-02-29 00:00:00"


def test_a_year_boundary_is_handled():
    start, end = calendar_day_bounds("yesterday", now=datetime(2027, 1, 1, 0, 30, 0))
    assert (start, end) == ("2026-12-31 00:00:00", "2026-12-31 23:59:59")


@pytest.mark.parametrize(
    "q",
    [
        "co2 last night",
        "co2 this morning",
        "co2 at the weekend",
        "co2 over the last 7 days",
        "co2 in the past hour",
        "what is the co2 now",
        "co2 between March and April",
        "",
    ],
)
def test_anything_whose_boundaries_are_in_dispute_is_left_alone(q):
    """Returning a wrong window is not better than returning none.

    "last night" spans two dates, "this morning" is a part-day, "the weekend" is two days
    and which two depends on where you are. The compiled range stands for all of them.
    """
    assert calendar_day_bounds(q, now=NOW) is None


@pytest.mark.parametrize("q", ["yesterdays report", "the yesterdayish figure", "AYESTERDAY"])
def test_it_matches_a_word_not_a_substring(q):
    """`"yesterday" in text` would fire on a possessive or a longer word."""
    assert calendar_day_bounds(q, now=NOW) is None


def test_case_and_punctuation_do_not_matter():
    assert calendar_day_bounds("Give me a report on CO2 YESTERDAY.", now=NOW) is not None


def test_an_unknown_timezone_does_not_break_the_turn():
    """The zone comes from per-building config and may be anything."""
    assert calendar_day_bounds("yesterday", tz_name="Not/AZone") is not None


def test_the_override_is_applied_after_the_compiled_range_and_wins():
    """A compiled `now-24h` must not survive when the question names a day."""
    import inspect

    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent._parse_llm_response)
    assert "calendar_day_bounds(user_query" in src, (
        "the override does not read the raw question, so it cannot correct a compiled "
        "range that disagrees with it"
    )
    day = src.index("calendar_day_bounds(user_query")
    compiled = src.index("_resolve_relative_dt(")
    assert compiled < day, "the compiled range is applied after the override and overwrites it"


def test_the_override_says_what_it_changed():
    """A window silently replaced is as hard to audit as a window silently wrong."""
    import inspect

    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent._parse_llm_response)
    assert "calendar day named in the question" in src
    assert "(was %s .. %s)" in src, "the log does not record what the window was before"


def test_nothing_here_names_a_building():
    import inspect

    body = inspect.getsource(calendar_day_bounds).split('"""')[-1].lower()
    for literal in ("bldg1", "bldg2", "abacws", "europe/london"):
        assert (
            literal not in body
        ), "the day boundary must come from the building's own timezone, never a literal"
