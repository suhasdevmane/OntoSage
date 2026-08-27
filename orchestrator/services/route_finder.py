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
    #: True when the route changed floors through a shaft the ONTOLOGY declares but
    #: the floor plans never drew, so its position is not known (CAVEAT-313). An
    #: approximate route beats no route, but only if the reader is told which it is.
    approximate_vertical: bool = False

    @property
    def vertical_note(self) -> str:
        """What to append to a route that used an undrawn shaft. "" otherwise."""
        if not self.approximate_vertical:
            return ""
        return (
            "_This route changes floor through a lift or staircase the building's "
            "ontology declares but its floor plans do not draw, so the shaft's "
            "position is approximate and the hop count near it is indicative._"
        )


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

    def __init__(self, manifests: Sequence, vertical_cores: Optional[Sequence] = None) -> None:
        self.nodes: Dict[str, _Node] = {}
        #: zone_ids of vertical nodes the ONTOLOGY declares and the plans never drew.
        #: A route touching one is approximate in a way the reader must be told about.
        self.inferred_vertical: Set[str] = set()
        #: cores whose served floors were assumed rather than declared.
        self.assumed_coverage: Set[str] = set()
        self._build(manifests)
        self._attach_declared_cores(vertical_cores or [])

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

    #: Synthetic vertical nodes: shafts the ONTOLOGY declares that the floor plans
    #: never drew. Held so a route can disclose that it changed floors through a
    #: core whose position is not known (CAVEAT-313).
    def _attach_declared_cores(self, cores) -> None:
        """Add one node per served floor for each declared core the plans lack.

        Skipped entirely for a kind the manifests already type — a building whose
        DWGs draw their lifts keeps the real geometry and learns nothing from here.

        **The position is not invented.** A drawing that omits the shaft gives no
        coordinate to be near, so the node attaches to that floor's best-connected
        space: a graph-theoretic stand-in for a lift lobby, derived from the
        building's own adjacency. Deterministic — highest degree, ties broken by
        zone_id — because a route that changes between runs is not a route.
        """
        if not cores:
            return
        drawn_kinds = {n.type for n in self.nodes.values() if n.type in _VERTICAL_TYPES}
        floors = sorted({n.floor for n in self.nodes.values()})
        if not floors:
            return

        # Best-connected space per floor, computed once from the plans-only graph so
        # one synthetic core cannot influence where the next one attaches.
        anchor: Dict[int, str] = {}
        for f in floors:
            on_floor = [n for n in self.nodes.values() if n.floor == f]
            if on_floor:
                anchor[f] = sorted(on_floor, key=lambda n: (-len(n.neighbours), n.zone_id))[
                    0
                ].zone_id

        for core in cores:
            if core.kind in drawn_kinds:
                logger.debug(f"[route-finder] {core.label}: plans already type {core.kind}")
                continue
            served = [f for f in (core.floors or floors) if f in anchor]
            previous: Optional[str] = None
            for f in served:
                zid = f"vertical::{core.entity_id.rsplit('#', 1)[-1]}::{f}"
                self.nodes[zid] = _Node(
                    zone_id=zid,
                    label=f"{core.label} (floor {f})",
                    floor=f,
                    type=core.kind,
                    xy_m=None,  # unknown, and left unknown
                    neighbours={anchor[f]},
                )
                self.nodes[anchor[f]].neighbours.add(zid)
                if previous is not None:
                    self.nodes[previous].neighbours.add(zid)
                    self.nodes[zid].neighbours.add(previous)
                previous = zid
                self.inferred_vertical.add(zid)
                if core.floors_assumed:
                    self.assumed_coverage.add(core.entity_id)

        if self.inferred_vertical:
            logger.info(
                f"[route-finder] attached {len(self.inferred_vertical)} node(s) for vertical "
                f"circulation the ontology declares and the floor plans do not draw; routes "
                f"through them are reported as approximate"
            )

    # ── search ─────────────────────────────────────────────────────────────

    def _edge_cost(self, a: _Node, b: _Node) -> float:
        if a.floor != b.floor:
            return _FLOOR_CHANGE_COST_M
        if a.xy_m and b.xy_m:
            return max(0.5, math.dist(a.xy_m, b.xy_m))
        return 5.0  # unscaled floors still route; distance stays approximate

    def _dijkstra(
        self,
        src: str,
        *,
        step_free: bool = False,
        unavailable: Optional[Set[str]] = None,
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
                if unavailable and nb.zone_id in unavailable:
                    # A LIFT THAT IS OUT OF SERVICE IS NOT A STEP-FREE ROUTE.
                    # Dropping stairs makes an accessible route depend entirely on
                    # lifts, so an out-of-service lift does not merely lengthen the
                    # journey — it can remove the only route there is. Returning the
                    # route anyway, still labelled accessible, would send someone who
                    # cannot use stairs to a floor they cannot reach, which is the
                    # highest-consequence wrong answer this system can give.
                    continue
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

    def route(
        self,
        src: str,
        dest: str,
        *,
        step_free: bool = False,
        unavailable: Optional[Set[str]] = None,
    ) -> Optional[RouteResult]:
        """Shortest route src→dest; None when disconnected (or blocked step-free).

        ``unavailable`` are vertical cores that cannot be used right now — a lift with
        an open outage episode. They are excluded from the search rather than penalised:
        a broken lift is not a slower way up, it is not a way up.
        """
        if src not in self.nodes or dest not in self.nodes:
            return None
        if step_free and self.nodes[src].type == "staircase":
            return None
        if unavailable and src in unavailable:
            return None
        dist, prev = self._dijkstra(src, step_free=step_free, unavailable=unavailable)
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
            approximate_vertical=any(z in self.inferred_vertical for z in path),
        )

    def nearest(
        self,
        src: str,
        *,
        space_types: Optional[Set[str]] = None,
        label_contains: Optional[str] = None,
        step_free: bool = False,
        unavailable: Optional[Set[str]] = None,
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

        dist, prev = self._dijkstra(src, step_free=step_free, unavailable=unavailable)
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
