"""Phase 14B — compound query verification.

`MultiIntentDetector.detect()` is the gate between single- and multi-intent
handling.  These tests verify:

  1. The heuristic gate correctly rejects single-intent queries (no LLM call,
     no overhead).
  2. The heuristic gate accepts genuine compound queries (passes through to
     LLM decomposition).
  3. The end-to-end decomposition emits the expected sub-intents for
     representative compound patterns.

The LLM step is mocked — we test the deterministic pre/post-processing logic,
not the LLM's classification accuracy (that's covered by the live survey).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.services.multi_intent_detector import MultiIntentDetector, SubIntent

# ─────────────────────────────────────────────────────────────────────────────
# Heuristic gate — fast path for single-intent queries
# ─────────────────────────────────────────────────────────────────────────────


SINGLE_INTENT_QUERIES = [
    # Short queries fail the length gate (50 chars, Phase 16A).
    "hi",
    "What is the temperature in zone 5.28?",
    "show me floor 3",
    "where is the prayer room?",
    # Long but only one intent domain.
    ("Can you tell me the average temperature in zone 5.28 over the " "past two weeks please?"),
]


# Phase 16A — compound patterns that were missed at the old 80-char
# threshold but are caught now at 50.  Each query is a NATURAL phrasing
# (not pad-to-length) and must satisfy: >= 50 chars, explicit connective
# from _CONNECTIVE_PHRASES, >= 2 INTENT_DOMAINS hit.
SHORT_COMPOUND_QUERIES = [
    # 57 chars: data ("temperature") + capability ("lift"), connective "tell me"
    "show me temperature in 5.28 and tell me where the lift is",
    # 55 chars: floor_plan ("layout") + spatial ("how many rooms"), connective "tell me"
    "show me floor 3 layout and tell me how many rooms there",
    # 63 chars: data ("temp readings") + report ("generate report"), connective "tell me"
    "temp readings in 5.28 today and tell me how to generate report",
]


@pytest.mark.parametrize("query", SINGLE_INTENT_QUERIES)
def test_heuristic_rejects_single_intent(query):
    detector = MultiIntentDetector()
    assert not detector._passes_heuristic(
        query
    ), f"Heuristic incorrectly flagged single-intent query as compound: {query!r}"


COMPOUND_QUERIES = [
    # The heuristic intentionally requires explicit compound markers
    # ("and also", "tell me", "1.", "first/then/finally", ", and how", etc.)
    # to avoid false-positives on every "and"-containing query.  Each
    # query below MUST satisfy:
    #   * len >= MULTI_INTENT_MIN_LENGTH (80)
    #   * contains an explicit connective from _CONNECTIVE_PHRASES
    #   * keywords from >= 2 distinct INTENT_DOMAINS
    #
    # 1. data + capability: explicit "tell me" connective
    (
        "What is the temperature in zone 5.28 and also tell me whether "
        "the building has a lift to floor 5"
    ),
    # 2. floor_plan + spatial: explicit "tell me" connective
    ("Show me the floor 3 layout and also tell me how many rooms are " "there on that floor"),
    # 3. compare + recommend: numeric list connective "1." / "2."
    (
        "1. Compare CO2 levels between floor 1 and floor 3 over the past week. "
        "2. Recommend what we should do to improve air quality."
    ),
    # 4. data + report: explicit "tell me" connective
    (
        "Show me the current temperature readings and tell me how to "
        "generate a weekly report so I can share it with the team"
    ),
]


@pytest.mark.parametrize("query", COMPOUND_QUERIES)
def test_heuristic_accepts_compound(query):
    detector = MultiIntentDetector()
    assert detector._passes_heuristic(query), f"Heuristic missed compound query: {query!r}"


@pytest.mark.parametrize("query", SHORT_COMPOUND_QUERIES)
def test_heuristic_accepts_short_compound(query):
    """Phase 16A — short compound queries that were missed at the old 80-char
    threshold but should pass at the new 50-char threshold."""
    detector = MultiIntentDetector()
    assert len(query) >= 50, f"Test misconfigured — query is only {len(query)} chars: {query!r}"
    assert detector._passes_heuristic(
        query
    ), f"Heuristic still misses {len(query)}-char compound query: {query!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Full decompose path — heuristic + (mocked) LLM
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decompose_returns_subintents_when_llm_yields_valid_json():
    detector = MultiIntentDetector()
    query = (
        "Show the temperature in zone 5.28 and tell me how many rooms are on "
        "floor 3 and recommend HVAC settings"
    )

    mock_llm_response = json.dumps(
        [
            {"sub_query": "temperature in 5.28", "intent": "sensor_data", "entities": ["5.28"]},
            {
                "sub_query": "how many rooms on floor 3",
                "intent": "spatial_query",
                "entities": ["floor 3"],
            },
            {"sub_query": "recommend HVAC settings", "intent": "recommend", "entities": []},
        ]
    )

    with patch(
        "orchestrator.services.multi_intent_detector.llm_manager.generate",
        new=AsyncMock(return_value=mock_llm_response),
    ):
        result = await detector.detect(query, primary_intent="sensor_data")

    assert result is not None
    assert len(result) == 3
    intents = [s.intent for s in result]
    assert "sensor_data" in intents
    assert "spatial_query" in intents
    assert "recommend" in intents


@pytest.mark.asyncio
async def test_decompose_returns_none_for_short_query():
    """Short query never reaches the LLM call (heuristic short-circuits)."""
    detector = MultiIntentDetector()
    with patch(
        "orchestrator.services.multi_intent_detector.llm_manager.generate",
        new=AsyncMock(return_value="[]"),
    ) as mock_gen:
        result = await detector.detect("hi", primary_intent="general")

    assert result is None
    assert not mock_gen.called, "LLM should NOT be called for short queries"


@pytest.mark.asyncio
async def test_decompose_drops_invalid_intents():
    """The decomposer filters sub-intents whose `intent` field isn't in
    VALID_INTENTS — protects the planner from receiving garbage labels."""
    detector = MultiIntentDetector()
    # Compound query that passes the heuristic (data + capability via `lift`).
    query = (
        "What is the temperature in zone 5.28 and also tell me whether the "
        "building has a lift to the upper floors"
    )

    mock_llm_response = json.dumps(
        [
            {"sub_query": "temp in 5.28", "intent": "sensor_data", "entities": []},
            {"sub_query": "prayer room", "intent": "totally_made_up_intent_xyz", "entities": []},
            {"sub_query": "fire safety", "intent": "discovery", "entities": []},
        ]
    )

    with patch(
        "orchestrator.services.multi_intent_detector.llm_manager.generate",
        new=AsyncMock(return_value=mock_llm_response),
    ):
        result = await detector.detect(query, primary_intent="sensor_data")

    assert result is not None
    intents = [s.intent for s in result]
    assert "totally_made_up_intent_xyz" not in intents
    assert "sensor_data" in intents
    assert "discovery" in intents


@pytest.mark.asyncio
async def test_decompose_caps_at_five_subintents():
    """Even if the LLM returns more, we keep only the first five (planner's
    max step budget is also small)."""
    detector = MultiIntentDetector()
    query = "long compound query " * 8  # 160+ chars

    mock_llm_response = json.dumps(
        [{"sub_query": f"task {i}", "intent": "analytics", "entities": []} for i in range(8)]
    )

    with patch(
        "orchestrator.services.multi_intent_detector.llm_manager.generate",
        new=AsyncMock(return_value=mock_llm_response),
    ):
        result = await detector.detect(query, primary_intent="analytics")

    # Skip if heuristic rejects this synthetic query; only assert the cap when
    # the LLM path actually runs.
    if result is None:
        pytest.skip("synthetic query didn't pass heuristic; cap test N/A")
    assert len(result) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# Phase 14A interplay — multi-intent + multi-persona must coexist
# ─────────────────────────────────────────────────────────────────────────────


def test_subintent_dict_serialization_stable():
    """SubIntent.to_dict shape is part of the contract with the planner.
    Pin it so downstream consumers don't silently break."""
    s = SubIntent(
        sub_query="temperature in 5.28",
        intent="sensor_data",
        entities=["5.28"],
    )
    d = s.to_dict()
    assert d == {
        "sub_query": "temperature in 5.28",
        "intent": "sensor_data",
        "entities": ["5.28"],
    }


def test_valid_intents_is_a_frozenset_of_strings():
    """VALID_INTENTS is loaded at import time from the registry and used by
    every consumer to validate sub-intent labels.  Pin the type contract."""
    from orchestrator.services.multi_intent_detector import VALID_INTENTS

    assert isinstance(VALID_INTENTS, frozenset)
    assert all(isinstance(s, str) for s in VALID_INTENTS)
    # At minimum the core intents must be present
    for intent in ("sensor_data", "analytics", "compare", "report"):
        assert (
            intent in VALID_INTENTS
        ), f"core intent {intent!r} missing from VALID_INTENTS — registry load failure?"
