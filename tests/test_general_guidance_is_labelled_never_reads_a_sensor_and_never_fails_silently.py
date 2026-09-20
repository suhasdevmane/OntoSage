# -*- coding: utf-8 -*-
"""Owner policy 2026-09-19: building knowledge that needs no building data is answered as GENERAL
GUIDANCE, labelled as not from this building's records.

The routing contract sends the question here; `general_guidance.general_guidance(question, persona)`
(another agent's module) writes the answer. What this module's node promises, and these tests pin:

* the answer always carries the label -- a writer that forgets it cannot ship an unlabelled textbook;
* a writer that is missing, raises or returns nothing costs the turn nothing: the reader gets an
  honest sentence, not a blank and not a guess;
* the lane cannot reach the sensor fetch, so "that question reaches N sensors" is unreachable.

The wiring tests pin the two places a hook could silently go missing: the pre-classification
short-circuits in the dialogue agent (which skip the routing contract entirely) and the workflow's
node methods.
"""

import inspect

import pytest

from orchestrator.services import guidance_node as gn

pytestmark = pytest.mark.unit


class _Msg:
    def __init__(self, content):
        self.content = content


class _State:
    def __init__(self, question, persona="facility_manager"):
        self.messages = [_Msg(question)]
        self.persona = persona
        self.intermediate_results = {}
        self.current_intent = ""


async def test_the_writers_text_is_labelled_and_written_to_the_response_slot():
    seen = {}

    def writer(question, persona):
        seen["args"] = (question, persona)
        return "A delta-T is the temperature difference across a heat exchanger."

    state = await gn.general_guidance_node(_State("What does a delta-T mean?"), guidance_fn=writer)
    text = state.intermediate_results["dialogue_response"]
    assert text.startswith("General guidance (not from this building's records):")
    assert "temperature difference" in text
    assert seen["args"] == ("What does a delta-T mean?", "facility_manager")
    assert state.current_intent == "general_guidance"
    assert state.intermediate_results["general_guidance"] == {"written": True}


async def test_an_async_writer_is_awaited():
    async def writer(question, persona):
        return "Humidity can shift an NDIR sensor's reading slightly."

    state = await gn.general_guidance_node(_State("Does humidity affect CO2 accuracy?"), guidance_fn=writer)
    assert state.intermediate_results["dialogue_response"].startswith("General guidance")


async def test_a_writer_that_already_labels_its_text_is_not_labelled_twice():
    def writer(question, persona):
        return "General guidance (not from this building's records): ventilate more."

    state = await gn.general_guidance_node(_State("How do I control CO2?"), guidance_fn=writer)
    assert state.intermediate_results["dialogue_response"].count("General guidance") == 1


@pytest.mark.parametrize("failure", ["raises", "empty", "none"])
async def test_a_writer_that_fails_gives_an_honest_sentence_never_a_blank(failure):
    def writer(question, persona):
        if failure == "raises":
            raise RuntimeError("model unavailable")
        return "" if failure == "empty" else None

    state = await gn.general_guidance_node(_State("How do I control CO2?"), guidance_fn=writer)
    text = state.intermediate_results["dialogue_response"]
    assert text == gn.unavailable_text()
    assert "couldn't write general guidance" in text
    assert state.intermediate_results["general_guidance"] == {"written": False}


async def test_a_missing_writer_module_is_the_same_honest_sentence(monkeypatch):
    # `general_guidance.py` may not exist yet: importing it must not crash the turn. A None entry in
    # sys.modules makes the import raise ImportError whether or not the file is there, so this
    # never reaches the real writer (and its model call) in a unit test.
    import sys

    monkeypatch.setitem(sys.modules, "orchestrator.services.general_guidance", None)
    state = await gn.general_guidance_node(_State("How do I control CO2?"))
    assert state.intermediate_results["dialogue_response"] == gn.unavailable_text()
    assert state.current_intent == "general_guidance"


def test_the_node_module_cannot_reach_a_sensor_or_the_data_pipeline():
    src = inspect.getsource(gn)
    for forbidden in ("sql_agent", "sparql_agent", "adapter_registry", "execute_query", "fetch("):
        assert forbidden not in src, forbidden


# ── the wiring that could silently go missing ────────────────────────────────


def test_the_dialogue_agents_short_circuits_yield_to_the_contract_for_these_shapes():
    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent.detect_intent)
    held = src.split("_held_record\n            and not _SR.is_report_intake_query")[1].split(
        "metadata via held record class"
    )[0]
    # the held-record return skips the contract, so the booking/report shape must veto it (BUG-828)
    assert "_events_question(user_query)" in held
    probe = src.split("capability via ontology triples")[0]
    # so does the capability probe, for scope and guidance shapes (BUG-812, owner policy)
    assert "_out_of_scope_kind(user_query)" in probe
    assert "_is_general_guidance(user_query)" in probe


def test_the_workflow_has_a_node_method_for_each_new_intent():
    from orchestrator.intents import get_intent_registry
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    registry = get_intent_registry(None)
    for name in ("scope_boundary", "general_guidance"):
        definition = registry.get(name)
        assert definition is not None, name
        assert definition.pipeline_group == "standalone"
        assert hasattr(WorkflowOrchestrator, definition.node_method), definition.node_method


def test_neither_new_intent_can_be_chosen_by_the_classifier_alone():
    from orchestrator.intents import get_intent_registry

    registry = get_intent_registry(None)
    for name in ("scope_boundary", "general_guidance"):
        assert "deterministic rule only" in registry.get(name).description
