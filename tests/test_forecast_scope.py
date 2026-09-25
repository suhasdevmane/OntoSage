# -*- coding: utf-8 -*-
"""W2-02 — a forecast about a floor is not a forecast of one room on it.

Measured live 2026-09-23:

    "Predict the average CO2 on floor 3 for tomorrow afternoon."
    -> "## Forecast: CO2 Level Sensor installed-node 3.58"   (floor 3 has 45 instrumented rooms)

    "What will the building's energy use be tomorrow?"
    -> "## Forecast: Electrical Energy Meter - Floor 0"      (one floor of six)

Both were correct forecasts of the wrong thing. The sensor is named in the heading, so the
substitution is not concealed — but a reader who asked about floor 3 has no reason to read that
heading as a correction of their question, and nothing else in either answer said so.

MEAN OR TOTAL IS NOT A STYLE CHOICE, which is why it is tested hardest here. A floor's CO2 is
the mean of its rooms; a floor's energy is the sum of its meters. Averaging six meters reports
a sixth of the building's consumption with every digit correct.
"""

from __future__ import annotations

import pytest

from orchestrator.services.forecasting import scope

pytestmark = pytest.mark.unit


# ── which questions need an aggregate ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Predict the average CO2 on floor 3 for tomorrow afternoon.",
        "What will the building's energy use be tomorrow?",
        "Forecast total energy across the building next week",
        "What will the typical noise be on level 2 this evening?",
        "predict occupancy across all floors tomorrow",
    ],
)
def test_a_question_about_a_floor_or_the_building_needs_an_aggregate(question):
    assert scope.detect(question) is not None, question


@pytest.mark.parametrize(
    "question",
    [
        "Predict the CO2 in room 5.01 for the next 24 hours",
        "What will the temperature be tomorrow in Room 2.01?",
        # A named room WINS even when a floor is also mentioned: the question is about the room.
        "predict the average co2 in room 3.10 on floor 3",
        "Project the noise level in the atrium for the next 12 hours",
        "Will the CO2 in room 5.01 exceed 1000 ppm tomorrow afternoon?",
    ],
)
def test_a_question_about_one_place_is_left_to_the_single_sensor_path(question):
    """None leaves the existing behaviour exactly as it was, which is correct for these."""
    assert scope.detect(question) is None, question


# ── mean or total, from the QUANTITY and never from the wording ─────────────────────


@pytest.mark.parametrize(
    "labels,question",
    [
        (["Electrical Energy Meter — Floor 0"], "what will the building's energy use be"),
        (["Water Flow Meter F2"], "total water across the building tomorrow"),
        (["Waste Fill Sensor"], "waste across the site next week"),
        (["Entry Count Sensor F2"], "predict the count across all floors"),
    ],
)
def test_an_extensive_quantity_is_summed(labels, question):
    assert scope.how_to_combine(labels, question) == "total"


@pytest.mark.parametrize(
    "labels,question",
    [
        (["CO2 Level Sensor installed-node 3.58"], "average co2 on floor 3"),
        (["Zone Air Temperature Sensor 2.01"], "typical temperature on floor 2"),
        (["Sound Level Sensor 4.10"], "noise across the building"),
        (["Relative Humidity Sensor"], "humidity on level 5"),
    ],
)
def test_an_intensive_quantity_is_averaged(labels, question):
    assert scope.how_to_combine(labels, question) == "mean"


def test_the_word_total_in_the_question_does_not_make_a_concentration_additive():
    """Summing 45 rooms of CO2 gives 33,000 ppm. The quantity decides, not the phrasing."""
    assert scope.how_to_combine(["CO2 Level Sensor 3.58"], "total co2 on floor 3") == "mean"


# ── the fold ─────────────────────────────────────────────────────────────────────────


def _rows():
    return [
        {"uuid": "a", "timestamp": "2026-09-23 10:00:00", "value": 700},
        {"uuid": "b", "timestamp": "2026-09-23 10:00:00", "value": 800},
        {"uuid": "a", "timestamp": "2026-09-23 11:00:00", "value": 600},
        {"uuid": "b", "timestamp": "2026-09-23 11:00:00", "value": 900},
    ]


def test_a_mean_folds_each_bucket_across_sensors():
    folded, n = scope.aggregate_records(_rows(), "mean")
    assert n == 2
    assert [r["value"] for r in folded] == [750.0, 750.0]
    assert {r["uuid"] for r in folded} == {"__aggregate__"}


def test_a_total_adds_each_bucket_across_sensors():
    folded, n = scope.aggregate_records(_rows(), "total")
    assert [r["value"] for r in folded] == [1500.0, 1500.0]
    assert n == 2


def test_buckets_come_out_in_time_order():
    shuffled = list(reversed(_rows()))
    folded, _ = scope.aggregate_records(shuffled, "mean")
    stamps = [r["timestamp"] for r in folded]
    assert stamps == sorted(stamps)


def test_unreadable_values_are_skipped_rather_than_poisoning_the_bucket():
    rows = _rows() + [
        {"uuid": "c", "timestamp": "2026-09-23 10:00:00", "value": None},
        {"uuid": "d", "timestamp": "2026-09-23 10:00:00", "value": "n/a"},
    ]
    folded, _n = scope.aggregate_records(rows, "mean")
    assert folded[0]["value"] == 750.0


def test_an_empty_set_folds_to_nothing_rather_than_to_zero():
    folded, n = scope.aggregate_records([], "total")
    assert folded == [] and n == 0


# ── the denominator must reach the reader ────────────────────────────────────────────


def test_the_answer_states_how_many_sensors_it_averaged():
    note = scope.denominator_note("mean", 45, "average on floor 3")
    assert "45 sensors" in note and "averaged over" in note


def test_a_total_says_summed_not_averaged():
    note = scope.denominator_note("total", 6, "the building")
    assert "summed across" in note and "6 sensors" in note


def test_one_sensor_gets_no_denominator_sentence():
    """With one sensor there is no substitution to disclose, and the sentence would be noise."""
    assert scope.denominator_note("mean", 1, "floor 3") == ""
    assert scope.denominator_note("mean", 0, "floor 3") == ""


# ── building-agnostic ────────────────────────────────────────────────────────────────


def test_the_module_names_no_building_no_floor_and_no_modality():
    import ast
    from pathlib import Path

    src = Path("orchestrator/services/forecasting/scope.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    code = ast.unparse(ast.fix_missing_locations(tree))
    for literal in ("bldg1", "abacws", "co2", "3.58", "cardiff"):
        assert literal not in code.lower(), literal


def test_a_quantity_called_a_level_is_not_read_as_a_floor():
    """"the noise LEVEL IN the atrium" was aggregated across the building as floor scope.

    "level" is the second half of "noise level", "CO2 level" and "water level" at least as
    often as it names a storey, so the floor word must carry a number.
    """
    for question in (
        "Project the noise level in the atrium for the next 12 hours",
        "predict the CO2 level in the lab tomorrow",
        "what will the water level in the tank be",
    ):
        assert scope.detect(question) is None, question


def test_a_numbered_floor_is_still_a_floor():
    for question in ("average co2 on level 2 tomorrow", "noise on floor 4 this evening"):
        assert scope.detect(question) is not None, question
