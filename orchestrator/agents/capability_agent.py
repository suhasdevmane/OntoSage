"""
CapabilityAgent — answers CAPABILITY and off-ontology (OTHER) queries
from a structured per-building Knowledge Base (input/<bldg>/capability.yaml).

Survey justification:
  CAPABILITY = 25.6% of corpus (P1); OTHER = 24.0%.
  Together ~50% of queries have no grounded path in SPARQL/SQL.
  Fire Safety (#3 Borda) and Security (#4 Borda) are dominated by this stratum.
"""

from pathlib import Path
from typing import Any, Dict, List

from shared.capability_schema import CapabilityKB, CapabilityEntry
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Capability KBs keyed by building_id.  Loaded lazily on first use.
_KB_CACHE: Dict[str, CapabilityKB] = {}

# Where building-specific input files live (inside the container)
_INPUT_ROOT = Path("/app/input")
# During local dev/tests fall back to the repo's input/ directory
_LOCAL_INPUT_ROOT = Path(__file__).resolve().parents[2] / "input"


def _load_kb(building_id: str) -> CapabilityKB | None:
    """Load (and cache) the capability KB for a building, or return None."""
    if building_id in _KB_CACHE:
        return _KB_CACHE[building_id]

    for root in (_INPUT_ROOT, _LOCAL_INPUT_ROOT):
        yaml_path = root / building_id / "capability.yaml"
        if yaml_path.exists():
            try:
                kb = CapabilityKB.from_yaml(yaml_path)
                _KB_CACHE[building_id] = kb
                logger.info(
                    f"[capability] Loaded KB for {building_id}: "
                    f"{len(kb.capabilities)} entries from {yaml_path}"
                )
                return kb
            except Exception as exc:
                logger.warning(f"[capability] Failed to load KB at {yaml_path}: {exc}")

    logger.warning(f"[capability] No capability.yaml found for building '{building_id}'")
    return None


def _format_entry(entry: CapabilityEntry, building_name: str) -> str:
    return (
        f"**{entry.category.replace('_', ' ').title()}**\n\n"
        f"{entry.content.strip()}\n\n"
        f"*Source: {entry.source or building_name + ' building profile'}*"
    )


class CapabilityAgent:
    """
    Answers building capability and off-ontology questions from the KB.
    Returns grounded answers with provenance, or an explicit boundary statement.
    Never hallucinate — if the KB has no entry, say so clearly.
    """

    async def answer(self, state: ConversationState) -> ConversationState:
        """Node function — called by the LangGraph workflow capability node."""
        logger.info(
            f"[capability] intent={state.current_intent}, "
            f"building={state.building_id}"
        )

        user_query = state.messages[-1].content if state.messages else ""
        building_id = state.building_id or "bldg1"

        kb = _load_kb(building_id)

        if kb is None:
            state.intermediate_results["capability_result"] = {
                "success": False,
                "response": (
                    "I don't have a capability profile on record for this building yet. "
                    "Please contact facility management directly for building-specific "
                    "information."
                ),
                "provenance": "no_kb",
            }
            return state

        # ── Read pre-fetched semantic matches populated by SemanticRouter ──
        # The dialogue agent embeds the query and queries the per-building Qdrant
        # collection BEFORE this node runs; matches land in state.intermediate_results.
        # When matches are present (the normal case), use them directly — they're
        # ranked by semantic similarity and are more accurate than keyword search.
        # When absent (Qdrant outage with fallback=skip, or non-capability route
        # leaked through), respond with the explicit "no info" boundary message.
        matches: List[CapabilityEntry] = []
        pre_fetched = state.intermediate_results.get("capability_matches") or []
        if pre_fetched:
            # SemanticRouter returns CapabilityMatch objects with .entry attribute.
            # Defensive: filter Nones (entry might be None if KB was stale during routing).
            matches = [m.entry for m in pre_fetched if getattr(m, "entry", None) is not None]
            if matches:
                logger.info(
                    f"[capability] using {len(matches)} pre-fetched semantic match(es): "
                    f"{[e.id for e in matches]}"
                )

        if not matches:
            # Explicit, honest boundary — do not guess or hallucinate
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": (
                    f"I don't have that specific information on record for "
                    f"**{kb.building.name}**. For building-specific queries please "
                    f"contact facility management at estates@cardiff.ac.uk or call "
                    f"the estates helpdesk (029 2087 6026)."
                ),
                "provenance": "kb_no_match",
                "building_name": kb.building.name,
            }
            return state

        # Build a grounded response from matched entries
        parts: List[str] = [
            f"Here is the information I have on record for **{kb.building.name}**:\n"
        ]
        for entry in matches:
            parts.append(_format_entry(entry, kb.building.name))

        parts.append(
            "\n---\n*This information comes from the building's capability profile. "
            "For the most up-to-date details, contact facility management.*"
        )

        response_text = "\n\n".join(parts)

        state.intermediate_results["capability_result"] = {
            "success": True,
            "response": response_text,
            "provenance": "capability_kb",
            "matched_categories": [e.category for e in matches],
            "building_name": kb.building.name,
        }

        logger.info(
            f"[capability] Answered from KB: matched categories="
            f"{[e.category for e in matches]}"
        )
        return state
