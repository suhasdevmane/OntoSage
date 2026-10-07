"""E6 — the architect's drawings for Rooms 1.04, 4.01 and 5.01, and how the TTL records them.

Measured 2026-10-06, three sources disagreed:

  * bldg1/bldg1_occupancy_capacity.ttl — hbco:roomCapacity 25 / 20 / 20, the live figures.
  * the same file's capacityBasis text — the superseded maxOccupancy 50 / 25 / 25, retired by
    BUG-896 and now kept as retained TTL records.
  * the architect's drawings — bldg1/Abacws floor N.dxf carries a "NP <function>" label next
    to each room tag, on layer A-AREA-IDEN. Nearest label to 1.04 is "30P Seminar" (floor 1),
    to 4.01 "7P PHD Research" (floor 4), to 5.01 "8P PHD Research" (floor 5).

CHANGED 2026-10-07 (owner decision, binding). The 2026-10-06 decision made the drawings
authoritative and wrote 30 / 7 / 8 onto the rooms. That is REVERSED: the TTL figure is
authoritative whenever the TTL holds one, and the drawing is a second source read only when it
holds none. The three rooms all hold a TTL figure, so the drawing figures are retained as records
and answer nothing today. The pins below were updated to the new order; the reason is the
owner's decision, not a change in the drawing evidence, which the DXF test still checks.

The TTL-level pins are on the figures and their records. The order itself is pinned in
``test_capacity_authority_order.py``.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
import rdflib
from rdflib.namespace import RDFS

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
BLDG1 = ROOT / "bldg1"
ROOM_TAGS = {"1.04": "floor 1", "4.01": "floor 4", "5.01": "floor 5"}
EXPECTED_DRAWING_CAPACITY = {"1.04": 30, "4.01": 7, "5.01": 8}
#: The figure the TTL holds for each room under the 2026-10-07 order.
EXPECTED_TTL_CAPACITY = {"1.04": 25, "4.01": 20, "5.01": 20}
LABEL_RE = re.compile(r"^(\d+)P\b")

HBCO = rdflib.Namespace("http://ontosage.org/hbco#")
ONT = rdflib.Namespace("http://ontosage.org/capabilities#")
BLDG = rdflib.Namespace("http://abacwsbuilding.cardiff.ac.uk/abacws#")


def _dxf_texts(path: Path):
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    out = []
    for i in range(len(lines) - 1):
        if lines[i] == "0" and lines[i + 1] == "TEXT":
            x = y = value = None
            j = i + 2
            while j < len(lines) - 1 and lines[j] != "0":
                code, val = lines[j], lines[j + 1]
                if code == "10" and x is None:
                    x = float(val)
                elif code == "20" and y is None:
                    y = float(val)
                elif code == "1" and value is None:
                    value = val
                j += 2
            if x is not None and value is not None:
                out.append((value, x, y))
    return out


def _nearest_capacity_label(path: Path, tag: str):
    items = _dxf_texts(path)
    tx, ty = next((x, y) for v, x, y in items if v == tag)
    labels = sorted(
        ((math.hypot(x - tx, y - ty), v) for v, x, y in items if LABEL_RE.match(v)),
    )
    return labels[0], labels[1]


@pytest.fixture(scope="module")
def capacity_graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(BLDG1 / "bldg1_occupancy_capacity.ttl", format="turtle")
    return g


@pytest.mark.parametrize("room", sorted(ROOM_TAGS))
def test_drawing_label_next_to_the_room_tag_is_the_capacity_it_states(room):
    dxf = BLDG1 / f"Abacws {ROOM_TAGS[room]}.dxf"
    if not dxf.exists():
        pytest.skip("drawing not present in this checkout")
    (dist, label), (second_dist, _) = _nearest_capacity_label(dxf, room)
    # The label is unambiguous: the nearest is well inside its room and the next is several
    # times further away. Without that margin the figure could belong to the neighbour.
    assert dist < 1500, f"{room}: nearest label is {dist:.0f} units away"
    assert second_dist > 3 * dist, f"{room}: label is ambiguous ({dist:.0f} vs {second_dist:.0f})"
    assert int(LABEL_RE.match(label).group(1)) == EXPECTED_DRAWING_CAPACITY[room]


@pytest.mark.parametrize("room", sorted(ROOM_TAGS))
def test_the_room_carries_the_ttl_figure_not_the_drawing_figure(capacity_graph, room):
    """Owner decision 2026-10-07: the TTL figure is authoritative. The drawing figure must not
    be written onto the room, where it would silently replace the building's own figure."""
    values = [int(v) for v in capacity_graph.objects(BLDG[f"Room{room}"], HBCO.roomCapacity)]
    assert values == [EXPECTED_TTL_CAPACITY[room]]
    assert EXPECTED_DRAWING_CAPACITY[room] not in values


@pytest.mark.parametrize("room", sorted(ROOM_TAGS))
def test_the_drawing_is_retained_as_a_second_source_record(capacity_graph, room):
    drawing = BLDG[f"CapacityRecord_Room{room}_drawing"]
    assert (drawing, HBCO.roomCapacity, rdflib.Literal(EXPECTED_DRAWING_CAPACITY[room])) in (
        capacity_graph
    )
    assert (drawing, ONT.capacitySource, rdflib.Literal("drawing")) in capacity_graph
    assert (drawing, RDFS.seeAlso, BLDG[f"Room{room}"]) in capacity_graph


@pytest.mark.parametrize("room", sorted(ROOM_TAGS))
def test_the_estimate_is_the_current_ttl_record_and_supersedes_the_retired_figure(
    capacity_graph, room
):
    estimate = BLDG[f"CapacityRecord_Room{room}_estimate"]
    retired = BLDG[f"CapacityRecord_Room{room}_retired"]
    assert (estimate, HBCO.roomCapacity, rdflib.Literal(EXPECTED_TTL_CAPACITY[room])) in (
        capacity_graph
    )
    assert (estimate, ONT.supersedes, retired) in capacity_graph
    assert (retired, ONT.capacitySource, rdflib.Literal("ttl")) in capacity_graph


def test_the_drawing_basis_names_the_dxf_and_the_label_it_read(capacity_graph):
    for room, drawing in (("1.04", 30), ("4.01", 7), ("5.01", 8)):
        basis = str(
            next(
                capacity_graph.objects(
                    BLDG[f"CapacityRecord_Room{room}_drawing"], ONT.capacityBasis
                )
            )
        )
        assert ".dxf" in basis and f"{drawing}P" in basis, room
        assert "second source" in basis.lower(), room
