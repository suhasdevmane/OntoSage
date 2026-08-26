# -*- coding: utf-8 -*-
"""A broken lift is not a slower way up — it is not a way up (V6-T58, 2026-08-26).

Step-free routing drops staircases, so an accessible route changes floors ONLY by lift.
That makes an out-of-service lift categorically different from a delay: it can remove
the only accessible route there is. Returning the route anyway, still labelled
accessible, would send someone who cannot use stairs to a floor they cannot reach —
the highest-consequence wrong answer this system can produce.

These tests use a synthetic two-floor fixture because the building this was developed
against types NO vertical circulation in its floor plans at all: 344 route nodes, zero
of type lift or staircase, and only 4 cross-floor edges, so floor 0 to floor 3 returns
no route by any method. That is a data gap logged separately; the routing behaviour is
still worth pinning, and a fixture is the only way to exercise it.
"""

import pytest

from orchestrator.services.route_finder import RouteFinder

pytestmark = pytest.mark.unit


class _Centroid:
    def __init__(self, x, y):
        self.x, self.y = x, y


class _Space:
    def __init__(self, zone_id, label, type_, adj, x=0.5, y=0.5):
        self.zone_id, self.label, self.type = zone_id, label, type_
        self.adjacent_spaces = list(adj)
        self.centroid = _Centroid(x, y)


class _Manifest:
    def __init__(self, floor, spaces):
        self.floor, self.spaces = floor, spaces
        self.bounding_box = {"width_m": 40.0, "height_m": 30.0}


def _two_floor_building():
    """Two floors joined ONLY by a lift core, plus a staircase on each floor."""
    f0 = [
        _Space("A0", "Room A0", "office", ["L0"], 0.1, 0.5),
        _Space("L0", "Main passenger lift", "lift", ["A0", "S0"], 0.5, 0.5),
        _Space("S0", "Stair 0", "staircase", ["L0"], 0.9, 0.5),
    ]
    f1 = [
        _Space("B1", "Room B1", "office", ["L1"], 0.1, 0.5),
        _Space("L1", "Main passenger lift", "lift", ["B1", "S1"], 0.5, 0.5),
        _Space("S1", "Stair 1", "staircase", ["L1"], 0.9, 0.5),
    ]
    return [_Manifest(0, f0), _Manifest(1, f1)]


def test_the_fixture_routes_between_floors_when_the_lift_works():
    rf = RouteFinder(_two_floor_building())
    assert rf.route("A0", "B1", step_free=True) is not None


def test_an_out_of_service_lift_removes_the_step_free_route():
    """Not a longer route — no route."""
    rf = RouteFinder(_two_floor_building())
    blocked = {"L0", "L1"}
    assert rf.route("A0", "B1", step_free=True, unavailable=blocked) is None


def test_the_stairs_route_still_exists_when_the_lift_is_out():
    """The honest answer is 'not step-free right now', not 'unreachable'."""
    rf = RouteFinder(_two_floor_building())
    assert rf.route("A0", "B1", step_free=False) is not None


def test_blocking_does_not_affect_same_floor_routes():
    rf = RouteFinder(_two_floor_building())
    assert rf.route("A0", "S0", step_free=False, unavailable={"L0", "L1"}) is None
    # A0 reaches S0 only through the lift, so that is correct; a direct pair is not.
    rf2 = RouteFinder(
        [
            _Manifest(
                0,
                [
                    _Space("X", "X", "office", ["Y"]),
                    _Space("Y", "Y", "office", ["X"]),
                    _Space("L0", "Main passenger lift", "lift", []),
                ],
            )
        ]
    )
    assert rf2.route("X", "Y", unavailable={"L0"}) is not None


def test_starting_inside_a_blocked_core_has_no_route():
    rf = RouteFinder(_two_floor_building())
    assert rf.route("L0", "B1", step_free=True, unavailable={"L0", "L1"}) is None


def test_nearest_search_also_honours_availability():
    rf = RouteFinder(_two_floor_building())
    with_lift = rf.nearest("A0", space_types={"office"}, step_free=True)
    without = rf.nearest("A0", space_types={"office"}, step_free=True, unavailable={"L0", "L1"})
    assert with_lift is not None
    # B1 is only reachable through the lift, so blocking it must not return B1.
    assert without is None or without.zone_id != "B1"


@pytest.mark.asyncio
async def test_availability_lookup_never_breaks_routing():
    """An availability lookup that errors must leave routing exactly as it was."""
    from orchestrator.services.asset_state_service import unavailable_vertical_nodes

    async def boom(_q):
        raise RuntimeError("graph down")

    rf = RouteFinder(_two_floor_building())
    out = await unavailable_vertical_nodes(rf.nodes, "b", "http://ns#", boom)
    assert out == {}


def test_the_route_lane_asks_for_availability_only_when_step_free():
    """Nothing but a step-free route can be blocked by a lift, so the lookup is not
    paid for on ordinary wayfinding."""
    import inspect

    from orchestrator.agents import spatial_agent

    src = inspect.getsource(spatial_agent)
    assert "_STEP_FREE_RE.search(query" in src
    assert "_blocked_vertical_nodes_for(manifests)" in src
