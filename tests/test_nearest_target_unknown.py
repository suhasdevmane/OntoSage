# -*- coding: utf-8 -*-
"""A nearest-question must never come back as a list of everything (BUG-377).

"Where's the nearest water refill station to Room 3.18?" returned **"## All spaces"** — a
whole-building inventory. The route question was understood; the amenity was not in
`_NEAREST_TARGETS`, so the nearest branch declined to claim it and the query fell past every
other branch to `_answer_list`, the default.

Wrong in SHAPE, not merely in content. The user asked where one thing is and got a list of
everything, which reads as an answer and is not one. A nearest-question now either locates
the thing or says it cannot — and says what it CAN locate, read from the building's own
manifests so a different building advertises its own amenities with no code change.
"""

import pytest

from orchestrator.agents.spatial_agent import SpatialAgent

pytestmark = pytest.mark.unit


class _Space:
    def __init__(self, space_type):
        self.space_type = space_type


class _Manifest:
    def __init__(self, types):
        self.spaces = [_Space(t) for t in types]


def _agent():
    return SpatialAgent.__new__(SpatialAgent)


MANIFESTS = [_Manifest(["toilet", "lift", "staircase", "meeting_room", "office"])]


def test_an_unknown_amenity_does_not_return_a_list_of_everything():
    out = _agent()._answer("where's the nearest water refill station to Room 3.18?", MANIFESTS)
    assert "All spaces" not in out
    assert "not one of them" in out


def test_it_names_what_it_can_actually_find():
    out = _agent()._answer("where is the nearest water refill station?", MANIFESTS)
    assert "toilet" in out and "meeting room" in out


def test_the_amenity_list_comes_from_the_building_not_a_constant():
    """A different building must advertise ITS amenities with no code change."""
    out = _agent()._answer(
        "where is the nearest water refill station?", [_Manifest(["prayer_room", "bike_store"])]
    )
    assert "prayer room" in out and "bike store" in out
    assert "toilet" not in out


def test_it_does_not_claim_the_building_lacks_the_amenity():
    """An unlabelled amenity is a gap in the plan, not a fact about the building."""
    out = _agent()._answer("where is the nearest water refill station?", MANIFESTS)
    assert "gap in the plan" in out


@pytest.mark.parametrize(
    "question",
    [
        "where is the nearest toilet?",
        "where's the closest lift?",
        "where is the nearest fire exit?",
    ],
)
def test_a_known_amenity_still_reaches_the_nearest_handler(question, monkeypatch):
    """The safety property: this must not swallow the questions that already worked."""
    agent = _agent()
    monkeypatch.setattr(agent, "_answer_nearest", lambda *a, **k: "NEAREST", raising=False)
    assert agent._answer(question, MANIFESTS) == "NEAREST"


def test_a_manifest_with_no_spaces_still_declines_cleanly():
    out = _agent()._answer("where is the nearest water refill station?", [_Manifest([])])
    assert "not one of them" in out
    assert "I can find the nearest:" not in out
