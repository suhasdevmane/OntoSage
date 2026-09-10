# -*- coding: utf-8 -*-
"""Prose answered a structural question before anything classified it (BUG-440, W0-2).

MEASURED, live:

    Q: "Which rooms are on floor 2?"
    log: [ttl-route] capability via document KB (3 chunk(s)) — skipping LLM intent call
    A: Room 2.01, 2.03, 2.05, 2.15, 2.17, 2.20
       *From Abacws Building's documents: Cleaning Task Register, Public Event Register,
        Timetabled Sessions.*

GraphDB holds FORTY-EIGHT rooms on Floor2. Six were returned, sourced from three
registers that each happen to mention some rooms, and nothing marked the answer partial —
it read as the floor's room list.

WHY THE GUARD COULD NOT BE FINISHED
-----------------------------------
The pre-classification probe was wrapped in nineteen `and not` clauses:

    and not _SR.is_data_query(...)          and not _SR.is_floor_plan_query(...)
    and not _SR.is_control_command(...)     and not _WAYFIND_RE.search(...)
    and not _plant_point_question(...)      and not _consumption_question(...)
    ... and thirteen more

Every one was added AFTER a live wrong answer of exactly this shape. That is the tell. A
veto that runs before classification and needs an exception per lane cannot be completed,
because it discovers each newly shadowed lane only by answering a question wrongly first
— and each clause is a regex reconstructing, badly, a judgement the classifier was about
to make correctly.

THE INVERSION
-------------
Documents are consulted AFTER the classifier and the routing contract, and only where
they left the intent weak. The nineteen clauses become UNNECESSARY rather than merely
deleted: a question the LLM calls `spatial_query` no longer needs a regex to defend it
from a register.

Live after the change, the same question routes to `floor_plan` and lists the floor's
spaces with "+30 more" — consistent with the 48 in the graph.

WHAT DID NOT CHANGE
-------------------
The score floor (0.50) and the TTL-triples probe. The triples match curated
`ontosage:layTerms` exactly, so they are precise in the way prose is not, and no incident
has ever implicated them. Keeping the threshold fixed means a regression here can only be
about SEQUENCING — the two cannot be confused for one another.
"""

from __future__ import annotations

import ast
import asyncio
import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.dialogue_agent import DialogueAgent  # noqa: E402


def _code(fn) -> str:
    """Source with docstrings stripped — the comments quote the old behaviour verbatim."""
    tree = ast.parse(inspect.getsource(fn).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


class _Docs:
    """Stand-in for the document KB, returning a fixed best score."""

    def __init__(self, score):
        self.score = score
        self.calls = 0

    async def __call__(self, query, bldg):
        self.calls += 1
        return [] if self.score is None else [{"score": self.score, "text": "prose"}]


def _promote(monkeypatch, intent, score):
    """Run the post-classification promotion over a classified result."""
    import orchestrator.agents.capability_agent as cap_mod

    docs = _Docs(score)
    monkeypatch.setattr(cap_mod, "_search_documents", docs)
    result = {"intent": intent, "general": intent == "general", "analytics": False}
    asyncio.run(DialogueAgent()._promote_to_capability_from_documents("a question", result, None))
    return result, docs


# ── the lanes the nineteen clauses were defending ───────────────────────────


@pytest.mark.parametrize(
    "intent",
    [
        # One per incident the escape clauses descend from.
        "sensor_data",
        "spatial_query",
        "floor_plan",
        "control",
        "events",
        "deliberate",
        "observability",
        "diagnosis",
        "asset_state",
        "report",
        "privacy_refusal",
        "maintenance",
        "analytics",
        "compliance",
        "trend",
        "anomaly",
        # Structural lanes the contract calls weak. A structural answer computed from the
        # graph still beats prose — BUG-440 was exactly a structural question losing to a
        # register.
        "metadata",
        "discovery",
    ],
)
def test_a_classified_lane_is_never_overridden_by_a_document(monkeypatch, intent):
    """Even a perfect document score must not take a turn a lane has claimed."""
    result, docs = _promote(monkeypatch, intent, score=0.99)
    assert result["intent"] == intent, (
        f"a document overrode {intent!r}; this is the BUG-440 shape and the reason the "
        f"old guard needed a clause per lane"
    )
    assert docs.calls == 0, "the document KB was searched for a turn it cannot claim"


# ── what documents are still for ────────────────────────────────────────────


@pytest.mark.parametrize("intent", ["general", "general_knowledge", "clarification", None])
def test_a_strong_document_still_answers_a_question_no_lane_wanted(monkeypatch, intent):
    result, _ = _promote(monkeypatch, intent, score=0.67)
    assert result["intent"] == "capability"
    assert result["general"] is False


def test_a_weak_document_leaves_the_classification_alone(monkeypatch):
    """0.43 is where "what is the capital of France" landed — prose must not claim it."""
    result, _ = _promote(monkeypatch, "general", score=0.43)
    assert result["intent"] == "general"


def test_the_floor_is_the_same_number_as_before_the_inversion():
    """A sequencing change and a threshold change must not be confusable."""
    assert DialogueAgent.CAPABILITY_DOC_FLOOR == 0.50


def test_no_documents_at_all_is_not_a_promotion(monkeypatch):
    result, _ = _promote(monkeypatch, "general", score=None)
    assert result["intent"] == "general"


def test_an_empty_question_searches_nothing(monkeypatch):
    import orchestrator.agents.capability_agent as cap_mod

    docs = _Docs(0.99)
    monkeypatch.setattr(cap_mod, "_search_documents", docs)
    result = {"intent": "general"}
    asyncio.run(DialogueAgent()._promote_to_capability_from_documents("   ", result, None))
    assert result["intent"] == "general" and docs.calls == 0


def test_a_failing_document_search_costs_the_prose_not_the_answer(monkeypatch):
    """The turn must survive a Qdrant outage with its classification intact."""
    import orchestrator.agents.capability_agent as cap_mod

    async def _boom(query, bldg):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(cap_mod, "_search_documents", _boom)
    result = {"intent": "general"}
    asyncio.run(DialogueAgent()._promote_to_capability_from_documents("q", result, None))
    assert result["intent"] == "general"


# ── the sequencing itself ───────────────────────────────────────────────────


def test_the_probe_runs_after_the_routing_contract():
    """Before the contract, this would be the old bug with extra steps."""
    # `ast.unparse` normalises string quotes, so match on the argument value alone.
    src = _code(DialogueAgent.detect_intent)
    assert "_promote_to_capability_from_documents" in src
    promote = src.index("_promote_to_capability_from_documents")
    post = src.index("stage='post'")
    assert post < promote, "documents are consulted before the routing contract has run"


def test_the_llm_outage_fallback_still_consults_documents():
    """The old probe ran BEFORE the LLM, so an outage cost it nothing.

    Moving it after classification would quietly remove that on exactly the path built
    for an outage (BUG-167) — trading a fixed sequencing bug for a new availability one.
    """
    src = _code(DialogueAgent.detect_intent)
    tail = src[src.rindex("classification_failed") :]
    assert "_promote_to_capability_from_documents" in tail, (
        "the LLM-outage fallback no longer consults documents, so a capability question "
        "goes unanswered whenever the classifier is unavailable"
    )


def test_the_pre_llm_document_branch_is_gone():
    """The whole point: no document may return an intent before classification."""
    src = _code(DialogueAgent.detect_intent)
    head = src[: src.index("_promote_to_capability_from_documents")]
    assert "_search_documents" not in head, (
        "the document KB is still searched before classification, so prose can still "
        "claim a turn no lane has been asked about"
    )


def test_the_triples_probe_is_untouched():
    """Exact lay-term matching is precise where prose is not; nothing implicates it."""
    assert "get_capability_graph_resolver" in _code(DialogueAgent.detect_intent)


def test_the_promotion_says_what_it_did():
    """A silent override is exactly as hard to audit as the one this replaces."""
    src = _code(DialogueAgent._promote_to_capability_from_documents)
    assert "doc-route" in src
    assert "routing to capability" in src


def test_the_overridable_set_excludes_structural_intents():
    assert "metadata" not in DialogueAgent._DOC_OVERRIDABLE
    assert "discovery" not in DialogueAgent._DOC_OVERRIDABLE
    assert "capability" not in DialogueAgent._DOC_OVERRIDABLE


def test_nothing_here_names_a_building():
    body = _code(DialogueAgent._promote_to_capability_from_documents).lower()
    for literal in ("bldg1", "bldg2", "abacws", "floor 2"):
        assert literal not in body
