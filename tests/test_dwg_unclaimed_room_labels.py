# -*- coding: utf-8 -*-
"""CAVEAT-206: a room the drawing NAMES but does not outline is still a room.

A real architectural export may identify every room as text on the
area-identification layer while its only closed polylines are the gross-internal
-area outline, furniture and access routes. Measured on a real building: 51 room
numbers on layer A-AREA-IDEN, and not one per-room polygon — so every label fell
outside every polygon and was dropped, while furniture polygons became "rooms"
under positional ids. The rooms the ontology knows by name vanished from the
manifest.
"""

from __future__ import annotations

import re

import pytest

from orchestrator.services.dwg_pipeline import DWGPipeline

pytestmark = pytest.mark.unit

ZONE_RE = re.compile(r"\b(\d+)\.(\d{2})\b")


def _pipe():
    return DWGPipeline.__new__(DWGPipeline)


def _run(labels, consumed=None):
    return _pipe()._spaces_from_unclaimed_labels(
        labels, consumed or set(), "bldg1", 5, ZONE_RE, 0.0, 0.0, 100.0, 100.0
    )


class TestNamedButNotOutlined:
    def test_an_unclaimed_room_number_becomes_a_space(self):
        out = _run([("5.26", 50.0, 50.0)])
        assert len(out) == 1
        assert out[0].zone_id == "5.26"
        assert out[0].id == "bldg1.5.26"

    def test_its_position_comes_from_the_label(self):
        out = _run([("5.26", 25.0, 75.0)])
        c = out[0].centroid
        assert c.x == pytest.approx(0.25)
        # y is flipped to image convention, as polygon spaces are
        assert c.y == pytest.approx(0.25)

    def test_area_is_left_unknown_never_guessed(self):
        """The drawing says where the room is, not how big it is."""
        out = _run([("5.26", 50.0, 50.0)])
        assert out[0].area_m2 is None
        assert out[0].polygon is None

    def test_it_is_less_confident_than_a_polygon_backed_space(self):
        assert _run([("5.26", 50.0, 50.0)])[0].confidence < 0.98

    def test_a_whole_floor_of_labels_survives(self):
        labels = [(f"5.{i:02d}", float(i), 50.0) for i in range(1, 52)]
        assert len(_run(labels)) == 51


class TestWhatMustNotBecomeARoom:
    @pytest.mark.parametrize(
        "text",
        [
            "FIRE ALARM PANEL",
            "HEAT DETECTOR AND SOUNDER BASE",
            "Office",
            "Waste & Recycling Station Legend",
            "SYMBOL TAG WHERE X DENOTES ZONE NUMBER",
        ],
    )
    def test_legend_and_annotation_text_is_ignored(self, text):
        """Only text matching the building's own zone pattern qualifies."""
        assert _run([(text, 10.0, 10.0)]) == []

    def test_a_label_a_polygon_already_claimed_is_not_duplicated(self):
        lab = ("5.26", 50.0, 50.0)
        assert _run([lab], consumed={lab}) == []

    def test_a_room_repeated_in_the_drawing_yields_one_space(self):
        out = _run([("5.26", 10.0, 10.0), ("5.26", 90.0, 90.0)])
        assert len(out) == 1


class TestCoordinatesStayInRange:
    @pytest.mark.parametrize("lx,ly", [(-50.0, -50.0), (500.0, 500.0)])
    def test_labels_outside_the_extent_are_clamped(self, lx, ly):
        c = _run([("5.26", lx, ly)])[0].centroid
        assert 0.0 <= c.x <= 1.0 and 0.0 <= c.y <= 1.0


class TestAdjacencyToleratesPolygonlessSpaces:
    """The point spaces broke an implicit invariant: `spaces` and `polygons_raw`
    used to be index-parallel, so adjacency indexed polygons by space position
    and walked off the end — every real DWG ingest failed with
    'list index out of range' AFTER the rooms had been recovered."""

    def test_more_spaces_than_polygons_does_not_raise(self):
        from shared.models import NormalisedPoint, Space

        poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        spaces = [
            Space(
                id="b.1",
                zone_id="1",
                label="with polygon",
                polygon=[NormalisedPoint(x=0, y=0), NormalisedPoint(x=1, y=0), NormalisedPoint(x=1, y=1)],
                source="dwg",
            ),
            Space(id="b.5.26", zone_id="5.26", label="point only", source="dwg"),
            Space(id="b.5.27", zone_id="5.27", label="point only", source="dwg"),
        ]
        # one polygon, three spaces — the shape that used to crash
        _pipe()._compute_adjacency(spaces, [(poly, "A-AREA")], 0.001)
        assert spaces[1].adjacent_spaces == []

    def test_a_point_space_claims_no_neighbours(self):
        from shared.models import Space

        spaces = [Space(id="b.5.26", zone_id="5.26", label="point", source="dwg")]
        _pipe()._compute_adjacency(spaces, [], 0.001)
        assert spaces[0].adjacent_spaces == []
