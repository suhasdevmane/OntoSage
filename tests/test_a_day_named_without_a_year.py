# -*- coding: utf-8 -*-
"""CAVEAT-1616: a day named without a year is the most recent such day, resolved in code.

"How much energy did the solar panels produce on Wednesday?" read ten days and said no daily
figure exists; "higher or lower than on Thursday, 8 October?" resolved no window. These pin the
arithmetic, with the building's clock fixed at Sunday 11 October 2026, 10:00 local (BST).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.services.requested_interval import explicit_date_bounds, named_date_bounds

pytestmark = pytest.mark.unit

TZ = "Europe/London"
NOW = datetime(2026, 10, 11, 10, 0, 0)  # a Sunday, local


def _day(q):
    got = explicit_date_bounds(q, TZ, now=NOW)
    return got


def _local_day(y, m, d):
    # BST in October: local midnight is 23:00 the previous day on the stores' UTC clock.
    from orchestrator.services.requested_interval import to_store

    start = to_store(datetime(y, m, d), TZ).strftime("%Y-%m-%d %H:%M:%S")
    end = to_store(datetime(y, m, d, 23, 59, 59), TZ).strftime("%Y-%m-%d %H:%M:%S")
    return (start, end)


@pytest.mark.parametrize(
    "q, ymd",
    [
        ("How much energy did the solar panels produce on Wednesday?", (2026, 10, 7)),
        ("What was the CO2 on floor 2 last Sunday?", (2026, 10, 4)),
        ("What was the noise in room 3.15 on Sunday?", (2026, 10, 11)),
        ("How busy was the atrium this Friday?", (2026, 10, 9)),
        ("What was the average humidity on floor 1 on 8 October?", (2026, 10, 8)),
        ("Was it warmer on Thursday, 8 October?", (2026, 10, 8)),
        ("What was the temperature in office 4.07 on October 8th?", (2026, 10, 8)),
        ("energy used on the 1st of September", (2026, 9, 1)),
    ],
)
def test_a_named_day_is_the_most_recent_such_day(q, ymd):
    assert _day(q) == _local_day(*ymd)


def test_a_weekday_and_a_date_pick_the_year_they_agree_in():
    # 13 January 2026 is a Tuesday; 13 January 2025 was a Monday.
    from orchestrator.services.requested_interval import to_store

    got = _day("What was the temperature on Monday 13 January?")
    start = to_store(datetime(2025, 1, 13), TZ).strftime("%Y-%m-%d %H:%M:%S")
    assert got is not None and got[0] == start


def test_a_date_still_ahead_this_year_is_last_years():
    from orchestrator.services.requested_interval import to_store

    got = _day("What was the energy use on 20 December?")
    assert got[0] == to_store(datetime(2025, 12, 20), TZ).strftime("%Y-%m-%d %H:%M:%S")


def test_a_clock_time_narrows_the_named_day():
    from orchestrator.services.requested_interval import to_store

    got = _day("What was the CO2 in room 2.13 on Wednesday between 10:00 and 12:00?")
    assert got == (
        to_store(datetime(2026, 10, 7, 10, 0), TZ).strftime("%Y-%m-%d %H:%M:%S"),
        to_store(datetime(2026, 10, 7, 11, 59, 59), TZ).strftime("%Y-%m-%d %H:%M:%S"),
    )


@pytest.mark.parametrize(
    "q",
    [
        "Is the building open on Mondays?",
        "How busy is the cafe every Monday?",
        "Has CO2 risen since Monday?",
        "Will it be warm on Monday?",
        "Is room 2.13 free on Monday?",
        "Compare Monday with Tuesday",
        "When is the Wednesday meeting?",
        "What will the temperature be next Wednesday?",
        "How busy is it this Friday?" if NOW.weekday() < 4 else "How busy will it be on Friday?",
        "What may 3 people need?",
        "What is the temperature on floor 2?",
    ],
)
def test_what_names_no_single_past_day_gets_no_window(q):
    assert named_date_bounds(q.lower(), TZ, now=NOW) is None


def test_a_written_year_still_takes_the_year_path():
    from orchestrator.services.requested_interval import to_store

    got = _day("What was the CO2 on 13 January 2025?")
    assert got[0] == to_store(datetime(2025, 1, 13), TZ).strftime("%Y-%m-%d %H:%M:%S")


def test_the_aggregate_window_reads_a_named_day():
    from orchestrator.services import aggregate_lane as al
    from orchestrator.services.requested_interval import to_store

    now_store = to_store(NOW, TZ)
    w = al.resolve_window("solar energy generated on Wednesday", None, None, TZ, now=now_store)
    assert w is not None
    assert w.start == to_store(datetime(2026, 10, 7), TZ).strftime("%Y-%m-%d %H:%M:%S")
