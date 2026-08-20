# -*- coding: utf-8 -*-
"""One outline around two rooms must not give either room the other's area.

Room boundaries drawn by hand are occasionally drawn once around a pair of small
adjoining rooms. The extractor took the first room number it found inside and
named the outline after it, so a 22.8 m2 rectangle spanning two ~11 m2 rooms
reported one of them as 22.8 m2 -- double its real size, and entirely plausible.
A wrong-but-believable area is precisely what the grounding contract exists to
prevent, and a floor plan is one of the few places the system can state a number
with no sensor to contradict it.

The chosen behaviour keeps the outline as an unnamed space, so the floor total
stays correct, and leaves each room number to become a point space: known to
exist, known where, honestly carrying no area.
"""

import pytest

from shared.floor_plan_config import default_config

pytestmark = pytest.mark.unit

pytest.importorskip("shapely")

from orchestrator.services.dwg_pipeline import DWGPipeline  # noqa: E402


def _rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _assign(polygons, labels, cfg=None):
    cfg = cfg or default_config("b")
    pipe = DWGPipeline.__new__(DWGPipeline)
    return pipe._associate_labels(
        polygons,
        labels,
        "b",
        2,
        cfg.zone_id_regex(),
        1.0,  # scale_to_m
        0.0,  # min_x
        0.0,  # min_y
        10.0,  # width
        10.0,  # height
        cfg,
    )


def _by_zone(spaces):
    return {s.zone_id: s for s in spaces}


def test_two_room_numbers_in_one_outline_yield_no_attributed_area():
    spaces = _by_zone(
        _assign([(_rect(0, 0, 10, 10), "A-AREA-ROOM")], [("2.15", 2.0, 5.0), ("2.24", 8.0, 5.0)])
    )

    assert spaces["2.15"].area_m2 is None
    assert spaces["2.24"].area_m2 is None
    assert spaces["2.15"].polygon is None
    assert spaces["2.24"].polygon is None


def test_the_outline_survives_as_an_unnamed_space_so_the_floor_total_is_right():
    spaces = _assign(
        [(_rect(0, 0, 10, 10), "A-AREA-ROOM")], [("2.15", 2.0, 5.0), ("2.24", 8.0, 5.0)]
    )

    unnamed = [s for s in spaces if s.area_m2 is not None]
    assert len(unnamed) == 1
    assert unnamed[0].zone_id not in ("2.15", "2.24")
    assert unnamed[0].area_m2 == pytest.approx(100.0)


def test_both_rooms_are_still_present_and_placed():
    """Losing the rooms would be a worse cure than the disease."""
    spaces = _by_zone(
        _assign([(_rect(0, 0, 10, 10), "A-AREA-ROOM")], [("2.15", 2.0, 5.0), ("2.24", 8.0, 5.0)])
    )

    assert set(spaces) >= {"2.15", "2.24"}
    assert spaces["2.15"].centroid is not None
    assert spaces["2.24"].centroid is not None
    # Placed where the drawing puts them, not at a shared centroid.
    assert spaces["2.15"].centroid.x != spaces["2.24"].centroid.x


def test_a_single_room_outline_is_untouched():
    """The common case must keep its measured area."""
    spaces = _by_zone(_assign([(_rect(0, 0, 10, 10), "A-AREA-ROOM")], [("2.15", 5.0, 5.0)]))

    assert spaces["2.15"].area_m2 == pytest.approx(100.0)
    assert spaces["2.15"].polygon is not None


def test_a_room_number_plus_a_descriptive_label_is_not_ambiguous():
    """Only ROOM NUMBERS count — a room named as well as numbered is one room."""
    spaces = _by_zone(
        _assign(
            [(_rect(0, 0, 10, 10), "A-AREA-ROOM")],
            [("2.15", 4.0, 5.0), ("Research Laboratory", 6.0, 5.0)],
        )
    )

    assert spaces["2.15"].area_m2 == pytest.approx(100.0)


def test_rooms_in_separate_outlines_each_keep_their_own_area():
    spaces = _by_zone(
        _assign(
            [(_rect(0, 0, 5, 10), "A-AREA-ROOM"), (_rect(5, 0, 10, 10), "A-AREA-ROOM")],
            [("2.15", 2.0, 5.0), ("2.24", 8.0, 5.0)],
        )
    )

    assert spaces["2.15"].area_m2 == pytest.approx(50.0)
    assert spaces["2.24"].area_m2 == pytest.approx(50.0)
