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

_FLOOR_IN_Q_RE = re.compile(r"\b(?:floor|level|storey|story)\s*(-?\d+)\b", re.IGNORECASE)


def _floor_in_question(query: str) -> str:
    """The floor number a question names, as a bare string. "" when none."""
    m = _FLOOR_IN_Q_RE.search(query or "")
    return m.group(1) if m else ""


def _same_floor(declared: str, asked: str) -> bool:
    """Does an amenity's declared floor match the one asked for?

    Buildings spell it differently -- "Floor3", "3", "Level 3" -- so compare the
    digits rather than the string. A declaration with no digits never matches,
    instead of matching everything.
    """
    digits = re.findall(r"-?\d+", str(declared or ""))
    return bool(digits) and digits[-1] == asked


#: How many amenity facts an answer presents, applied AFTER the on-topic
#: filter and the relevance ranking above.
_PRESENT_FACTS = 3

# Module-level clients used by _search_documents.  Initialized via init_document_search().
_doc_qdrant_client: Optional[Any] = None
_doc_embedding_service: Optional[Any] = None


def init_document_search(qdrant_client: Any, embedding_service: Any) -> None:
    """Call from main.py lifespan to wire up the document search dependencies."""
    global _doc_qdrant_client, _doc_embedding_service
    _doc_qdrant_client = qdrant_client
    _doc_embedding_service = embedding_service


async def _search_documents(
    query: str,
    building_id: str,
    top_k: int = 3,
    only_document: str = "",
    stats: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Search the per-building uploaded-documents collection.  Returns [] on any failure.

    ``only_document`` scopes the search to the file the ontology declared for this
    topic (``ontosage:documentRef``) — see search_documents for why that matters.

    ``stats``, when given, is filled with ``retrieved`` / ``kept`` / ``floor`` (CAVEAT-226).
    The floor is applied HERE rather than server-side so the caller can tell "nothing was
    retrieved" from "everything retrieved fell below the floor". Those are different facts and
    only the second is attributable to a threshold; without the distinction, raising the floor
    looks identical to unexplained drift in the regression gate.
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
        # score_threshold=0.0 so the raw candidates come back and the floor is applied below.
        # Same query, same top_k -- no extra cost, and the suppression becomes visible.
        raw = await search_documents(
            _doc_qdrant_client,
            _doc_embedding_service,
            query,
            building_id,
            top_k=top_k,
            score_threshold=0.0,
            only_document=only_document or None,
        )
        kept = [h for h in raw if float(h.get("score") or 0.0) >= threshold]
        if stats is not None:
            stats.update({"retrieved": len(raw), "kept": len(kept), "floor": threshold})
        return kept
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
            from orchestrator.services.grounding_guard import (
                SUBJECT_SPACE,
                enablement_hint,
            )
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

    @staticmethod
    async def _building_profile_answer(
        building_id: str, building_name: str, state: ConversationState
    ) -> Optional[Dict[str, Any]]:
        """Answer a question about the building itself, or None to carry on.

        Kept separate from the metrics responder because the two answer
        different questions: metrics say how MANY things the building has,
        this says what the building IS.
        """
        query = state.user_message or ""
        try:
            from orchestrator.services import building_profile as bp

            facet = bp.detect_facet(query)
            if facet is None:
                return None

            from orchestrator.agents.sparql_agent import SPARQLAgent, _active_namespace

            profile = await bp.resolve(_active_namespace(), SPARQLAgent()._execute_query)
            text = bp.render(profile, facet, building_name)
            if text is None:
                # The building states nothing about itself. Decline, and say what
                # to add — the same contract the sensor path keeps.
                text = bp.enablement_hint(building_name)
                provenance = "building_profile_absent"
            else:
                provenance = "building_profile"
            logger.info(f"[capability] building-profile question (facet={facet}) answered")
            return {
                "success": True,
                "response": text,
                "provenance": provenance,
                "building_name": building_name,
            }
        except Exception as e:  # never block the rest of the chain
            logger.warning(f"[capability] building-profile check skipped: {e}")
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

        # ── 0. The building's own description ────────────────────────────────
        # "How old is this building?", "who built it?", "what type of building is
        # this?" are about the building AS AN ENTITY, not its sensors — the
        # largest class of unanswered question in the survey corpus. This runs
        # FIRST because those questions must never reach the open-domain
        # answerer, which will supply a confident, plausible, unfalsifiable year.
        # Building-agnostic: it reports whatever the active building's own node
        # asserts, and declines what it does not.
        _profile_answer = await self._building_profile_answer(building_id, building_name, state)
        if _profile_answer:
            state.intermediate_results["capability_result"] = _profile_answer
            return state

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
                from orchestrator.services.grounding_guard import (
                    filter_on_topic as _on_topic,
                )

                # The on-topic surface includes the LAY TERMS the building declared,
                # not just the rendered prose. bldg2 declined "where can I fill my
                # water bottle?" while holding four amenities whose lay terms say
                # "fill my bottle" -- their prose never repeats the word, so the
                # guard rejected every one and the building denied having them.
                # Rejecting an amenity the building explicitly declared for that
                # phrasing overrules the building about its own vocabulary.
                _rendered = [
                    {
                        "text": f.render() + " " + getattr(f, "lay_terms", ""),
                        "doc_name": getattr(f, "label", ""),
                    }
                    for f in _facts
                ]
                _keep = {id(r) for r in _on_topic(state.user_message or "", _rendered)}
                _pairs = [(f, r) for f, r in zip(_facts, _rendered) if id(r) in _keep]
                # ORDER matters as much as inclusion, and the filter above cannot
                # supply it. For "how many parking bays are free?" BOTH a
                # "Transport Parking" amenity and a general "Catering Amenities"
                # blob survive on-topic legitimately — the catering text mentions
                # bicycle parking in passing — and the resolver hands them back in
                # graph order, so the reader was shown a CATERING answer to a
                # parking question (measured live 2026-08-25). BUG-103 removed the
                # off-topic amenity; it could not rank the on-topic ones.
                #
                # An amenity whose LABEL names what was asked is the one that
                # answers it; an amenity that merely mentions it in passing is not.
                # So rank by label match first, then by how distinctive the shared
                # vocabulary is. Rank, never drop: the weaker fact is still true and
                # may still be worth reading — it simply must not lead.
                from orchestrator.services.grounding_guard import (
                    MATCH_COMMON,
                    MATCH_DISTINCTIVE,
                )
                from orchestrator.services.grounding_guard import (
                    is_on_topic as _is_on_topic,
                )
                from orchestrator.services.grounding_guard import (
                    match_strength as _strength,
                )

                _rank = {MATCH_DISTINCTIVE: 2, MATCH_COMMON: 1}
                _q = state.user_message or ""

                # A floor named in the question outranks everything else. "Where can I
                # fill my bottle ON FLOOR 3?" listed floors 0, 1 and 2 and never
                # mentioned 3, because nothing in the ranking looked at the floor the
                # amenity declares (BUG-337). Ranked, not filtered: the other floors'
                # points are still true and still worth seeing underneath.
                _asked_floor = _floor_in_question(_q)

                def _relevance(pair):
                    _f, _r = pair
                    _label = str(_r.get("doc_name", "")).replace("_", " ")
                    _on = getattr(_f, "on_floor", "") or ""
                    return (
                        1 if _asked_floor and _same_floor(_on, _asked_floor) else 0,
                        1 if _label and _is_on_topic(_q, _label) else 0,
                        _rank.get(_strength(_q, str(_r.get("text", ""))), 0),
                    )

                _pairs.sort(key=_relevance, reverse=True)
                # Truncate HERE, after filtering and ranking -- never in the resolver.
                # The resolver cutting to this size first is what made the building deny
                # having bottle-refill points it has twelve of (BUG-337).
                _facts = [f for f, _ in _pairs][:_PRESENT_FACTS]
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

        # ── 2b. A system of record this building does not hold (V7-T21) ──────
        #
        # Runs BEFORE the document search, because that search is what turns a missing
        # system into a wrong answer: measured 2026-08-31, "which contracts expire in the
        # next six months?" came back with the PERMIT register pasted underneath it. The
        # building holds no contracts. Saying which system is missing is both true and
        # actionable, and it is decidable — the ontology defines the class and the graph
        # holds no instances of it.
        try:
            from orchestrator.services.record_registry import (
                absent_record_class,
                load_lay_terms,
                record_classes,
            )

            await load_lay_terms()
            _absent = absent_record_class(state.user_message or "", await record_classes())
        except Exception as _rr_err:  # pragma: no cover - never block the lane on this
            logger.debug(f"[capability] record registry unavailable: {_rr_err}")
            _absent = None

        if _absent:
            _readable = re.sub(r"(?<!^)(?=[A-Z])", " ", _absent).lower()
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": (
                    f"**{building_name} holds no {_readable} records**, so I cannot answer "
                    f"this from the building's own data.\n\n"
                    f"I checked: the ontology defines `ontosage:{_absent}`, and this "
                    f"building has no instances of it.\n\n"
                    f"To make this answerable, add a {_readable} record — either as TTL, "
                    f"or as a document carrying the record-document front-matter "
                    f"(`record_type`, `owner`, `authority`, `effective_from`, `version`), "
                    f"which is lifted into queryable triples on ingest. No code change is "
                    f"needed.\n\n"
                    f"Meanwhile, the {_readable} owner holds the authoritative answer."
                ),
                "provenance": "absent_system_of_record",
                "absent_record_class": _absent,
                "building_name": building_name,
            }
            logger.info(f"[capability] declined — building holds no {_absent} records")
            return state

        # ── 3. Uploaded documents (documents_<bldg>) ─────────────────────────
        # Genuinely-uploaded manuals / policy PDFs, semantically retrieved. This is NOT a
        # capability.yaml fallback — it is a distinct source for long-form uploaded content.
        _doc_stats: Dict[str, Any] = {}
        doc_hits = await _search_documents(state.user_message or "", building_id, stats=_doc_stats)
        # CAVEAT-226: when the floor removed EVERY candidate, say so on the evidence record.
        # An answer that got thinner because a threshold moved is an attributable tightening;
        # one that got thinner for no stated reason is a regression, and the gate cannot tell
        # them apart unless the threshold names itself.
        if _doc_stats.get("retrieved") and not _doc_stats.get("kept"):
            _ev = state.intermediate_results.setdefault("evidence", {})
            if isinstance(_ev, dict):
                _ev.setdefault("gates_applied", []).append("retrieval_floor")
                logger.info(
                    f"[capability] retrieval floor {_doc_stats['floor']} suppressed all "
                    f"{_doc_stats['retrieved']} candidate passage(s)"
                )
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
            _before_guard = len(doc_hits)
            doc_hits = filter_on_topic(
                state.user_message or "", doc_hits, extra_vocab=_concept_vocab
            )
            # The on-topic guard must name itself for the same reason the retrieval floor has
            # to (CAVEAT-226): it SUPPRESSES an answer, and a suppression that names nothing is
            # indistinguishable from breakage to the regression gate. Measured on the 0.55
            # floor run, 3 of 8 blocking findings were this guard rather than the floor --
            # "which anchor points are certified for the abseil window clean", which used to be
            # answered with the building's HVAC CO2 table, scores 0.5749 and clears the floor
            # outright. Correct behaviour, reported as a regression for want of a name.
            if _before_guard and not doc_hits:
                _ev = state.intermediate_results.setdefault("evidence", {})
                if isinstance(_ev, dict):
                    _applied = _ev.setdefault("gates_applied", [])
                    if "grounding_guard" not in _applied:
                        _applied.append("grounding_guard")
                    logger.info(
                        f"[capability] on-topic guard suppressed all {_before_guard} "
                        "retrieved passage(s)"
                    )
        if doc_hits:
            # BUG-218: the guard above decides WHETHER a passage is shown; this decides
            # how confidently it is introduced. Measured over the golden baseline, 148 of
            # 377 document-citing answers (39.3%) came from an unrelated document sharing
            # ONE incidental word with the question -- 'cleaned annually' in an HVAC table
            # answering a question about carpets. The content was real, so no
            # anti-fabrication guard fired; what misled was the heading asserting it
            # answered.
            #
            # Suppressing those was measured and rejected: every count-based threshold
            # dropped roughly one legitimate answer per off-topic one it removed. Hedging
            # costs no recall and removes the false assertion, so the corpus signal drives
            # the FRAMING rather than the filtering.
            from orchestrator.services.corpus_stats import document_frequencies
            from orchestrator.services.grounding_guard import (
                MATCH_DISTINCTIVE,
                match_strength,
                missing_fact_caveat,
            )

            try:
                _corpus_df, _n_docs = document_frequencies(building_id)
            except Exception as exc:  # a statistics helper must never break an answer
                logger.debug(f"[capability] corpus stats unavailable: {exc}")
                _corpus_df, _n_docs = {}, 0

            _strong = any(
                match_strength(
                    state.user_message or "",
                    str(h.get("text", "")),
                    extra_vocab=_concept_vocab,
                    corpus_df=_corpus_df,
                    n_docs=_n_docs,
                )
                == MATCH_DISTINCTIVE
                for h in doc_hits
            )

            seen_docs: set = set()
            if _strong:
                parts: List[str] = [f"Here is what I found in **{building_name}** documentation:\n"]
            else:
                # Names the match instead of claiming it. The passage is still shown --
                # it is real content and may help -- but a reader can no longer mistake
                # proximity for an answer.
                parts = [
                    f"I could not find a passage in **{building_name}**'s documents that "
                    "directly addresses this. The closest related material is below, and "
                    "it may not answer your question:\n"
                ]

            # Already wired on the graph path (and tested there); its absence here is why
            # a question asking for a DATE could be answered with prose containing none.
            _caveat = missing_fact_caveat(
                state.user_message or "", str((doc_hits[0] or {}).get("text", ""))
            )
            if _caveat:
                parts.append(f"{_caveat}\n")
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
