# -*- coding: utf-8 -*-
"""A turn the asset-state lane cannot serve is handed to the data pipeline, not refused.

Live, unscripted, 2026-09-18: "Is the heat pump running?" -> "I couldn't tell which service or
asset you meant, so I'm not guessing." The building has exactly one heat pump; nothing was
ambiguous. The classifier chose `asset_state` from the SHAPE "is the X running", and that lane
knows three families (lifts, AV, network). Its docstring says a `None` classification means "this
lane should not have been asked". The rule under test acts on that sentence.
"""

from __future__ import annotations

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit


def _run(query: str, intent: str = "asset_state"):
    ctx = rc._Ctx(query=query, ql=query.lower(), normalized={"intent": intent}, sr=None)
    return rc._r_asset_state_without_a_family(ctx)


@pytest.mark.parametrize(
    "question",
    [
        "Is the heat pump running?",
        "Is the chiller working?",
        "Is the boiler running?",
        "Are the air handling units operational?",
        "Is the generator available?",
    ],
)
def test_equipment_the_lane_has_no_family_for_goes_to_the_data_pipeline(question):
    assert _run(question) == "sensor_data", question


@pytest.mark.parametrize(
    "question",
    [
        "Is the lift working?",
        "Is the elevator out of service?",
        "Is the wifi down?",
        "Is the network working?",
        "Is the projector in Room 1.06 working?",
        "Is the AV kit operational?",
    ],
)
def test_a_question_the_lane_can_serve_is_left_exactly_where_it_was(question):
    """The whole safety argument: every turn that gets a correct asset-state answer today."""
    assert _run(question) is None, question


@pytest.mark.parametrize("intent", ["sensor_data", "capability", "metadata", "analytics", "general"])
def test_the_rule_only_ever_acts_on_an_asset_state_intent(intent):
    assert _run("Is the heat pump running?", intent=intent) is None


def test_the_rule_is_registered_after_promotion_and_named():
    names = [r.name for r in rc.POST_STAGE_RULES]
    assert names.index("asset_state_without_a_family") > names.index("data_query_promotion")
    rule = next(r for r in rc.POST_STAGE_RULES if r.name == "asset_state_without_a_family")
    assert rule.shape.strip()
    assert rule.preserve_analytics is True


def test_the_rule_carries_no_building_literal():
    import inspect

    src = inspect.getsource(rc._r_asset_state_without_a_family).lower()
    for literal in ("abacws", "bldg1", "cardiff", "heat_pump_1"):
        assert literal not in src, literal
