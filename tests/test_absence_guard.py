# -*- coding: utf-8 -*-
"""BUG-192: an answer must not claim the building lacks a sensor class it has.

Measured on bldg2 (138 temperature sensors): "The ontology data you provided does
not contain any temperature sensors ... Therefore, I cannot list live room
temperatures." The refusal was right, the REASON was false — and because the leak
grader counts refusal markers, the false claim scored as a privacy PASS.

Precision matters more than recall here: a false positive rewrites a CORRECT
answer, so the detector must ignore windowing statements ("no data for 9am") and
empty result sets ("no rooms above 25 degrees").
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services.absence_guard import (
    correction_text,
    count_sensors,
    detect_absence_claim,
    guard_answer,
    modality_classes,
)

pytestmark = pytest.mark.unit


# ── detection: the real shapes seen live ─────────────────────────────────────


@pytest.mark.parametrize(
    "text, modality",
    [
        (
            "The ontology data you provided does **not** contain any temperature sensors.",
            "temperature",
        ),
        (
            "The ontology data does not contain any temperature sensors (e.g. no instances of "
            "`brick:TemperatureSensor`).",
            "temperature",
        ),
        ("This building has no humidity sensors.", "humidity"),
        ("There are no occupancy sensors in this building.", "occupancy"),
        ("The model lacks CO2 sensors.", "co2"),
        ("No noise sensors are present.", "noise"),
    ],
)
def test_absence_claims_are_detected(text, modality):
    assert detect_absence_claim(text) == modality


# ── precision: these must NOT be touched ─────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        # a windowing statement, not a capability claim
        "I couldn't find any readings for floor 1 at 9am today - the data covers 06:30 to 08:00.",
        # an empty RESULT set, not absent sensors
        "There are no rooms above 25 degrees right now.",
        # a normal answer
        "**Average temperature: 21.08 C** - latest reading from RM109_room.",
        # a referent decline (handled by the referent gate, not here)
        "I couldn't find **atrium** in this building's model.",
        # policy refusal — no capability claim at all
        "I can't answer that at the level you asked. Building-wide aggregates only.",
        "",
    ],
)
def test_non_absence_text_is_ignored(text):
    assert detect_absence_claim(text) is None


# ── verification gate ────────────────────────────────────────────────────────


def _sparql(count):
    async def _exec(_q):
        return {"results": {"bindings": [{"n": {"value": str(count)}}]}}

    return _exec


def test_a_true_absence_claim_is_left_alone():
    """0 sensors means the answer was RIGHT — never rewrite a correct statement."""
    text = "This building has no humidity sensors."
    out, violation = asyncio.run(guard_answer(text, "urn:b#", _sparql(0)))
    assert out == text and violation is None


def test_a_false_absence_claim_is_corrected():
    text = "The ontology data does not contain any temperature sensors."
    out, violation = asyncio.run(guard_answer(text, "urn:b#", _sparql(138)))
    assert out != text
    assert "138 temperature sensor" in out
    assert "not contain any temperature sensors" not in out
    assert violation["graph_count"] == 138 and violation["modality"] == "temperature"


def test_an_unverifiable_claim_is_left_alone():
    """A guard that cannot check has no business rewriting an answer."""

    async def _boom(_q):
        raise RuntimeError("graphdb down")

    text = "This building has no temperature sensors."
    out, violation = asyncio.run(guard_answer(text, "urn:b#", _boom))
    assert out == text and violation is None


def test_an_unknown_modality_is_not_guessed():
    assert asyncio.run(count_sensors("unicorns", "urn:b#", _sparql(5))) is None


def test_classes_come_from_the_shared_overlay_aware_config():
    """Not a second hardcoded map: a building overlay must be honoured (BUG-192/CAVEAT-148)."""
    assert "Relative_Humidity_Sensor" in modality_classes("humidity")
    assert modality_classes("unicorns") == ()


def test_the_correction_does_not_invent_a_reason():
    """We know the sensing claim is false; we do NOT know why the answer declined."""
    out = correction_text("temperature", 138, "original")
    assert "138" in out
    assert "isn't a lack of sensing" in out
    for invented in ("policy", "permission", "privacy", "not allowed"):
        assert invented not in out.lower()
