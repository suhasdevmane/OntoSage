# -*- coding: utf-8 -*-
"""The non-substitution rule (V6-T13, Master Report 8, acceptance scenario 1).

The case that matters is not "the room does not exist" -- the referent gate already handles
that -- but **the room exists, a sensor of the right kind exists, just not in that room**.
That is the one the supervisors test hardest, and the one that actually happens on a real
building with partial coverage.

Two properties are load-bearing and both are asserted below:

* a declared ``environmentalBoundary`` pointing at a DIFFERENT space is decisive in the
  negative -- containment must not rescue it, or a duct sensor becomes room evidence;
* nothing in the module may depend on distance. Proximity is not evidence of what a sensor
  measures, and allowing it to imply attribution is how BUG-189 attributed a room's reading
  to a corridor that did not exist.
"""

from pathlib import Path

import pytest

from orchestrator.services.evidence.spatial_adequacy import (
    PointFacts,
    best_verdict,
    classify,
    is_permitted,
)
from shared.models import SpatialAdequacy

pytestmark = pytest.mark.unit

ROOM = "http://x/Room2.15"
CORRIDOR = "http://x/Corridor2"
OTHER = "http://x/Room2.16"


# ── in-room ──────────────────────────────────────────────────────────────────


def test_sensor_inside_the_room_is_in_room():
    v = classify(ROOM, PointFacts("p1", containing_space=ROOM))
    assert v.grade is SpatialAdequacy.IN_ROOM
    assert v.is_room_level


def test_declared_environmental_boundary_wins_over_containment():
    """A duct or plenum sensor SITS in one space and MEASURES another.

    This is the entire reason environmentalBoundary exists; if containment could override
    it, the property would be decorative.
    """
    v = classify(ROOM, PointFacts("p1", environmental_boundary=ROOM, containing_space=CORRIDOR))
    assert v.grade is SpatialAdequacy.IN_ROOM


def test_boundary_naming_another_space_is_decisive_against_in_room():
    """The dangerous direction: physically inside the room, but measuring the corridor.

    Containment must NOT rescue this. If it did, a sensor explicitly declared as measuring
    somewhere else would still carry a room-level claim.
    """
    v = classify(ROOM, PointFacts("p1", environmental_boundary=CORRIDOR, containing_space=ROOM))
    assert v.grade is SpatialAdequacy.PROXY
    assert not v.is_room_level
    assert "Corridor2" in v.reason


# ── served zones ─────────────────────────────────────────────────────────────


def test_validated_served_zone_counts_as_room_level():
    """The single alternative to an in-room sensor the Master Report permits."""
    v = classify(ROOM, PointFacts("p1", containing_space=CORRIDOR, validated_zone_spaces=(ROOM,)))
    assert v.grade is SpatialAdequacy.SERVED_ZONE
    assert v.is_room_level


def test_unvalidated_served_zone_is_only_proxy():
    """Fails closed. An unvalidated zone silently trusted is a substitution wearing a label."""
    v = classify(ROOM, PointFacts("p1", containing_space=CORRIDOR, unvalidated_zone_spaces=(ROOM,)))
    assert v.grade is SpatialAdequacy.PROXY
    assert not v.is_room_level
    assert "not validated" in v.reason


# ── proxy and none ───────────────────────────────────────────────────────────


def test_corridor_sensor_is_proxy_and_names_where_it_actually_is():
    """The answer has to be able to say WHICH proxy, or it cannot explain the limitation."""
    v = classify(ROOM, PointFacts("p1", containing_space=CORRIDOR))
    assert v.grade is SpatialAdequacy.PROXY
    assert "Corridor2" in v.reason
    assert v.evidence_space == CORRIDOR


def test_unrelated_sensor_is_none():
    v = classify(ROOM, PointFacts("p1"))
    assert v.grade is SpatialAdequacy.NONE


def test_empty_target_space_is_none_not_a_guess():
    assert classify("", PointFacts("p1", containing_space=ROOM)).grade is SpatialAdequacy.NONE


# ── choosing between candidates ──────────────────────────────────────────────


def test_best_verdict_prefers_the_in_room_sensor_over_a_corridor_one():
    """Order of arrival is a property of the SPARQL query, not of the building.

    If first-wins, an answer's quality would depend on result ordering.
    """
    corridor_first = [
        PointFacts("corridor", containing_space=CORRIDOR),
        PointFacts("inroom", containing_space=ROOM),
    ]
    assert best_verdict(ROOM, corridor_first).grade is SpatialAdequacy.IN_ROOM
    assert best_verdict(ROOM, list(reversed(corridor_first))).grade is SpatialAdequacy.IN_ROOM


def test_tie_between_equal_grades_is_broken_deterministically():
    """Order-independence must hold WITHIN a grade too, not only across grades.

    Two proxies in different spaces have no principled ranking -- the only thing that could
    separate them is distance, which this module refuses to consider. So the tie is broken by
    point identity, because the alternative is that the answer depends on SPARQL result
    ordering, silently. (The first implementation had exactly that defect; it surfaced as
    acceptance scenario 1 naming a neighbouring ROOM instead of the corridor.)
    """
    cands = [
        PointFacts("p-b", containing_space="http://x/RoomB"),
        PointFacts("p-a", containing_space=CORRIDOR),
    ]
    forward = best_verdict(ROOM, cands)
    reverse = best_verdict(ROOM, list(reversed(cands)))
    assert forward.evidence_space == reverse.evidence_space


def test_a_proxy_reason_never_claims_nearness():
    """The module has no notion of distance, so its text must not imply one.

    'The nearest reading is from X' is an unsupported spatial assertion inside the very
    sentence whose job is to be precise about spatial support.
    """
    v = classify(ROOM, PointFacts("p1", containing_space=CORRIDOR))
    assert "nearest" not in v.reason
    assert "not the space asked about" in v.reason


def test_best_verdict_of_nothing_is_none():
    assert best_verdict(ROOM, []).grade is SpatialAdequacy.NONE


def test_validated_zone_beats_proxy_but_loses_to_in_room():
    cands = [
        PointFacts("proxy", containing_space=CORRIDOR),
        PointFacts("zone", containing_space=OTHER, validated_zone_spaces=(ROOM,)),
    ]
    assert best_verdict(ROOM, cands).grade is SpatialAdequacy.SERVED_ZONE
    cands.append(PointFacts("inroom", containing_space=ROOM))
    assert best_verdict(ROOM, cands).grade is SpatialAdequacy.IN_ROOM


# ── policy integration ───────────────────────────────────────────────────────


def test_policy_forbids_a_proxy_carrying_a_room_level_answer():
    from orchestrator.services.evidence import load_policy

    allowed = load_policy("any").allowed_adequacy("space")
    assert is_permitted(SpatialAdequacy.IN_ROOM, "space", allowed)
    assert is_permitted(SpatialAdequacy.SERVED_ZONE, "space", allowed)
    assert not is_permitted(SpatialAdequacy.PROXY, "space", allowed)


def test_policy_allows_a_proxy_for_a_building_wide_question():
    """A building-scope question may legitimately rest on partial coverage."""
    from orchestrator.services.evidence import load_policy

    allowed = load_policy("any").allowed_adequacy("building")
    assert is_permitted(SpatialAdequacy.PROXY, "building", allowed)


# ── the invariant that must never be relaxed ─────────────────────────────────


def test_module_has_no_notion_of_distance():
    """Proximity is not evidence of what a sensor measures; ductwork is.

    A distance field would invite the exact inference this module exists to prevent, so its
    absence is a property worth pinning rather than a coincidence of the current design.
    """
    from scripts.check_building_literals import _prose_lines

    path = (
        Path(__file__).resolve().parent.parent
        / "orchestrator"
        / "services"
        / "evidence"
        / "spatial_adequacy.py"
    )
    src = path.read_text(encoding="utf-8")
    # Strip docstrings and comments properly. The module PROSE necessarily discusses
    # distance -- it explains why distance is excluded -- so a raw substring search would
    # fail here and push a maintainer to delete the explanation to green the test. (This
    # test made exactly that mistake on its first run, for the third time in this session;
    # the lesson is that "search the source" nearly always means "search the EXECUTABLE
    # source".)
    prose = _prose_lines(src)
    code = "\n".join(line for n, line in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for banned in ("distance", "proximity", "nearest_m", "metres", "euclid"):
        assert banned not in code, f"spatial adequacy must not consider {banned}"


def test_fields_are_all_asserted_facts():
    """No derived or computed geometry may enter PointFacts."""
    assert set(PointFacts.__dataclass_fields__) == {
        "point_iri",
        "environmental_boundary",
        "containing_space",
        "validated_zone_spaces",
        "unvalidated_zone_spaces",
        "sibling_spaces",
    }
