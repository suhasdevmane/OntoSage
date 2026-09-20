# -*- coding: utf-8 -*-
"""2D-06: the register lane, run whole, answers a lookup from the rows without asking the model.

The other tests in this family check the projection on rows. This one runs
``SPARQLAgent._whole_register`` itself — the lane that fetches a register, pivots it, counts it and
narrates it — with the graph replaced by the building's own register document (lifted into the
triples GraphDB would return) and the language model replaced by a function that fails the test if
it is called. What it pins:

* the scripted demo question comes back with the owner in it, and the model is never asked;
* a question the rows cannot settle still reaches the model, with the locked facts in its prompt;
* a model that DENIES the owner has the denial replaced;
* a register that was only partly fetched is never counted as the whole register.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent
from orchestrator.services import record_documents, record_registry
from tests.register_fixture_rows import DOCUMENTS, MAPPINGS, NAMESPACE

pytestmark = pytest.mark.unit

LAY_TERMS = {
    "EvacuationProvision": "refuge point|refuge points|evacuation chair",
    "FireSafetyAsset": "fire safety asset|fire safety assets|fire alarm|fire door",
}
DEMO_QUESTION = "Which refuge points are defective, and who owns them?"


def _triple_bindings(document: str) -> List[Dict[str, Any]]:
    """The ?record ?p ?v bindings the lane's register query returns for one document."""
    result = record_documents.lift_document(DOCUMENTS / document, NAMESPACE, MAPPINGS)
    assert result.ok, result.errors
    seen = set()
    out = []
    for subject, predicate, value in result.triples:
        text = "true" if value is True else "false" if value is False else str(value)
        if predicate == record_documents.RDF_TYPE or (subject, predicate, text) in seen:
            continue
        seen.add((subject, predicate, text))
        out.append(
            {
                "record": {"type": "uri", "value": subject},
                "p": {"type": "uri", "value": predicate},
                "v": {"type": "literal", "value": text},
            }
        )
    return out


def _lane(
    document: str, local_name: str, label: str, monkeypatch, *, instances=None, llm=None, lay=""
):
    bindings = _triple_bindings(document)
    subjects = {b["record"]["value"] for b in bindings}
    calls: Dict[str, List[Any]] = {"llm": []}

    agent = SPARQLAgent.__new__(SPARQLAgent)

    async def _execute(query: str, *a, **k):
        return {"head": {"vars": ["record", "p", "v"]}, "results": {"bindings": bindings}}

    async def _format(results, guidance, *a, **k):
        calls["llm"].append(guidance)
        if llm is None:
            raise AssertionError("the model was asked, and this lookup is settled by the rows")
        return llm

    agent._execute_query = _execute
    agent._format_results = _format

    lay = lay or LAY_TERMS.get(local_name, "")
    cls = record_registry.RecordClass(
        local_name,
        label,
        len(subjects) if instances is None else instances,
        record_registry._terms_for(local_name, label, lay),
    )

    async def _classes(namespace: str = ""):
        return [cls]

    monkeypatch.setattr(record_registry, "record_classes", _classes)
    return agent, calls


def _ask(agent: SPARQLAgent, question: str) -> Dict[str, Any]:
    state = SimpleNamespace(building_id=None, intermediate_results={})
    return asyncio.run(agent._whole_register(state, question))


def test_the_scripted_demo_question_is_answered_from_the_rows_and_the_model_is_not_asked(
    monkeypatch,
):
    agent, calls = _lane(
        "evacuation_and_peeps.md", "EvacuationProvision", "Evacuation provision", monkeypatch
    )
    result = _ask(agent, DEMO_QUESTION)
    text = result["formatted_response"]
    assert result["method"] == "whole_register" and result["success"] is True
    assert "EV-003" in text and "Building Fire Warden Coordinator" in text
    assert "EV-007" not in text and "does not contain" not in text
    assert calls["llm"] == []
    # the rows themselves still travel with the result, for the evidence record
    assert len(result["results"]["results"]["bindings"]) == 12


def test_a_question_the_rows_cannot_settle_reaches_the_model_with_the_locked_facts(monkeypatch):
    agent, calls = _lane(
        "evacuation_and_peeps.md",
        "EvacuationProvision",
        "Evacuation provision",
        monkeypatch,
        llm="EV-003 is the only defective refuge point.",
    )
    result = _ask(agent, "Why are the refuge points defective, and who owns them?")
    assert len(calls["llm"]) == 1
    prompt = calls["llm"][0]
    assert "RECORDED FACTS" in prompt
    assert "THE ANSWER TO THIS QUESTION, WORKED OUT BY THE SYSTEM" in prompt
    assert "Building Fire Warden Coordinator" in prompt
    assert result["formatted_response"].startswith("EV-003 is the only defective refuge point.")


def test_a_model_that_denies_the_owner_has_the_denial_replaced(monkeypatch):
    agent, calls = _lane(
        "evacuation_and_peeps.md",
        "EvacuationProvision",
        "Evacuation provision",
        monkeypatch,
        llm=(
            "EV-003 is a defective refuge point.\n\n"
            "**Ownership**\n\n"
            "The register does not contain an ownership field, so the owner is not recorded."
        ),
    )
    # a shape the projection declines to compose, so the narration is what is checked
    result = _ask(agent, "Why is the refuge point defective, and who owns it?")
    text = result["formatted_response"]
    assert len(calls["llm"]) == 1
    assert "does not contain an ownership field" not in text
    assert "Building Fire Warden Coordinator" in text


def test_a_register_fetched_only_in_part_is_never_counted_as_the_whole(monkeypatch):
    agent, calls = _lane(
        "evacuation_and_peeps.md",
        "EvacuationProvision",
        "Evacuation provision",
        monkeypatch,
        instances=40,  # the graph says 40 records; the lane holds 12 (a scoped fetch)
        llm="narrated",
    )
    result = _ask(agent, DEMO_QUESTION)
    assert len(calls["llm"]) == 1 and result["formatted_response"].startswith("narrated")


def test_the_switch_returns_the_lane_to_the_narration(monkeypatch):
    monkeypatch.setenv("REGISTER_PROJECTION_ANSWER", "false")
    agent, calls = _lane(
        "evacuation_and_peeps.md",
        "EvacuationProvision",
        "Evacuation provision",
        monkeypatch,
        llm="narrated",
    )
    result = _ask(agent, DEMO_QUESTION)
    assert len(calls["llm"]) == 1 and result["formatted_response"].startswith("narrated")


def test_the_overdue_question_is_answered_with_no_completeness_line_appended(monkeypatch):
    """A composed overdue answer already names the past-due records; appending the narration's
    completeness note would state them twice."""
    agent, calls = _lane("fire_safety.md", "FireSafetyAsset", "Fire safety asset", monkeypatch)
    result = _ask(agent, "Which fire safety assets are overdue?")
    text = result["formatted_response"]
    assert "FSA-027" in text and "FSA-001" in text
    assert "Also past their due date" not in text
    assert calls["llm"] == []
