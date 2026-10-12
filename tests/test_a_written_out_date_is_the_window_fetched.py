"""BUG-1490: a date the question writes out is the window fetched, computed, never asked for.

A one-room average "in March 2025" got 2025-03-01 .. 03-31 from the classifier on one ask and no
window on the next, which read the last 30 days of 2026 under the heading "March 2025". These pin
the arithmetic (no zone, so local == store) and, as importantly, every shape the resolver must
REFUSE, because a wrong window is worse than the classifier's.
"""

from datetime import datetime

import pytest

from orchestrator.agents.sql_agent import resolve_named_window
from orchestrator.services.requested_interval import explicit_date_bounds

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question,expected",
    [
        # the shapes a question writes a date in (no Paper 3 study task is quoted here: this
        # repository is public and the study's tasks must not be)
        (
            "What was the average humidity in room 1.01 in April 2025?",
            ("2025-04-01 00:00:00", "2025-04-30 23:59:59"),
        ),
        (
            "What was the lowest noise level in room 3.10 on 2 June 2025 between 08:30 and 11:00?",
            ("2025-06-02 08:30:00", "2025-06-02 10:59:59"),
        ),
        (
            "Did the lab stay between 18 and 22 C from 13:00 to 17:00 on Thursday 6 November 2025?",
            ("2025-11-06 13:00:00", "2025-11-06 16:59:59"),
        ),
        (
            "Was humidity under 60 percent everywhere on Saturday 1 November 2025?",
            ("2025-11-01 00:00:00", "2025-11-01 23:59:59"),
        ),
        (
            "Which wing used less gas from Monday 6 October 2025 to Sunday 12 October 2025?",
            ("2025-10-06 00:00:00", "2025-10-12 23:59:59"),
        ),
        (
            "What was the light level in the atrium at noon on Tuesday 9 December 2025?",
            ("2025-12-09 11:30:00", "2025-12-09 12:29:59"),
        ),
        # rewordings
        (
            "noise in 3.10 on Jun 2, 2025 from 8am to 4pm",
            ("2025-06-02 08:00:00", "2025-06-02 15:59:59"),
        ),
        ("temperature on 2025-02-14", ("2025-02-14 00:00:00", "2025-02-14 23:59:59")),
        ("gas between 6 and 12 October 2025", ("2025-10-06 00:00:00", "2025-10-12 23:59:59")),
        ("the week of 8 October 2025", ("2025-10-06 00:00:00", "2025-10-12 23:59:59")),
        ("CO2 from January to March 2025", ("2025-01-01 00:00:00", "2025-03-31 23:59:59")),
        ("humidity in Feb 2025.", ("2025-02-01 00:00:00", "2025-02-28 23:59:59")),
        (
            "what were the readings in the March 2025 data",
            ("2025-03-01 00:00:00", "2025-03-31 23:59:59"),
        ),
        ("CO2 on the 3rd of April 2025", ("2025-04-03 00:00:00", "2025-04-03 23:59:59")),
        (
            "from noon until midnight on the 3rd of April, 2025",
            ("2025-04-03 12:00:00", "2025-04-03 23:59:59"),
        ),
    ],
)
def test_a_written_out_date_resolves(question, expected):
    assert explicit_date_bounds(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "What is the temperature in room 5.01 right now?",  # no date at all
        # "What was the CO2 on 3 April?" used to be here (no year: two readings). Since
        # CAVEAT-1616 a past day named without a year is its most recent occurrence, stated in
        # the answer's window -- see tests/test_a_day_named_without_a_year.py.
        "temperature on 03/04/2025",  # day-first and month-first disagree
        "compare 14 February 2025 with 15 February 2025",  # two dates, a comparison
        "CO2 since 1 March 2025",  # an open interval
        "anything before 5 March 2025?",
        "What was the CO2 on 31 February 2025?",  # no such day
        "CO2 on 5 March 2025 from 16:00 to 10:00",  # a span that runs backwards
        "the 2025 energy report",  # a bare year is not resolved here
        "Room 1.20 or Room 1.21 between 20 and 24",  # numbers, no date
        "March 2025 against 15 March 2025",  # a month and a day
        "Which rooms may use the May 2021 framework for scheduling?",  # a dated thing, not a period
        "Who reported the 3 March 2025 incident?",
    ],
)
def test_a_window_in_dispute_gets_no_window(question):
    assert explicit_date_bounds(question) is None


def test_a_band_is_not_read_as_a_time_span():
    # "between 20 and 24" is degrees; the day must not be narrowed to 20:00-24:00.
    assert explicit_date_bounds("Did it stay between 20 and 24 on Thursday 3 April 2025?") == (
        "2025-04-03 00:00:00",
        "2025-04-03 23:59:59",
    )


def test_the_day_is_the_buildings_and_the_bounds_are_on_the_store_clock():
    # 31 March 2025 is BST: local midnight is 23:00 UTC the day before.
    start, end = explicit_date_bounds("on 31 March 2025", "Europe/London")
    assert (start, end) == ("2025-03-30 23:00:00", "2025-03-31 22:59:59")


def test_the_lane_takes_the_written_date_over_the_classifier():
    now = datetime(2026, 10, 10, 3, 0, 0)
    s, e, origin = resolve_named_window(
        "What was the average temperature in room 5.23 in March 2025?", None, None, now=now
    )
    assert origin["source"] == "explicit_date"
    assert s.startswith("2025-03-0") and e.startswith("2025-03-31")


def test_a_narrower_compiled_window_inside_the_date_is_kept():
    now = datetime(2026, 10, 10, 3, 0, 0)
    s, e, origin = resolve_named_window(
        "temperature on the morning of 14 February 2025",
        "2025-02-14 08:00:00",
        "2025-02-14 12:00:00",
        now=now,
    )
    assert (s, e) == ("2025-02-14 08:00:00", "2025-02-14 12:00:00")
    assert origin["source"] == "classifier_within_explicit_date"


def test_a_written_date_in_the_future_is_not_imposed():
    now = datetime(2026, 10, 10, 3, 0, 0)
    s, e, origin = resolve_named_window(
        "What will the CO2 be on 20 December 2026?", None, None, now=now
    )
    assert origin["source"] != "explicit_date" and (s, e) == (None, None)
