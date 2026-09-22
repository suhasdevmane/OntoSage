# -*- coding: utf-8 -*-
"""The amenity and room answers must reach the lanes that used to give the wrong ones (BUG-827, 810).

A module that answers correctly and is called by nobody is the failure this project has met before:
the unit tests pass and the user sees the old answer. Each test here drives the REAL lane -- the
capability node, the spatial agent, the floor-plan agent -- with only its data sources replaced, and
checks what the reader would have seen.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

import orchestrator.agents.capability_agent as cap
import orchestrator.services.building_context as bctx
import orchestrator.services.building_metrics as bmmod
import orchestrator.services.capability_graph_resolver as cgr
import orchestrator.services.room_type_lookup as rtl
from orchestrator.services.capability_graph_resolver import CapabilityFact
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

_LAYS = "toilet, toilets, washroom, restroom, bathroom"


def _toilet(floor, room, **kw) -> CapabilityFact:
    return CapabilityFact(
        label=f"Toilet facility — {room}",
        location=f"Toilet facility in {room} (floor {floor})",
        on_floor=f"Floor{floor}",
        lay_terms=_LAYS,
        **kw,
    )


def _state(message: str) -> ConversationState:
    return ConversationState(
        conversation_id="wired-1",
        user_id="u",
        user_message=message,
        building_id="bldgX",
        current_intent="capability",
        messages=[Message(role="user", content=message)],
    )


def _wire(monkeypatch, live: List[CapabilityFact], withheld: List[CapabilityFact]) -> None:
    monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name="Test"))

    class _Metrics:
        async def snapshot(self, _bid, namespace=None):
            return bmmod.BuildingMetricsSnapshot()

    monkeypatch.setattr(bmmod, "get_building_metrics", lambda: _Metrics())

    class _Resolver:
        async def resolve(self, _q):
            return list(live)

        async def resolve_with_withheld(self, _q):
            return list(live), list(withheld)

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())

    async def _no_docs(*_a, **_k):
        return []

    monkeypatch.setattr(cap, "_search_documents", _no_docs)

    async def _no_rooms(_q, only=None):
        return None

    monkeypatch.setattr(rtl, "answer_live", _no_rooms)


async def _ask(question: str) -> str:
    out = await cap.CapabilityAgent().answer(_state(question))
    return out.intermediate_results["capability_result"]["response"]


# -- the capability lane: a floor named in the question ----------------------------------------
@pytest.mark.asyncio
async def test_toilets_on_floor_2_says_the_one_on_floor_2_is_out_of_service(monkeypatch):
    """The reported defect, end to end: floors 0, 1 and 3 listed, floor 2 never mentioned."""
    live = [_toilet(0, "Room 0.04"), _toilet(1, "Room 1.07"), _toilet(3, "Room 3.02")]
    _wire(monkeypatch, live, [_toilet(2, "Room 2.02", service_status="out_of_service")])
    text = await _ask("Where are the toilets on floor 2?")
    assert "Nothing recorded on floor 2 is currently in service" in text
    assert "Out of service: Toilet facility — Room 2.02" in text
    assert "Room 1.07" in text and "Room 3.02" in text
    assert "Room 0.04" not in text, "the nearest are floors 1 and 3, one away each"
    assert "Here is what I found" not in text


@pytest.mark.asyncio
async def test_toilets_on_a_floor_that_has_some_lists_that_floor(monkeypatch):
    """Every toilet the building records on the asked-for floor, and no other floor's first.

    CHANGED BY D1 (2026-09-22). A fourth record here -- a toilet in a Research Laboratory -- used
    to be suppressed because it was generated and the floor also held surveyed ones. No record
    declares an origin now, so all of that floor's records are listed.

    A toilet recorded in a laboratory is a DATA defect and is fixed in the TTL, not hidden by a
    filter: bldg1's placeholder toilets were replaced with the surveyed provision for exactly that
    reason. What this still guards is the scope -- floor 2's records answer a floor 2 question, and
    another floor's appear only under "Also recorded"."""
    live = [
        _toilet(1, "Room 1.07"),
        _toilet(2, "Room 2.35 — Restroom (Male)"),
        _toilet(2, "Room 2.36 — Restroom (Female)"),
    ]
    _wire(monkeypatch, live, [])
    text = await _ask("Where are the toilets on floor 2?")
    assert "Room 2.35" in text and "Room 2.36" in text
    assert "Room 1.07" not in text.split("Also recorded")[0]


@pytest.mark.asyncio
async def test_a_question_that_names_no_floor_is_answered_as_before(monkeypatch):
    _wire(monkeypatch, [_toilet(1, "Room 1.07"), _toilet(3, "Room 3.02")], [])
    text = await _ask("Where are the toilets?")
    assert "Here is what I found" in text and "Room 1.07" in text


@pytest.mark.asyncio
async def test_a_plumbing_question_that_merely_names_toilets_is_not_answered_as_a_floor_list(
    monkeypatch,
):
    """BUG-601's guard must still hold: a topic answers only the question it is about."""
    live = [_toilet(2, "Room 2.35"), _toilet(3, "Room 3.02")]
    _wire(monkeypatch, live, [])
    text = await _ask("Where can I isolate the water supply for the toilets on the second floor?")
    assert "On floor 2" not in text and "Room 2.35" not in text


# -- the capability lane: a kind of room -------------------------------------------------------
@pytest.mark.asyncio
async def test_the_capability_lane_answers_which_rooms_from_the_room_records(monkeypatch):
    _wire(monkeypatch, [], [])

    async def _rooms(q, only=None):
        return "**10 rooms are recorded as Computer Laboratory**" if "laborator" in q else None

    monkeypatch.setattr(rtl, "answer_live", _rooms)
    out = await cap.CapabilityAgent().answer(_state("Which rooms are computer laboratories?"))
    res = out.intermediate_results["capability_result"]
    assert res["provenance"] == "room_records"
    assert "10 rooms are recorded as Computer Laboratory" in res["response"]


def test_the_resolver_hands_back_what_it_withheld():
    import inspect

    src = inspect.getsource(cgr.CapabilityGraphResolver.resolve)
    assert "withheld_out.append(_to_fact(am))" in src
    assert hasattr(cgr.CapabilityGraphResolver, "resolve_with_withheld")


@pytest.mark.asyncio
async def test_a_resolver_that_hands_back_the_withheld_ones_reports_them():
    class _Rows:
        def __init__(self, floor, status):
            self.floor, self.status = floor, status

    def row(iri, floor, status=""):
        b = {
            "a": {"value": iri},
            "label": {"value": f"Toilet facility {iri}"},
            "lay": {"value": "toilet, toilets"},
            "floor": {"value": f"Floor{floor}"},
            "cat": {"value": "AMENITIES"},
        }
        if status:
            b["svc"] = {"value": status}
        return b

    async def fake_exec(q):
        if "subClassOf" in q:
            return {"results": {"bindings": []}}
        return {
            "results": {
                "bindings": [
                    row("x#t1", 1),
                    row("x#t2", 2, "out_of_service"),
                    row("x#t2", 2, "out_of_service"),  # the same amenity twice: one answer
                ]
            }
        }

    resolver = cgr.CapabilityGraphResolver(fake_exec)
    kept, withheld = await resolver.resolve_with_withheld("where are the toilets")
    assert [f.on_floor for f in kept] == ["Floor1"]
    assert [f.on_floor for f in withheld] == ["Floor2"], "one amenity, listed once"
    assert withheld[0].service_status == "out_of_service"


@pytest.mark.asyncio
async def test_the_same_amenity_is_never_answered_twice():
    """'Where are the lifts?' printed the first lift twice (two status rows for one amenity)."""

    def row(status_iri):
        return {
            "a": {"value": "x#Lift_1"},
            "label": {"value": "Passenger Lift 1"},
            "lay": {"value": "lift, elevator"},
            "svc": {"value": "operational"},
            "st": {"value": status_iri},
        }

    async def fake_exec(q):
        if "subClassOf" in q:
            return {"results": {"bindings": []}}
        return {"results": {"bindings": [row("x#status_a"), row("x#status_b")]}}

    facts = await cgr.CapabilityGraphResolver(fake_exec).resolve("where is the lift")
    assert [f.label for f in facts] == ["Passenger Lift 1"]


@pytest.mark.asyncio
async def test_a_safety_critical_flag_is_not_stacked_on_the_cached_note():
    """The out-of-service flag was written onto the CACHED amenity, so every call within five
    minutes prepended another copy to the note."""

    async def fake_exec(q):
        if "subClassOf" in q:
            return {"results": {"bindings": []}}
        return {
            "results": {
                "bindings": [
                    {
                        "a": {"value": "x#aed"},
                        "label": {"value": "Defibrillator"},
                        "lay": {"value": "defibrillator"},
                        "cat": {"value": "Safety"},
                        "svc": {"value": "out_of_service"},
                    }
                ]
            }
        }

    resolver = cgr.CapabilityGraphResolver(fake_exec)
    await resolver.resolve("where is the defibrillator")
    facts = await resolver.resolve("where is the defibrillator")
    assert facts[0].note.count("Currently out of service") == 1


# -- the spatial lane ------------------------------------------------------------------------------
def _plans():
    def sp(zone, area, stype="zone", label=None):
        return SimpleNamespace(
            zone_id=zone,
            label=label or zone,
            area_m2=area,
            type=stype,
            ontology_iri="",
            adjacent_spaces=[],
            aliases=[],
        )

    return [
        SimpleNamespace(
            floor=0, floor_label="Ground", spaces=[sp("0.01", 184.5), sp("0.02", 20.0)]
        ),
        SimpleNamespace(floor=1, floor_label="One", spaces=[sp("1.01", 201.2), sp("1.02", 5.5)]),
    ]


@pytest.mark.asyncio
async def test_the_spatial_lane_ranks_the_biggest_room_instead_of_listing_every_space():
    from orchestrator.agents.spatial_agent import SpatialAgent

    text = await SpatialAgent()._answer("What's the biggest room in the building?", _plans())
    assert text.startswith("**The largest room in the building by floor-plan area is Room 1.01**")
    assert "All spaces" not in text and "|" not in text


@pytest.mark.asyncio
async def test_a_size_filter_still_lists_what_matches_it():
    from orchestrator.agents.spatial_agent import SpatialAgent

    text = await SpatialAgent()._answer("rooms larger than 100 m2", _plans())
    assert "0.01" in text and "1.01" in text and "largest" not in text


@pytest.mark.asyncio
async def test_a_nearest_question_that_names_a_floor_uses_it_as_the_starting_point(monkeypatch):
    """'Where is the nearest accessible toilet on floor 1?' asked for a starting point."""
    import orchestrator.services.deliberation.live as live
    from orchestrator.agents.spatial_agent import SpatialAgent

    async def fake_exec(_q):
        return {
            "results": {
                "bindings": [
                    {
                        "a": {"value": "x#access_accessible_wc_0"},
                        "label": {"value": "Accessible WC - Floor 0 (Ground Floor)"},
                        "located": {"value": "x#Floor0"},
                        "lays": {"value": "accessible toilet"},
                        "classes": {
                            "value": "http://ontosage.org/capabilities#AccessibilityFeature"
                        },
                        "acc_verified": {"value": "true"},
                    }
                ]
            }
        }

    monkeypatch.setattr(live, "sparql_exec", fake_exec)
    text = await SpatialAgent()._answer(
        "Where is the nearest accessible toilet on floor 1?", _plans()
    )
    assert "need a starting point" not in text
    assert "There is no accessible toilet recorded on floor 1." in text
    assert "1 floor down" in text


@pytest.mark.asyncio
async def test_a_nearest_question_with_no_floor_and_no_room_still_asks_for_a_starting_point():
    from orchestrator.agents.spatial_agent import SpatialAgent

    text = await SpatialAgent()._answer("Where is the nearest toilet?", _plans())
    assert "need a starting point" in text


# -- the floor-plan lane ----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_which_floor_is_the_server_room_on_reaches_the_room_records(monkeypatch):
    from orchestrator.agents.floor_plan_agent import FloorPlanAgent

    seen: Dict[str, Any] = {}

    async def _floors(q, only=None):
        seen["only"] = only
        return "**The building records a Server Room on floors 2, 4 and 5:**"

    monkeypatch.setattr(rtl, "answer_live", _floors)
    result = await FloorPlanAgent().resolve("Which floor is the server room on?", _state("x"))
    assert "Server Room on floors 2, 4 and 5" in result.markdown
    assert seen["only"] == "floors", "'show me the meeting rooms' must still get the drawing"


@pytest.mark.asyncio
async def test_the_floor_menu_is_still_the_answer_when_the_room_records_have_nothing(monkeypatch):
    from orchestrator.agents.floor_plan_agent import FloorPlanAgent

    async def _nothing(q, only=None):
        return None

    monkeypatch.setattr(rtl, "answer_live", _nothing)
    result = await FloorPlanAgent().resolve("Which floor is the server room on?", _state("x"))
    assert "Server Room on floors" not in result.markdown


# -- wayfinding to a KIND of place ("how do I get to the lifts?") ------------------------------
@pytest.mark.asyncio
async def test_how_do_i_get_to_the_lifts_is_the_nearest_lift_question_not_a_request_for_a_room(
    monkeypatch,
):
    """BUG-810: 'How do I get to the lifts from the entrance?' asked for a room number."""
    from orchestrator.agents.spatial_agent import SpatialAgent

    async def _nearest(self, query, manifests, cores=None):
        return "NEAREST"

    monkeypatch.setattr(SpatialAgent, "_answer_nearest", _nearest)
    monkeypatch.setattr(SpatialAgent, "_answer_wayfinding", lambda *a, **k: "WAYFINDING")
    agent = SpatialAgent()
    assert (
        await agent._answer("How do I get to the lifts from the entrance?", _plans()) == "NEAREST"
    )
    # a named room is still a route
    assert await agent._answer("how do I get to room 5.01 from reception", _plans()) == "WAYFINDING"
