# -*- coding: utf-8 -*-
"""BUG-554: the recommendation prompt summarises EVERY series fetched, and knows energy data."""

import inspect
from datetime import datetime, timedelta

import pytest

from orchestrator.services.series_summary import summarise_series

pytestmark = pytest.mark.unit


def _rows(uuid, base, n=48, night=5.0, day=12.0):
    start = datetime(2026, 9, 14, 0, 0)
    out = []
    for i in range(n):
        t = start + timedelta(hours=i / 2)
        out.append({"timestamp": t.strftime("%Y-%m-%dT%H:%M:%S"), "uuid": uuid,
                    "value": base + (night if t.hour < 5 else day)})
    return out


META = {
    f"u{i}": {"label": f"Energy Meter Floor{i}", "unit": "kWh", "kind": "energy",
              "sensor_uri": f"http://x#Energy_Meter_Floor{i}"}
    for i in range(6)
}


def test_every_series_gets_a_line_even_when_rows_are_grouped_by_series():
    rows = [r for i in range(6) for r in _rows(f"u{i}", base=i)]
    text, energy = summarise_series(rows, META, "Europe/London")
    assert energy is True
    for i in range(6):
        assert f"Energy Meter Floor{i}:" in text
    assert "u0" not in text and "uuid" not in text.lower()  # names, never identifiers


def test_night_and_day_means_are_given_in_building_time():
    text, _ = summarise_series(_rows("u1", base=0), {"u1": META["u1"]}, "Europe/London")
    assert "night (00-06) mean" in text and "day (08-18) mean" in text
    assert "(building time)" in text


def test_energy_is_recognised_from_the_unit_alone():
    rows = _rows("m", base=1, n=4)
    _, energy = summarise_series(rows, {"m": {"label": "Main incomer", "unit": "kW"}})
    assert energy is True
    _, energy = summarise_series(rows, {"m": {"label": "Room 5.01 CO2", "unit": "ppm"}})
    assert energy is False


def test_the_recommend_node_uses_the_summary_not_the_last_five_rows():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._recommend_node)
    assert "summarise_series(" in src and "rows[-5:]" not in src
    assert "_series_are_energy" in src
