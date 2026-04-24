"""
spatial_agent.py — SpatialAgent (DW4)

Answers quantitative geometry questions sourced from DWG manifests:

  Area queries      "rooms larger than 50 m²", "smallest room on floor 3"
  Adjacency queries "rooms adjacent to 3.01", "what's next to the server room"
  Count/aggregate   "how many rooms on floor 3", "total area of floor 3"
  Block/MEP queries "how many sensors are on floor 3", "where are the fire exits"
  Type filter       "all meeting rooms on floor 4 larger than 20 m²"

All data comes from FloorPlanManifest spaces[] and blocks[].
No LLM calls — pure manifest analysis with keyword-driven query parsing.
"""

from __future__ import annotations

import re
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
            manifests = self._load_manifests(building_id, floor)
            if not manifests:
                return (
                    f"No floor plan data is available for **{building_id}**"
                    + (f" floor {floor}" if floor is not None else "")
                    + ". Make sure the DWG files have been ingested."
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

            return self._answer(query, manifests)
        except Exception as e:
            logger.error(f"[SpatialAgent] Error: {e}", exc_info=True)
            return "I encountered an error analysing the spatial data. Please try again."

    # ── Query dispatch ────────────────────────────────────────────────────────

    def _answer(self, query: str, manifests: List[FloorPlanManifest]) -> str:
        q = query.lower()

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

    def _load_manifests(
        self, building_id: str, floor: Optional[int]
    ) -> List[FloorPlanManifest]:
        """Load manifests from registry (covers both PDF and DWG-only floors)."""
        try:
            from orchestrator.services.floor_plan_registry import get_floor_plan_registry
            registry = get_floor_plan_registry()
            if floor is not None:
                m = registry.load_manifest(building_id, floor)
                return [m] if m else []
            results = []
            for bid, fl in registry.list_manifests():
                if bid != building_id:
                    continue
                manifest = registry.load_manifest(bid, fl)
                if manifest:
                    results.append(manifest)
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
