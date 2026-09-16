"""A question about what a plant circuit READS must not be answered from a register (2026-09-16).

"What's the delta-T across the heating circuit, and is it healthy?" matched PatrolCheckpoint
("circuit" is one of its lay terms) and came back as eighteen patrol checkpoints, while the
building's boilers, chiller and heat pump carry flow and return temperatures.
"""

import inspect

import pytest

from orchestrator.services.routing_contract import PLANT_READING_RE

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "q",
    [
        "What's the delta-T across the heating circuit, and is it healthy?",
        "what is the flow water temperature on the boiler?",
        "is the chilled loop temperature where it should be?",
        "what is the approach temperature on the chiller?",
    ],
)
def test_a_plant_reading_is_recognised(q):
    assert PLANT_READING_RE.search(q)


@pytest.mark.parametrize(
    "q",
    [
        "which checkpoints are on the north circuit?",
        "how many patrol circuits are there?",
        "which rooms are the stuffiest right now?",
        "how many open work orders are there?",
    ],
)
def test_an_ordinary_question_is_not_a_plant_reading(q):
    assert not PLANT_READING_RE.search(q)


def test_both_paths_that_resolve_a_record_class_honour_it():
    from orchestrator.agents import dialogue_agent, sparql_agent

    assert "PLANT_READING_RE" in inspect.getsource(dialogue_agent)
    assert "PLANT_READING_RE" in inspect.getsource(sparql_agent.SPARQLAgent._whole_register)
