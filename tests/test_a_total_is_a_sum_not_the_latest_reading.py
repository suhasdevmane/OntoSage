# -*- coding: utf-8 -*-
"""A total over a period is computed as a SUM, never narrated from the latest readings.

Live, unscripted, 2026-09-18: "How much electricity did the building use yesterday?" fetched the
right six meters and the right local day (144 readings), took the analytics lane's default stats
template — there is no total template — and the narrator reported "17.08 kWh yesterday", which was
the sum of the six LATEST readings. A confident wrong figure, worse than the "no data" it replaced.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest

from orchestrator.services.series_summary import asks_for_a_total, summarise_energy_totals

pytestmark = pytest.mark.unit


def _six_meters_one_day(kwh_per_hour: float = 3.0):
    """The live shape: six floor meters, 24 hourly readings each."""
    t0 = datetime(2026, 9, 16, 23, 0, 0)
    rows, meta = [], {}
    for floor in range(6):
        u = f"m{floor}"
        meta[u] = {"label": f"Electrical Energy Meter — Floor {floor}", "unit": "kWh"}
        for h in range(24):
            rows.append(
                {"uuid": u, "value": kwh_per_hour, "timestamp": (t0 + timedelta(hours=h)).isoformat(sep=" ")}
            )
    return rows, meta


def test_the_total_is_the_sum_of_every_reading_not_of_the_latest_ones():
    rows, meta = _six_meters_one_day(3.0)
    out = summarise_energy_totals(rows, meta)
    assert "432" in out, out  # 6 meters x 24 readings x 3.0 kWh
    assert "17.08" not in out and " 18 kWh" not in out, "the six LATEST readings summed is the bug"
    assert "across 6 series (144 readings" in out
    assert "Electrical Energy Meter — Floor 3: 72 kWh (24 readings)" in out
    assert "never use a latest reading as a total" in out


def test_the_window_is_stated_in_store_time():
    rows, meta = _six_meters_one_day()
    out = summarise_energy_totals(rows, meta)
    assert "16 Sep 23:00" in out and "17 Sep 22:00" in out and "store time" in out


def test_a_power_series_is_never_added_up_into_energy():
    rows = [{"uuid": "a", "value": 5.0, "timestamp": "2026-09-17 10:00:00"}] * 3
    assert summarise_energy_totals(rows, {"a": {"label": "Boiler power", "unit": "kW"}}) is None


def test_a_mixed_set_is_not_totalled():
    rows = [
        {"uuid": "a", "value": 1, "timestamp": "2026-09-17 10:00:00"},
        {"uuid": "b", "value": 2, "timestamp": "2026-09-17 10:00:00"},
    ]
    meta = {"a": {"label": "Energy meter", "unit": "kWh"}, "b": {"label": "CO2 sensor", "unit": "ppm"}}
    assert summarise_energy_totals(rows, meta) is None


def test_mixed_energy_units_are_not_summed_blindly():
    """kWh and MWh are both energy but summing the raw numbers would be wrong."""
    rows = [{"uuid": "a", "value": 1}, {"uuid": "b", "value": 1}]
    meta = {"a": {"label": "Meter A", "unit": "kWh"}, "b": {"label": "Meter B", "unit": "MWh"}}
    out = summarise_energy_totals(rows, meta)
    assert out is None or "MWh" not in out.split("across")[0], out


def test_no_rows_and_no_usable_values_return_none():
    assert summarise_energy_totals([], {"a": {"unit": "kWh"}}) is None
    assert summarise_energy_totals([{"uuid": "a", "value": "n/a"}], {"a": {"unit": "kWh"}}) is None


def test_more_series_than_the_cap_are_counted_but_not_listed():
    rows = [{"uuid": f"m{i}", "value": 1.0, "timestamp": "2026-09-17 10:00:00"} for i in range(12)]
    meta = {f"m{i}": {"label": f"Meter {i:02d}", "unit": "kWh"} for i in range(12)}
    out = summarise_energy_totals(rows, meta, max_series=8)
    assert "across 12 series" in out and "12 kWh" in out
    assert "…and 4 more series not shown" in out


@pytest.mark.parametrize(
    "question",
    [
        "How much electricity did the building use yesterday?",
        "What was the total energy use last month?",
        "How much energy did we use last week?",
        "How much power did the building consume this week?",
        "What is the total electricity consumption for floor 3?",
    ],
)
def test_a_question_that_asks_for_a_total_is_recognised(question):
    assert asks_for_a_total(question), question


@pytest.mark.parametrize(
    "question",
    [
        "What is the average energy use per floor?",
        "What's our energy use like compared with last week?",
        "Which floor uses the most power?",
        "What is the current energy use?",
        "Is energy use going up?",
        "What's the latest electricity reading?",
        "What is the temperature in Room 2.01 right now?",
        "Show me the peak electricity demand",
    ],
)
def test_a_question_with_its_own_template_or_lane_is_not_claimed(question):
    assert not asks_for_a_total(question), question


def test_the_lane_adds_the_block_only_for_a_total_question():
    from orchestrator.agents import analytics_agent

    src = inspect.getsource(analytics_agent)
    assert "asks_for_a_total(user_query)" in src and "summarise_energy_totals" in src
    assert src.index("summarise_energy_totals(rows or []") > src.index("Sensor Information:")


def test_the_narrator_is_told_to_state_the_period_the_total_covers():
    """'Total energy use last month' was answered '5,531 kWh for the period' from ~11 days of data."""
    rows, meta = _six_meters_one_day()
    out = summarise_energy_totals(rows, meta)
    assert "State in your answer the period these readings actually cover" in out
    assert "shorter than the period the question asked about, say so" in out
    # No dated readings, no period to state: the sentence must not appear.
    undated = [{"uuid": "a", "value": 1.0}, {"uuid": "a", "value": 2.0}]
    assert "State in your answer the period" not in summarise_energy_totals(
        undated, {"a": {"label": "M", "unit": "kWh"}}
    )
