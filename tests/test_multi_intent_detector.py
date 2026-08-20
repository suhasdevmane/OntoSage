"""
Tests for the multi-intent detector heuristic and decomposition logic.

These tests verify that:
1. Simple single-intent queries are NOT decomposed (no false positives)
2. Compound multi-intent queries ARE decomposed correctly
3. The heuristic gate filters efficiently (no LLM calls for simple queries)
4. Invalid sub-intents from LLM are dropped gracefully
5. The feature flag disables decomposition entirely
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator.services.multi_intent_detector import (
    _CONNECTIVE_PHRASES,
    INTENT_DOMAINS,
    MultiIntentDetector,
    SubIntent,
)


@pytest.fixture
def detector():
    return MultiIntentDetector()


# ── Heuristic gate tests (no LLM call) ────────────────────────────────


class TestHeuristicGate:
    def test_short_query_rejected(self, detector):
        assert detector._passes_heuristic("What is the temperature?") is False

    def test_no_connectives_rejected(self, detector):
        query = (
            "The temperature on floor 5 seems very high right now, "
            "I wonder whether the HVAC system is working correctly."
        )
        assert detector._passes_heuristic(query) is False

    def test_single_domain_rejected(self, detector):
        query = (
            "Can you check the temperature and also tell me the humidity "
            "reading in zone 5 right now?"
        )
        assert detector._passes_heuristic(query) is False

    def test_multi_domain_with_connective_passes(self, detector):
        query = (
            "Can you check the temperature on floor 5, tell me if anything "
            "unusual was flagged, and let me know who I should contact?"
        )
        assert detector._passes_heuristic(query) is True

    def test_numbered_list_passes(self, detector):
        query = (
            "1) What are the current CO2 levels on floor 3, "
            "2) how many rooms are on that floor, and "
            "3) how do I book a room?"
        )
        assert detector._passes_heuristic(query) is True

    def test_first_then_finally_passes(self, detector):
        query = (
            "First tell me the current temperature in zone 5.08, "
            "then check if there are any anomalies, and finally "
            "suggest whether I should move my team."
        )
        assert detector._passes_heuristic(query) is True


# ── Decomposition tests (mock LLM) ──────────────────────────────────


class TestDecomposition:
    @pytest.mark.asyncio
    async def test_t15_c1_decomposition(self, detector):
        """T15-C1: analytics + anomaly + capability"""
        query = (
            "Yesterday afternoon the whole of floor 5 felt terrible - way too hot "
            "and the air was stale. Can you check what happened with both temperature "
            "and CO2 on floor 5, tell me if anything unusual was flagged, and let me "
            "know who I should contact?"
        )
        mock_response = json.dumps(
            [
                {
                    "sub_query": "Check temperature and CO2 on floor 5 yesterday",
                    "intent": "analytics",
                    "entities": ["floor 5", "temperature", "co2"],
                },
                {
                    "sub_query": "Were there any anomalies flagged?",
                    "intent": "anomaly",
                    "entities": ["floor 5"],
                },
                {
                    "sub_query": "Who should I contact about this?",
                    "intent": "capability",
                    "entities": [],
                },
            ]
        )
        with patch.object(
            detector,
            "_decompose",
            wraps=detector._decompose,
        ):
            with patch(
                "orchestrator.services.multi_intent_detector.llm_manager.generate",
                new_callable=AsyncMock,
                return_value=mock_response,
            ):
                result = await detector.detect(query, "anomaly", ["floor 5"])

        assert result is not None
        assert len(result) == 3
        intents = {s.intent for s in result}
        assert "analytics" in intents
        assert "anomaly" in intents
        assert "capability" in intents

    @pytest.mark.asyncio
    async def test_t15_c2_decomposition(self, detector):
        """T15-C2: analytics + spatial_query + capability"""
        query = (
            "I need to book the most comfortable room for a 3-hour workshop. "
            "Which rooms on floor 3 have the best temperature and air quality, "
            "how big are they, and how do I book them?"
        )
        mock_response = json.dumps(
            [
                {
                    "sub_query": "Best temperature and air quality rooms on floor 3",
                    "intent": "analytics",
                    "entities": ["floor 3"],
                },
                {
                    "sub_query": "Room sizes on floor 3",
                    "intent": "spatial_query",
                    "entities": ["floor 3"],
                },
                {"sub_query": "How to book a room", "intent": "capability", "entities": []},
            ]
        )
        with patch(
            "orchestrator.services.multi_intent_detector.llm_manager.generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await detector.detect(query, "analytics", ["floor 3"])

        assert result is not None
        assert len(result) == 3
        intents = {s.intent for s in result}
        assert "analytics" in intents
        assert "spatial_query" in intents
        assert "capability" in intents

    @pytest.mark.asyncio
    async def test_single_intent_query_returns_none(self, detector):
        """Simple queries should never be decomposed."""
        query = "What is the current temperature in zone 3?"
        result = await detector.detect(query, "sensor_data", ["zone 3"])
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_intents_dropped(self, detector):
        """LLM returning invalid intent types should be filtered out."""
        query = (
            "Can you check the temperature and also tell me the meaning of life "
            "and let me know who to contact about maintenance?"
        )
        mock_response = json.dumps(
            [
                {"sub_query": "Check temperature", "intent": "analytics", "entities": []},
                {"sub_query": "Meaning of life", "intent": "philosophy", "entities": []},
                {"sub_query": "Maintenance contact", "intent": "capability", "entities": []},
            ]
        )
        with patch(
            "orchestrator.services.multi_intent_detector.llm_manager.generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await detector.detect(query, "analytics", [])

        assert result is not None
        assert len(result) == 2
        assert all(s.intent != "philosophy" for s in result)

    @pytest.mark.asyncio
    async def test_llm_returns_single_intent_returns_none(self, detector):
        """If LLM only finds one sub-intent, treat as single-intent."""
        query = (
            "Can you check the temperature on floor 5 and also tell me the "
            "humidity reading in the same zone right now?"
        )
        mock_response = json.dumps(
            [
                {
                    "sub_query": "Temperature and humidity on floor 5",
                    "intent": "analytics",
                    "entities": ["floor 5"],
                },
            ]
        )
        with patch(
            "orchestrator.services.multi_intent_detector.llm_manager.generate",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await detector.detect(query, "analytics", ["floor 5"])

        assert result is None

    @pytest.mark.asyncio
    async def test_feature_flag_disabled(self, detector):
        """MULTI_INTENT_ENABLED=False should skip all detection."""
        query = (
            "Check temperature, flag anomalies, and tell me who to contact "
            "about the heating system in the building right now?"
        )
        with patch("orchestrator.services.multi_intent_detector.settings") as mock_settings:
            mock_settings.MULTI_INTENT_ENABLED = False
            mock_settings.MULTI_INTENT_MIN_LENGTH = 80
            result = await detector.detect(query, "anomaly", [])

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self, detector):
        """LLM errors should be non-fatal — return None."""
        query = (
            "Check temperature on floor 5 and also tell me who to contact "
            "about the heating system in this building?"
        )
        with patch(
            "orchestrator.services.multi_intent_detector.llm_manager.generate",
            new_callable=AsyncMock,
            side_effect=Exception("LLM timeout"),
        ):
            result = await detector.detect(query, "analytics", [])

        assert result is None


# ── SubIntent dataclass tests ─────────────────────────────────────────


class TestSubIntent:
    def test_to_dict(self):
        si = SubIntent(sub_query="test", intent="analytics", entities=["zone 5"])
        d = si.to_dict()
        assert d["sub_query"] == "test"
        assert d["intent"] == "analytics"
        assert d["entities"] == ["zone 5"]


# ── Domain coverage tests ────────────────────────────────────────────


class TestIntentDomains:
    def test_all_domains_have_keywords(self):
        for domain, keywords in INTENT_DOMAINS.items():
            assert len(keywords) > 0, f"Domain {domain} has no keywords"

    def test_connective_phrases_nonempty(self):
        assert len(_CONNECTIVE_PHRASES) > 10
