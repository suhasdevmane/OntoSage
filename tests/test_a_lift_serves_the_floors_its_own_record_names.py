# -*- coding: utf-8 -*-
"""'Where is the nearest lift to Room 4.01?' said 3 floors down, and listed two non-lifts (BUG-827).

    "There is no lift recorded on 4.01's floor. The nearest is Passenger Lift 1 -- 3 floors down.
     Also recorded: Passenger Lift 2 / Goods Lift, Accessibility, Lift Accessibility Detail."

Three separate faults, one answer:

1. The floor of "Passenger Lift 1" was read from the trailing digit of its LABEL, so the lift
   numbered 1 was placed on floor 1. A lift stands in one place and SERVES floors, and the building's
   own record says which: "serves floors G, 1, 2, 3, 4 and 5". That is now `ontosage:servesFloor`.
2. "Accessibility" and "Lift Accessibility Detail" are paragraphs of prose typed only as
   ontosage:Amenity. Their lay terms contain "lift", so they were listed as lifts.
3. A lift that is out of service was offered as the nearest.

The spatial lane also passed the BUILDING's namespace where the query wanted the ontosage one, so the
class filter matched nothing and every amenity looked untyped.
"""

import pytest

from orchestrator.services.amenity_proximity import (
    AmenityHit,
    floor_number,
    nearest_by_floor,
    render,
)

pytestmark = pytest.mark.unit

_NS = "http://ontosage.org/capabilities#"
_B = "http://example.org/b#"


def _exec(rows, seen=None):
    async def run(q):
        if seen is not None:
            seen.append(q)
        return {
            "results": {
                "bindings": [
                    {k: {"value": v} for k, v in r.items() if v not in (None, "")} for r in rows
                ]
            }
        }

    return run


def _lift(n, serves, status="", label=None):
    return {
        "a": f"{_B}Lift_{n}",
        "label": label or f"Passenger Lift {n}",
        "lays": "lift, elevator",
        "classes": f"{_NS}Lift",
        "serves": " ".join(f"{_B}Floor{f}" for f in serves),
        "service_status": status,
    }


_TOPICS = [
    # A reasoner adds ontosage:Capability to every amenity, so a topic's `classes` is not empty --
    # it is generic, and generic is not a kind.
    {
        "a": f"{_B}Cap_accessibility",
        "label": "Accessibility",
        "lays": "wheelchair, lift, elevator",
        "classes": f"{_NS}Capability",
    },
    {
        "a": f"{_B}Cap_lift_accessibility_detail",
        "label": "Lift Accessibility Detail",
        "lays": "lift accessibility",
        "classes": f"{_NS}Capability",
    },
]

_LIFTS = [_lift(1, range(0, 6)), _lift(2, range(0, 6), label="Passenger Lift 2 / Goods Lift")]


# -- 1. a label's trailing digit is not a floor -------------------------------------------------
@pytest.mark.asyncio
async def test_the_number_in_a_lifts_name_is_not_the_floor_it_stands_on():
    hits = await nearest_by_floor(_exec(_LIFTS), _NS, ["lift"], from_floor=4)
    by_label = {h.label: h for h in hits}
    assert by_label["Passenger Lift 1"].floor == ""
    assert by_label["Passenger Lift 1"].floor_no is None


@pytest.mark.asyncio
async def test_a_lift_reaches_every_floor_its_own_record_says_it_serves():
    hits = await nearest_by_floor(_exec(_LIFTS), _NS, ["lift"], from_floor=4)
    assert all(h.reaches(4) and h.gap_to(4) == 0 for h in hits)
    assert hits[0].serves == (0, 1, 2, 3, 4, 5)


@pytest.mark.asyncio
async def test_the_answer_says_both_lifts_serve_the_asked_floor_and_not_that_one_is_nearer():
    hits = await nearest_by_floor(_exec(_LIFTS + _TOPICS), _NS, ["lift"], from_floor=4)
    text = render(hits, "lift", "4.01", 4, False)
    assert "Passenger Lift 1" in text and "Passenger Lift 2 / Goods Lift" in text
    assert "serve 4.01's floor (floor 4)" in text
    assert "3 floors down" not in text and "no lift recorded" not in text
    assert "cannot say which is nearer" in text
    assert "not a surveyed route" in text


@pytest.mark.asyncio
async def test_a_lift_that_does_not_serve_the_floor_is_the_nearest_by_floors_served():
    rows = [_lift(1, [0, 1, 2])]
    hits = await nearest_by_floor(_exec(rows), _NS, ["lift"], from_floor=5)
    text = render(hits, "lift", "5.01", 5, False)
    assert "There is no lift recorded on 5.01's floor." in text
    assert "3 floors down" in text


# -- 2. a topic is not an instance --------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_paragraph_of_prose_is_not_listed_among_the_lifts():
    hits = await nearest_by_floor(_exec(_LIFTS + _TOPICS), _NS, ["lift"], from_floor=4)
    assert {h.label for h in hits} == {"Passenger Lift 1", "Passenger Lift 2 / Goods Lift"}
    text = render(hits, "lift", "4.01", 4, False)
    assert "Accessibility" not in text and "Detail" not in text


@pytest.mark.asyncio
async def test_an_amenity_with_only_a_floor_is_still_an_instance():
    rows = [
        {"a": f"{_B}x", "label": "Kiosk", "lays": "lift", "floor": "Floor2"},
    ]
    hits = await nearest_by_floor(_exec(rows), _NS, ["lift"], from_floor=2)
    assert len(hits) == 1 and hits[0].floor_no == 2


# -- 3. the nearest is the nearest that works ---------------------------------------------------
@pytest.mark.asyncio
async def test_an_out_of_service_lift_is_named_and_never_offered_as_the_nearest():
    rows = [
        _lift(1, [0], status="out_of_service"),
        {
            "a": f"{_B}Lift_9",
            "label": "Platform lift",
            "lays": "lift",
            "classes": f"{_NS}Lift",
            "floor": "Floor1",
            "service_status": "operational",
        },
    ]
    hits = await nearest_by_floor(_exec(rows), _NS, ["lift"], from_floor=0)
    text = render(hits, "lift", "0.01", 0, False)
    assert "serves 0.01's floor" not in text, "a broken lift was offered as the way to this floor"
    assert "The nearest is Platform lift — 1 floor up" in text
    assert "Currently out of service: Passenger Lift 1" in text


@pytest.mark.asyncio
async def test_when_everything_recorded_is_out_of_service_the_answer_says_so():
    rows = [_lift(1, [0, 1], status="out_of_service")]
    hits = await nearest_by_floor(_exec(rows), _NS, ["lift"], from_floor=1)
    text = render(hits, "lift", "1.01", 1, False)
    assert "currently out of service" in text.lower()
    assert "serves 1.01's floor" in text


# -- the namespace the caller passes -----------------------------------------------------------
@pytest.mark.asyncio
async def test_the_class_filter_uses_the_ontosage_namespace_whatever_the_caller_passes():
    seen = []
    await nearest_by_floor(_exec(_LIFTS, seen), "http://a-building#", ["lift"], from_floor=1)
    assert 'STRSTARTS(STR(?cls), "http://ontosage.org/capabilities#")' in seen[0]
    assert "http://a-building#" not in seen[0]
    assert "o:servesFloor" in seen[0]


# -- asking about a floor rather than a room ---------------------------------------------------
@pytest.mark.asyncio
async def test_a_question_that_names_a_floor_is_answered_about_that_floor():
    rows = [
        {
            "a": f"{_B}wc4",
            "label": "Accessible WC - Floor 4",
            "lays": "accessible toilet",
            "located": f"{_B}Floor4",
            "classes": f"{_NS}AccessibilityFeature",
            "acc_verified": "true",
        },
    ]
    hits = await nearest_by_floor(
        _exec(rows), _NS, ["toilet", "wc"], from_floor=1, accessible_only=True
    )
    text = render(hits, "toilet", "floor 1", 1, True, from_is_floor=True)
    assert "There is no accessible toilet recorded on floor 1." in text
    assert "floor 1's floor" not in text
    assert "3 floors up" in text


def test_a_label_that_says_floor_n_is_a_floor_but_one_that_ends_in_a_number_is_not():
    from orchestrator.services.amenity_proximity import _floor_text

    assert _floor_text("", "", "Accessible WC - Floor 4 (Fourth Floor)") == "Floor4"
    assert _floor_text("", "", "Passenger Lift 1") == ""
    assert _floor_text("", f"{_B}Floor4", "x") == f"{_B}Floor4"
    assert _floor_text("", f"{_B}Room4.44", "x") == ""
    assert _floor_text("Floor2", f"{_B}Room4.44", "x") == "Floor2"


def test_floor_numbers_are_still_read_from_declared_floors():
    assert floor_number("Floor3") == 3 and floor_number("Ground") is None
    hit = AmenityHit(iri="x#a", label="a", floor="Floor4")
    assert hit.floor_no == 4 and hit.gap_to(1) == 3


def test_a_location_the_label_already_names_is_not_repeated():
    from orchestrator.services.amenity_proximity import _where

    generated = AmenityHit(
        iri="x#a", label="Toilet facility — Room 3.02 — Lab", location=f"{_B}Room3.02"
    )
    assert _where(generated) == ""
    unlabelled = AmenityHit(iri="x#b", label="Accessible WC", location=f"{_B}Room3.02")
    assert _where(unlabelled) == " in Room3.02"
    assert _where(AmenityHit(iri="x#c", label="Kiosk")) == ""
