# -*- coding: utf-8 -*-
"""BUG-202 / CAVEAT-094: the floor overview must name the building it serves.

`_BUILDING_NAME` was a module constant fixed to the first building this system
ever served. Two consequences, both live: every heading it rendered announced
that building's name whatever building was running — bldg2 users were served
"Abacws Building — Floor Overview" while .env said "BuildSys Building (bldg2)" —
and the PDF discovery regex was anchored to the same literal, so no other
building's floor plans were discovered at all.
"""

from __future__ import annotations

import re

import pytest

from orchestrator.services import floor_plan_service as fps

pytestmark = pytest.mark.unit


class TestTheNameFollowsTheActiveBuilding:
    def test_it_reports_the_configured_name(self, monkeypatch):
        monkeypatch.setattr(fps.settings, "BUILDING_NAME", "BuildSys Building (bldg2)")
        assert fps._building_name() == "BuildSys Building (bldg2)"

    def test_a_different_building_gets_its_own_name(self, monkeypatch):
        monkeypatch.setattr(fps.settings, "BUILDING_NAME", "North Wing")
        assert fps._building_name() == "North Wing"

    def test_it_is_read_per_call_so_a_swap_is_reflected(self, monkeypatch):
        """A module constant would freeze at import and survive a building swap."""
        monkeypatch.setattr(fps.settings, "BUILDING_NAME", "First Building")
        first = fps._building_name()
        monkeypatch.setattr(fps.settings, "BUILDING_NAME", "Second Building")
        assert fps._building_name() != first

    def test_it_falls_back_to_the_id_not_to_a_real_building(self, monkeypatch):
        monkeypatch.setattr(fps.settings, "BUILDING_NAME", "")
        monkeypatch.setattr(fps.settings, "BUILDING_ID", "bldg7")
        name = fps._building_name()
        assert name == "bldg7"
        assert "abacws" not in name.lower()

    def test_it_never_returns_empty(self, monkeypatch):
        monkeypatch.setattr(fps.settings, "BUILDING_NAME", "")
        monkeypatch.setattr(fps.settings, "BUILDING_ID", "")
        assert fps._building_name() == "Building"

    def test_no_building_literal_survives_in_the_module(self):
        src = fps.__file__
        with open(src, encoding="utf-8") as fh:
            body = fh.read()
        assert not re.search(r"_BUILDING_NAME\s*=", body), "the frozen constant came back"


class TestPdfDiscoveryIsBuildingAgnostic:
    @pytest.mark.parametrize(
        "filename,floor",
        [
            ("bldg2 floor 0.pdf", 0),
            ("Abacws floor 3.pdf", 3),
            ("North Wing floor 12.pdf", 12),
            ("BUILDSYS FLOOR 1.PDF", 1),
        ],
    )
    def test_any_building_prefix_is_discovered(self, filename, floor):
        m = fps._PDF_FILE_RE.match(filename)
        assert m is not None, f"{filename} would not be discovered"
        assert int(m.group("floor")) == floor

    @pytest.mark.parametrize(
        "filename",
        ["floorplan.pdf", "bldg2 basement.pdf", "bldg2 floor two.pdf", "notes.txt"],
    )
    def test_unrelated_files_are_not_mistaken_for_floor_plans(self, filename):
        assert fps._PDF_FILE_RE.match(filename) is None
