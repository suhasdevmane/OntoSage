"""Unit test for SpatialAgent floor inference (N3 over-answering fix).

"How many meeting rooms on floor 4?" must scope to floor 4, not aggregate
across every floor. The agent infers the floor from the query when the caller
did not pin floor_context, but stays building-wide when zero or multiple
floors are named.
"""

import pytest

from orchestrator.agents.spatial_agent import SpatialAgent

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "query,expected",
    [
        ("how many meeting rooms on floor 4?", 4),
        ("total area of floor 3", 3),
        ("rooms on level 2", 2),
        ("floor 0 room count", 0),
        ("how many offices in the building", None),  # no floor → all floors
        ("compare floor 1 and floor 5", None),  # ambiguous → all floors
        ("list all rooms", None),
        ("", None),
    ],
)
def test_infer_floor_from_query(query, expected):
    assert SpatialAgent._infer_floor_from_query(query) == expected
