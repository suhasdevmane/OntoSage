# -*- coding: utf-8 -*-
""""The area of room 0.34" must reach the named-space handler.

The area lane was gated on floor-shaped phrasings only -- "total area",
"area ... floor", "size of floor". A question about ONE room therefore never
reached the handler written for exactly that case, and fell through to the
honest-no-data reply while the manifest held the room's 195 m2. A false "I don't
have that" is worse than a wrong number in one respect: it tells the user to go
add data that is already there.
"""

import pytest

from orchestrator.agents.spatial_agent import _AREA_GT_RE, _AREA_LT_RE, _AREA_QUERY_RE

pytestmark = pytest.mark.unit


def _routes_to_area_lane(q: str) -> bool:
    """Mirror the call-site condition exactly, guards included."""
    return bool(
        _AREA_QUERY_RE.search(q) and not _AREA_GT_RE.search(q) and not _AREA_LT_RE.search(q)
    )


@pytest.mark.parametrize(
    "q",
    [
        "What is the area of room 0.34?",
        "what's the area of 0.01",
        "How big is room 0.34?",
        "How large is the lecture theatre?",
        "what is the size of room 0.17",
        "what are the dimensions of room 0.10",
        "what is the perimeter of room 0.34",
        "how much floor space does room 0.04 have",
    ],
)
def test_named_space_area_questions_reach_the_area_lane(q):
    assert _routes_to_area_lane(q), q


@pytest.mark.parametrize(
    "q",
    [
        "What is the total area of floor 0?",
        "area of floor 3",
        "size of floor 2",
    ],
)
def test_floor_scoped_area_questions_still_reach_the_area_lane(q):
    assert _routes_to_area_lane(q), q


@pytest.mark.parametrize(
    "q",
    [
        "Which rooms are larger than 20 m2?",
        "list spaces with an area of more than 50 m2",
        "rooms smaller than 10 m2",
        "which offices have a size of less than 15 m2",
    ],
)
def test_filter_questions_are_left_to_the_filter_lane(q):
    """Widening the gate must not steal queries from the >/< comparison lane."""
    assert not _routes_to_area_lane(q), q
