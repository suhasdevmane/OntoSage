"""V4-T15 tests — NL -> CQ-IR compilation with canned LLM outputs (fully offline)."""

from __future__ import annotations

import asyncio
import json

import pytest

from orchestrator.services.deliberation.compiler import compile_query
from orchestrator.services.deliberation.coverage_audit import ModalitySpec
from orchestrator.services.deliberation.cqir import (
    DecisionKind,
    Direction,
    Hardness,
    SpatialRelation,
    ThresholdSource,
    TimeBasis,
)

pytestmark = pytest.mark.unit

MODALITIES = [
    ModalitySpec("noise", ["Sound_Level_Sensor"]),
    ModalitySpec("co2", ["CO2_Level_Sensor"]),
    ModalitySpec("occupancy", ["Occupancy_Count_Sensor"]),
    ModalitySpec("temperature", ["Temperature_Sensor"]),
]


def _llm(payload):
    async def call(prompt: str) -> str:
        return "Here is the JSON:\n" + json.dumps(payload)

    return call


def _compile(payload, query="q"):
    # use_cache=False: these are OFFLINE tests of the compiler, and the cache would
    # reach for a Redis that is not there -- costing a DNS timeout per call and
    # testing the fail-open path over and over instead of the compiler.
    return asyncio.run(compile_query(query, MODALITIES, llm_call=_llm(payload), use_cache=False))


FLAGSHIP = {
    "decision": "select_one",
    "constraints": [
        {"phrase": "quiet", "modality": "noise", "direction": "minimize", "hardness": "soft"},
        {"phrase": "good air", "modality": "co2", "direction": "minimize", "hardness": "soft"},
    ],
    "spatial": [{"relation": "near_amenity", "anchor": "DrinkingWater", "phrase": "near water"}],
    "time": {"basis": "forecast", "horizon_hours": 24, "window_hours": None, "phrase": "tomorrow"},
    "time_phrase_unclear": "",
    "unmapped": [],
}


def test_flagship_compiles_executable():
    ir = _compile(
        FLAGSHIP, "I'm visiting tomorrow — where can I sit that's quiet, good air, near water?"
    )
    assert ir.is_executable()
    assert ir.decision == DecisionKind.SELECT_ONE
    assert {c.modality for c in ir.constraints} == {"noise", "co2"}
    assert all(
        c.direction == Direction.MINIMIZE and c.hardness == Hardness.SOFT for c in ir.constraints
    )
    assert ir.spatial[0].relation == SpatialRelation.NEAR_AMENITY
    assert ir.spatial[0].anchor == "DrinkingWater"
    assert ir.time.basis == TimeBasis.FORECAST and ir.time.horizon_hours == 24


def test_whole_building_scope_is_dropped_not_ambiguous():
    """BUG-163 tail: 'in the whole building' is the default scope, never an
    unresolved anchor that traps the user in a rephrase ask."""
    payload = dict(
        FLAGSHIP,
        constraints=[{"phrase": "warmest", "modality": "temperature", "direction": "maximize"}],
        spatial=[
            {
                "relation": "in_space",
                "anchor": "the whole building",
                "phrase": "in the whole building",
            }
        ],
        time={"basis": "now", "horizon_hours": None, "window_hours": None, "phrase": ""},
    )
    ir = _compile(payload, "Which room is the warmest in the whole building right now?")
    assert ir.is_executable()
    assert ir.spatial == []
    assert not any(s.kind == "unresolved_anchor" for s in ir.signals)
    # anchor-less variants ('building-wide', phrase-only) drop too
    payload["spatial"] = [{"relation": "in_space", "anchor": "", "phrase": "across the building"}]
    ir2 = _compile(payload)
    assert ir2.spatial == [] and not any(s.kind == "unresolved_anchor" for s in ir2.signals)


def test_unknown_modality_becomes_signal_never_a_guess():
    payload = dict(
        FLAGSHIP,
        constraints=[{"phrase": "low radiation", "modality": "radiation", "direction": "minimize"}],
    )
    ir = _compile(payload)
    assert not ir.is_executable()
    assert any(s.kind == "unmapped_term" and "radiation" in s.note for s in ir.signals)
    assert ir.constraints == []


def test_user_threshold_recorded_with_source():
    payload = dict(
        FLAGSHIP,
        constraints=[
            {
                "phrase": "below 800 ppm",
                "modality": "co2",
                "direction": "below",
                "hardness": "hard",
                "threshold": 800,
            }
        ],
    )
    ir = _compile(payload)
    c = ir.constraints[0]
    assert c.threshold == 800.0 and c.threshold_source == ThresholdSource.USER
    assert c.hardness == Hardness.HARD


def test_no_threshold_defaults_to_recipe_source():
    ir = _compile(FLAGSHIP)
    assert all(c.threshold_source == ThresholdSource.RECIPE for c in ir.constraints)


def test_unclear_time_phrase_is_a_signal_not_a_default():
    payload = dict(FLAGSHIP, time_phrase_unclear="when the stars align")
    ir = _compile(payload)
    assert ir.time.unparseable
    assert any(s.kind == "unparseable_time" for s in ir.signals)
    assert not ir.is_executable()


def test_bad_relation_or_anchor_becomes_signal():
    payload = dict(FLAGSHIP, spatial=[{"relation": "teleport", "anchor": "", "phrase": "x"}])
    ir = _compile(payload)
    assert any(s.kind == "unresolved_anchor" for s in ir.signals)
    assert ir.spatial == []


def test_garbage_llm_output_is_vague_signal():
    async def bad(prompt: str) -> str:
        return "I cannot answer that."

    ir = asyncio.run(compile_query("q", MODALITIES, llm_call=bad, use_cache=False))
    assert not ir.is_executable()
    assert any(s.kind == "vague" for s in ir.signals)


def test_empty_constraints_flags_vague():
    payload = dict(FLAGSHIP, constraints=[], unmapped=[])
    ir = _compile(payload)
    assert any(s.kind == "vague" for s in ir.signals)


def test_fingerprint_deterministic_for_same_program():
    a, b = _compile(FLAGSHIP, "phrasing one"), _compile(FLAGSHIP, "totally different phrasing")
    assert a.plan_fingerprint() == b.plan_fingerprint()


# ── a direction the model omitted, read from the phrase it came with ──────────────────
#
# Measured live 2026-09-23, two questions, one minute apart, same two modalities:
#
#   "is anywhere both hot and noisy"        -> directions emitted, rooms ranked, answered
#   "which rooms are both warm and stuffy"  -> direction "none" for both, REFUSED
#
# The refusal message named its own cure: "I couldn't map part of your request (warm; stuffy)".
# `_LAY_POLARITY` already records that warm is the high end of temperature and stuffy the high
# end of CO2, and `_constraint_from_phrase` already trusts it for phrases the model left in
# `unmapped` -- it was simply never consulted where a MAPPED constraint arrives without a
# direction. A refusal manufactured out of temp-0 provider wobble is not honesty.


def test_a_polarity_word_supplies_a_direction_the_model_left_out():
    from orchestrator.services.deliberation.compiler import _direction_from_phrase_polarity

    assert _direction_from_phrase_polarity("warm") is Direction.MAXIMIZE
    assert _direction_from_phrase_polarity("stuffy") is Direction.MAXIMIZE
    assert _direction_from_phrase_polarity("the coolest corner") is Direction.MINIMIZE


def test_an_avoidance_phrase_is_left_for_a_human_rather_than_inverted():
    """"less stuffy" and "stuffy" name the same modality and OPPOSITE ends."""
    from orchestrator.services.deliberation.compiler import _direction_from_phrase_polarity

    for phrase in ("less stuffy", "avoid the noisy rooms", "somewhere without bright light"):
        assert _direction_from_phrase_polarity(phrase) is None, phrase


def test_two_words_pulling_opposite_ways_decline_rather_than_pick_one():
    from orchestrator.services.deliberation.compiler import _direction_from_phrase_polarity

    assert _direction_from_phrase_polarity("warm but not cold") is None


def test_a_word_with_no_polarity_of_its_own_still_refuses():
    """This is the boundary that keeps the fix a robustness fix.

    "temperature" and "occupancy" have no better end without a preference, and inventing one
    would answer a question nobody asked. `_infer_direction` still owns those.
    """
    from orchestrator.services.deliberation.compiler import _direction_from_phrase_polarity

    for phrase in ("temperature", "the occupancy", "co2 level", ""):
        assert _direction_from_phrase_polarity(phrase) is None, phrase
