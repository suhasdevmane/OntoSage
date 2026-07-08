"""
spatial_agent.py — SpatialAgent (DW4)

Answers quantitative geometry questions sourced from DWG manifests:

  Area queries      "rooms larger than 50 m²", "smallest room on floor 3"
  Adjacency queries "rooms adjacent to 3.01", "what's next to the server room"
  Count/aggregate   "how many rooms on floor 3", "total area of floor 3"
  Block/MEP queries "how many sensors are on floor 3", "where are the fire exits"
  Type filter       "all meeting rooms on floor 4 larger than 20 m²"
  Wayfinding        "how do I get to room 5.01 from the main entrance"

All data comes from FloorPlanManifest spaces[] and blocks[].
No LLM calls — pure manifest analysis with keyword-driven query parsing.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from shared.models import Block, FloorPlanManifest, Space
from shared.utils import get_logger

logger = get_logger(__name__)

# ── Query pattern constants ────────────────────────────────────────────────────

_AREA_GT_RE = re.compile(
    r"(?:larger|bigger|greater|more|over|above|exceed)\s+than\s+([\d.]+)\s*(?:m²|m2|sq(?:uare)?\s*m(?:etre)?s?)?",
    re.IGNORECASE,
)
_AREA_LT_RE = re.compile(
    r"(?:smaller|less|under|below|fewer)\s+than\s+([\d.]+)\s*(?:m²|m2|sq(?:uare)?\s*m(?:etre)?s?)?",
    re.IGNORECASE,
)
_AREA_BETWEEN_RE = re.compile(
    r"between\s+([\d.]+)\s+and\s+([\d.]+)\s*(?:m²|m2|sq(?:uare)?\s*m(?:etre)?s?)?",
    re.IGNORECASE,
)
_AREA_QUERY_RE = re.compile(
    r"total\s+area|sum.*area|area.*floor|floor.*area|how\s+big|size\s+of\s+floor",
    re.IGNORECASE,
)
_ADJ_RE = re.compile(
    r"adjacent\s+to|next\s+to|beside|neighbouring|neighbor(?:ing)?\s+to|near\s+(?:room|zone|space)",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    r"how\s+many|count\s+(?:of\s+)?|number\s+of|total\s+(?:number|count)",
    re.IGNORECASE,
)
_FLOOR_RE = re.compile(r"\bfloor\s*(\d+)\b|\blevel\s*(\d+)\b", re.IGNORECASE)
_ZONE_RE = re.compile(r"\b(\d+)[.Z](\d{2,3})\b")
_BLOCK_TYPE_RE = re.compile(
    r"\b(sensor|door|window|fire.?exit|hvac|diffuser|fire.?alarm|light|power.?outlet|equipment)\b",
    re.IGNORECASE,
)

_WAYFINDING_RE = re.compile(
    r"how\s+(?:do\s+I|can\s+I|would\s+I)\s+(?:get|reach|go)\s+to"
    r"|how\s+to\s+(?:get|reach|find|go)\s+to"
    r"|direction[s]?\s+(?:to|for)"
    r"|route\s+to"
    r"|navigate\s+to"
    r"|find\s+my\s+way\s+to"
    r"|guide\s+me\s+to"
    r"|way\s+to\s+get\s+to"
    r"|how\s+do\s+I\s+reach",
    re.IGNORECASE,
)

_SPACE_TYPE_KEYWORDS: Dict[str, str] = {
    "office": "office",
    "lab": "lab",
    "laboratory": "lab",
    "meeting": "meeting_room",
    "conference": "meeting_room",
    "classroom": "classroom",
    "lecture": "lecture",
    "toilet": "toilet",
    "bathroom": "toilet",
    "kitchen": "kitchen",
    "server": "server_room",
    "storage": "storage",
    "stair": "staircase",
    "lift": "lift",
    "elevator": "lift",
    "reception": "reception",
    "corridor": "corridor",
    "utility": "utility",
}

# Colour palette for SVG / markdown tables (by space type)
_TYPE_COLOUR: Dict[str, str] = {
    "office": "#93c5fd",
    "lab": "#86efac",
    "meeting_room": "#fde68a",
    "classroom": "#c4b5fd",
    "lecture": "#a5b4fc",
    "toilet": "#d1d5db",
    "kitchen": "#fdba74",
    "server_room": "#f87171",
    "storage": "#d1fae5",
    "staircase": "#e5e7eb",
    "lift": "#e5e7eb",
    "reception": "#fbcfe8",
    "corridor": "#f3f4f6",
    "utility": "#fef9c3",
    "zone": "#bfdbfe",
    "unknown": "#f9fafb",
}


class SpatialAgent:
    """
    Answers spatial/geometry questions from DWG manifest data.
    Stateless — all context is derived from manifests.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    async def resolve(
        self,
        query: str,
        building_id: str,
        floor: Optional[int] = None,
    ) -> str:
        """
        Return a markdown-formatted answer to a spatial query.
        Never raises — errors produce a descriptive fallback string.
        """
        try:
            # Resolve the target floor: caller-pinned (floor_context, which may
            # arrive as a string) wins; otherwise infer it from the query when
            # it names exactly one. Coerce to int for reliable matching.
            target_floor: Optional[int] = None
            if floor is not None:
                try:
                    target_floor = int(floor)
                except (TypeError, ValueError):
                    target_floor = None
            if target_floor is None:
                target_floor = self._infer_floor_from_query(query)

            # Always load ALL manifests via the building-wide (alias-resolved)
            # path, then narrow in-memory. The per-floor registry fast-path is
            # type-sensitive (int vs str) and silently returned empty for valid
            # floors; filtering here is robust and floor-type-agnostic.
            manifests = self._load_manifests(building_id, None)
            if not manifests:
                return (
                    f"No floor plan data is available for **{building_id}**"
                    ". Make sure the DWG files have been ingested."
                )

            has_geometry = any(
                any(s.area_m2 is not None for s in m.spaces) for m in manifests
            )
            if not has_geometry:
                return (
                    "Geometry data (room areas, polygons) is not yet available — "
                    "this requires DWG source files in `/app/input/`. "
                    "Currently only PDF text extraction is active."
                )

            # Narrow to the target floor; fall back to the full set if that
            # floor has no manifest loaded (better an all-floors answer than
            # a false "no data").
            if target_floor is not None and len(manifests) > 1:
                scoped = [m for m in manifests if m.floor == target_floor]
                if scoped:
                    manifests = scoped

            return self._answer(query, manifests)
        except Exception as e:
            logger.error(f"[SpatialAgent] Error: {e}", exc_info=True)
            return "I encountered an error analysing the spatial data. Please try again."

    # ── Query dispatch ────────────────────────────────────────────────────────

    def _answer(self, query: str, manifests: List[FloorPlanManifest]) -> str:
        q = query.lower()

        # Wayfinding takes priority (before adjacency — "get to X from Y" ≠ "next to X")
        if _WAYFINDING_RE.search(q):
            return self._answer_wayfinding(query, manifests)

        # Adjacency query takes priority (before area checks)
        if _ADJ_RE.search(q):
            return self._answer_adjacency(query, manifests)

        # Total area / floor size
        if _AREA_QUERY_RE.search(q) and not _AREA_GT_RE.search(q) and not _AREA_LT_RE.search(q):
            return self._answer_total_area(manifests)

        # Area comparison
        if _AREA_GT_RE.search(q) or _AREA_LT_RE.search(q) or _AREA_BETWEEN_RE.search(q):
            return self._answer_area_filter(query, manifests)

        # Block/MEP entities
        if _BLOCK_TYPE_RE.search(q):
            return self._answer_blocks(query, manifests)

        # Count query
        if _COUNT_RE.search(q):
            return self._answer_count(query, manifests)

        # Default: list rooms of a given type (or all)
        return self._answer_list(query, manifests)

    # ── Area filter ───────────────────────────────────────────────────────────

    def _answer_area_filter(
        self, query: str, manifests: List[FloorPlanManifest]
    ) -> str:
        min_area: Optional[float] = None
        max_area: Optional[float] = None

        between = _AREA_BETWEEN_RE.search(query)
        if between:
            min_area = float(between.group(1))
            max_area = float(between.group(2))
        else:
            gt = _AREA_GT_RE.search(query)
            lt = _AREA_LT_RE.search(query)
            if gt:
                min_area = float(gt.group(1))
            if lt:
                max_area = float(lt.group(1))

        space_type = self._detect_space_type(query)
        matched: List[Tuple[int, Space]] = []
        for m in manifests:
            for s in m.spaces:
                if s.area_m2 is None:
                    continue
                if space_type and s.type != space_type:
                    continue
                if min_area is not None and s.area_m2 <= min_area:
                    continue
                if max_area is not None and s.area_m2 >= max_area:
                    continue
                matched.append((m.floor, s))

        if not matched:
            filter_desc = self._area_filter_desc(min_area, max_area, space_type)
            return f"No spaces found matching: **{filter_desc}**."

        # Sort by area descending
        matched.sort(key=lambda x: x[1].area_m2 or 0, reverse=True)

        filter_desc = self._area_filter_desc(min_area, max_area, space_type)
        lines = [f"## Spaces — {filter_desc}", f"", f"Found **{len(matched)}** space(s):", ""]
        lines.append("| Floor | Zone | Label | Type | Area (m²) |")
        lines.append("|-------|------|-------|------|-----------|")
        for fl, s in matched[:50]:
            lines.append(
                f"| {fl} | `{s.zone_id}` | {s.label} | {s.type} | {s.area_m2:.1f} |"
            )
        if len(matched) > 50:
            lines.append(f"\n_… and {len(matched) - 50} more._")
        return "\n".join(lines)

    def _area_filter_desc(
        self, min_area: Optional[float], max_area: Optional[float], space_type: Optional[str]
    ) -> str:
        parts = []
        if space_type:
            parts.append(space_type.replace("_", " ").title())
        if min_area is not None and max_area is not None:
            parts.append(f"{min_area}–{max_area} m²")
        elif min_area is not None:
            parts.append(f"> {min_area} m²")
        elif max_area is not None:
            parts.append(f"< {max_area} m²")
        return ", ".join(parts) if parts else "all spaces"

    # ── Total area ────────────────────────────────────────────────────────────

    def _answer_total_area(self, manifests: List[FloorPlanManifest]) -> str:
        lines = ["## Floor Areas", ""]
        lines.append("| Floor | Label | Total Area (m²) | Rooms |")
        lines.append("|-------|-------|-----------------|-------|")
        grand_total = 0.0
        for m in sorted(manifests, key=lambda x: x.floor):
            total = sum(s.area_m2 for s in m.spaces if s.area_m2 is not None)
            rooms = len([s for s in m.spaces if s.area_m2 is not None])
            grand_total += total
            lines.append(f"| {m.floor} | {m.floor_label} | {total:,.1f} | {rooms} |")
        if len(manifests) > 1:
            lines.append(f"| **Total** | | **{grand_total:,.1f}** | |")
        return "\n".join(lines)

    # ── Adjacency ─────────────────────────────────────────────────────────────

    def _answer_adjacency(
        self, query: str, manifests: List[FloorPlanManifest]
    ) -> str:
        # Find which zone is referenced
        zone_match = _ZONE_RE.search(query)
        ref_zone = zone_match.group(0) if zone_match else None

        # Also try space type or label keyword
        if ref_zone is None:
            ref_zone = self._find_zone_by_label(query, manifests)

        if ref_zone is None:
            return (
                "Please specify a zone ID (e.g. `3.01`) or room name to look up adjacency. "
                "Example: *\"rooms adjacent to 3.01\"*"
            )

        results: List[Tuple[int, Space, List[str]]] = []
        for m in manifests:
            for s in m.spaces:
                if s.zone_id == ref_zone or s.id.endswith(f".{ref_zone}"):
                    results.append((m.floor, s, s.adjacent_spaces))

        if not results:
            return f"Zone `{ref_zone}` not found in the floor plan data."

        fl, target_space, adj_ids = results[0]
        if not adj_ids:
            return (
                f"**{target_space.label}** (`{ref_zone}`, floor {fl}) "
                "has no recorded adjacencies — adjacency data requires DWG source files."
            )

        # Resolve adjacent zone IDs to spaces
        all_spaces: Dict[str, Space] = {
            s.zone_id: s for m in manifests for s in m.spaces
        }
        lines = [
            f"## Rooms adjacent to {target_space.label} (`{ref_zone}`, floor {fl})",
            "",
            f"Found **{len(adj_ids)}** neighbouring space(s):",
            "",
            "| Zone | Label | Type | Area (m²) |",
            "|------|-------|------|-----------|",
        ]
        for zid in adj_ids:
            adj = all_spaces.get(zid)
            if adj:
                area = f"{adj.area_m2:.1f}" if adj.area_m2 else "—"
                lines.append(f"| `{zid}` | {adj.label} | {adj.type} | {area} |")
            else:
                lines.append(f"| `{zid}` | — | — | — |")
        return "\n".join(lines)

    def _find_zone_by_label(
        self, query: str, manifests: List[FloorPlanManifest]
    ) -> Optional[str]:
        """Find zone_id for a space whose label appears in the query."""
        q_lower = query.lower()
        for m in manifests:
            for s in m.spaces:
                if s.label.lower() in q_lower and len(s.label) > 3:
                    return s.zone_id
        return None

    # ── Wayfinding ────────────────────────────────────────────────────────────

    def _answer_wayfinding(
        self, query: str, manifests: List[FloorPlanManifest]
    ) -> str:
        """BFS route guidance between two named spaces in the building."""
        zone_to_space: Dict[str, Space] = {}
        zone_to_floor: Dict[str, int] = {}
        for m in manifests:
            for s in m.spaces:
                zone_to_space[s.zone_id] = s
                zone_to_floor[s.zone_id] = m.floor

        dest_zone = self._extract_waypoint(query, manifests, role="destination")
        src_zone = self._extract_waypoint(query, manifests, role="source")

        if dest_zone is None:
            return (
                "I couldn't identify the destination in your query. "
                "Please specify a room number (e.g. `5.01`) or room name. "
                "Example: *'how do I get to room 5.01 from reception'*"
            )

        dest_space = zone_to_space.get(dest_zone)
        if dest_space is None:
            return f"Destination zone `{dest_zone}` not found in the floor plan data."

        if src_zone is None:
            src_zone = self._find_default_start(zone_to_space)

        if src_zone is None or src_zone not in zone_to_space:
            dest_floor = zone_to_floor.get(dest_zone)
            return (
                f"**{dest_space.label}** is on floor {dest_floor} (zone `{dest_zone}`). "
                "Please specify your starting point, e.g. *'from the main entrance'*, "
                "for turn-by-turn route guidance."
            )

        if src_zone == dest_zone:
            src_space = zone_to_space[src_zone]
            return f"You are already at **{src_space.label}** (`{src_zone}`)."

        path = self._bfs_route(src_zone, dest_zone, zone_to_space)
        src_space = zone_to_space.get(src_zone)
        src_floor = zone_to_floor.get(src_zone)
        dest_floor = zone_to_floor.get(dest_zone)

        if path is None:
            # No connected path — offer lift/stair hint for cross-floor cases
            if src_floor != dest_floor:
                lifts = [
                    zone_to_space[z].label
                    for z, s in zone_to_space.items()
                    if s.type in ("lift", "staircase")
                ][:3]
                hint = (
                    " Use " + ", ".join(f"**{n}**" for n in lifts) + " to change floors, then"
                    if lifts
                    else " Look for a lift or staircase to reach floor " + str(dest_floor) + "."
                )
                return (
                    f"**{dest_space.label}** (`{dest_zone}`) is on floor {dest_floor}. "
                    f"{hint} follow the corridor signs. "
                    "(Full route adjacency data requires DWG source files.)"
                )
            return (
                f"I could not find a connected route from "
                f"**{src_space.label if src_space else src_zone}** "
                f"to **{dest_space.label}** — adjacency data may be incomplete. "
                "(Full route data requires DWG source files.)"
            )

        lines = [
            f"## Route to {dest_space.label} (`{dest_zone}`)",
            "",
            f"**From:** {src_space.label if src_space else src_zone} (floor {src_floor})  ",
            f"**To:** {dest_space.label} (floor {dest_floor})  ",
            f"**Steps:** {len(path) - 1}",
            "",
        ]
        prev_floor = zone_to_floor.get(path[0])
        for i, zid in enumerate(path):
            space = zone_to_space.get(zid)
            fl = zone_to_floor.get(zid)
            label = space.label if space else zid
            space_type = space.type if space else ""
            floor_note = f" _(floor {prev_floor} → {fl})_" if fl != prev_floor else ""
            prev_floor = fl

            if i == 0:
                lines.append(f"1. **Start at** {label} (`{zid}`, floor {fl})")
            elif i == len(path) - 1:
                lines.append(
                    f"{i + 1}. **Arrive at** {label} (`{zid}`, floor {fl}){floor_note}"
                )
            else:
                verb = "Take" if space_type in ("lift", "staircase") else "Continue through"
                lines.append(
                    f"{i + 1}. {verb} **{label}** (`{zid}`, floor {fl}){floor_note}"
                )

        lines.append("")
        lines.append(
            "_Route calculated from floor plan adjacency data. "
            "For detailed directions, consult the posted floor plan maps._"
        )
        return "\n".join(lines)

    def _bfs_route(
        self, start: str, end: str, zone_to_space: Dict[str, Space]
    ) -> Optional[List[str]]:
        """BFS shortest path between zone IDs. Returns ordered zone ID list or None."""
        if start not in zone_to_space or end not in zone_to_space:
            return None
        visited = {start}
        queue: deque = deque([[start]])
        while queue:
            path = queue.popleft()
            current = path[-1]
            if current == end:
                return path
            space = zone_to_space.get(current)
            if space is None:
                continue
            for neighbor in space.adjacent_spaces:
                if neighbor not in visited and neighbor in zone_to_space:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return None

    def _extract_waypoint(
        self,
        query: str,
        manifests: List[FloorPlanManifest],
        role: str,  # "destination" | "source"
    ) -> Optional[str]:
        """Extract destination or source zone ID from a wayfinding query."""
        from_match = re.search(r"\bfrom\b", query, re.IGNORECASE)

        if role == "destination":
            # Destination is everything BEFORE 'from' (if present), or the whole query
            search_text = query[: from_match.start()] if from_match else query
        else:
            # Source is the clause AFTER 'from'
            if not from_match:
                return None
            search_text = query[from_match.end() :]

        zone_match = _ZONE_RE.search(search_text)
        if zone_match:
            return zone_match.group(0)
        return self._find_zone_by_label(search_text, manifests)

    def _find_default_start(self, zone_to_space: Dict[str, Space]) -> Optional[str]:
        """Return the zone_id of the reception or entrance space, if one exists."""
        for zid, s in zone_to_space.items():
            if s.type == "reception":
                return zid
        for zid, s in zone_to_space.items():
            if any(kw in s.label.lower() for kw in ("entrance", "lobby", "reception")):
                return zid
        return None

    # ── Block/MEP queries ─────────────────────────────────────────────────────

    def _answer_blocks(
        self, query: str, manifests: List[FloorPlanManifest]
    ) -> str:
        btype_match = _BLOCK_TYPE_RE.search(query)
        raw_type = btype_match.group(1).lower() if btype_match else None

        # Normalise to BlockType
        _NORM: Dict[str, str] = {
            "sensor": "sensor",
            "door": "door",
            "window": "window",
            "fire exit": "fire_exit",
            "fire_exit": "fire_exit",
            "hvac": "hvac_diffuser",
            "diffuser": "hvac_diffuser",
            "fire alarm": "fire_alarm",
            "fire_alarm": "fire_alarm",
            "light": "light_fixture",
            "power outlet": "power_outlet",
            "equipment": "equipment",
        }
        btype = _NORM.get(raw_type.replace("-", "_"), raw_type) if raw_type else None

        matched: List[Tuple[int, Block]] = []
        for m in manifests:
            for b in m.blocks:
                if btype is None or b.type == btype:
                    matched.append((m.floor, b))

        type_label = btype or "all blocks"
        if not matched:
            return (
                f"No **{type_label}** entities found in the floor plan data. "
                "Block data requires DWG source files."
            )

        by_floor: Dict[int, int] = {}
        for fl, _ in matched:
            by_floor[fl] = by_floor.get(fl, 0) + 1

        lines = [f"## {type_label.replace('_', ' ').title()} Count", ""]
        lines.append(f"Total: **{len(matched)}** across {len(by_floor)} floor(s).")
        lines.append("")
        lines.append("| Floor | Count |")
        lines.append("|-------|-------|")
        for fl in sorted(by_floor):
            lines.append(f"| {fl} | {by_floor[fl]} |")

        # List first 20 with location
        if len(matched) <= 20:
            lines.append("")
            lines.append("| Floor | Block | Layer | Space |")
            lines.append("|-------|-------|-------|-------|")
            for fl, b in sorted(matched, key=lambda x: x[0]):
                iri = b.attributes.get("ontology_iri", "")
                linked = " 🔗" if iri else ""
                lines.append(
                    f"| {fl} | `{b.block_name}`{linked} | {b.layer or '—'} | {b.space_id or '—'} |"
                )
        return "\n".join(lines)

    # ── Count ─────────────────────────────────────────────────────────────────

    def _answer_count(
        self, query: str, manifests: List[FloorPlanManifest]
    ) -> str:
        space_type = self._detect_space_type(query)
        lines = ["## Room Count", ""]
        lines.append("| Floor | Label | Rooms |" + (" Type |" if space_type else ""))
        lines.append("|-------|-------|-------|" + ("-------|" if space_type else ""))
        grand = 0
        for m in sorted(manifests, key=lambda x: x.floor):
            spaces = [s for s in m.spaces if not space_type or s.type == space_type]
            lines.append(
                f"| {m.floor} | {m.floor_label} | {len(spaces)} |"
                + (f" {space_type} |" if space_type else "")
            )
            grand += len(spaces)
        if len(manifests) > 1:
            lines.append(f"| **Total** | | **{grand}** |" + (" |" if space_type else ""))
        return "\n".join(lines)

    # ── List spaces ───────────────────────────────────────────────────────────

    def _answer_list(
        self, query: str, manifests: List[FloorPlanManifest]
    ) -> str:
        space_type = self._detect_space_type(query)
        matched: List[Tuple[int, Space]] = []
        for m in manifests:
            for s in m.spaces:
                if not space_type or s.type == space_type:
                    matched.append((m.floor, s))

        label = space_type.replace("_", " ").title() if space_type else "All spaces"
        if not matched:
            return f"No **{label.lower()}** spaces found."

        lines = [f"## {label}", f"", f"**{len(matched)}** space(s) found:", ""]
        lines.append("| Floor | Zone | Label | Type | Area (m²) |")
        lines.append("|-------|------|-------|------|-----------|")
        for fl, s in sorted(matched, key=lambda x: (x[0], x[1].zone_id))[:60]:
            area = f"{s.area_m2:.1f}" if s.area_m2 else "—"
            lines.append(f"| {fl} | `{s.zone_id}` | {s.label} | {s.type} | {area} |")
        if len(matched) > 60:
            lines.append(f"\n_… and {len(matched) - 60} more._")
        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _detect_space_type(self, query: str) -> Optional[str]:
        q = query.lower()
        for keyword, stype in _SPACE_TYPE_KEYWORDS.items():
            if keyword in q:
                return stype
        return None

    @staticmethod
    def _infer_floor_from_query(query: str) -> Optional[int]:
        """Return the floor number when EXACTLY one is named in the query.

        Lets a count/area/list query scope to the floor the user asked about
        even when the caller didn't pin floor_context. Multi-floor queries
        (e.g. "floor 1 vs floor 5") return None so they stay building-wide.
        """
        floors = {int(g1 or g2) for g1, g2 in _FLOOR_RE.findall(query or "")}
        return next(iter(floors)) if len(floors) == 1 else None

    def _candidate_building_ids(self, building_id: str) -> set:
        """Phase 4 — accept aliases when matching manifests on disk."""
        cands: set = {building_id}
        try:
            from orchestrator.services.building_registry import get_building_registry
            reg = get_building_registry()
            primary = reg.resolve_id(building_id) or building_id
            cands.add(primary)
            cfg = reg.get(primary)
            if cfg is not None:
                cands.update(cfg.floor_plan_aliases or [])
        except Exception:
            pass
        return cands

    def _load_manifests(
        self, building_id: str, floor: Optional[int]
    ) -> List[FloorPlanManifest]:
        """Load manifests from registry (alias-aware over both PDF and DWG floors)."""
        try:
            from orchestrator.services.floor_plan_registry import get_floor_plan_registry
            registry = get_floor_plan_registry()
            candidates = self._candidate_building_ids(building_id)
            if floor is not None:
                # Try each candidate ID; first hit wins.
                for cand in candidates:
                    m = registry.load_manifest(cand, floor)
                    if m:
                        return [m]
                return []
            results = []
            seen_floors: set = set()
            for bid, fl in registry.list_manifests():
                if bid not in candidates or fl in seen_floors:
                    continue
                manifest = registry.load_manifest(bid, fl)
                if manifest:
                    results.append(manifest)
                    seen_floors.add(fl)
            return results
        except Exception as e:
            logger.warning(f"[SpatialAgent] Could not load manifests: {e}")
            return []


# ── Module-level singleton ─────────────────────────────────────────────────────
_agent: Optional[SpatialAgent] = None


def get_spatial_agent() -> SpatialAgent:
    global _agent
    if _agent is None:
        _agent = SpatialAgent()
    return _agent
