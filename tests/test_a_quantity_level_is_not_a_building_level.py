# -*- coding: utf-8 -*-
"""A "<quantity> level" question must not be answered with a list of floors (BUG-1271).

MEASURED LIVE 2026-09-30, occupant on /v1. "What is the average sound level?" returned
*"I couldn't answer that from Abacws Building's records"* — about a building holding **235
sound/noise sensors with timeseries references**. The container log gives the whole chain:

    [sparql] class from HBCO concept 'noisy': ontosage:Sound_Level_Sensor   <- 233 instances
    Using template SPARQL (entities=[]):
      SELECT ?floor ?label WHERE { ?floor a brick:Floor ... }               <- floors
    GraphDB query returned 8 results                                        <- 8 floors
    [analytics] No UUIDs found — no specific sensor type detected           <- it WAS detected
    [response] relevance gate replaced a analytics answer: OFF_TOPIC
    [response] nothing to say

`floor_words` contains "level", so "sound LEVEL" matched the floor branch, and that branch
never consulted `concept_class` — which had been resolved and logged one line earlier. The
relevance gate was RIGHT to call a floor list off-topic; the defect is upstream of it, and the
visible result was a false statement about what the building records.

WHY KEYING ON THE RESOLVED CLASS AND NOT ON A WORD LIST. A word list ("sound level", "VOC
level", …) would need extending for every quantity and would still miss lay terms — "stuffy",
"noisy" — which is what HBCO exists to resolve. The resolved class is already computed, already
passed into `_template_sparql`, and was merely being ignored. It also cannot over-capture: a
genuine "how many floors are there?" resolves no sensor concept.

BLAST RADIUS, measured over both corpora before the change: **284 questions** say
"<quantity> level(s)" — **269 in the REAL survey corpus**, 3.8% of everything 96 participants
asked. In that corpus **zero** questions use "level <n>" for a storey; only the synthetic bank
does (22). Among real users, "level" after a quantity word never means storey.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _agent():
    from orchestrator.agents.sparql_agent import SPARQLAgent

    return SPARQLAgent.__new__(SPARQLAgent)


def _is_floor_listing(sparql) -> bool:
    return isinstance(sparql, str) and "?floor a brick:Floor" in sparql


@pytest.mark.parametrize(
    "question,concept_class",
    [
        # the two confirmed live false absences
        ("What is the average sound level?", "ontosage:Sound_Level_Sensor"),
        ("What is the VOC level", "brick:TVOC_Sensor"),
        # the shape, from the real survey corpus
        ("are there any areas where noise levels suddenly increased?", "ontosage:Sound_Level_Sensor"),
        ("is the lighting level appropriate for presentations or screen viewing?", "brick:Illuminance_Sensor"),
        ("What's a normal CO2 level, and how does my office compare right now?", "brick:CO2_Sensor"),
        # a floor word AND a resolved quantity: still not an inventory question
        ("Which floor is the warmest?", "brick:Temperature_Sensor"),
    ],
)
def test_a_resolved_quantity_is_never_answered_with_a_floor_inventory(question, concept_class):
    out = _agent()._template_sparql(question, [], [], concept_class=concept_class)
    assert not _is_floor_listing(out), (
        f"{question!r} resolved {concept_class} and was still routed to a list of floors — "
        "the reader is then told the building records nothing about the quantity it measures"
    )


@pytest.mark.parametrize(
    "question",
    [
        "How many floors are there?",
        "List the floors in the building",
        "what floors does this building have",
    ],
)
def test_a_genuine_floor_question_still_gets_the_floor_template(question):
    """The counterfactual. A fix that silenced the floor template entirely would trade one
    defect for another, which is how guards in this repo have failed before (lessons #135)."""
    out = _agent()._template_sparql(question, [], [], concept_class=None)
    assert _is_floor_listing(out), (
        f"{question!r} is a genuine floor-inventory question and must still be answered as one"
    )


def test_the_branch_consults_the_resolved_class_at_all():
    """Pins the MECHANISM, not the outcome: the floor branches must read `concept_class`.

    Without this, someone could satisfy the tests above by adding "sound level" and "voc level"
    to a stop-list and the next quantity would regress silently."""
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._template_sparql)
    assert "_is_quantity_question" in src, (
        "the floor branches no longer consult the resolved concept class; a word list is not a "
        "substitute, because HBCO exists precisely to resolve lay terms like 'noisy' and 'stuffy'"
    )
