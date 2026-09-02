# -*- coding: utf-8 -*-
"""A deliberative question reaches the deliberative lane whatever the classifier says.

CAVEAT-327 measured plan reproducibility at 3/8 for ONE model run twice, which put
cross-model agreement (2/8) at or below the noise floor and made the invariance claim
unmeasurable. BUG-184 had already split the mismatches by cause, and the split matters:

    2/8   LANE DOWNGRADE   -- the second run never entered the deliberative lane and
                              produced a reflex plan. A routing problem.
    1/8   COMPILE DIVERGENCE -- the same lane, a different program.

So the downgrades were the LARGER contributor, and they are the deterministic half:
nothing about them requires the LLM to behave.

All ten benchmark questions match ``DELIBERATE_RE``, so the pattern was never the gap.
The two rules that route to the lane gated on DISJOINT intent sets -- weak intents plus
``recommend`` in one, ``analytics``/``sensor_data`` in the other -- and any question the
classifier put elsewhere fell between them. Naming a floor pulls a question toward
``floor_plan``; "where can I sit near the cafe" pulls toward ``spatial_query``. Neither
was covered.

The widening is safe because DELIBERATE_RE must still match, and it requires a
superlative or an explicit should-I shape. The tests below hold both ends: the
deliberative shapes arrive from every intent the classifier is observed to pick, and
plain floor-plan and wayfinding questions keep their own lanes.
"""

import pytest

from orchestrator.services.routing_contract import (
    _SUPERLATIVE_TAKEOVER_INTENTS,
    _WEAK_INTENTS,
    DELIBERATE_RE,
)

pytestmark = pytest.mark.unit

#: The L7 bank the multi-model benchmark actually runs, verbatim from
#: scripts/generate_l7_bank.py with the placeholders filled.
_BENCHMARK_QUESTIONS = [
    "Which room on floor 2 is the quietest right now?",
    "Show me the zone with minimum occupancy.",
    "Which room on floor 2 has the lowest CO2 right now?",
    "Which room is the warmest in the whole building right now?",
    "Rank the rooms on floor 2 by noise level.",
    "Where can I sit that's quiet, with good air, near the cafe?",
    "Find me a warm room to work in",
    "Where is the most comfortable place to sit at the moment?",
]


@pytest.mark.parametrize("question", _BENCHMARK_QUESTIONS)
def test_every_benchmark_question_matches_the_deliberative_shape(question):
    """If this fails, the invariance benchmark is measuring a lane it never enters."""
    assert DELIBERATE_RE.search(question), question


def test_the_two_rules_between_them_cover_every_plausible_classification():
    """The hole between the two gates is what produced the downgrades.

    Listed explicitly rather than computed, so that adding an intent to the registry
    without deciding whether a superlative can land in it is a visible choice.
    """
    covered = set(_WEAK_INTENTS) | {"recommend"} | set(_SUPERLATIVE_TAKEOVER_INTENTS)
    for intent in ("floor_plan", "spatial_query", "analytics", "sensor_data", "compare", "trend"):
        assert intent in covered, f"a superlative classified {intent!r} reaches no deliberate rule"


def test_the_floor_plan_intent_is_covered_because_naming_a_floor_pulls_there():
    """The specific downgrade: "which room on floor 2 is the quietest" carries a floor,
    and a floor in a question is exactly what makes the classifier say floor_plan."""
    assert "floor_plan" in _SUPERLATIVE_TAKEOVER_INTENTS


# -- and the widening steals nothing ------------------------------------------
@pytest.mark.parametrize(
    "question",
    [
        "show me floor 2",
        "Show me the floor plan for level 3.",
        "where is room 2.14?",
        "How do I get to the seminar room on level 3?",
        "Take me to the nearest accessible toilet from where I'm standing.",
        "how many rooms are on floor 2?",
        "what is the area of room 2.14?",
    ],
)
def test_plain_floor_plan_and_wayfinding_questions_are_untouched(question):
    """The gate widened, but DELIBERATE_RE is still the thing that has to match. A
    question with no superlative and no should-I shape never reaches the lane, so
    floor_plan and spatial_query keep their own work."""
    assert not DELIBERATE_RE.search(question), question


@pytest.mark.parametrize(
    "question",
    [
        "which policy should I read?",
        "which room is 2.14?",
        "which building is this?",
    ],
)
def test_should_i_and_which_shapes_without_a_preference_stay_out(question):
    assert not DELIBERATE_RE.search(question), question
