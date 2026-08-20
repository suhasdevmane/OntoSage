# -*- coding: utf-8 -*-
"""A boundary drawn by snapping back to the start is closed, flag or no flag.

AutoCAD sets a polyline's ``closed`` flag only when the ring is finished with the
Close option. Someone drawing a room boundary by hand naturally ends it by
snapping the last vertex onto the first instead, which produces the same ring
with the flag unset. Trusting the flag alone dropped those rooms from the floor
plan entirely -- and because the label fallback then kept them as point spaces,
the loss presented as missing source data rather than as a bug in extraction.

These tests pin both halves of the rule: a ring that closes geometrically counts,
and an open path does not become one just because it has several vertices.
"""

import pytest

from orchestrator.services.dwg_pipeline import (
    _RING_CLOSURE_TOLERANCE,
    _is_ring,
    _iter_closed_rings,
)

pytestmark = pytest.mark.unit

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_flagged_closed_is_a_ring():
    assert _is_ring(SQUARE, True) is True


def test_ends_that_meet_exactly_are_a_ring_without_the_flag():
    assert _is_ring(SQUARE + [(0.0, 0.0)], False) is True


@pytest.mark.parametrize("gap_ratio", [0.000025, 0.001047])
def test_real_drafting_gaps_are_rings(gap_ratio):
    """The two gaps actually measured on a hand-drawn floor: 0.0025% and 0.10%.

    Recorded as ratios rather than millimetres because the tolerance is relative
    -- the same slip means something different on a 14 m room than a 140 mm one.
    """
    perimeter = 40.0
    gap = gap_ratio * perimeter
    assert _is_ring(SQUARE + [(gap, 0.0)], False) is True


def test_gap_beyond_tolerance_is_not_a_ring():
    perimeter = 40.0
    gap = 2 * _RING_CLOSURE_TOLERANCE * perimeter
    assert _is_ring(SQUARE + [(gap, 0.0)], False) is False


def test_open_wall_run_is_not_a_ring():
    """A leader or wall line has a gap comparable to its own length."""
    assert _is_ring([(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)], False) is False


def test_l_shaped_open_path_is_not_a_ring():
    assert _is_ring([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)], False) is False


def test_too_few_points_is_not_a_ring():
    assert _is_ring([(0.0, 0.0), (1.0, 1.0)], True) is False


def test_degenerate_zero_perimeter_is_not_a_ring():
    """All-coincident points have a zero gap; that must not read as closed."""
    assert _is_ring([(1.0, 1.0), (1.0, 1.0), (1.0, 1.0)], False) is False


# --- iteration over both polyline flavours -----------------------------------


class _FakeDxf:
    def __init__(self, layer):
        self.layer = layer


class _FakeLw:
    def __init__(self, pts, closed, layer):
        self._pts, self.closed, self.dxf = pts, closed, _FakeDxf(layer)

    def get_points(self, _fmt):
        return self._pts


class _FakeVertex:
    def __init__(self, xy):
        self.dxf = type("d", (), {"location": (xy[0], xy[1], 0.0)})()


class _FakePoly:
    def __init__(self, pts, closed, layer, is_2d=True):
        self.vertices = [_FakeVertex(p) for p in pts]
        self.is_closed, self.is_2d_polyline = closed, is_2d
        self.dxf = _FakeDxf(layer)


class _FakeMsp:
    def __init__(self, lw, poly):
        self._lw, self._poly = lw, poly

    def query(self, name):
        return self._lw if name == "LWPOLYLINE" else self._poly


def test_iter_reads_both_lwpolyline_and_heavy_polyline():
    """Which flavour a DXF carries depends on the exporter, not on what was drawn."""
    msp = _FakeMsp(
        [_FakeLw(SQUARE, True, "A-AREA-ROOM")],
        [_FakePoly(SQUARE, True, "A-AREA-ROOM")],
    )
    assert [layer for _, layer in _iter_closed_rings(msp)] == ["A-AREA-ROOM"] * 2


def test_iter_skips_3d_polylines():
    msp = _FakeMsp([], [_FakePoly(SQUARE, True, "MESH", is_2d=False)])
    assert list(_iter_closed_rings(msp)) == []


def test_one_malformed_entity_does_not_abort_the_floor():
    class _Broken:
        dxf = _FakeDxf("A-AREA-ROOM")
        closed = True

        def get_points(self, _fmt):
            raise ValueError("corrupt")

    msp = _FakeMsp([_Broken(), _FakeLw(SQUARE, True, "A-AREA-ROOM")], [])
    assert len(list(_iter_closed_rings(msp))) == 1
