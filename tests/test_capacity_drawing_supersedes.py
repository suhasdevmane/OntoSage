# -*- coding: utf-8 -*-
"""Architect's-drawing capacities supersede the 2026-09-30 estimates (owner decision 2026-10-06).

Rooms 1.04, 4.01 and 5.01 carried estimated capacities. The building's own DXF drawings label
them with a seat/person count, and the drawings are authoritative for this building. Each room
now has a drawing record that ``ontosage:supersedes`` a retained estimate record, and the space
itself carries the drawing figure, which is the single value the design-occupancy reader sees.

The reader is exercised for real: ``design_occupancy._ALL_QUERY`` runs over an rdflib graph
built from the Brick TBox, the room typing and the capacity file, and the result goes through
``declared_design_occupancy`` unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rdflib
from rdflib.namespace import RDFS

from orchestrator.services import design_occupancy as dO

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
BLDG1 = ROOT / "bldg1"
CAPACITY_TTL = BLDG1 / "bldg1_occupancy_capacity.ttl"
METADATA_TTL = BLDG1 / "bldg1_abacws_metadata.ttl"
BRICK_TTL = BLDG1 / "Brick_v1.4.ttl"

HBCO = rdflib.Namespace("http://ontosage.org/hbco#")
ONT = rdflib.Namespace("http://ontosage.org/capabilities#")
BLDG = rdflib.Namespace("http://abacwsbuilding.cardiff.ac.uk/abacws#")

#: room -> (current figure from the drawing, drawing record, estimate record, estimate figure)
ROOMS = {
    "Room1.04": (30, "CapacityRecord_Room1.04_drawing", "CapacityRecord_Room1.04_estimate", 25),
    "Room4.01": (7, "CapacityRecord_Room4.01_drawing", "CapacityRecord_Room4.01_estimate", 20),
    "Room5.01": (8, "CapacityRecord_Room5.01_drawing", "CapacityRecord_Room5.01_estimate", 20),
}


@pytest.fixture(scope="module")
def capacity_graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(CAPACITY_TTL, format="turtle")
    return g


@pytest.fixture(scope="module")
def reader_graph() -> rdflib.Graph:
    """The graph the reader's query runs over: TBox, room typing and the capacity file."""
    g = rdflib.Graph()
    g.parse(BRICK_TTL, format="turtle")
    g.parse(METADATA_TTL, format="turtle")
    g.parse(CAPACITY_TTL, format="turtle")
    return g


def _run_reader_query(g: rdflib.Graph) -> dict:
    """Execute the reader's own SPARQL and shape the rows as a SPARQL JSON payload."""
    query = dO._ALL_QUERY.format(brick=dO._BRICK, rdfs=dO._RDFS, terms=dO._terms_for_sparql())
    bindings = []
    for row in g.query(query):
        out = {
            "space": {"value": str(row.space)},
            "p": {"value": str(row.p)},
            "v": {"value": str(row.v)},
        }
        if row.label is not None:
            out["label"] = {"value": str(row.label)}
        bindings.append(out)
    return {"results": {"bindings": bindings}}


def _exec_over(g: rdflib.Graph):
    async def run(_query):
        return _run_reader_query(g)

    return run


# ── (a) the TTL parses ───────────────────────────────────────────────────────


def test_capacity_ttl_parses(capacity_graph):
    assert len(capacity_graph) > 0


# ── (b) the reader resolves the drawing figure ───────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("room", sorted(ROOMS))
async def test_reader_returns_drawing_figure(reader_graph, room):
    expected, *_ = ROOMS[room]
    declared = await dO.declared_design_occupancy(_exec_over(reader_graph))
    space_iri = str(BLDG[room])
    entry = declared.get(space_iri)
    assert entry is not None, f"{room} not read by the design-occupancy reader"
    assert entry.conflicted is False
    assert entry.value == expected


@pytest.mark.asyncio
async def test_reader_does_not_see_superseded_estimates(reader_graph):
    """The retained estimates must not reach the space-level reader as extra values."""
    declared = await dO.declared_design_occupancy(_exec_over(reader_graph))
    for room, (_, _, _, old) in ROOMS.items():
        entry = declared[str(BLDG[room])]
        assert old not in entry.values, f"{room} still exposes superseded figure {old}"


def test_space_carries_exactly_one_capacity_value(capacity_graph):
    for room, (expected, *_) in ROOMS.items():
        values = list(capacity_graph.objects(BLDG[room], HBCO.roomCapacity))
        assert len(values) == 1, f"{room} has {len(values)} roomCapacity values"
        assert int(values[0]) == expected


# ── (c) superseded records are still present ─────────────────────────────────


@pytest.mark.parametrize("room", sorted(ROOMS))
def test_estimate_record_is_retained(capacity_graph, room):
    _, drawing, estimate, old = ROOMS[room]
    est = BLDG[estimate]
    assert (est, HBCO.roomCapacity, rdflib.Literal(old)) in capacity_graph
    assert (est, RDFS.seeAlso, BLDG[room]) in capacity_graph
    assert (BLDG[drawing], ONT.supersedes, est) in capacity_graph


@pytest.mark.parametrize("room", sorted(ROOMS))
def test_drawing_record_carries_the_drawing_figure_and_provenance(capacity_graph, room):
    expected, drawing, _, _ = ROOMS[room]
    node = BLDG[drawing]
    assert (node, HBCO.roomCapacity, rdflib.Literal(expected)) in capacity_graph
    basis = str(next(capacity_graph.objects(node, ONT.capacityBasis)))
    assert "drawing" in basis and ".dxf" in basis and "owner decision" in basis


# ── (d) no supersedes cycle, and the chain resolves to the drawing ───────────


def test_supersedes_has_no_cycle(capacity_graph):
    edges = {}
    for s, o in capacity_graph.subject_objects(ONT.supersedes):
        edges.setdefault(s, []).append(o)
    for start in edges:
        seen = set()
        frontier = [start]
        while frontier:
            node = frontier.pop()
            for nxt in edges.get(node, []):
                assert nxt != start, f"supersedes cycle through {start}"
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)


def test_current_record_is_not_superseded(capacity_graph):
    superseded = set(capacity_graph.objects(None, ONT.supersedes))
    for _, drawing, _, _ in ROOMS.values():
        assert BLDG[drawing] not in superseded
