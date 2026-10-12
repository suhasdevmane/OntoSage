"""A future comparison of two places is two forecasts, compared with their bands (CAVEAT-1558).

"Will floor 3 be warmer than floor 4 tomorrow?" was answered from two past means (BUG-1545).
A difference is stated only when the 80% bands do not overlap. Synthetic data, no building.
"""

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import forecast_comparison as fc

pytestmark = pytest.mark.unit


def test_two_floors_or_two_rooms_are_the_places():
    assert fc.named_places("Will floor 3 be warmer than floor 4 tomorrow?") == [
        ("floor", "3"),
        ("floor", "4"),
    ]
    assert fc.named_places("Will room 5.01 be noisier than room 2.03 tomorrow?") == [
        ("room", "5.01"),
        ("room", "2.03"),
    ]
    assert fc.named_places("Will floor 3 be warm tomorrow?") == []


def test_sensors_are_grouped_by_the_graph_s_placement_not_their_labels():
    located = {
        "a": SimpleNamespace(room="Room 3.01", floor="3"),
        "b": SimpleNamespace(room="Room 3.02", floor="3"),
        "c": SimpleNamespace(room="Room 4.01", floor="4"),
    }
    groups = fc.group_by_place([("floor", "3"), ("floor", "4")], located)
    assert groups == {"Floor 3": ["a", "b"], "Floor 4": ["c"]}


def _r(mid, lo, hi):
    return {
        "success": True,
        "forecast": [mid] * 3,
        "lower_80": [lo] * 3,
        "upper_80": [hi] * 3,
        "model": "Holt-Winters",
        "n_history": 193,
        "metrics": {"mae": 0.3},
        "unit": "°C",
    }


def test_overlapping_bands_say_neither_is_warmer():
    text = fc.render(
        "Will floor 3 be warmer than floor 4 tomorrow?",
        "temperature",
        "°C",
        {"Floor 3": _r(23.1, 22.4, 23.8), "Floor 4": _r(23.0, 22.2, 23.7)},
        "tomorrow",
    )
    assert "overlap" in text.splitlines()[0]
    assert "will be warmer" not in text


def test_separate_bands_state_the_difference():
    text = fc.render(
        "Will floor 3 be warmer than floor 4 tomorrow?",
        "temperature",
        "°C",
        {"Floor 3": _r(24.5, 24.1, 24.9), "Floor 4": _r(22.0, 21.6, 22.4)},
        "tomorrow",
    )
    assert text.startswith("**Floor 3 is forecast to be warmer than Floor 4 tomorrow, by about 2.5")


def test_a_cooler_question_is_answered_in_its_own_direction():
    text = fc.render(
        "Will floor 3 be cooler than floor 4 tomorrow?",
        "temperature",
        "°C",
        {"Floor 3": _r(24.5, 24.1, 24.9), "Floor 4": _r(22.0, 21.6, 22.4)},
        "tomorrow",
    )
    assert text.startswith("**Floor 4 is forecast to be cooler than Floor 3 tomorrow")


def test_the_comparison_forecasts_each_place_with_its_own_sensors():
    meta = {"a": {"label": "t a"}, "b": {"label": "t b"}, "c": {"label": "t c"}}
    seen = {}

    async def sparql(_q):
        return {
            "results": {
                "bindings": [
                    {
                        "uuid": {"value": "a"},
                        "locLabel": {"value": "Room 3.01"},
                        "floorNum": {"value": "3"},
                    },
                    {
                        "uuid": {"value": "b"},
                        "locLabel": {"value": "Room 3.02"},
                        "floorNum": {"value": "3"},
                    },
                    {
                        "uuid": {"value": "c"},
                        "locLabel": {"value": "Room 4.01"},
                        "floorNum": {"value": "4"},
                    },
                ]
            }
        }

    async def predict(_state, q, _sql, sub_meta):
        seen[q] = sorted(sub_meta)
        return _r(23.0, 22.0, 24.0)

    out = asyncio.run(
        fc.compare_forecasts(
            None, "Will floor 3 be warmer than floor 4 tomorrow?", meta, {}, sparql, predict
        )
    )
    assert out and out["source"] == "forecast_comparison"
    assert seen == {
        "Forecast the average temperature on floor 3 tomorrow": ["a", "b"],
        "Forecast the average temperature on floor 4 tomorrow": ["c"],
    }


def test_a_place_with_no_bound_sensor_stands_down():
    async def sparql(_q):
        return {
            "results": {
                "bindings": [
                    {
                        "uuid": {"value": "a"},
                        "locLabel": {"value": "Room 3.01"},
                        "floorNum": {"value": "3"},
                    },
                ]
            }
        }

    async def predict(*_a):
        raise AssertionError("must not forecast")

    assert (
        asyncio.run(
            fc.compare_forecasts(
                None,
                "Will floor 3 be warmer than floor 4 tomorrow?",
                {"a": {}},
                {},
                sparql,
                predict,
            )
        )
        is None
    )
