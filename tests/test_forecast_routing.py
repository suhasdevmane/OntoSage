# tests/test_forecast_routing.py
import pytest

FORECAST_QUERIES = [
    "Predict temperature for tomorrow afternoon",
    "Forecast energy usage for next week",
    "What will the CO2 level be tomorrow?",
    "What will be the temperature tomorrow?",
    "Is temperature projected to rise next week?",
    "What will humidity be like tomorrow morning?",
]

NON_FORECAST_QUERIES = [
    "Show me floor 3 layout",
    "What are the fire evacuation procedures?",
    "Hello, what can you do?",
    "Show me energy data for next week",
    "What is the expected sensor output?",
]


def _is_forecast_query(query: str) -> bool:
    from orchestrator.agents.dialogue_agent import _FORECAST_KWS, _SENSOR_METRIC_KWS

    q = query.lower()
    return any(kw in q for kw in _FORECAST_KWS) and any(kw in q for kw in _SENSOR_METRIC_KWS)


@pytest.mark.unit
def test_forecast_queries_detected():
    for q in FORECAST_QUERIES:
        assert _is_forecast_query(q), f"Expected forecast detection for: {q!r}"


@pytest.mark.unit
def test_non_forecast_queries_not_detected():
    for q in NON_FORECAST_QUERIES:
        assert not _is_forecast_query(q), f"False positive forecast for: {q!r}"
