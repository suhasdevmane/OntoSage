"""
floor_plan_agent.py — FloorPlanAgent

Resolves a user query to a structured FloorPlanResult by:
  1. Detecting building_id (from state, query, or default)
  2. Detecting floor (explicit number → state.floor_context → None)
  3. Detecting space (zone_id regex → manifest space search → LLM resolver)
  4. Branching:
     A) Space known     → result with selected_space populated
     B) Floor known     → result with candidates for disambiguation
     C) Nothing known   → cross-building / cross-floor search
     D) Overview intent → building overview cards

This replaces the inline _floor_plan_node logic in workflow.py so the
workflow node becomes a thin wrapper.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional

from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline
from shared.models import ConversationState, FloorPlanManifest, FloorPlanResult, Space
from shared.utils import get_logger

logger = get_logger(__name__)

from shared.config import settings

# Building defaults flow from the global BUILDING_ID setting.  The Phase 4
# alias mechanism in BuildingRegistry transparently maps legacy floor-plan
# slugs (e.g. "abacws") to the logical building_id (e.g. "bldg1"), so the
# floor plan agent can use settings.BUILDING_ID everywhere.
_DEFAULT_BUILDING_ID = settings.BUILDING_ID
_DEFAULT_BUILDING_NAME = settings.BUILDING_NAME
_STATIC_BASE_URL = "http://localhost:8080"

# Patterns for detecting floor and zone references in natural language
# Matches: "floor 5", "level 5", "storey 5"
_FLOOR_RE = re.compile(r"\b(?:floor|level|storey|story)\s*(\d+)\b", re.IGNORECASE)
# Matches: "5th floor", "1st floor", "2nd floor", "3rd floor"
_ORDINAL_FLOOR_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+floor\b", re.IGNORECASE)
# Matches written ordinals: "first floor", "second floor", ..., "tenth floor"
_WORD_ORDINAL_MAP = {
    "ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4,
    "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_WORD_FLOOR_RE = re.compile(
    r"\b(" + "|".join(_WORD_ORDINAL_MAP.keys()) + r")\s+floor\b",
    re.IGNORECASE,
)
# Matches: "top floor", "highest floor"
_TOP_FLOOR_RE = re.compile(r"\b(?:top|highest|uppermost)\s+floor\b", re.IGNORECASE)
_ZONE_RE = re.compile(r"\b(\d+)\.(\d{2,3})\b")

# Keywords that suggest a building-overview request
_OVERVIEW_KEYWORDS = frozenset(
    [
        "overview", "all floors", "each floor", "entire building",
        "building summary", "building layout", "what floors", "how many floors",
    ]
)

# Keywords that trigger cross-floor search even without a floor number
_LOCATION_KEYWORDS = frozenset(
    [
        "where is", "where are", "find", "locate", "which floor",
        "navigate", "directions to", "how do i get to",
    ]
)


class FloorPlanAgent:
    """
    Resolves floor plan queries to structured FloorPlanResult objects.
    One shared instance per application (stateless — all context via ConversationState).
    """

    def __init__(self, static_base_url: Optional[str] = None) -> None:
        self._base_url = (static_base_url or _STATIC_BASE_URL).rstrip("/")

    # ── Public API ────────────────────────────────────────────────────────────

    async def resolve(
        self, query: str, state: ConversationState
    ) -> FloorPlanResult:
        """
        Main entry point.  Returns a FloorPlanResult.  Never raises —
        errors produce a result with a descriptive markdown message.
        """
        try:
            return await self._resolve(query, state)
        except Exception as e:
            logger.error(f"[FloorPlanAgent] Unexpected error: {e}", exc_info=True)
            return FloorPlanResult(
                building_id=_DEFAULT_BUILDING_ID,
                markdown="I encountered an error loading the floor plan. Please try again.",
                interactive=False,
            )

    # ── Resolution logic ──────────────────────────────────────────────────────

    async def _resolve(
        self, query: str, state: ConversationState
    ) -> FloorPlanResult:
        pipeline = get_floor_plan_pipeline()

        # 1. Determine building
        building_id = self._detect_building(query, state)
        building_name = _DEFAULT_BUILDING_NAME

        # Load building name from any available manifest
        all_manifests = {
            (bid, fl): pipeline.load_manifest(bid, fl)
            for bid, fl in pipeline.list_manifests()
            if bid == building_id
        }
        if all_manifests:
            first = next(iter(all_manifests.values()))
            if first:
                building_name = first.building_name

        # 2. Detect floor
        floor = self._detect_floor(query, state)

        # 3. Detect zone/space reference
        zone_id = self._detect_zone(query, state)
        space_label = self._detect_space_label(query)

        # 4. Check for overview intent
        q_lower = query.lower()
        if any(kw in q_lower for kw in _OVERVIEW_KEYWORDS):
            return self._build_overview_result(pipeline, building_id, building_name)

        # 4b. Zone ID detected but no floor stated → infer floor from zone prefix (e.g. "3.12" → floor 3)
        if floor is None and zone_id:
            try:
                floor = int(zone_id.split(".")[0])
            except (ValueError, IndexError):
                pass

        # 5. Cross-floor search if user mentions a space type/name but no floor
        if floor is None and (
            space_label or any(kw in q_lower for kw in _LOCATION_KEYWORDS)
        ):
            search_term = space_label or query
            results = self._search_across_floors(
                search_term, pipeline, building_id, building_name
            )
            if results:
                return self._build_search_result(query, results, building_id, building_name)

        # 6. Floor is None → ask which floor
        available = self._available_floors(pipeline, building_id)
        if floor is None:
            if not available:
                return FloorPlanResult(
                    building_id=building_id,
                    markdown=(
                        "I don't have floor plans loaded yet for the "
                        f"{building_name} Building. "
                        "Please check that PDF files are placed in the `/app/input/` folder."
                    ),
                    interactive=False,
                )
            floor_list = " • ".join(
                _floor_label(f) for f in available
            )
            return FloorPlanResult(
                building_id=building_id,
                markdown=(
                    f"I have floor plans for the **{building_name} Building** covering:\n\n"
                    f"**{floor_list}**\n\n"
                    "Which floor would you like to see?\n\n"
                    "You can also ask things like:\n"
                    '- *"Where is the server room?"*\n'
                    '- *"Show me all meeting rooms"*\n'
                    '- *"Give me a building overview"*'
                ),
                interactive=False,
            )

        # 7. Load the manifest for this floor
        manifest = pipeline.load_manifest(building_id, floor)
        if manifest is None:
            return FloorPlanResult(
                building_id=building_id,
                floor=floor,
                markdown=(
                    f"I don't have a floor plan for Floor {floor} of the "
                    f"{building_name} Building. "
                    f"Available floors: {', '.join(str(f) for f in available)}."
                ),
                interactive=False,
            )

        # 8. Branch A: space known → full resolution
        selected_space: Optional[Space] = None
        if zone_id:
            selected_space = self._find_space_by_zone(manifest, zone_id)
        if selected_space is None and space_label:
            selected_space = self._find_space_by_label(manifest, space_label)

        if selected_space:
            return self._build_space_result(selected_space, manifest, query)

        # 9. Branch B: floor known, space unknown → disambiguation
        return self._build_disambiguation_result(manifest, query)

    # ── Building/floor/space detection ───────────────────────────────────────

    def _detect_building(self, query: str, state: ConversationState) -> str:
        # Phase 4 — precedence: floor_context > state.building_id > default.
        # The BuildingRegistry alias map (consulted by the pipeline) translates
        # the logical id to whichever slug the manifest is stored under.
        if state.floor_context and state.floor_context.get("building_id"):
            return state.floor_context["building_id"]
        if state.building_id:
            return state.building_id
        return _DEFAULT_BUILDING_ID

    def _detect_floor(self, query: str, state: ConversationState) -> Optional[int]:
        # "floor 5", "level 5"
        m = _FLOOR_RE.search(query)
        if m:
            return int(m.group(1))
        # "5th floor", "1st floor"
        m = _ORDINAL_FLOOR_RE.search(query)
        if m:
            return int(m.group(1))
        # "fifth floor", "ground floor"
        m = _WORD_FLOOR_RE.search(query)
        if m:
            return _WORD_ORDINAL_MAP.get(m.group(1).lower())
        # "top floor" / "highest floor" → maximum available floor
        if _TOP_FLOOR_RE.search(query):
            available = self._available_floors(
                get_floor_plan_pipeline(),
                self._detect_building(query, state),
            )
            if available:
                return max(available)
        if state.floor_context:
            return state.floor_context.get("floor")
        return None

    def _detect_zone(self, query: str, state: ConversationState) -> Optional[str]:
        m = _ZONE_RE.search(query)
        if m:
            return m.group(0)
        # Fall back to previously resolved zone
        if state.floor_context:
            return state.floor_context.get("zone")
        prior = (state.intermediate_results or {}).get("user_context", {})
        return prior.get("resolved_zone")

    def _detect_space_label(self, query: str) -> Optional[str]:
        """
        Extract a space/room name from a natural-language query.
        e.g. "Where is the server room?" → "server room"
        """
        q_lower = query.lower()
        # Remove question words and navigation phrases
        for prefix in [
            "where is the", "where is", "where are the", "where are",
            "find the", "find", "locate the", "locate",
            "how do i get to the", "how do i get to",
            "navigate to the", "navigate to",
            "show me the", "show me",
            "which floor has the", "which floor has",
        ]:
            if q_lower.startswith(prefix):
                remainder = query[len(prefix):].strip(" ?")
                if remainder and len(remainder) > 2:
                    return remainder
                break
        return None

    # ── Available floors ──────────────────────────────────────────────────────

    def _available_floors(
        self, pipeline, building_id: str
    ) -> List[int]:
        # Phase 4 — accept both the primary building_id and its aliases when
        # matching manifests on disk (legacy slug paths remain valid).
        candidates: set = {building_id}
        try:
            candidates.update(pipeline._candidate_building_ids(building_id))
        except Exception:
            pass
        return sorted(
            fl for bid, fl in pipeline.list_manifests() if bid in candidates
        )

    # ── Space lookup ──────────────────────────────────────────────────────────

    def _find_space_by_zone(
        self, manifest: FloorPlanManifest, zone_id: str
    ) -> Optional[Space]:
        for space in manifest.spaces:
            if space.zone_id == zone_id or space.id.endswith(zone_id):
                return space
        return None

    def _find_space_by_label(
        self, manifest: FloorPlanManifest, label: str
    ) -> Optional[Space]:
        label_lower = label.lower()
        # Exact match first
        for space in manifest.spaces:
            if space.label.lower() == label_lower:
                return space
        # Substring match
        for space in manifest.spaces:
            if label_lower in space.label.lower() or space.label.lower() in label_lower:
                return space
        # Tag / type match
        for space in manifest.spaces:
            if label_lower in space.type.lower() or label_lower in " ".join(space.tags):
                return space
        return None

    # ── Cross-floor search ────────────────────────────────────────────────────

    def _search_across_floors(
        self,
        query: str,
        pipeline,
        building_id: str,
        building_name: str,
    ) -> List[Dict[str, Any]]:
        """Search all floors for spaces matching query by label/type."""
        query_lower = query.lower()
        results: List[Dict[str, Any]] = []

        for bid, floor in pipeline.list_manifests():
            if bid != building_id:
                continue
            manifest = pipeline.load_manifest(bid, floor)
            if not manifest:
                continue
            for space in manifest.spaces:
                score = 0
                if query_lower in space.label.lower():
                    score += 3
                if query_lower in space.type.lower():
                    score += 2
                if any(query_lower in tag.lower() for tag in space.tags):
                    score += 1
                if score > 0:
                    results.append(
                        {
                            "floor": floor,
                            "floor_label": manifest.floor_label,
                            "space": space,
                            "image_url": self._abs(manifest.rendered_image.png_url),
                            "pdf_url": self._abs(manifest.pdf_url),
                            "score": score,
                        }
                    )

        results.sort(key=lambda r: (-r["score"], r["floor"]))
        return results

    # ── Result builders ───────────────────────────────────────────────────────

    def _build_space_result(
        self,
        space: Space,
        manifest: FloorPlanManifest,
        query: str,
    ) -> FloorPlanResult:
        floor_label = manifest.floor_label
        pdf_url = self._abs(manifest.pdf_url)
        image_url = self._abs(manifest.rendered_image.png_url)
        thumb_url = self._abs(manifest.rendered_image.thumbnail_url)

        md_lines = [
            f"## 🏢 {manifest.building_name} — {floor_label}",
            "",
            f"**Space found:** {space.label}  |  Type: *{space.type.replace('_', ' ').title()}*",
            f"**Zone ID:** `{space.zone_id}`",
        ]
        if space.ontology_iri:
            md_lines.append(f"**Ontology IRI:** `{space.ontology_iri}`")
        md_lines += [
            "",
            f"📄 **[View {floor_label} Plan (PDF)]({pdf_url})**",
            "",
            "💬 *Would you like to:*",
            f"- See **live sensor data** for {space.label}?",
            f"- Get an **air quality or temperature report** for {floor_label}?",
        ]

        return FloorPlanResult(
            building_id=manifest.building_id,
            floor=manifest.floor,
            selected_space=space,
            manifest_url=f"/api/v1/floor-plans/{manifest.building_id}/{manifest.floor}/manifest",
            image_url=image_url,
            thumbnail_url=thumb_url,
            pdf_url=pdf_url,
            interactive=True,
            markdown="\n".join(md_lines),
        )

    def _build_disambiguation_result(
        self, manifest: FloorPlanManifest, query: str
    ) -> FloorPlanResult:
        floor_label = manifest.floor_label
        pdf_url = self._abs(manifest.pdf_url)
        image_url = self._abs(manifest.rendered_image.png_url)
        thumb_url = self._abs(manifest.rendered_image.thumbnail_url)

        # Group spaces by type for a clean menu
        by_type: Dict[str, List[Space]] = {}
        for space in manifest.spaces:
            by_type.setdefault(space.type, []).append(space)

        md_lines = [
            f"## 🏢 {manifest.building_name} — {floor_label}",
            "",
            f"📄 **[Open {floor_label} Plan (PDF)]({pdf_url})**",
            "",
            f"I've pulled up the floor plan for **{floor_label}**. "
            "Use the plan above to locate the room or zone you're interested in.",
            "",
        ]

        if by_type:
            md_lines.append("**Spaces on this floor:**")
            for stype, spaces in sorted(by_type.items()):
                if stype == "zone":
                    zones_str = ", ".join(f"`{s.zone_id}`" for s in spaces[:12])
                    if len(spaces) > 12:
                        zones_str += f" … (+{len(spaces) - 12} more)"
                    md_lines.append(f"- **Sensor zones:** {zones_str}")
                else:
                    labels_str = ", ".join(f"**{s.label}**" for s in spaces[:6])
                    md_lines.append(
                        f"- **{stype.replace('_', ' ').title()}:** {labels_str}"
                    )

        md_lines += [
            "",
            "💬 Which zone or room would you like sensor data for?  "
            "(e.g. *\"zone 3.12\"* or *\"the meeting room\"*)",
        ]

        return FloorPlanResult(
            building_id=manifest.building_id,
            floor=manifest.floor,
            candidates=manifest.spaces,
            manifest_url=f"/api/v1/floor-plans/{manifest.building_id}/{manifest.floor}/manifest",
            image_url=image_url,
            thumbnail_url=thumb_url,
            pdf_url=pdf_url,
            interactive=True,
            markdown="\n".join(md_lines),
        )

    def _build_search_result(
        self,
        query: str,
        results: List[Dict[str, Any]],
        building_id: str,
        building_name: str,
    ) -> FloorPlanResult:
        md_lines = [
            f'## 🔍 Location Search: "{query}"',
            f"Found **{len(results)}** match(es) in the **{building_name} Building**:",
            "",
        ]
        spaces_found: List[Space] = []
        for r in results[:8]:
            space = r["space"]
            spaces_found.append(space)
            pdf_url = r["pdf_url"]
            floor_label = r["floor_label"]
            zone_str = f" (Zone `{space.zone_id}`)" if space.zone_id else ""
            type_str = f" — *{space.type.replace('_', ' ').title()}*" if space.type not in ("unknown", "zone") else ""
            md_lines.append(
                f"- **{floor_label}**: {space.label}{zone_str}{type_str} "
                f"[📄 View Plan]({pdf_url})"
            )

        md_lines += [
            "",
            "💬 *Would you like sensor data for any of these locations? Just say which one.*",
        ]

        # Pick the best floor to show the image for
        best = results[0]
        return FloorPlanResult(
            building_id=building_id,
            floor=best["floor"],
            candidates=spaces_found,
            image_url=best["image_url"],
            pdf_url=best["pdf_url"],
            interactive=True,
            markdown="\n".join(md_lines),
        )

    def _build_overview_result(
        self,
        pipeline,
        building_id: str,
        building_name: str,
    ) -> FloorPlanResult:
        floors = [
            fl for bid, fl in pipeline.list_manifests() if bid == building_id
        ]
        if not floors:
            return FloorPlanResult(
                building_id=building_id,
                markdown=f"No floor plans are available for the {building_name} Building.",
                interactive=False,
            )

        md_lines = [
            f"## 🏢 {building_name} Building — Floor Overview",
            "",
        ]

        for floor in sorted(floors):
            manifest = pipeline.load_manifest(building_id, floor)
            if not manifest:
                continue
            pdf_url = self._abs(manifest.pdf_url)
            floor_label = manifest.floor_label

            # Count spaces by type
            type_counts: Dict[str, int] = {}
            for space in manifest.spaces:
                type_counts[space.type] = type_counts.get(space.type, 0) + 1

            summary_parts = []
            for stype, count in sorted(type_counts.items()):
                if stype != "zone":
                    label = stype.replace("_", " ").title()
                    summary_parts.append(f"{count} {label}{'s' if count > 1 else ''}")
            zone_count = type_counts.get("zone", 0)

            md_lines.append(f"### [{floor_label} 📄]({pdf_url})")
            if summary_parts:
                md_lines.append(f"**Spaces:** {', '.join(summary_parts)}")
            if zone_count:
                md_lines.append(f"**Sensor zones:** {zone_count}")
            if manifest.warnings:
                md_lines.append(f"⚠️ *{manifest.warnings[0]}*")
            md_lines.append("")

        md_lines.append(
            "💬 *Which floor would you like to explore? "
            "Or ask \"where is the server room?\" to search across all floors.*"
        )

        return FloorPlanResult(
            building_id=building_id,
            interactive=True,
            markdown="\n".join(md_lines),
        )

    # ── URL helper ────────────────────────────────────────────────────────────

    def _abs(self, rel_url: str) -> str:
        """Convert a relative URL to an absolute one using the static base URL."""
        if rel_url.startswith("http"):
            return rel_url
        return f"{self._base_url}{rel_url}"


def _floor_label(floor: int) -> str:
    if floor == 0:
        return "Ground Floor"
    return f"Floor {floor}"


# ── Module-level singleton ─────────────────────────────────────────────────────
_agent: Optional[FloorPlanAgent] = None


def get_floor_plan_agent() -> FloorPlanAgent:
    global _agent
    if _agent is None:
        try:
            from shared.config import settings

            base = getattr(settings, "STATIC_BASE_URL", "http://localhost:8080")
        except Exception:
            base = "http://localhost:8080"
        _agent = FloorPlanAgent(static_base_url=base)
    return _agent
