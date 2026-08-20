# -*- coding: utf-8 -*-
"""
route_finder.py — hop routes and nearest-facility search over floor-plan
adjacency (V5-T27).

The graph is built entirely from the building's OWN persisted floor-plan
manifests: nodes are spaces, intra-floor edges come from DWG-derived
``adjacent_spaces``, and cross-floor edges connect vertical circulation
(lifts/staircases) whose footprints align between consecutive floors.
Distances are straight-line centroid-to-centroid in metres using each
floor's own drawing scale (``bounding_box.width_m/height_m``) — reported
honestly as "approximate", never as walking distance.

Step-free routing drops STAIRCASE nodes from the graph before searching, so
an accessible route only ever changes floors by lift; if that leaves no
route, the answer says so instead of quietly using stairs.

Everything is building-agnostic: no zone ids, floor counts or names appear
here — the same code routes any building whose manifests carry adjacency.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: space types that connect floors vertically
_VERTICAL_TYPES = {"lift", "staircase"}

#: assumed vertical travel cost between adjacent floors (metres-equivalent)
_FLOOR_CHANGE_COST_M = 6.0

#: how closely two vertical cores must align (metres) to be joined across floors
_CORE_ALIGN_M = 8.0

METHOD_NOTE = (
    "_Method: shortest path over DWG-derived room adjacency; distances are "
    "approximate straight-line between room centroids at drawing scale, not "
    "walking distance._"
)


@dataclass
class RouteResult:
    path: List[str]  # zone_ids, start → end
    labels: List[str]
    floors: List[int]
    hops: int
    distance_m: Optional[float]
    step_free: bool
    used_stairs: bool
    method: str = METHOD_NOTE


@dataclass
class NearestResult:
    zone_id: str
    label: str
    floor: int
    hops: int
    distance_m: Optional[float]
    method: str = METHOD_NOTE


@dataclass
class _Node:
    zone_id: str
    label: str
    floor: int
    type: str
    xy_m: Optional[Tuple[float, float]]  # centroid in metres on its floor
    neighbours: Set[str] = field(default_factory=set)


class RouteFinder:
    """Builds once per manifest set; route/nearest are pure lookups after."""

    def __init__(self, manifests: Sequence) -> None:
        self.nodes: Dict[str, _Node] = {}
        self._build(manifests)

    # ── graph construction ─────────────────────────────────────────────────

    @staticmethod
    def _floor_scale(manifest) -> Tuple[float, float]:
        bbox = getattr(manifest, "bounding_box", None) or {}
        width = float(
            getattr(bbox, "width_m", None)
            or (bbox.get("width_m") if isinstance(bbox, dict) else 0)
            or 0
        )
        height = float(
            getattr(bbox, "height_m", None)
            or (bbox.get("height_m") if isinstance(bbox, dict) else 0)
            or 0
        )
        return width, height

    def _build(self, manifests: Sequence) -> None:
        for m in manifests:
            width_m, height_m = self._floor_scale(m)
            for s in getattr(m, "spaces", []) or []:
                xy = None
                if s.centroid is not None and width_m > 0 and height_m > 0:
                    xy = (float(s.centroid.x) * width_m, float(s.centroid.y) * height_m)
                self.nodes[s.zone_id] = _Node(
                    zone_id=s.zone_id,
                    label=s.label,
                    floor=int(getattr(m, "floor", 0) or 0),
                    type=str(getattr(s, "type", "") or ""),
                    xy_m=xy,
                    neighbours=set(getattr(s, "adjacent_spaces", []) or []),
                )
        # adjacency is symmetric even when only one side declares it
        for zid, node in self.nodes.items():
            for nb in list(node.neighbours):
                if nb in self.nodes:
                    self.nodes[nb].neighbours.add(zid)
        # cross-floor edges: vertical cores on consecutive floors whose
        # footprints align (same shaft drawn on each storey)
        verticals = [n for n in self.nodes.values() if n.type in _VERTICAL_TYPES]
        by_floor: Dict[int, List[_Node]] = {}
        for n in verticals:
            by_floor.setdefault(n.floor, []).append(n)
        for floor, group in by_floor.items():
            uppers = by_floor.get(floor + 1, [])
            for a in group:
                for b in uppers:
                    if a.type != b.type:
                        continue
                    if a.xy_m and b.xy_m:
                        if math.dist(a.xy_m, b.xy_m) > _CORE_ALIGN_M:
                            continue
                    a.neighbours.add(b.zone_id)
                    b.neighbours.add(a.zone_id)
        n_edges = sum(len(n.neighbours) for n in self.nodes.values()) // 2
        logger.info(f"[route-finder] graph: {len(self.nodes)} spaces, {n_edges} edges")

    # ── search ─────────────────────────────────────────────────────────────

    def _edge_cost(self, a: _Node, b: _Node) -> float:
        if a.floor != b.floor:
            return _FLOOR_CHANGE_COST_M
        if a.xy_m and b.xy_m:
            return max(0.5, math.dist(a.xy_m, b.xy_m))
        return 5.0  # unscaled floors still route; distance stays approximate

    def _dijkstra(
        self, src: str, *, step_free: bool = False
    ) -> Tuple[Dict[str, float], Dict[str, str]]:
        dist: Dict[str, float] = {src: 0.0}
        prev: Dict[str, str] = {}
        heap: List[Tuple[float, str]] = [(0.0, src)]
        seen: Set[str] = set()
        while heap:
            d, zid = heapq.heappop(heap)
            if zid in seen:
                continue
            seen.add(zid)
            node = self.nodes.get(zid)
            if node is None:
                continue
            for nb_id in node.neighbours:
                nb = self.nodes.get(nb_id)
                if nb is None:
                    continue
                if step_free and nb.type == "staircase":
                    continue  # accessible routes never pass through stairs
                nd = d + self._edge_cost(node, nb)
                if nd < dist.get(nb_id, float("inf")):
                    dist[nb_id] = nd
                    prev[nb_id] = zid
                    heapq.heappush(heap, (nd, nb_id))
        return dist, prev

    @staticmethod
    def _unwind(prev: Dict[str, str], src: str, dest: str) -> Optional[List[str]]:
        if dest not in prev and dest != src:
            return None
        path = [dest]
        while path[-1] != src:
            path.append(prev[path[-1]])
        return list(reversed(path))

    def _has_scale(self, path: List[str]) -> bool:
        return all(self.nodes[z].xy_m is not None for z in path if z in self.nodes)

    def route(self, src: str, dest: str, *, step_free: bool = False) -> Optional[RouteResult]:
        """Shortest route src→dest; None when disconnected (or blocked step-free)."""
        if src not in self.nodes or dest not in self.nodes:
            return None
        if step_free and self.nodes[src].type == "staircase":
            return None
        dist, prev = self._dijkstra(src, step_free=step_free)
        path = self._unwind(prev, src, dest)
        if path is None:
            return None
        nodes = [self.nodes[z] for z in path]
        return RouteResult(
            path=path,
            labels=[n.label for n in nodes],
            floors=[n.floor for n in nodes],
            hops=len(path) - 1,
            distance_m=round(dist[dest], 1) if self._has_scale(path) else None,
            step_free=step_free,
            used_stairs=any(n.type == "staircase" for n in nodes),
        )

    def nearest(
        self,
        src: str,
        *,
        space_types: Optional[Set[str]] = None,
        label_contains: Optional[str] = None,
        step_free: bool = False,
    ) -> Optional[NearestResult]:
        """Closest space matching a type set or a label fragment."""
        if src not in self.nodes:
            return None

        def _matches(n: _Node) -> bool:
            if n.zone_id == src:
                return False
            if space_types and n.type in space_types:
                return True
            if label_contains and label_contains.lower() in n.label.lower():
                return True
            return False

        dist, prev = self._dijkstra(src, step_free=step_free)
        best: Optional[Tuple[float, _Node]] = None
        for zid, d in dist.items():
            node = self.nodes[zid]
            if _matches(node) and (best is None or d < best[0]):
                best = (d, node)
        if best is None:
            return None
        d, node = best
        path = self._unwind(prev, src, node.zone_id) or [src, node.zone_id]
        return NearestResult(
            zone_id=node.zone_id,
            label=node.label,
            floor=node.floor,
            hops=len(path) - 1,
            distance_m=round(d, 1) if self._has_scale(path) else None,
        )
