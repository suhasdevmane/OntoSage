# -*- coding: utf-8 -*-
"""CAVEAT-148: retrieval that returns the WRONG sensors must be repaired from the graph.

Live evidence on bldg2 — "What is the building-wide average humidity this week?"
generated SPARQL beginning:

    BIND(bldg:Building_Air_Static_Pressure_Sensor.01 AS ?sensor)

a PRESSURE sensor for a HUMIDITY question. Two sensors reached the fetch stage,
so the answer had to decline, and a "building-wide average" would have rested on
2 of ~70 humidity sensors.

The repair must be NARROW: it fires only on a total modality miss. A correct
retrieval, a mixed result, or a question with no clear modality must pass through
untouched — replacing those would trade one wrong answer for another.
"""

from __future__ import annotations

import pytest

from orchestrator.services.modality_repair import (
    build_modality_query,
    modality_classes,
    needs_repair,
    results_match_modality,
)

pytestmark = pytest.mark.unit


def _b(**vals):
    return {k: {"value": v} for k, v in vals.items()}


# ── class resolution comes from the shared config ────────────────────────────


def test_classes_are_resolved_from_the_modality_config():
    assert "Relative_Humidity_Sensor" in modality_classes("humidity")
    assert any("Temperature" in c for c in modality_classes("temperature"))


def test_an_unknown_modality_has_no_classes():
    assert modality_classes("unicorns") == ()


# ── matching ─────────────────────────────────────────────────────────────────


def test_the_live_failure_is_detected_as_a_miss():
    """Pressure sensors returned for a humidity question."""
    bindings = [
        _b(sensor="http://x#Building_Air_Static_Pressure_Sensor.01", label="Static Pressure"),
        _b(sensor="http://x#Building_Air_Static_Pressure_Sensor.02", label="Static Pressure"),
    ]
    assert results_match_modality(bindings, "humidity") is False
    assert needs_repair(bindings, "humidity") is True


def test_a_correct_retrieval_is_left_alone():
    bindings = [_b(sensor="http://x#Humidity_01", type="http://b#Relative_Humidity_Sensor")]
    assert results_match_modality(bindings, "humidity") is True
    assert needs_repair(bindings, "humidity") is False


def test_one_match_is_enough_to_leave_a_mixed_result_alone():
    """A wholesale replacement of a partially-right result would lose information."""
    bindings = [
        _b(sensor="http://x#Pressure_01", label="Static Pressure"),
        _b(sensor="http://x#Hum_02", label="Humidity"),
    ]
    assert needs_repair(bindings, "humidity") is False


def test_a_label_only_match_counts():
    assert results_match_modality([_b(label="Room Humidity")], "humidity") is True


# ── when the repair must NOT fire ────────────────────────────────────────────


def test_no_modality_means_no_repair():
    """Metadata/hierarchy questions have no modality — the LLM path owns them."""
    assert needs_repair([_b(sensor="http://x#Anything")], None) is False


def test_an_unknown_modality_never_triggers_a_guess():
    assert needs_repair([_b(sensor="http://x#Anything")], "unicorns") is False


def test_empty_results_with_a_known_modality_do_trigger_repair():
    """Retrieval finding nothing is exactly when the graph should be asked."""
    assert needs_repair([], "humidity") is True


# ── the deterministic query ──────────────────────────────────────────────────


def test_the_query_demands_a_timeseries_reference():
    """A sensor with no UUID cannot answer a data question."""
    q = build_modality_query("humidity", "http://b#")
    assert "ref:hasTimeseriesId" in q
    assert "Relative_Humidity_Sensor" in q


def test_the_query_is_scoped_to_the_building_and_bounded():
    q = build_modality_query("humidity", "http://b#")
    assert 'STRSTARTS(STR(?sensor), "http://b#")' in q
    assert "LIMIT" in q


def test_no_query_without_a_namespace_or_known_classes():
    assert build_modality_query("humidity", "") is None
    assert build_modality_query("unicorns", "http://b#") is None


# ── under-population: the right modality, but not enough of it ───────────────


@pytest.mark.parametrize(
    "q, expected",
    [
        ("What is the building-wide average humidity this week?", True),
        ("average temperature across the building", True),
        ("the temperature in every room on floor 1", True),
        ("What is the temperature in RM101 right now?", False),
        ("Which room is quietest?", False),
    ],
)
def test_aggregate_scope_is_detected(q, expected):
    from orchestrator.services.modality_repair import is_aggregate_question

    assert is_aggregate_question(q) is expected


def test_an_aggregate_question_asks_for_the_population():
    """8 genuine humidity sensors is still the wrong answer to a building-wide question."""
    from orchestrator.services.modality_repair import needs_population

    sample = [_b(sensor="http://x#Hum_%d" % i, label="Humidity") for i in range(8)]
    assert (
        needs_population(
            "What is the building-wide average humidity this week?", sample, "humidity"
        )
        is True
    )


def test_a_single_space_question_does_not():
    from orchestrator.services.modality_repair import needs_population

    assert (
        needs_population(
            "What is the temperature in RM101 right now?",
            [_b(sensor="http://x#T1", label="Temperature")],
            "temperature",
        )
        is False
    )


def test_no_modality_means_no_population_demand():
    from orchestrator.services.modality_repair import needs_population

    assert needs_population("How many floors are there?", [], None) is False
