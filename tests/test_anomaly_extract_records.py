"""Regression tests for the anomaly data-handoff + bare-anomaly default metric.

Two bugs made anomaly detection always answer "No sensor data available":
  1. _extract_records() treated sql_result["results"] (a {"data": [...]} dict) as
     the record list and discarded it — so the agent saw 0 rows despite SQL
     returning data.
  2. A bare anomaly query ("are there any unusual readings today?") names no
     metric, so SPARQL RAG picked a sensor type with no time-series UUIDs and the
     pipeline dead-ended. _ANOMALY_METRIC_RE detects the no-metric case so the
     SPARQL node can default the target to temperature.
"""

import pytest

from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

pytestmark = pytest.mark.unit

_agent = AnomalyDetectionAgent()
_ROWS = [{"value": 1.0}, {"value": 2.0}]


def test_extract_records_nested_results_data():
    # The pipeline sql_result shape — this was the dropped case.
    assert _agent._extract_records({"results": {"data": _ROWS}}) == _ROWS


def test_extract_records_flat_data():
    assert _agent._extract_records({"data": _ROWS}) == _ROWS


def test_extract_records_results_as_list():
    assert _agent._extract_records({"results": _ROWS}) == _ROWS


def test_extract_records_list_passthrough():
    assert _agent._extract_records(_ROWS) == _ROWS


def test_extract_records_empty_and_none():
    assert _agent._extract_records({"results": {"data": []}}) == []
    assert _agent._extract_records(None) == []
    assert _agent._extract_records({}) == []


def test_extract_records_filters_non_dicts():
    assert _agent._extract_records({"results": {"data": [{"a": 1}, "bad", 7]}}) == [{"a": 1}]


@pytest.mark.parametrize(
    "query,has_metric",
    [
        ("Are there any unusual temperature readings?", True),
        ("Any unusual CO2 readings today?", True),
        ("is the humidity abnormal?", True),
        ("any weird air quality?", True),
        ("Are there any unusual readings today?", False),
        ("anything strange going on right now?", False),
        ("detect anomalies", False),
    ],
)
def test_anomaly_metric_regex(query, has_metric):
    from orchestrator.workflow._orchestrator import _ANOMALY_METRIC_RE

    assert bool(_ANOMALY_METRIC_RE.search(query)) is has_metric
