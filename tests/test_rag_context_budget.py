# -*- coding: utf-8 -*-
"""BUG-170: the retriever's entity budget is not the prompt's context budget.

``/graphdb/retrieve``'s ``top_k`` bounds how many ENTITIES it finds; it then
returns every triple around them (~1000 for 5 entities at 1 hop). The dialogue
agent reused that same number to truncate the RESULT, so it kept the summary plus
four triples and discarded the rest of what it had just fetched — and rendered the
survivors as Python dict reprs. These tests pin the two budgets apart.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from orchestrator.agents.dialogue_agent import DialogueAgent, _format_triple

pytestmark = pytest.mark.unit


# ── triple formatting ────────────────────────────────────────────────────────


def test_a_triple_dict_becomes_a_readable_line():
    line = _format_triple(
        {"subject": "bldg:RM101", "predicate": "brick:hasPoint", "object": "bldg:T1"}
    )
    assert line == "bldg:RM101 brick:hasPoint bldg:T1"
    assert "{" not in line and "'" not in line


def test_a_string_triple_passes_through():
    assert _format_triple("already a line") == "already a line"


def test_a_partial_triple_does_not_raise():
    assert _format_triple({"subject": "bldg:RM101"}) == "bldg:RM101"


# ── the two budgets ──────────────────────────────────────────────────────────


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class _FakeClient:
    """Captures the request body so the entity budget can be asserted."""

    sent: List[Dict[str, Any]] = []

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, **kw):
        _FakeClient.sent.append(json or {})
        return _FakeResponse(self._payload)


def _run(monkeypatch, *, n_triples: int, summary: str = "5 entities matched", **kwargs):
    payload = {
        "summary": summary,
        "triples": [
            {"subject": f"bldg:S{i}", "predicate": "brick:hasPoint", "object": f"bldg:P{i}"}
            for i in range(n_triples)
        ],
        "metadata": {"entity_count": 5, "triple_count": n_triples},
    }
    _FakeClient.sent = []
    monkeypatch.setattr(
        "orchestrator.agents.dialogue_agent.httpx.AsyncClient",
        lambda *a, **k: _FakeClient(payload),
    )
    agent = DialogueAgent.__new__(DialogueAgent)  # no __init__: no LLM needed
    return asyncio.run(agent._retrieve_ontology_context("where is it quiet?", **kwargs))


def test_the_entity_budget_still_goes_to_the_retriever(monkeypatch):
    _run(monkeypatch, n_triples=50, top_k=5)
    assert _FakeClient.sent[0]["top_k"] == 5, "the retriever's entity budget must be unchanged"


def test_context_is_no_longer_truncated_to_the_entity_budget(monkeypatch):
    out = _run(monkeypatch, n_triples=1078, top_k=5)
    assert len(out) == 30, "5 entities must not mean 5 context lines"


def test_the_summary_is_kept_first(monkeypatch):
    out = _run(monkeypatch, n_triples=1078, top_k=5)
    assert out[0] == "5 entities matched"


def test_the_context_budget_is_honoured(monkeypatch):
    out = _run(monkeypatch, n_triples=1078, top_k=5, max_context_items=10)
    assert len(out) == 10


def test_a_small_result_is_returned_whole(monkeypatch):
    out = _run(monkeypatch, n_triples=3, top_k=5)
    assert len(out) == 4  # summary + 3 triples


def test_no_dict_reprs_reach_the_prompt(monkeypatch):
    out = _run(monkeypatch, n_triples=40, top_k=5)
    assert all(isinstance(c, str) for c in out)
    assert not any(c.startswith("{") for c in out)


def test_a_missing_summary_does_not_leave_an_empty_line(monkeypatch):
    out = _run(monkeypatch, n_triples=5, top_k=5, summary="")
    assert "" not in out and len(out) == 5
