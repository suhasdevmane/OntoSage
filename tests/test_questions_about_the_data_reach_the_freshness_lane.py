"""Questions about the DATA itself reach the lane that measures it (2026-10-11, r7 pool).

"How many sensors are connected and reporting?" was answered "18 sensors" from a label lookup;
"When was the building's sensor data last updated?" with "the data set does not contain a
timestamp"; "What data sources does the building have?" was declined. The observability lane's
freshness sweep and measurement menu answer all three.
"""

from __future__ import annotations

import pytest

from orchestrator.services import observability as ob

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q",
    [
        "How many sensors are connected and reporting?",
        "When was the building's sensor data last updated?",
        "Is the sensor data up to date?",
        "Are all the meters online?",
    ],
)
def test_a_positive_health_question_runs_the_sweep(q):
    assert ob.is_silence_question(q)
    assert ob.is_observability_question(q)


@pytest.mark.parametrize(
    "q", ["What data sources does the building have?", "What kinds of data does it collect?"]
)
def test_a_data_sources_question_gets_the_menu(q):
    assert ob.is_observability_question(q)


@pytest.mark.parametrize(
    "q",
    [
        "What is the CO2 in room 2.13?",
        "Show me the data from the current week",
        "How many people are in the building?",
    ],
)
def test_a_reading_question_does_not(q):
    assert not ob.is_observability_question(q)


@pytest.mark.parametrize(
    "q, want",
    [
        ("What units are the illuminance readings in?", "**Illuminance** readings are in **lux**"),
        ("What is the unit for CO2?", "**CO2** readings are in **ppm**"),
    ],
)
def test_a_units_question_gets_the_declared_unit(q, want):
    assert want in (ob.units_answer(q, building_id="bldg1") or "")


@pytest.mark.parametrize(
    "q", ["Which unit manages the building?", "What unit of the university runs it?"]
)
def test_an_organisational_unit_is_not_a_units_question(q):
    assert ob.units_answer(q) is None
