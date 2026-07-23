"""
CapabilityAgent — answers CAPABILITY and off-ontology (OTHER) queries
from a structured per-building Knowledge Base (input/<bldg>/capability.yaml).

Survey justification:
  CAPABILITY = 25.6% of corpus (P1); OTHER = 24.0%.
  Together ~50% of queries have no grounded path in SPARQL/SQL.
  Fire Safety (#3 Borda) and Security (#4 Borda) are dominated by this stratum.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.capability_schema import CapabilityEntry, CapabilityKB
from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Capability KBs keyed by building_id.  Loaded lazily on first use.
_KB_CACHE: Dict[str, CapabilityKB] = {}

# Count / area questions must be answered from the live graph + floor plans, never from
# frozen KB prose. When one of these matches, BuildingMetrics supplies authoritative live
# figures (see answer()); any KB entry that names a number is demoted to background context.
_METRICS_RE = re.compile(
    r"(how many\s+(sensors?|points?|zones?|rooms?|floors?|devices?|cameras?)"
    r"|(sensor|point|device)\s+count"
    r"|number of\s+(sensors?|points?|zones?|rooms?|floors?)"
    r"|total\s+(area|floor\s*area|sensors?|number of)"
    r"|floor\s*area|net internal area"
    r"|how (big|large) is the building"
    r"|square\s*(met(er|re)s?|m2|m²))",
    re.IGNORECASE,
)


def _is_metrics_question(query: str) -> bool:
    return bool(_METRICS_RE.search(query or ""))


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

        # The default 0.35 floor is calibrated for OpenAI (1536-d) embeddings; local MiniLM
        # (384-d) scores lower, so borderline-relevant capability docs (e.g. wifi) fall
        # through. Relax the floor for local embeddings — this is the capability node's prose
        # fallback, so surfacing the best-matching doc beats an honest "no info".
        threshold = 0.28 if settings.EMBEDDING_PROVIDER == "local" else 0.35
        return await search_documents(
            _doc_qdrant_client,
            _doc_embedding_service,
            query,
            building_id,
            top_k=top_k,
            score_threshold=threshold,
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

        # ── Live-metrics grounding ───────────────────────────────────────────
        # Count / area questions are answered from the graph + floor plans at request
        # time, never from frozen numbers in capability.yaml. The live figures are
        # authoritative; any KB entry that names a number is demoted to background.
        if _is_metrics_question(state.user_message or ""):
            try:
                from orchestrator.services.building_metrics import (
                    get_building_metrics,
                    render_metrics_block,
                )

                snap = await get_building_metrics().snapshot(building_id)
                if snap.has_counts() or snap.has_area():
                    block = render_metrics_block(snap, kb.building.name)
                    pf = state.intermediate_results.get("capability_matches") or []
                    bg_entries = [m.entry for m in pf if getattr(m, "entry", None) is not None]
                    bg = (
                        "\n\n" + "\n\n".join(_format_entry(e, kb.building.name) for e in bg_entries)
                        if bg_entries
                        else ""
                    )
                    state.intermediate_results["capability_result"] = {
                        "success": True,
                        "response": (
                            block + bg + "\n\n*These figures are computed live from the "
                            "building's ontology and floor plans.*"
                        ),
                        "provenance": "live_metrics",
                        "building_name": kb.building.name,
                    }
                    logger.info("[capability] answered metrics question from live graph")
                    return state
            except Exception as e:
                logger.warning(f"[capability] live metrics grounding failed, using KB: {e}")

        # ── Capability facts from ontology triples (TTL-first, ROADMAP-009) ──
        # Structured amenities (lift, prayer room, café, …) are answered from triples,
        # not frozen KB prose. Only fires on a confident lay-term match; otherwise falls
        # through to the semantic KB below.
        try:
            from orchestrator.services.capability_graph_resolver import (
                get_capability_graph_resolver,
            )

            _facts = await get_capability_graph_resolver().resolve(state.user_message or "")
            if _facts:
                _parts = [f"Here is what I found for **{kb.building.name}**:\n"]
                _parts.extend(f.render() for f in _facts)
                _parts.append("\n*Answered live from the building ontology (triples).*")
                state.intermediate_results["capability_result"] = {
                    "success": True,
                    "response": "\n\n".join(_parts),
                    "provenance": "capability_graph",
                    "building_name": kb.building.name,
                }
                logger.info(
                    f"[capability] answered from ontology triples: {[f.label for f in _facts]}"
                )
                return state
        except Exception as e:
            logger.warning(f"[capability] graph resolver failed, using KB: {e}")

        # ── Read pre-fetched semantic matches populated by SemanticRouter ──
        # The dialogue agent embeds the query and queries the per-building Qdrant
        # collection BEFORE this node runs; matches land in state.intermediate_results.
        # When matches are present (the normal case), use them directly — they're
        # ranked by semantic similarity and are more accurate than keyword search.
        # When absent (Qdrant outage with fallback=skip, or non-capability route
        # leaked through), respond with the explicit "no info" boundary message.
        # Read the KB matches pre-fetched by the router — always kept as a safety net
        # (SemanticRouter returns CapabilityMatch objects with an .entry attribute).
        matches: List[CapabilityEntry] = []
        pre_fetched = state.intermediate_results.get("capability_matches") or []
        if pre_fetched:
            matches = [m.entry for m in pre_fetched if getattr(m, "entry", None) is not None]

        # ── Answer-source ordering (ROADMAP-009 WS-4) ────────────────────────────
        # TTL-first (CAPABILITIES_TTL_FIRST): documents preferred, with the capability.yaml
        #   KB as the safety net for local-embedding retrieval gaps (e.g. wifi @0.248):
        #   graph (above) → documents → KB → honest "no info".
        # Legacy: KB matches preferred, documents as the fallback.
        ttl_first = settings.CAPABILITIES_TTL_FIRST
        doc_hits: List[Dict[str, Any]] = []
        if ttl_first or not matches:
            doc_hits = await _search_documents(state.user_message or "", building_id)
        if ttl_first and doc_hits:
            matches = []  # prefer documents; the KB answers only when documents miss
        if doc_hits:
            logger.info(
                f"[capability] doc match: {len(doc_hits)} chunk(s) "
                f"from {set(h['doc_name'] for h in doc_hits)}"
            )
        elif matches:
            logger.info(
                f"[capability] KB match: {[e.id for e in matches]}"
                + (" (TTL-first safety-net fallback)" if ttl_first else "")
            )

        if not matches and not doc_hits:
            # Explicit, honest boundary — do not guess or hallucinate
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": (
                    f"I don't have that specific information on record for "
                    f"**{kb.building.name}**. For building-specific queries please "
                    f"contact your building's facilities / estates management team."
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
