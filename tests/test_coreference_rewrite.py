"""Tests for co-reference / follow-up query rewriting (issue #1).

Covers the cheap heuristic gate (`_is_followup_query`) and the gated LLM
rewrite (`DialogueAgent.rewrite_to_standalone`). The LLM is mocked, so these
tests run offline and are safe for CI.
"""

from unittest.mock import AsyncMock, patch

import pytest

from shared.models import ConversationState, Message


def _state(*contents: str) -> ConversationState:
    """Build a state whose messages alternate user/assistant, current last."""
    msgs = [
        Message(role="user" if i % 2 == 0 else "assistant", content=c)
        for i, c in enumerate(contents)
    ]
    return ConversationState(
        conversation_id="conv-coref",
        user_id="tester",
        user_message=contents[-1] if contents else "",
        building_id="bldg1",
        messages=msgs,
    )


# ── Heuristic gate ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,expected",
    [
        ("and what about humidity there", True),
        ("the same for floor 5", True),
        ("how about floor 2", True),
        ("show me", True),  # very short
        ("what about it", True),
        ("what is the temperature on floor 3", False),
        ("list all CO2 sensors in the building please", False),
        ("", False),
    ],
)
def test_is_followup_query(query, expected):
    from orchestrator.agents.dialogue_agent import _is_followup_query

    assert _is_followup_query(query) is expected


# ── rewrite_to_standalone ──────────────────────────────────────────────────────


@pytest.fixture
def agent():
    from orchestrator.agents.dialogue_agent import DialogueAgent

    return DialogueAgent()


@pytest.mark.asyncio
async def test_rewrite_disabled_by_flag(agent):
    state = _state("avg temperature on floor 3", "Floor 3 avg is 21C", "and humidity there")
    with patch("orchestrator.agents.dialogue_agent.settings") as s:
        s.COREFERENCE_REWRITE_ENABLED = False
        assert await agent.rewrite_to_standalone(state) is None


@pytest.mark.asyncio
async def test_rewrite_requires_prior_turn(agent):
    # Only the current message — nothing to resolve against.
    state = _state("and humidity there")
    assert await agent.rewrite_to_standalone(state) is None


@pytest.mark.asyncio
async def test_rewrite_skips_self_contained(agent):
    # Heuristic returns False → no LLM call, returns None.
    state = _state(
        "avg temperature on floor 3",
        "Floor 3 avg is 21C",
        "what is the average humidity on floor 2",
    )
    with patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(),
    ) as gen:
        assert await agent.rewrite_to_standalone(state) is None
        gen.assert_not_called()


@pytest.mark.asyncio
async def test_rewrite_resolves_followup(agent):
    state = _state(
        "what is the average temperature on floor 3",
        "Floor 3 average temperature is 21C.",
        "and what about humidity there",
    )
    with patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(return_value="what is the average humidity on floor 3"),
    ):
        out = await agent.rewrite_to_standalone(state)
    assert out == "what is the average humidity on floor 3"


@pytest.mark.asyncio
async def test_rewrite_strips_quotes(agent):
    state = _state("temperature on floor 3", "21C", "and humidity there")
    with patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(return_value='"humidity on floor 3"\n'),
    ):
        assert await agent.rewrite_to_standalone(state) == "humidity on floor 3"


@pytest.mark.asyncio
async def test_rewrite_noop_when_unchanged(agent):
    # LLM judged it already self-contained and echoed it back → None.
    state = _state("temperature on floor 3", "21C", "what about floor 2")
    with patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(return_value="what about floor 2"),
    ):
        assert await agent.rewrite_to_standalone(state) is None


@pytest.mark.asyncio
async def test_rewrite_graceful_on_llm_error(agent):
    state = _state("temperature on floor 3", "21C", "and humidity there")
    with patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(side_effect=RuntimeError("LLM down")),
    ):
        assert await agent.rewrite_to_standalone(state) is None


@pytest.mark.asyncio
async def test_rewrite_rejects_overlong(agent):
    state = _state("temperature on floor 3", "21C", "and humidity there")
    with patch(
        "orchestrator.agents.dialogue_agent.llm_manager.generate",
        new=AsyncMock(return_value="x" * 600),
    ):
        assert await agent.rewrite_to_standalone(state) is None
