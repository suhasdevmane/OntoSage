"""BUG-045 regression: sensor/equipment COUNT questions must route to metadata
(a SPARQL COUNT on the graph), not to spatial_query (DWG floor-plan geometry).

The LLM classification prompt used to map every "count" to spatial_query, so
"How many temperature sensors are there?" reached the spatial agent and returned
a room count. These tests exercise the deterministic guard in
DialogueAgent._parse_llm_response that corrects that class of misclassification,
while leaving genuine room-geometry questions on spatial_query.
"""

import json

import pytest

from orchestrator.agents.dialogue_agent import DialogueAgent

pytestmark = pytest.mark.unit


def _classify(agent: DialogueAgent, intent: str, query: str) -> str:
    """Run the raw LLM intent through _parse_llm_response's deterministic overrides."""
    raw = json.dumps({"intent": intent, "entities": [], "required_analytics": ["count"]})
    return agent._parse_llm_response(raw, query)["intent"]


@pytest.fixture(scope="module")
def agent() -> DialogueAgent:
    return DialogueAgent()


@pytest.mark.parametrize(
    "query",
    [
        "How many temperature sensors are there?",
        "How many CO2 sensors are there?",
        "Number of humidity sensors in the building?",
        "How many energy meters are installed?",
        "Count of occupancy sensors on floor 3?",  # 'floor' present but it's a sensor count
    ],
)
def test_sensor_count_forced_to_metadata_from_spatial(agent, query):
    """A sensor/equipment count the LLM mislabels spatial_query becomes metadata."""
    assert _classify(agent, "spatial_query", query) == "metadata"


def test_sensor_count_forced_to_metadata_from_floor_plan(agent):
    """Same correction when the LLM mislabels it floor_plan."""
    assert _classify(agent, "floor_plan", "How many temperature sensors are there?") == "metadata"


@pytest.mark.parametrize(
    "query",
    [
        "What is the area of floor 3?",
        "Which rooms are adjacent to 5.08?",
        "How big is the atrium?",
        "How many rooms are there?",  # room count -> room geometry, stays spatial
        "What are the room sizes on floor 2?",
    ],
)
def test_room_geometry_stays_spatial(agent, query):
    """Genuine room/space geometry questions are NOT hijacked to metadata."""
    assert _classify(agent, "spatial_query", query) == "spatial_query"


def test_non_count_sensor_query_unaffected(agent):
    """A sensor data question the LLM already labelled correctly is untouched."""
    assert _classify(agent, "sensor_data", "What is the temperature on floor 3?") == "sensor_data"
