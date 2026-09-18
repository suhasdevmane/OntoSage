"""A question about how something changed is answered with a shape over time (BUG-626).

"How has the temperature on floor 3 changed over the last week?" was answered *"No change data
available for floor 3 over the last week"* — from a week of readings that had been fetched,
clamped by policy and handed to the narrator. The only deterministic summary that existed was
per FLOOR: one mean per floor across the whole window, which cannot show a change within it.

The counting stays in code (BUG-581): the narrator is given the per-period figures and the
change across the window, and told to quote them.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.series_summary import (
    asks_how_it_changed,
    summarise_periods,
)

pytestmark = pytest.mark.unit


def _rows(hours, start_value, step, unit_uuid="s1", interval_h=1):
    start = datetime(2026, 9, 1, 0, 0, 0)
    return [
        {
            "datetime": (start + timedelta(hours=i * interval_h)).strftime("%Y-%m-%d %H:%M:%S"),
            "uuid": unit_uuid,
            "value": start_value + i * step,
        }
        for i in range(hours)
    ]


_META = {"s1": {"unit": "degC", "floor": "3", "label": "Air Temperature Sensor"}}
_ENERGY_META = {"s1": {"unit": "kWh", "floor": "3", "label": "Energy Meter"}}


@pytest.mark.parametrize(
    "question",
    [
        "How has the temperature on floor 3 changed over the last week?",
        "What is the CO2 trend in room 5.01?",
        "Compare this week's electricity use with last week",
        "Has the humidity risen over the past month?",
        "When is the building busiest?",
    ],
)
def test_a_temporal_question_is_recognised(question):
    assert asks_how_it_changed(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "What is the CO2 in room 5.01?",
        "Show me floor 3",
        "Which floor is the warmest right now?",
        "How many sensors are there?",
    ],
)
def test_a_question_with_no_time_in_it_is_left_alone(question):
    """The period summary costs a fetch of every row; a point-in-time question must not pay it."""
    assert asks_how_it_changed(question) is False


def test_the_change_across_the_window_is_stated():
    summary = summarise_periods(_rows(48, 20.0, 0.1), _META, "how has it changed?")
    assert summary is not None
    assert "CHANGE ACROSS THE WINDOW" in summary
    assert "up by" in summary


def test_a_falling_series_is_called_falling():
    summary = summarise_periods(_rows(48, 30.0, -0.1), _META, "how has it changed?")
    assert "down by" in summary


def test_the_bucket_follows_the_span():
    """Neither one bucket for a month nor two hundred for a day."""
    hourly = summarise_periods(_rows(48, 20.0, 0.1), _META, "trend")
    assert "Per-hour figures" in hourly
    # 30 days of readings, one every 6 hours.
    monthly = summarise_periods(_rows(120, 20.0, 0.05, interval_h=6), _META, "trend")
    assert "Per-day figures" in monthly


def test_a_long_window_is_not_two_hundred_lines():
    summary = summarise_periods(_rows(400, 20.0, 0.01, interval_h=6), _META, "trend")
    assert "further" in summary and "omitted" in summary
    assert len(summary.splitlines()) < 20


def test_energy_is_summed_per_period_and_never_averaged():
    """A period total that averages kWh understates the period by the number of readings."""
    summary = summarise_periods(_rows(48, 2.0, 0.0), _ENERGY_META, "how has energy changed?")
    assert "total" in summary
    assert "mean" not in summary.split("CHANGE ACROSS")[0]


def test_the_highest_and_lowest_period_are_named():
    summary = summarise_periods(_rows(48, 20.0, 0.1), _META, "when is it highest?")
    assert "HIGHEST" in summary and "LOWEST" in summary


def test_too_few_readings_yield_nothing_rather_than_a_shape():
    assert summarise_periods(_rows(2, 20.0, 1.0), _META, "trend") is None


def test_rows_with_no_timestamp_yield_nothing():
    rows = [{"uuid": "s1", "value": 1.0} for _ in range(10)]
    assert summarise_periods(rows, _META, "trend") is None


def test_mixed_units_refuse_to_aggregate_rather_than_average_nonsense():
    """900 ppm and 21.5 degC averaged to 590.5 once already (BUG-521)."""
    rows = _rows(24, 20.0, 0.1, "s1") + _rows(24, 900.0, 1.0, "s2")
    meta = {"s1": {"unit": "degC"}, "s2": {"unit": "ppm"}}
    summary = summarise_periods(rows, meta, "how has it changed?")
    assert summary is not None and summary.startswith("Per-period aggregates were NOT computed")


def test_the_narrator_is_told_not_to_claim_only_latest_values():
    """The exact sentence the wrong answer used, refused in the handover."""
    summary = summarise_periods(_rows(48, 20.0, 0.1), _META, "trend")
    assert "do not say the data holds only latest values" in summary


def test_nothing_here_names_a_building():
    import inspect

    import orchestrator.services.series_summary as mod

    source = inspect.getsource(mod)
    assert "bldg1" not in source and "Abacws" not in source


def _rows_with_partial_edges():
    """A fortnight of daily readings whose first and last day are partial — the ordinary
    shape of any window that starts mid-day and ends now."""
    start = datetime(2026, 9, 1, 18, 0, 0)  # begins in the evening: a short first day
    rows = []
    t = start
    end = datetime(2026, 9, 15, 3, 0, 0)  # ends at 3am: a short last day
    while t < end:
        rows.append(
            {"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "uuid": "s1", "value": 20.0}
        )
        t += timedelta(hours=1)
    return rows


def test_a_partial_edge_period_is_not_compared_with_a_whole_one():
    """"+291.7%" was reported for electricity from a partial first day to a partial last day
    — a change in the measurement window, not in the building (BUG-627)."""
    summary = summarise_periods(_rows_with_partial_edges(), _ENERGY_META, "how has it changed?")
    assert "PARTIAL" in summary
    assert "2026-09-01" in summary.split("PARTIAL")[1].split("\n")[0]


def test_the_change_line_uses_whole_periods_only():
    summary = summarise_periods(_rows_with_partial_edges(), _ENERGY_META, "how has it changed?")
    change_line = [l for l in summary.splitlines() if l.startswith("CHANGE ACROSS")][0]
    assert "2026-09-01" not in change_line
    assert "2026-09-15" not in change_line


def test_a_question_naming_weeks_is_answered_in_weeks():
    """"Compare this week's electricity use with last week" bucketed by DAY answered with one
    day against another. A question that names weeks is answered in weeks."""
    start = datetime(2026, 8, 1)
    rows = [
        {
            "datetime": (start + timedelta(hours=i * 3)).strftime("%Y-%m-%d %H:%M:%S"),
            "uuid": "s1",
            "value": 2.0,
        }
        for i in range(8 * 24)  # 24 days at 3-hourly
    ]
    summary = summarise_periods(rows, _ENERGY_META, "Compare this week's use with last week")
    assert "Per-week figures" in summary


def test_a_short_window_is_not_forced_into_the_named_period():
    """One week of data cannot answer week-against-week; bucketing by week would give a
    single bucket and say nothing."""
    rows = _rows(48, 20.0, 0.1)
    summary = summarise_periods(rows, _META, "Compare this week with last week")
    assert "Per-week figures" not in summary
