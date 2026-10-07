"""E6 — the capacity authority order is TTL, then the drawing, then none (owner decision 2026-10-07).

The owner's binding rule:

  * when the building's TTL holds a capacity figure for a space, that figure is authoritative;
  * the drawing-derived figure is a SECOND source, used only when the TTL holds no figure for it;
  * otherwise the answer is "none";
  * never an average, and never "the larger value".

Before E6 the reader took whatever figure sat on the space, the drawing figure had been written
onto the room node itself, and the drawing records were not read at all. These tests pin the
order where it is decided (``authoritative_capacity``) and then against the real bldg1 TTL, so a
future edit that lets a drawing outrank the model, or averages two figures, goes red.

No room number or capacity value is written into code here except as test fixture data for the
synthetic cases; the real-building cases read the TTL.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rdflib

from orchestrator.services import design_occupancy as dO

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
BLDG1 = ROOT / "bldg1"
CAPACITY_TTL = BLDG1 / "bldg1_occupancy_capacity.ttl"
METADATA_TTL = BLDG1 / "bldg1_abacws_metadata.ttl"
BRICK_TTL = BLDG1 / "Brick_v1.4.ttl"

BLDG = rdflib.Namespace("http://abacwsbuilding.cardiff.ac.uk/abacws#")
HBCO = rdflib.Namespace("http://ontosage.org/hbco#")
ONT = rdflib.Namespace("http://ontosage.org/capabilities#")
BRICK = rdflib.Namespace("https://brickschema.org/schema/Brick#")
RDFS = rdflib.Namespace("http://www.w3.org/2000/01/rdf-schema#")

TTL_KEY = "http://ontosage.org/hbco#roomCapacity"


# ── the decision itself, on synthetic figures ──────────────────────────────────────────────────


def test_ttl_outranks_a_drawing_that_disagrees():
    got = dO.authoritative_capacity({"ttl": 25}, {"drawing": 30})
    assert (got.value, got.source, got.unresolved) == (25, "ttl", False)


def test_the_larger_figure_does_not_win_when_the_ttl_is_smaller():
    got = dO.authoritative_capacity({"ttl": 7}, {"drawing": 30})
    assert got.value == 7 and got.source == "ttl"


def test_the_drawing_is_used_only_when_the_ttl_has_no_figure():
    got = dO.authoritative_capacity({}, {"drawing": 30})
    assert (got.value, got.source) == (30, "drawing")


def test_no_figure_in_either_source_is_none_not_zero():
    got = dO.authoritative_capacity({}, {})
    assert got.value is None and got.source == "" and got.unresolved is False


def test_two_ttl_figures_with_no_supersedes_link_are_unresolved_not_averaged_or_maxed():
    got = dO.authoritative_capacity({"a": 20, "b": 40}, {})
    assert got.value is None
    assert got.unresolved is True
    assert got.source == "ttl"


def test_a_ttl_figure_that_supersedes_another_wins_and_is_not_a_disagreement():
    got = dO.authoritative_capacity(
        {"current": 20, "retired": 50},
        {},
        {"current": "retired"},
    )
    assert (got.value, got.source, got.unresolved) == (20, "ttl", False)


def test_a_third_figure_no_link_explains_keeps_the_answer_unresolved():
    """A supersedes link settles only the record it names. An unrelated disagreeing figure
    must not be waved through because the winner happens to supersede something."""
    got = dO.authoritative_capacity(
        {"current": 20, "retired": 50, "stray": 35},
        {},
        {"current": "retired"},
    )
    assert got.value is None and got.unresolved is True


def test_the_order_does_not_depend_on_insertion_order():
    forward = dO.authoritative_capacity({"a": 20, "b": 40}, {})
    backward = dO.authoritative_capacity({"b": 40, "a": 20}, {})
    assert forward == backward


def test_the_drawing_never_joins_a_ttl_tie():
    """A drawing that agrees with one of two disagreeing TTL figures must not settle them."""
    got = dO.authoritative_capacity({"a": 20, "b": 40}, {"drawing": 40})
    assert got.value is None and got.unresolved is True and got.source == "ttl"


# ── the real bldg1 TTL, read through the real reader ───────────────────────────────────────────

#: 2026-10-07, second owner decision: these three rooms' TTL figures were reconciled to the
#: architect's drawing figures (7/30/8), which is WHY the next test below no longer asserts a
#: disagreement for them -- the synthetic test_ttl_outranks_a_drawing_that_disagrees above
#: already covers the general mechanism; this dict just has to track whatever bldg1's TTL says.
ROOMS = {"Room1.04": 30, "Room4.01": 7, "Room5.01": 8}


def _payload(g: rdflib.Graph, query: str) -> dict:
    bindings = []
    result = g.query(query)
    for row in result:
        out = {}
        for var in result.vars:
            term = row[var]
            if term is not None:
                out[str(var)] = {"value": str(term)}
        bindings.append(out)
    return {"results": {"bindings": bindings}}


def _exec_over(g: rdflib.Graph):
    async def run(query: str):
        return _payload(g, query)

    return run


@pytest.fixture(scope="module")
def bldg1_graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(BRICK_TTL, format="turtle")
    g.parse(METADATA_TTL, format="turtle")
    g.parse(CAPACITY_TTL, format="turtle")
    return g


@pytest.mark.asyncio
@pytest.mark.parametrize("room", sorted(ROOMS))
async def test_the_building_model_figure_is_what_the_reader_answers_with(bldg1_graph, room):
    declared = await dO.declared_design_occupancy(_exec_over(bldg1_graph))
    entry = declared[str(BLDG[room])]
    assert entry.source == "ttl"
    assert entry.conflicted is False
    assert entry.value == ROOMS[room]


@pytest.mark.asyncio
@pytest.mark.parametrize("room", sorted(ROOMS))
async def test_a_drawing_figure_on_file_is_read_but_never_overrides_the_ttl_source(
    bldg1_graph, room
):
    """2026-10-07: these three rooms' TTL figures were reconciled to equal their drawing
    figures (the owner's second decision), so bldg1's real graph can no longer demonstrate a
    DISAGREEING drawing -- that general case is `test_ttl_outranks_a_drawing_that_disagrees`
    above, on synthetic figures. What the real graph still proves: a drawing record exists and
    is READ (entry.drawing is populated), but the winning ``source`` is always "ttl", never
    "drawing", even when the two numbers now happen to match -- the authority order is not
    merely coincidentally right here, it is still TTL-first by construction."""
    declared = await dO.declared_design_occupancy(_exec_over(bldg1_graph))
    entry = declared[str(BLDG[room])]
    assert entry.drawing, f"{room} has a drawing record on file"
    assert entry.source == "ttl"


# ── a space with NO model figure falls through to its drawing ──────────────────────────────────


def _drawing_only_graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.add((BRICK.Room, RDFS.subClassOf, BRICK.Location))
    space = BLDG["SyntheticSpace"]
    g.add((space, rdflib.RDF.type, BRICK.Room))
    g.add((space, RDFS.label, rdflib.Literal("Synthetic space")))
    record = BLDG["SyntheticSpace_drawing"]
    g.add((record, RDFS.seeAlso, space))
    g.add((record, HBCO.roomCapacity, rdflib.Literal(12)))
    g.add((record, ONT.capacitySource, rdflib.Literal("drawing")))
    return g


@pytest.mark.asyncio
async def test_a_space_with_only_a_drawing_figure_is_answered_from_the_drawing():
    declared = await dO.declared_design_occupancy(_exec_over(_drawing_only_graph()))
    entry = declared[str(BLDG["SyntheticSpace"])]
    assert (entry.value, entry.source, entry.conflicted) == (12, "drawing", False)


@pytest.mark.asyncio
async def test_a_space_with_no_figure_anywhere_is_none():
    g = rdflib.Graph()
    g.add((BRICK.Room, RDFS.subClassOf, BRICK.Location))
    g.add((BLDG["Bare"], rdflib.RDF.type, BRICK.Room))
    declared = await dO.declared_design_occupancy(_exec_over(g))
    assert str(BLDG["Bare"]) not in declared


@pytest.mark.asyncio
async def test_a_failed_graph_query_is_not_read_as_no_figure():
    async def boom(_query):
        raise RuntimeError("graph unreachable")

    assert await dO.declared_design_occupancy(boom) == {}


# ── the TTL carries the figures the order needs (populated with their reader) ──────────────────


def test_the_building_model_figure_is_on_the_room_and_the_drawing_is_a_separate_record(
    bldg1_graph,
):
    for room, figure in ROOMS.items():
        on_room = list(bldg1_graph.objects(BLDG[room], HBCO.roomCapacity))
        assert [int(v) for v in on_room] == [figure], room


@pytest.mark.parametrize("room", sorted(ROOMS))
def test_the_estimate_supersedes_the_retired_figure_and_both_are_retained(bldg1_graph, room):
    estimate = BLDG[f"CapacityRecord_{room}_estimate"]
    retired = BLDG[f"CapacityRecord_{room}_retired"]
    assert (estimate, ONT.supersedes, retired) in bldg1_graph
    assert (retired, ONT.capacitySource, rdflib.Literal("ttl")) in bldg1_graph
    assert (estimate, ONT.capacitySource, rdflib.Literal("ttl")) in bldg1_graph


@pytest.mark.parametrize("room", sorted(ROOMS))
def test_the_drawing_record_is_tagged_as_a_drawing_and_supersedes_nothing(bldg1_graph, room):
    """Owner decision 2026-10-07: a drawing is a second source and does not replace the TTL,
    so no drawing record may carry a supersedes link. (Pre-E6 the drawing superseded the
    estimate; that link is removed and this test pins its absence.)"""
    drawing = BLDG[f"CapacityRecord_{room}_drawing"]
    assert (drawing, ONT.capacitySource, rdflib.Literal("drawing")) in bldg1_graph
    assert list(bldg1_graph.objects(drawing, ONT.supersedes)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("room", sorted(ROOMS))
async def test_a_superseded_figure_is_never_offered_as_a_live_value(bldg1_graph, room):
    """The retired figure is retained in the graph (for audit) but a reader must not see it:
    ``values`` is the one list a recipe or narration is built from."""
    declared = await dO.declared_design_occupancy(_exec_over(bldg1_graph))
    entry = declared[str(BLDG[room])]
    assert entry.values == [ROOMS[room]]
    assert str(BLDG[f"CapacityRecord_{room}_retired"]) in entry.declarations


def test_no_supersedes_cycle_in_the_capacity_records(bldg1_graph):
    edges: dict = {}
    for s, o in bldg1_graph.subject_objects(ONT.supersedes):
        edges.setdefault(s, []).append(o)
    for start in edges:
        frontier, seen = [start], set()
        while frontier:
            for nxt in edges.get(frontier.pop(), []):
                assert nxt != start, f"supersedes cycle through {start}"
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)


def test_the_tier_for_each_source_is_the_one_the_precedence_module_ranks():
    """The TTL is ``authoritative`` and a drawing is ``document_derived`` (E4's tiers)."""
    from orchestrator.services.evidence.precedence import RANK

    assert RANK["authoritative"] > RANK["document_derived"]


def test_precedence_settles_the_estimate_over_the_retired_figure_by_supersedes():
    """The E4 same-tier path, exercised with the real TTL shape: a current record that
    supersedes a retired one wins and is not reported as a disagreement."""
    from orchestrator.services.evidence.precedence import SourceClaim, resolve

    claims = [
        SourceClaim("bldg:CapacityRecord_Room4.01_retired", "authoritative", 25.0),
        SourceClaim(
            "bldg:CapacityRecord_Room4.01_estimate",
            "authoritative",
            20.0,
            supersedes="bldg:CapacityRecord_Room4.01_retired",
        ),
    ]
    verdict = resolve(claims)
    assert verdict.winner.value == 20.0
    assert verdict.tiebreak == "supersedes"
