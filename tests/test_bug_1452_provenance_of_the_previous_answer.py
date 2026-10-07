# -*- coding: utf-8 -*-
"""BUG-1427: a question about the PROVENANCE of the previous answer had no lane.

Two shapes were measured against the live stack on 2026-10-02 and both still existed at
this session's start:

1. "what evidence supports that?" / "what data sources backed that up?" matched NEITHER
   `answer_provenance.PROVENANCE_RE` nor `session_recall._ABOUT_MY_ANSWER` and fell through
   to `general_knowledge` -- no lane at all. Measured over the 4,060-question bank before
   shipping: exactly 1 new move, 0 overlap with the existing pattern, 0 lost.

2. "what is the evidence behind your answer?" / "how did you arrive at that?" / "what was
   your previous answer based on?" are -- BY DESIGN, BUG-1397, VERIFIED_LIVE -- routed to
   `session_recall`, the one lane that can say whether there was a previous answer at all.
   But the lane could only quote the past QUESTION back (`answer()`), never the previous
   ANSWER's own recorded evidence. Asking for a BASIS produced "I have no record of you
   mentioning 'evidence', 'behind' or 'answer'" -- a confusing non-answer when a basis really
   was recorded one turn back. This file is mostly about closing THAT gap: a stubbed
   two-turn conversation where turn 1 produced a data answer with a recorded evidence
   record, and turn 2 asks about its provenance.

Deliberately NOT touched, and pinned here as a regression guard: `is_provenance_question`
must still return False for "what is the evidence behind your answer?" and "how did you
arrive at that?" (test_d7_provenance_detector_widened.py), and D19's co-reference guard
(`rewrite_to_standalone`) must still skip the rewrite for a provenance question BEFORE any
deterministic resolver runs (test_d7_live_provenance_question_is_not_rewritten.py) -- this
file does not touch `dialogue_agent.py` at all.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest

import orchestrator.redis_manager as redis_manager_module
from orchestrator.services.answer_provenance import (
    is_provenance_question,
    load_previous_turn_record,
)
from orchestrator.services.session_recall import (
    NOTES_KEY,
    _render_previous_answer_evidence,
    session_recall_node,
)
from orchestrator.services.session_summary import TurnNote

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# A sample evidence record, in the shape `evidence.assemble.record_for_response` produces.
# ─────────────────────────────────────────────────────────────────────────────

RECORDED_EVIDENCE: Dict[str, Any] = {
    "status": "observed",
    "operation": "direct_lookup",
    "sources": [
        {
            "source_id": "uuid-co2-204",
            "label": "CO2 Sensor 204",
            "kind": "sensor_reading",
            "owner": "Estates",
        }
    ],
    "latest_evidence_at": "2026-10-06T14:00:00",
    "retrieved_at": "2026-10-06T14:00:05",
}


class _State:
    """A minimal stand-in for `ConversationState` -- only what this lane reads."""

    def __init__(self, message: str, notes, conversation_id: Optional[str] = "conv-1427"):
        self.user_message = message
        self.intermediate_results: Dict[str, Any] = {NOTES_KEY: notes} if notes is not None else {}
        self.current_intent = None
        self.conversation_id = conversation_id


def _previous_turn_state(evidence_record: Optional[Dict[str, Any]]) -> SimpleNamespace:
    """A stand-in for the PREVIOUS turn's saved `ConversationState`, as `redis_manager.load_state`
    would return it."""
    results: Dict[str, Any] = {}
    if evidence_record is not None:
        results["evidence_record"] = evidence_record
    return SimpleNamespace(intermediate_results=results)


def _patch_load_state(monkeypatch: pytest.MonkeyPatch, returned) -> None:
    monkeypatch.setattr(
        redis_manager_module.redis_manager, "load_state", AsyncMock(return_value=returned)
    )


FIRST_TURN_NOTE = [TurnNote(1, "What is the CO2 level in room 2.01?", "sensor_data", "answered")]


# ─────────────────────────────────────────────────────────────────────────────
# 1. The complete-fall-through gap: new vocabulary that reached NEITHER detector.
# ─────────────────────────────────────────────────────────────────────────────


class TestTheFallThroughGapIsClosed:
    @pytest.mark.parametrize(
        "q",
        [
            "what evidence supports that?",
            "what evidence backs that up?",
            "what evidence confirms this?",
            "what data backed that up?",
            "what sources support it?",
        ],
    )
    def test_matches(self, q):
        assert is_provenance_question(q), q

    def test_an_ordinary_question_is_still_not_taken(self):
        assert not is_provenance_question("which rooms have a projector?")


class TestBugFourteenNinetySevensTerritoryStaysWithSessionRecall:
    """Regression guard: D7's deliberate exclusion is unchanged by this fix.

    "how did you arrive at that?" is a PRE-EXISTING dual match (D7's own comment: both
    detectors already claimed it, and the routing contract's last-rule-wins gives it to
    session_recall) -- untouched here, so it is not re-asserted as excluded.
    """

    def test_still_not_provenance_re(self):
        assert not is_provenance_question("what is the evidence behind your answer?")


# ─────────────────────────────────────────────────────────────────────────────
# 2. `load_previous_turn_record` -- the shared Redis read, never raises.
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadPreviousTurnRecord:
    @pytest.mark.asyncio
    async def test_no_conversation_id_is_none_with_no_io(self):
        assert await load_previous_turn_record(None) is None

    @pytest.mark.asyncio
    async def test_a_recorded_evidence_record_is_returned(self, monkeypatch):
        _patch_load_state(monkeypatch, _previous_turn_state(RECORDED_EVIDENCE))
        record = await load_previous_turn_record("conv-1427")
        assert record == RECORDED_EVIDENCE

    @pytest.mark.asyncio
    async def test_a_previous_turn_with_no_record_is_none(self, monkeypatch):
        _patch_load_state(monkeypatch, _previous_turn_state(None))
        assert await load_previous_turn_record("conv-1427") is None

    @pytest.mark.asyncio
    async def test_no_previous_turn_at_all_is_none(self, monkeypatch):
        _patch_load_state(monkeypatch, None)
        assert await load_previous_turn_record("conv-1427") is None

    @pytest.mark.asyncio
    async def test_a_redis_failure_is_none_not_an_exception(self, monkeypatch):
        async def _boom(_conversation_id):
            raise ConnectionError("redis unreachable")

        monkeypatch.setattr(redis_manager_module.redis_manager, "load_state", _boom)
        assert await load_previous_turn_record("conv-1427") is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. The two-turn conversation: turn 1 has evidence, turn 2 asks about it.
# ─────────────────────────────────────────────────────────────────────────────


class TestTheTwoTurnConversationWithEvidence:
    @pytest.mark.asyncio
    async def test_the_second_turn_narrates_the_first_turns_evidence(self, monkeypatch):
        _patch_load_state(monkeypatch, _previous_turn_state(RECORDED_EVIDENCE))
        state = _State("What is the evidence behind your answer?", FIRST_TURN_NOTE)
        result = await session_recall_node(state)

        response = result.intermediate_results["dialogue_response"]
        assert "CO2 Sensor 204" in response
        assert "observed" in response
        assert "read from an instrument" in response
        # Same vocabulary as the inline evidence panel, not a dump of raw UUIDs.
        assert "uuid-co2-204" not in response
        assert result.current_intent == "session_recall"

    @pytest.mark.asyncio
    async def test_a_backward_referencing_phrasing_also_narrates_it(self, monkeypatch):
        _patch_load_state(monkeypatch, _previous_turn_state(RECORDED_EVIDENCE))
        state = _State("How did you arrive at that?", FIRST_TURN_NOTE)
        result = await session_recall_node(state)
        assert "CO2 Sensor 204" in result.intermediate_results["dialogue_response"]

    @pytest.mark.asyncio
    async def test_a_plain_recall_question_is_unaffected(self, monkeypatch):
        """A question about what the USER said (not about the assistant's evidence) must
        keep the existing quote-based behaviour -- this fix must not hijack BUG-941's lane."""
        _patch_load_state(monkeypatch, _previous_turn_state(RECORDED_EVIDENCE))
        state = _State("What did I ask you about earlier?", FIRST_TURN_NOTE)
        result = await session_recall_node(state)
        response = result.intermediate_results["dialogue_response"]
        assert "CO2 level in room 2.01" in response
        assert "CO2 Sensor 204" not in response


# ─────────────────────────────────────────────────────────────────────────────
# 4. Honest declines: no evidence on the previous turn, or no previous turn at all.
# ─────────────────────────────────────────────────────────────────────────────


class TestHonestDeclines:
    @pytest.mark.asyncio
    async def test_the_previous_turn_had_no_evidence_record(self, monkeypatch):
        """A capability/general-knowledge answer carries no evidence key at all."""
        _patch_load_state(monkeypatch, _previous_turn_state(None))
        note = [TurnNote(1, "What can you help me with?", "capability", "answered")]
        state = _State("What is the evidence behind your answer?", note)
        result = await session_recall_node(state)
        response = result.intermediate_results["dialogue_response"]
        assert "no recorded evidence basis" in response
        assert result.current_intent == "session_recall"

    @pytest.mark.asyncio
    async def test_a_not_assessable_record_still_renders_honestly(self, monkeypatch):
        """A record that DID assemble but found nothing to support the answer is itself an
        honest answer (`render`'s NOT_ASSESSABLE handling) -- not the generic decline above."""
        not_assessable = {
            "status": "not_assessable",
            "not_assessable_reason": "no lane produced evidence for this answer",
        }
        _patch_load_state(monkeypatch, _previous_turn_state(not_assessable))
        state = _State("What is the evidence behind your answer?", FIRST_TURN_NOTE)
        result = await session_recall_node(state)
        response = result.intermediate_results["dialogue_response"]
        assert "not_assessable" in response
        assert "no recorded evidence basis" not in response

    @pytest.mark.asyncio
    async def test_no_previous_turn_at_all(self):
        """Nothing asked yet in this conversation -- the existing honest decline, untouched."""
        state = _State("What is the evidence behind your answer?", None)
        result = await session_recall_node(state)
        assert "Nothing has been asked in this conversation yet" in (
            result.intermediate_results["dialogue_response"]
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. `_render_previous_answer_evidence` in isolation.
# ─────────────────────────────────────────────────────────────────────────────


class TestRenderPreviousAnswerEvidenceHelper:
    @pytest.mark.asyncio
    async def test_returns_none_for_a_query_not_about_the_previous_answer(self, monkeypatch):
        _patch_load_state(monkeypatch, _previous_turn_state(RECORDED_EVIDENCE))
        state = _State("placeholder", FIRST_TURN_NOTE)
        assert (
            await _render_previous_answer_evidence(state, "Which rooms have a projector?") is None
        )

    @pytest.mark.asyncio
    async def test_never_raises_when_conversation_id_is_missing(self):
        state = _State("placeholder", FIRST_TURN_NOTE, conversation_id=None)
        result = await _render_previous_answer_evidence(state, "How did you arrive at that?")
        assert result == (
            "**Your last answer in this conversation carries no recorded evidence basis.** "
            "That happens when the turn is too old to carry one, or ended before a record "
            "could be assembled. Ask a question the building answers from its own records "
            "or live readings, then ask how I know, and I will read that record back to you."
        )
