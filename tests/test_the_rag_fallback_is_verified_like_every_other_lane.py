# -*- coding: utf-8 -*-
"""The semantic-RAG fallback gets a grounding record instead of crashing the verifier (BUG-643).

WHAT WENT WRONG
---------------
``SPARQLAgent.answer_semantically`` returns ``results`` as a LIST -- ``[{"answer": "..."}]``,
annotated in the source as "mock results for compatibility". Both of the verifier's SPARQL
readers dug ``result["results"]["results"]["bindings"]`` behind an ``isinstance`` guard on
the OUTER value only. The outer value IS a dict, so the guard passed; the second ``.get``
then ran against the list and raised ``AttributeError``.

That exception escaped ``VerifierAgent.verify()`` into a caller that logged it at DEBUG.
So the turn attached NO verification record, and ``publication_gate`` -- which fails open by
design -- reads a missing record as "the check did not run" and publishes.

The consequence is the precise inversion of what the gate is for: the lane whose output is
un-grounded LLM prose over retrieved text was the ONLY lane with no grounding check, on
every turn it fired, invisibly.

WHAT THESE TESTS PIN
--------------------
Four things, and the last two matter most:

1. the malformed shape no longer raises;
2. a RAG answer is recorded as ungrounded, because it genuinely has no bindings;
3. a REAL SPARQL result is still recognised -- the fix must not buy safety by making the
   verifier blind to everything (this project's expensive failure mode is a guard that
   takes something else with it, see test_a_failed_verification_withholds_the_claim.py);
4. the producer still emits the list shape. If someone "tidies" ``answer_semantically`` to
   return the protocol shape, the guard here stops being exercised by anything real and
   these tests would keep passing while testing nothing. Test 4 fails loudly instead.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents import verifier_agent as va  # noqa: E402
from orchestrator.services import publication_gate as pg  # noqa: E402
from shared.models import ConversationState, Message  # noqa: E402

# The exact shape orchestrator/agents/sparql_agent.py::answer_semantically returns.
RAG_RESULT = {
    "success": True,
    "query": "SEMANTIC_RAG_NO_SPARQL",
    "results": [{"answer": "The building appears to have around 40 rooms on floor 3."}],
    "formatted_response": "The building appears to have around 40 rooms on floor 3.",
    "standardized": [],
    "context": "…retrieved ontology text…",
    "analytics_required": False,
    "llm_reasoning": "Semantic RAG fallback used",
    "method": "semantic_rag",
}

# The SPARQL protocol shape, as GraphDB actually returns it.
REAL_RESULT = {
    "success": True,
    "results": {
        "results": {
            "bindings": [
                {
                    "sensor": {"value": "http://example.org/S1"},
                    "uuid": {"value": "abc-123"},
                }
            ]
        }
    },
}


def _state(intent: str, sparql_result) -> ConversationState:
    s = ConversationState(
        conversation_id="c1",
        user_id="u",
        user_message="how many rooms are on floor 3?",
        building_id="bldgX",
        current_intent=intent,
        messages=[Message(role="user", content="how many rooms are on floor 3?")],
    )
    s.intermediate_results["sparql_result"] = sparql_result
    return s


# ── 1. it no longer raises ───────────────────────────────────────────────────


def test_the_rag_shape_does_not_raise_in_the_binding_readers():
    """Both readers, not just the one. _extract_sensor_ids crashed FIRST."""
    assert va._extract_sensor_ids(RAG_RESULT) == []
    assert va._sparql_returned_data(RAG_RESULT) is False


@pytest.mark.parametrize(
    "shape",
    [
        {"results": []},
        {"results": "a string"},
        {"results": None},
        {"results": {"results": []}},
        {"results": {"results": {"bindings": "not a list"}}},
        {"results": {"results": {}}},
        {},
        None,
        [],
        "not a dict at all",
    ],
)
def test_no_malformed_lane_result_can_raise(shape):
    assert va._bindings(shape) == []
    assert va._extract_sensor_ids(shape) == []


def test_verify_attaches_a_record_for_a_rag_answer_rather_than_raising():
    state = asyncio.run(va.VerifierAgent().verify(_state("analytics", RAG_RESULT)))
    record = state.intermediate_results.get("verification")
    assert isinstance(record, dict) and record, "a missing record is what the gate publishes"


# ── 2. a RAG answer is recorded as ungrounded, because it is ─────────────────


def test_a_rag_answer_is_not_called_grounded():
    state = asyncio.run(va.VerifierAgent().verify(_state("analytics", RAG_RESULT)))
    record = state.intermediate_results["verification"]
    assert record["grounded"] is False
    assert record["source"] == "none"


def test_the_gate_now_withholds_a_figure_that_came_only_from_rag_prose():
    """The consequence the crash was suppressing, end to end."""
    state = asyncio.run(va.VerifierAgent().verify(_state("analytics", RAG_RESULT)))
    claim = "Floor 3 averaged 812.4 ppm of CO2 yesterday."
    d = pg.evaluate(
        intent="analytics",
        final_response=claim,
        verification=state.intermediate_results["verification"],
    )
    assert not d.publish
    assert "812.4" not in d.text


# ── 3. the fix must not blind the verifier to real data ──────────────────────


def test_a_real_sparql_result_is_still_recognised():
    assert va._sparql_returned_data(REAL_RESULT) is True
    assert va._extract_sensor_ids(REAL_RESULT) == ["http://example.org/S1", "abc-123"]


def test_a_real_sparql_result_is_still_called_grounded():
    state = asyncio.run(va.VerifierAgent().verify(_state("metadata", REAL_RESULT)))
    record = state.intermediate_results["verification"]
    assert record["grounded"] is True
    assert record["source"] == "sparql"


def test_an_empty_but_well_formed_sparql_result_is_ungrounded_not_crashed():
    empty = {"success": True, "results": {"results": {"bindings": []}}}
    assert va._sparql_returned_data(empty) is False


def test_an_unsuccessful_lane_result_is_ungrounded():
    assert va._sparql_returned_data({"success": False, "results": REAL_RESULT["results"]}) is False


# ── 4. the producer still emits the shape this guard exists for ──────────────


def test_answer_semantically_still_returns_results_as_a_list():
    """If this fails, the guard above is no longer exercised by anything real.

    Either the producer was changed to the protocol shape -- in which case say so and
    delete the guard deliberately -- or the compatibility comment moved. Do not just
    update this assertion; the whole point is that the two files disagreed silently.
    """
    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent.answer_semantically)
    assert '"results": [{"answer"' in src, (
        "answer_semantically no longer returns a list for `results`; "
        "re-check whether verifier_agent._bindings still guards a real shape"
    )
