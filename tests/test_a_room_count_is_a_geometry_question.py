"""Counting rooms is a floor-plan question, not a sensor one (BUG-628).

"How many rooms are on floor 2?" was answered *"the building model doesn't keep a record of
how many rooms are on a specific floor"* — seconds after "What is the total area of floor 4?"
answered "1,149.0 m², 57 rooms" from the same manifests. The classifier had called it
`sensor_data`, and the rule that owns count questions correctly DECLINED it (a room count is
not a SPARQL census) without naming the lane that could answer.

Declining to force the wrong lane is not the same as naming the right one.
"""

import pytest

from orchestrator.services.routing_contract import apply_contract

pytestmark = pytest.mark.unit


def _route(query: str, intent: str = "sensor_data"):
    norm = {
        "intent": intent,
        "entities": [],
        "analytics": intent == "analytics",
        "general": intent == "general",
    }
    apply_contract(query, norm, stage="parse")
    return norm["intent"]


@pytest.mark.parametrize(
    "query",
    [
        "How many rooms are on floor 2?",
        "how many rooms does floor 3 have",
        "what is the number of spaces on the ground floor",
        "count the rooms on level 4",
        "How many meeting rooms are on floor 1?",
    ],
)
def test_a_room_count_goes_to_the_floor_plan_lane(query):
    assert _route(query) == "spatial_query"


@pytest.mark.parametrize(
    "query",
    [
        "How many sensors are there in total?",
        "how many CO2 sensors are on floor 2",
        "how many meters does the building have",
    ],
)
def test_a_device_count_is_still_a_graph_census(query):
    """The geometry rule must not swallow the census it was built alongside (BUG-045)."""
    assert _route(query) == "metadata"


def test_a_device_count_inside_a_room_is_not_claimed_as_geometry():
    """"How many devices are in room 5.01" names both a device and a room. The contract has
    never sent it to metadata (countable_metadata declines it for naming geometry), and this
    rule must not grab it either — a count of devices is not a count of rooms."""
    assert _route("how many devices are in room 5.01") != "spatial_query"


@pytest.mark.parametrize(
    "query",
    ["How many floors does this building have?", "how many levels are there"],
)
def test_a_structure_count_is_still_metadata(query):
    assert _route(query) == "metadata"


def test_a_reading_question_naming_a_room_is_untouched():
    """"room" appears here too; only a COUNT is claimed."""
    assert _route("What is the CO2 in room 5.01?") == "sensor_data"


def test_a_room_superlative_keeps_its_own_lane():
    """"Which room is the warmest right now?" is ranked from live readings (BUG-163). The
    word "room" must not pull it into the floor-plan lane."""
    assert _route("Which room is the warmest right now?") == "deliberate"


def test_the_rule_is_pinned_in_the_contract_order():
    """The contract applies every matching rule and the LAST wins, so the position is part
    of the behaviour, not a detail of the file."""
    from orchestrator.services.routing_contract import PARSE_STAGE_RULES

    names = [r.name for r in PARSE_STAGE_RULES]
    assert names.index("room_count_is_spatial") == names.index("countable_metadata") + 1
