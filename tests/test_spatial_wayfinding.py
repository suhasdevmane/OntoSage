"""T31 — SpatialAgent wayfinding unit tests.

Covers:
  1. _WAYFINDING_RE matches expected trigger phrases
  2. _bfs_route finds shortest path through adjacency graph
  3. _bfs_route returns None when no path exists
  4. _answer_wayfinding formats route correctly
  5. Cross-floor fallback when no adjacency data spans floors
  6. Missing destination returns helpful message
  7. Wayfinding takes priority over adjacency in _answer dispatch
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.agents.spatial_agent import SpatialAgent, _WAYFINDING_RE
from shared.models import FloorPlanManifest, RenderedImage, Space


# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _space(zone_id: str, label: str, space_type: str = "office", adjacent: List[str] = None, area: float = 20.0) -> Space:
    return Space(
        id=f"bldg1.{zone_id}",
        zone_id=zone_id,
        label=label,
        type=space_type,
        area_m2=area,
        adjacent_spaces=adjacent or [],
    )


def _manifest(floor: int, spaces: List[Space]) -> FloorPlanManifest:
    return FloorPlanManifest(
        building_id="bldg1",
        building_name="Test Building",
        floor=floor,
        floor_label=f"Floor {floor}",
        schema_version="2.0",
        source_pdf=f"floor{floor}.pdf",
        source_sha256="0" * 64,
        generated_at="2026-01-01T00:00:00",
        rendered_image=RenderedImage(
            png_url=f"/floor{floor}.png",
            thumbnail_url=f"/floor{floor}_thumb.png",
            width_px=1000,
            height_px=800,
            dpi=96,
        ),
        pdf_url=f"/floor{floor}.pdf",
        spaces=spaces,
        blocks=[],
    )


@pytest.fixture
def linear_manifests():
    """Three rooms on floor 5: reception → corridor → office 5.01 (linear adjacency)."""
    return [
        _manifest(5, [
            _space("5.00", "Main Reception", "reception", adjacent=["5.01"]),
            _space("5.01", "Corridor", "corridor", adjacent=["5.00", "5.02"]),
            _space("5.02", "Office 5.02", "office", adjacent=["5.01"]),
        ])
    ]


@pytest.fixture
def cross_floor_manifests():
    """Lift on floor 3 adjacent to lift on floor 5; final office only on floor 5."""
    floor3 = _manifest(3, [
        _space("3.00", "Floor 3 Reception", "reception", adjacent=["3.lift"]),
        _space("3.lift", "Lift Floor 3", "lift", adjacent=["3.00", "5.lift"]),
    ])
    floor5 = _manifest(5, [
        _space("5.lift", "Lift Floor 5", "lift", adjacent=["3.lift", "5.01"]),
        _space("5.01", "Office 5.01", "office", adjacent=["5.lift"]),
    ])
    return [floor3, floor5]


# ─── _WAYFINDING_RE ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "how do I get to room 5.01",
    "how do I get to room 5.01 from the main entrance",
    "directions to the server room from reception",
    "route to 3.01 from 5.20",
    "navigate to the meeting room",
    "find my way to the kitchen",
    "guide me to the server room",
    "how do I reach the library",
    "way to get to room 4.02",
    "how can I get to floor 3",
    "how would I get to zone 2.01",
])
def test_wayfinding_re_matches_trigger_phrases(phrase):
    assert _WAYFINDING_RE.search(phrase), f"Expected match for: '{phrase}'"


@pytest.mark.parametrize("phrase", [
    "rooms adjacent to 3.01",
    "what's next to the server room",
    "how many rooms on floor 2",
    "show me the floor plan",
    "total area of floor 5",
])
def test_wayfinding_re_does_not_match_non_wayfinding(phrase):
    assert not _WAYFINDING_RE.search(phrase), f"Unexpected match for: '{phrase}'"


# ─── _bfs_route ───────────────────────────────────────────────────────────────


def test_bfs_route_direct_adjacency():
    """Two directly adjacent zones."""
    zone_to_space = {
        "A": _space("A", "Room A", adjacent=["B"]),
        "B": _space("B", "Room B", adjacent=["A"]),
    }
    agent = SpatialAgent()
    path = agent._bfs_route("A", "B", zone_to_space)
    assert path == ["A", "B"]


def test_bfs_route_shortest_path():
    """BFS finds shortest path when a longer alternative exists."""
    zone_to_space = {
        "A": _space("A", "A", adjacent=["B", "C"]),
        "B": _space("B", "B", adjacent=["A", "D"]),
        "C": _space("C", "C", adjacent=["A", "D"]),
        "D": _space("D", "D", adjacent=["B", "C"]),
    }
    agent = SpatialAgent()
    path = agent._bfs_route("A", "D", zone_to_space)
    assert path is not None
    assert path[0] == "A" and path[-1] == "D"
    assert len(path) == 3  # A → B → D  or  A → C → D


def test_bfs_route_no_path():
    """Returns None when destination is unreachable."""
    zone_to_space = {
        "A": _space("A", "A", adjacent=["B"]),
        "B": _space("B", "B", adjacent=["A"]),
        "C": _space("C", "C", adjacent=[]),  # isolated
    }
    agent = SpatialAgent()
    assert agent._bfs_route("A", "C", zone_to_space) is None


def test_bfs_route_same_start_end():
    zone_to_space = {"A": _space("A", "A", adjacent=[])}
    agent = SpatialAgent()
    path = agent._bfs_route("A", "A", zone_to_space)
    assert path == ["A"]


def test_bfs_route_unknown_start():
    zone_to_space = {"A": _space("A", "A", adjacent=[])}
    agent = SpatialAgent()
    assert agent._bfs_route("Z", "A", zone_to_space) is None


# ─── _answer_wayfinding ───────────────────────────────────────────────────────


def test_wayfinding_finds_route_on_same_floor(linear_manifests):
    agent = SpatialAgent()
    result = agent._answer_wayfinding("how do I get to room 5.02 from the main reception", linear_manifests)
    assert "Arrive at" in result or "Office 5.02" in result
    assert "5.02" in result


def test_wayfinding_no_destination_gives_helpful_message(linear_manifests):
    agent = SpatialAgent()
    result = agent._answer_wayfinding("how do I get to the restrooms", linear_manifests)
    # No zone_id + no label match → destination not found
    assert "couldn't identify" in result.lower() or "not found" in result.lower()


def test_wayfinding_already_at_destination(linear_manifests):
    agent = SpatialAgent()
    result = agent._answer_wayfinding(
        "how do I get to main reception from main reception", linear_manifests
    )
    assert "already" in result.lower()


def test_wayfinding_cross_floor_via_lift(cross_floor_manifests):
    agent = SpatialAgent()
    result = agent._answer_wayfinding(
        "how do I get to office 5.01 from floor 3 reception", cross_floor_manifests
    )
    # Should produce a multi-step route going through lifts
    assert "5.01" in result or "Office 5.01" in result


def test_wayfinding_no_path_honest_fallback(linear_manifests):
    """When BFS can't find a path, returns an honest fallback — not silence."""
    agent = SpatialAgent()
    # 5.02 is reachable, but if we ask for something disconnected we get fallback
    # Create manifests with an isolated space
    isolated_manifests = [
        _manifest(5, [
            _space("5.00", "Reception", "reception", adjacent=[]),
            _space("5.99", "Isolated Room", "office", adjacent=[]),
        ])
    ]
    result = agent._answer_wayfinding("how do I get to isolated room from reception", isolated_manifests)
    assert "could not find" in result.lower() or "not available" in result.lower() or "adjacency" in result.lower()


# ─── _answer dispatch priority ───────────────────────────────────────────────


def test_wayfinding_takes_priority_over_adjacency(linear_manifests):
    """'how do I get to X' should not be dispatched to _answer_adjacency."""
    agent = SpatialAgent()
    result = agent._answer("how do I get to 5.02 from main reception", linear_manifests)
    # Adjacency response header is "## Rooms adjacent to"
    assert "Rooms adjacent to" not in result


def test_adjacency_still_works_for_non_wayfinding(linear_manifests):
    """Normal adjacency query still routes to _answer_adjacency."""
    agent = SpatialAgent()
    result = agent._answer("rooms adjacent to 5.00", linear_manifests)
    assert "adjacent to" in result.lower() or "neighbour" in result.lower() or "5.01" in result
