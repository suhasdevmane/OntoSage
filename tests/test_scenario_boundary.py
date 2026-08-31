# -*- coding: utf-8 -*-
"""What-if questions are declined, and the decline says what would answer them (V7-T80).

The building holds sensors and records, not a thermal, hydraulic or electrical model.
"If power fails, how long do the lab freezers stay safe?" therefore has no grounded
answer — and a model left to run will produce a confident one from physical intuition,
which is the most dangerous answer this system could give.

Both halves are required to fire: a hypothetical premise AND a request for its
consequence. One without the other is ordinary language.
"""

from __future__ import annotations

import pytest

from orchestrator.services.routing_contract import scenario_question

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query",
    [
        "If power fails, how long do the lab freezers stay safe?",
        "What if the chiller goes down during a heatwave — what would happen to the labs?",
        "Suppose the main AHU stopped, how long would CO2 stay acceptable?",
        "In the event of a lift failure, how many people would be affected?",
        "What would happen if we lost the mains supply overnight?",
        "Assuming the boiler fails, would the building stay above 16 degrees?",
    ],
)
def test_a_scenario_is_recognised(query):
    assert scenario_question(query), query


@pytest.mark.parametrize(
    "query",
    [
        "How long does the lift take to reach floor 5?",  # consequence, no premise
        "If you can, show me the floor 3 layout",  # conditional, no consequence
        "What is the temperature in room 5.04?",
        "How many permits are open?",
        "Which rooms failed the CO2 threshold last week?",
        "What happened during yesterday's alarm?",  # a RECORDED event, not a what-if
    ],
)
def test_ordinary_questions_are_left_alone(query):
    assert not scenario_question(query), query


def test_the_rule_fires_before_anything_that_could_compute_a_number():
    """A scenario must never reach a lane that could compute a plausible figure for it.

    Being literally first is not the invariant — `answer_provenance` was later placed
    ahead of it, and reading back an evidence record cannot fabricate a scenario answer.
    What matters is that no rule capable of routing to a DATA lane runs earlier.
    """
    from orchestrator.services import routing_contract as rc

    names = [r.name for r in rc.PARSE_STAGE_RULES]
    position = names.index("scenario_boundary")
    # Everything ahead of it must be a refusal or a read-back lane, never a data route.
    assert set(names[:position]) <= {
        "answer_provenance",
        "inference_privacy_denial",
    }, f"a data-routing rule now precedes the scenario boundary: {names[:position]}"
