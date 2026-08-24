"""
SPARQL Agent - Ontology query generation with RAG
"""

import sys

sys.path.append("/app")

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import httpx

from orchestrator.agents.dialogue_agent import format_conversation_history
from orchestrator.llm_manager import TaskType, llm_manager
from orchestrator.redis_manager import redis_manager
from orchestrator.services.hybrid_retrieval import (
    QueryType,
    classify_query_type,
    hybrid_retrieval,
)
from orchestrator.services.ontology_introspector import ontology_introspector
from orchestrator.services.prompt_builder import get_prompt_builder
from orchestrator.services.self_correction_engine import SelfCorrectionEngine
from orchestrator.services.sparql_validator import sparql_validator
from shared.config import settings
from shared.models import ConversationState
from shared.utils import (
    extract_sparql_from_llm_response,
    generate_hash,
    get_logger,
    validate_sparql_syntax,
)

logger = get_logger(__name__)

RAG_SERVICE_URL = f"http://{settings.RAG_SERVICE_HOST}:{settings.RAG_SERVICE_PORT}"
# GraphDB SPARQL endpoint (new architecture)
GRAPHDB_QUERY_ENDPOINT = f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}/repositories/{settings.GRAPHDB_REPOSITORY}"
# Fuseki fallback endpoint
_base_fuseki = settings.FUSEKI_URL.rstrip("/")
FUSEKI_QUERY_ENDPOINT = _base_fuseki + ("/query" if not _base_fuseki.endswith("/query") else "")

# Ensure GraphDB endpoint is correct
if not settings.GRAPHDB_HOST:
    settings.GRAPHDB_HOST = "graphdb"
if not settings.GRAPHDB_PORT:
    settings.GRAPHDB_PORT = 7200
if not settings.GRAPHDB_REPOSITORY:
    settings.GRAPHDB_REPOSITORY = "bldg"

GRAPHDB_QUERY_ENDPOINT = f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}/repositories/{settings.GRAPHDB_REPOSITORY}"

_STANDARD_PREFIXES = [
    "PREFIX br: <http://vocab.deri.ie/br#>",
    "PREFIX bl: <https://w3id.org/biolink/vocab/>",
    "PREFIX bld: <http://biglinkeddata.com/>",
    "PREFIX brick: <https://brickschema.org/schema/Brick#>",
    "PREFIX dcterms: <http://purl.org/dc/terms/>",
    "PREFIX owl: <http://www.w3.org/2002/07/owl#>",
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>",
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
    "PREFIX sh: <http://www.w3.org/ns/shacl#>",
    "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>",
    "PREFIX sosa: <http://www.w3.org/ns/sosa/>",
    "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>",
    "PREFIX tag: <https://brickschema.org/schema/BrickTag#>",
    "PREFIX bsh: <https://brickschema.org/schema/BrickShape#>",
    "PREFIX s223: <http://data.ashrae.org/standard223#>",
    "PREFIX ashrae: <http://data.ashrae.org/standard223#>",
    "PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>",
    "PREFIX g36: <http://data.ashrae.org/standard223/1.0/extensions/g36#>",
    "PREFIX qkdv: <http://qudt.org/vocab/dimensionvector/>",
    "PREFIX quantitykind: <http://qudt.org/vocab/quantitykind/>",
    "PREFIX qudt: <http://qudt.org/schema/qudt/>",
    "PREFIX rec: <https://w3id.org/rec#>",
    "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>",
    "PREFIX s223tobrick: <https://brickschema.org/extension/brick_extension_interpret_223#>",
    "PREFIX schema1: <http://schema.org/>",
    "PREFIX unit: <http://qudt.org/vocab/unit/>",
    "PREFIX vcard: <http://www.w3.org/2006/vcard/ns#>",
]


def _build_extended_prefixes() -> list:
    """Build EXTENDED_PREFIXES dynamically, appending the building-specific prefix from settings."""
    building_prefix_line = f"PREFIX {settings.BUILDING_PREFIX}: <{settings.BUILDING_NAMESPACE}>"
    return _STANDARD_PREFIXES + [building_prefix_line]


EXTENDED_PREFIXES = _build_extended_prefixes()


# ─────────────────────────────────────────────────────────────────────────────
# Phase 15A — request-scoped building context.
#
# The SPARQLAgent is a SINGLETON shared across requests; we cannot attach the
# active building's namespace/prefix to the instance.  Instead we use a
# ContextVar — async-safe, per-coroutine, automatically isolated across
# concurrent requests.  `sparql_node` SETS it on entry; every helper method
# READS it via `_active_bctx()` with a safe fallback to settings.
#
# This closes the multi-tenant gap left in Phase 11B (which only converted the
# `_generate_sparql` prompt) without threading `building_id` through 7+ helper
# signatures.
# ─────────────────────────────────────────────────────────────────────────────

from contextvars import ContextVar

_REQUEST_BCTX: ContextVar = ContextVar("sparql_request_bctx", default=None)


def _active_bctx():
    """Return the BuildingContext for the active request, or None.

    Helpers should fall back to `settings.BUILDING_*` when this returns None
    (e.g. when called outside a request context, like tests or scripts).
    """
    return _REQUEST_BCTX.get()


def _active_namespace() -> str:
    """Per-request building namespace; falls back to the process-global default."""
    bctx = _active_bctx()
    return bctx.namespace if bctx else settings.BUILDING_NAMESPACE


def _active_prefix() -> str:
    """Per-request building prefix; falls back to the process-global default."""
    bctx = _active_bctx()
    return bctx.prefix if bctx else settings.BUILDING_PREFIX


def set_request_bctx(building_id: Optional[str]) -> Optional[object]:
    """Set the active request's BuildingContext.  Returns the token needed
    to `reset()` it; pair with a try/finally in the caller.

    `sparql_node` in workflow.py wraps the SPARQL agent call with this.
    """
    try:
        from orchestrator.services.building_context import resolve_building_context

        bctx = resolve_building_context(building_id) if building_id else None
    except Exception:
        bctx = None
    return _REQUEST_BCTX.set(bctx)


def reset_request_bctx(token) -> None:
    """Reset the request bctx token returned by `set_request_bctx`."""
    if token is not None:
        try:
            _REQUEST_BCTX.reset(token)
        except (ValueError, LookupError):
            pass


#: Row cap for a class listing. 50 could not express a real sensor population -- bldg1 alone
#: has 280 CO2 sensors -- so any "how many / which floors have X" answered from a 50-row result
#: reported the truncation as the population. Raised to a figure that covers a realistic
#: single-class count while still bounding the query, per the project's no-unbounded-query rule.
#: A class that genuinely exceeds this is still truncated, and that is what the caller must
#: disclose rather than silently present as complete.
_CLASS_LISTING_LIMIT = 500

#: The class-listing projections are aliased because SPARQL forbids `(SAMPLE(?x) AS ?x)`, and
#: the aliases MUST still contain the substrings the binding reader looks for -- it matches
#: variables by name ("uuid"/"id" for the timeseries id, "storage" for the storedAt ref), not
#: by position. Aliasing ?storage to ?store silently emptied the storage map for every
#: class-listing query, so sql_agent lost every sensor's storedAt and validated them all
#: against a fallback adapter (BUG-236). Pinned by
#: tests/test_sparql_projection_contract.py.


class SPARQLAgent:
    """Generates and executes SPARQL queries with RAG support"""

    def __init__(self):
        self.max_retries = 3
        self._instance_cache: Dict[str, List[str]] = {}
        # B.5: Self-correction engine wraps SPARQL execution with 4-strategy repair loop
        self._correction_engine = SelfCorrectionEngine()
        # C.2: Dynamic prompt builder (injects live building metadata into prompts)
        self._prompt_builder = get_prompt_builder()

    async def _reason_over_ontology(self, user_query: str, context: List[str]) -> Dict[str, Any]:
        """
        Use LLM to reason over retrieved ontology fragments and answer question directly
        (Semantic Fallback)
        """
        # Build context from ontology fragments
        context_text = "\n".join(context)

        if not context_text.strip():
            context_text = "No relevant ontology information found."

        # Build reasoning prompt
        reasoning_prompt = f"""You are an expert building management assistant. Answer the user's question based on the provided building ontology data.

User Question: "{user_query}"

Building Ontology Data:
{context_text}

Instructions:
1. Carefully read the building data above
2. Answer concisely and accurately using what you find
3. If the user asks for a sensor type that is NOT in the ontology, clearly state:
   "This building does not have [sensor type] sensors." Then suggest what IS available.
4. Only claim a sensor or sensor type exists if it appears in the Building Ontology Data above — never assume sensors that are not shown there (this system serves any building, so the available sensors are whatever the data above lists). Real sensors carry a timeseries UUID + a storedAt reference.
5. If you find a label (rdfs:label) or definition, include it
6. Format your answer clearly (use bold for key values, bullets for lists)
7. Always be helpful — if data isn't available, suggest the closest relevant sensor type that IS available

Your Answer:"""

        try:
            response = await llm_manager.generate(
                reasoning_prompt, temperature=0.1, task_type=TaskType.SPARQL
            )
            return {
                "text": response.strip(),
                "confidence": "high" if len(context_text) > 100 else "low",
            }

        except Exception as e:
            logger.error(f"LLM reasoning error: {e}")
            return {
                "text": f"I found relevant ontology data but had trouble interpreting it: {str(e)}",
                "confidence": "low",
            }

    async def answer_semantically(
        self, state: ConversationState, user_query: str, context: List[str] = None
    ) -> Dict[str, Any]:
        """
        Answer using Semantic RAG (no SPARQL)
        """
        if not context:
            context = await self._retrieve_context(user_query)

        answer = await self._reason_over_ontology(user_query, context)

        return {
            "success": True,
            "query": "SEMANTIC_RAG_NO_SPARQL",
            "results": [{"answer": answer["text"]}],  # Mock results for compatibility
            "formatted_response": answer["text"],
            "standardized": [],
            "context": context,
            "analytics_required": False,
            "llm_reasoning": "Semantic RAG fallback used",
            "method": "semantic_rag",
        }

    async def generate_query(self, state: ConversationState, user_query: str) -> Dict[str, Any]:
        """
        Generate SPARQL query using RAG

        Returns:
            Dict with 'query', 'explanation', 'context'
        """
        try:
            # Attempt deterministic template first (avoids LLM latency for common patterns)
            context = await self._retrieve_context(user_query)

            # NEW: Check intent for direct semantic answer (skip SPARQL)
            intent = state.intermediate_results.get("intent", "metadata")
            if intent == "general_knowledge":
                logger.info("Intent is general_knowledge (building), using Semantic RAG directly")
                return await self.answer_semantically(state, user_query, context)

            # Extract explicit entity references first
            # NEW: Use entities from DialogueAgent if available, but only valid SPARQL URI forms
            # (DialogueAgent may return plain text like "air quality sensors" which breaks templates)
            _valid_ent_re = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*:[A-Za-z0-9_\.]+$")
            raw_entities = state.intermediate_results.get("entities", [])
            entities = [e for e in raw_entities if _valid_ent_re.match(str(e))]
            if entities:
                logger.info(f"Using entities extracted by DialogueAgent (filtered): {entities}")
            if not entities:
                # These are guesses built from natural-language patterns in one
                # building's naming convention ("zone 3" → bldg:Zone_3). Keep
                # only the ones the graph actually holds: a guess that misses
                # is still non-empty, which suppresses label resolution below,
                # so the query then runs against IRIs that match nothing and the
                # answer becomes a confident "no data" for a sensor that exists.
                _guessed = self._extract_entities(user_query)
                if _guessed:
                    entities = await self._filter_existing(_guessed)
                    if not entities:
                        logger.info(
                            f"[sparql] pattern-guessed entities {_guessed} are not in this "
                            f"building's graph — falling back to label resolution"
                        )
            # Entities the graph confirms carry a timeseries reference; passed to
            # template selection so "is this a point?" is answered by the data
            # rather than by how this building spells its names.
            ts_entities: Set[str] = set()
            # V6-T26: a plant question resolves its points DETERMINISTICALLY, overriding
            # whatever entity extraction or label similarity produced.
            #
            # This has to happen HERE rather than via class_target below, because class_target
            # is consulted only when `entities` is empty -- and for "is the supply fan running
            # on floor 5?" it never was: label resolution matched "supply" and "floor 5" to
            # bldg:AHU_Floor5_Supply_Air_Temperature, a real plant point and the wrong one. The
            # model then answered "there is no sensor that reports the running status of a
            # supply fan on floor 5" while AHU_F5_Fan_Status sat connected with 1,344 rows.
            #
            # A near-miss is worse than a miss here: a fuzzy match on a plant point produces a
            # confident denial that cites a genuine-looking sensor as evidence of absence.
            _plant_cls = self._infer_plant_class(user_query.lower())
            if _plant_cls:
                _plant_hits = await self._plant_instances(_plant_cls, user_query)
                if _plant_hits:
                    if entities and set(entities) != set(_plant_hits):
                        logger.info(
                            f"[sparql] plant override: {entities} -> {_plant_hits} "
                            f"(class {_plant_cls} resolved from config)"
                        )
                    entities = _plant_hits
                    # Mark them ts-bearing so template selection knows these are POINTS.
                    # Without this the entity-specific template asks "what sensors are
                    # LOCATED IN bldg:AHU_F5_Filter_DP" -- treating the point as a room --
                    # and returns 0 rows. The spelling test it falls back on (`Sensor|Point`
                    # in the name) is defeated by every plant name here: Filter_DP,
                    # Fan_Status and Damper_Position contain neither word. This file's own
                    # comment predicted that exact failure; ts_entities is the answer it names.
                    ts_entities.update(await self._ts_bearing(_plant_hits))
                else:
                    # The class is right and the building has no such point. Say nothing here
                    # and let the honest "no data" path own it -- inventing a substitute point
                    # is the substitution that produced the wrong answer above.
                    logger.info(f"[sparql] plant class {_plant_cls} has no instances here")

            if not entities:
                # The dialogue agent named the point in prose rather than as an IRI.
                # Resolve those names against the graph instead of discarding them —
                # otherwise the query falls back to a generic template that returns
                # nothing, and the answer never reaches the timeseries.
                plain = [e for e in raw_entities if not _valid_ent_re.match(str(e))]
                if plain:
                    entities = await self._resolve_entities_by_label(
                        plain, user_query=user_query, ts_bearing=ts_entities
                    )
            # T05: prefer HBCO concept brick class over static keyword map
            class_target = None
            _hbco_concepts = state.intermediate_results.get("concepts") or []
            for _cm in _hbco_concepts:
                _bc = _cm.get("brick_classes") or []
                if _bc:
                    class_target = _bc[0]
                    logger.info(
                        f"[sparql] class from HBCO concept "
                        f"'{_cm.get('concept_id')}': {class_target}"
                    )
                    break
            if not class_target:
                class_target = self._infer_class(user_query.lower())
            instance_candidates = []
            if not entities and class_target:
                # attempt instance discovery before LLM
                try:
                    instance_candidates = await self._get_instances_for_class(
                        class_target, limit=40
                    )
                    if not instance_candidates:
                        # fallback pattern search
                        pattern_candidates = await self._pattern_instance_search(
                            class_target, limit=40
                        )
                        instance_candidates.extend(pattern_candidates)
                    if instance_candidates:
                        logger.info(
                            f"Discovered {len(instance_candidates)} instance candidates for {class_target}"
                        )
                except Exception as e:
                    logger.warning(f"Instance candidate discovery failed: {e}")

            # Portable floor-scoped resolution first: "compare temperature between
            # floor 1 and floor 5" → resolve the metric's sensors per floor via the
            # Brick spatial hierarchy (no building-specific label parsing). Falls
            # through when the query names no floor + inferrable metric.
            sparql_query = self._floor_scoped_sparql(user_query, class_target)
            if sparql_query is not None:
                logger.info("[sparql] using deterministic floor-scoped template (portable)")

            # Phase 3.1: Template-first routing (zero LLM for common patterns)
            # Expanded dynamically using OntologyIntrospector discovered classes
            if sparql_query is None:
                sparql_query = self._template_sparql(user_query, entities, ts_entities)

            used_template = sparql_query is not None
            # Default analytics decision for template queries
            # Most sensor queries need analytics=True because users want DATA/VALUES
            analytics_required = self._should_require_analytics(user_query, entities)
            llm_reasoning = "Template-based query - analytics decision heuristic"

            # Format conversation history for context
            conversation_history = format_conversation_history(state.messages, max_messages=5)
            logger.info("─" * 80)
            logger.info("SPARQL AGENT: Conversation History")
            logger.info("─" * 80)
            if conversation_history and conversation_history != "(No previous conversation)":
                logger.info(f"📜 Including conversation context:\n{conversation_history}")
            else:
                logger.info("📜 No previous conversation context")
            logger.info("─" * 80)

            if sparql_query is None:
                logger.info("🤖 Using LLM to generate SPARQL query with conversation context")
                # LLM generation - returns dict with sparql, analytics, reasoning
                # Phase 10E — pass building_id so the SPARQL prompt's prefix
                # block uses this conversation's per-building namespace.
                llm_result = await self._generate_sparql(
                    user_query,
                    context,
                    instance_candidates,
                    class_target,
                    conversation_history,
                    building_id=getattr(state, "building_id", None),
                )
                sparql_query = llm_result["sparql"]
                analytics_required = llm_result["analytics"]
                llm_reasoning = llm_result.get("reasoning", "")
                logger.info(f"✅ LLM determined: analytics_required={analytics_required}")
                logger.info(f"💭 LLM reasoning: {llm_reasoning}")
            else:
                logger.info(f"Using template SPARQL (entities={entities}):")
                logger.info(sparql_query)

            # Step 3: Legacy-style postprocessing fixes (spacing/prefix issues) then validate
            sparql_query = self._postprocess_query(sparql_query)
            # Ensure required prefixes present (legacy add_sparql_prefixes behavior)
            sparql_query = self._ensure_prefixes(sparql_query)

            # Step 4+5: Phase 3.4 — Validate + B.5 self-correction + cache-aware execute
            async def _wrapped_execute(query: str) -> Dict[str, Any]:
                try:
                    res, _from_cache = await sparql_validator.validate_and_execute(
                        query, executor=self._execute_query, use_cache=True
                    )
                    if _from_cache:
                        logger.info("📦 SPARQL result served from cache")
                    bindings = res.get("results", {}).get("bindings", [])
                    return {
                        "success": True,
                        "results": res,
                        "error": None if bindings else "Empty results",
                    }
                except ValueError as _ve:
                    return {"success": False, "results": {}, "error": str(_ve)}
                except Exception as _ex:
                    return {"success": False, "results": {}, "error": str(_ex)}

            # Phase 11B — correction engine context is per-request; resolve the
            # building namespace/prefix from the active conversation so multi-tenant
            # SPARQL repair targets the right ontology graph.
            _bctx_for_correction = None
            try:
                from orchestrator.services.building_context import (
                    resolve_building_context,
                )

                _bctx_for_correction = resolve_building_context(getattr(state, "building_id", None))
            except Exception:
                pass
            _ctx = {
                "building_namespace": (
                    _bctx_for_correction.namespace
                    if _bctx_for_correction
                    else settings.BUILDING_NAMESPACE
                ),
                "building_prefix": (
                    _bctx_for_correction.prefix
                    if _bctx_for_correction
                    else settings.BUILDING_PREFIX
                ),
                "user_query": user_query,
                "llm_call": None,
            }
            correction_result = await self._correction_engine.execute_with_correction(
                sparql_query, _wrapped_execute, _ctx
            )
            results = correction_result.get("results", {})
            from_cache = False  # correction engine doesn't surface this flag directly

            # NEW: Fallback if no results
            has_results = False
            if results and isinstance(results, dict):
                bindings = results.get("results", {}).get("bindings", [])
                has_results = len(bindings) > 0

            if not has_results:
                logger.warning("SPARQL returned no results, attempting semantic fallback")
                return await self.answer_semantically(state, user_query, context)

            # Step 6: Standardize + Format results
            standardized = self._standardize_results(results, user_query, sparql_query)
            formatted = await self._format_results(results, user_query, sparql_query, used_template)

            return {
                "success": True,
                "query": sparql_query,
                "results": results,
                "formatted_response": formatted,
                "standardized": standardized,
                "context": context,
                "analytics_required": analytics_required,  # NEW: Flag for further analysis
                "llm_reasoning": llm_reasoning,  # NEW: LLM's reasoning about analytics decision
            }

        except Exception as e:
            logger.error(f"SPARQL generation error: {e}", exc_info=True)
            return {"success": False, "error": str(e), "query": None, "results": None}

    async def _retrieve_context(self, query: str) -> List[str]:
        """
        🧠 GRAPHDB RAG RETRIEVAL (New Architecture)

        Uses GraphDB's 2-step Ontotext technique:
        1. Vector similarity search returns entity IRIs
        2. SPARQL fetches bounded context (triples around entities)

        Returns: List of context strings with prefixes and triples for SPARQL generation
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Use GraphDB RAG endpoint
                try:
                    logger.info(f"🔍 Using GraphDB RAG retrieval for: {query[:100]}")

                    graphdb_response = await client.post(
                        f"{RAG_SERVICE_URL}/graphdb/retrieve",
                        json={
                            "query": query,
                            "top_k": 10,  # Entity retrieval limit
                            "hops": 2,  # Graph traversal depth
                            "min_score": 0.3,  # Similarity threshold
                        },
                    )
                    graphdb_response.raise_for_status()
                    graphdb_data = graphdb_response.json()

                    # Extract structured context
                    if graphdb_data.get("status") == "success":
                        logger.info(f"✅ GraphDB RAG successful:")
                        logger.info(f"   - Entities: {graphdb_data['metadata']['entity_count']}")
                        logger.info(f"   - Triples: {graphdb_data['metadata']['triple_count']}")

                        # Build context for SPARQL generation
                        prefix_declarations = graphdb_data.get("prefix_declarations", "")
                        summary = graphdb_data.get("summary", "")
                        triples = graphdb_data.get("triples", [])

                        # Format triples for LLM
                        triple_text = "\n".join(
                            [
                                f"  {t['subject']} {t['predicate']} {t['object']} ."
                                for t in triples[:50]  # Limit to prevent token explosion
                            ]
                        )

                        # Build unified context
                        context_text = f"""=== GRAPHDB KNOWLEDGE BASE ===

PREFIXES:
{prefix_declarations}

{summary}

TRIPLES (Graph Structure):
{triple_text}
"""

                        return [context_text]

                    logger.warning("GraphDB RAG returned unsuccessful status")
                    return []

                except Exception as e:
                    logger.warning(f"GraphDB RAG failed: {e}")
                    return []

        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")
            return []

        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")
            return []

    async def _generate_sparql(
        self,
        user_query: str,
        context: List[str],
        candidates: List[str],
        class_target: Optional[str],
        conversation_history: str = "",
        building_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate SPARQL query using LLM with Brick Schema context

        Args:
            user_query: The current user query
            context: RAG context from knowledge graph
            candidates: Candidate instances
            class_target: Target class (if identified)
            conversation_history: Formatted conversation history for context

        Returns:
            Dict with:
                - 'sparql': str - The SPARQL query
                - 'analytics': bool - Whether further analysis is needed after SPARQL execution
                - 'reasoning': str - LLM's reasoning about whether exact answer exists in context
        """

        # Phase 11B — resolve building context once for use throughout the prompt;
        # falls back to settings when no building_id was supplied.
        try:
            from orchestrator.services.building_context import resolve_building_context

            _bctx = resolve_building_context(building_id)
            _bldg_prefix = _bctx.prefix
            _bldg_namespace = _bctx.namespace
            _bldg_timezone = _bctx.timezone or settings.BUILDING_TIMEZONE
        except Exception:
            _bldg_prefix = settings.BUILDING_PREFIX
            _bldg_namespace = settings.BUILDING_NAMESPACE
            _bldg_timezone = settings.BUILDING_TIMEZONE

        # Get current time in building's local timezone
        try:
            local_time = datetime.now(ZoneInfo(_bldg_timezone))
            current_time_str = local_time.strftime("%A, %B %d, %Y, %H:%M %Z")
        except Exception:
            current_time_str = datetime.now().strftime("%A, %B %d, %Y, %H:%M (UTC)")

        # Check if we have a unified smart context (starts with header)
        is_smart_context = len(context) > 0 and "=== ONTOLOGY KNOWLEDGE BASE ===" in context[0]

        # Add conversation history section if available
        history_section = (
            f"\n\n=== CONVERSATION HISTORY ===\n{conversation_history}\n"
            if conversation_history and conversation_history != "(No previous conversation)"
            else ""
        )

        # C.2: Build dynamic building profile from live introspector data (if available)
        try:
            from orchestrator.services.ontology_introspector import (
                ontology_introspector,
            )

            _sensor_classes = (
                ontology_introspector.sensor_classes if ontology_introspector.is_ready() else []
            )
            _ns_map = (
                ontology_introspector.namespace_map if ontology_introspector.is_ready() else {}
            )
        except Exception:
            _sensor_classes, _ns_map = [], {}
        _building_profile = self._prompt_builder.sparql_system_hints(_sensor_classes, _ns_map)

        if is_smart_context:
            # Use the pre-built unified context directly
            full_context = "\n\n".join(context)
            sparql_prompt = f"""Given a natural language query about a building and context from GraphRAG knowledge graph, generate an accurate SPARQL query using correct RDF prefixes.
Current Date and Time: {current_time_str}

{_building_profile}

=== GRAPHRAG CONTEXT ===
{full_context}{history_section}

=== USER QUERY ===
{user_query}

NOTE: If this query references previous results (e.g., "give me all", "detailed list", "show everything"), use the conversation history to understand what was previously requested and expand on it.

=== OUTPUT FORMAT ===
Respond with JSON containing exactly TWO keys:

1. "analytics" (boolean) - Determines if SPARQL results need further processing:
   
   FALSE = Query is about METADATA (structural information already in ontology):
   - "List all sensors" → Just entity names/types
   - "Where is sensor X located?" → Location property from ontology
   - "What equipment in zone Y?" → Equipment list from ontology
   - "What is the UUID of X?" → UUID property from ontology
   
   TRUE = Query is about DATA/VALUES (requires time-series database access or analytics):
   - "What temperature sensors in room 5.01?" → Needs CURRENT temperature readings
   - "What is the CO2 level?" → Needs REAL-TIME sensor values
   - "Average temperature in building?" → Needs to COMPUTE from readings
   - "Which rooms have high CO2?" → Needs to COMPARE values against threshold
   - Any query with: "level", "reading", "value", "current", "yesterday", "trend", "average", "min", "max"
   - any computation or comparison on sensor data
   KEY INSIGHT: Most sensor queries = TRUE (users want data, not just sensor names!)

2. "sparql" (string) - The SPARQL query to execute

=== SPARQL GENERATION RULES ===

1. Analyze the query to identify:
   - Entities being asked about (sensors, zones, equipment)
   - Properties/relationships needed
   - Filters or conditions

2. Map to ontology concepts using context:
   - "temperature sensors" → brick:Air_Temperature_Sensor
   - "room 5.01" → bldg:Room_5.01 or filter CONTAINS "5.01"
   - "location" → brick:hasLocation property
   - "next to", "adjacent", "nearby" → rec:adjacentElement
   - "contains", "inside" → rec:containsElement or rec:locatedIn (inverse)
   - "zone", "floor" → rec:Zone, rec:Level

3. Construct query with:
   - PREFIX declarations (ONLY what's actually used)
   - SELECT clause with all needed variables
   - WHERE clause with triple patterns from context
   - FILTER clauses for conditions
   - OPTIONAL blocks for non-critical data

4. CRITICAL - External Timeseries References:
   For ANY sensor/device query, ALWAYS include UUID retrieval using the exact path from the ontology context:
   
   OPTIONAL {{
     ?sensor ref:hasExternalReference ?ref .
     ?ref ref:hasTimeseriesId ?uuid .
     ?ref ref:storedAt ?storage .
   }}
   
   Add ?uuid and ?storage to SELECT clause. This enables downstream time-series queries.
   KEY INSIGHT: when "analytics" (boolean) is TRUE, UUID and storedAt are ESSENTIAL for data retrieval!
   
   DO NOT use 'bldg:connstring' unless it explicitly appears in the context triples.

5. Use ONLY the following prefixes (if needed):
{self._prefix_block(building_id=building_id)}

6. Use exact URIs from context. Prefer OPTIONAL for optional properties.

=== EXAMPLE OUTPUT ===

{{
  "analytics": true,
  "sparql": "PREFIX brick: <https://brickschema.org/schema/Brick#>\\nPREFIX bldg: <{settings.BUILDING_NAMESPACE}>\\nPREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\\nPREFIX ref: <https://brickschema.org/schema/Brick/ref#>\\n\\nSELECT ?sensor ?location ?uuid ?storage WHERE {{\\n  BIND(bldg:CO2_Level_Sensor_5.08 AS ?sensor)\\n  OPTIONAL {{ ?sensor brick:hasLocation ?location . }}\\n  OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }}\\n}} LIMIT 50"
}}

=== STRICT REQUIREMENTS ===
- USE ONLY classes/properties from the provided context
- If specific instance URI provided in context, USE IT directly (e.g. BIND(bldg:X AS ?sensor))
- DO NOT attempt to compute averages, min/max, or retrieve time-series values (like brick:hasValue) in SPARQL.
- If analytics=true, ONLY retrieve the UUID and storage location. The analytics engine will handle the data.
- Use 'bldg:' prefix for building instances, 'brick:' for schema classes
- Escape newlines as \\n for valid JSON
- Include LIMIT clause (default 50) to prevent large result sets
- Ensure syntactically valid SPARQL (matching braces, correct syntax)

=== MANDATORY SPARQL PATTERN FOR SENSORS ===
If the query involves a specific sensor or device, you MUST generate a query matching this EXACT pattern:

PREFIX {_bldg_prefix}: <{_bldg_namespace}>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX ashrae: <http://data.ashrae.org/standard223#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?timeseriesID ?database
WHERE {{
    ?sensor ashrae:hasExternalReference ?extRef .

    ?extRef ref:hasTimeseriesId ?timeseriesID ;
            ref:storedAt ?database .

    # Filter for the specific entity found in context/query
    FILTER(?sensor = {_bldg_prefix}:ENTITY_NAME)
}}

Replace {_bldg_prefix}:ENTITY_NAME with the actual URI found in the context (e.g. {_bldg_prefix}:CO2_Level_Sensor_5.08).
Do NOT add other OPTIONAL blocks or properties.
Do NOT use '{_bldg_prefix}:connstring'.
Do NOT use 'ref:hasExternalReference' directly on the sensor (use ashrae:hasExternalReference).
"""
        else:
            # Fallback: Limited context available
            context_preview = "\n".join(context[:10]) if context else "No context available"
            candidate_preview = "\n".join(candidates[:30]) if candidates else "None"
            class_hint = class_target or "Unknown"

            sparql_prompt = f"""Given a natural language query about a building, generate SPARQL using the building's ontology schema.

{_building_profile}

=== AVAILABLE CONTEXT ===
{context_preview}

=== CANDIDATE INSTANCES ===
{candidate_preview}

=== TARGET CLASS ===
{class_hint}{history_section}

=== USER QUERY ===
{user_query}

NOTE: If this query references previous results (e.g., "give me all", "detailed list"), check the conversation history above.

=== OUTPUT FORMAT ===
JSON with TWO keys:

1. "analytics" (boolean):
   FALSE = Metadata query (list sensors, get UUID, show location)
   TRUE = Data query (sensor readings, current values, computations, trends)
   
   Most sensor queries need TRUE (users want data, not just names!)

2. "sparql" (string): The SPARQL query

=== SPARQL RULES ===
1. Use ONLY given prefixes.

2. For sensor queries, ALWAYS retrieve UUID and Storage Location when "analytics" (boolean): guessed TRUE
   You MUST use this EXACT pattern:
   
   ?sensor ashrae:hasExternalReference ?extRef .
   ?extRef ref:hasTimeseriesId ?timeseriesID ;
           ref:storedAt ?database .
   
   DO NOT use 'bldg:connstring'.
   DO NOT retrieve time-series data (values, timestamps) or perform aggregations (AVG, MIN, MAX) in SPARQL.
   ONLY retrieve metadata (UUID, storage).

3. Use candidate instances if available.
   - If user asks for a specific sensor by name (e.g. "Sensor_5.08"), FILTER by URI or Label:
     FILTER(CONTAINS(STR(?sensor), "5.08") || CONTAINS(STR(?label), "5.08"))
   - Ensure ?label is retrieved: OPTIONAL {{ ?sensor rdfs:label ?label }}

4. Add FILTER for specific room/zone mentions
5. Include LIMIT only when user explicitely saids so
6. Escape newlines as \\n

Example:
{{
  "analytics": true,
  "sparql": "PREFIX brick: <...>\\nPREFIX ref: <...>\\nSELECT ?sensor ?uuid ?storage WHERE {{ ?sensor rdf:type brick:Air_Temperature_Sensor . OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} }}"
}}"""

        # Check cache
        prompt_hash = generate_hash(sparql_prompt)
        cache_key = f"cache:sparql_gen:{prompt_hash}"
        cached_result = await redis_manager.get_cache(cache_key)

        if cached_result:
            logger.info(f"✅ Cache hit for SPARQL generation: {prompt_hash}")
            return cached_result

        response = await llm_manager.generate(sparql_prompt, task_type=TaskType.SPARQL)

        # Parse JSON response from LLM
        try:
            # Try to extract JSON from response (in case LLM wraps it in markdown)
            json_match = re.search(r'\{[\s\S]*"analytics"[\s\S]*"sparql"[\s\S]*\}', response)
            if json_match:
                response = json_match.group(0)

            parsed = json.loads(response)

            analytics = parsed.get("analytics", False)
            sparql = parsed.get("sparql", "")

            # Unescape newlines in SPARQL
            sparql = sparql.replace("\\n", "\n").replace("\\t", "\t")

            # Validate we got both required fields
            if not sparql:
                raise ValueError("SPARQL query is empty in LLM response")

            logger.info(f"LLM Analysis Decision: analytics={analytics}")
            logger.info(f"Generated SPARQL query:\n{sparql}")

            result = {
                "sparql": sparql,
                "analytics": analytics,
                "reasoning": f"LLM determined analytics={'required' if analytics else 'not required'}",
            }

            # Cache result
            await redis_manager.set_cache(cache_key, result, ttl=3600)

            return result

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse JSON response from LLM: {e}")
            logger.warning(f"Raw LLM response: {response[:500]}")

            # Fallback: Extract SPARQL using traditional method and assume analytics=False
            sparql = extract_sparql_from_llm_response(response)

            return {
                "sparql": sparql,
                "analytics": False,  # Default to no analytics if parsing fails
                "reasoning": "Fallback: Could not parse JSON, using traditional SPARQL extraction",
            }

    async def _repair_query(self, query: str, user_query: str, context: List[str]) -> str:
        """Attempt to repair invalid SPARQL query"""

        repair_prompt = f"""The following SPARQL query has syntax errors:

{query}

Original user request: {user_query}

Please fix the syntax errors and return a valid SPARQL query. Common issues:
- Missing or incorrect prefixes
- Unclosed braces
- Invalid URI syntax
- Missing periods or semicolons

Return ONLY the corrected SPARQL query."""

        response = await llm_manager.generate(repair_prompt, task_type=TaskType.SPARQL)
        repaired = extract_sparql_from_llm_response(response)

        logger.info(f"Repaired SPARQL query:\n{repaired}")
        return repaired

    def _floor_scoped_sparql(self, user_query: str, class_target: Optional[str]) -> Optional[str]:
        """Deterministic, building-portable floor-scoped sensor resolver.

        For queries naming one or more floors plus an inferrable metric
        ("compare temperature between floor 1 and floor 5", "average CO2 on
        floor 3"), resolve that metric's sensors per floor through the Brick
        spatial hierarchy: sensor → brick:hasLocation → (isPartOf|^hasPart)* →
        brick:Floor. No building-specific label parsing, so it keeps working
        after a building swap. Returns None when the query names no floor or no
        metric class can be inferred (callers fall through to the normal path).
        """
        floors = re.findall(r"\b(?:floor|level)\s*(\d+)\b", user_query, re.IGNORECASE)
        floors = sorted(set(floors), key=int)
        if not floors:
            return None

        # This resolver answers questions about the SENSORS on a floor. A
        # question about the floor's spaces ("how many rooms are on floor 2")
        # also names a floor, and answering it with a sensor query returns
        # nothing — so the honest-sounding "no rooms found" was produced while
        # the graph held them. Defer to the space templates unless the question
        # also asks for a measurement.
        _uq = user_query.lower()
        _asks_about_spaces = self._mentions(
            _uq, ["room", "rooms", "zone", "zones", "space", "spaces"]
        )
        _asks_for_readings = self._infer_class(_uq) is not None or self._mentions(
            _uq, ["sensor", "sensors", "reading", "readings", "measurement", "measurements"]
        )
        if _asks_about_spaces and not _asks_for_readings:
            return None
        floor_in = ", ".join(f'"{f}"' for f in floors)
        # Build the point SELECTOR with two naming-agnostic tiers:
        #  1) Brick class (preferred) — from the keyword map or the HBCO concept.
        #  2) rdfs:label text-match on the salient query terms — works for ANY URI
        #     naming scheme (e.g. bldg:bldgx.ZONE.AHU01.RM123.Zone_Air_Temp) as long
        #     as the point is labelled (every point carries rdfs:label).
        # Either way resolution keys off class/label/location, never the URI string.
        cls = self._infer_class(user_query.lower()) or class_target
        if cls:
            # TBOX rollup, not exact type: sensors are typed as SUBCLASSES of the
            # inferred class (bldg1 -> Air_Temperature_Sensor, bldg2 -> Zone_Air/
            # Water_Temperature_Sensor, …). An exact `?sensor a Temperature_Sensor`
            # would match none of them. rdf:type/rdfs:subClassOf* keeps it
            # building-agnostic — it resolves whatever subclass the building uses.
            type_clause = f"?sensor rdf:type/rdfs:subClassOf* {cls} ."
            label_clause = ""
            logger.info(f"[sparql] floor-scoped resolve: class={cls} floors={floors}")
        else:
            terms = self._salient_terms(user_query)
            if not terms:
                return None
            type_clause = ""
            label_clause = (
                "FILTER(" + " && ".join(f'CONTAINS(LCASE(STR(?label)), "{t}")' for t in terms) + ")"
            )
            logger.info(f"[sparql] floor-scoped resolve: label-match terms={terms} floors={floors}")
        # ref: prefix is not in the standard block — declare it explicitly.
        return (
            self._prefix_block()
            + "\nPREFIX ref: <https://brickschema.org/schema/Brick/ref#>"
            + f"""
SELECT DISTINCT ?sensor ?label ?floorNum ?uuid ?storage WHERE {{
  ?sensor rdfs:label ?label ;
          brick:hasLocation ?loc .
  {type_clause}
  {label_clause}
  ?loc (brick:isPartOf|^brick:hasPart)* ?floor .
  ?floor a brick:Floor .
  BIND(REPLACE(STR(?floor), "^.*[Ff]loor", "") AS ?floorNum)
  FILTER(?floorNum IN ({floor_in}))
  ?sensor ref:hasExternalReference ?ref .
  ?ref ref:hasTimeseriesId ?uuid .
  OPTIONAL {{ ?ref ref:storedAt ?storage }}
}} ORDER BY ?floorNum ?label LIMIT 100"""
        )

    # Stopwords stripped before label text-matching (keep domain nouns).
    _SALIENT_STOP = frozenset(
        {
            "what",
            "whats",
            "is",
            "are",
            "the",
            "on",
            "in",
            "at",
            "of",
            "for",
            "to",
            "me",
            "my",
            "show",
            "give",
            "tell",
            "get",
            "current",
            "latest",
            "reading",
            "readings",
            "value",
            "values",
            "level",
            "levels",
            "please",
            "floor",
            "number",
            "right",
            "now",
            "today",
            "this",
            "much",
            "many",
            "how",
            "there",
            "do",
            "does",
            "and",
            "or",
            "status",
            "data",
            "sensor",
            "sensors",
            "you",
            "have",
            "any",
            "all",
            "with",
            "from",
            "about",
            # comparison / aggregation / structure words — not metric nouns, so they
            # must not become label-match terms ("compare floor 1 and floor 5").
            "compare",
            "comparison",
            "between",
            "versus",
            "difference",
            "vs",
            "average",
            "mean",
            "trend",
            "highest",
            "lowest",
            "maximum",
            "minimum",
        }
    )

    def _salient_terms(self, user_query: str, limit: int = 4) -> List[str]:
        """Domain keywords for naming-agnostic rdfs:label matching.

        Lowercases, strips punctuation (so 'run-time' -> 'run', 'time'), drops
        stopwords and bare numbers, dedupes, and caps the count so the ANDed
        label filter stays specific without over-constraining."""
        raw = re.sub(r"[^a-z0-9]+", " ", user_query.lower())
        out: List[str] = []
        for t in raw.split():
            if len(t) >= 3 and not t.isdigit() and t not in self._SALIENT_STOP and t not in out:
                out.append(t)
        return out[:limit]

    def _template_sparql(
        self,
        user_query: str,
        entities: List[str],
        ts_entities: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """Return a direct SPARQL template for common sensor/location/entity queries with feature detection."""
        uq = user_query.lower()
        features = self._classify_query(uq)
        ts_entities = ts_entities or set()

        # Special case: Building name query
        if ("building" in uq and "name" in uq) or "name of" in uq or "which building" in uq:
            # Query for building entity with rdfs:label
            return (
                self._prefix_block()
                + """
SELECT ?building ?label ?comment WHERE {
  ?building a brick:Building .
  OPTIONAL { ?building rdfs:label ?label . }
  OPTIONAL { ?building rdfs:comment ?comment . }
} LIMIT 5"""
            )

        # Entity-focused specialized queries
        if entities:
            # Detect if any entity is a Zone/Room/Space (location) vs a sensor
            zone_entities = [
                e
                for e in entities
                if re.search(r"bldg:Zone_\d|bldg:Room_|bldg:Space_|bldg:Floor_", e)
            ]
            sensor_entities = [e for e in entities if e not in zone_entities]

            # Room/floor lookup for a zone: "what room is zone 5.14 in?"
            # Interrogative phrases only — a bare "room" substring would hijack
            # measurement queries ("latest temperature reading in room 5.01")
            # into this topology template, so SQL never receives a UUID.
            _room_words = ["which room", "what room", "which floor", "what floor", "which level"]
            _measurement_words = ("temperature", "humidity", "co2", "reading", "value", "sensor")
            if (
                zone_entities
                and any(w in uq for w in _room_words)
                and not any(m in uq for m in _measurement_words)
            ):
                patterns = []
                for zone in zone_entities:
                    # Zone is part of a Room (brick:isPartOf)
                    patterns.append(
                        f"{{ {zone} brick:isPartOf ?parent . "
                        f"OPTIONAL {{ ?parent rdfs:label ?label . }} "
                        f"FILTER(CONTAINS(STR(?parent), 'Room') || CONTAINS(STR(?parent), 'Floor')) }}"
                    )
                union_block = " UNION ".join(patterns)
                return (
                    self._prefix_block()
                    + f"\nSELECT DISTINCT ?parent ?label WHERE {{ {union_block} }} ORDER BY ?parent"
                )

            # Adjacency query: "what zones are adjacent/nearby to zone 5.28?"
            _adj_words = ["adjacent", "nearby", "next to", "neighboring", "neighbour", "neighbours"]
            if zone_entities and any(w in uq for w in _adj_words):
                patterns = []
                for zone in zone_entities:
                    patterns.append(
                        f"{{ {zone} brick:isAdjacentTo ?adjacent . OPTIONAL {{ ?adjacent rdfs:label ?label . }} }}"
                    )
                union_block = " UNION ".join(patterns)
                return (
                    self._prefix_block()
                    + f"\nSELECT DISTINCT ?adjacent ?label WHERE {{ {union_block} }} ORDER BY ?adjacent"
                )

            # If we have zone entities → find sensors in those zones with their timeseries UUIDs
            if (
                zone_entities
                and not features["wants_definition"]
                and not features["wants_equipment"]
            ):
                # Infer specific sensor class from query (e.g. temperature → brick:Air_Temperature_Sensor)
                # so we don't return a wrong sensor type that happens to be alphabetically first
                inferred_class = self._infer_class(uq)
                if inferred_class:
                    type_lines = (
                        f"  ?sensor rdf:type {inferred_class} .\n  BIND({inferred_class} AS ?type)"
                    )
                    # For specific type + zone: require UUID (we need it for SQL data fetching)
                    uuid_lines = "  ?ref ref:hasTimeseriesId ?uuid .\n  ?ref ref:storedAt ?storage .\n  ?sensor ref:hasExternalReference ?ref ."
                    patterns = []
                    for zone in zone_entities:
                        patterns.append(
                            f"""{{\n  ?sensor brick:hasLocation {zone} .\n{type_lines}\n  ?sensor rdfs:label ?label .\n{uuid_lines}\n}}"""
                        )
                    union_block = " UNION ".join(patterns)
                    return (
                        self._prefix_block()
                        + f"\nSELECT ?sensor ?label ?type ?uuid ?storage WHERE {{\n{union_block}\n}} LIMIT 50"
                    )
                else:
                    # Generic sensor listing (no type filter): use DISTINCT and OPTIONAL uuid
                    # to avoid LIMIT explosion from sensors with many external refs
                    patterns = []
                    for zone in zone_entities:
                        patterns.append(
                            f"""{{
  ?sensor brick:hasLocation {zone} .
  ?sensor rdf:type ?type .
  FILTER(CONTAINS(STR(?type), 'Sensor') && !CONTAINS(STR(?type), '#Sensor') && STRSTARTS(STR(?type), 'https://brickschema'))
  ?sensor rdfs:label ?label .
  OPTIONAL {{
    ?sensor ref:hasExternalReference ?ref .
    ?ref ref:hasTimeseriesId ?uuid .
    ?ref ref:storedAt ?storage .
  }}
}}"""
                        )
                    union_block = " UNION ".join(patterns)
                    return (
                        self._prefix_block()
                        + f"\nSELECT DISTINCT ?sensor ?label ?type ?uuid ?storage WHERE {{\n{union_block}\n}} ORDER BY ?sensor LIMIT 50"
                    )

            # Order of checks matters: prioritize equipment and definition before uuid-only.
            #
            # ...EXCEPT when the entities we resolved are themselves timeseries-bearing points.
            # "vav" and "ahu" are equipment keywords, so "what is the damper position of
            # VAV_Floor5_West?" set wants_equipment and returned this topology template --
            # which selects ?label ?equipment ?equipLabel and NO uuid. The pipeline then read
            # sparql_has_uuids=False, never ran the SQL node, and answered with the sensor's
            # NAME where a percentage was asked for. The reading existed the whole time.
            #
            # The distinction is the question's subject: "what equipment serves X" is topology,
            # "what is X's damper position" is a measurement that merely NAMES equipment to
            # locate the point. Once the point is resolved and confirmed ts-bearing, it is the
            # subject, and the reading template is the right shape.
            _resolved_points = bool(ts_entities) and all(e in ts_entities for e in entities)
            if features["wants_equipment"] and not _resolved_points:
                patterns = []
                for ent in entities:
                    # sensor → equipment: brick:isPointOf / brick:hasPoint
                    patterns.append(
                        f"{{ {ent} brick:isPointOf ?equipment . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} }}"
                    )
                    patterns.append(
                        f"{{ ?equipment brick:hasPoint {ent} . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} }}"
                    )
                    # zone/location → equipment: feeds / isFedBy
                    patterns.append(
                        f"{{ ?equipment brick:feeds {ent} . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} }}"
                    )
                    patterns.append(
                        f"{{ {ent} brick:isFedBy ?equipment . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} }}"
                    )
                union_block = " \n UNION \n ".join(patterns)
                return (
                    self._prefix_block()
                    + f"\nSELECT DISTINCT ?label ?equipment ?equipLabel WHERE {{ {union_block} }}"
                )

            # Enhanced definition query - get label AND definition for specific entity
            if features["wants_definition"] or "label" in uq or "definition" in uq:
                # Query for specific entity's label and definition
                patterns = []
                for ent in entities:
                    patterns.append(
                        f"""{{
  {ent} rdfs:label ?label .
  OPTIONAL {{ {ent} rdfs:comment ?def . }}
  OPTIONAL {{ {ent} skos:definition ?def2 . }}
  BIND(COALESCE(?def, ?def2, "No definition available") AS ?definition)
}}"""
                    )
                union_block = " \n UNION \n ".join(patterns)
                return (
                    self._prefix_block() + f"\nSELECT ?label ?definition WHERE {{ {union_block} }}"
                )

            if features["wants_location"]:
                patterns = []
                for ent in entities:
                    patterns.append(
                        f"{{ {ent} brick:hasLocation ?location . OPTIONAL {{ ?location rdfs:label ?locLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} OPTIONAL {{ {ent} ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} OPTIONAL {{ {ent} bldg:connstring ?uuid . }} }}"
                    )
                union_block = " \n UNION \n ".join(patterns)
                return (
                    self._prefix_block()
                    + f"\nSELECT ?label ?location ?locLabel ?uuid ?storage WHERE {{ {union_block} }}"
                )
            if (
                features["wants_uuid"]
                and not features["wants_label"]
                and not features["wants_location"]
            ):
                patterns = []
                for ent in entities:
                    patterns.append(
                        f"{{ {ent} ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} UNION {{ {ent} bldg:connstring ?uuid . }}"
                    )
                union_block = " \n UNION \n ".join(patterns)
                return self._prefix_block() + f"\nSELECT ?uuid ?storage WHERE {{ {union_block} }}"
            if (features["wants_label"] or features["wants_uuid"]) and not features[
                "wants_location"
            ]:
                patterns = []
                for ent in entities:
                    patterns.append(
                        f"{{ {ent} rdfs:label ?label . OPTIONAL {{ {ent} bldg:connstring ?uuid . }} }}"
                    )
                union_block = " \n UNION \n ".join(patterns)
                return self._prefix_block() + f"\nSELECT ?label ?uuid WHERE {{ {union_block} }}"

        # ── T0: All-zones sensor-type query (e.g. "temperature across all zones") ──
        # Must run BEFORE T1/T2 so it captures sensor UUIDs, not just zone names
        zone_words = ["zone", "zones", "room", "rooms", "space", "spaces"]
        all_zones_words = [
            "all zones",
            "all rooms",
            "all spaces",
            "every zone",
            "across zones",
            "across all",
            "building-wide",
            "building wide",
            "each zone",
            "each room",
        ]
        inferred_class_t0 = self._infer_class(uq)
        if (
            inferred_class_t0
            and (
                any(aw in uq for aw in all_zones_words)
                or ("all" in uq and any(w in uq for w in zone_words))
            )
            and not entities
        ):
            return (
                self._prefix_block()
                + f"""
SELECT ?sensor ?label ?type ?uuid ?storage WHERE {{
  ?sensor rdf:type {inferred_class_t0} .
  BIND({inferred_class_t0} AS ?type)
  ?sensor rdfs:label ?label .
  ?ref ref:hasTimeseriesId ?uuid .
  ?ref ref:storedAt ?storage .
  ?sensor ref:hasExternalReference ?ref .
}} LIMIT 200"""
            )

        # ── E.5: 5 additional template patterns ─────────────────────────────
        # T0.6: Zones (or sensors) on a specific floor ("what zones are on floor 5?")
        floor_words = ["floor", "floors", "storey", "storeys", "level", "levels"]
        _floor_num_m = re.search(r"\b(?:floor|storey|level)\s*(\d+)\b", uq)
        if _floor_num_m and any(w in uq for w in zone_words):
            # Find the floor by its NUMBER rather than by rebuilding its IRI.
            # Buildings spell floors differently ("floor2", "Floor_2", label
            # "Level 2"), so a constructed IRI matches one convention and
            # silently returns nothing for every other building. Both part-of
            # directions are traversed because either may be the asserted one,
            # and rooms count as spaces — a floor's rooms are what "how many
            # rooms on floor N" is asking for.
            n = _floor_num_m.group(1)
            # Count what was actually asked for. A room is usually also typed as
            # a zone, so counting every space type answers "how many rooms" with
            # the room count plus the zone count.
            if self._mentions(uq, ["room", "rooms"]):
                type_union = "{ ?zone a brick:Room }"
            elif self._mentions(uq, ["zone", "zones"]):
                type_union = "{ ?zone a brick:HVAC_Zone } UNION { ?zone a brick:Zone }"
            else:
                type_union = (
                    "{ ?zone a brick:Room } UNION { ?zone a brick:HVAC_Zone } "
                    "UNION { ?zone a brick:Zone } UNION { ?zone a brick:Space }"
                )
            floor_match = (
                "  { ?floor a brick:Floor . } UNION { ?floor a brick:Level . }\n"
                "  OPTIONAL { ?floor rdfs:label ?floorLabel . }\n"
                '  BIND(LCASE(CONCAT(STR(?floor), " ", COALESCE(STR(?floorLabel), ""))) AS ?fhay)\n'
                f'  FILTER(REGEX(?fhay, "(floor|storey|level)[ _-]*0*{n}([^0-9]|$)"))\n'
                "  { ?floor brick:hasPart ?zone } UNION { ?zone brick:isPartOf ?floor }\n"
                f"  {type_union}\n"
            )
            if features["wants_count"]:
                return (
                    self._prefix_block()
                    + f"\nSELECT (COUNT(DISTINCT ?zone) AS ?count) WHERE {{\n{floor_match}}}"
                )
            return (
                self._prefix_block()
                + f"\nSELECT DISTINCT ?zone ?label WHERE {{\n{floor_match}"
                + "  OPTIONAL { ?zone rdfs:label ?label . }\n} ORDER BY ?zone LIMIT 200"
            )

        # T1: List all floors / storeys — only when not asking about zones or equipment on a floor
        _equip_words_t1 = [
            "ahu",
            "vav",
            "hvac",
            "air handler",
            "equipment",
            "fan",
            "pump",
            "meter",
            "boiler",
            "chiller",
            "sensor",
            "serve",
            "serves",
            "feed",
        ]
        _no_equip = not any(w in uq for w in _equip_words_t1)
        _no_zones = not any(w in uq for w in zone_words)
        if (
            any(w in uq for w in floor_words)
            and features["wants_count"]
            and _no_zones
            and _no_equip
        ):
            return (
                self._prefix_block()
                + """
SELECT (COUNT(DISTINCT ?floor) AS ?count) WHERE {
  { ?floor a brick:Floor . } UNION { ?floor a brick:Level . }
}"""
            )
        if any(w in uq for w in floor_words) and not entities and _no_zones and _no_equip:
            return (
                self._prefix_block()
                + """
SELECT ?floor ?label WHERE {
  { ?floor a brick:Floor . } UNION { ?floor a brick:Level . }
  OPTIONAL { ?floor rdfs:label ?label . }
} ORDER BY ?label LIMIT 50"""
            )

        # T2: List all zones / rooms / spaces
        # Zones in this ontology have no rdf:type — discoverable only via brick:hasLocation
        if any(w in uq for w in zone_words) and features["wants_count"] and not entities:
            return (
                self._prefix_block()
                + """
SELECT (COUNT(DISTINCT ?space) AS ?count) WHERE {
  { ?space a brick:Zone . } UNION { ?space a brick:Room . } UNION { ?space a brick:Space . }
  UNION { ?sensor brick:hasLocation ?space . FILTER(CONTAINS(STR(?space), "Zone")) }
}"""
            )
        if any(w in uq for w in zone_words) and not entities:
            return (
                self._prefix_block()
                + f"""
SELECT DISTINCT ?space (COUNT(?sensor) AS ?sensor_count) WHERE {{
  ?sensor brick:hasLocation ?space .
  FILTER(CONTAINS(STR(?space), "Zone") || CONTAINS(STR(?space), "Room") || CONTAINS(STR(?space), "Floor"))
}} GROUP BY ?space ORDER BY ?space LIMIT 100"""
            )

        # T2b: GENERIC sensor count — "how many sensors does this building have?" (no
        # specific type). TBOX COUNT of every brick:Sensor (subclasses included via
        # rdf:type/rdfs:subClassOf*), so it works on ANY building. A named TYPE goes to
        # the class-map count below (temperature → 136); rooms/floors/zones/equipment are
        # handled by their own templates above.
        _sensor_kws = ("sensor", "sensors", "device", "devices", "point", "points")
        if (
            features["wants_count"]
            and any(w in uq for w in _sensor_kws)
            and _no_zones
            and _no_equip
            and not any(w in uq for w in floor_words)
            and not any(k in uq for k in self._get_extended_class_map())
        ):
            return (
                self._prefix_block()
                + "\nSELECT (COUNT(DISTINCT ?s) AS ?count) WHERE "
                + "{ ?s rdf:type/rdfs:subClassOf* brick:Sensor . }"
            )

        # T2c: Building identity — "what building is this?" → name via brick:Building label.
        if any(w in uq for w in ("what building", "which building", "building name")) or (
            "building" in uq and any(w in uq for w in ("name", "called", "which", "what is this"))
        ):
            return (
                self._prefix_block()
                + """
SELECT ?building ?label WHERE {
  ?building a brick:Building . OPTIONAL { ?building rdfs:label ?label . }
} LIMIT 1"""
            )

        # T3a: Direct sensor/entity lookup (entity itself is a sensor/point).
        # Membership is decided by the graph — an entity the resolver confirmed
        # carries a timeseries reference IS a point — with the name check kept
        # only as a fallback for entities that never went through resolution.
        # Naming alone cannot decide this: a building that names points
        # "…Zone_Air_Temp" would fail a "Sensor"/"Point" spelling test and fall
        # through to the class-level template, which answers about every sensor
        # of that class instead of the one that was asked about.
        sensor_entities = [
            e for e in entities if e in ts_entities or re.search(r"(Sensor|Point)", e)
        ]
        if sensor_entities:
            patterns = []
            for ent in sensor_entities:
                patterns.append(
                    f"{{ BIND({ent} AS ?sensor) "
                    f"OPTIONAL {{ ?sensor rdfs:label ?label . }} "
                    f"OPTIONAL {{ ?sensor rdf:type ?type . }} "
                    f"OPTIONAL {{ ?sensor brick:hasUnit ?unit . }} "
                    f"OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} "
                    f"OPTIONAL {{ ?sensor bldg:connstring ?uuid . }} }}"
                )
            union_block = " UNION ".join(patterns)
            return (
                self._prefix_block()
                + f"\nSELECT DISTINCT ?sensor ?label ?type ?uuid ?storage ?unit WHERE {{ {union_block} }} LIMIT 100"
            )

        # T3b: Sensors located in a specific zone/floor/room (entity = location)
        # Only trigger for bldg: instance entities (not class references like brick:Sensor)
        # Phase 15A: per-request building prefix.
        location_entities = [e for e in entities if e.startswith(f"{_active_prefix()}:")]
        # BUG-115: this was written r"\\b(...)\\b" inside a RAW string, so the
        # pattern looked for a literal backslash followed by "b" and could never
        # match — the whole location-scoped branch below was unreachable, and
        # "sensors in Room X" fell through to a broader query that ignored the
        # location. In a raw string \b is already the word boundary.
        if location_entities and re.search(r"\b(in|on|at|within)\b", uq):
            patterns = []
            for ent in location_entities:
                patterns.append(
                    f"{{ ?sensor brick:hasLocation {ent} . OPTIONAL {{ ?sensor rdfs:label ?label . }} "
                    f"OPTIONAL {{ ?sensor rdf:type ?type . }} OPTIONAL {{ ?sensor brick:hasUnit ?unit . }} "
                    f"OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} "
                    f"OPTIONAL {{ ?sensor bldg:connstring ?uuid . }} }}"
                )
                patterns.append(
                    f"{{ ?sensor brick:isLocatedIn {ent} . OPTIONAL {{ ?sensor rdfs:label ?label . }} "
                    f"OPTIONAL {{ ?sensor rdf:type ?type . }} OPTIONAL {{ ?sensor brick:hasUnit ?unit . }} "
                    f"OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} "
                    f"OPTIONAL {{ ?sensor bldg:connstring ?uuid . }} }}"
                )
            union_block = " UNION ".join(patterns)
            return (
                self._prefix_block()
                + f"\nSELECT DISTINCT ?sensor ?label ?type ?uuid ?storage ?unit WHERE {{ {union_block} }} LIMIT 100"
            )

        # T4: Equipment / HVAC / AHU / VAV listing
        equipment_keywords = {
            "hvac": "brick:HVAC_System",
            "air handler": "brick:Air_Handler_Unit",
            "air handling": "brick:Air_Handler_Unit",
            "ahu": "brick:Air_Handler_Unit",
            "vav": "brick:VAV",
            "variable air volume": "brick:VAV",
            "boiler": "brick:Boiler",
            "chiller": "brick:Chiller",
            "fan": "brick:Fan",
            "pump": "brick:Pump",
            "damper": "brick:Damper",
            "actuator": "brick:Actuator",
        }
        for kw, equip_class in equipment_keywords.items():
            # Whole-word only: an equipment type is also a prefix of the units a
            # building names after it ("ahu" in "AHU01N", "fan" in "fancoil-3"),
            # so a substring test turns a reading request into an equipment listing.
            if self._mentions(uq, [kw]):
                if features["wants_count"]:
                    return (
                        self._prefix_block()
                        + f"\nSELECT (COUNT(?equip) AS ?count) WHERE {{ ?equip a {equip_class} . }}"
                    )
                # For generic 'hvac' keyword, query all HVAC-related types (AHU, VAV, etc.)
                if kw == "hvac":
                    return (
                        self._prefix_block()
                        + """
# HVAC Equipment listing
SELECT ?equip ?label ?type WHERE {
  { ?equip a brick:Air_Handler_Unit . BIND("HVAC Air Handler Unit" AS ?type) }
  UNION { ?equip a brick:VAV . BIND("HVAC VAV" AS ?type) }
  UNION { ?equip a brick:Boiler . BIND("HVAC Boiler" AS ?type) }
  UNION { ?equip a brick:Chiller . BIND("HVAC Chiller" AS ?type) }
  UNION { ?equip a brick:Fan . BIND("HVAC Fan" AS ?type) }
  UNION { ?equip a brick:Pump . BIND("HVAC Pump" AS ?type) }
  OPTIONAL { ?equip rdfs:label ?label . }
} ORDER BY ?type ?equip LIMIT 100"""
                    )
                return (
                    self._prefix_block()
                    + f"""
SELECT ?equip ?label ?location WHERE {{
  ?equip a {equip_class} .
  OPTIONAL {{ ?equip rdfs:label ?label . }}
  OPTIONAL {{ ?equip brick:hasLocation ?location . }}
}} LIMIT 50"""
                )

        # T5: Building hierarchy / location tree
        hierarchy_words = ["hierarchy", "structure", "layout", "topology", "contains", "hasPart"]
        if any(w in uq for w in hierarchy_words) or (
            "building" in uq and any(w in uq for w in ["structure", "layout", "contains"])
        ):
            return (
                self._prefix_block()
                + """
SELECT ?parent ?parentLabel ?child ?childLabel WHERE {
  { ?parent brick:hasPart ?child . }
  UNION { ?parent brick:hasLocation ?child . FILTER(?parent != ?child) }
  OPTIONAL { ?parent rdfs:label ?parentLabel . }
  OPTIONAL { ?child rdfs:label ?childLabel . }
} LIMIT 100"""
            )

        # Phase 3.1: Use expanded class map (static + OntologyIntrospector discovered)
        class_map = self._get_extended_class_map()
        uq = user_query.lower()
        target_class = None
        for k, v in class_map.items():
            if k in uq:
                target_class = v
                break
        if features["wants_count"] and target_class:
            # Roll up subclasses so "how many temperature sensors" counts every
            # Brick subclass of the target (air/water/zone/…), not just the exact type.
            return (
                self._prefix_block()
                + f"\nSELECT (COUNT(DISTINCT ?sensor) AS ?count) WHERE "
                + f"{{ ?sensor rdf:type/rdfs:subClassOf* {target_class} . }}"
            )
        if features["wants_definition"] and target_class:
            return (
                self._prefix_block()
                + f"\nSELECT ?def WHERE {{ {target_class} (rdfs:comment|skos:definition) ?def . }} LIMIT 5"
            )
        if features["wants_equipment"] and target_class:
            return (
                self._prefix_block()
                + f"\nSELECT ?sensor ?equipment ?equipLabel WHERE {{ {{ ?sensor rdf:type {target_class} . ?sensor brick:isPointOf ?equipment . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} }} UNION {{ ?sensor rdf:type {target_class} . ?equipment brick:hasPoint ?sensor . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} }} }} LIMIT 50"
            )
        if target_class:
            return (
                self._prefix_block()
                + f"\nSELECT ?sensor (SAMPLE(?location) AS ?locationName) (SAMPLE(?uuid) AS ?uuidValue) (SAMPLE(?storage) AS ?storageRef) (SAMPLE(?unit) AS ?unitName) WHERE {{\n  ?sensor rdf:type {target_class} .\n  OPTIONAL {{ ?sensor brick:hasLocation ?location . }}\n  OPTIONAL {{ ?sensor brick:hasUnit ?unit . }}\n  OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }}\n  OPTIONAL {{ ?sensor bldg:connstring ?uuid . }}\n}} GROUP BY ?sensor LIMIT {_CLASS_LISTING_LIMIT}"
            )
        # Generic sensor listing fallback
        sensor_words = ["sensor", "sensors", "point", "points"]
        if any(w in uq for w in sensor_words):
            # "what types" / "list types" → DISTINCT type + count
            type_words = ["types", "type of", "kinds", "categories", "what type", "which type"]
            if any(w in uq for w in type_words):
                return (
                    self._prefix_block()
                    + """
SELECT ?type (COUNT(?sensor) AS ?count) WHERE {
  ?sensor rdf:type ?type .
  FILTER(CONTAINS(STR(?type), 'Sensor') || CONTAINS(STR(?type), 'Point'))
} GROUP BY ?type ORDER BY DESC(?count)"""
                )
            return (
                self._prefix_block()
                + "\nSELECT ?sensor ?type ?location ?uuid ?storage ?unit WHERE {\n  ?sensor rdf:type ?type .\n  FILTER(CONTAINS(STR(?type), 'Sensor') || CONTAINS(STR(?type), 'Point'))\n  OPTIONAL { ?sensor brick:hasLocation ?location . }\n  OPTIONAL { ?sensor brick:hasUnit ?unit . }\n  OPTIONAL { ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }\n  OPTIONAL { ?sensor bldg:connstring ?uuid . }\n} LIMIT 50"
            )
        return None

    def _get_extended_class_map(self) -> dict:
        """
        Phase 3.1: Static class map merged with OntologyIntrospector-discovered sensor classes.
        Supports any building's sensor taxonomy without code changes.
        """
        static_map = {
            "air temperature": "brick:Air_Temperature_Sensor",
            # generic "temperature" → the BROAD class so counts roll up every
            # subclass (air/water/zone/…), not just Air_Temperature_Sensor.
            "temperature": "brick:Temperature_Sensor",
            # Thermal-comfort synonyms → temperature sensor
            "too warm": "brick:Air_Temperature_Sensor",
            "too hot": "brick:Air_Temperature_Sensor",
            "too cold": "brick:Air_Temperature_Sensor",
            "overheating": "brick:Air_Temperature_Sensor",
            "overheat": "brick:Air_Temperature_Sensor",
            "freezing": "brick:Air_Temperature_Sensor",
            "warm": "brick:Air_Temperature_Sensor",
            "hot": "brick:Air_Temperature_Sensor",
            "cold": "brick:Air_Temperature_Sensor",
            "thermal": "brick:Air_Temperature_Sensor",
            "humidity": "brick:Humidity_Sensor",
            "co2": "brick:CO2_Sensor",
            # Air quality synonyms
            "stuffy": "brick:CO2_Level_Sensor",
            "stale air": "brick:CO2_Level_Sensor",
            "occupancy": "brick:Occupancy_Sensor",
            "people counter": "brick:Occupancy_Sensor",
            "footfall": "brick:Occupancy_Sensor",
            "pressure": "brick:Pressure_Sensor",
            "air quality": "brick:Air_Quality_Sensor",
            "motion": "brick:Occupancy_Sensor",
            "light": "brick:Illuminance_Sensor",
            "lighting": "brick:Illuminance_Sensor",
            "lux": "brick:Illuminance_Sensor",
            "illuminance": "brick:Illuminance_Sensor",
            "voc": "brick:TVOC_Sensor",
            "tvoc": "brick:TVOC_Sensor",
            "pm2.5": "brick:PM2.5_Level_Sensor",
            "pm25": "brick:PM2.5_Level_Sensor",
            "particulate": "brick:PM2.5_Level_Sensor",
            # Modalities standardized out of input/data (energy, water, runtime).
            "energy": "brick:Energy_Sensor",
            "power": "brick:Energy_Sensor",
            "electricity": "brick:Energy_Sensor",
            "kwh": "brick:Energy_Sensor",
            "water": "brick:Water_Flow_Sensor",
            "water flow": "brick:Water_Flow_Sensor",
            "runtime": "brick:Run_Time_Sensor",
            "run time": "brick:Run_Time_Sensor",
        }
        # Custom point classes use the active building prefix (Brick 1.4 has no
        # native noise/vibration point class). Absent in other buildings → the
        # query simply returns nothing and the caller falls through gracefully.
        _pfx = _active_prefix()
        static_map["noise"] = f"{_pfx}:Noise_Level_Sensor"
        static_map["sound"] = f"{_pfx}:Noise_Level_Sensor"
        static_map["acoustic"] = f"{_pfx}:Noise_Level_Sensor"
        static_map["vibration"] = f"{_pfx}:Vibration_Sensor"
        if ontology_introspector.is_ready():
            # Phase 15A: per-request building prefix (falls back to settings).
            _bldg_pfx = _active_prefix()
            for local_name in ontology_introspector.sensor_classes:
                keyword = local_name.replace("_Sensor", "").replace("_", " ").lower()
                ns = _bldg_pfx if local_name.startswith(_bldg_pfx) else "brick"
                if keyword not in static_map:
                    static_map[keyword] = f"{ns}:{local_name}"
        return static_map

    @staticmethod
    def _infer_plant_class(uq: str) -> Optional[str]:
        """Brick class for a plant/BMS measurand, resolved from the modality config (V6-T26).

        Checked BEFORE the keyword class map because plant questions were being answered from
        whatever the vector retriever happened to rank. Measured: `_retrieve_context("is the
        supply fan running on floor 5")` returned 6,385 characters containing no fan point at
        all -- the floor-5 room sensors outranked it -- so the model concluded "there is no
        sensor that reports the running status of the supply fan on Floor 5" while
        AHU_F5_Fan_Status sat connected and readable. A confident denial of a sensor that
        exists is worse than no answer, and it is invisible from the outside.

        Deterministic on purpose. Design contract #2 puts SPARQL first and treats retrieval as
        the fallback; for a question whose class is derivable from config there is no reason to
        let similarity decide.
        """
        try:
            from orchestrator.services.deliberation.coverage_audit import (
                load_modality_raw,
            )
        except Exception:  # pragma: no cover - defensive
            return None
        try:
            raw = load_modality_raw() or {}
        except Exception:  # pragma: no cover - defensive
            return None
        best: Optional[Tuple[int, str]] = None
        for name, spec in raw.items():
            sat = (spec or {}).get("sat") or {}
            if str(sat.get("scope", "room")).lower() != "equipment":
                continue
            brick_class = str(sat.get("brick_class") or "")
            if not brick_class:
                continue
            phrase = name.replace("_", " ")
            # Longest match wins: "supply air temperature" must beat "supply air flow" on a
            # question naming both words, and "return air temperature" must not lose to a
            # shorter prefix of itself.
            if phrase in uq and (best is None or len(phrase) > best[0]):
                best = (len(phrase), brick_class)
        if best:
            return f"brick:{best[1]}"
        # Shorthands operators actually type, each tied to the modality that licenses it so a
        # building not declaring that modality never matches.
        declared = {
            n
            for n, s in raw.items()
            if str(((s or {}).get("sat") or {}).get("scope", "room")).lower() == "equipment"
        }
        shorthand = [
            ("damper", "damper_position"),
            ("filter differential", "filter_differential_pressure"),
            ("filter dp", "filter_differential_pressure"),
            ("filter pressure", "filter_differential_pressure"),
            ("supply fan", "fan_state"),
            ("fan status", "fan_state"),
            ("fan running", "fan_state"),
        ]
        for token, modality in shorthand:
            if token in uq and modality in declared:
                cls = ((raw.get(modality) or {}).get("sat") or {}).get("brick_class")
                if cls:
                    return f"brick:{cls}"
        return None

    async def _ts_bearing(self, entities: List[str]) -> Set[str]:
        """Which of these entities actually carry a timeseries reference.

        Asked of the GRAPH, not of the name. Template selection otherwise falls back to
        testing whether the local name contains "Sensor" or "Point" -- a spelling test that
        every plant point here defeats (Filter_DP, Fan_Status, Damper_Position contain
        neither), which sends them to the "what is located inside this room" template and
        returns nothing.
        """
        if not entities:
            return set()
        values = " ".join(entities)
        q = (
            f"{self._prefix_block()}\n"
            "SELECT DISTINCT ?e WHERE {\n"
            f"  VALUES ?e {{ {values} }}\n"
            "  ?e ref:hasExternalReference/ref:hasTimeseriesId ?uuid .\n"
            "}"
        )
        try:
            data = await self._execute_query(q)
            found = {
                (b.get("e") or {}).get("value") or ""
                for b in (data or {}).get("results", {}).get("bindings", [])
            }
            return {
                ent
                for ent in entities
                if any(iri.rsplit("#", 1)[-1] == ent.split(":", 1)[-1] for iri in found)
            }
        except Exception as exc:
            logger.debug(f"[sparql] ts-bearing probe failed: {exc}")
            return set()

    async def _plant_instances(self, brick_class: str, user_query: str) -> List[str]:
        """Instances of a plant class, narrowed to the equipment or floor the question names.

        Narrowing is a FILTER over instances the graph returned, never a guess: if the query
        names no equipment and no floor, every instance of the class is returned and the
        downstream template decides. Silently picking one when the question was ambiguous is
        how a building-wide question gets answered from a single AHU.

        bldg1 carries twelve AHU individuals for six physical units (BUG-249), so a floor
        filter can legitimately match two. Both are returned -- the duplication is reported,
        not resolved here.
        """
        instances = await self._get_instances_for_class(brick_class, limit=200)
        if not instances:
            return []
        uq = user_query.lower()
        # An explicit equipment id in the question is the strongest signal available.
        named = re.findall(r"\b((?:ahu|vav|fcu)[-_][\w.]+)\b", uq)
        if named:
            hits = [i for i in instances if any(n in i.lower() for n in named)]
            if hits:
                return hits
        m = re.search(r"\b(?:floor|level)\s*(\w{1,3})\b", uq)
        if m:
            token = m.group(1).lower()
            # Match the floor token at a WORD BOUNDARY inside the local name: plain substring
            # matching lets "floor 5" select AHU_Floor15 on a taller building.
            pat = re.compile(rf"(?:^|[_\-])(?:f|floor)0*{re.escape(token)}(?:$|[_\-])", re.I)
            hits = [i for i in instances if pat.search(i.rsplit(":", 1)[-1])]
            if hits:
                return hits
        return instances

    def _infer_class(self, uq: str) -> Optional[str]:
        """Phase 3.1: Uses _get_extended_class_map for class inference."""
        plant = self._infer_plant_class(uq)
        if plant:
            logger.info(f"[sparql] plant class resolved deterministically: {plant}")
            return plant
        class_map = self._get_extended_class_map()
        for k, v in class_map.items():
            if k in uq:
                return v
        return None

    async def _get_instances_for_class(self, brick_class: str, limit: int = 40) -> List[str]:
        """Query GraphDB for instances of a Brick class. Returns <prefix>: URIs only.

        Phase 15A: reads the active building's namespace/prefix from the
        request-scoped ContextVar so multi-building deployments hit the right
        ABox.  Falls back to settings when called outside a request context.
        """
        if brick_class in self._instance_cache:
            return self._instance_cache[brick_class]
        bldg_ns = _active_namespace()
        bldg_pfx = _active_prefix()
        q = f"""{self._prefix_block()}
SELECT ?s WHERE {{ ?s rdf:type {brick_class} . FILTER(STRSTARTS(STR(?s), '{bldg_ns}')) }} LIMIT {limit}"""
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                auth = (
                    (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                    if settings.GRAPHDB_USER
                    else None
                )
                resp = await client.post(
                    GRAPHDB_QUERY_ENDPOINT,
                    auth=auth,
                    data={"query": q},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                data = resp.json()
                out = []
                for b in data.get("results", {}).get("bindings", []):
                    uri = b.get("s", {}).get("value")
                    if uri and uri.startswith(bldg_ns):
                        out.append(f"{bldg_pfx}:" + uri.split("#", 1)[1])
                self._instance_cache[brick_class] = out
                return out
        except Exception as e:
            logger.warning(f"Class instance query failed for {brick_class}: {e}")
            return []

    # Words that carry no discriminating power when matching a point's name.
    _LABEL_STOPWORDS = frozenset(
        {
            "the",
            "a",
            "an",
            "of",
            "in",
            "on",
            "at",
            "for",
            "to",
            "and",
            "or",
            "is",
            "are",
            "was",
            "were",
            "current",
            "latest",
            "value",
            "reading",
            "readings",
            "data",
            "level",
            "levels",
            "what",
            "show",
            "me",
            "my",
        }
    )

    @staticmethod
    def _name_tokens(text: str) -> List[str]:
        """Split an IRI local name or phrase into comparable lowercase tokens.

        Letter and digit runs are split apart, because a building may write a
        name with no separator ("floor2"): left whole that is one opaque token,
        every floor scores identically, and a reference to one floor matches all
        of them. Single letters are dropped as noise, but single digits are kept
        — the number is the whole of what distinguishes floor 2 from floor 1.
        """
        return [
            t for t in re.findall(r"[A-Za-z]+|\d+", str(text).lower()) if len(t) > 1 or t.isdigit()
        ]

    @classmethod
    def _narrow_to_best_match(cls, candidates: List[str], user_query: str) -> List[str]:
        """Keep the candidates that best match the words of the question.

        Resolving a unit name alone ("AHU01N") returns every point on that unit,
        so a question about one measurement would fetch and average all of them.
        Ranking by how many of the question's own words appear in each point's
        name — then preferring the shortest such name — picks the measurement
        actually asked for. Abbreviated names are handled by prefix matching
        ("temperature" matches "Temp"), which is what makes this work across
        buildings that abbreviate differently.
        """
        if len(candidates) <= 1 or not user_query:
            return candidates

        q_tokens = [t for t in cls._name_tokens(user_query) if t not in cls._LABEL_STOPWORDS]
        if not q_tokens:
            return candidates

        def matches(q: str, cand_tokens: List[str]) -> bool:
            return any(
                q == c or (len(q) >= 3 and len(c) >= 3 and (q.startswith(c) or c.startswith(q)))
                for c in cand_tokens
            )

        scored = []
        for cand in candidates:
            local = cand.split(":", 1)[-1]
            toks = cls._name_tokens(local)
            hits = sum(1 for q in q_tokens if matches(q, toks))
            scored.append((hits, -len(set(toks)), cand))

        # If every candidate scores the same, the question named no measurement —
        # only the thing they all belong to ("everything about AHU01N"). There is
        # nothing to choose between them, so keep them all rather than letting the
        # name-length tie-break pick one arbitrarily.
        if len({s[0] for s in scored}) == 1:
            return candidates

        best = max(s[:2] for s in scored)
        if best[0] == 0:
            return candidates
        narrowed = [c for h, n, c in scored if (h, n) == best]
        if narrowed and len(narrowed) < len(candidates):
            logger.info(f"[sparql] narrowed {len(candidates)} candidates to {narrowed}")
        return narrowed or candidates

    async def _resolve_entities_by_label(
        self,
        names: List[str],
        limit: int = 8,
        user_query: str = "",
        ts_bearing: Optional[Set[str]] = None,
    ) -> List[str]:
        """Resolve human-readable point names to <prefix>:LocalName IRIs.

        The dialogue agent names a point the way a person would ("Supply Air Temp
        AHU01N"), but the templates need an IRI.  Matching on rdfs:label and the
        IRI's own local name keeps this portable: every building labels its
        points, and no two share a naming convention, so nothing here can encode
        one.  Points carrying a timeseries reference are preferred because those
        are the ones the SQL stage can actually read.
        """
        bldg_ns = _active_namespace()
        bldg_pfx = _active_prefix()
        resolved: List[str] = []
        ts_bearing = ts_bearing if ts_bearing is not None else set()

        for name in names:
            tokens = [
                t
                for t in re.split(r"[^A-Za-z0-9]+", str(name).lower())
                if len(t) > 1 and t not in self._LABEL_STOPWORDS
            ]
            if not tokens:
                continue
            # Escape for safe embedding in a SPARQL string literal.
            filters = " && ".join(
                'CONTAINS(?hay, "{}")'.format(t.replace("\\", "\\\\").replace('"', '\\"'))
                for t in tokens
            )
            hay = 'BIND(LCASE(CONCAT(STR(?s), " ", COALESCE(STR(?l), ""))) AS ?hay)'
            # Timeseries-bearing points first, then any typed entity.
            queries = [
                f"""{self._prefix_block()}
SELECT DISTINCT ?s WHERE {{
  ?s ref:hasExternalReference ?r .
  OPTIONAL {{ ?s rdfs:label ?l }}
  {hay}
  FILTER(STRSTARTS(STR(?s), '{bldg_ns}'))
  FILTER({filters})
}} LIMIT {limit}""",
                f"""{self._prefix_block()}
SELECT DISTINCT ?s WHERE {{
  ?s rdf:type ?t .
  OPTIONAL {{ ?s rdfs:label ?l }}
  {hay}
  FILTER(STRSTARTS(STR(?s), '{bldg_ns}'))
  FILTER({filters})
}} LIMIT {limit}""",
            ]
            for i, q in enumerate(queries):
                hits = await self._select_subjects(q, bldg_ns, bldg_pfx)
                if hits:
                    hits = self._narrow_to_best_match(hits, user_query)
                    resolved.extend(h for h in hits if h not in resolved)
                    if i == 0:
                        # Query 0 required a timeseries reference, so these are
                        # points the SQL stage can read — regardless of how this
                        # building spells their names.
                        ts_bearing.update(hits)
                    break

        if resolved:
            logger.info(f"[sparql] resolved {names} → {resolved[:limit]} via rdfs:label/IRI match")
        return resolved[:limit]

    async def _filter_existing(self, entities: List[str]) -> List[str]:
        """Return only the entities the active building's graph actually contains.

        An entity is present if it appears as a subject or an object — a room
        may be described only by what points at it.
        """
        safe = [e for e in entities if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:[A-Za-z0-9_.\-]+$", e)]
        if not safe:
            return []
        values = " ".join(safe)
        q = f"""{self._prefix_block()}
SELECT DISTINCT ?e WHERE {{
  VALUES ?e {{ {values} }}
  {{ ?e ?p ?o }} UNION {{ ?s ?p2 ?e }}
}}"""
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                auth = (
                    (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                    if settings.GRAPHDB_USER
                    else None
                )
                resp = await client.post(
                    GRAPHDB_QUERY_ENDPOINT,
                    auth=auth,
                    data={"query": q},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                found = {
                    b.get("e", {}).get("value")
                    for b in resp.json().get("results", {}).get("bindings", [])
                }
        except Exception as e:
            # A validation outage must not drop entities that may well be real.
            logger.warning(f"[sparql] entity existence check failed, keeping candidates: {e}")
            return entities

        ns = _active_namespace()
        return [e for e in safe if f"{ns}{e.split(':', 1)[1]}" in found]

    async def _select_subjects(self, query: str, bldg_ns: str, bldg_pfx: str) -> List[str]:
        """Run a SELECT ?s query and return <prefix>:LocalName forms."""
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                auth = (
                    (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                    if settings.GRAPHDB_USER
                    else None
                )
                resp = await client.post(
                    GRAPHDB_QUERY_ENDPOINT,
                    auth=auth,
                    data={"query": query},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                out = []
                for b in resp.json().get("results", {}).get("bindings", []):
                    uri = b.get("s", {}).get("value")
                    if uri and uri.startswith(bldg_ns) and "#" in uri:
                        out.append(f"{bldg_pfx}:" + uri.split("#", 1)[1])
                return out
        except Exception as e:
            logger.warning(f"[sparql] label resolution query failed: {e}")
            return []

    async def _pattern_instance_search(self, brick_class: str, limit: int = 40) -> List[str]:
        """Fallback: search for URIs containing core type token (e.g., Humidity_Sensor) when rdf:type lookup empty."""
        token = None
        m = re.search(r"brick:([A-Za-z0-9_]+)", brick_class)
        if m:
            token = (
                m.group(1)
                .replace("Air_Temperature", "Air_Temperature")
                .replace("Humidity", "Humidity")
                .replace("CO2", "CO2")
                .replace("Pressure", "Pressure")
                .replace("Occupancy", "Occupancy")
            )
        if not token:
            return []
        # Phase 15A — per-request building context.
        bldg_ns = _active_namespace()
        bldg_pfx = _active_prefix()
        # Use regex on URI string via FILTER(CONTAINS())
        q = f"""{self._prefix_block()}
SELECT ?s WHERE {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s),'{bldg_ns}') && CONTAINS(STR(?s), '{token}_Sensor')) }} LIMIT {limit}"""
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                auth = (
                    (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                    if settings.GRAPHDB_USER
                    else None
                )
                resp = await client.post(
                    GRAPHDB_QUERY_ENDPOINT,
                    auth=auth,
                    data={"query": q},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                data = resp.json()
                out = []
                for b in data.get("results", {}).get("bindings", []):
                    uri = b.get("s", {}).get("value")
                    if uri and uri.startswith(bldg_ns):
                        out.append(f"{bldg_pfx}:" + uri.split("#", 1)[1])
                return out
        except Exception as e:
            logger.warning(f"Pattern instance search failed for token {token}: {e}")
            return []

    @staticmethod
    def _mentions(uq: str, words: List[str]) -> bool:
        """True when any term appears as a whole word.

        Substring matching silently misreads ordinary questions: "id" hides
        inside "humidity", "meter" inside "parameter", and "ahu" inside an
        identifier like "AHU01N" — so asking for a reading from a named unit
        was classified as a question about equipment and answered with
        relationships instead of the sensor's timeseries. Whole-word matching
        also keeps this portable, since it stops a building's own naming
        convention from tripping these keywords.
        """
        for w in words:
            pattern = SPARQLAgent._WORD_RE_CACHE.get(w)
            if pattern is None:
                pattern = re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE)
                SPARQLAgent._WORD_RE_CACHE[w] = pattern
            if pattern.search(uq):
                return True
        return False

    _WORD_RE_CACHE: Dict[str, Any] = {}

    def _classify_query(self, uq: str) -> Dict[str, bool]:
        m = self._mentions
        return {
            "wants_label": m(uq, ["label", "name", "called"]),
            "wants_uuid": m(uq, ["uuid", "id", "identifier"]),
            "wants_location": m(uq, ["location", "located"])
            or "where is" in uq
            or "where are" in uq,
            "wants_count": m(uq, ["how many", "count", "number of"]),
            "wants_equipment": m(
                uq,
                [
                    "equipment",
                    "device",
                    "vav",
                    "ahu",
                    "hvac",
                    "air handler",
                    "air handling",
                    "fan coil",
                    "pump",
                    "boiler",
                    "chiller",
                    "meter",
                    "damper",
                    "actuator",
                ],
            ),
            "wants_definition": m(uq, ["definition", "describe", "meaning"]),
        }

    def _ensure_prefixes(self, sparql: str) -> str:
        """Ensure the full extended prefix block is present (idempotent)."""
        if not isinstance(sparql, str):
            return sparql

        # Remove any existing PREFIX lines to avoid duplicates
        lines = sparql.split("\n")
        clean_lines = [line for line in lines if not line.strip().lower().startswith("prefix ")]
        clean_sparql = "\n".join(clean_lines).strip()

        return self._prefix_block() + "\n" + clean_sparql

    def _prefix_block(self, building_id: Optional[str] = None) -> str:
        """Return the SPARQL prefix block for the given building.

        Phase 10E — when `building_id` is provided, the building prefix
        line comes from that building's BuildingContext (read from
        input/<bid>/building.yaml).  When None, falls back to the
        process-global EXTENDED_PREFIXES (active settings building).
        """
        if building_id:
            try:
                from orchestrator.services.building_context import (
                    resolve_building_context,
                )

                bctx = resolve_building_context(building_id)
                custom = _STANDARD_PREFIXES + [f"PREFIX {bctx.prefix}: <{bctx.namespace}>"]
                return "\n".join(custom)
            except Exception as e:
                logger.debug(f"[sparql] per-building prefix lookup failed for {building_id}: {e}")
        return "\n".join(EXTENDED_PREFIXES)

    def _extract_entities(self, user_query: str) -> List[str]:
        """Extract explicit bldg: entities or construct them from natural language patterns."""
        entities = []
        # Direct bldg: references
        for token in re.findall(r"bldg:[A-Za-z0-9_\.]+", user_query):
            entities.append(token)

        # Zone/Room/Space number pattern: "zone 5.01", "zone 5", "room 5.03"
        zone_pattern = re.findall(
            r"\b(?:zone|room|space)\s+(\d+(?:\.\d+)?)\b", user_query, re.IGNORECASE
        )
        for num in zone_pattern:
            entities.append(f"bldg:Zone_{num}")

        # Sensor type + node number patterns: "Air Quality Level Sensor 5.01", "Air Temperature Sensor 5.01"
        sensor_type_map = [
            (r"air quality level sensor[s]?\s+(\d+\.\d+|\d+)", "Air_Quality_Level_Sensor"),
            (r"air quality sensor[s]?\s+(\d+\.\d+|\d+)", "Air_Quality_Level_Sensor"),
            (r"air temperature sensor[s]?\s+(\d+\.\d+|\d+)", "Air_Temperature_Sensor"),
            (r"temperature sensor[s]?\s+(\d+\.\d+|\d+)", "Air_Temperature_Sensor"),
            (r"humidity sensor[s]?\s+(\d+\.\d+|\d+)", "Zone_Air_Humidity_Sensor"),
            (r"zone air humidity sensor[s]?\s+(\d+\.\d+|\d+)", "Zone_Air_Humidity_Sensor"),
            (r"co2 sensor[s]?\s+(\d+\.\d+|\d+)", "CO2_Level_Sensor"),
            (r"co2 level sensor[s]?\s+(\d+\.\d+|\d+)", "CO2_Level_Sensor"),
            (r"co\s+level sensor[s]?\s+(\d+\.\d+|\d+)", "CO_Level_Sensor"),
            (r"tvoc sensor[s]?\s+(\d+\.\d+|\d+)", "TVOC_Level_Sensor"),
            (r"formaldehyde sensor[s]?\s+(\d+\.\d+|\d+)", "Formaldehyde_Level_Sensor"),
            (r"illuminance sensor[s]?\s+(\d+\.\d+|\d+)", "Illuminance_Sensor"),
            (r"sound sensor[s]?\s+(\d+\.\d+|\d+)", "Sound_Noise_Sensor_MEMS"),
            (r"noise sensor[s]?\s+(\d+\.\d+|\d+)", "Sound_Noise_Sensor_MEMS"),
        ]
        for pattern, sensor_type in sensor_type_map:
            for num in re.findall(pattern, user_query, re.IGNORECASE):
                entities.append(f"bldg:{sensor_type}_{num}")

        # Legacy: (Zone|Room|Space|Air)? (Air Temperature|Humidity|CO2|etc) Sensor NUM
        sensor_pattern = re.findall(
            r"(Zone|Room|Space|Air)?\s*(Air Temperature|Temperature|Air Humidity|Humidity|CO2|Pressure|Occupancy) Sensor\s*(\d+\.\d+|\d+)",
            user_query,
            re.IGNORECASE,
        )
        for prefix, stype, num in sensor_pattern:
            stype_norm = stype.lower().strip()
            mapping = {
                "air temperature": "Air_Temperature_Sensor",
                "temperature": "Air_Temperature_Sensor",
                "air humidity": "Zone_Air_Humidity_Sensor",
                "humidity": "Zone_Air_Humidity_Sensor",
                "co2": "CO2_Level_Sensor",
                "pressure": "Pressure_Sensor",
                "occupancy": "Occupancy_Sensor",
            }
            base_type = mapping.get(stype_norm, stype_norm.title().replace(" ", "_") + "_Sensor")
            entities.append(f"bldg:{base_type}_{num}")

        # Underscore-format sensor names: Air_Temperature_Sensor_5.28, CO2_Level_Sensor_5.08, etc.
        # These appear when users copy-paste sensor IDs from the UI without spaces
        underscore_sensor_pat = re.compile(
            r"\b([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)*_Sensor_\d+(?:\.\d+)?)\b"
        )
        for match in underscore_sensor_pat.finditer(user_query):
            cand = f"bldg:{match.group(1)}"
            if cand not in entities:
                entities.append(cand)

        return list(dict.fromkeys(entities))  # dedupe preserving order

    def _infer_class_from_entity(self, entity: str) -> Optional[str]:
        """Derive Brick class from an instance local name pattern."""
        if not entity.startswith("bldg:"):
            return None
        local = entity.split(":", 1)[1]  # Zone_Air_Humidity_Sensor_5.01
        # Strip Zone_ prefix
        if local.startswith("Zone_"):
            local = local[5:]
        # Match core type before _Sensor_
        m = re.match(r"([A-Za-z_]+)_Sensor_", local)
        if not m:
            return None
        core = m.group(1)
        mapping = {
            "Air_Temperature": "brick:Air_Temperature_Sensor",
            "Air_Humidity": "brick:Humidity_Sensor",
            "CO2": "brick:CO2_Sensor",
            "Pressure": "brick:Pressure_Sensor",
            "Occupancy": "brick:Occupancy_Sensor",
        }
        return mapping.get(core)

    def _postprocess_query(self, sparql: Optional[str]) -> Optional[str]:
        """Apply legacy fixes: sensor name spacing and instance prefix corrections."""
        if not sparql or not isinstance(sparql, str):
            return sparql
        fixed = re.sub(r"(\w+_Sensor)\s+(\d+\.?\d*)", r"\1_\2", sparql)
        # brick:Some_Sensor_x => bldg:Some_Sensor_x for instance lookups
        fixed = re.sub(r"brick:([A-Za-z0-9_]+_Sensor_\d+(?:\.\d+)?)", r"bldg:\1", fixed)
        if fixed != sparql:
            logger.info("Applied SPARQL postprocessing corrections")
        return fixed

    def _standardize_results(
        self, results: Dict[str, Any], question: str, sparql_query: str
    ) -> Dict[str, Any]:
        """Produce standardized JSON similar to legacy Rasa action for downstream summarization."""
        standardized = {"question": question, "query": sparql_query, "results": []}
        try:
            bindings = (
                results.get("results", {}).get("bindings", []) if isinstance(results, dict) else []
            )
            for b in bindings:
                entry = {}
                for var, val in b.items():
                    value = val.get("value")
                    vtype = val.get("type")
                    if vtype == "uri":
                        # Compact known namespaces
                        for ns, pref in (
                            ("https://brickschema.org/schema/Brick#", "brick:"),
                            # Phase 15A: per-request building namespace.
                            (_active_namespace(), f"{_active_prefix()}:"),
                            ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
                            ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
                            ("http://www.w3.org/2002/07/owl#", "owl:"),
                            ("https://brickschema.org/schema/Brick/ref#", "ref:"),
                            ("https://w3id.org/rec#", "rec:"),
                            ("http://www.w3.org/ns/sosa/", "sosa:"),
                        ):
                            if value.startswith(ns):
                                value = pref + value[len(ns) :]
                                break
                    entry[var] = value
                standardized["results"].append(entry)
        except Exception as e:
            standardized["error"] = f"standardization_failed: {e}"

    async def _execute_query(self, sparql: str) -> Dict[str, Any]:
        """Execute SPARQL query against GraphDB (with Fuseki fallback)"""
        # Phase 4.2: Enforce LIMIT safety cap on SELECT queries
        from orchestrator.services.sparql_validator import sparql_validator

        sparql = sparql_validator.enforce_limit(sparql)

        # Check cache
        query_hash = generate_hash(sparql)
        cache_key = f"cache:sparql_exec:{query_hash}"
        cached_result = await redis_manager.get_cache(cache_key)

        if cached_result:
            logger.info(f"✅ Cache hit for SPARQL execution: {query_hash}")
            return cached_result

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try GraphDB first
                try:
                    logger.info(f"🔍 Executing SPARQL on GraphDB: {GRAPHDB_QUERY_ENDPOINT}")

                    # GraphDB uses basic auth
                    auth = (
                        (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                        if settings.GRAPHDB_USER
                        else None
                    )

                    response = await client.post(
                        GRAPHDB_QUERY_ENDPOINT,
                        auth=auth,
                        data={"query": sparql},
                        headers={"Accept": "application/sparql-results+json"},
                    )
                    response.raise_for_status()

                    results = response.json()
                    result_count = len(results.get("results", {}).get("bindings", []))
                    logger.info(f"✅ GraphDB query returned {result_count} results")

                    # If zero results, try fallback pattern search
                    if result_count == 0:
                        logger.info("Zero results from GraphDB, attempting pattern-based fallback")
                        fallback_results = await self._fallback_pattern_search(sparql, client, auth)
                        if fallback_results:
                            await redis_manager.set_cache(cache_key, fallback_results, ttl=3600)
                            return fallback_results

                    await redis_manager.set_cache(cache_key, results, ttl=3600)
                    return results

                except Exception as e:
                    logger.warning(f"GraphDB query failed: {e}, trying Fuseki fallback")

                    # Fallback to Fuseki if GraphDB fails
                    response = await client.post(
                        FUSEKI_QUERY_ENDPOINT,
                        data={"query": sparql},
                        headers={"Accept": "application/sparql-results+json"},
                    )
                    response.raise_for_status()

                    results = response.json()
                    logger.info(
                        f"Fuseki fallback returned {len(results.get('results', {}).get('bindings', []))} results"
                    )

                    # Fallback pattern search for Fuseki too
                    if len(results.get("results", {}).get("bindings", [])) == 0:
                        fallback_results = await self._fallback_pattern_search(sparql, client, None)
                        if fallback_results:
                            await redis_manager.set_cache(cache_key, fallback_results, ttl=3600)
                            return fallback_results

                    await redis_manager.set_cache(cache_key, results, ttl=3600)
                    return results

        except httpx.HTTPError as e:
            logger.error(f"SPARQL query error: {e}")
            raise Exception(f"Failed to execute SPARQL query: {str(e)}")

    async def _fallback_pattern_search(
        self, sparql: str, client: httpx.AsyncClient, auth: Optional[tuple] = None
    ) -> Optional[Dict[str, Any]]:
        """Fallback pattern-based search when class-based query returns zero results.

        Preserves an explicit location constraint from the original query. If the user
        named a specific zone/room id (e.g. "5.28"), the fallback must keep it — dropping
        it and returning class-matching sensors from anywhere causes another zone's data
        to be attributed to the requested one. Location-free class queries ("show
        temperature sensors") keep the broad building-wide behavior.
        """
        # Extract class from query
        m = re.search(r"rdf:type\s+(brick:[A-Za-z0-9_]+_Sensor)", sparql)
        if not m:
            m = re.search(r"rdf:type\s+(brick:[A-Za-z0-9_]+)", sparql)
        if not m:
            return None

        brick_class = m.group(1)
        token = brick_class.split(":", 1)[1].replace("_Sensor", "")

        # Preserve an explicit dotted location id (digits + '.' only — injection-safe).
        loc_m = re.search(r"\d{1,2}\.\d{1,2}", sparql)
        loc_filter = f" && CONTAINS(STR(?sensor), '{loc_m.group(0)}')" if loc_m else ""

        # Pattern-based query (Phase 15A: per-request building namespace).
        alt_query = (
            self._prefix_block()
            + f"""
SELECT ?sensor ?location ?uuid WHERE {{
    ?sensor ?p ?o .
    FILTER(STRSTARTS(STR(?sensor), '{_active_namespace()}') && CONTAINS(STR(?sensor), '{token}_Sensor'){loc_filter})
    OPTIONAL {{ ?sensor brick:hasLocation ?location . }}
    OPTIONAL {{ ?sensor bldg:connstring ?uuid . }}
}} LIMIT 50"""
        )

        logger.info(
            f"Attempting pattern fallback for token: {token}"
            + (f" (location-constrained: {loc_m.group(0)})" if loc_m else "")
        )

        try:
            # Try current endpoint (GraphDB)
            endpoint = GRAPHDB_QUERY_ENDPOINT
            response = await client.post(
                endpoint,
                auth=auth,
                data={"query": alt_query},
                headers={"Accept": "application/sparql-results+json"},
            )

            if response.status_code == 200:
                data = response.json()
                count = len(data.get("results", {}).get("bindings", []))
                if count > 0:
                    logger.info(f"✅ Pattern fallback succeeded: {count} results")
                    return data
        except Exception as e:
            logger.warning(f"Pattern fallback failed: {e}")

        return None

    async def _format_results(
        self, results: Dict[str, Any], user_query: str, sparql_query: str, used_template: bool
    ) -> str:
        """Format SPARQL results into natural language"""

        bindings = results.get("results", {}).get("bindings", [])
        # Deduplicate rows based on concatenated variable values
        seen = set()
        deduped = []
        for b in bindings:
            sig = tuple(sorted((var, val.get("value")) for var, val in b.items()))
            if sig not in seen:
                seen.add(sig)
                deduped.append(b)
        bindings = deduped

        if not bindings:
            return "No results found for your query."

        # Special formatting for label+definition queries
        uq = user_query.lower()
        if ("label" in uq and "definition" in uq) or ("#" in user_query):
            # Format as: "Label: X, Definition: Y"
            if len(bindings) == 1:
                b = bindings[0]
                label = b.get("label", {}).get("value", "N/A")
                definition = b.get("definition", {}).get("value") or b.get("def", {}).get(
                    "value", "N/A"
                )
                return f"**{label}**\n\nDefinition: {definition}"
            else:
                result_text = f"Found {len(bindings)} result(s):\n\n"
                for i, b in enumerate(bindings[:10], 1):
                    label = b.get("label", {}).get("value", "N/A")
                    definition = b.get("definition", {}).get("value") or b.get("def", {}).get(
                        "value", "N/A"
                    )
                    result_text += f"{i}. **{label}**: {definition}\n\n"
                return result_text

        # Special formatting for building name query
        if "building" in uq and "name" in uq:
            if bindings:
                b = bindings[0]
                label = b.get("label", {}).get("value", "Unknown Building")
                comment = b.get("comment", {}).get("value", "")
                if comment:
                    return f"The building name is: **{label}**\n\n{comment}"
                return f"The building name is: **{label}**"

        # Convert results to readable format
        result_text = f"Found {len(bindings)} result(s):\n\n"

        # Check if user wants all results
        user_query_lower = user_query.lower()
        show_all = any(
            k in user_query_lower for k in ["all", "complete", "full", "everything", "list"]
        )

        # Set limit based on user intent (default 10, but higher if "all" requested)
        # Cap at 100 to prevent context window overflow
        limit = 100 if show_all else 10

        for i, binding in enumerate(bindings[:limit], 1):
            result_text += f"{i}. "
            for var, value in binding.items():
                result_text += f"{var}: {value.get('value', 'N/A')} | "
            result_text = result_text.rstrip(" | ") + "\n"

        if len(bindings) > limit:
            result_text += f"\n... and {len(bindings) - limit} more results (truncated for brevity)"

        # Generate human-readable natural language response
        summary_prompt = f"""You are a helpful building management assistant. Convert these SPARQL query results into a clear, natural language response for the user.

=== USER QUESTION ===
{user_query}

=== QUERY RESULTS ===
{result_text}

=== YOUR TASK ===
Create a human-readable response that:

1. **Directly answers the user's question** in natural language
2. **Presents information clearly** - extract sensor names from URIs (e.g., "Air_Temperature_Sensor_5.01" instead of full URI)
3. **Groups related information** - organize by location/zone if applicable
4. **Uses formatting** for readability:
   - Use bullet points (•) or numbered lists
   - Group sensors by location/zone when relevant
   - Highlight key information
5. **Provides context** - mention total count and any patterns
6. **Keep it concise** - summarize if more than 50 results if user did not asked for all details explicitly

=== OUTPUT FORMAT EXAMPLES ===

Example 1 (Sensor List):
"I found 34 temperature sensors in the building. Here are the sensors organized by zone:

**West Zone:**
• Air_Temperature_Sensor_5.01
• Air_Temperature_Sensor_5.02
• Air_Temperature_Sensor_5.10
• Air_Temperature_Sensor_5.15
• Air_Temperature_Sensor_5.16

**North Zone:**
• Air_Temperature_Sensor_5.06
• Air_Temperature_Sensor_5.07
• Air_Temperature_Sensor_5.12
... (and 26 more sensors across other zones)

Would you like to see the complete list or get data from specific sensors?"

Example 2 (Location Query):
"The CO2 sensor in room 5.06 is located in the **North-East Zone**. Its UUID for data retrieval is: 791284f8-..."

Example 3 (Equipment List):
"There are 5 Air Handling Units (AHUs) on the first floor:
1. AHU_01 - Serves West Zone
2. AHU_02 - Serves East Zone
..."

=== IMPORTANT ===
- Extract readable names from URIs (show only the local name after the last '#' or '/', never the full building-namespace URI)
- Be conversational and helpful
- Don't show raw URIs unless specifically asked
- If results contain UUIDs, mention they're available for data queries

Generate your response now:"""

        if used_template:
            # For template queries, always use LLM formatting for better UX
            try:
                summary = await llm_manager.generate(summary_prompt, task_type=TaskType.GENERAL)
                return summary.strip()
            except Exception as e:
                logger.warning(f"LLM formatting failed, using structured fallback: {e}")
                # Fallback: Clean up URIs in the result text
                return self._clean_uri_output(result_text)

        try:
            summary = await llm_manager.generate(summary_prompt, task_type=TaskType.GENERAL)
            return summary.strip()
        except Exception as e:
            logger.warning(f"LLM summarization failed, fallback to cleaned output: {e}")
            return self._clean_uri_output(result_text)

    def _should_require_analytics(self, user_query: str, entities: List[str]) -> bool:
        """
        Determine if query requires analytics/time-series data processing

        Args:
            user_query: User's natural language query
            entities: Extracted entities

        Returns:
            True if analytics needed, False if ontology metadata sufficient
        """
        query_lower = user_query.lower()

        # **PRIORITY 1: Metadata-only patterns** (check FIRST!)
        # These are static ontology properties - NEVER require analytics
        metadata_patterns = [
            "what is the label",
            "what is the uuid",
            "what is the id",
            "what is the type",
            "what is the location",
            "where is",
            "what is the definition",
            "what is the description",
            "list all",
            "show all",
            "how many",
            "count of sensors",
            "which equipment",
            "what type",
            "explain",
            "describe",
            "in ontology",
            "in the ontology",
            "from ontology",
            "hasLocation",
            "isPointOf",
            "feeds",
            "hasPart",
            "what sensors",
            "which sensors",
            "list sensors",
        ]

        for pattern in metadata_patterns:
            if pattern in query_lower:
                return False  # Metadata query - NO analytics needed

        # **PRIORITY 2: Analytics/Time-series patterns**
        # These require sensor DATA (readings, values, trends)
        analytics_patterns = [
            "current temperature",
            "current reading",
            "current value",
            "average temperature",
            "min temperature",
            "max temperature",
            "temperature reading",
            "co2 reading",
            "humidity reading",
            "air quality reading",
            "humidity reading",
            "sound reading",
            "above",
            "below",
            "higher than",
            "lower than",
            "trend",
            "history",
            "yesterday",
            "last week",
            "last hour",
            "last month",
            "graph",
            "chart",
            "plot",
            "visualize",
            "visualise",
            "show me the data",
            "get readings",
            "fetch values",
            # Time-relative queries
            "last reading",
            "latest reading",
            "last value",
            "latest value",
            "recent reading",
            "recent data",
            "last data",
            "latest data",
            "last measurement",
            "most recent",
            # Generic "reading" / "value" when asking for data
            "give me reading",
            "get reading",
            "show reading",
            "sensor data",
            "sensor value",
            "sensor reading",
            "data for zone",
            "data for room",
            "data from zone",
            "readings for zone",
            "readings from zone",
            "values for zone",
            "readings in zone",
            "average in zone",
            "average for zone",
            "max in zone",
            "min in zone",
            "temperature in zone",
            # Aggregation patterns
            "average",
            "minimum",
            "maximum",
            "distribution",
            "compare",
            "highest",
            "lowest",
            "peak",
            "anomaly",
            "anomalies",
        ]

        for pattern in analytics_patterns:
            if pattern in query_lower:
                return True  # Analytics query - need time-series data

        # **PRIORITY 3: Ambiguous cases** - Conservative default
        # If no clear pattern, assume metadata (safer default)
        return False

    def _clean_uri_output(self, result_text: str) -> str:
        """
        Clean up raw SPARQL results by removing URI prefixes for better readability

        Args:
            result_text: Raw formatted results with full URIs

        Returns:
            Cleaned text with shortened entity names
        """
        import re

        # Remove common URI prefixes
        cleaned = result_text

        # Replace full URIs with just the local name.  Phase 15A: read the
        # building namespace from the request-scoped ContextVar so each
        # tenant's URIs are stripped against ITS namespace, not the global one.
        _bldg_ns_escaped = re.escape(_active_namespace())
        uri_patterns = [
            (_bldg_ns_escaped, ""),
            (r"https://brickschema\.org/schema/Brick#", "brick:"),
            (r"http://www\.w3\.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
            (r"http://www\.w3\.org/2000/01/rdf-schema#", "rdfs:"),
        ]

        for pattern, replacement in uri_patterns:
            cleaned = re.sub(pattern, replacement, cleaned)

        return cleaned
