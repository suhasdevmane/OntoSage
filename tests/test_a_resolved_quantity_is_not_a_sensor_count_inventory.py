# -*- coding: utf-8 -*-
"""A resolved quantity + an unnamed room/zone must not fall to the sensor-COUNT template
(BUG-1271's sibling, same file, two lines down).

MEASURED LIVE 2026-10-07, a 210-question stakeholder-persona sample through /v1. Two answers
stated "the building model only records how many sensors are installed in each space ... it
does not contain any information about background noise levels" and, separately, "... does
not contain any information about: capacity, accessibility, acoustics, lighting, network
service" -- both confidently false. This building has noise, illuminance and capacity data
throughout (used by other answers in the same sample and by this round's own capacity work).

`orchestrator/agents/sparql_agent.py`'s T2 "list zones" block has TWO templates back to back.
The first (a bare COUNT of spaces) already excludes a resolved `concept_class`, with a comment
explaining exactly why: "the wrong answer to any question the building's own vocabulary has
already recognised as being about something measurable". The second, three lines later --
`SELECT ?space (COUNT(?sensor) AS ?sensor_count) ...`, rows with no timeseries id -- did not
carry the same guard, so a question naming a real quantity ("background noise", "acoustics",
"lighting") but no specific room still fell into it whenever the dialogue stage resolved no
entity, which an unnamed/comparative room reference ("these two rooms", "this office") always
does.

Same shape as test_a_quantity_level_is_not_a_building_level.py (BUG-1271): a word list would
need extending per quantity and would still miss lay terms; `concept_class` is already
computed by the HBCO resolver and was merely being ignored at this one branch.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _agent():
    from orchestrator.agents.sparql_agent import SPARQLAgent

    return SPARQLAgent.__new__(SPARQLAgent)


def _is_sensor_count_inventory(sparql) -> bool:
    return isinstance(sparql, str) and "COUNT(?sensor) AS ?sensor_count" in sparql


@pytest.mark.parametrize(
    "question,concept_class",
    [
        # the two confirmed live false claims
        (
            "Can I choose a room with lower expected background noise for this meeting?",
            "ontosage:Sound_Level_Sensor",
        ),
        (
            "Which of these two rooms has better acoustics and lighting for a presentation?",
            "brick:Illuminance_Sensor",
        ),
        # the shape generalised to another quantity and an unnamed-room comparison
        ("Is this office warmer than the one next door?", "brick:Temperature_Sensor"),
    ],
)
def test_a_resolved_quantity_is_never_answered_with_a_sensor_count_inventory(
    question, concept_class
):
    out = _agent()._template_sparql(question, [], [], concept_class=concept_class)
    assert not _is_sensor_count_inventory(out), (
        f"{question!r} resolved {concept_class} and was still routed to a sensor-count "
        "inventory with no timeseries id — the reader is then told the building records "
        "nothing about the quantity it measures"
    )


def test_a_genuine_sensor_count_question_still_gets_the_count_template():
    """The counterfactual. A question that genuinely asks for a per-space sensor count, with
    no quantity resolved, must still be answered by this template -- the fix is a guard, not
    a removal (lesson #135's shape: a guard that silences a correct path too). "How many
    sensors are in each room?" is NOT this counterfactual: its `wants_count` phrasing matches
    the sibling bare-COUNT-of-spaces template three lines above instead, which is also
    correct and unaffected by this change."""
    question = "list the sensors per zone"
    out = _agent()._template_sparql(question, [], [], concept_class=None)
    assert _is_sensor_count_inventory(out), (
        f"{question!r} is a genuine per-space sensor-count question and must still be "
        "answered as one"
    )


def test_the_branch_consults_the_resolved_class():
    """Pins the MECHANISM: the sensor-count branch must read `concept_class`, the same way
    its sibling bare-COUNT branch three lines above it already does."""
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._template_sparql)
    i = src.index("COUNT(?sensor) AS ?sensor_count")
    i_guard = src.rfind("if any(w in uq for w in zone_words)", 0, i)
    assert i_guard != -1
    guard_line = src[i_guard : src.index("\n", i_guard)]
    assert "concept_class" in guard_line, (
        "the sensor-count branch's own if-condition no longer consults concept_class — a "
        "word list is not a substitute, the same reasoning as BUG-1271"
    )
