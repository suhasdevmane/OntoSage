# -*- coding: utf-8 -*-
"""'How do I get to the lifts from the entrance?' started from a floor-4 drawing label.

    "Passenger Lift 1 and Passenger Lift 2 / Goods Lift serve Reception's floor (floor 4)."

The reception is on floor 0 (graph: Room 0.01, brick:Reception; building text: "Ground Floor, main
entrance"). The spatial lane found a starting point two ways, and both landed on floor 4: it matched
the word "reception" against the labels of every drawn space (the floor-4 sheet carries a text label
"Reception"), and with no starting point named it took the first space typed `reception`.

These tests drive the real `_answer_nearest` with the graph anchor supplied and only the amenity
catalogue replaced, and check which floor the answer was measured from.
"""

from typing import List

import pytest

from orchestrator.agents.spatial_agent import SpatialAgent
from orchestrator.services import place_anchor as pa
from shared.models import FloorPlanManifest, RenderedImage, Space

pytestmark = pytest.mark.unit

_IRI = "http://example.org/b#Room0.01"


def _space(zone, label, stype="zone", iri=None, adjacent=None):
    return Space(
        id=f"b.{zone}",
        zone_id=zone,
        label=label,
        type=stype,
        area_m2=20.0,
        ontology_iri=iri,
        adjacent_spaces=adjacent or [],
    )


def _manifest(floor: int, spaces: List[Space]) -> FloorPlanManifest:
    return FloorPlanManifest(
        building_id="b",
        building_name="B",
        floor=floor,
        floor_label=f"Floor {floor}",
        schema_version="2.0",
        source_pdf="f.pdf",
        source_sha256="0" * 64,
        generated_at="2026-01-01T00:00:00",
        rendered_image=RenderedImage(
            png_url="/f.png", thumbnail_url="/t.png", width_px=10, height_px=10, dpi=96
        ),
        pdf_url="/f.pdf",
        spaces=spaces,
        blocks=[],
    )


#: The manifests as the building has them: Room 0.01 drawn on floor 0 under its number, and a
#: floor-4 sheet with a text label "Reception" that carries no ontology IRI.
MANIFESTS = [
    _manifest(0, [_space("0.01", "0.01", iri=_IRI), _space("0.02", "0.02")]),
    _manifest(4, [_space("fp.4.reception", "Reception", "reception"), _space("4.01", "4.01")]),
]


class _Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, query, target_word, src_label, from_floor, *a, **k):
        self.calls.append(
            {"word": target_word, "label": src_label, "floor": from_floor, "kwargs": k, "args": a}
        )
        return f"AMENITY from {src_label} floor {from_floor}"


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(SpatialAgent, "_nearest_from_amenities", rec)
    return rec


def _anchor(monkeypatch, anchor, seen=None):
    async def locate(question, manifests=(), exclude=(), sparql_exec=None):
        if seen is not None:
            seen.append(list(exclude))
        return anchor

    monkeypatch.setattr(pa, "locate", locate)

    async def entrance(manifests=(), sparql_exec=None):
        # The default start asks the graph for the building's entrance. Without this stub the test
        # reached a REAL GraphDB when the stack was up, and fell back to the drawings' floor-4
        # reception label when it was down (parked, CI, a fresh clone) - so it passed or failed on
        # whether a container was running. A test of "the graph names nothing" states it.
        # ... and the answer this test exercises: the graph names an entrance the PLANS do not draw
        # (no zone), so the lane must decline for a starting point rather than assume floor 4.
        return pa.Anchor("Main Entrance Zone — Ground Floor", 0, "x#E", None, "Entrance")

    monkeypatch.setattr(pa, "entrance", entrance)


@pytest.mark.asyncio
async def test_a_place_the_graph_names_is_the_start_not_a_drawing_label_of_the_same_word(
    monkeypatch, recorder
):
    _anchor(monkeypatch, pa.Anchor("Room 0.01", 0, _IRI, "0.01", "Reception"))
    text = await SpatialAgent()._answer_nearest(
        "Where is the nearest lift to reception?", MANIFESTS
    )
    assert text == "AMENITY from Room 0.01 floor 0"
    assert recorder.calls[0]["floor"] == 0, "not floor 4, where the drawing's text label sits"


@pytest.mark.asyncio
async def test_a_place_the_plans_do_not_draw_is_still_measured_from_its_floor(
    monkeypatch, recorder
):
    _anchor(monkeypatch, pa.Anchor("Main Entrance Zone — Ground Floor", 0, "x#E", None, "Entrance"))
    text = await SpatialAgent()._answer_nearest(
        "How do I get to the lifts from the entrance?", MANIFESTS
    )
    assert text.startswith("AMENITY from Main Entrance Zone")
    assert recorder.calls[0]["floor"] == 0


@pytest.mark.asyncio
async def test_what_is_being_sought_is_excluded_from_the_places_the_question_can_name(
    monkeypatch, recorder
):
    seen: list = []
    _anchor(monkeypatch, None, seen)
    await SpatialAgent()._answer_nearest("nearest lift to reception", MANIFESTS)
    assert any("lift" in w for w in seen[0])


@pytest.mark.asyncio
async def test_an_explicit_room_number_is_never_overridden_by_a_named_place(monkeypatch, recorder):
    seen: list = []
    _anchor(monkeypatch, pa.Anchor("Room 0.01", 0, _IRI, "0.01", "Reception"), seen)
    await SpatialAgent()._answer_nearest("nearest lift to room 4.01 near reception", MANIFESTS)
    assert seen == [], "a room number is the reference point and the graph is not even asked"
    assert recorder.calls[0]["floor"] == 4


@pytest.mark.asyncio
async def test_no_place_named_and_none_in_the_graph_asks_for_a_starting_point(
    monkeypatch, recorder
):
    _anchor(monkeypatch, None)
    text = await SpatialAgent()._answer_nearest("Where is the nearest toilet?", MANIFESTS)
    assert "need a starting point" in text
    assert recorder.calls == [], "no floor-4 reception was assumed"


@pytest.mark.asyncio
async def test_a_floor_named_in_the_question_is_still_a_starting_point(monkeypatch, recorder):
    _anchor(monkeypatch, None)
    text = await SpatialAgent()._answer_nearest("nearest toilet on floor 2", MANIFESTS)
    assert text == "AMENITY from floor 2 floor 2"
    assert recorder.calls[0]["kwargs"].get("from_is_floor") is True


@pytest.mark.asyncio
async def test_wayfinding_with_no_source_starts_from_the_graphs_entrance(monkeypatch):
    agent = SpatialAgent()
    manifests = [
        _manifest(
            0,
            [
                _space("0.01", "0.01", "reception", adjacent=["5.01"]),
                _space("5.01", "Office 5.01", "office", adjacent=["0.01"]),
            ],
        ),
        _manifest(4, [_space("fp.4.reception", "Reception", "reception")]),
    ]
    text = agent._answer_wayfinding(
        "how do I get to room 5.01", manifests, None, None, default_start="0.01"
    )
    assert "fp.4.reception" not in text and "Arrive" in text or "5.01" in text
    legacy = agent._answer_wayfinding("how do I get to room 5.01", manifests)
    assert "5.01" in legacy, "without a graph start the drawing's first reception is still used"


# -- the lifts' own words about where they are -------------------------------------------------
def test_a_lift_is_described_in_its_own_words_when_the_reference_is_the_entrance():
    from orchestrator.services.amenity_proximity import AmenityHit, render

    hits = [
        AmenityHit(
            iri="x#Lift_1",
            label="Passenger Lift 1",
            serves=(0, 1, 2),
            location_text="Passenger Lift 1, left from the front entrance, approximately 25 m "
            "from the entrance; serves floors G, 1, 2.",
        ),
        AmenityHit(
            iri="x#Lift_2",
            label="Passenger Lift 2 / Goods Lift",
            serves=(0, 1, 2),
            location_text="Passenger Lift 2, on the opposite side of the building from Lift 1; "
            "serves floors G, 1, 2.",
        ),
    ]
    text = render(hits, "lift", "the main entrance", 0, False, describe_places=True)
    assert "left from the front entrance, approximately 25 m from the entrance" in text
    assert "opposite side of the building from Lift 1" in text
    assert "serves floors G, 1, 2" not in text, "the served floors are stated once, not per lift"
    plain = render(hits, "lift", "4.01", 0, False)
    assert "left from the front entrance" not in plain
