"""The floor overview finds the plans it holds, and names the building once (2026-10-11, r7).

"Where are the network cabinets on each floor?" was told "No floor plans are available for the
Abacws Building Building" while six floors of plans were served: the plans are keyed by the
building's plan name and the overview filtered by its id.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.agents.floor_plan_agent import FloorPlanAgent

pytestmark = pytest.mark.unit


class _Pipeline:
    def __init__(self, manifests):
        self._m = manifests

    def list_manifests(self):
        return list(self._m)

    def load_manifest(self, building_id, floor):
        return SimpleNamespace(
            pdf_url=f"/floor-plans/{floor}.pdf",
            floor_label=f"Floor {floor}",
            spaces=[],
            warnings=[],
            rendered_image=SimpleNamespace(png_url="", thumbnail_url=""),
        )


def _agent():
    agent = FloorPlanAgent.__new__(FloorPlanAgent)
    agent._abs = lambda url: url
    return agent


def test_one_buildings_plans_are_this_buildings():
    out = _agent()._build_overview_result(
        _Pipeline([("abacws", 0), ("abacws", 1)]), "bldg1", "Abacws Building"
    )
    assert "No floor plans" not in out.markdown
    assert "Building Building" not in out.markdown


def test_none_at_all_still_says_so_once():
    out = _agent()._build_overview_result(_Pipeline([]), "bldg1", "Abacws Building")
    assert out.markdown == "No floor plans are available for Abacws Building."
