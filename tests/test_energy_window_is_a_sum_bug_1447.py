# -*- coding: utf-8 -*-
"""BUG-1447: an energy window is totalled by its SUM, whatever the question's wording.

Live, 2026-10-06: "What was the energy use on floor 3 for the day before yesterday?" fetched 85
readings of a floor-3 kWh meter. The question names no total word, so no total block was built
and the narrator headlined the LATEST reading ("4.44 kWh was the latest energy use"). The sum of
the 85 readings is 374.42 kWh. Mean and median in the same answer were right; the headline was not.

The quantity decides: a summable energy series is totalled, a level (temperature) keeps its mean.
The wording only rules out a question that asks for a different statistic.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from orchestrator.services.series_summary import (
    asks_for_a_total,
    summarise_energy_totals,
    summarise_series,
)

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 10, 3, 23, 0, 0)


def _energy_window(values):
    """One kWh meter, one reading per 15 minutes from the window start."""
    rows = [
        {
            "uuid": "floor3",
            "value": v,
            "timestamp": (_T0 + timedelta(minutes=15 * i)).isoformat(sep=" "),
        }
        for i, v in enumerate(values)
    ]
    meta = {"floor3": {"label": "Electrical Energy Meter — Floor 3", "unit": "kWh"}}
    return rows, meta


def _temperature_window(values):
    rows = [
        {
            "uuid": "t3",
            "value": v,
            "timestamp": (_T0 + timedelta(minutes=15 * i)).isoformat(sep=" "),
        }
        for i, v in enumerate(values)
    ]
    meta = {"t3": {"label": "Room 3.01 Temperature", "unit": "degC", "kind": "Temperature_Sensor"}}
    return rows, meta


#: 85 readings, 1..85 kWh: the sum is 3,655, the LAST value is 85, the mean is 43.
_ENERGY = [float(v) for v in range(1, 86)]
_TEMP = [20.0 + (i % 5) for i in range(85)]  # mean 22.0


def test_the_energy_headline_is_the_sum_not_the_last_reading():
    rows, meta = _energy_window(_ENERGY)
    out = summarise_energy_totals(rows, meta)
    assert out is not None
    first_line = out.splitlines()[0]
    assert "3,655 kWh" in first_line, first_line
    assert "across 1 series (85 readings" in first_line, first_line
    assert "85 kWh" not in first_line, "the last reading must not be the total"


def test_the_temperature_headline_is_the_mean_and_no_total_is_built():
    rows, meta = _temperature_window(_TEMP)
    line, has_energy = summarise_series(rows, meta)
    assert has_energy is False
    assert "mean 22" in line, line
    # A level is never summed, even when the question's wording asks for a total.
    assert asks_for_a_total("How much temperature did room 3.01 have over the day?")
    assert summarise_energy_totals(rows, meta) is None


def test_the_quantity_decides_not_the_wording():
    """A neutral energy question and an explicit 'how much' question get the same total."""
    rows, meta = _energy_window(_ENERGY)
    neutral = "What was the energy use on floor 3 for the day before yesterday?"
    explicit = "How much energy did floor 3 use the day before yesterday?"
    assert asks_for_a_total(neutral)
    assert asks_for_a_total(explicit)
    assert "3,655 kWh" in summarise_energy_totals(rows, meta)


def test_the_wording_still_rules_out_a_question_that_asks_for_another_statistic():
    """A latest value, a level's mean, an extreme or a change is not the window's sum."""
    for question in (
        "What is the current energy use on floor 3?",
        "What is the average energy use on floor 3?",
        "Which floor used the most energy yesterday?",
        "Has the energy use on floor 3 changed since yesterday?",
        "Is the energy use on floor 3 going up?",
    ):
        assert not asks_for_a_total(question), question


def test_a_power_series_is_not_totalled_even_when_the_question_says_how_much():
    rows, meta = _energy_window(_ENERGY)
    meta["floor3"] = {"label": "Boiler power", "unit": "kW"}
    assert summarise_energy_totals(rows, meta) is None
    assert asks_for_a_total("How much power did the boiler draw yesterday?")
