"""A period that is still filling is not compared with a whole one by its total (BUG-820).

"Compare this week's electricity use with last week", asked on a Friday, was answered
*"Electricity use fell by 4,318 kWh (-34.1 %) ... an unintended outage"* — twice, in two
rehearsals, and read as correct both times. Week 38 held five days of readings and week 37 held
seven; the building used the same power per day. The count test that drops an edge bucket
(BUG-627) keeps anything above 60% of a typical bucket, and it does nothing at all with two
buckets, so the shorter week survived and its smaller total was reported as a fall.

A SUM over an unfinished bucket is now compared as a rate per smaller unit, and the narrator is
told the bucket is in progress. A mean is per reading already and needs none of this.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.series_summary import _covered_hours, summarise_periods

pytestmark = pytest.mark.unit

_ENERGY = {"m1": {"unit": "kWh", "label": "Energy Meter"}}
_TEMP = {"m1": {"unit": "degC", "label": "Air Temperature Sensor"}}
_ASK = "Compare this week's electricity use with last week"


def _hourly(start, end, value_of, uuid="m1"):
    """One reading an hour from ``start`` to ``end`` inclusive; ``value_of(t)`` gives the value."""
    rows, t = [], start
    while t <= end:
        rows.append(
            {"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "uuid": uuid, "value": value_of(t)}
        )
        t += timedelta(hours=1)
    return rows


MON_37 = datetime(2026, 9, 7)  # a Monday: ISO week 37
MON_38 = datetime(2026, 9, 14)  # the next Monday: ISO week 38
FRIDAY_EVENING = datetime(2026, 9, 18, 20, 0)  # five days into week 38
END_OF_38 = datetime(2026, 9, 20, 23, 0)


def _change_line(summary):
    return [l for l in summary.splitlines() if l.startswith("CHANGE ACROSS")][0]


def test_a_flat_load_is_not_reported_as_a_fall_when_the_newer_week_is_shorter():
    rows = _hourly(MON_37, FRIDAY_EVENING, lambda t: 1.0)
    summary = summarise_periods(rows, _ENERGY, _ASK)
    line = _change_line(summary)
    assert "kWh per day" in line
    assert "unchanged" in line, line
    assert "down by" not in line


def test_the_narrator_is_told_the_newer_week_is_still_in_progress():
    rows = _hourly(MON_37, FRIDAY_EVENING, lambda t: 1.0)
    summary = summarise_periods(rows, _ENERGY, _ASK)
    assert "IN PROGRESS: 2026-W38" in summary
    assert "do not compare the totals" in summary
    assert "covers 117 of 168 hours, not a whole week" in summary


def test_a_real_change_in_rate_is_still_reported_in_that_rate():
    """Week 38 draws twice the power of week 37, over five days against seven: +100% per day."""
    rows = _hourly(MON_37, FRIDAY_EVENING, lambda t: 2.0 if t >= MON_38 else 1.0)
    summary = summarise_periods(rows, _ENERGY, _ASK)
    line = _change_line(summary)
    assert "up by 24 kWh per day" in line, line
    assert "+100.0%" in line, line


def test_the_highest_and_lowest_week_are_ranked_by_rate_when_one_is_unfinished():
    rows = _hourly(MON_37, FRIDAY_EVENING, lambda t: 1.0)
    summary = summarise_periods(rows, _ENERGY, _ASK)
    ranking = [l for l in summary.splitlines() if l.startswith("HIGHEST")][0]
    assert "kWh per day" in ranking, ranking


def test_two_whole_weeks_are_compared_by_total_exactly_as_before():
    rows = _hourly(MON_37, END_OF_38, lambda t: 2.0 if t >= MON_38 else 1.0)
    summary = summarise_periods(rows, _ENERGY, _ASK)
    line = _change_line(summary)
    assert "per day" not in line
    assert "IN PROGRESS" not in summary
    assert "up by 168 kWh" in line, line


def test_a_mean_is_not_rewritten_because_the_bucket_is_short():
    """Temperature in five days against seven is a fair comparison of means."""
    rows = _hourly(MON_37, FRIDAY_EVENING, lambda t: 21.0)
    summary = summarise_periods(rows, _TEMP, "Compare this week's temperature with last week")
    assert "IN PROGRESS" not in summary
    line = _change_line(summary)
    assert " per " not in line, line
    assert "21 " in line and "in 2026-W37" in line and "in 2026-W38" in line


def test_readings_every_fifteen_minutes_do_not_make_every_hour_look_partial():
    """Four readings span 45 minutes; the bucket is still a whole hour."""
    start = datetime(2026, 9, 1, 0, 0)
    stamps = [start + timedelta(minutes=15 * i) for i in range(4)]
    assert _covered_hours(stamps) == pytest.approx(1.0)


def test_fewer_than_three_readings_cannot_say_how_much_they_cover():
    start = datetime(2026, 9, 1, 0, 0)
    assert _covered_hours([start, start + timedelta(hours=1)]) is None
    assert _covered_hours([start]) is None


def test_hourly_buckets_of_dense_energy_readings_are_not_flagged():
    start = datetime(2026, 9, 1, 0, 0)
    rows = [
        {
            "datetime": (start + timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M:%S"),
            "uuid": "m1",
            "value": 0.25,
        }
        for i in range(4 * 48)
    ]
    summary = summarise_periods(rows, _ENERGY, "how has energy changed?")
    assert "IN PROGRESS" not in summary
    assert "per hour" not in _change_line(summary)
