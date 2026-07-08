"""Unit tests for the general_knowledge live-data detection heuristics.

These are pure functions — no network, no LLM, no services. They gate whether a
general-knowledge question triggers a live weather/web fetch.
"""

import pytest

from orchestrator.workflow._orchestrator import (
    _detect_answer_length,
    _detect_live_data_need,
    _extract_location,
)

pytestmark = pytest.mark.unit


# ── Answer-length detection ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "query,expected",
    [
        ("In one sentence, what is entropy?", "short"),
        ("Briefly explain TCP.", "short"),
        ("Explain in detail how photosynthesis works.", "long"),
        ("Give me a comprehensive overview of ML.", "long"),
        ("Summarize how a hash table works.", "summary"),
        ("What are the key points of REST?", "summary"),
        ("Who wrote Hamlet?", "medium"),
    ],
)
def test_detect_answer_length(query, expected):
    assert _detect_answer_length(query) == expected


def test_explicit_length_overrides_phrasing():
    # Explicit hint wins even when phrasing suggests otherwise.
    assert _detect_answer_length("Explain in detail X", explicit="short") == "short"
    assert _detect_answer_length("anything", explicit="bogus") == "medium"


# ── Location extraction ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "query,expected",
    [
        ("What's the weather in London right now?", "London"),
        ("weather forecast for New York", "New York"),
        ("Is it raining in San Francisco today?", "San Francisco"),
        ("how hot is it in Tokyo?", "Tokyo"),
        ("What is the weather?", None),
        ("Is it sunny outside?", None),
    ],
)
def test_extract_location(query, expected):
    assert _extract_location(query) == expected


# ── Live-data need detection ──────────────────────────────────────────────────
def test_weather_question_routes_to_weather():
    kind, arg = _detect_live_data_need("What's the weather in Paris right now?")
    assert kind == "weather"
    assert arg == "Paris"


def test_weather_without_location_still_weather_empty_arg():
    kind, arg = _detect_live_data_need("Is it raining outside?")
    assert kind == "weather"
    assert arg == ""


@pytest.mark.parametrize(
    "query",
    [
        "What is the latest version of Python?",
        "Who is the current CEO of OpenAI?",
        "What's the price of Bitcoin right now?",
        "Give me today's news headlines.",
    ],
)
def test_live_web_questions_route_to_web(query):
    kind, arg = _detect_live_data_need(query)
    assert kind == "web"
    assert arg == query.strip()


@pytest.mark.parametrize(
    "query",
    [
        "What is the capital of France?",
        "Explain how photosynthesis works.",
        "Who wrote Hamlet?",
        "What is a hash table?",
    ],
)
def test_static_questions_need_no_live_data(query):
    assert _detect_live_data_need(query) is None
