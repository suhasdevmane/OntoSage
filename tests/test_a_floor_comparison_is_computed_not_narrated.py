# -*- coding: utf-8 -*-
"""BUG-537 / BUG-556: floors are compared from figures computed in code, across every floor."""

import inspect

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent
from orchestrator.services.series_summary import summarise_groups

pytestmark = pytest.mark.unit


def _agent():
    return SPARQLAgent.__new__(SPARQLAgent)


@pytest.mark.parametrize(
    "question",
    ["Which floor used the most energy yesterday?", "what is the temperature on each floor?",
     "compare CO2 across floors"],
)
def test_a_metric_compared_across_unnamed_floors_uses_every_floor(question):
    q = _agent()._floor_scoped_sparql(question, None)
    assert q is not None and "FILTER(?floorNum IN" not in q and "LIMIT 500" in q
    assert "?floorNum" in q


@pytest.mark.parametrize(
    "question",
    ["How many floors does this building have?", "which floor is the lab on?", "Show me floor 3"],
)
def test_floor_questions_without_a_metric_are_left_to_their_templates(question):
    assert _agent()._floor_scoped_sparql(question, None) is None


def test_named_floors_still_filter_to_those_floors():
    q = _agent()._floor_scoped_sparql("average CO2 on floor 1 versus floor 3", None)
    assert 'FILTER(?floorNum IN ("1", "3"))' in q and "LIMIT 100" in q


def test_sensor_metadata_carries_the_floor():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    orch = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    meta = orch._build_sensor_metadata_from_bindings([
        {"sensor": {"value": "http://x#CO2_5.01"}, "label": {"value": "CO2 5.01"},
         "floorNum": {"value": "5"}, "uuid": {"value": "11111111-1111-1111-1111-111111111111"}},
    ])
    assert meta["11111111-1111-1111-1111-111111111111"]["floor"] == "5"


def _rows(meta, per=10):
    return [{"uuid": u, "value": float(i + 1)} for i, u in enumerate(meta) for _ in range(per)]


def test_energy_is_totalled_and_averaged_per_floor():
    meta = {f"u{i}": {"unit": "kWh", "floor": str(i % 2)} for i in range(4)}
    text = summarise_groups(_rows(meta), meta)
    assert "- Floor 0: 2 sensor(s), 20 readings; total 40 kWh; mean 2 kWh" in text
    assert "- Floor 1: 2 sensor(s), 20 readings; total 60 kWh; mean 3 kWh" in text
    assert "do not recompute" in text


def test_a_concentration_is_averaged_not_totalled():
    meta = {"a": {"unit": "ppm", "floor": "1"}, "b": {"unit": "ppm", "floor": "3"}}
    text = summarise_groups(_rows(meta), meta)
    assert "total" not in text.split("\n")[1] and "mean 1 ppm" in text


def test_incompatible_units_are_refused_with_the_reason():
    meta = {"a": {"unit": "ppm", "floor": "1"}, "b": {"unit": "°C", "floor": "3"}}
    assert "NOT computed" in summarise_groups(_rows(meta), meta)


def test_one_floor_is_not_a_comparison():
    meta = {"a": {"unit": "ppm", "floor": "1"}}
    assert summarise_groups(_rows(meta), meta) is None


def test_the_narration_uses_the_group_summary_and_gets_the_rows():
    from orchestrator.agents.analytics_agent import AnalyticsAgent

    src = inspect.getsource(AnalyticsAgent._format_analysis)
    assert "summarise_groups(" in src and 'key="floor"' in src
    assert "rows=data.get(\"data\", [])" in inspect.getsource(AnalyticsAgent.analyze)


def test_plant_side_sensors_never_enter_a_floor_measurement():
    """WB-14: AHU supply/return temperatures were averaged into per-floor room temperature."""
    q = _agent()._floor_scoped_sparql("Which floor is the warmest right now?", None)
    assert "FILTER NOT EXISTS" in q and "brick:Return_Air_Temperature_Sensor" in q


def test_a_per_floor_comparison_skips_code_generation():
    from orchestrator.agents.analytics_agent import AnalyticsAgent

    src = inspect.getsource(AnalyticsAgent.analyze)
    assert src.index("summarise_groups(") < src.index("await self._generate_code(")
    assert '"method": "per_floor_summary"' in src
