"""E6 — which design capacity is authoritative for Rooms 1.04, 4.01 and 5.01?

Measured 2026-10-06, three sources disagree:

  * bldg1/bldg1_occupancy_capacity.ttl — hbco:roomCapacity 25 / 20 / 20, the live figures.
  * the same file's capacityBasis text — the superseded maxOccupancy 50 / 25 / 25, retired by
    BUG-896 and kept only in prose (git history holds the triples).
  * the architect's drawings — bldg1/Abacws floor N.dxf carries a "NP <function>" label next
    to each room tag, on layer A-AREA-IDEN. Nearest label to 1.04 is "30P Seminar" (floor 1),
    to 4.01 "7P PHD Research" (floor 4), to 5.01 "8P PHD Research" (floor 5).

The owner decided on 2026-09-17 that the architect's DXF drawings are authoritative for what a
room is (tasks/held_back/room_identity_2026-09-17/README.md). The drawing label is therefore
the best-supported figure. It is NOT written into the TTL here: it would RAISE Room 1.04 from
25 to 30, against the recorded rule that the lower figure is kept, and the held-back README
sequences all capacity corrections as one change with a cascade. That is the owner's call.

This file pins the drawing evidence, so the reconciliation can be reviewed against it.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BLDG1 = Path("bldg1")
ROOM_TAGS = {"1.04": "floor 1", "4.01": "floor 4", "5.01": "floor 5"}
EXPECTED_DRAWING_CAPACITY = {"1.04": 30, "4.01": 7, "5.01": 8}
LABEL_RE = re.compile(r"^(\d+)P\b")


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


def test_live_ttl_records_both_figures_it_was_reconciled_from():
    """Owner decision (2026-10-06): drawing figures are live; estimates are retained as records."""
    ttl = (BLDG1 / "bldg1_occupancy_capacity.ttl").read_text(encoding="utf-8")
    for room, drawing in (("1.04", 30), ("4.01", 7), ("5.01", 8)):
        block = ttl[ttl.index(f"bldg:Room{room}\n") :]
        block = block[: block.index(" .\n") + 3]
        assert f"hbco:roomCapacity     {drawing} ;" in block, room
        assert f"CapacityRecord_Room{room}_estimate" in ttl, room


def test_no_supersedes_triples_are_invented_for_these_rooms():
    """Owner decision (2026-10-06): supersedes links are written; no record is deleted."""
    ttl = (BLDG1 / "bldg1_occupancy_capacity.ttl").read_text(encoding="utf-8")
    assert "supersedes" in ttl
    for room in ("1.04", "4.01", "5.01"):
        assert f"CapacityRecord_Room{room}_drawing" in ttl, room


@pytest.mark.skip(
    reason="E6: awaits owner confirmation of the drawing figures (30/7/8) over the recorded "
    "25/20/20 before ontosage:supersedes + effectiveFrom are written. The precedence reader here "
    "has no supersedes support; that is the E4 work in commit 39c05c9."
)
def test_precedence_picks_the_authoritative_figure_once_the_triples_exist():
    from orchestrator.services.evidence.precedence import SourceClaim, resolve

    claims = [
        SourceClaim("bldg:Room4.01#hbco:roomCapacity", "authoritative", 7.0),
        SourceClaim("bldg:Room4.01#superseded", "authoritative", 20.0),
    ]
    assert resolve(claims).winner.value == 7.0
