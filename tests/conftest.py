"""
conftest.py — Shared pytest fixtures for OntoSage
==================================================
Provides reusable fixtures available to all test modules.
"""

import os
import sys

import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.fixtures.ontology_fixtures import (
    brick_fixture,
    mock_anomalous_readings,
    mock_sensor_readings,
    mock_sparql_result,
    mock_sql_result,
    rec_fixture,
    s223_fixture,
)


@pytest.fixture
def brick_graph():
    """Parsed rdflib Graph with Brick v1.3 mock building."""
    return brick_fixture()


@pytest.fixture
def rec_graph():
    """Parsed rdflib Graph with REC 3.3 mock building."""
    return rec_fixture()


@pytest.fixture
def s223_graph():
    """Parsed rdflib Graph with ASHRAE 223P mock system."""
    return s223_fixture()


@pytest.fixture
def normal_readings():
    """50 normal temperature readings (21–24°C)."""
    return mock_sensor_readings("uuid-temp-101", n=50)


@pytest.fixture
def anomalous_readings():
    """20 readings with injected spike (35°C at index 5) and cold (8°C at index 10)."""
    return mock_anomalous_readings(n=20)


@pytest.fixture
def sql_result():
    """Typical SQLAgent result with 30 sensor readings."""
    return mock_sql_result("uuid-temp-101", n=30)


@pytest.fixture
def sparql_result():
    """Typical SPARQLAgent result for Air_Temperature_Sensor_1_01."""
    return mock_sparql_result("Air_Temperature_Sensor_1_01")


@pytest.fixture
def mock_state():
    """Minimal ConversationState mock."""
    from unittest.mock import MagicMock

    state = MagicMock()
    state.conversation_id = "test-conv-001"
    state.user_id = "test-user"
    state.messages = [MagicMock(content="test query", role="user")]
    state.current_intent = "analytics"
    state.analytics_required = False
    state.needs_clarification = False
    state.query_results = {}
    state.intermediate_results = {}
    state.persona = "general"
    return state


@pytest.fixture
def building_config(tmp_path):
    """Write a minimal building_config.yaml to a temp dir and return its path."""
    cfg_content = """
building:
  id: test_bldg
  name: Test Building
  namespace: "http://test.building.local/mock#"
  prefix: bldg
  timezone: Europe/London
  abox_file: data/test_abox.ttl
  tbox_file: data/Brick.ttl
ontology:
  schema: brick
  schema_uri: https://brickschema.org/schema/Brick#
  extra_prefixes: []
storage:
  backend: mysql
  database: test_db
  table: sensor_data
  columns:
    uuid: uuid
    value: value
    timestamp: time
    sensor_name: sensor_name
"""
    cfg_file = tmp_path / "test_building_config.yaml"
    cfg_file.write_text(cfg_content)
    return str(cfg_file)
