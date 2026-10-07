# -*- coding: utf-8 -*-
"""BUG-1450: "When was room 2.01 last comfortable?" was live-routing to `readiness_check`,

which answers from the AV register (projector/display/microphone status) -- wrong for a
question about comfort HISTORY. Diagnosis found no deterministic rule matches the AV register
for this shape (neither `record_registry` term scoring nor any `_READINESS_RE` branch), so the
classifier itself picks `readiness_check` on a broad reading of its own description.

This adds one parse-stage rule, directly after `readiness_check` in the module, that stands
down ONLY a `readiness_check` result for the comfort-history shape and routes it to a new
deterministic, honest-decline lane (`comfort_history`) -- no lane in this codebase keeps a
register of WHEN a space was last compliant, so nothing invents a past timestamp.

What these tests pin:

* the rule fires on "when was X last comfortable" / "how long ago did X last meet comfort
  standards" shapes, ONLY when the incoming intent is `readiness_check`;
* it does NOT fire on a genuine readiness-check question, even one that happens to use the
  word "comfortable" alongside a readiness occasion;
* it does NOT fire on a CURRENT-state comfort question ("is it comfortable in here?") --
  that shape has its own home (Intent_Comfort -> analytics/sensor_data) and is untouched;
* it takes ONLY from `readiness_check`, so a comfort-history question the classifier filed
  under any other intent keeps its own route;
* the node's own decline names the room when the question named one, and never claims a
  past timestamp.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
BANK = REPO / "docs" / "smart_building_questions.csv"


def _ctx(query: str, intent: str = "readiness_check") -> rc._Ctx:
    return rc._Ctx(query=query, ql=query.lower(), normalized={"intent": intent}, sr=None)


def _fires(query: str, intent: str = "readiness_check") -> bool:
    return rc._r_comfort_history_not_readiness(_ctx(query, intent)) == "comfort_history"


# ── the routing rule ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "When was room 2.01 last comfortable?",
        "When was Room 3.04 last comfortable?",
        "How long ago did room 2.01 last meet comfort standards?",
        "When did the office last comply with comfort standards?",
        "What was the last time this room was comfortable?",
        "When was Lab 1.12 last comfortable?",
    ],
)
def test_the_rule_fires_on_the_comfort_history_shape(query):
    assert _fires(query), query


@pytest.mark.parametrize(
    "query",
    [
        # Genuine readiness checks -- must keep their own lane, not be stolen.
        "Is room 1.06 ready for my class?",
        "Give me a readiness check for the seminar room before my session.",
        "What should I know before teaching in 3.13?",
        "Is the lecture theatre set up?",
        # A CURRENT-state comfort question -- not history-shaped (no when/last-time marker).
        "Is it comfortable in room 2.01 right now?",
        "Is room 2.01 comfortable?",
        # No comfort vocabulary at all.
        "When was the lift last serviced?",
    ],
)
def test_the_rule_does_not_fire_on_other_shapes(query):
    assert not _fires(query), query


def test_the_rule_takes_only_from_readiness_check():
    """A comfort-history question the classifier filed elsewhere keeps its own route."""
    query = "When was room 2.01 last comfortable?"
    for other_intent in ("sensor_data", "analytics", "capability", "metadata", "general", None):
        assert not _fires(query, intent=other_intent), other_intent


def test_the_rule_guards_against_a_genuine_readiness_match_too():
    """Defensive: even if a question matched BOTH patterns, readiness wins (_READINESS_RE
    checked first, per the rule's own docstring)."""
    # A constructed phrasing that deliberately matches both _READINESS_RE (a readiness
    # occasion) and the comfort-history vocabulary -- the readiness guard must win.
    query = "Is the room comfortable and ready for my class?"
    assert rc._READINESS_RE.search(query), "fixture no longer matches _READINESS_RE"
    assert not _fires(query), query


def test_rule_is_registered_once_directly_after_readiness_check():
    names = [r.name for r in rc.PARSE_STAGE_RULES]
    assert names.index("comfort_history_not_readiness") == names.index("readiness_check") + 1


# ── blast radius over the full stakeholder-question bank ───────────────────────────


def _bank_questions():
    with BANK.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [row["Question"] for row in reader if row.get("Question")]


def test_blast_radius_is_small_and_only_on_comfort_wording():
    """The matcher must only ever match a row containing comfort vocabulary -- it cannot
    move a question that says nothing about comfort."""
    questions = _bank_questions()
    assert len(questions) > 4000, "the bank fixture did not load as expected"
    moved = [q for q in questions if rc._COMFORT_HISTORY_RE.search(q)]
    for q in moved:
        assert re.search(r"comfort", q, re.IGNORECASE), q
    # Reported, not asserted to an exact figure (the bank is append-only and may grow) --
    # pinned to an upper bound so a vocabulary-widening regression is caught.
    assert len(moved) < 20, f"unexpectedly wide match: {len(moved)} rows -- {moved[:10]}"


# ── the node's own decline ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_node_declines_honestly_and_names_the_room():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator
    from shared.models import ConversationState, Message

    question = "When was room 2.01 last comfortable?"
    state = ConversationState(
        conversation_id="t-1449",
        user_id="u",
        user_message=question,
        current_intent="comfort_history",
        messages=[Message(role="user", content=question)],
    )
    state.intermediate_results["entities"] = ["2.01"]
    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    state = await orch._comfort_history_node(state)
    result = state.intermediate_results["comfort_history_result"]
    assert result["success"] is True
    text = result["formatted_response"]
    assert "2.01" in text
    # No past timestamp is invented.
    assert not re.search(r"\b\d{1,2}:\d{2}(:\d{2})?\b", text)
    assert "don't have a record" in text or "do not have a record" in text
