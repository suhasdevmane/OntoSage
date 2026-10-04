# -*- coding: utf-8 -*-
"""F7 (QA-trial plan, 2026-10-04): a declared location was used ONCE, for the immediate
next question, and never remembered. "I am in room 3.01" storage is now unconditional
(whether or not resolve_location_statement produces an immediate rewrite), carried
forward across turns via turn_memory._CARRY_FORWARD_KEYS, and consumed by the spatial
lane's "nearest" fallback as a better default than the building's entrance -- disclosed,
never silently.

Scope note: this is implemented ENTIRELY inside the spatial lane's own fallback, never
by injecting the remembered token into the co-reference REWRITE text. The acceptance
criterion's own phrasing ("a remembered place does NOT pass rewrite_invents_a_place as a
user-named place for a non-wayfinding question") is satisfied structurally: the
remembered token is never passed to that function, or to any rewrite, for ANY question
shape -- see TestTheRememberedLocationNeverFeedsTheRewrite.
"""
import re
from types import SimpleNamespace

import pytest

from orchestrator.services.context_switch import _LOCATION_STATEMENT_RE, rewrite_invents_a_place
from orchestrator.services.turn_memory import _CARRY_FORWARD_KEYS

pytestmark = pytest.mark.unit


class TestTheStatementIsRecognised:
    @pytest.mark.parametrize(
        "statement,expected",
        [
            ("I am in room 3.01", "room 3.01"),
            ("I'm on floor 2", "floor 2"),
            ("we are in room 5.16", "room 5.16"),
            ("I am at rm 2.01", "room 2.01"),
        ],
    )
    def test_the_regex_extracts_the_place_token(self, statement, expected):
        m = _LOCATION_STATEMENT_RE.match(statement)
        assert m is not None
        token = re.sub(r"\s+", " ", m.group("place").strip().lower())
        token = re.sub(r"^rm\.?\s*", "room ", token)
        assert token == expected


class TestItIsCarriedForwardAcrossTurns:
    def test_remembered_location_is_in_the_carry_forward_set(self):
        """Without this, /v1 rebuilding state fresh each turn loses the token the
        moment the turn that stated it ends."""
        assert "remembered_location" in _CARRY_FORWARD_KEYS


class TestTheWriteRunsOnEveryTurnNotOnlyFollowUps:
    """Found live, the first time this feature was end-to-end tested: a two-turn
    conversation where turn 1 was 'I am in room 3.01' (the FIRST message, no prior
    turn) produced no remember-log-line at all, and turn 2's 'nearest toilet' fell back
    to the entrance default. Root cause: the write originally lived inside
    rewrite_to_standalone, which returns before doing anything when `len(msgs) < 2` --
    exactly the shape of a location stated as the first thing a user says. Moved to
    _dialogue_node, which runs on every turn regardless."""

    def test_the_write_sits_in_the_dialogue_node_before_the_rewrite_call(self):
        import inspect

        from orchestrator.workflow._orchestrator import WorkflowOrchestrator

        src = inspect.getsource(WorkflowOrchestrator._dialogue_node)
        write_idx = src.index('state.intermediate_results["remembered_location"] = _token')
        rewrite_idx = src.index("rewrite_to_standalone(state)")
        assert write_idx < rewrite_idx

    def test_the_write_reads_the_raw_latest_message_not_a_follow_up_gated_one(self):
        import inspect

        from orchestrator.workflow._orchestrator import WorkflowOrchestrator

        src = inspect.getsource(WorkflowOrchestrator._dialogue_node)
        write_idx = src.index('state.intermediate_results["remembered_location"]')
        window = src[max(0, write_idx - 400) : write_idx]
        assert "state.messages[-1].content" in window


class TestTheSpatialLaneUsesItAsALastResort:
    def test_wired_into_the_spatial_node_before_resolve(self):
        import inspect

        from orchestrator.workflow._orchestrator import WorkflowOrchestrator

        src = inspect.getsource(WorkflowOrchestrator)
        idx = src.index("agent._remembered_place_token = state.intermediate_results.get(")
        resolve_idx = src.index("await agent.resolve(", idx)
        assert idx < resolve_idx, "the token must be set BEFORE resolve() is called"

    def test_the_fallback_reads_and_clears_the_token(self):
        import inspect

        from orchestrator.agents.spatial_agent import SpatialAgent

        src = inspect.getsource(SpatialAgent._answer_nearest_inner)
        assert "_remembered_place_token" in src
        assert "self._remembered_place_token = None" in src, (
            "the token must be cleared after one use -- the agent is a singleton and a "
            "stale token must never leak into a later, unrelated request"
        )

    def test_the_remembered_disclosure_is_distinct_from_the_entrance_guess(self):
        import inspect

        from orchestrator.agents.spatial_agent import SpatialAgent

        src = inspect.getsource(SpatialAgent._answer_nearest)
        assert "Based on what you told me earlier" in src
        assert "the building's entrance" in src
        assert "_assumed_from_remembered" in src


class TestTheRememberedLocationNeverFeedsTheRewrite:
    """The acceptance criterion's concern, verified structurally: the remembered token
    is never passed to rewrite_invents_a_place (or to any rewrite) for ANY question --
    F7 is implemented entirely inside the spatial lane's own fallback, so there is no
    code path by which a remembered place could be mistaken for one the user named in
    the current turn."""

    def test_rewrite_to_standalone_never_mentions_the_remembered_key_at_all(self):
        """The write lives in _dialogue_node, BEFORE rewrite_to_standalone is called --
        not inside it (see TestTheWriteRunsOnEveryTurnNotOnlyFollowUps for why: that
        function returns early for a turn with no PRIOR message, which is exactly the
        turn a location statement is most likely to be the FIRST thing said in)."""
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        assert "remembered_location" not in src

    def test_rewrite_invents_a_place_is_unaffected_by_a_remembered_location(self):
        """A direct functional check: calling the real guard with a remembered-shaped
        value as the 'rewritten' text, for a non-wayfinding question, is refused exactly
        as any other invented place would be -- confirming nothing in this feature
        weakens that guard."""
        latest = "what is the CO2 level there?"
        rewritten = "what is the CO2 level in room 3.01?"
        user_texts = [latest]  # the user named no place anywhere
        assert rewrite_invents_a_place(latest, rewritten, user_texts) is True
