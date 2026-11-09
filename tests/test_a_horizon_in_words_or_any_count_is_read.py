"""'Forecast the building's electricity use for the next three days' was forecast for 24 hours.

The horizon table listed fixed phrasings ("next 3 days", "next 2 days"), so a count written as a
word and any count of any unit it did not list fell through to the 24-hour default -- and the
answer printed "Horizon: next 24 hours" over a question that asked for three days (2026-11-07).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from orchestrator.services.forecasting.horizon_parser import match_horizon, parse_horizon

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q,total",
    [
        ("Forecast the building's electricity use for the next three days.", timedelta(days=3)),
        ("forecast the next two weeks", timedelta(days=14)),
        ("what will CO2 be over the next 48 hours", timedelta(hours=48)),
        ("predict noise for the coming 5 hours", timedelta(hours=5)),
        ("forecast the next 10 minutes", timedelta(minutes=10)),
    ],
)
def test_a_count_in_words_or_any_unit_is_the_horizon(q, total):
    h = match_horizon(q)
    assert h is not None and h.total == total
    assert h.n_steps <= 60 and h.n_steps == int(h.total / h.step)


def test_the_table_still_decides_what_it_lists():
    assert match_horizon("forecast for the next week").label == "next 7 days"
    assert match_horizon("what will it be tomorrow").label == "next 24 hours"
    assert match_horizon("forecast the next 3 days").step == timedelta(hours=3)


def test_a_horizon_beyond_the_longest_says_so():
    h = match_horizon("forecast the next 90 days")
    assert h.total == timedelta(days=30)
    assert "longest horizon" in h.label


def test_no_horizon_named_is_still_the_default():
    assert match_horizon("forecast the CO2 in room 5.01") is None
    assert parse_horizon("forecast the CO2 in room 5.01").total == timedelta(hours=24)
