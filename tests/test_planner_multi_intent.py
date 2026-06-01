"""
Tests for the enhanced PlannerAgent multi-intent execution path.

Verifies:
1. Pre-built plans from MultiIntentDetector are accepted and executed
2. Dependency-aware ordering: data pipeline agents share sparql→sql prefix
3. Standalone agents (capability, floor_plan, spatial_query) run independently
4. Multi-section response assembly produces sectioned markdown
5. Partial failures produce graceful degradation (other sections still appear)
6. _extract_sensor_metadata bug fix works correctly
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.agents.planner_agent import (
    ExecutionPlan,
    PlanStep,
    PlannerAgent,
    _DATA_PIPELINE_AGENTS,
    _STANDALONE_AGENTS,
)


@pytest.fixture
def planner():
    return PlannerAgent()


@pytest.fixture
def mock_state():
    from shared.models import ConversationState, Message

    state = ConversationState(
        conversation_id="test-multi-001",
        user_id="test-user",
        messages=[Message(role="user", content="complex multi-intent query")],
        current_intent="planner",
        building_id="bldg1",
        intermediate_results={},
    )
    return state


# ── Plan building from multi-intent ──────────────────────────────────

class TestBuildFromMultiIntent:
    def test_mixed_group_a_and_b(self, planner):
        """Group A (data pipeline) + Group B (standalone) produces correct ordering."""
        multi_plan = {
            "sub_intents": [
                {"sub_query": "Check temperature on floor 5", "intent": "analytics", "entities": ["floor 5"]},
                {"sub_query": "Flag anomalies", "intent": "anomaly", "entities": []},
                {"sub_query": "Who to contact", "intent": "capability", "entities": []},
            ],
            "primary_intent": "anomaly",
        }
        plan = planner._build_from_multi_intent("complex query", multi_plan)

        assert plan.multi_intent is True
        agents = [s.agent for s in plan.steps]
        assert agents[0] == "sparql"
        assert agents[1] == "sql"
        assert "analytics" in agents
        assert "anomaly" in agents
        assert "capability" in agents
        sparql_idx = agents.index("sparql")
        sql_idx = agents.index("sql")
        capability_idx = agents.index("capability")
        assert sparql_idx < sql_idx
        assert sql_idx < capability_idx or capability_idx > sql_idx

    def test_all_standalone_no_data_prefix(self, planner):
        """All Group B sub-intents should NOT include sparql/sql prefix."""
        multi_plan = {
            "sub_intents": [
                {"sub_query": "Show floor 3", "intent": "floor_plan", "entities": []},
                {"sub_query": "Room sizes", "intent": "spatial_query", "entities": []},
                {"sub_query": "How to book", "intent": "capability", "entities": []},
            ],
            "primary_intent": "floor_plan",
        }
        plan = planner._build_from_multi_intent("query", multi_plan)
        agents = [s.agent for s in plan.steps]
        assert "sparql" not in agents
        assert "sql" not in agents
        assert len(agents) == 3

    def test_sensor_data_skipped_as_duplicate(self, planner):
        """sensor_data maps to data pipeline, so sparql+sql cover it."""
        multi_plan = {
            "sub_intents": [
                {"sub_query": "Current temp", "intent": "sensor_data", "entities": []},
                {"sub_query": "Contact info", "intent": "capability", "entities": []},
            ],
            "primary_intent": "sensor_data",
        }
        plan = planner._build_from_multi_intent("query", multi_plan)
        agents = [s.agent for s in plan.steps]
        assert "sparql" in agents
        assert "sql" in agents
        assert "sensor_data" not in agents
        assert "capability" in agents

    def test_max_steps_enforced(self, planner):
        """Plans should be capped at MAX_STEPS."""
        many = [
            {"sub_query": f"task {i}", "intent": "analytics", "entities": []}
            for i in range(10)
        ]
        multi_plan = {"sub_intents": many, "primary_intent": "analytics"}
        plan = planner._build_from_multi_intent("query", multi_plan)
        assert len(plan.steps) <= planner.MAX_STEPS


# ── Section assembly ──────────────────────────────────────────────────

class TestSectionAssembly:
    def test_multi_section_output(self, planner):
        """Multi-intent assembly should produce ## headers with content."""
        sections = [
            {"agent": "analytics", "description": "temp check", "content": "Temperature is 22C"},
            {"agent": "anomaly", "description": "anomaly check", "content": "No anomalies found"},
            {"agent": "capability", "description": "contact", "content": "Contact: facilities@building.com"},
        ]
        plan = ExecutionPlan(
            user_query="test", steps=[], rationale="test", multi_intent=True
        )
        result = planner._assemble_multi_intent(plan, sections, [])

        assert result["success"] is True
        assert result["multi_intent"] is True
        assert "## Sensor Data Analysis" in result["formatted_response"]
        assert "## Anomaly Detection" in result["formatted_response"]
        assert "## Building Information" in result["formatted_response"]
        assert "22C" in result["formatted_response"]

    def test_empty_sections_skipped(self, planner):
        """Sections with no content should be omitted."""
        sections = [
            {"agent": "analytics", "description": "temp", "content": "Data here"},
            {"agent": "capability", "description": "contact", "content": ""},
        ]
        plan = ExecutionPlan(
            user_query="test", steps=[], rationale="test", multi_intent=True
        )
        result = planner._assemble_multi_intent(plan, sections, [])
        assert "## Building Information" not in result["formatted_response"]
        assert "## Sensor Data Analysis" in result["formatted_response"]

    def test_all_empty_returns_failure(self, planner):
        """If all sections are empty, return failure."""
        sections = [
            {"agent": "analytics", "description": "temp", "content": ""},
            {"agent": "capability", "description": "contact", "content": ""},
        ]
        plan = ExecutionPlan(
            user_query="test", steps=[], rationale="test", multi_intent=True
        )
        result = planner._assemble_multi_intent(plan, sections, [])
        assert result["success"] is False


# ── Content extraction ─────────────────────────────────────────────

class TestContentExtraction:
    def test_dict_with_formatted_response(self, planner):
        result = {"formatted_response": "Hello", "success": True}
        assert planner._extract_section_content("analytics", result) == "Hello"

    def test_dict_with_markdown(self, planner):
        result = {"markdown": "# Floor 3", "success": True}
        assert planner._extract_section_content("floor_plan", result) == "# Floor 3"

    def test_string_result(self, planner):
        assert planner._extract_section_content("spatial", "Room 3.01: 45 m²") == "Room 3.01: 45 m²"

    def test_none_result(self, planner):
        assert planner._extract_section_content("analytics", None) == ""


# ── _extract_sensor_metadata fix ─────────────────────────────────────

class TestExtractSensorMetadata:
    def test_extracts_uuid_label_mapping(self, planner):
        sparql_result = {
            "standardized": {
                "results": [
                    {"uuid": "uuid-1", "label": "Temp Sensor 1", "type": "Temperature"},
                    {"uuid": "uuid-2", "label": "CO2 Sensor 1", "type": "CO2"},
                    {"name": "no-uuid-entry"},
                ]
            }
        }
        metadata = planner._extract_sensor_metadata(sparql_result)
        assert "uuid-1" in metadata
        assert metadata["uuid-1"]["label"] == "Temp Sensor 1"
        assert "uuid-2" in metadata
        assert len(metadata) == 2

    def test_empty_sparql_result(self, planner):
        assert planner._extract_sensor_metadata({}) == {}
        assert planner._extract_sensor_metadata(None) == {}

    def test_non_dict_input(self, planner):
        assert planner._extract_sensor_metadata("not a dict") == {}


# ── Agent grouping constants ──────────────────────────────────────────

class TestAgentGroups:
    def test_data_pipeline_agents_defined(self):
        assert "analytics" in _DATA_PIPELINE_AGENTS
        assert "anomaly" in _DATA_PIPELINE_AGENTS
        assert "report" in _DATA_PIPELINE_AGENTS

    def test_standalone_agents_defined(self):
        assert "capability" in _STANDALONE_AGENTS
        assert "floor_plan" in _STANDALONE_AGENTS
        assert "spatial_query" in _STANDALONE_AGENTS

    def test_no_overlap(self):
        assert _DATA_PIPELINE_AGENTS.isdisjoint(_STANDALONE_AGENTS)
