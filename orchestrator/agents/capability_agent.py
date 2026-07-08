"""
CapabilityAgent — answers CAPABILITY and off-ontology (OTHER) queries
from a structured per-building Knowledge Base (input/<bldg>/capability.yaml).

Survey justification:
  CAPABILITY = 25.6% of corpus (P1); OTHER = 24.0%.
  Together ~50% of queries have no grounded path in SPARQL/SQL.
  Fire Safety (#3 Borda) and Security (#4 Borda) are dominated by this stratum.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.capability_schema import CapabilityEntry, CapabilityKB
from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Capability KBs keyed by building_id.  Loaded lazily on first use.
_KB_CACHE: Dict[str, CapabilityKB] = {}

# Minimum capability KB score before we also search the document collection.
# If no pre-fetched semantic matches exist OR the top score is below this threshold,
# the agent additionally searches documents_<bldg> for policy / manual content.
_DOC_FALLBACK_SCORE_THRESHOLD = 0.55

# Where building-specific input files live (inside the container)
_INPUT_ROOT = Path("/app/input")
# During local dev/tests fall back to the repo's input/ directory
_LOCAL_INPUT_ROOT = Path(__file__).resolve().parents[2] / "input"


def _load_kb(building_id: str) -> CapabilityKB | None:
    """Load (and cache) the capability KB for a building, or return None."""
    if building_id in _KB_CACHE:
        return _KB_CACHE[building_id]

    for root in (_INPUT_ROOT, _LOCAL_INPUT_ROOT):
        # Try the NESTED layout (input/<id>/capability.yaml) first, then the
        # FLAT layout (input/capability.yaml) — the active single-building
        # layout, where bldg1's capability.yaml lives after the nested dir was
        # removed. Without the flat fallback the agent reported "no capability
        # profile" despite the KB being present and indexed.
        for yaml_path in (
            root / building_id / "capability.yaml",
            root / "capability.yaml",
        ):
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


# Module-level clients used by _search_documents.  Initialized via init_document_search().
_doc_qdrant_client: Optional[Any] = None
_doc_embedding_service: Optional[Any] = None


def init_document_search(qdrant_client: Any, embedding_service: Any) -> None:
    """Call from main.py lifespan to wire up the document search dependencies."""
    global _doc_qdrant_client, _doc_embedding_service
    _doc_qdrant_client = qdrant_client
    _doc_embedding_service = embedding_service


async def _search_documents(query: str, building_id: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Search the per-building documents collection.  Returns [] on any failure."""
    if not query.strip() or _doc_qdrant_client is None or _doc_embedding_service is None:
        return []
    try:
        from orchestrator.services.document_indexer import search_documents

        return await search_documents(
            _doc_qdrant_client, _doc_embedding_service, query, building_id, top_k=top_k
        )
    except Exception as e:
        logger.debug(f"[capability] document search unavailable: {e}")
        return []


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
        logger.info(f"[capability] intent={state.current_intent}, " f"building={state.building_id}")

        building_id = state.building_id or settings.BUILDING_ID

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

        # ── Document KB fallback ─────────────────────────────────────────────
        # When capability KB has no matches, also search the documents collection
        # (policies, manuals, governance) so policy questions get grounded answers.
        doc_hits: List[Dict[str, Any]] = []
        if not matches:
            doc_hits = await _search_documents(
                state.user_message or "",
                building_id,
            )
            if doc_hits:
                logger.info(
                    f"[capability] KB no match → doc fallback: {len(doc_hits)} chunk(s) "
                    f"from {set(h['doc_name'] for h in doc_hits)}"
                )

        if not matches and not doc_hits:
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

        if doc_hits and not matches:
            # Build response from document chunks with citation
            parts: List[str] = [f"Here is what I found in **{kb.building.name}** documentation:\n"]
            seen_docs: set = set()
            for hit in doc_hits:
                doc_label = hit["doc_name"].replace("_", " ").title()
                if doc_label not in seen_docs:
                    parts.append(f"**From: {doc_label}**\n")
                    seen_docs.add(doc_label)
                parts.append(hit["text"])
            parts.append(
                "\n---\n*Source: building policy documents. "
                "For the most current version, contact facility management.*"
            )
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": "\n\n".join(parts),
                "provenance": "document_kb",
                "doc_sources": list(seen_docs),
                "building_name": kb.building.name,
            }
            return state

        # Build a grounded response from capability KB matched entries
        parts = [f"Here is the information I have on record for **{kb.building.name}**:\n"]
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
            f"[capability] Answered from KB: matched categories=" f"{[e.category for e in matches]}"
        )
        return state
