"""
CapabilityAgent — answers CAPABILITY and off-ontology (OTHER) queries.

TTL-first, SINGLE path (TODO-012). Capabilities are ``ontosage:Amenity`` /
``ontosage:KnowledgeTopic`` TRIPLES in the building's ontology — authored via the admin
Capabilities GUI (``/api/v1/admin/capabilities``) or by writing the OCBV TBox terms
(``input/ontosage_schema.ttl``) — and answered by the CapabilityGraphResolver. Genuinely
uploaded manuals/policies live in the per-building document KB (``documents_<bldg>``).
There is no ``capability.yaml`` and no Qdrant capability-KB anymore — both were removed.

Answer chain — each source is independent and OPTIONAL; NONE is a precondition for the
next (locked by tests/test_capability_bare_building.py):

    live building metrics  →  ontology triples  →  uploaded documents  →  honest "no info"

Building-agnostic: the display name and namespace resolve from the active building's
config/graph, never from a per-building literal. A building with no capability triples and
no documents honestly declines — it does not fabricate.

Survey justification:
  CAPABILITY = 25.6% of corpus (P1); OTHER = 24.0% — together ~50% of queries have no
  grounded path in SPARQL/SQL. Fire Safety (#3 Borda) and Security (#4 Borda) live here.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Count / area questions are answered from the live graph + floor plans (BuildingMetrics),
# never from frozen prose. When one of these matches, a TBOX SPARQL COUNT + DWG area supplies
# the authoritative live figures.
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


# Where building-specific input files live (inside the container); repo input/ for local dev.
_INPUT_ROOT = Path("/app/input")
_LOCAL_INPUT_ROOT = Path(__file__).resolve().parents[2] / "input"

# Module-level clients used by _search_documents.  Initialized via init_document_search().
_doc_qdrant_client: Optional[Any] = None
_doc_embedding_service: Optional[Any] = None


def init_document_search(qdrant_client: Any, embedding_service: Any) -> None:
    """Call from main.py lifespan to wire up the document search dependencies."""
    global _doc_qdrant_client, _doc_embedding_service
    _doc_qdrant_client = qdrant_client
    _doc_embedding_service = embedding_service


async def _search_documents(
    query: str, building_id: str, top_k: int = 3, only_document: str = ""
) -> List[Dict[str, Any]]:
    """Search the per-building uploaded-documents collection.  Returns [] on any failure.

    ``only_document`` scopes the search to the file the ontology declared for this
    topic (``ontosage:documentRef``) — see search_documents for why that matters.
    """
    if not query.strip() or _doc_qdrant_client is None or _doc_embedding_service is None:
        return []
    try:
        from orchestrator.services.document_indexer import search_documents

        # Honesty floor: the capability node must NOT surface a document that was too
        # weak to ROUTE here. The floor now comes from the loaded MODEL rather than a
        # constant branching on provider name — the old code applied 0.50 to anything
        # "local", a value calibrated for MiniLM at 384 dimensions while bge-large at
        # 1024 was the model actually running. Override with DOCUMENT_SCORE_FLOOR.
        threshold = settings.document_score_floor
        return await search_documents(
            _doc_qdrant_client,
            _doc_embedding_service,
            query,
            building_id,
            top_k=top_k,
            score_threshold=threshold,
            only_document=only_document or None,
        )
    except Exception as e:
        logger.debug(f"[capability] document search unavailable: {e}")
        return []


class CapabilityAgent:
    """
    Answers building capability / off-ontology questions from the building's own data.
    Returns a grounded answer with provenance, or an explicit boundary statement.
    Never hallucinate — if no source has the fact, say so clearly.
    """

    @staticmethod
    def _unverified_referent_result(referent: str, building_name: str) -> Dict[str, Any]:
        """The honest reply when an existence check could not COMPLETE (BUG-136).

        Distinct from "not found": the thing may well exist, we simply could not
        confirm it in time. Saying so costs one retry; proceeding costs a
        confident answer about something unverified.
        """
        return {
            "success": True,
            "response": (
                f"I couldn't verify **{referent}** against **{building_name}**'s model just "
                "now — the existence check didn't complete in time. Rather than give you "
                "figures that might belong to something else, I'd rather you ask again in "
                "a moment."
            ),
            "provenance": "referent_unverified",
            "building_name": building_name,
        }

    @staticmethod
    async def _absent_referent_decline(
        state: ConversationState, building_id: str, building_name: str
    ) -> Optional[Dict[str, Any]]:
        """Refuse a whole-building answer when the question names a place that isn't there.

        Returns a capability_result to send back, or None to carry on.

        Failure handling is ASYMMETRIC by design (BUG-136). For a question that
        names nothing, any error fails open — there is nothing to fabricate about.
        But once a referent IS named, a check that cannot complete must not become
        "proceed": under back-to-back load the resolver's SPARQL timed out, the
        SKIPPED status sailed through, and a count question about a pool this
        building does not have was answered with whole-building figures — the
        guard dropping out exactly when the system is busiest. Failing open on a
        legitimate question loses one answer; failing open on an existence check
        produces a confident fabrication. Those costs are not symmetrical, so
        neither is this code.
        """
        if not getattr(settings, "REFERENT_VALIDATION_ENABLED", True):
            return None
        query = state.user_message or ""
        typed_phrase = ""
        try:
            from orchestrator.agents.sparql_agent import SPARQLAgent, _active_namespace
            from orchestrator.services.grounding_guard import SUBJECT_SPACE, enablement_hint
            from orchestrator.services.referent_resolver import (
                NOT_FOUND,
                SKIPPED,
                ReferentResolver,
                detect_typed_referent,
            )

            # Only questions that NAME something are gated: "how many sensors are
            # there?" is a whole-building question and must keep its answer.
            typed = detect_typed_referent(query)
            if typed is None:
                return None
            typed_phrase = typed.phrase

            resolution = await ReferentResolver(SPARQLAgent()._execute_query).resolve(
                query=query,
                entities=state.intermediate_results.get("entities", []),
                namespace=_active_namespace(),
                building_name=building_name,
            )

            if resolution.status == SKIPPED:
                logger.warning(
                    f"[capability] existence check for '{resolution.referent or typed_phrase}' "
                    "did not complete — refusing to assert rather than failing open (BUG-136)"
                )
                return CapabilityAgent._unverified_referent_result(
                    resolution.referent or typed_phrase, building_name
                )

            if resolution.status != NOT_FOUND:
                return None

            logger.info(
                f"[capability] '{resolution.referent}' is not in this building — declining "
                "rather than answering with whole-building figures"
            )
            return {
                "success": True,
                "response": (
                    f"I couldn't find **{resolution.referent}** in **{building_name}**'s model, "
                    "so I can't give you figures for it — the counts I hold describe other "
                    "parts of the building, and reporting them here would suggest this one "
                    "exists.\n\n" + enablement_hint(SUBJECT_SPACE, resolution.referent)
                ),
                "provenance": "referent_not_found",
                "building_name": building_name,
            }
        except Exception as e:
            if typed_phrase:
                # The question named something and the check ERRORED — same
                # asymmetry as SKIPPED above: refuse to assert, do not fabricate.
                logger.warning(
                    f"[capability] existence check for '{typed_phrase}' errored — "
                    f"refusing to assert rather than failing open (BUG-136): {e}"
                )
                return CapabilityAgent._unverified_referent_result(typed_phrase, building_name)
            logger.warning(f"[capability] referent gate skipped (nothing named, failing open): {e}")
            return None

    async def answer(self, state: ConversationState) -> ConversationState:
        """Node function — called by the LangGraph workflow capability node.

        Single TTL-first chain: metrics → ontology triples → uploaded documents →
        honest "no info". Every source is optional; none gates another.
        """
        logger.info(f"[capability] intent={state.current_intent}, building={state.building_id}")

        building_id = state.building_id or settings.BUILDING_ID

        # Display name from the active building's config/graph — never a KB literal.
        from orchestrator.services.building_context import resolve_building_context

        building_name = resolve_building_context(building_id).name

        # ── 1. Live-metrics grounding ────────────────────────────────────────
        # Count / area questions → TBOX SPARQL COUNT (brick:Sensor/Point/Floor/Room) + DWG
        # area, computed now. Works on ANY building straight from the ontology.
        # A question that asks for a MEASUREMENT of a named place is gated before any
        # source is consulted. Gating only the metrics branch was not enough: "what is
        # the temperature on the rooftop helipad?" walked past it into the rest of the
        # chain and came back with temperature values for a helipad this building does
        # not have. The measurand test keeps it narrow — "is there a cafeteria?" names
        # a place but asks about existence, not a reading, and amenities are answered
        # from triples that the spatial resolver would not find.
        from orchestrator.services.plausibility import measurand_of

        if measurand_of(state.user_message or "") or _is_metrics_question(state.user_message or ""):
            _decline = await self._absent_referent_decline(state, building_id, building_name)
            if _decline:
                state.intermediate_results["capability_result"] = _decline
                return state
            try:
                from orchestrator.services.building_metrics import (
                    get_building_metrics,
                    render_metrics_block,
                )

                snap = await get_building_metrics().snapshot(building_id)
                if snap.has_counts() or snap.has_area():
                    block = render_metrics_block(snap, building_name)
                    state.intermediate_results["capability_result"] = {
                        "success": True,
                        "response": (
                            block + "\n\n*These figures are computed live from the "
                            "building's ontology and floor plans.*"
                        ),
                        "provenance": "live_metrics",
                        "building_name": building_name,
                    }
                    logger.info("[capability] answered metrics question from live graph")
                    return state
            except Exception as e:
                logger.warning(f"[capability] live metrics grounding failed: {e}")

        # ── 2. Ontology triples (ontosage:Amenity + ontosage:KnowledgeTopic) ──
        # The canonical capability source: physical amenities (lift, prayer room, café, …)
        # and knowledge topics (wifi, GDPR, fault-reporting, …) authored via the admin GUI /
        # OCBV TBox. Matched deterministically by lay-term — no embeddings, no capability.yaml.
        try:
            from orchestrator.services.capability_graph_resolver import (
                get_capability_graph_resolver,
            )

            _facts = await get_capability_graph_resolver().resolve(state.user_message or "")
            # BUG-103: lay-term matching can land on a loosely-related amenity — a
            # question about a swimming pool or a water tank's pH was answered with
            # "Catering Amenities". An amenity may only answer if it actually mentions
            # what was asked about (its label or its rendered text).
            if _facts:
                from orchestrator.services.grounding_guard import filter_on_topic as _on_topic

                _rendered = [
                    {"text": f.render(), "doc_name": getattr(f, "label", "")} for f in _facts
                ]
                _keep = {id(r) for r in _on_topic(state.user_message or "", _rendered)}
                _facts = [f for f, r in zip(_facts, _rendered) if id(r) in _keep]
            if _facts:
                _parts = [f"Here is what I found for **{building_name}**:\n"]
                # Being ABOUT the subject is not the same as ANSWERING the question.
                # A service-history question can match a topic that discusses the
                # equipment and carries no date at all; printed plainly that reads as
                # the answer. Say what is missing first (CAVEAT-108).
                from orchestrator.services.grounding_guard import missing_fact_caveat

                _caveat = missing_fact_caveat(
                    state.user_message or "", " ".join(f.render() for f in _facts)
                )
                if _caveat:
                    _parts.append(f"*{_caveat}*\n")
                _parts.extend(f.render() for f in _facts)
                # When the topic NAMES its governing document, draw the detail from
                # that document instead of leaving the user to find it. Retrieval is
                # scoped to the named file, so similarity only orders chunks inside a
                # document already known to be the right one — the corpus-tuned score
                # floor stops deciding which document is relevant.
                # getattr: the resolver is a duck-typed boundary, so a fact that
                # predates documentRef must degrade to "no linked document", never
                # take down the whole capability answer.
                _doc_ref = next(
                    (
                        getattr(f, "document_ref", "")
                        for f in _facts
                        if getattr(f, "document_ref", "")
                    ),
                    "",
                )
                _sources = ["building ontology (triples)"]
                if _doc_ref:
                    _extra = await _search_documents(
                        state.user_message or "", building_id, only_document=_doc_ref
                    )
                    if _extra:
                        _parts.append(
                            f"\nFrom the full policy document (**{_doc_ref}**):\n\n"
                            + _extra[0].get("text", "").strip()
                        )
                        _sources.append(f"document {_doc_ref}")
                        logger.info(f"[capability] detail scoped to declared document {_doc_ref}")
                _parts.append(f"\n*Answered live from the {' + '.join(_sources)}.*")
                state.intermediate_results["capability_result"] = {
                    "success": True,
                    "response": "\n\n".join(_parts),
                    "provenance": "capability_graph",
                    "building_name": building_name,
                }
                logger.info(
                    f"[capability] answered from ontology triples: {[f.label for f in _facts]}"
                )
                return state
        except Exception as e:
            logger.warning(f"[capability] graph resolver failed: {e}")

        # ── 2b. Brick-class inventory from the ontology (BUG-122) ────────────
        # Capabilities are what a building OFFERS (amenities, knowledge topics).
        # What it CONTAINS is already described in Brick, and nothing was reading
        # that half — so "what equipment is installed here?" declined while the
        # graph held 149 equipment instances. Matching the question's nouns
        # against Brick CLASS names keeps this portable: buildings name their
        # individual units differently but all type them from the same TBox.
        try:
            from orchestrator.services.ontology_inventory import (
                class_census,
                is_inventory_question,
                render_census,
            )

            if is_inventory_question(state.user_message or ""):
                from orchestrator.agents.sparql_agent import (
                    GRAPHDB_QUERY_ENDPOINT,
                    _active_namespace,
                )

                _rows = await class_census(
                    state.user_message or "", _active_namespace(), GRAPHDB_QUERY_ENDPOINT
                )
                _block = render_census(_rows, building_name)
                if _block:
                    state.intermediate_results["capability_result"] = {
                        "success": True,
                        "response": _block,
                        "provenance": "ontology_inventory",
                        "building_name": building_name,
                    }
                    logger.info(
                        f"[capability] answered inventory question from Brick classes: "
                        f"{[r[0] for r in _rows][:6]}"
                    )
                    return state
        except Exception as e:
            logger.warning(f"[capability] ontology inventory failed: {e}")

        # ── 3. Uploaded documents (documents_<bldg>) ─────────────────────────
        # Genuinely-uploaded manuals / policy PDFs, semantically retrieved. This is NOT a
        # capability.yaml fallback — it is a distinct source for long-form uploaded content.
        doc_hits = await _search_documents(state.user_message or "", building_id)
        # BUG-103: vector similarity alone is not grounding. The cosine floor above was
        # calibrated for one embedding model; under another (bge-large) generic building
        # prose clears it for ANY question, so an HVAC table was surfaced under "Here is
        # what I found…" for a question about pH. Require the passage to actually mention
        # what was asked about — model-agnostic and building-agnostic.
        if doc_hits:
            from orchestrator.services.grounding_guard import filter_on_topic

            _concept_vocab = [
                str(c.get("concept_id", "")).replace("_", " ")
                for c in (state.intermediate_results.get("concepts") or [])
                if isinstance(c, dict)
            ]
            doc_hits = filter_on_topic(
                state.user_message or "", doc_hits, extra_vocab=_concept_vocab
            )
        if doc_hits:
            seen_docs: set = set()
            parts: List[str] = [f"Here is what I found in **{building_name}** documentation:\n"]
            for hit in doc_hits:
                doc_label = hit["doc_name"].replace("_", " ").title()
                if doc_label not in seen_docs:
                    parts.append(f"**From: {doc_label}**\n")
                    seen_docs.add(doc_label)
                parts.append(hit["text"])
            parts.append(
                "\n---\n*Source: building documents. "
                "For the most current version, contact facility management.*"
            )
            logger.info(f"[capability] doc match: {len(doc_hits)} chunk(s) from {seen_docs}")
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": "\n\n".join(parts),
                "provenance": "document_kb",
                "doc_sources": list(seen_docs),
                "building_name": building_name,
            }
            return state

        # ── 4. Honest boundary — every source missed ─────────────────────────
        # BUG-103: a refusal must also say how to MAKE it answerable (connect-data →
        # get-answers), otherwise the user is left at a dead end with no next step.
        from orchestrator.services.grounding_guard import (
            SUBJECT_DOCUMENT,
            SUBJECT_SENSOR,
            enablement_hint,
        )

        _q = (state.user_message or "").lower()
        _kind = (
            SUBJECT_DOCUMENT
            if any(w in _q for w in ("policy", "manual", "procedure", "document", "guide", "say"))
            else SUBJECT_SENSOR
        )
        state.intermediate_results["capability_result"] = {
            "success": True,
            "response": (
                f"I don't have that specific information on record for **{building_name}**. "
                f"For building-specific queries please contact your building's facilities / "
                f"estates management team."
                f"{enablement_hint(_kind)}"
            ),
            "provenance": "no_match",
            "building_name": building_name,
        }
        logger.info("[capability] no source matched — honest boundary returned")
        return state
