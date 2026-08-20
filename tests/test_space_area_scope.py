# -*- coding: utf-8 -*-
"""BUG-199: an area question about one room must be about that room.

Every area query fell through to the whole-building floor table, so "how big is
RM001A_room?" — a 20 m² room — came back as three floor totals and a 1,040 m²
building sum. Nothing in that answer is false, which is what made it easy to
miss: it answers a question nobody asked, and a reader who trusts it leaves with
a number four orders of magnitude off.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from orchestrator.agents.spatial_agent import SpatialAgent
from shared.models import FloorPlanManifest, RenderedImage, Space

pytestmark = pytest.mark.unit


def space(zone_id, label, area=20.0, perimeter=18.0):
    return Space(
        id=f"bldg2.{zone_id}",
        zone_id=zone_id,
        label=label,
        type="zone",
        area_m2=area,
        perimeter_m=perimeter,
        source="dwg",
        confidence=0.98,
    )


def manifest(floor, spaces):
    return FloorPlanManifest(
        schema_version="2.0",
        building_id="bldg2",
        building_name="BuildSys Building",
        floor=floor,
        floor_label=f"Floor {floor}",
        source_pdf=f"bldg2 floor {floor}.pdf",
        source_sha256="0" * 64,
        generated_at=datetime(2026, 8, 19, 12, 0, 0),
        generator_version="2.0.0",
        page_count=1,
        rendered_image=RenderedImage(
            png_url=f"/floor-plans/renders/bldg2/floor_{floor}.png",
            thumbnail_url=f"/floor-plans/renders/bldg2/floor_{floor}_thumb.png",
            width_px=1000,
            height_px=800,
            dpi=150,
        ),
        pdf_url=f"/floor-plans/bldg2%20floor%20{floor}.pdf",
        spaces=spaces,
    )


@pytest.fixture
def agent():
    return SpatialAgent.__new__(SpatialAgent)


@pytest.fixture
def manifests():
    return [
        manifest(0, [space("0Z001", "RM001A_room", 20.0), space("0Z002", "RM001B_room", 30.0)]),
        manifest(1, [space("1Z001", "RM101_room", 50.0)]),
    ]


class TestTheNamedRoomAnswer:
    def test_the_rooms_own_area_is_reported(self, agent, manifests):
        out = agent._answer("How big is RM001A_room?", manifests)
        assert "20.0 m²" in out
        assert "RM001A_room" in out

    def test_the_building_total_is_not_the_answer(self, agent, manifests):
        """100.0 m² is the sum across both floors — the old answer."""
        out = agent._answer("How big is RM001A_room?", manifests)
        assert "Floor Areas" not in out, "fell through to the building-wide table"
        assert "100.0" not in out

    def test_a_room_named_without_its_suffix_still_resolves(self, agent, manifests):
        out = agent._answer("how big is RM101?", manifests)
        assert "50.0 m²" in out

    def test_the_answer_gives_the_room_its_context(self, agent, manifests):
        out = agent._answer("How big is RM001A_room?", manifests)
        assert "floor 0" in out
        assert "%" in out, "a bare number without its share of the floor is less useful"


class TestBuildingAndFloorScopeAreUntouched:
    def test_a_building_question_keeps_the_floor_table(self, agent, manifests):
        out = agent._answer("What is the total floor area?", manifests)
        assert "Floor Areas" in out

    def test_how_big_is_the_building_is_not_a_room(self, agent, manifests):
        out = agent._answer("How big is the building?", manifests)
        assert "Floor Areas" in out

    def test_a_floor_question_is_not_captured_by_a_room(self, agent, manifests):
        out = agent._answer("size of floor 1", manifests)
        assert "Floor Areas" in out


class TestHonestyWhenGeometryIsMissing:
    def test_a_room_without_area_says_so_instead_of_substituting(self, agent):
        ms = [manifest(0, [space("0Z001", "RM001A_room", area=None, perimeter=None)])]
        out = agent._answer("How big is RM001A_room?", ms)
        assert "no area is recorded" in out
        assert "Floor Areas" not in out, "the building total must not stand in for the room"

    def test_an_unknown_room_does_not_invent_one(self, agent, manifests):
        out = agent._answer("How big is RM999_room?", manifests)
        assert "20.0 m²" not in out and "50.0 m²" not in out
