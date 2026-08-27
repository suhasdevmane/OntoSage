# -*- coding: utf-8 -*-
"""Cross-floor routing, when the plans do not draw the shaft (CAVEAT-313).

Measured on bldg1's live route graph: 344 nodes across 6 floors, twelve space
types, and ZERO typed lift or staircase. No node label mentioned a lift either.
Cross-floor edges numbered four in the whole building, and a route from floor 0
to floor 3 returned nothing at all -- with or without the step-free requirement.

The graph knew better the whole time: one ``ontosage:Lift`` ("Main passenger
lift") and two ``brick:Staircase``. The floor-plan pipeline simply never typed
the shafts, and the route finder can only see what the manifests say.

So the declared cores are read out of the ontology and attached to the route
graph. The POSITION is not invented -- a drawing that omits the shaft gives no
coordinate to be near -- so the node hangs off the floor's best-connected space,
and every route through one says so. An approximate route beats no route, but
only if the reader is told which it is.
"""

from types import SimpleNamespace as NS

import pytest

from orchestrator.services.route_finder import RouteFinder
from orchestrator.services.vertical_circulation import (
    VerticalCore,
    cores_from_rows,
    with_assumed_floors,
)

pytestmark = pytest.mark.unit


def _space(zid, label, typ, nbs):
    return NS(zone_id=zid, label=label, type=typ, centroid=None, adjacent_spaces=list(nbs))


def _plans():
    """Two floors with no vertical circulation drawn - bldg1's actual shape."""
    m0 = NS(
        floor=0,
        bounding_box={},
        spaces=[
            _space("z0a", "Reception", "reception", ["z0b"]),
            _space("z0b", "Corridor 0", "zone", ["z0a", "z0c"]),
            _space("z0c", "Office 0.1", "office", ["z0b"]),
        ],
    )
    m3 = NS(
        floor=3,
        bounding_box={},
        spaces=[
            _space("z3a", "Corridor 3", "zone", ["z3b"]),
            _space("z3b", "Lab 3.1", "lab", ["z3a"]),
        ],
    )
    return [m0, m3]


_LIFT = VerticalCore("ns#Lift_Main", "Main passenger lift", "lift", [0, 3])
_STAIR = VerticalCore("ns#Stair_A", "Stair A", "staircase", [0, 3])


# -- the defect --------------------------------------------------------------
def test_without_the_declared_lift_there_is_no_cross_floor_route():
    """The live behaviour being fixed: not a bad route, no route."""
    assert RouteFinder(_plans()).route("z0c", "z3b") is None


def test_the_declared_lift_makes_the_route_exist():
    rr = RouteFinder(_plans(), vertical_cores=[_LIFT]).route("z0c", "z3b")
    assert rr is not None
    assert rr.floors[0] == 0 and rr.floors[-1] == 3
    assert any("Main passenger lift" in lab for lab in rr.labels)


def test_the_route_says_the_shaft_position_is_approximate():
    """A route that silently invented a lift position would be the more confident
    kind of wrong."""
    rr = RouteFinder(_plans(), vertical_cores=[_LIFT]).route("z0c", "z3b")
    assert rr.approximate_vertical is True
    assert "do not draw" in rr.vertical_note


def test_a_route_that_never_changes_floor_is_not_labelled_approximate():
    rr = RouteFinder(_plans(), vertical_cores=[_LIFT]).route("z0a", "z0c")
    assert rr.approximate_vertical is False
    assert rr.vertical_note == ""


# -- accessibility still means what it meant ---------------------------------
def test_a_declared_lift_gives_a_step_free_route():
    assert RouteFinder(_plans(), vertical_cores=[_LIFT]).route("z0c", "z3b", step_free=True)


def test_a_declared_staircase_does_not():
    """Step-free routing drops staircases. A stair-only building must still answer
    that no step-free route exists, not route someone up the stairs."""
    rf = RouteFinder(_plans(), vertical_cores=[_STAIR])
    assert rf.route("z0c", "z3b") is not None
    assert rf.route("z0c", "z3b", step_free=True) is None


# -- a building whose plans DO draw their shafts learns nothing from here -----
def test_drawn_shafts_are_left_alone():
    """Real geometry beats a stand-in. A kind the manifests already type is skipped
    entirely, so a well-surveyed building keeps its own lift positions."""
    # Floors 1 and 2, because the existing cross-floor rule joins drawn shafts only
    # between CONSECUTIVE storeys (the same shaft drawn on each). The synthetic
    # chain is deliberately more permissive: a declared lift links the floors it
    # serves even where a manifest is missing in between.
    m1 = NS(
        floor=1,
        bounding_box={},
        spaces=[
            _space("z1a", "Corridor 1", "zone", ["z1b", "z1lift"]),
            _space("z1b", "Office 1.1", "office", ["z1a"]),
            _space("z1lift", "Lift 1", "lift", ["z1a"]),
        ],
    )
    m2 = NS(
        floor=2,
        bounding_box={},
        spaces=[
            _space("z2a", "Corridor 2", "zone", ["z2b", "z2lift"]),
            _space("z2b", "Lab 2.1", "lab", ["z2a"]),
            _space("z2lift", "Lift 2", "lift", ["z2a"]),
        ],
    )
    drawn = VerticalCore("ns#Lift_Main", "Main passenger lift", "lift", [1, 2])
    rf = RouteFinder([m1, m2], vertical_cores=[drawn])
    assert rf.inferred_vertical == set()
    rr = rf.route("z1b", "z2b")
    assert rr is not None and rr.approximate_vertical is False
    assert "Lift 1" in rr.labels


def test_no_declared_cores_changes_nothing():
    rf = RouteFinder(_plans(), vertical_cores=[])
    assert rf.inferred_vertical == set()
    assert rf.route("z0c", "z3b") is None


# -- attachment is deterministic ---------------------------------------------
def test_the_attachment_point_is_the_best_connected_space_and_is_stable():
    """A route that changes between runs is not a route. Highest degree, ties by
    zone_id: Corridor 0 has two neighbours where the others have one."""
    first = RouteFinder(_plans(), vertical_cores=[_LIFT]).route("z0c", "z3b")
    second = RouteFinder(_plans(), vertical_cores=[_LIFT]).route("z0c", "z3b")
    assert first.path == second.path
    assert "z0b" in first.path


# -- reading the ontology ----------------------------------------------------
def test_rows_group_into_one_core_per_shaft():
    rows = [
        {
            "c": "ns#Lift_Main",
            "label": "Main lift",
            "type": "http://ontosage.org/capabilities#Lift",
            "floor": "ns#Floor0",
        },
        {
            "c": "ns#Lift_Main",
            "label": "Main lift",
            "type": "http://ontosage.org/capabilities#Lift",
            "floor": "ns#Floor3",
        },
        {
            "c": "ns#Stair_A",
            "label": "Stair A",
            "type": "https://brickschema.org/schema/Brick#Staircase",
            "floor": "ns#Floor1",
        },
    ]
    cores = cores_from_rows(rows)
    assert [c.entity_id for c in cores] == ["ns#Lift_Main", "ns#Stair_A"]
    assert cores[0].kind == "lift" and cores[0].floors == [0, 3]
    assert cores[1].kind == "staircase"


def test_a_class_that_is_not_vertical_circulation_is_ignored():
    rows = [{"c": "ns#Room1", "type": "https://brickschema.org/schema/Brick#Room"}]
    assert cores_from_rows(rows) == []


def test_a_core_naming_no_floors_is_assumed_to_serve_all_and_says_so():
    """Usually right, and never reported as though the building had declared it."""
    (core,) = with_assumed_floors([VerticalCore("ns#L", "Lift", "lift")], [0, 1, 2])
    assert core.floors == [0, 1, 2]
    assert core.floors_assumed is True


def test_a_core_that_declares_its_floors_is_left_exactly_as_declared():
    (core,) = with_assumed_floors([VerticalCore("ns#L", "Lift", "lift", [0, 2])], [0, 1, 2])
    assert core.floors == [0, 2] and core.floors_assumed is False


def test_an_unparseable_floor_reference_does_not_invent_a_storey():
    """Picking a plausible number out of an unreadable string is how a route ends up
    claiming a lift stops somewhere it does not."""
    rows = [{"c": "ns#L", "type": "ontosage#Lift", "floor": "ns#BasementLevelUnknown"}]
    assert cores_from_rows(rows)[0].floors == []


# -- and the agent asks for them ---------------------------------------------
def test_the_spatial_agent_resolves_and_passes_the_cores():
    import inspect

    from orchestrator.agents import spatial_agent

    src = inspect.getsource(spatial_agent)
    assert "_declared_vertical_cores_for(manifests)" in src
    assert "RouteFinder(manifests, vertical_cores=vertical_cores)" in src


def test_a_synthetic_node_is_narrated_by_name_not_by_zone_id():
    """Without this the step read "Continue through vertical::Lift_Main::0" - the
    right route, narrated as gibberish."""
    import inspect

    from orchestrator.agents import spatial_agent

    src = inspect.getsource(spatial_agent)
    assert "_node.label if _node else zid" in src
