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

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


# What the building HAS, in general terms: the only other shape the live-figures block answers.
_WHAT_BUILDING_HAS_RE = re.compile(
    r"\bwhat\b[^?.!]{0,40}\b(?:does|do)\b[^?.!]{0,30}\b(?:have|hold|contain|monitor|measure)\b",
    re.IGNORECASE,
)


def _asks_for_building_figures(query: str) -> bool:
    """True only for counts, size and 'what does it have' -- the questions the live block answers.

    A MEASURAND alone ("is the sound insulation good?") names a quantity, not a census. Answering
    it with the sensor and room counts was measured as an irrelevant fragment on the held-out read.
    """
    q = query or ""
    return _is_metrics_question(q) or bool(_WHAT_BUILDING_HAS_RE.search(q))


# A question about the QUALITY or an ATTRIBUTE of the things a building holds ("are there
# duplicate assets?", "which meters are inconsistent?") is not answered by counting classes.
_INVENTORY_ATTRIBUTE_RE = re.compile(
    r"\b(?:duplicat\w*|inconsisten\w*|consisten\w*|mismatch\w*|conflict\w*|reconcil\w*|"
    r"accura\w*|stale|outdated|out[- ]of[- ]date|overdue|missing|orphan\w*|unlinked|unmapped|"
    r"misclassif\w*|complete(?:ness)?|up[- ]to[- ]date|agree\w*|differ\w*|same (?:name|tag|id)|"
    r"warrant\w*|oldest|newest|cost|price|who|why|when)\b",
    re.IGNORECASE,
)


def _census_can_answer(query: str) -> bool:
    """False when the question asks about an attribute a class census cannot supply."""
    return not _INVENTORY_ATTRIBUTE_RE.search(query or "")


#: Words that describe the building as an entity. What is left of a question once these and its
#: framing are removed is what the question is actually ABOUT.
_PROFILE_VOCABULARY = (
    "old age year built build construct constructed design designed architect owner own owned "
    "operator operate operated run runs manage managed address postcode locate located location "
    "type kind purpose visitor visitors public occupy occupied residence residential commercial "
    "tall big large size storey storeys function contractor name called use uses used access "
    "allowed allow check open education educational university campus "
    "capacity people persons occupants hold fit accommodate house host maximum max time"
)


def _profile_is_the_subject(query: str) -> bool:
    """True when the building itself is what the question is about, not a passing word in it.

    "Who built it?" is a profile question. "How fresh is the data from the access-control feeds,
    and who built the system?" contains the same words and is about feeds; answering it with the
    building's architect was measured as an irrelevant fragment. The profile answers only when at
    most one content word of the question falls outside the profile vocabulary.
    """
    from orchestrator.services.grounding_guard import content_terms
    from orchestrator.services.passage_relevance import question_topic_terms

    known = content_terms(_PROFILE_VOCABULARY)
    return len({t for t in question_topic_terms(query or "") if t not in known}) <= 1


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
            # Headroom: commentary passages are dropped below and must not crowd out the table.
            top_k=top_k + 3,
            score_threshold=0.0,
            only_document=only_document or None,
        )
        kept = [h for h in raw if float(h.get("score") or 0.0) >= threshold]
        # Authoring commentary ("Three duty columns, not one ...") is developer prose about how a
        # register was designed, not a fact about the building; front matter goes with it.
        from orchestrator.services.passage_relevance import drop_commentary_hits

        kept = drop_commentary_hits(kept, building_id)[:top_k]
        if stats is not None:
            stats.update({"retrieved": len(raw), "kept": len(kept), "floor": threshold})
        return kept
    except Exception as e:
        logger.debug(f"[capability] document search unavailable: {e}")
        return []


def _boundary_pointer(building_name: str, query: str, held: List[Any]) -> str:
    """What the building's records CAN answer that is near the question, or '' (never raises)."""
    try:
        from orchestrator.services.fallback_wording import compose_boundary_pointer

        return compose_boundary_pointer(building_name, query, held)
    except Exception as exc:  # a pointer is a courtesy, never a reason to lose the decline
        logger.debug(f"[capability] boundary pointer unavailable: {exc}")
        return ""


def _held_register_note(query: str, held: List[Any]) -> Optional[str]:
    """Name the register this building HOLDS for this question, when it holds one (BUG-749).

    The document lane is the catch-all, and its decline claims an absence: "the building's
    records do not cover this". Measured on the 147-question live read, that sentence was
    said over registers the building holds and the lane never looked at — 30 cleaning tasks
    for "which washroom should I service next", accessible routes for a pushchair question.
    A false absence is the worst answer this system can give short of a fabricated number,
    so before any decline the held registers get a say.

    Building-agnostic by construction: the classes, their labels and their vocabulary all
    come from the ontology and the counts from the active graph — `rank_record_classes` is
    the same scorer the routing short-circuit uses, so this cannot disagree with it.

    Returns None when the question names no held register, which is the common case and
    must leave the decline exactly as it was. Naming a register the question did NOT name
    is the C8 defect (a decline reciting an unrelated register's statistics) with the sign
    flipped, and is worse than saying nothing.
    """
    if not held:
        return None
    try:
        from orchestrator.services.record_registry import rank_record_classes

        ranked = rank_record_classes(query or "", held)
    except Exception as exc:  # pragma: no cover - never block a decline on this
        logger.debug(f"[capability] register ranking unavailable: {exc}")
        return None
    if not ranked:
        return None
    record = ranked[0][1]
    label = (record.label or record.local_name).strip().lower()
    return (
        f"**This is a question for {label} records, and the building keeps them.** "
        f"I searched the building's documents instead, which do not cover it, but "
        f"{record.instances} {label} record(s) are held and they are where the answer "
        f"would be. Ask for the {label} records and I will read them."
    )


class CapabilityAgent:
    """
    Answers building capability / off-ontology questions from the building's own data.
    Returns a grounded answer with provenance, or an explicit boundary statement.
    Never hallucinate — if no source has the fact, say so clearly.
    """

    #: The model's declared way to say the passages do not contain the answer. A refusal
    #: has to be as easy to produce as an answer, or the model fills the gap from its own
    #: knowledge — which is the one thing a document lane must never do.
    _NO_ANSWER = "NO_ANSWER_IN_SOURCE"

    @staticmethod
    async def _answer_from_passages(
        question: str, hits: List[Dict[str, Any]]
    ) -> Tuple[Optional[str], bool]:
        """Compose an answer from retrieved passages.

        Returns ``(answer, decided)``. Three outcomes, and the third is the one that
        matters:

            ("...", True)   the passages answer, and this is that answer
            (None,  True)   the passages do not answer — decline, do not paste
            (None,  False)  the composer could not RUN, so nothing was decided

        The last case exists because a model outage must not silently turn this lane off.
        Without it the document lane would answer nothing whenever the LLM was
        unavailable, which is BUG-177's lesson exactly: a degraded model produced fallback
        text that read like an answer, and the harness scored it. Here the caller falls
        back to presenting the passage, honestly labelled, as it always did.

        Grounded generation, not extraction: the passages are the ONLY permitted source
        and the model is given an explicit token for "not in here".
        """
        if not hits:
            return None, False
        from orchestrator.llm_manager import TaskType, llm_manager

        passages = "\n\n".join(
            f"[{h.get('doc_name', 'document')}]\n{str(h.get('text', ''))[:2000]}" for h in hits[:3]
        )
        prompt = (
            "Answer the question using ONLY the passages below. They are extracts from a "
            "building's own documents.\n\n"
            "Rules:\n"
            "- Use nothing but the passages. Do not add general knowledge.\n"
            f"- If the passages do not contain the answer, reply with exactly "
            f"{CapabilityAgent._NO_ANSWER} and nothing else. Being close to the topic is "
            "NOT containing the answer.\n"
            "- Do not restate a passage as though it were the answer.\n"
            "- Reproduce names, identifiers and codes EXACTLY as written — same spelling,\n"
            "  same punctuation. An SSID, a room id or a reference number that has been\n"
            "  retyped is no longer the thing the document named.\n"
            "- Be brief and direct.\n\n"
            f"QUESTION: {question}\n\nPASSAGES:\n{passages}\n\nANSWER:"
        )
        try:
            reply = (await llm_manager.generate(prompt, task_type=TaskType.GENERAL) or "").strip()
        except Exception as exc:
            logger.warning(f"[capability] passage answering unavailable: {exc}")
            return None, False
        if not reply:
            return None, False  # an empty completion decided nothing
        if CapabilityAgent._NO_ANSWER in reply.upper():
            return None, True
        return reply, True

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
                reader_is_admin_in,
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
            # What DOES exist, as the resolver found it in the graph — never a guess. Read
            # defensively: a missing list must not turn a clean "not found" into the
            # "could not verify" branch below.
            _have = [str(s) for s in (getattr(resolution, "suggestions", None) or []) if s]
            return {
                "success": True,
                "response": (
                    f"I couldn't find **{resolution.referent}** in **{building_name}**'s "
                    "records, so I can't give you figures for it — the counts I hold describe "
                    "other parts of the building, and reporting them here would suggest this "
                    "one exists."
                    + (
                        f"\n\nWhat this building does have: **{', '.join(_have)}**."
                        if _have
                        else ""
                    )
                    + enablement_hint(
                        SUBJECT_SPACE,
                        resolution.referent,
                        for_admin=reader_is_admin_in(state),
                    )
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
            if not _profile_is_the_subject(query):
                logger.info("[capability] profile words present, question is about another subject")
                return None

            from orchestrator.agents.sparql_agent import SPARQLAgent, _active_namespace

            from orchestrator.services.grounding_guard import reader_is_admin_in

            # Every reader gets the decline; only an administrator is told what to add.
            _for_admin = reader_is_admin_in(state)
            profile = await bp.resolve(_active_namespace(), SPARQLAgent()._execute_query)
            text = bp.render(profile, facet, building_name, for_admin=_for_admin)
            if text is None:
                # The building states nothing about itself. Decline for everyone; say
                # what to add only to an administrator.
                text = bp.enablement_hint(building_name, for_admin=_for_admin)
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
        """Run the chain, then refuse to present coded status rows as evidence of health."""
        state = await self._answer_unchecked(state)
        try:
            from orchestrator.services import terse_status_answer as _terse

            _res = state.intermediate_results.get("capability_result")
            if isinstance(_res, dict) and _res.get("response"):
                _repl = _terse.apply(
                    state.user_message or "",
                    str(_res.get("response")),
                    str(_res.get("building_name") or "this building"),
                )
                if _repl:
                    logger.info("[capability] coded status rows are not evidence — declining")
                    _res["response"] = _repl
                    _res["provenance"] = "terse_status_declined"
        except Exception as exc:  # never let the guard cost the turn its answer
            logger.debug(f"[capability] terse-status guard skipped: {exc}")
        return state

    async def _answer_unchecked(self, state: ConversationState) -> ConversationState:
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

        # "Which rooms are computer laboratories?" / "which floor is the server room on?" are
        # answered from the room records, not from a topic that mentions them (BUG-810, 827).
        from orchestrator.services import room_type_lookup as _rooms

        _kind_answer = await _rooms.answer_live(state.user_message or "")
        if _kind_answer:
            state.intermediate_results["capability_result"] = _rooms.capability_result(
                _kind_answer, building_name
            )
            return state

        # "Is the parking free or is there a fee?" asks for a FIELD of an amenity's record: the
        # record answers it, or the answer says the field is not recorded (never a document
        # passage that merely mentions parking).
        from orchestrator.services import amenity_attribute_answer as _attrs

        _attr = await _attrs.answer_live(state.user_message or "", building_name)
        if _attr:
            state.intermediate_results["capability_result"] = _attr
            return state

        # A metrology question is not a census (BUG-427). "How many sensors are overdue for
        # calibration?" is a count of sensors, so it reads as a metrics question and was
        # answered with the building's live figures — instrumented points, zones, floors —
        # none of which is what was asked. The graph holds 194 overdue calibrations and the
        # deterministic metrology path in the SPARQL lane counts them; this must not claim
        # the question before it gets there.
        from orchestrator.services.building_metrics import names_a_specific_class
        from orchestrator.services.routing_contract import _METROLOGY_RE as _METROLOGY

        _is_metrology = bool(_METROLOGY.search(state.user_message or ""))
        # Nor a count of a specific KIND of device (BUG-431). This snapshot reports the
        # building's totals, so "how many CO2 sensors are there?" was answered "2,721
        # sensors". The class census two blocks below counts by class and holds the right
        # figure — CO2_Sensor 280 — so a class-qualified count belongs to it.
        _class_qualified = names_a_specific_class(state.user_message or "")
        if not _is_metrology and not _class_qualified and (
            measurand_of(state.user_message or "")
            or _is_metrics_question(state.user_message or "")
        ):
            _decline = await self._absent_referent_decline(state, building_id, building_name)
            if _decline:
                state.intermediate_results["capability_result"] = _decline
                return state
            # The census answers counts and size only. A measurand ("sound insulation") that
            # asks for neither must not be answered with sensor and room totals.
            _wants_figures = _asks_for_building_figures(state.user_message or "")
            if not _wants_figures:
                logger.info("[capability] measurand named but no count asked — figures withheld")
            try:
                if _wants_figures:
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

            _resolver = get_capability_graph_resolver()
            _withheld: list = []  # matched but out of service: named, never dropped silently
            if hasattr(_resolver, "resolve_with_withheld"):  # a duck-typed resolver may lack it
                _facts, _withheld = await _resolver.resolve_with_withheld(state.user_message or "")
            else:
                _facts = await _resolver.resolve(state.user_message or "")
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

                # A TOPIC ANSWERS ONLY THE QUESTION IT IS ABOUT (BUG-601).
                #
                # Ranking picks the best of the matching topics; it cannot tell that NONE of
                # them is what was asked. Measured in stakeholder run #3: "Book me a hotel near
                # the building" answered with the room-booking topic, "Is the building
                # pushchair-friendly from the car park?" with travel directions, "Where can I
                # isolate the water supply for the second-floor toilets?" with a list of
                # toilets, and "What systems are specific for the meeting room?" with study
                # spaces — each in about a second, each confidently about something else.
                #
                # A topic qualifies when it IS the subject: at most one content word of the
                # question is left once its own lay terms and the framing words (where, floor,
                # nearest, free, …) are removed. Where none qualifies the lane falls through to
                # the documents and then to the honest "not on record" below, which is the
                # answer this building can defend.
                from orchestrator.services.capability_graph_resolver import (
                    leftover_content_words,
                )

                def _is_subject(f) -> bool:
                    # Judged against the terms the BUILDING declared for this topic, or its
                    # label when it declared none. A topic with neither is kept: there is
                    # nothing to judge it by, and dropping it would deny a declared amenity.
                    phrases = [
                        p.strip().lower()
                        for p in str(getattr(f, "lay_terms", "") or "").split(",")
                        if p.strip()
                    ] or [
                        w.lower()
                        for w in str(getattr(f, "label", "") or "").split()
                        if len(w) > 2
                    ]
                    if not phrases:
                        return True
                    return len(leftover_content_words(_q.lower(), phrases)) <= 1

                _subject = [f for f in _facts if _is_subject(f)]
                if _facts and not _subject:
                    logger.info(
                        "[capability] topics %s match words but are not the subject — "
                        "not answering from them",
                        [f.label for f in _facts][:3],
                    )
                _facts = _subject
                # A floor named in the question is answered FOR THAT FLOOR, or the gap is stated
                # (BUG-827): "toilets on floor 2" never said the one there was out of service.
                from orchestrator.services import amenity_floor_answer as _floors

                _by_floor = _floors.capability_answer(
                    state.user_message or "",
                    [f for f, _ in _pairs if _is_subject(f)],
                    [w for w in _withheld if _is_subject(w)],
                    building_name,
                )
                if _by_floor:
                    state.intermediate_results["capability_result"] = _by_floor
                    return state
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
                # Worded for every reader (2026-09-17): "ontology (triples)" is how the fact
                # is stored, not where a supervisor would say it came from.
                _sources = ["building's own records"]
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
                overlap_notes,
                render_census,
            )

            # "Are there duplicate assets?" asks about a QUALITY of what is held; a census of
            # equipment classes is a different fact and was returned as though it answered.
            if is_inventory_question(state.user_message or "") and _census_can_answer(
                state.user_message or ""
            ):
                from orchestrator.agents.sparql_agent import (
                    GRAPHDB_QUERY_ENDPOINT,
                    _active_namespace,
                )

                _rows = await class_census(
                    state.user_message or "", _active_namespace(), GRAPHDB_QUERY_ENDPOINT
                )
                # A census reads as a partition, and Brick's classes are not disjoint:
                # "Air Quality Sensor 523, CO2 Sensor 214, CO2 Level Sensor 208" invites a
                # reader to add up to 945 devices in a building that has 523 (CAVEAT-006).
                # Measured per building rather than assumed, because two classes CAN be
                # genuinely disjoint here (V12-09).
                _overlaps = await overlap_notes(
                    _rows, _active_namespace(), GRAPHDB_QUERY_ENDPOINT
                )
                _block = render_census(_rows, building_name, overlaps=_overlaps)
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

        # ── 1b. "How do you know that?" — read the evidence record (V7-T74) ──
        #
        # V6 built a machine-readable record for every consequential answer and nothing
        # reached it by asking: auditors asking "can every extraction, join and filter be
        # rerun from authorised inputs?" got a document search, and "how do you know
        # that?" was answered as a question about the system's capabilities. The record
        # was in the previous turn's state the whole time.
        #
        # It is the PREVIOUS turn's record that matters — "how do you know that" refers to
        # the answer just given — so it is read from the saved state rather than from this
        # turn's, which is still empty.
        try:
            from orchestrator.services.answer_provenance import (
                is_provenance_question,
                render,
            )

            _wants_provenance = is_provenance_question(state.user_message or "")
        except Exception:  # pragma: no cover - never block the lane on this
            _wants_provenance = False

        if _wants_provenance:
            _record = None
            try:
                from orchestrator.redis_manager import redis_manager

                _prev = await redis_manager.load_state(state.conversation_id)
                if _prev and _prev.intermediate_results:
                    _record = _prev.intermediate_results.get("evidence_record")
            except Exception as _prov_err:
                logger.debug(f"[capability] could not load previous turn: {_prov_err}")

            try:
                from orchestrator.services.grounding_guard import reader_is_admin_in

                _prov_for_admin = reader_is_admin_in(state)
            except Exception:  # pragma: no cover - the plain read-back is the safe side
                _prov_for_admin = False
            _rendered = render(_record, state.user_message or "", for_admin=_prov_for_admin)
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": _rendered
                or (
                    "**I have no evidence record for a previous answer in this "
                    "conversation.** Every consequential answer carries one — its sources "
                    "and their owners, the operation performed, when the evidence was "
                    "observed and when it was retrieved, and the checks that fired. Ask a "
                    "question first and then ask how I know, and I will read that record "
                    "back to you.\n\nI would rather say this than reconstruct an "
                    "explanation after the fact, which is not the same thing as provenance."
                ),
                "provenance": "answer_provenance",
                "building_name": building_name,
            }
            logger.info(
                "[capability] answered from the evidence record"
                if _rendered
                else "[capability] provenance asked with no prior record"
            )
            return state

        # ── 2a. A state the building is not in (V7-T80) ──────────────────────
        #
        # "If power fails, how long do the lab freezers stay safe?" has no grounded
        # answer: the building holds sensors and records, not a thermal, hydraulic or
        # electrical model. Left to run, the model answers from physical intuition and
        # produces a confident number about freezer safety — the most dangerous answer
        # this system could give.
        #
        # The decline names what a real answer would need, so it reads as a specification
        # rather than a refusal, and it distinguishes the two halves that ARE answerable:
        # what the building recorded when something like this last happened, and what its
        # procedures say to do.
        try:
            from orchestrator.services.routing_contract import scenario_question

            _is_scenario = scenario_question(state.user_message or "")
        except Exception:  # pragma: no cover - never block the lane on this
            _is_scenario = False

        if _is_scenario:
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": (
                    f"**I can't answer a what-if for {building_name}.** The question "
                    "supposes a state the building is not in, and answering it would take "
                    "a model of how the building behaves under that state — thermal, "
                    "hydraulic or electrical. This service holds measurements and "
                    "records, not a simulation, and a confident figure without a model "
                    "behind it would be a guess dressed as an answer.\n\n"
                    "Two things I can do instead:\n"
                    "- tell you what was **recorded** the last time something like this "
                    "happened, if it is in the event history\n"
                    "- tell you what the building's **procedures** say to do, if a "
                    "document covers it\n\n"
                    "For the scenario itself, the responsible engineer or the resilience "
                    "plan owner holds the answer."
                ),
                "provenance": "scenario_out_of_scope",
                "building_name": building_name,
            }
            logger.info("[capability] declined — scenario question, no model to answer it")
            return state

        # ── 2b. A system of record this building does not hold (V7-T21) ──────
        #
        # Runs BEFORE the document search, because that search is what turns a missing
        # system into a wrong answer: measured 2026-08-31, "which contracts expire in the
        # next six months?" came back with the PERMIT register pasted underneath it. The
        # building holds no contracts. Saying which system is missing is both true and
        # actionable, and it is decidable — the ontology defines the class and the graph
        # holds no instances of it.
        _held_classes: List[Any] = []
        try:
            from orchestrator.services.record_registry import (
                absent_record_class,
                load_lay_terms,
                record_classes,
            )

            await load_lay_terms()
            _held_classes = await record_classes()
            _absent = absent_record_class(state.user_message or "", _held_classes)
        except Exception as _rr_err:  # pragma: no cover - never block the lane on this
            logger.debug(f"[capability] record registry unavailable: {_rr_err}")
            _absent = None

        if _absent:
            _readable = re.sub(r"(?<!^)(?=[A-Z])", " ", _absent).lower()
            _response = (
                f"**{building_name} holds no {_readable} records**, so I cannot answer "
                f"this from the building's own data.\n\n"
                f"The {_readable} owner holds the authoritative answer."
            )
            from orchestrator.services.grounding_guard import reader_is_admin_in

            if reader_is_admin_in(state):
                # The remediation is for someone who can change the building's data. Told to
                # an occupant or a supervisor it is an instruction they cannot follow, and
                # "front-matter" in an answer reads as the system being broken.
                _response += (
                    f"\n\nI checked: the ontology defines `ontosage:{_absent}`, and this "
                    f"building has no instances of it.\n\n"
                    f"To make this answerable, add a {_readable} record — either as TTL, "
                    f"or as a document carrying the record-document front-matter "
                    f"(`record_type`, `owner`, `authority`, `effective_from`, `version`), "
                    f"which is lifted into queryable triples on ingest. No code change is "
                    f"needed."
                )
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": _response,
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
        # One shared word is not an answer. A passage must cover a fair share of what the
        # question is about, name the document the question is about, or clear the retrieval
        # floor by a margin; otherwise the lane declines instead of quoting it.
        # Passages the gate removes were still SEARCHED: they stay on the evidence record and the
        # lane gives the same honest decline as when the composer read them and found no answer,
        # naming none of them (BUG-748), rather than the generic "not on record" boundary.
        _gated_out: List[Dict[str, Any]] = []
        if doc_hits and os.environ.get("DOCUMENT_RELEVANCE_GATE", "on").lower() != "off":
            from orchestrator.services.passage_relevance import relevant_hits

            doc_hits, _gated_out = relevant_hits(
                state.user_message or "",
                doc_hits,
                floor=settings.document_score_floor,
                extra_vocab=_concept_vocab,
            )
            if _gated_out and not doc_hits:
                _ev = state.intermediate_results.setdefault("evidence", {})
                if isinstance(_ev, dict):
                    _applied = _ev.setdefault("gates_applied", [])
                    if "passage_relevance" not in _applied:
                        _applied.append("passage_relevance")
        if doc_hits or _gated_out:
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

            # Kept as a LIST rather than an `any(...)`, because the decline below has to
            # name which documents were about the question and which merely surfaced
            # (BUG-748). The boolean is exactly what it was.
            _distinctive = [
                h
                for h in doc_hits
                if match_strength(
                    state.user_message or "",
                    str(h.get("text", "")),
                    extra_vocab=_concept_vocab,
                    corpus_df=_corpus_df,
                    n_docs=_n_docs,
                )
                == MATCH_DISTINCTIVE
            ]
            _strong = bool(_distinctive)

            # ── Answer FROM the passage, or decline (V7-T20 / BUG-369) ───────
            #
            # The strength check above is a relevance heuristic and it is not enough.
            # Measured on the 111-question probe: 38 of 56 "answers" were pastes, and
            # several answered a different question entirely — "which plant can be
            # installed, commissioned and replaced through a credible route" returned the
            # ASBESTOS REGISTER, and it passed as a distinctive match. Fifteen roles had
            # their whole score made of such pastes.
            #
            # Whether a passage answers a question is not decidable from word overlap, so
            # it is decided by trying: compose an answer from the passage alone, with an
            # explicit way to say the passage does not contain one. That escape hatch is
            # what makes this safe — without it the model would fill the gap from its own
            # knowledge, which is the fabrication this project guards against hardest.
            if doc_hits:
                composed, _decided = await self._answer_from_passages(
                    state.user_message or "", doc_hits
                )
            else:
                # Every retrieved passage failed the relevance gate: nothing to compose from.
                composed, _decided = None, True
            _searched = doc_hits or _gated_out
            if composed is not None:
                _cited = sorted({h["doc_name"].replace("_", " ").title() for h in doc_hits})
                state.intermediate_results["capability_result"] = {
                    "success": True,
                    "response": (
                        f"{composed}\n\n---\n*From {building_name}'s documents: "
                        f"{', '.join(_cited)}. For the current version, contact facility "
                        "management.*"
                    ),
                    "provenance": "document_answered",
                    "building_name": building_name,
                    "documents": _cited,
                }
                logger.info(f"[capability] answered from documents: {_cited}")
                return state

            # A composer that could not run leaves the passages unjudged. Pasting them under
            # "closest related material" when nothing in them is distinctive to the question AND
            # no document the question names is among them is a fragment presented as an answer
            # (defect C10), so that case declines too.
            from orchestrator.services.passage_relevance import document_is_named

            if _searched and (
                _decided or not (_strong or document_is_named(state.user_message or "", doc_hits))
            ):
                from orchestrator.services.grounding_guard import reader_is_admin_in

                _cited = sorted({h["doc_name"].replace("_", " ").title() for h in _searched})
                # BUG-748: a decline must not recite registers that have nothing to do with
                # the question. Measured on the 147-question live read: "which washroom
                # should I service next" was declined with "I searched Asset Engineering
                # Register, Waste Collection Register, Water Hygiene Legionella", and a
                # security records question with "Continuity Provision, Coordination
                # Function, Patrol Checkpoint". The retriever returns the nearest passages
                # whatever the distance, so naming all of them tells the reader the system
                # looked in the wrong places — which is exactly what it did. Only passages
                # the strength test calls DISTINCTIVE are named; when none is, the boundary
                # is stated without a list.
                _named = sorted({h["doc_name"].replace("_", " ").title() for h in _distinctive})
                # BUG-730: this used to end "The owner of that record holds the answer." — an
                # owner nobody named, pointing nowhere, on 19 of 147 recorded answers. A
                # retrieved passage carries text, document name and score, never an owner, so
                # there is no one real to name here; the plain boundary is the whole answer.
                # BUG-710: and the sentence that replaced it over-claimed in the other
                # direction. "…so the building's records do not cover this" was a statement
                # about EVERYTHING the building holds, reached by searching DOCUMENTS only.
                # Measured on run 3 of the 147-question read: "which current Security records
                # are incomplete, stale, duplicated or conflicting?" was answered with it
                # while 18 patrol checkpoints are held and row 22 of the same run listed
                # CHK-105, CHK-301 and CHK-302 overdue — a supervisor asking two related
                # questions sees the contradiction himself. A decline may report only what
                # was actually looked in, and `_absent_note` below is the one path allowed to
                # speak for the building as a whole, because it has counted.
                if _named:
                    _response = (
                        f"**{building_name}'s documents do not answer this.** I searched "
                        f"{', '.join(_named)}; they are the closest material and none of "
                        "them contains the answer. That is a statement about the documents, "
                        "not about the building — if you can name the record or the "
                        "measurement this would be written down as, I will look there next."
                    )
                else:
                    _response = (
                        f"**I could not find this in {building_name}'s documents.** I "
                        "searched them and none is about this question, so I have nothing "
                        "grounded to answer it with. Name the record or the measurement it "
                        "would be written down as and I will look there next."
                    )
                # ...unless the building holds a REGISTER the question names, in which case
                # the honest thing is to name that, not to report an absence. This is a
                # backstop: a register question normally routes to the graph lane long
                # before here (dialogue_agent's TTL-first short-circuit), and it reaches
                # this line only when some earlier stage claimed the question for documents.
                _register_note = _held_register_note(state.user_message or "", _held_classes)
                if _register_note:
                    _response = _register_note
                elif reader_is_admin_in(state):
                    _response += (
                        "\n\nIf the answer should be in a document, add or update it — a "
                        "document carrying record-document front-matter is also lifted "
                        "into queryable data on ingest."
                    )
                state.intermediate_results["capability_result"] = {
                    "success": True,
                    "response": _response,
                    "provenance": (
                        "held_register_named" if _register_note else "documents_do_not_answer"
                    ),
                    "building_name": building_name,
                    # What was SEARCHED stays on the evidence record — only the sentence the
                    # reader sees is narrowed to what was actually about the question.
                    "documents": _cited,
                    "documents_named": _named,
                }
                logger.info(
                    f"[capability] documents searched and none answered: {_cited} "
                    f"(named to the reader: {_named or 'none'})"
                )
                return state

            # Only a passage that is distinctive OR from a document the question names reaches
            # here, and only when the composer could not run. The passage is shown under a
            # heading that claims no more than the match does.
            seen_docs: set = set()
            if _strong:
                parts: List[str] = [f"Here is what I found in **{building_name}** documentation:\n"]
            else:
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
        # get-answers), otherwise the user is left at a dead end with no next step. The next
        # step differs by reader: everyone is pointed at the people who hold the answer; only
        # an administrator, who can act on it, is also told how to add it (2026-09-17).
        from orchestrator.services.grounding_guard import (
            SUBJECT_DOCUMENT,
            SUBJECT_SENSOR,
            enablement_hint,
            reader_is_admin_in,
        )

        # BUG-749: "I don't have that specific information on record" was said to a visitor
        # asking whether the building is pushchair-friendly from the car park, while the
        # accessible-route register held a step-free ground-level parking entrance. Nothing
        # reached it, and the boundary sentence turned a routing miss into a statement about
        # the building. A held register the question names is checked before that sentence
        # is allowed out.
        _register_note = _held_register_note(state.user_message or "", _held_classes)
        if _register_note:
            state.intermediate_results["capability_result"] = {
                "success": True,
                "response": _register_note,
                "provenance": "held_register_named",
                "building_name": building_name,
            }
            logger.info("[capability] no source matched — named the register held instead")
            return state

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
                f"{enablement_hint(_kind, for_admin=reader_is_admin_in(state))}"
                f"{_boundary_pointer(building_name, state.user_message or '', _held_classes)}"
            ),
            "provenance": "no_match",
            "building_name": building_name,
        }
        logger.info("[capability] no source matched — honest boundary returned")
        return state
