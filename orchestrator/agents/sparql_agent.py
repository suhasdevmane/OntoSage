"""
SPARQL Agent - Ontology query generation with RAG
"""

import sys

sys.path.append("/app")

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
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


# ── SCHEMA DOCUMENTATION IS NOT AN ANSWER ────────────────────────────────────
#
# Run-3 rows 139 and 146 (2026-09-17) handed readers the `rdfs:comment` and
# `skos:example` that OntoSage's own TBox carries on its record classes. A person asking
# about a barometric meter was shown: "The three stream columns are separate deliberately
# -- a point recorded as general waste, labelled mixed recycling and fitted with a narrow
# slot is one people will use wrongly, and collapsing them into a single stream field
# makes that disagreement unrepresentable when the disagreement IS the answer."
#
# That paragraph is a DESIGN NOTE. It explains to a developer why a register is modelled
# with three columns; it says nothing about the building, and a reader cannot act on it.
# The same fields on Brick classes are genuine definitions and stay eligible — only the
# annotations OntoSage wrote about its own data model are withheld, which is why the set
# is built from the subjects in the `ontosage:` namespace inside `ontology/` rather than
# from a word list.
#
# Withheld at the point the results become answer CONTENT, not from the prose afterwards
# and not from retrieval: a design note is still a legitimate signal for choosing a query.
_SCHEMA_DOC_PREDICATES = ("rdfs:comment", "skos:example", "skos:definition")
_ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "ontology"
_TTL_LITERAL_RE = re.compile(r"(?:" + "|".join(_SCHEMA_DOC_PREDICATES) + r')\s+"((?:[^"\\]|\\.)*)"')
_TTL_SUBJECT_RE = re.compile(r"^\s*(?:ontosage|o):([\w.\-]+)", re.M)


def _normalise_prose(text: str) -> str:
    """Whitespace-insensitive form, so a re-wrapped literal still matches itself."""
    return " ".join(str(text or "").split())


@lru_cache(maxsize=1)
def schema_documentation_literals() -> frozenset:
    """Every annotation OntoSage's own TBox carries, normalised for comparison.

    Empty when `ontology/` is missing — nothing is withheld, which is the same failure
    mode as an unreachable graph and never removes a real answer.
    """
    out = set()
    if not _ONTOLOGY_DIR.is_dir():
        return frozenset()
    for path in sorted(_ONTOLOGY_DIR.glob("*.ttl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - unreadable file
            continue
        body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        for stmt in re.split(r'(?<=[\s>"])\.\s*(?:\n|$)', body):
            if not _TTL_SUBJECT_RE.search(stmt):
                continue
            for raw in _TTL_LITERAL_RE.findall(stmt):
                literal = raw.replace("\\n", " ").replace('\\"', '"').replace("\\\\", "\\")
                normalised = _normalise_prose(literal)
                if len(normalised) >= 40:  # a one-word label is not a design note
                    out.add(normalised)
    return frozenset(out)


def redact_schema_documentation(bindings: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Drop binding cells whose value IS one of the TBox's own design notes.

    Returns the surviving bindings and how many cells were withheld. A row left with
    nothing goes too — an empty row in a result list reads as a record that exists and
    has no content, which is a different and equally false statement.
    """
    known = schema_documentation_literals()
    if not known:
        return bindings, 0
    kept: List[Dict[str, Any]] = []
    withheld = 0
    for b in bindings:
        row = {}
        for var, cell in b.items():
            value = (cell or {}).get("value") if isinstance(cell, dict) else None
            if isinstance(value, str) and _normalise_prose(value) in known:
                withheld += 1
                continue
            row[var] = cell
        if row:
            kept.append(row)
    return kept, withheld


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
    # THE OCBV LAYER. Missing until 2026-08-26, which made every ontosage:/hbco:
    # term a SYNTAX ERROR in any query this agent generated — so the whole
    # conversational vocabulary (amenities, knowledge topics, lifts, AV, network,
    # asset status, service schedules, the parking sensor class) was unreachable
    # from the SPARQL lane. It surfaced when a specificity check silently fell back
    # to its exception path: the query was correct and simply could not parse.
    "PREFIX ontosage: <http://ontosage.org/capabilities#>",
    "PREFIX hbco: <http://ontosage.org/hbco#>",
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

#: Words that say WHAT KIND of place an identifier names, not which one (WB-10).
_LOCATION_HEAD_WORDS = frozenset({"room", "rooms", "zone", "zones", "space", "node", "area", "rm"})

#: A question that compares FLOORS without naming one (BUG-556).
_ACROSS_FLOORS_RE = re.compile(
    r"\b(?:which|what)\s+(?:\w+\s+)?(?:floor|level)s?\b"
    r"|\b(?:each|every|per|by)\s+(?:floor|level)\b"
    r"|\b(?:all|across|between)\s+(?:the\s+)?(?:floors|levels)\b"
    r"|\bfloor[- ]by[- ]floor\b",
    re.IGNORECASE,
)

#: Brick classes that measure PLANT air or water, never a room (WB-14). A ROOM question on a
#: floor excludes them, so an AHU's supply air is not averaged into the floor's temperature.
#: A question that NAMES one of them is the opposite case and must get exactly that class
#: (BUG-667) -- see `_plant_quantity_class`.
_PLANT_SIDE_CLASSES: Tuple[str, ...] = (
    "brick:Supply_Air_Temperature_Sensor",
    "brick:Return_Air_Temperature_Sensor",
    "brick:Mixed_Air_Temperature_Sensor",
    "brick:Discharge_Air_Temperature_Sensor",
    "brick:Outside_Air_Temperature_Sensor",
    "brick:Leaving_Water_Temperature_Sensor",
    "brick:Entering_Water_Temperature_Sensor",
    "brick:Supply_Air_Humidity_Sensor",
    "brick:Return_Air_Humidity_Sensor",
    "brick:Outside_Air_Humidity_Sensor",
)

#: Intents whose question asks for a READING, a count of readings or a value (CAVEAT-654).
#: Taken from `orchestrator/intents/intent_definitions.yaml` (`pipeline_group: data`), minus
#: the ones whose answer is legitimately prose about the building rather than a figure:
#: `metadata` and `discovery` (open "what is there" questions) and `recommend` (advice).
_DATA_READING_INTENTS = frozenset(
    {
        "sensor_data",
        "analytics",
        "compare",
        "trend",
        "anomaly",
        "report",
        "export",
        "compliance",
        "visualization",
    }
)


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
8. The data above comes from the building's own records, not from the user — never call it data the user "provided" or "supplied"; call it the building's records

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

    @staticmethod
    def _humanise_class(brick_class: str) -> str:
        """'brick:Supply_Air_Temperature_Sensor' -> 'supply air temperature'; CO2 stays CO2."""
        local = brick_class.split(":", 1)[-1]
        local = re.sub(r"_(Sensor|Command|Status|Setpoint)$", "", local) or local
        words = []
        for word in local.split("_"):
            keep = any(ch.isdigit() for ch in word) or (word.isupper() and len(word) > 1)
            words.append(word if keep else word.lower())
        return " ".join(w for w in words if w)

    def _typed_absence(
        self,
        state: ConversationState,
        user_query: str,
        sparql_query: Optional[str],
        results: Any,
        used_floor_scope: bool,
        class_target: Optional[str],
        class_targets: Optional[List[str]],
        concept_populated: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """A typed NOT_DECLARED outcome for an empty data-reading lookup, or None (CAVEAT-654).

        None means "this emptiness proves nothing", and the caller keeps its old path. The
        conditions, all required, are argued at the call site: a data-reading intent, the
        deterministic floor-scoped resolver selecting by CLASS, and a query that RAN (a result
        envelope with an empty bindings list, not a failure's empty dict).

        The shape is the one the referent and sensor-type gates already hand the response
        node — success, no analytics, a formatted_response — so no new reader is needed to
        narrate it. `results` stays the real, empty SPARQL envelope, so the verifier's
        `_bindings` reads [] and records it as ungrounded rather than crashing (BUG-643).
        The wording is retrieval_outcome's ONE authorised sentence for the state; its remedy
        ("add the sensor to the ontology") is carried separately and NOT put in front of the
        user, because remediation is for administrators.
        """
        intent = str((state.intermediate_results or {}).get("intent") or "")
        if intent not in _DATA_READING_INTENTS or not used_floor_scope:
            return None
        inner = results.get("results") if isinstance(results, dict) else None
        if not isinstance(inner, dict) or not isinstance(inner.get("bindings"), list):
            return None  # the query did not run: a failure, not an absence
        if inner["bindings"]:
            return None
        # The SAME selection the query was built with, or the coverage check below compares
        # against classes the query never asked for.
        cls, classes, plant = self._floor_scope_classes(
            user_query, class_target, class_targets, concept_populated
        )
        if not classes and not cls:
            return None  # label tier: an empty text match establishes nothing
        selected = set(classes or [cls])
        unasked = set(class_targets or []) - selected
        if unasked and not plant:
            # The query did not ask for everything the question's CONCEPT means, so its
            # emptiness is not an absence of that concept. Measured live: "noise on floor 4"
            # selects the keyword map's building-prefixed Noise_Level_Sensor (one instance
            # in the building, none on floor 4) while the concept resolves to
            # ontosage:Sound_Level_Sensor — 52 of them on floor 4. Announcing "there is no
            # noise measurement on floor 4" there would be the false absence this project
            # has a guard for. (A named plant quantity drops room concept classes on
            # purpose, so it is exempt.)
            logger.info(
                f"[sparql] empty floor-scoped result did not cover concept classes "
                f"{sorted(unasked)} — no typed absence"
            )
            return None
        floors = sorted(
            set(re.findall(r"\b(?:floor|level)\s*(\d+)\b", user_query, re.IGNORECASE)), key=int
        )
        if not floors:
            where = "on any floor"
        elif len(floors) == 1:
            where = f"on floor {floors[0]}"
        else:
            where = "on floors " + ", ".join(floors[:-1]) + f" and {floors[-1]}"
        quantity = self._humanise_class(plant or cls or classes[0])
        subject = f"{quantity} measurement {where}"

        from orchestrator.services.retrieval_outcome import (
            classify as _classify_nothing,
        )

        outcome = _classify_nothing(declared=False, subject=subject)
        logger.info(
            f"[sparql] intent={intent}: floor-scoped resolve by class {classes or [cls]} "
            f"returned 0 rows -> typed absence ({outcome.outcome.value}), no semantic fallback"
        )
        return {
            "success": True,
            "query": sparql_query,
            "results": results,
            "formatted_response": outcome.external,
            "standardized": [],
            "context": [],
            "analytics_required": False,
            "llm_reasoning": "Deterministic floor-scoped lookup returned no rows",
            "method": "typed_absence",
            "retrieval_outcome": {
                "outcome": outcome.outcome.value,
                "internal": outcome.internal,
                "subject": subject,
                "remedy": outcome.remedy,
                "classes": list(classes or [cls]),
                "floors": floors,
            },
        }

    async def generate_query(self, state: ConversationState, user_query: str) -> Dict[str, Any]:
        """
        Generate SPARQL query using RAG

        Returns:
            Dict with 'query', 'explanation', 'context'
        """
        try:
            # A register is small and completely enumerable, so it is fetched WHOLE
            # rather than queried (V7-T18). Generated SPARQL over these was wrong in a
            # different way on every run: "is the standby generator under warranty?"
            # answered "expired" when the record says VOID, then on the next attempt said
            # no warranty covers it at all — the record is right there. "Which contracts
            # expire in the next six months?" counted six including two that lapsed
            # months ago, then one. A date filter and a status filter are exactly what a
            # language model is least reliable at, and a confidently wrong register
            # answer is worse than no answer.
            #
            # Bounded by MAX_RECORD_ROWS: this is only correct while a register is small
            # enough to hand over whole, and a bigger one must fall back to querying.
            deterministic = await self._whole_register(state, user_query)
            if deterministic is not None:
                return deterministic

            # An instrument's calibration and cadence are declared, not inferred (BUG-427).
            # Routing now sends these questions here, but a generated query asked for sensor
            # names and UUIDs and the answer came back "the data I have only lists the
            # sensor itself — it doesn't include a calibration timestamp" about a sensor
            # whose record says 2025-11-17. The properties are narrow and named; asking for
            # them directly is more reliable than hoping they are retrieved into context.
            metrology = await self._instrument_metrology(user_query)
            if metrology is not None:
                return metrology

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
                    # The Brick classes the lay-term resolver already found, so a FLOOR entity
                    # can be resolved to the points of that quantity ON the floor rather than
                    # to whatever is NAMED for it (BUG-884). Read here, before the class target
                    # is computed below, because the resolution happens first.
                    _floor_classes = [
                        str(_c)
                        for _cm in (state.intermediate_results.get("concepts") or [])
                        for _c in (_cm.get("brick_classes") or [])
                        if str(_c).strip()
                    ]
                    entities = await self._resolve_entities_by_label(
                        plain,
                        user_query=user_query,
                        ts_bearing=ts_entities,
                        class_hints=_floor_classes,
                    )
            # T05: prefer HBCO concept brick class over static keyword map
            class_target = None
            _concept_classes: List[str] = []
            _hbco_concepts = state.intermediate_results.get("concepts") or []
            for _cm in _hbco_concepts:
                _bc = _cm.get("brick_classes") or []
                if _bc:
                    # MOST SPECIFIC, not first. The classes come back from the graph
                    # unordered, so taking _bc[0] picked whichever the store happened
                    # to return -- and when a concept names both a class and its
                    # PARENT, the parent answers a different question. Measured
                    # 2026-08-25: parking_availability maps to
                    # ontosage:Parking_Occupancy_Sensor and its parent
                    # brick:Occupancy_Count_Sensor; the parent won, matched 40
                    # instances instead of 1, and "how many parking spaces are free?"
                    # was answered "294" -- the building's space count, presented as
                    # free bays. A real number from a real query to a different
                    # question, so the numeric guard had no reason to object.
                    # The TBox decides, not the alphabet: the resolver SORTS these, and
                    # "first" made every temperature concept target
                    # Outside_Air_Temperature_Sensor (one instance in bldg1).
                    _anc, _inst = await self._class_relations(_bc)
                    class_target = self._most_specific_class(_bc, _anc, _inst)
                    # Kept alongside the single pick: the floor-scoped resolver can query
                    # them all, and a composite concept means all of them (BUG-632).
                    _concept_classes = list(_bc)
                    logger.info(
                        f"[sparql] class from HBCO concept "
                        f"'{_cm.get('concept_id')}': {class_target}"
                        + (f" (from {len(_bc)} candidates)" if len(_bc) > 1 else "")
                    )
                    break
            # Does the building hold any instance of what the concept resolved to? True makes
            # the concept outrank the static keyword map; False hands the choice back to the
            # map; None (the graph could not say) leaves the ranking as it was.
            _concept_populated: Optional[bool] = None
            if _concept_classes:
                _held = await self._populated_classes(_concept_classes)
                if _held is not None:
                    _concept_populated = bool(_held)
                if _concept_populated is False:
                    _kw_cls = self._infer_class(user_query.lower())
                    logger.info(
                        f"[sparql] concept classes {_concept_classes} have no instances here "
                        f"— keyword map class {_kw_cls} used instead"
                    )
                    class_target = _kw_cls or class_target
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
            sparql_query = self._floor_scoped_sparql(
                user_query,
                class_target,
                class_targets=_concept_classes,
                concept_populated=_concept_populated,
            )
            used_floor_scope = sparql_query is not None
            if used_floor_scope:
                logger.info("[sparql] using deterministic floor-scoped template (portable)")

            # Phase 3.1: Template-first routing (zero LLM for common patterns)
            # Expanded dynamically using OntologyIntrospector discovered classes
            if sparql_query is None:
                sparql_query = self._template_sparql(
                    user_query, entities, ts_entities, concept_class=class_target
                )

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
                # CAVEAT-654 — decided per intent AND per what the empty result proves.
                #
                # The semantic-RAG fallback is LLM prose over retrieved ontology text with no
                # bindings behind it. For a question asking for a READING it can only produce
                # a figure nothing measured, or a paragraph about sensors in place of the
                # value; for an open metadata / discovery question it is often the best
                # answer available. So:
                #   * data-reading intent + the deterministic floor-scoped resolver, by CLASS,
                #     ran and returned zero rows -> a typed absence (NOT_DECLARED in the
                #     authorised scope). That query's meaning is fixed, so its emptiness is a
                #     fact about the graph and the absence machinery words it.
                #   * data-reading intent + an LLM-generated or label-matched query that came
                #     back empty -> STILL the fallback. An empty result from a query nobody
                #     can vouch for is not evidence of absence (review C08), and
                #     retrieval_outcome has no authorised wording for "the lookup established
                #     neither"; claiming NOT_DECLARED there would be the false "this building
                #     has no X" that absence_guard exists to catch. BUG-643 now records those
                #     answers grounded=False, and the gated intents withhold their figures.
                #   * a query that FAILED (no result envelope at all) is not an absence either
                #     and keeps the old path.
                #   * every other intent (metadata, discovery, general, recommend...) keeps
                #     the fallback unchanged.
                absence = self._typed_absence(
                    state,
                    user_query,
                    sparql_query,
                    results,
                    used_floor_scope,
                    class_target,
                    _concept_classes,
                    _concept_populated,
                )
                if absence is not None:
                    return absence
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

    #: A register above this size is no longer safely enumerable in one answer, and the
    #: LLM path takes over. Chosen so bldg1's largest (15 permits) fits several times
    #: over; a building with thousands of bookings will fall back, which is correct.
    MAX_RECORD_ROWS = 120

    #: A whole-register handover is paid for in rows TIMES columns, not rows alone. The
    #: stakeholder register is 82 rows — comfortably inside the 120-row limit — and returned
    #: an EMPTY COMPLETION, so the user got nothing at all.
    #:
    #: SET FROM MEASUREMENT, not from a guess. The pivoted size of every register this
    #: building holds:
    #:
    #:     StakeholderGroup        1,558   <- the only one that fails
    #:     AssetEngineeringProfile   816
    #:     WorkspaceProfile          784
    #:     FireSafetyAsset           600
    #:     Department                460
    #:
    #: 1300 sits above every register that works and below the one that does not. An
    #: earlier value of 700, chosen from an ESTIMATE rather than these figures, declined
    #: the asset and workspace registers and took the regression probe from 23/25 to 19/25.
    #:
    #: Raised from 1000 to 1300 on measurement, not on preference: a TWO-register handover
    #: of workspace plus circulation is 1,267 cells, and three consecutive runs at that size
    #: returned full answers with no empty completion. 1,558 still fails and is still
    #: excluded, so the budget continues to separate the two.
    MAX_RECORD_CELLS = 1300

    #: The same limit in the unit the model actually pays: characters of the rows as
    #: `_render_rows` prints them into the prompt (BUG-546). Cells cannot see value length —
    #: 1,267 cells of workspace + circulation rendered 40.6k and answered three times, while
    #: 1,300 cells of routes + workspace rendered 42.8k and returned an empty completion
    #: three times (the whole prompt 58,848 chars; every empty completion logged on this
    #: stack was 56k or more at a 16,384-token context). 34k sits 20% under the failure,
    #: and hoisting the values a register's rows share brings most handovers well below it.
    MAX_RECORD_CHARS = 34000

    def _rendered_chars(self, results: Dict[str, Any]) -> int:
        """How many characters these rows cost the narration prompt."""
        return len(self._render_rows(results.get("results", {}).get("bindings", []), hoist=True))

    #: How many columns a register hands over.
    #:
    #: This was 12, set when a wide register's narration kept failing and width was the
    #: suspect. Width was NOT the cause (CAVEAT-619: the provider's runner was dying with a
    #: CUDA fault, on prompts as small as 155 tokens), and the cap then caused a worse defect
    #: than the one it was meant to fix: asked for spaces suitable for quiet focused work, the
    #: projection dropped `noiseProfile`, `quietestPeriod` and `seatCount`, and the answer
    #: truthfully reported that the building records no such thing (BUG-622). A narrower
    #: handover that makes the system deny its own data is not a saving.
    #:
    #: So the cap is now set where it only trims the genuinely extreme, and the real budget is
    #: the character one below. Direct measurement: this provider answers prompts of 351k
    #: characters; the widest register here renders in ~15k.
    MAX_HANDOVER_COLUMNS = 24

    #: Columns every register answer needs whatever was asked: what the record IS and what
    #: state its owner put it in.
    _ALWAYS_KEEP = ("record", "recordId", "label", "recordStatus")

    #: Stamped on every row by the lifter; they say where the record came from, never what it
    #: says. Dropped first, and the answer's provenance chip carries them anyway.
    _PROVENANCE_COLUMNS = (
        "retrievedAt",
        "liftedByMapping",
        "derivedFromDocument",
        "recordVersion",
        "owningAuthority",
        "effectiveFrom",
        "recordOwner",
    )

    def _project_columns(
        self, results: Dict[str, Any], columns: List[str], question: str
    ) -> Tuple[Dict[str, Any], List[str], List[str]]:
        """Keep the columns the question names, plus identity and status. Returns what was cut.

        Ranked, never truncated arbitrarily: a column whose words appear in the question comes
        first, then the rest in their original order. What is dropped is NAMED in the guidance,
        so the answer can say the register holds more than it showed.
        """
        # The stamps go whatever the width: they record where a row came from, never what it
        # says, and the answer's provenance chip carries them already. The facts are counted
        # from the full rows upstream, so nothing computed depends on their being here.
        #
        # `effectiveFrom` is judged by its VALUES, not its name (BUG-639): the lifter stamps
        # it from the front matter only when a row has no mapped column of its own, so in ten
        # registers it holds the record's real date. Dropping it as a stamp answered "when was
        # the last project handover?" with "the records do not contain dates for handovers"
        # from a register carrying an issue date on every row.
        from orchestrator.services.register_facts import provenance_fields

        _stamps = set(self._PROVENANCE_COLUMNS) & provenance_fields(
            results.get("results", {}).get("bindings", [])
        ) | (set(self._PROVENANCE_COLUMNS) - {"effectiveFrom"})
        content = [c for c in columns if c not in _stamps]
        if len(content) <= self.MAX_HANDOVER_COLUMNS and len(content) == len(columns):
            return results, columns, []
        columns, dropped_provenance = content, [c for c in columns if c in _stamps]
        asked = set(re.findall(r"[a-z]+", (question or "").lower()))

        def _named(col: str) -> bool:
            # Matched on STEMS and PREFIXES, not whole words. "services" must keep
            # `servesService` (the first version dropped it), and "quiet" must keep
            # `quietestPeriod` — the column the question is actually about, which a whole-word
            # comparison misses entirely (BUG-622).
            stems = {w.rstrip("s") for w in asked if len(w) > 3}
            words = {w.lower().rstrip("s") for w in re.findall(r"[A-Za-z][a-z]+", col)}
            return any(w.startswith(s) or s.startswith(w) for s in stems for w in words)

        keep = [c for c in columns if c in self._ALWAYS_KEEP]
        keep += [c for c in columns if c not in keep and _named(c)]
        for col in columns:
            if len(keep) >= self.MAX_HANDOVER_COLUMNS:
                break
            if col in keep or col in _stamps:
                continue
            keep.append(col)
        # Order the survivors as the register declares them: a table whose columns arrive in
        # question-order reads as a ranking the register never made.
        keep = [c for c in columns if c in keep]
        dropped = [c for c in columns if c not in keep] + dropped_provenance
        kept_set = set(keep)
        projected = {
            "results": {
                "bindings": [
                    {k: v for k, v in row.items() if k in kept_set}
                    for row in results["results"]["bindings"]
                ]
            }
        }
        logger.info(
            f"[sparql] register projected to {len(keep)} of {len(keep) + len(dropped)} "
            f"columns; dropped {dropped}"
        )
        return projected, keep, dropped

    @staticmethod
    def _pivot_by_subject(bindings: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[str]]:
        """Turn ?record/?p/?v triples into one binding row per record.

        Returns a SPARQL-shaped result so everything downstream — standardisation,
        formatting, the evidence record — treats it like any other query result.
        """
        rows: Dict[str, Dict[str, Any]] = {}
        columns: List[str] = ["record"]
        for binding in bindings:
            subject = (binding.get("record") or {}).get("value", "")
            predicate = (binding.get("p") or {}).get("value", "")
            value = (binding.get("v") or {}).get("value", "")
            if not subject or not predicate:
                continue
            column = predicate.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            row = rows.setdefault(subject, {"record": {"type": "uri", "value": subject}})
            if column in row:  # a repeated predicate keeps both, comma-joined
                row[column]["value"] = f"{row[column]['value']}, {value}"
            else:
                row[column] = {"type": "literal", "value": value}
                if column not in columns:
                    columns.append(column)
        ordered = list(rows.values())
        for row in ordered:  # every row carries every column, so a gap reads as a gap
            for column in columns:
                row.setdefault(column, {"type": "literal", "value": ""})
        return {"head": {"vars": columns}, "results": {"bindings": ordered}}, columns

    #: Words that scope nothing. A filter built from these matches most of a register and
    #: defeats the purpose, so they are excluded before the scope is built.
    _SCOPE_STOPWORDS = frozenset(
        """the a an of in for is are to and or on with by which what how many when where who
        this that from at as it its be has have do does any all show me my our list tell
        please can could would should not no next last this month week year day today
        tomorrow scheduled are there""".split()
    )

    @staticmethod
    def _escape_literal(text: str) -> str:
        return str(text).replace("\\", "\\\\").replace('"', '\\"')

    @classmethod
    def _scope_tokens(cls, user_query: str) -> List[str]:
        """The parts of a question specific enough to narrow a large register.

        Identifiers ("1.06", "TS-0042", "DEP-07") and capitalised words carry the scope;
        ordinary words do not. Returns [] when the question names nothing specific, and the
        caller then declines rather than handing over an arbitrary slice.
        """
        import re as _re

        tokens: List[str] = []
        for match in _re.findall(
            r"\b\d+\.\d+\b|\b[A-Z]{2,}-\d+\b|\b\d{4}-\d{2}-\d{2}\b", user_query or ""
        ):
            if match.lower() not in tokens:
                tokens.append(match.lower())
        if not tokens:
            for word in _re.findall(r"\b[A-Z][a-z]{3,}\b", user_query or ""):
                low = word.lower()
                if low not in cls._SCOPE_STOPWORDS and low not in tokens:
                    tokens.append(low)
        return tokens[:6]

    #: Words that name no measurand. Every metrology question contains several of them, and
    #: a filter matching "sensor" matches the whole graph and scopes nothing.
    _GENERIC_INSTRUMENT_WORDS = frozenset(
        """sensor sensors device devices instrument instruments point points meter meters
        stream streams report reports reporting record records recording log logs logging
        was were been being will shall may might must
        sample samples sampling interval intervals calibrated calibration calibrations
        recalibration overdue due date dates last next often does the a an of in for is are
        to and or on with by which what how many when where who this that from at as it its
        be has have do any all show me my our list tell please can could would should not
        no year years month months week weeks day days building""".split()
    )

    @classmethod
    def _measurand_tokens(cls, user_query: str) -> List[str]:
        """What the question is asking ABOUT, when it names a kind rather than an instance.

        "How often does a CO2 sensor report?" -> ["co2"]. Matched against the sensor IRI,
        which carries the class name in every building this repo has seen. Returns [] when
        the question names no measurand, and the caller then answers building-wide.
        """
        import re as _re

        out: List[str] = []
        for word in _re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", user_query or ""):
            low = word.lower()
            if len(low) < 3 or low in cls._GENERIC_INSTRUMENT_WORDS or low in out:
                continue
            out.append(low)
        return out[:4]

    @staticmethod
    def _merge_registers(
        a: Dict[str, Any],
        a_columns: List[str],
        a_label: str,
        b: Dict[str, Any],
        b_columns: List[str],
        b_label: str,
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Two registers as one result set, each row saying which register it came from.

        A `register` column is added FIRST and carries the register's human label. Without
        it the two sets of rows are indistinguishable once they reach the prompt, and a
        model asked which transition takes longest would happily read a setup time as a
        travel time — turning a fix for a half-answer into a wrong one.

        Columns are the union, and a row missing a column carries an empty value rather
        than nothing, so a gap reads as a gap in both registers alike.
        """
        columns = ["register"] + [c for c in a_columns if c != "register"]
        for column in b_columns:
            if column not in columns:
                columns.append(column)

        merged: List[Dict[str, Any]] = []
        for rows, label in (
            (a["results"]["bindings"], a_label),
            (b["results"]["bindings"], b_label),
        ):
            for row in rows:
                out = {"register": {"type": "literal", "value": label}}
                for column in columns:
                    if column == "register":
                        continue
                    out[column] = row.get(column) or {"type": "literal", "value": ""}
                merged.append(out)
        return {"head": {"vars": columns}, "results": {"bindings": merged}}, columns

    async def _instrument_metrology(self, user_query: str) -> Optional[Dict[str, Any]]:
        """Answer a calibration or reporting-interval question from the declaration.

        Returns None when the question is not about an instrument's metrology, so the
        normal path runs untouched.

        WHY DETERMINISTIC. The properties are few and named — ontosage:calibratedOn,
        calibrationDueOn, calibrationMethod, samplingIntervalS, archivalIntervalS — and a
        generated query has to guess that they exist before it can ask for them. It did not:
        routed correctly to this lane, the LLM asked for sensor names and UUIDs, and the
        answer was "it doesn't include a calibration timestamp" about a sensor carrying one.

        The question's own identifiers scope the result, exactly as an oversized register is
        scoped. Without one the answer is the building-wide picture, which is what "how many
        sensors are overdue for calibration?" is actually asking.
        """
        from orchestrator.services.routing_contract import _METROLOGY_RE

        if not _METROLOGY_RE.search(user_query or ""):
            return None

        # An identifier scopes to an INSTANCE ("Room 5.01"); a measurand scopes to a KIND
        # ("a CO2 sensor"). Both are scopes and the question uses whichever it means.
        #
        # Identifiers alone were not enough: "How often does a CO2 sensor report?" names no
        # instance, so the query ran building-wide with a LIMIT and returned the first 200
        # sensors in IRI order — every one of them an air-handling point — and the answer
        # was "none of the listed URIs contain a CO2 sensor". Correct about its input and
        # useless, from a graph holding 280 of them.
        tokens = self._scope_tokens(user_query)
        if not tokens:
            tokens = self._measurand_tokens(user_query)
        scope = ""
        if tokens:
            clauses = " || ".join(
                f'CONTAINS(LCASE(STR(?sensor)), "{self._escape_literal(t)}")' for t in tokens
            )
            scope = f"  FILTER({clauses})\n"

        # AN UNSCOPED QUESTION IS COUNTED, NOT LISTED.
        #
        # "How many sensors are overdue for calibration?" names nothing to scope by, and
        # 1,929 sensors declare a calibration date. Handing back the first 200 in IRI order
        # and letting the model count them would produce a confident number computed from a
        # tenth of the data — the exact failure BUG-370 and BUG-191 cost this project twice.
        # The graph can count; so it counts.
        if not scope:
            today = datetime.now(timezone.utc).date().isoformat()
            query = (
                "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
                "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
                "SELECT (COUNT(DISTINCT ?s) AS ?sensors_with_declared_interval)\n"
                "       (COUNT(DISTINCT ?c) AS ?sensors_with_a_calibration_regime)\n"
                "       (COUNT(DISTINCT ?overdue) AS ?calibrations_overdue) WHERE {\n"
                "  ?s ontosage:archivalIntervalS ?iv .\n"
                "  OPTIONAL { ?s ontosage:calibrationDueOn ?due . BIND(?s AS ?c)\n"
                f'    OPTIONAL {{ FILTER(?due < "{today}"^^xsd:date) BIND(?s AS ?overdue) }}\n'
                "  }\n"
                "}"
            )
        else:
            query = (
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
                "SELECT ?sensor ?calibrated_on ?calibration_due_on ?calibration_method "
                "?sampling_interval_s ?archival_interval_s WHERE {\n"
                "  ?sensor ontosage:archivalIntervalS ?archival_interval_s .\n"
                "  OPTIONAL { ?sensor ontosage:samplingIntervalS ?sampling_interval_s }\n"
                "  OPTIONAL { ?sensor ontosage:calibratedOn ?calibrated_on }\n"
                "  OPTIONAL { ?sensor ontosage:calibrationDueOn ?calibration_due_on }\n"
                "  OPTIONAL { ?sensor ontosage:calibrationMethod ?calibration_method }\n"
                + scope
                + "} ORDER BY ?sensor LIMIT 200"
            )
        try:
            raw = await self._execute_query(query)
        except Exception as exc:
            logger.warning(f"[sparql] metrology fetch failed, falling back: {exc}")
            return None
        bindings = (raw or {}).get("results", {}).get("bindings", [])
        if not bindings:
            return None  # nothing declared — let the normal path answer honestly

        logger.info(
            f"[sparql] instrument metrology: {len(bindings)} sensor(s) "
            f"{'scoped by ' + ', '.join(tokens) if tokens else 'building-wide'}"
        )
        guidance = (
            f"{user_query}\n\n"
            "(These are the instrument's DECLARED metrology, read from the building's "
            "ontology. sampling_interval_s and archival_interval_s are in SECONDS and are "
            "what the instrument is declared to do — never infer a reporting interval from "
            "the spacing of readings, which reflects whatever window happened to be "
            "fetched. A blank calibration field means the stream is a state or contact "
            "signal that is verified rather than calibrated, not that a calibration is "
            "missing. Answer only from these rows.)"
        )
        results = raw
        # Formatted by the SAME helpers as a generated query, so this reads like every
        # other answer. Only the QUERY is deterministic, never the wording.
        return {
            "success": True,
            "query": query,
            "results": results,
            "error": None,
            "formatted_response": await self._format_results(
                # A SMALLER limit than the register path, on purpose. That path is
                # bounded by MAX_RECORD_CELLS before the query runs; this one is
                # bounded only by LIMIT 200, and raising its rows to 240 sent a
                # scoped CO2 fetch of ~200 sensors into one prompt and produced an
                # empty completion. 40 covers every metrology question seen: an
                # instance, a handful of a kind, or the aggregate, which is a
                # single row.
                results,
                guidance,
                query,
                True,
                row_limit=40,
            ),
            "standardized": self._standardize_results(results, user_query, query),
            "context": [],
            "analytics_required": False,
            "llm_reasoning": "Deterministic instrument-metrology fetch (BUG-427)",
            "method": "instrument_metrology",
        }

    async def _whole_register(
        self, state: ConversationState, user_query: str
    ) -> Optional[Dict[str, Any]]:
        """Return an entire small register, deterministically, with no generated SPARQL.

        Returns None when the question is not about a held record class, or when the
        register is too large to hand over whole — in both cases the normal path runs.
        """
        try:
            from orchestrator.services.record_registry import (
                held_record_class,
                record_classes,
            )

            record = held_record_class(user_query, await record_classes())
        except Exception as exc:  # pragma: no cover - never block on this
            logger.debug(f"[sparql] record registry unavailable: {exc}")
            return None

        if record is None:
            return None

        # A PLANT READING IS NOT A REGISTER QUESTION (2026-09-16). "What's the delta-T across
        # the heating circuit, and is it healthy?" matched PatrolCheckpoint — "circuit" is one
        # of its lay terms — and was answered with eighteen patrol checkpoints. The dialogue
        # short-circuit already refuses these; this path resolves the record class again, so
        # the same rule has to hold here or the guard only moves the wrong answer one lane.
        from orchestrator.services.routing_contract import (
            PLANT_READING_RE,
            measured_reading_question,
        )

        if PLANT_READING_RE.search(user_query or "") or measured_reading_question(user_query):
            logger.info(
                f"[sparql] {record.local_name} matches, but the question asks what a plant "
                f"circuit READS — leaving it to the data lanes"
            )
            return None

        # A LARGE REGISTER IS SCOPED, NOT ABANDONED.
        #
        # This used to return None whenever a register exceeded MAX_RECORD_ROWS, on the
        # reasoning that a building "with thousands of bookings will fall back, which is
        # correct". Falling back is correct; what happened next was not. Measured live once
        # the timetable was lifted into 675 sessions:
        #
        #   Q: "Which teaching sessions are scheduled in Room 1.06 this month?"
        #   A: "the data you provided only lists spaces and the number of sensors ..."
        #
        # The generated fallback query asked about SENSOR COUNTS. The routing had already
        # established the question was about TimetabledSession and that knowledge was
        # dropped on the floor, so a register with the answer in it produced an answer about
        # something else entirely.
        #
        # The question almost always carries its own scope — a room, a code, a date. Those
        # literals are matched against the register's values, and a filtered set that fits
        # is handed over exactly as a small register is. Nothing is truncated: if the filter
        # does not bring the set under the limit, this still returns None and the normal
        # path runs, because handing over an arbitrary 120 of 675 sessions would answer
        # "which room has the most" from a quarter of the data and look authoritative.
        # ROWS ARE NOT THE COST. COLUMNS ARE, TOO.
        #
        # MAX_RECORD_ROWS bounded the handover by row count while the prompt is paid in
        # rows TIMES columns. The stakeholder register is 82 rows — comfortably inside the
        # 120-row limit — and 11 columns, so 902 values went into one prompt and the model
        # returned an EMPTY COMPLETION. The user got nothing at all, which is worse than
        # either a scoped answer or an honest decline.
        #
        # Measured across this building's registers: stakeholder 902 cells, asset
        # engineering 624, workspace 560, fire safety 390. Only the first fails, and only
        # a cell budget separates it from the rest — a row limit cannot, because the
        # failing register has the FEWEST columns of the four.
        #
        # This is the same shape as several defects already in this tracker: a limit
        # expressed in one unit against a requirement expressed in another.
        # THE PRE-CHECK IS THE ROW COUNT ONLY. An estimate of cells from the mapping's
        # declared columns understates the real width by about 1.7x, because every lifted
        # record also carries provenance predicates the mapping never mentions. Gating on
        # that estimate declined two registers that work — measured, 19/25 on the regression
        # probe against a 23/25 baseline. The real size is known one query later and is
        # checked there; guessing it here only produced a confident wrong answer about how
        # big something was going to be.
        tokens = self._scope_tokens(user_query) or self._measurand_tokens(user_query)

        def _scope_clause() -> str:
            if not tokens:
                return ""
            clauses = " || ".join(
                f'CONTAINS(LCASE(STR(?sv)), "{self._escape_literal(t)}")' for t in tokens
            )
            return (
                "  {\n"
                "    SELECT DISTINCT ?record WHERE {\n"
                f"      ?record a ontosage:{record.local_name} ; ?sp ?sv .\n"
                f"      FILTER({clauses})\n"
                f"    }} LIMIT {self.MAX_RECORD_ROWS}\n"
                "  }\n"
            )

        def _build_for(which: Any, scope_filter: str) -> str:
            """The register query for any class, so a second register reuses this one."""
            return (
                "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
                "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
                "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
                "SELECT ?record ?p ?v WHERE {\n"
                + scope_filter
                + f"  ?record a ontosage:{which.local_name} ; ?p ?v .\n"
                "  FILTER(?p != rdf:type)\n"
                f"}} ORDER BY ?record LIMIT {self.MAX_RECORD_ROWS * 25}"
            )

        def _build(scope_filter: str) -> str:
            return _build_for(record, scope_filter)

        # A ROW-oversized register is scoped up front, because fetching 675 sessions to
        # discover they are 675 is waste. A CELL-oversized one cannot be known until the
        # rows come back, so it is fetched, measured, and RE-FETCHED scoped — one extra
        # query, only for a register that needs it.
        #
        # Without the retry the cell check was a dead end: the stakeholder register (82
        # rows, under the row limit) was fetched whole, measured at 1,640 cells, and
        # declined WITHOUT EVER BEING SCOPED. "Which stakeholder groups does DEP-13 serve?"
        # names a department code that narrows it to three records, and the answer was
        # still "no such records appear in the triples supplied".
        oversized = record.instances > self.MAX_RECORD_ROWS
        # "WHICH ROOMS HAVE TEACHING SESSIONS?" IS A GROUPING, AND THE GRAPH CAN DO IT (2D-06
        # wave 2). Counting per value is an aggregate, so it is asked of GraphDB rather than of a
        # narration holding no rows.
        #
        # BEFORE THE SCOPING, not after it, and that placement is the whole of the fix. `tokens`
        # falls back to the question's content words, so "rooms", "teaching" and "sessions"
        # counted as a scope: the register was re-fetched filtered on those words as TEXT,
        # measured over budget, and declined — and the generated query then answered "the
        # building's records do not contain any information about teaching sessions … consult the
        # timetable system", from a building holding 675 of them. A word like "rooms" scopes
        # nothing in a register of sessions; it names what to group BY.
        if oversized:
            grouped = await self._register_grouping(record, user_query, state)
            if grouped is not None:
                return grouped
            projected = await self._register_projected_whole(record, user_query, state)
            if projected is not None:
                return projected
        if oversized and not tokens:
            logger.info(
                f"[sparql] {record.local_name} is too large to hand over whole and the "
                f"question names nothing to scope by — falling back to a generated query"
            )
            return None
        query = _build(_scope_clause() if oversized else "")
        try:
            raw = await self._execute_query(query)
        except Exception as exc:
            # A HELD REGISTER THAT COULD NOT BE READ IS NOT A REASON TO IMPROVISE (BUG-596).
            # This fell back to a generated query, which answered "Where can I work for three
            # hours with power, good Wi-Fi and a low risk of noise?" with "Wi-Fi coverage is
            # generally strong throughout the building" and "the ground floor tends to be the
            # quietest" — none of it in any record — after the workspace register read timed out.
            # Size-based fallbacks stay above; a failed READ says so.
            logger.warning(f"[sparql] whole-register fetch failed — answering honestly: {exc}")
            label = record.label or record.local_name
            return {
                # success=True: this IS the answer. False lets later lanes generate one.
                "success": True,
                "query": query,
                "results": {"results": {"bindings": []}},
                "error": f"register read failed: {type(exc).__name__}",
                "formatted_response": (
                    f"I couldn't read the building's **{label}** records just now, so I can't "
                    "answer this from them. Please ask again in a moment — I won't guess."
                ),
                "context": [],
                "analytics_required": False,
                "llm_reasoning": "Whole-register read failed; declined rather than generated",
                "method": "whole_register_unavailable",
            }
        bindings = (raw or {}).get("results", {}).get("bindings", [])
        if not bindings:
            return None  # nothing to hand over — let the normal path try

        # ONE ROW PER RECORD, not one row per triple.
        #
        # Handing back the flat triple list regressed a question that had been answering
        # correctly: "how many permits are open?" became "none of them — all 15 are
        # closed" when 3 are open. 15 permits times 16 predicates is 240 rows, and
        # grouping those by subject to count a status is exactly the bookkeeping a
        # language model is worst at. Pivoting costs nothing and removes the need.
        results, columns = self._pivot_by_subject(bindings)

        # SIZE THE PIVOTED RESULT, in the same unit the budget is written in.
        #
        # An estimate decides whether to TRY; the result decides whether to HAND OVER. The
        # scope only helps if it narrows, and it does not always: "which stakeholder groups
        # are served by the accessibility team?" names no identifier, so the scope falls
        # back to content words and "groups" matches nearly every row — the prompt stayed as
        # large as before and the model returned an EMPTY COMPLETION.
        #
        # MEASURED AFTER THE PIVOT, deliberately. A first version of this check counted RAW
        # BINDINGS, which are one per triple and include the provenance predicates every
        # lifted record carries — so a 24-row register measured 792 against a 624 estimate
        # and four working answers were declined into the generated-query path. Comparing an
        # estimate in one unit against a measurement in another is the same mistake the
        # budget itself was introduced to fix, made one line further down.
        _cells = len(results["results"]["bindings"]) * max(len(columns), 1)
        _too_big = lambda: (  # noqa: E731 - re-evaluated after the scoped re-fetch
            _cells > self.MAX_RECORD_CELLS or self._rendered_chars(results) > self.MAX_RECORD_CHARS
        )
        if _too_big() and not oversized and tokens:
            # Too wide to hand over whole, and the question DOES name something. Re-fetch
            # scoped rather than declining a register that can answer once narrowed.
            logger.info(
                f"[sparql] {record.local_name} is {_cells} cells whole — re-fetching scoped "
                f"by {', '.join(tokens)}"
            )
            try:
                query = _build(_scope_clause())
                raw = await self._execute_query(query)
            except Exception as exc:
                logger.warning(f"[sparql] scoped re-fetch failed, falling back: {exc}")
                return None
            bindings = (raw or {}).get("results", {}).get("bindings", [])
            if not bindings:
                return None
            results, columns = self._pivot_by_subject(bindings)
            _cells = len(results["results"]["bindings"]) * max(len(columns), 1)

        if _too_big():
            logger.info(
                f"[sparql] {record.local_name} still holds {_cells} cells / "
                f"{self._rendered_chars(results)} chars after scoping, over the "
                f"{self.MAX_RECORD_CELLS}-cell / {self.MAX_RECORD_CHARS}-char budget — falling "
                f"back to a generated query rather than risking an empty completion"
            )
            return None

        # THE FACTS ARE COUNTED FROM EVERY FIELD, and only the NARRATION is projected
        # (BUG-622). `passed_due_not_marked()` needs `nextTestDue`, completeness needs the
        # columns a question names; counting them from the trimmed rows would make the system
        # state, in code and with authority, a figure derived from data it had just discarded.
        _full_rows = list(results["results"]["bindings"])

        results, columns, _dropped_columns = self._project_columns(results, columns, user_query)

        logger.info(
            f"[sparql] whole-register fetch: {record.local_name} "
            f"({record.instances} instances, {len(columns)} fields) — no SPARQL generated"
        )

        # A SECOND REGISTER, when the question genuinely names two (CAVEAT-432).
        #
        # "Which transition needs the larger travel and setup time?" names CirculationTime
        # (travel) and WorkspaceProfile (setup). Handing over one produced a confident half
        # answer — "we don't have explicit travel-time data" — from a building holding it in
        # the register next door. The same shape refused "which stakeholder groups are
        # served by the accessibility team?".
        #
        # NOT BY DENORMALISING. Copying the second register's fields into the first would
        # answer these questions today and guarantee the two disagree within a year, which
        # the stakeholder mapping's own header already argues against. The registers stay
        # separate and BOTH are handed over.
        #
        # At most one extra, and only when the budget still fits. Two registers is a
        # question spanning two things; handing over the building's whole record layer is
        # the prompt-size failure that already cost an empty completion (BUG-433).
        # BUG-589: the counted facts describe the register the question named, so they are
        # taken from its rows BEFORE a second register is merged in — and from the FULL
        # fields, not the projected ones (BUG-622).
        _primary_rows = _full_rows
        second_label = ""
        try:
            from orchestrator.services.record_registry import record_classes as _rc
            from orchestrator.services.record_registry import second_record_class

            _second = second_record_class(user_query, await _rc(), record)
            if _second is not None:
                s_raw = await self._execute_query(_build_for(_second, ""))
                s_bindings = (s_raw or {}).get("results", {}).get("bindings", [])
                if s_bindings:
                    s_results, s_columns = self._pivot_by_subject(s_bindings)
                    s_cells = len(s_results["results"]["bindings"]) * max(len(s_columns), 1)
                    merged = None
                    if _cells + s_cells <= self.MAX_RECORD_CELLS:
                        merged = self._merge_registers(
                            results,
                            columns,
                            record.label or record.local_name,
                            s_results,
                            s_columns,
                            _second.label or _second.local_name,
                        )
                        if self._rendered_chars(merged[0]) > self.MAX_RECORD_CHARS:
                            merged = None
                    if merged is not None:
                        results, columns = merged
                        second_label = _second.label or _second.local_name
                        logger.info(
                            f"[sparql] second register {_second.local_name} added "
                            f"({s_cells} cells, {_cells + s_cells} total, "
                            f"{self._rendered_chars(results)} chars) — the question names both"
                        )
                    else:
                        logger.info(
                            f"[sparql] second register {_second.local_name} would take the "
                            f"handover to {_cells + s_cells} cells, over budget — answering "
                            f"from {record.local_name} alone"
                        )
        except Exception as exc:  # pragma: no cover - never lose the primary answer
            logger.debug(f"[sparql] second-register lookup skipped: {exc}")
        # Formatted by the SAME helpers as a generated query, so a register answer reads
        # like every other answer and inherits whatever formatting the rest of the
        # pipeline gains. Only the QUERY is deterministic here, never the wording.
        # WHAT THE RECORDS DO NOT SAY, AND WHAT DAY IT IS (BUG-546). Stakeholder run #1 through
        # Open WebUI found the narration inventing the link between a question and whatever
        # register it was handed: approval dates read as plant start times ("1 day late"),
        # approval statuses read as room no-shows, an approvals register used to declare that
        # compliance records "are retained for the correct period, in the authorised system",
        # and "events due today (2026-09-05)" on 15 September, the date taken from a
        # retrieval stamp because nothing told the model the date.
        try:
            from orchestrator.services.requested_interval import building_local_now

            _today = building_local_now(getattr(state, "building_id", None)).strftime(
                "%A %d %B %Y, %H:%M"
            )
        except Exception:  # pragma: no cover - the rules still apply without a date
            _today = ""
        grounding = (
            (f" Today is {_today} in the building's local time." if _today else "")
            + " If these records do not record what the question asks, say so plainly in the "
            "first sentence, name what they DO record, and stop there: never map a field onto a "
            "different concept (an approval, effective or review date is not an operating, start, "
            "attendance or occupancy time; an approval status is not a usage record; a "
            "commissioned or design DUTY is not an operating SCHEDULE, so a unit running below "
            "its duty is not a unit running outside its hours). Never "
            "certify, approve or guarantee safety, compliance, accessibility, confidentiality or "
            "adequacy, and never call a record 'yours' — report what the records state. When a "
            'word in the question could cover more than one recorded status ("open" can mean '
            "open or in progress), give the count for EACH status rather than choosing one."
        )
        if second_label:
            # SAY THAT THERE ARE TWO. The rows are interleaved in one table, and a model
            # told nothing would read a setup time as a travel time — a half-answer turned
            # into a wrong one, which is a worse trade than the gap it was fixing.
            guidance = (
                f"{user_query}\n\n"
                f"(These records come from TWO registers, grouped under a header naming each: "
                f"**{record.label}** and **{second_label}**. They describe different "
                f"things and their columns are NOT interchangeable — read each value against "
                f"the register its row names, and say which register each figure came from. "
                f"EVERY NUMBER YOU GIVE MUST APPEAR VERBATIM IN A ROW ABOVE. Do not estimate, "
                f"round, average or infer a figure, and do not describe one as 'about' or "
                f"'approximately' a value that is not there: name the row it comes from. If "
                f"the rows do not contain a figure the question needs, say that instead of "
                f"supplying one. ontosage:recordStatus is the owner's RECORDED state; use it "
                f"as given and never re-derive it from the dates. Answer only from these "
                f"records.{grounding})"
            )
        else:
            guidance = (
                f"{user_query}\n\n"
                f"(These are all {record.instances} {record.label} records this building "
                "holds. ontosage:recordStatus is the owner's RECORDED state — use it as "
                "given and never re-derive it from the dates; 'void' is not 'expired'. "
                "Where the RECORDED FACTS below list due dates that have already passed, "
                "report those as well, as dates passed, alongside the recorded status. "
                f"Answer only from these records.{grounding})"
            )
            if _dropped_columns:
                guidance += (
                    "\n\n(This register holds more fields than are shown: "
                    + ", ".join(_dropped_columns[:12])
                    + ". They were left out to keep the handover readable. If the question needs "
                    "one of them, say that they are recorded and can be read on request rather "
                    "than answering from the fields above as though they were all there.)"
                )

            # BUG-581: the counting is done in code, not left to the narration.
        try:
            from orchestrator.services.register_facts import register_facts

            _facts = register_facts(
                _primary_rows,
                user_query,
                building_local_now(getattr(state, "building_id", None)).date(),
                register_label=record.label or record.local_name,
            )
            logger.info(
                f"[sparql] register facts for {record.local_name} ({len(_facts)} chars): "
                f"{_facts!r}"[:900]
            )
            if _facts:
                guidance += (
                    "\n\nRECORDED FACTS — counted by the system from every row above. Every "
                    "count, list and status you state must agree with these; never recount, "
                    "and never move a record into a kind or status it does not have. They "
                    "also state WHAT THE REGISTER DOES NOT RECORD and where it disagrees "
                    "with itself: those statements are the answer to that part of the "
                    "question, so say them rather than reasoning past them:\n" + _facts
                )
        except Exception as exc:  # pragma: no cover - the rows still answer without it
            logger.warning(f"[sparql] register facts skipped: {type(exc).__name__}: {exc}")
        # Provenance for the evidence record. A record LIFTED from a document is
        # `document_derived`, which outranks a sensor reading and loses to authored TTL
        # (V7-T19) — the answer is only as current as the transcription. Where the graph
        # holds authored instances the tier is plain `authoritative`.
        lifted = any(
            (b.get("derivedFromDocument") or {}).get("value")
            for b in results["results"]["bindings"]
        )

        def _first(field: str) -> str:
            """The first non-empty value of a field across the register's rows.

            Every row of one register shares its owner, authority and version — the
            lifter stamps them from the document's front-matter — so one is enough to
            name who is accountable for the answer.
            """
            for binding in results["results"]["bindings"]:
                value = (binding.get(field) or {}).get("value", "")
                if value:
                    return str(value)
            return ""

        try:
            state.intermediate_results.setdefault("_prov_stores", []).append(
                {
                    "source_id": f"ontosage:{record.local_name}",
                    "kind": "document_derived" if lifted else "authoritative",
                    "store": "graphdb",
                    # V7-T11/T17/T10: owner is the most demanded field in the whole
                    # catalogue corpus, and an answer that cannot name it cannot be acted
                    # on — the reader does not know who to go to.
                    "owner": _first("recordOwner"),
                    "authority": _first("owningAuthority"),
                    "record_version": _first("recordVersion"),
                    "effective_at": _first("effectiveFrom") or None,
                }
            )
        except Exception:  # provenance is best-effort and must never cost the answer
            pass

        from orchestrator.services.register_facts import (
            completeness_line,
            passed_due_not_marked,
            strip_leaked_code_line,
        )

        _rows_answer = ""
        try:  # 2D-06: a lookup the rows settle (or a whole-subject state question) skips the model
            from orchestrator.services import register_projection as _rp
            from orchestrator.services.record_registry import record_classes as _rc0
            from orchestrator.services.requested_interval import building_local_now as _bln0

            _rows_answer = await _rp.answer_before_narration(
                user_query,
                _primary_rows,
                record.label or record.local_name,
                record.local_name,
                await _rc0(),
                lambda cls: self._register_rows(cls, _build_for),
                _bln0(getattr(state, "building_id", None)).date(),
                bool(second_label) or len(_primary_rows) < record.instances,
            )
        except Exception as exc:  # pragma: no cover - the narration still answers
            logger.warning(f"[sparql] projected answer skipped: {type(exc).__name__}: {exc}")
        _narration = _rows_answer or strip_leaked_code_line(
            await self._format_results(
                results, guidance, query, True, row_limit=self.MAX_RECORD_ROWS * 2
            )
        )
        try:  # BUG-589: completeness of an overdue answer is not left to the narration
            from orchestrator.services.requested_interval import (
                building_local_now as _bln,
            )

            if not _rows_answer:
                _narration += completeness_line(
                    _narration,
                    passed_due_not_marked(
                        _primary_rows, user_query, _bln(getattr(state, "building_id", None)).date()
                    ),
                )
        except Exception as exc:  # pragma: no cover - the narration still answers
            logger.warning(f"[sparql] completeness line skipped: {type(exc).__name__}: {exc}")
        try:  # W19 + 2D-06: a denial of a field the rows hold is REPLACED by its values.
            from orchestrator.services import register_projection as _rp
            from orchestrator.services.requested_interval import building_local_now as _bln

            if not _rows_answer:
                _narration = _rp.guard_narration(
                    _narration,
                    _primary_rows,
                    user_query,
                    record.label or record.local_name,
                    _bln(getattr(state, "building_id", None)).date(),
                )
        except Exception as exc:  # pragma: no cover - the narration still answers
            logger.warning(f"[sparql] false-absence check skipped: {type(exc).__name__}: {exc}")

        return {
            "success": True,
            "query": query,
            "results": results,
            "error": None,
            "formatted_response": _narration,
            "standardized": self._standardize_results(results, user_query, query),
            "context": [],
            "analytics_required": False,
            "llm_reasoning": "Deterministic whole-register fetch (V7-T18)",
            "method": "whole_register",
        }

    #: The most records read whole to answer one question deterministically. Counting and
    #: filtering 675 timetable sessions is cheap once they are rows; the limit exists so a
    #: register of a million records is never pulled into the process to answer "how many".
    MAX_PROJECTED_RECORDS = 3000

    async def _register_projected_whole(
        self, record: Any, user_query: str, state: ConversationState
    ) -> Optional[Dict[str, Any]]:
        """A count / exists / list-by-facet question over a register too large to narrate.

        Measured live 2026-09-19 on the timetable (675 sessions): "How many timetabled sessions
        on floor 1 are scheduled?" was DECLINED and "Are any timetabled sessions with weekday
        Thursday scheduled?" was answered "I did not find any weekday". The register was too big
        to hand to a model, so the lane refused it — but counting and filtering are not a model's
        job, and the same projection that answers the small registers answers this one from the
        rows (16 on floor 1, 36 on Thursdays). The narration is never asked: this returns an
        answer or None, and None leaves the scoped path exactly as it was.
        """
        from orchestrator.services import register_projection as rp
        from orchestrator.services.requested_interval import building_local_now

        if not (0 < record.instances <= self.MAX_PROJECTED_RECORDS):
            return None
        prep = rp.prepare(user_query)
        if prep.reader or not rp.question_shape(prep.core, prep.list_hint):
            return None  # a question no lookup answers: do not pay for the fetch
        limit = record.instances * 40  # a lifted record carries ~15-25 predicates
        query = (
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
            "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
            "SELECT ?record ?p ?v WHERE {\n"
            f"  ?record a ontosage:{record.local_name} ; ?p ?v .\n"
            "  FILTER(?p != rdf:type)\n"
            f"}} ORDER BY ?record LIMIT {limit}"
        )
        try:
            raw = await self._execute_query(query)
            bindings = (raw or {}).get("results", {}).get("bindings", [])
            pivoted, _cols = self._pivot_by_subject(bindings)
            rows = pivoted["results"]["bindings"]
            text = rp.deterministic_answer(
                rows,
                user_query,
                record.label or record.local_name,
                building_local_now(getattr(state, "building_id", None)).date(),
                len(rows) < record.instances,  # a truncated read is never presented as the whole
                record.terms,
            )
        except Exception as exc:
            logger.warning(
                f"[sparql] projected whole-register skipped: {type(exc).__name__}: {exc}"
            )
            return None
        if not text:
            return None
        logger.info(
            f"[sparql] {record.local_name}: {len(rows)} records read whole and answered by "
            "projection — the register was too large to narrate"
        )
        return {
            "success": True,
            "query": query,
            "results": {"results": {"bindings": []}},
            "error": None,
            "formatted_response": text,
            "context": [],
            "analytics_required": False,
            "llm_reasoning": "Deterministic register projection over a large register (2D-06)",
            "method": "whole_register",
        }

    async def _register_rows(self, cls: Any, build: Any) -> List[Dict[str, Any]]:
        """Every row of one register, one binding per record (2D-06, BUG-829)."""
        raw = await self._execute_query(build(cls, ""))
        pivoted, _cols = self._pivot_by_subject((raw or {}).get("results", {}).get("bindings", []))
        return pivoted["results"]["bindings"]

    async def _register_grouping(
        self, record: Any, user_query: str, state: ConversationState
    ) -> Optional[Dict[str, Any]]:
        """ "Which rooms have teaching sessions?" over a register too large to hand over.

        The grouping is COUNTED BY THE GRAPH — one row per distinct value — so a register of any
        size can answer it. Returns None unless the question is a grouping one and exactly one
        predicate is named by the word it groups by: grouping by the wrong column would file every
        record under a heading it does not belong to, which is worse than the fallback.
        """
        from orchestrator.services import register_projection as rp

        words = rp.grouping_words(user_query)
        if not words:
            return None
        clauses = " || ".join(
            f'CONTAINS(LCASE(STR(?p)), "{self._escape_literal(w.lower())}")' for w in words
        )
        query = (
            "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
            "SELECT ?p ?v (COUNT(DISTINCT ?record) AS ?n) WHERE {\n"
            f"  ?record a ontosage:{record.local_name} ; ?p ?v .\n"
            f"  FILTER({clauses})\n"
            "} GROUP BY ?p ?v ORDER BY DESC(?n) LIMIT 400"
        )
        try:
            raw = await self._execute_query(query)
        except Exception as exc:
            logger.warning(f"[sparql] register grouping failed: {type(exc).__name__}: {exc}")
            return None
        by_predicate: Dict[str, List[Tuple[str, int]]] = {}
        for binding in (raw or {}).get("results", {}).get("bindings", []):
            predicate = (binding.get("p") or {}).get("value", "").rsplit("#", 1)[-1]
            value = (binding.get("v") or {}).get("value", "")
            try:
                count = int((binding.get("n") or {}).get("value", "0"))
            except ValueError:
                continue
            if predicate and value:
                by_predicate.setdefault(predicate, []).append((value, count))
        if len(by_predicate) != 1:
            logger.info(
                f"[sparql] {record.local_name} grouping by {words} matched "
                f"{sorted(by_predicate)} — not exactly one field, leaving it"
            )
            return None
        pairs = next(iter(by_predicate.values()))
        text = "\n".join(
            rp.grouping_lines(
                pairs,
                record.label or record.local_name,
                rp.grouping_label(user_query),
                # the register's own size, never the sum of the groups: a record carrying the
                # field twice would be counted twice and the total would overstate the register
                record.instances,
                rp.unfiltered_periods(user_query),
            )
        )
        logger.info(
            f"[sparql] {record.local_name} grouped by {next(iter(by_predicate))}: "
            f"{len(pairs)} distinct value(s) — counted by the graph"
        )
        return {
            "success": True,
            "query": query,
            "results": {"results": {"bindings": []}},
            "error": None,
            "formatted_response": text,
            "context": [],
            "analytics_required": False,
            "llm_reasoning": "Deterministic register grouping (2D-06)",
            "method": "whole_register",
        }

    async def _record_schema_context(self, query: str) -> List[str]:
        """Schema for a record class this building HOLDS, when the question names one.

        The RAG index is embedded from the ontology as it stood when it was last built,
        so a class lifted from a document today retrieves zero entities and the generator
        writes SPARQL blind. Measured: a permit-count question returned 0 triples and then
        hung for two minutes. This adds the class and the predicates its own instances
        carry, read live, so the generator has something to write against.
        """
        try:
            from orchestrator.services.record_registry import (
                held_record_class,
                record_classes,
                schema_hint,
            )

            record = held_record_class(query, await record_classes())
            if not record:
                return []
            hint = await schema_hint(record)
            if hint:
                logger.info(f"[sparql] record-class schema injected: {record.local_name}")
            return [hint] if hint else []
        except Exception as exc:  # pragma: no cover - never block generation on this
            logger.debug(f"[sparql] record schema unavailable: {exc}")
            return []

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

                        return (await self._record_schema_context(query)) + [context_text]

                    logger.warning("GraphDB RAG returned unsuccessful status")
                    return await self._record_schema_context(query)

                except Exception as e:
                    logger.warning(f"GraphDB RAG failed: {e}")
                    return await self._record_schema_context(query)

        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")
            return await self._record_schema_context(query)

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

        # ── worked examples, from THIS building ─────────────────────────────────
        #
        # The prompt taught `room 5.01`, `CO2_Level_Sensor_5.08` and
        # `CONTAINS(STR(?sensor), "5.08")` in six places. `5.01` is not a placeholder: it
        # is a room in one building, in that building's N.NN numbering, and a model shown
        # three examples of it reaches for that shape when asked about a building
        # numbering rooms `RM-204`. The advice was CORRECT for bldg1, so nothing looked
        # wrong until somebody checked whether the room existed.
        #
        # Deleting the examples would have made the prompt worse -- the CONTAINS-filter
        # guidance is genuinely useful and hard to state abstractly -- so they are read
        # from the graph, cached per building. When none can be read the example lines are
        # OMITTED rather than defaulted: worse guidance beats wrong guidance, and a
        # fallback here would reintroduce the defect.
        _ex = None
        try:
            from orchestrator.services.prompt_exemplars import exemplars_for

            _ex = await exemplars_for(building_id or "", _bldg_namespace, self._execute_query)
        except Exception:
            _ex = None
        _ex_usable = bool(_ex is not None and _ex.usable)
        _ex_room_line = (
            f'   - "room {_ex.room_identifier}" -> {_bldg_prefix}:{_ex.room_local} '
            f'or filter CONTAINS "{_ex.room_identifier}"\n'
            if _ex_usable
            else ""
        )

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
{_ex_room_line}   - "location" → brick:hasLocation property
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

Replace {_bldg_prefix}:ENTITY_NAME with the actual URI found in the context{f" (e.g. {_bldg_prefix}:{_ex.sensor_local})" if _ex_usable else ""}.
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
   - If user asks for a specific sensor by name{f' (e.g. "{_ex.sensor_local}")' if _ex_usable else ""}, FILTER by URI or Label:
     FILTER(CONTAINS(STR(?sensor), "IDENTIFIER") || CONTAINS(STR(?label), "IDENTIFIER"))
     where IDENTIFIER is the part of the name the user actually said.
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

    def _floor_scoped_sparql(
        self,
        user_query: str,
        class_target: Optional[str],
        class_targets: Optional[List[str]] = None,
        concept_populated: Optional[bool] = None,
    ) -> Optional[str]:
        """Deterministic, building-portable floor-scoped sensor resolver.

        ``concept_populated`` is whether the graph holds instances of the resolved concept's
        classes (``_populated_classes``). True makes the concept's classes win over the static
        keyword map; False or None (unknown) keeps the keyword map first, as before.

        For queries naming one or more floors plus an inferrable metric
        ("compare temperature between floor 1 and floor 5", "average CO2 on
        floor 3"), resolve that metric's sensors per floor through the Brick
        spatial hierarchy: sensor → brick:hasLocation → (isPartOf|^hasPart)* →
        brick:Floor, or a point of equipment that feeds a location on that floor
        (BUG-667). No building-specific label parsing, so it keeps working
        after a building swap. Returns None when the query names no floor or no
        metric class can be inferred (callers fall through to the normal path).
        """
        floors = re.findall(r"\b(?:floor|level)\s*(\d+)\b", user_query, re.IGNORECASE)
        floors = sorted(set(floors), key=int)
        # EVERY FLOOR, when the question compares floors without naming one (BUG-556).
        # "Which floor used the most energy yesterday?" named no number, so this returned
        # None, the generic 'list the floors' template answered with eight floor labels and
        # no sensors, and the compare lane replied that comparison "requires sensors with
        # linked time-series data" — for a building with a meter on every floor. Only with a
        # resolved metric CLASS: a label match across the whole building is too loose.
        across_floors = False
        if not floors:
            if not (
                (self._infer_class(user_query.lower()) or class_target)
                and _ACROSS_FLOORS_RE.search(user_query)
            ):
                return None
            across_floors = True

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
        floor_filter = "" if across_floors else f"FILTER(?floorNum IN ({floor_in}))"
        # Every floor's sensors, ordered by floor — so the row limit must reach the top floor.
        row_limit = 500 if across_floors else 100
        # Build the point SELECTOR with two naming-agnostic tiers:
        #  1) Brick class (preferred) — from the keyword map or the HBCO concept.
        #  2) rdfs:label text-match on the salient query terms — works for ANY URI
        #     naming scheme (e.g. bldg:bldgx.ZONE.AHU01.RM123.Zone_Air_Temp) as long
        #     as the point is labelled (every point carries rdfs:label).
        # Either way resolution keys off class/label/location, never the URI string.
        cls, _classes, _plant_q = self._floor_scope_classes(
            user_query, class_target, class_targets, concept_populated
        )
        if len(_classes) > 1:
            type_clause = (
                "VALUES ?metricCls { " + " ".join(_classes) + " }\n"
                "  ?sensor rdf:type/rdfs:subClassOf* ?metricCls ."
            )
            label_clause = ""
            row_limit = row_limit * len(_classes)
            logger.info(f"[sparql] floor-scoped resolve: classes={_classes} floors={floors}")
        elif cls:
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
        # The `ref:` prefix WAS absent from the standard block when this was written, and is
        # in it now — so re-declaring it made GraphDB reject the whole query with "Multiple
        # prefix declarations for prefix 'ref'" (BUG-631, P1). Nothing announced that: the
        # floor-scoped template failed, the agent fell back, and the fallback took the first
        # 40 instances of the class with NO floor constraint. "What is the air quality on
        # floor 3?" was answered from sensors labelled 5.02 and 5.03 — the right class, the
        # wrong floor, stated with confidence. Ask the block what it declares instead of
        # remembering what it used to.
        _prefixes = self._prefix_block()
        if "PREFIX ref:" not in _prefixes:
            _prefixes += "\nPREFIX ref: <https://brickschema.org/schema/Brick/ref#>"
        # WB-14 keeps plant-side points out of a ROOM question on a floor. When the question
        # NAMES a plant quantity the exclusion is the opposite of what was asked — it removed
        # the one point that answers "supply air temperature on floor 3" while the composite
        # temperature concept let 49 room sensors through (BUG-667). The type clause above is
        # then the specific plant class alone, so no room sensor can satisfy it either way.
        if _plant_q:
            plant_side_filter = ""
        else:
            plant_side_filter = (
                "FILTER NOT EXISTS { ?sensor a ?plantSide .\n"
                "    VALUES ?plantSide { " + " ".join(_PLANT_SIDE_CLASSES) + " } }"
            )
        # A point belongs to a floor when it is LOCATED there, or when it is a point of
        # equipment that FEEDS a place on that floor (BUG-667). An air handler serves its floor
        # from a plant room: the graph says `AHU feeds HVAC_Zone`, `HVAC_Zone isPartOf Floor`,
        # and its outside-air damper point is `isPointOf` a damper that `isPartOf` the AHU —
        # with no location anywhere on that chain, so "the damper position on floor 3" found
        # nothing while "the damper position on AHU F3" answered from 989 readings. Asserting a
        # location on the AHU would make that work by writing something the building does not
        # say. Both relationship directions, as everywhere else in this file; `?equip` must be
        # Equipment and `?served` a Location, so a whole SYSTEM feeding a zone does not put every
        # point of every unit in it on that floor, and a boiler feeding an air handler that sits
        # on a floor does not put the boiler there either.
        #
        # `a brick:Equipment`, not `rdf:type/rdfs:subClassOf*`: measured on the live store, the
        # path form cost about a second on EVERY floor question (energy across floors 0.02 s ->
        # 1.5 s) while the direct form cost 0.1 s. The store materialises superclass types —
        # the plant fallback's `?sensor a brick:Point` already depends on that.
        floor_membership = (
            "{\n"
            "    ?sensor brick:hasLocation ?loc .\n"
            "    ?loc (brick:isPartOf|^brick:hasPart)* ?floor .\n"
            "  } UNION {\n"
            "    ?sensor (brick:isPointOf|^brick:hasPoint) ?host .\n"
            "    ?host (brick:isPartOf|^brick:hasPart)* ?equip .\n"
            "    ?equip a brick:Equipment .\n"
            "    ?equip (brick:feeds|^brick:isFedBy) ?served .\n"
            "    ?served a brick:Location .\n"
            "    ?served (brick:isPartOf|^brick:hasPart)* ?floor .\n"
            "  }"
        )
        return (
            _prefixes
            + f"""
SELECT DISTINCT ?sensor ?label ?floorNum ?uuid ?storage WHERE {{
  ?sensor rdfs:label ?label .
  {type_clause}
  {label_clause}
  {floor_membership}
  ?floor a brick:Floor .
  BIND(REPLACE(STR(?floor), "^.*[Ff]loor", "") AS ?floorNum)
  {floor_filter}
  {plant_side_filter}
  ?sensor ref:hasExternalReference ?ref .
  ?ref ref:hasTimeseriesId ?uuid .
  OPTIONAL {{ ?ref ref:storedAt ?storage }}
}} ORDER BY ?floorNum ?label LIMIT {row_limit}"""
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
        concept_class: Optional[str] = None,
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
        #
        # NOT when a concept already identified a measurand. "How many parking SPACES are
        # free?" contains a zone word and asks for a count, so this template claimed it and
        # answered 294 — the building's room count — for a question about parking
        # availability, while the sensor that answers it sat behind the resolved class.
        # A generic space count is the right answer to "how many rooms are there?" and the
        # wrong answer to any question the building's own vocabulary has already recognised
        # as being about something measurable.
        if (
            any(w in uq for w in zone_words)
            and features["wants_count"]
            and not entities
            and not concept_class
        ):
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
                    f"OPTIONAL {{ ?sensor brick:hasUnit ?unit . }} OPTIONAL {{ ?sensor qudt:hasUnit ?qunit . }} "
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
                    f"OPTIONAL {{ ?sensor rdf:type ?type . }} OPTIONAL {{ ?sensor brick:hasUnit ?unit . }} OPTIONAL {{ ?sensor qudt:hasUnit ?qunit . }} "
                    f"OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} "
                    f"OPTIONAL {{ ?sensor bldg:connstring ?uuid . }} }}"
                )
                patterns.append(
                    f"{{ ?sensor brick:isLocatedIn {ent} . OPTIONAL {{ ?sensor rdfs:label ?label . }} "
                    f"OPTIONAL {{ ?sensor rdf:type ?type . }} OPTIONAL {{ ?sensor brick:hasUnit ?unit . }} OPTIONAL {{ ?sensor qudt:hasUnit ?qunit . }} "
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
                + f"\nSELECT ?sensor (SAMPLE(?location) AS ?locationName) (SAMPLE(?uuid) AS ?uuidValue) (SAMPLE(?storage) AS ?storageRef) (SAMPLE(?unit) AS ?unitName) (SAMPLE(?qunit) AS ?qunitName) WHERE {{\n  ?sensor rdf:type {target_class} .\n  OPTIONAL {{ ?sensor brick:hasLocation ?location . }}\n  OPTIONAL {{ ?sensor brick:hasUnit ?unit . }} OPTIONAL {{ ?sensor qudt:hasUnit ?qunit . }}\n  OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }}\n  OPTIONAL {{ ?sensor bldg:connstring ?uuid . }}\n}} GROUP BY ?sensor LIMIT {_CLASS_LISTING_LIMIT}"
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
                + "\nSELECT ?sensor ?type ?location ?uuid ?storage ?unit ?qunit WHERE {\n  ?sensor rdf:type ?type .\n  FILTER(CONTAINS(STR(?type), 'Sensor') || CONTAINS(STR(?type), 'Point'))\n  OPTIONAL { ?sensor brick:hasLocation ?location . }\n  OPTIONAL { ?sensor brick:hasUnit ?unit . } OPTIONAL { ?sensor qudt:hasUnit ?qunit . }\n  OPTIONAL { ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }\n  OPTIONAL { ?sensor bldg:connstring ?uuid . }\n} LIMIT 50"
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
            # Water side (2026-09-16). "delta-T across the heating circuit" needs BOTH the
            # flow and the return, so it resolves to their common parent and the TBox rollup
            # brings back each generator's pair; a building that types only one of them still
            # resolves. Without this the question reached the document lane and was declined
            # while eight water temperatures sat on the boilers, chiller and heat pump.
            "delta-t": "brick:Water_Temperature_Sensor",
            "delta t": "brick:Water_Temperature_Sensor",
            "water temperature": "brick:Water_Temperature_Sensor",
            "flow temperature": "brick:Leaving_Water_Temperature_Sensor",
            "return temperature": "brick:Entering_Water_Temperature_Sensor",
            "leaving water": "brick:Leaving_Water_Temperature_Sensor",
            "entering water": "brick:Entering_Water_Temperature_Sensor",
            "heating circuit": "brick:Water_Temperature_Sensor",
            "chilled circuit": "brick:Water_Temperature_Sensor",
            "heating loop": "brick:Water_Temperature_Sensor",
            "chilled loop": "brick:Water_Temperature_Sensor",
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
        # Acoustic questions resolve to the OCBV class, never to a class in ONE BUILDING'S
        # namespace (design contract 3). These entries used to be `<building prefix>:
        # Noise_Level_Sensor` — one instance in bldg1 — while 233 points were typed
        # ontosage:Sound_Level_Sensor, so "noise on floor 4" found none of the 52 on that
        # floor. `vibration` is deliberately NOT mapped: Brick has no vibration point class
        # and the schema declares none, so the naming-agnostic label tier owns it rather than
        # a class name that exists in one building only.
        static_map["noise"] = "ontosage:Sound_Level_Sensor"
        static_map["sound"] = "ontosage:Sound_Level_Sensor"
        static_map["acoustic"] = "ontosage:Sound_Level_Sensor"
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

    @classmethod
    def _plant_quantity_class(cls, uq: str) -> Optional[str]:
        """The plant-side class a question NAMES, or None (BUG-667).

        Two sources, neither a keyword list of its own: the equipment-scope modalities in
        config (`_infer_plant_class`), then the plant-side Brick classes by their own NAMES
        ("Return_Air_Temperature_Sensor" -> "return air temperature"). The second catches the
        classes config does not declare a modality for, and it is derived from the class, so
        adding a class to `_PLANT_SIDE_CLASSES` adds its phrase. Longest phrase wins.
        """
        plant = cls._infer_plant_class(uq)
        if plant:
            return plant
        best: Optional[Tuple[int, str]] = None
        for brick_class in _PLANT_SIDE_CLASSES:
            phrase = brick_class.split(":", 1)[-1]
            phrase = re.sub(r"_Sensor$", "", phrase).replace("_", " ").lower()
            if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", uq):
                if best is None or len(phrase) > best[0]:
                    best = (len(phrase), brick_class)
        return best[1] if best else None

    @staticmethod
    def _plant_family(plant_class: str) -> Set[str]:
        """Every class config groups with this plant class in ONE equipment modality.

        `damper_position` is `Damper_Position_Sensor` AND `Damper_Position_Command`; a concept
        naming both is naming one quantity, and keeping both is not a substitution. A class no
        equipment modality declares is its own family.
        """
        family = {plant_class}
        try:
            from orchestrator.services.deliberation.coverage_audit import (
                load_modality_raw,
            )

            raw = load_modality_raw() or {}
        except Exception:  # pragma: no cover - defensive, config is optional
            return family
        local = plant_class.split(":", 1)[-1]
        for spec in raw.values():
            spec = spec or {}
            sat = spec.get("sat") or {}
            if str(sat.get("scope", "room")).lower() != "equipment":
                continue
            members = {str(c) for c in (spec.get("brick_classes") or [])}
            if sat.get("brick_class"):
                members.add(str(sat["brick_class"]))
            if local in members:
                family.update(f"brick:{m}" for m in members)
        return family

    def _floor_scope_classes(
        self,
        user_query: str,
        class_target: Optional[str],
        class_targets: Optional[List[str]] = None,
        concept_populated: Optional[bool] = None,
    ) -> Tuple[Optional[str], List[str], Optional[str]]:
        """(class, classes, plant class) the floor-scoped resolver selects points by.

        `classes` is empty for the label tier. `plant class` is set only when the question
        names a plant-side quantity, and then it is the ONLY kind of class selected.

        Precedence: a named plant quantity; then the resolved CONCEPT, when the graph shows
        its classes have instances; then the static keyword map; then the label tier.
        """
        uq = user_query.lower()
        # THE CONCEPT OUTRANKS THE KEYWORD MAP when the building holds its classes. The map
        # is a hand-written English table; the concept is the building's own vocabulary
        # resolved against its own graph. Ranked the other way, "noise on floor 4" selected
        # the map's building-namespace Noise_Level_Sensor (one instance in the building) and
        # never saw the 52 ontosage:Sound_Level_Sensor points on that floor. When the
        # concept's classes have NO instances, or that could not be checked, the map stays
        # first — a concept naming a class nobody typed is no better than a keyword.
        concept_wins = bool(concept_populated and class_targets and class_target)
        cls = (class_target if concept_wins else self._infer_class(uq)) or class_target
        # BUG-586: "a report on the temperature AND CO2 on floor 2" resolved one class, so the
        # report said "CO2 measurements were not included in the supplied dataset". A question
        # that joins two measurands gets both.
        classes = self._infer_classes(uq) if cls else []
        # MOST SPECIFIC DECLARING CLASS WINS (BUG-609), and a plant quantity is more specific
        # than any room concept that happens to share its noun. "What is the supply air
        # temperature on floor 3?" resolves the temperature CONCEPT — Temperature_Sensor,
        # Zone_Air_Temperature_Sensor, Outside_Air_Temperature_Sensor — and the composite rule
        # below replaced the supply-air class with all three, so it answered 24.1 °C from
        # "Air Temperature Sensor installed-node 3.66", a room sensor (BUG-667). A concept class
        # is kept beside the plant class only when config puts both in the same equipment
        # modality; if the floor has no point of that kind the result is an honest absence,
        # never the room sensors.
        plant = self._plant_quantity_class(uq)
        if plant:
            family = self._plant_family(plant)
            kept = [c for c in (class_targets or []) if c in family and c != plant]
            classes = list(dict.fromkeys([plant] + kept))
            if class_targets and set(class_targets) - set(classes):
                logger.info(
                    f"[sparql] plant quantity {plant} named: concept classes "
                    f"{sorted(set(class_targets) - set(classes))} not substituted"
                )
            return plant, classes, plant
        if concept_wins and len(classes) <= 1:
            # Every class the concept resolved to, as the composite rule below would take
            # them. Two JOINED measurands (BUG-586) still come from the question, because the
            # dialogue hands over the first concept only.
            classes = list(dict.fromkeys(class_targets or [])) or [cls]
            logger.info(f"[sparql] populated concept outranks the keyword map: {classes}")
            return cls, classes, None
        # A COMPOSITE concept names several constituents on purpose — "air quality" is CO2
        # AND PM2.5 AND TVOC AND the generic air-quality point — and picking the most
        # specific one answered with an opaque "level" instead of the pollutants a person
        # means (BUG-632). Most-specific is the right rule for a concept naming a class and
        # its PARENT (the parking case it was written for) and the wrong one here.
        if len(classes) <= 1 and class_targets and len(class_targets) > 1:
            classes = list(dict.fromkeys(class_targets))
            logger.info(f"[sparql] composite concept contributes {len(classes)} classes")
        return cls, classes, None

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

    _JOINED_RE = re.compile(r"\band\b|,|&|\bplus\b|\bas well as\b", re.IGNORECASE)

    def _infer_classes(self, uq: str) -> List[str]:
        """Every measurand class a question JOINS ("temperature and CO2"), in question order.

        One class unless the question joins terms, so a single-measurand question is
        resolved exactly as `_infer_class` resolves it. Plant classes stay single.
        """
        first = self._infer_class(uq)
        if not first or self._infer_plant_class(uq) or not self._JOINED_RE.search(uq):
            return [first] if first else []
        spans: List[Tuple[int, int, str]] = []
        for k, v in self._get_extended_class_map().items():
            m = re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", uq)
            if m:
                spans.append((m.start(), m.end(), v))
        # "air temperature" also contains "temperature": a term inside a longer matched term
        # is the same measurand, not a second one.
        hits = [
            (s, v)
            for s, e, v in spans
            if not any(s2 <= s and e <= e2 and (e2 - s2) > (e - s) for s2, e2, _ in spans)
        ]
        ordered: List[str] = []
        for _, v in sorted(hits):
            if v not in ordered:
                ordered.append(v)
        return ordered or [first]

    @staticmethod
    def _most_specific_class(
        candidates: List[str],
        ancestors: Optional[Dict[str, Set[str]]] = None,
        instances: Optional[Dict[str, int]] = None,
    ) -> str:
        """The most specific of a concept's classes. Pure: the graph facts are ARGUMENTS.

        A concept may legitimately name a class AND its parent — the parent so a
        building that types only the generic form still resolves, the child so a
        building that types precisely gets a precise answer. Which one the store
        returns first is arbitrary, so the choice cannot be made on order.

        ``ancestors`` maps each candidate to the OTHER candidates it is a subclass of,
        read from the TBox by ``_class_relations``; ``instances`` is how many instances
        of each the building holds. With them (BUG-609's rule, "most specific declaring
        class wins"):

          1. a candidate that is an ancestor of another candidate is never chosen — the
             descendant is more specific along that chain;
          2. when several incomparable candidates remain, none of them is "more specific"
             than the others. The concept named siblings, so the question is at the level
             of a candidate that COVERS all of them, and the deepest such candidate wins.
             `temperature_reading` names Temperature_Sensor, Zone_Air_Temperature_Sensor
             and Outside_Air_Temperature_Sensor: the two leaves tie on depth, and on bldg1
             one of them holds 66 instances and the other 1 while the room sensors (288)
             are typed as neither — so the parent is the only honest pick;
          3. with no covering candidate, the leaf the building actually has instances of
             wins, most instances first — never a class with none. Pure depth would pick
             Damper_Position_Command (depth 8, no instances) over Damper_Position_Sensor
             (depth 7, six instances);
          4. then an OCBV (``ontosage:``/``hbco:``) class, then the concept's own order.

        WITHOUT them (graph unreachable, or a caller that has none) the old rule stands:
        an OCBV class exists PRECISELY BECAUSE Brick lacked one and is declared a subclass
        of the nearest Brick parent, so it wins; otherwise the first candidate. The
        concept resolver SORTS its classes, so that first candidate is alphabetical — which
        made every "temperature" concept target Outside_Air_Temperature_Sensor, one
        instance in bldg1. That fallback is logged where the facts failed to arrive.

        The first version asked the graph FROM HERE, and always fell back: `_execute_query`
        raised `[Errno -2] Name or service not known` from its Fuseki fallback, the
        `except` swallowed it at DEBUG level, and the function silently returned
        `candidates[0]` — which is why "how many parking spaces are free?" kept
        answering 294 (the building's space count) from the generic parent class,
        through three rounds of me "verifying" a fix that had never once run. So the
        query lives in the caller and this stays unable to fail on a network call.
        """
        uniq = list(dict.fromkeys(c for c in candidates if c))
        if not uniq:
            return ""
        if len(uniq) == 1:
            return uniq[0]

        def _extension(c: str) -> bool:
            return c.startswith("ontosage:") or c.startswith("hbco:")

        if ancestors is None:
            for cand in uniq:
                if _extension(cand):
                    return cand
            return uniq[0]

        def _is_ancestor(a: str, b: str) -> bool:
            return a != b and a in (ancestors.get(b) or set())

        leaves = [c for c in uniq if not any(_is_ancestor(c, o) for o in uniq)]
        if len(leaves) == 1:
            return leaves[0]
        covering = [
            c for c in uniq if c not in leaves and all(_is_ancestor(c, lf) for lf in leaves)
        ]
        if covering:
            # The deepest cover: the one no other cover is a descendant of.
            deepest = [c for c in covering if not any(_is_ancestor(c, o) for o in covering)]
            return deepest[0]
        counts = instances or {}
        order = {c: i for i, c in enumerate(uniq)}
        return sorted(
            leaves,
            key=lambda c: (
                -(1 if counts.get(c, 0) > 0 else 0),
                -counts.get(c, 0),
                0 if _extension(c) else 1,
                order[c],
            ),
        )[0]

    def _expand_class_curies(self, classes: List[str]) -> Optional[Dict[str, str]]:
        """{curie: full IRI} via the prefix block, or None if any class cannot be expanded.

        The local name must be a plain name, so nothing a concept carries can inject SPARQL.
        """
        prefixes: Dict[str, str] = {}
        for line in self._prefix_block().splitlines():
            m = re.match(r"\s*PREFIX\s+([\w-]*):\s*<([^>]+)>", line)
            if m:
                prefixes[m.group(1)] = m.group(2)
        iris: Dict[str, str] = {}
        for curie in classes:
            if curie.startswith("http://") or curie.startswith("https://"):
                if re.search(r"[\s<>\"{}|\\^`]", curie):
                    return None
                iris[curie] = curie
                continue
            pfx, _, local = curie.partition(":")
            if not local or pfx not in prefixes or not re.fullmatch(r"[\w.\-]+", local):
                return None
            iris[curie] = prefixes[pfx] + local
        return iris

    async def _populated_classes(self, classes: List[str]) -> Optional[Set[str]]:
        """Which of these classes have at least one instance in the ACTIVE building, or None.

        None means the graph could not say, and is logged at WARNING: the caller then keeps
        its previous ranking rather than guessing in either direction. An existence test per
        class (FILTER EXISTS), not a COUNT — the answer needed is yes/no. Cached per building
        for the process, like `_class_relations`; data loads come with a restart here.
        """
        uniq = sorted({c for c in classes if c})
        if not uniq:
            return set()
        iris = self._expand_class_curies(uniq)
        if iris is None:
            logger.warning(f"[sparql] class population: cannot expand {uniq}")
            return None
        namespace = _active_namespace()
        cache = self.__dict__.setdefault("_populated_class_cache", {})
        key = (namespace, tuple(uniq))
        if key in cache:
            return cache[key]
        back = {v: k for k, v in iris.items()}
        values = " ".join(f"<{v}>" for v in iris.values())
        scope = (
            f'    FILTER(STRSTARTS(STR(?i), "{self._escape_literal(namespace)}"))\n'
            if namespace
            else ""
        )
        query = (
            "SELECT DISTINCT ?c WHERE {\n"
            f"  VALUES ?c {{ {values} }}\n"
            "  FILTER EXISTS {\n"
            "    ?i a ?c .\n" + scope + "  }\n"
            "} LIMIT 1000"
        )
        try:
            data = await self._execute_query(query)
        except Exception as exc:
            logger.warning(
                f"[sparql] class population: graph unavailable ({type(exc).__name__}: {exc}) "
                f"for {uniq}"
            )
            return None
        held = {
            back[v]
            for b in (data or {}).get("results", {}).get("bindings", [])
            for v in [(b.get("c") or {}).get("value", "")]
            if v in back
        }
        cache[key] = held
        return held

    async def _class_relations(
        self, candidates: List[str]
    ) -> Tuple[Optional[Dict[str, Set[str]]], Optional[Dict[str, int]]]:
        """Which candidates subsume which, and how many instances each has — from the graph.

        Returns (None, None) when the graph cannot say, and says so at WARNING: a silent
        fallback here is exactly how the parking fix "worked" for three rounds without
        once running. Cached per building for the process; the TBox does not change
        between questions, and a new instance does not change which class is specific.
        """
        uniq = sorted({c for c in candidates if c})
        if len(uniq) < 2:
            return None, None
        iris = self._expand_class_curies(uniq)
        if iris is None:
            logger.warning(f"[sparql] class specificity: cannot expand {uniq} — order fallback")
            return None, None
        back = {v: k for k, v in iris.items()}
        cache = self.__dict__.setdefault("_class_relation_cache", {})
        key = (_active_namespace(), tuple(uniq))
        if key in cache:
            return cache[key]
        values = " ".join(f"<{v}>" for v in iris.values())
        sub_q = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?c ?anc WHERE {\n"
            f"  VALUES ?c {{ {values} }}\n"
            f"  VALUES ?anc {{ {values} }}\n"
            "  ?c rdfs:subClassOf+ ?anc .\n"
            "  FILTER(?c != ?anc)\n"
            "} LIMIT 1000"
        )
        count_q = (
            "SELECT ?c (COUNT(DISTINCT ?i) AS ?n) WHERE {\n"
            f"  VALUES ?c {{ {values} }}\n"
            "  ?i a ?c .\n"
            "} GROUP BY ?c LIMIT 1000"
        )
        try:
            sub = await self._execute_query(sub_q)
            ancestors: Dict[str, Set[str]] = {c: set() for c in uniq}
            for b in (sub or {}).get("results", {}).get("bindings", []):
                c = back.get((b.get("c") or {}).get("value", ""))
                a = back.get((b.get("anc") or {}).get("value", ""))
                if c and a:
                    ancestors[c].add(a)
            # Instances matter only when the hierarchy leaves the choice open — incomparable
            # leaves with no candidate covering them — so the count is not paid otherwise.
            leaves = [c for c in uniq if not any(c in ancestors[o] for o in uniq if o != c)]
            open_choice = len(leaves) > 1 and not any(
                c not in leaves and all(c in ancestors[lf] for lf in leaves) for c in uniq
            )
            cnt = await self._execute_query(count_q) if open_choice else {}
        except Exception as exc:
            logger.warning(
                f"[sparql] class specificity: graph unavailable ({type(exc).__name__}: {exc}) "
                f"— falling back to concept order for {uniq}"
            )
            return None, None
        instances: Dict[str, int] = {}
        for b in (cnt or {}).get("results", {}).get("bindings", []):
            c = back.get((b.get("c") or {}).get("value", ""))
            if c:
                try:
                    instances[c] = int(float((b.get("n") or {}).get("value", "0")))
                except ValueError:
                    continue
        cache[key] = (ancestors, instances)
        return ancestors, instances

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

    #: A floor named as an entity: "Floor_3", "floor 3", "Level 2", "storey 4". A ROOM
    #: identifier ("2.01") is deliberately unmatched — a dotted number is a space, not a floor,
    #: and the existing label path resolves those correctly.
    _FLOOR_ENTITY_RE = re.compile(r"^\W*(?:floor|level|storey)[\s_\-]*(\d+)\W*$", re.IGNORECASE)

    #: How many of a floor's points of one quantity to take. A floor here has 48-56 sensors per
    #: modality; the cap is a guard against a pathological building, not a sample.
    _FLOOR_POINT_CAP = 200

    async def _resolve_floor_structurally(
        self,
        name: str,
        user_query: str,
        bldg_ns: str,
        limit: int,
        class_hints: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """Points located ON a named floor, through the graph's own structure — or [].

        Returns [] for anything that is not a floor name and whenever the traversal finds
        nothing, so every other entity and every building that models floors differently falls
        through to the label path exactly as before.

        BUILDING-AGNOSTIC: the floor is matched by its own label or IRI in the ACTIVE namespace,
        and both location idioms are covered (`brick:hasLocation` directly, and `brick:isPointOf`
        an equipment sited in the space) — the same pair `coverage_audit` has always used,
        because a building that models one and not the other is common.
        """
        m = self._FLOOR_ENTITY_RE.match(str(name or ""))
        if not m:
            return []
        # THE QUANTITY MUST BE KNOWN, OR THIS MUST NOT ACT.
        #
        # A floor holds hundreds of points, and narrowing them by the QUESTION's words is the
        # bug one layer down: every candidate is already on that floor, so the words "floor 3"
        # are noise that scores `Floor3_General_Waste_Bin_Fill` above every temperature sensor
        # in forty-eight rooms. Measured exactly that on the first attempt -- floor 3 bound four
        # WASTE BINS for "will floor 3 be warmer than floor 4", and the narration compared them
        # with floor 4's temperatures as though both were degrees.
        #
        # So the filter is the resolved Brick class, not the prose. With no class resolved this
        # returns [] and the label path runs unchanged: binding eight arbitrary points off a
        # floor would be worse than the behaviour this replaces, not better.
        classes = [str(c) for c in (class_hints or []) if str(c).strip()]
        if not classes:
            return []
        digits = m.group(1)
        values = " ".join(c if ":" in c else f"brick:{c}" for c in classes[:8])
        query = f"""{self._prefix_block()}
SELECT DISTINCT ?s WHERE {{
  VALUES ?cls {{ {values} }}
  ?floor a brick:Floor .
  OPTIONAL {{ ?floor rdfs:label ?fl }}
  BIND(LCASE(CONCAT(STR(?floor), " ", COALESCE(STR(?fl), ""))) AS ?fhay)
  FILTER(CONTAINS(?fhay, "floor_{digits}") || CONTAINS(?fhay, "floor {digits}")
      || CONTAINS(?fhay, "level_{digits}") || CONTAINS(?fhay, "level {digits}"))
  ?space brick:isPartOf ?floor .
  {{ ?s brick:hasLocation ?space }} UNION {{ ?s brick:isPointOf ?e . ?e brick:hasLocation ?space }}
  ?s a ?cls ; ref:hasExternalReference ?r .
  FILTER(STRSTARTS(STR(?s), '{bldg_ns}'))
}} LIMIT 400"""
        try:
            hits = await self._select_subjects(query, bldg_ns, _active_prefix())
        except Exception as exc:  # pragma: no cover - the label path still answers
            logger.warning(f"[sparql] structural floor resolution skipped: {exc}")
            return []
        if not hits:
            return []
        logger.info(
            f"[sparql] '{name}' resolved STRUCTURALLY to {len(hits)} point(s) of "
            f"{classes[:3]} on that floor, taking {min(len(hits), limit)}"
        )
        return hits[:limit]

    async def _resolve_entities_by_label(
        self,
        names: List[str],
        limit: int = 8,
        user_query: str = "",
        ts_bearing: Optional[Set[str]] = None,
        class_hints: Optional[Sequence[str]] = None,
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
        structural_found = False

        for name in names:
            # A FLOOR IS A PLACE, NOT A NAME (BUG-884).
            #
            # Matching a floor by text finds what is NAMED for it, not what is ON it. Measured
            # 2026-09-23: "Will floor 3 be warmer than floor 4 tomorrow?" resolved to
            # ['Access_Reader_F3_Entrance', 'Entry_Count_Sensor_F3', 'HVAC_Meter_F3',
            # 'Lighting_Meter_F3', ...] -- eight floor-3 METERS, nothing at all from floor 4,
            # and not one temperature sensor. The same shape answered "No readings were found
            # for Floor_2" for pack #27.
            #
            # The graph already holds the structure: floor -> spaces -> points, through the two
            # location idioms the coverage audit has always covered. Asked structurally, floor 3
            # yields 96 temperature sensors across 48 spaces.
            structural = await self._resolve_floor_structurally(
                name, user_query, bldg_ns, self._FLOOR_POINT_CAP, class_hints
            )
            if structural:
                # A FLOOR'S MEAN IS NOT EIGHT OF ITS ROOMS. The default limit exists to stop a
                # unit name dragging in every point on an AHU; a floor entity is the opposite
                # case -- the question is ABOUT all of them, and `resolved[:limit]` with the
                # default 8 both averaged a sixth of floor 3 and dropped floor 4 entirely from a
                # comparison whose answer still quoted floor-4 numbers.
                structural_found = True
                resolved.extend(h for h in structural if h not in resolved)
                ts_bearing.update(structural)
                continue
            # A dotted identifier stays WHOLE and digits are never dropped (WB-10). Splitting
            # "Room_2.01" on non-alphanumerics gave room/2/01, the length filter discarded "2",
            # and CONTAINS("room") && CONTAINS("01") resolved room 2.01 to Room5.01's sensor —
            # a reading from another floor presented for the room asked about.
            tokens = [
                t
                for t in re.findall(r"\d+(?:\.\d+)+|[a-z]+|\d+", str(name).lower())
                if (len(t) > 1 or t.isdigit()) and t not in self._LABEL_STOPWORDS
            ]
            # With an identifier present, "room"/"zone"/"space" are not required: points are
            # named "CO2 Level Sensor installed-node 2.01", so requiring "room" found only the
            # simulated Room2.01_* points and no CO2 sensor at all. Narrowing by the question's
            # own words still picks the measurement asked for.
            if any(re.fullmatch(r"\d+(?:\.\d+)+", t) for t in tokens):
                tokens = [t for t in tokens if t not in _LOCATION_HEAD_WORDS] or tokens
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

        cap = max(limit, self._FLOOR_POINT_CAP * len(names)) if structural_found else limit
        if resolved:
            logger.info(
                f"[sparql] resolved {names} → {len(resolved[:cap])} point(s), "
                f"e.g. {resolved[:4]}"
            )
        return resolved[:cap]

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
        # THE RETURN. It was missing (BUG-476).
        #
        # This function is annotated `-> Dict[str, Any]`, builds the dict, fills it from
        # the bindings and then fell off the end — returning None on every call, on every
        # path, since it was written. Everything downstream reads it defensively
        # (`.get("standardized", {})`), so nothing ever raised: the planner's
        # `_extract_uuids`, `_extract_storage_map` and `_extract_sensor_metadata` simply
        # returned empty every time.
        #
        # `_run_sql` then took its `else` branch — no UUIDs, so let the LLM write the SQL
        # — and the LLM, given a room named "5.01" and no sensor id, wrote
        # `WHERE uuid = '5.01'`. Zero rows, and a report that told the reader their room
        # had no CO2 sensor and recommended installing one, for a room whose readings run
        # to 77,088 rows a day.
        return standardized

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
                    logger.warning(
                        f"GraphDB query failed: {type(e).__name__}: {e}, trying Fuseki fallback"
                    )

                    # Fallback to Fuseki if GraphDB fails. When Fuseki is not deployed (the
                    # compose service is commented out) its DNS error REPLACED GraphDB's, so a
                    # 30 s GraphDB timeout was reported as "Name or service not known" and
                    # the cause was invisible (BUG-544). The GraphDB error is the one to keep.
                    try:
                        response = await client.post(
                            FUSEKI_QUERY_ENDPOINT,
                            data={"query": sparql},
                            headers={"Accept": "application/sparql-results+json"},
                        )
                        response.raise_for_status()
                    except httpx.HTTPError as fuseki_err:
                        logger.debug(f"Fuseki fallback unavailable: {fuseki_err}")
                        raise e

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
            # The type, because a timeout's message is the EMPTY string (CAVEAT-415).
            logger.error(f"SPARQL query error: {type(e).__name__}: {e}")
            raise Exception(f"Failed to execute SPARQL query: {type(e).__name__}: {e}")

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
        #
        # TWO CHEAP STAGES, never one unbounded scan. This used to be a single
        # query over `?sensor ?p ?o` with a string FILTER — i.e. every triple in
        # the store — plus two OPTIONAL joins. When the token MATCHED something
        # the LIMIT 50 cut it short and it looked fine; when the token matched
        # NOTHING there was nothing to cut it short and it read the whole store.
        # That is the case that actually happens, because this fallback only runs
        # after the class query returned zero — the LLM had invented a class.
        # Measured live 2026-08-25 on a 19.4M-triple store: 29.98s per attempt,
        # three self-correction attempts, and the 120s workflow budget gone, so
        # "how many parking bays are free right now?" returned "your request took
        # too long" while the sensor that answers it sat one 0.06s query away.
        #
        # Anchoring on `a brick:Point` bounds the scan to the building's points
        # (0.56s for the same zero-match token, 49x faster) and moving the
        # OPTIONALs into a second VALUES-bound query keeps the hot path cheap —
        # measured, the OPTIONAL joins cost more than the scan they rode on.
        ns = _active_namespace()
        probe_query = (
            self._prefix_block()
            + f"""
SELECT DISTINCT ?sensor WHERE {{
    ?sensor a brick:Point .
    FILTER(STRSTARTS(STR(?sensor), '{ns}') && CONTAINS(STR(?sensor), '{token}_Sensor'){loc_filter})
}} LIMIT 50"""
        )
        alt_query = probe_query

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
                bindings = data.get("results", {}).get("bindings", [])
                count = len(bindings)
                if count > 0:
                    logger.info(f"✅ Pattern fallback succeeded: {count} results")
                    # Stage 2: attach location/uuid for the handful of subjects
                    # stage 1 found. Bound by VALUES, so this cannot degrade into
                    # a scan however large the store grows. Enrichment is a
                    # best-effort improvement on an answer we already have — if it
                    # fails, the caller still gets the sensors.
                    iris = [
                        b["sensor"]["value"] for b in bindings if b.get("sensor", {}).get("value")
                    ]
                    if iris:
                        values = " ".join(f"<{iri}>" for iri in iris)
                        enrich_query = (
                            self._prefix_block()
                            + f"""
SELECT DISTINCT ?sensor ?location ?uuid WHERE {{
    VALUES ?sensor {{ {values} }}
    OPTIONAL {{ ?sensor brick:hasLocation ?location . }}
    OPTIONAL {{ ?sensor ref:hasExternalReference [ ref:hasTimeseriesId ?uuid ] . }}
}}"""
                        )
                        try:
                            enriched = await client.post(
                                endpoint,
                                auth=auth,
                                data={"query": enrich_query},
                                headers={"Accept": "application/sparql-results+json"},
                            )
                            if enriched.status_code == 200:
                                e_data = enriched.json()
                                if e_data.get("results", {}).get("bindings"):
                                    return e_data
                        except Exception as e:
                            logger.warning(f"Pattern fallback enrichment failed: {e}")
                    return data
        except Exception as e:
            logger.warning(f"Pattern fallback failed: {e}")

        return None

    async def _format_results(
        self,
        results: Dict[str, Any],
        user_query: str,
        sparql_query: str,
        used_template: bool,
        row_limit: Optional[int] = None,
    ) -> str:
        """Format SPARQL results into natural language.

        ``row_limit`` overrides the default cap on how many rows reach the prompt. The
        deterministic register handover passes one, because its whole purpose is that the
        model sees the WHOLE register — and it was not.
        """

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

        # A design note about how a register is MODELLED is not an answer about the
        # building (rows 139/146). Withheld here, before the rows become either the
        # narration prompt or the deterministic fallback, so neither path can quote one.
        bindings, _withheld = redact_schema_documentation(bindings)
        if _withheld:
            logger.info(
                f"[sparql] withheld {_withheld} schema-documentation literal(s) from the answer"
            )

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

        # Special formatting for building name query.
        #
        # THREE GUARDS, and it had none of them. `"name" in uq` matched the word "names",
        # and the template then took bindings[0]'s label WHATEVER the query was about --
        # measured live, "where do waste stream NAMES and labels conflict within a station?"
        # answered "The building name is: **Reception mixed recycling**", naming a waste bin
        # as the building. A confident false statement about the building's own identity is
        # the worst shape of wrong answer this system can produce, and it is exactly what
        # contract 4 forbids.
        #
        # So: whole words, not substrings; and a single binding, because a building-name
        # answer is one row by definition and a multi-row result is a different question
        # that happens to share two words.
        _asks_building_name = bool(
            re.search(r"\bbuilding\b", uq) and re.search(r"\b(name|named|called)\b", uq)
        )
        if _asks_building_name and len(bindings) == 1:
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
        # Cap at 100 to prevent context window overflow.
        #
        # AN EXPLICIT row_limit WINS (BUG-434). The whole-register handover exists so the
        # model sees every record and can count, filter and group them — and this capped it
        # at TEN unless the question happened to contain "all", "list", "full",
        # "everything" or "complete". Measured consequences: "which departments have no
        # out-of-hours route?" answered 7 one run and 8 another from a 20-row register, and
        # a merged two-register handover reported the second register "isn't included in
        # the snippet you posted" because its rows sat at positions 29 to 49.
        #
        # The register path is already bounded by MAX_RECORD_CELLS, so the context-window
        # protection this cap provides is done there, in the right unit, before the query.
        limit = row_limit if row_limit is not None else (100 if show_all else 10)

        # The register handover hoists values every row of a register shares (BUG-546), and
        # is sized by `_render_rows` too — so the budget and the prompt measure one text.
        result_text += self._render_rows(bindings[:limit], hoist=row_limit is not None)
        count_note = self._count_meaning(sparql_query)
        if count_note:
            result_text = count_note + "\n\n" + result_text

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
- A COUNT OF SENSORS describes how a space is instrumented, nothing else (BUG-602). Never use it
  as evidence of occupancy, demand, emptiness, busyness, fragility, importance or any other
  property of how a space is used. If the question asks for such a property and the results
  hold only counts or lists, say the results do not record it and stop
- Never describe the results as data the user "provided", "supplied" or "pulled back": they
  are the building's records
- A FIELD IS EVIDENCE OF ITSELF AND NOTHING ELSE (BUG-709, 17 answers measured 2026-09-17).
  Questions ask whether something is orphaned, adequate, justified, stable, viable, verified,
  compliant, suitable, at risk or complete. Report such a judgement ONLY when a field records
  it. If no field does, say which field would have recorded it and stop — do not reason your
  way to a verdict from the fields that are present. Measured failures to avoid: "each record
  has a mapped opening and a granted role, so none lack evidence of ownership or purpose"
  (the question asked which are orphaned); "assets list probable containment features that
  would limit damage from a leak" (no field records containment)
- A MISSING FIELD MEANS UNKNOWN, NEVER SATISFACTORY. "No evidence reference recorded" is not
  "no evidence needed", an empty exception field is not "no exception", and a record with
  nothing in a column is not a record that passed
- A STATUS DESCRIBES THE RECORD, NOT THE WORLD. A record whose status is "current" says the
  RECORD is current; it does not say the equipment works, the test passed or the activity
  happened. Say which of the two you are reporting
- DO NOT INVENT A CATEGORY. If you group records under a heading the records do not use
  ("displaced activities", "late-stopping systems"), say in the same sentence which field you
  grouped on and what value you treated as meaning that
- TWO THINGS ARE THE SAME ONLY IF A FIELD SAYS SO. When the question names something no record
  names, say that no record records it — do not nominate the nearest-looking record as it. An
  escorted contractor's one-off lab permit is not a new starter's permission package; a chiller
  handover is not an event-space handover; an inspection interval is not a sampling rate
- NEVER ISSUE AN INSTRUCTION, A PLAN, A RECOVERY ORDER OR A PRIORITY unless a field records it.
  Report what the records state and stop. A recorded threshold, limit or target is the level at
  which something is TRIGGERED, never a level anyone should bring a value up to; a recorded
  role's task is not the reader's task; the order records appear in is not an order of work
- NAME A FIELD IN PLAIN WORDS AND A RECORD BY ITS OWN NAME. Write "the recorded state", "a
  response target in hours" or "the capital value band" — never a field's internal name, in
  backticks or otherwise, and never relabel a field as the thing the question asked for.
  Identify a record by its own name and reference, not by a place or a system named in one of
  its other fields
- THE RECORDED FACTS BLOCK IS YOUR WORKING-OUT, NOT TEXT TO COPY. It is written to you, not to
  the reader. Never quote it, never repeat its phrasing ("recorded, in …", "no field is named
  for it", "does not appear as a field name or value"), and never put one of its field names in
  your answer. Write an ordinary answer about the building instead, and let the block decide
  what may be in it
- YOUR SENTENCES MUST AGREE WITH THE COMPUTED NUMBERS. Restate a count, a split or a list from
  the facts block verbatim rather than working it out again in prose: if the block says a group
  holds 9 records, the sentence says 9 and the table has 9 rows, and every record named in that
  group appears. Measured failures: "high — 9 assets" above a table of 8, with two assets in no
  table at all; "a summary of the 12 records" above 9 rows
- ONE RECORD, ONE CATEGORY, AND A HEADING IS A FILTER. A record belongs to exactly one value of
  the field you group by — never list the same record under two kinds — and a heading that
  names a status or a kind may contain ONLY the records the block lists under it. Measured
  failures: three workspaces filed under two kinds each, 31 placements for 28 records; a table
  headed "routes that are open" containing a restricted route and a closed one
- NEVER WRITE AN ABSENCE BESIDE THE ROWS THAT ANSWER IT. Before saying the records do not cover
  something, check what you have already shown: if your own answer lists records bearing on it,
  that absence sentence is false and it is the worst thing on the page. Measured failures: "the
  register does not record whether the building is pushchair-friendly from the car park", above
  its own three step-free routes from the drop-off; "no continuity information is available for
  a communications room", four lines under a row reading "secondary comms room"; "the register
  does not record any open actions", over five records the same answer lists as requiring a
  decision
- A WORD THE RECORDS DO NOT HOLD IS NOT A QUESTION YOU CANNOT ANSWER. Most questions name
  several things and the records hold some of them. Answer from the ones they hold FIRST, name
  the records, and give the unrecorded part one clause at the end. Measured failure to avoid:
  "Who do I contact about a broken door closer, and how quickly should they respond?" answered
  in full with "The records do not record a specific department responsible for broken door
  closers; they do record contactEmail, contactPhone, and respondsWithinHours for each
  department" — from a register in which one department's recorded scope covers doors and its
  recorded response target is 24 hours. Saying only what is missing, in internal field names,
  is the worst available answer. Never end on what is absent when something was found

Generate your response now:"""

        if used_template:
            # For template queries, always use LLM formatting for better UX
            try:
                # BUG-618: when a register narration fails, the FIRST question is how big the
                # prompt was. It was guesswork twice; now it is in the log either way.
                logger.info(
                    f"[sparql] narration prompt: {len(summary_prompt)} chars, "
                    f"{len(bindings)} rows"
                )
                summary = await llm_manager.generate(summary_prompt, task_type=TaskType.GENERAL)
                return summary.strip()
            except Exception as e:
                logger.warning(f"LLM formatting failed, using structured fallback: {e}")
                if row_limit is not None:
                    # A register handover the model could not summarise. The raw rows were
                    # returned here — "Found 44 result(s): 1. register: Accessible route |
                    # record: route/RTE-001 | comment: …" — which is unreadable and answers
                    # nothing (BUG-546). Name what was found and say it was not summarised.
                    return self._register_fallback(bindings)
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

    _COUNT_RE = re.compile(
        r"\(\s*COUNT\s*\(\s*(?:DISTINCT\s+)?(\?\w+|\*)\s*\)\s+AS\s+(\?\w+)\s*\)", re.IGNORECASE
    )
    _COUNTED_CLASS_RE = re.compile(
        r"\b(?:a|rdf:type)(?:/rdfs:subClassOf\*)?\s+([A-Za-z0-9]+:[A-Za-z_][\w-]*)"
    )

    @classmethod
    def _count_meaning(cls, sparql_query: str) -> str:
        """What a COUNT result is a count OF, stated for the narration (BUG-547).

        "What's the daylight hour count in the deepest workstation this December?" generated
        `SELECT (COUNT(DISTINCT ?sensor) AS ?count) WHERE { ?sensor a brick:Illuminance_Sensor }`
        and was answered "the deepest workstation recorded **269 daylight hours**". The number
        was real, so the numeric guard passed it; its MEANING was invented. A count of graph
        entities is never a reading, a duration or an amount, and the prompt now says so.
        """
        counts = cls._COUNT_RE.findall(sparql_query or "")
        if not counts:
            return ""
        what = cls._COUNTED_CLASS_RE.search(sparql_query or "")
        kind = f" of type {what.group(1)}" if what else ""
        grouped = (
            " for that row's group" if re.search(r"\bGROUP\s+BY\b", sparql_query, re.I) else ""
        )
        pairs = ", ".join(
            f"{alias} = how many {var if var != '*' else 'matches'}{kind} the building model "
            f"holds{grouped}"
            for var, alias in counts
        )
        return (
            f"NOTE ON THESE FIGURES: {pairs}. A count of things in the model is NOT a reading, a "
            "measurement, a duration, an amount or a total over time. If the question asks for "
            "any of those, say plainly that the building model does not hold it, and mention "
            "the count only as what it is — never present it as the quantity asked for."
        )

    #: Columns never hoisted into a group header, because they are what a reader counts,
    #: filters and names records by — even when every row happens to share one value.
    _NEVER_HOISTED = frozenset({"record", "label", "recordId", "recordStatus"})

    @classmethod
    def _render_rows(cls, bindings: List[Dict[str, Any]], hoist: bool = False) -> str:
        """Rows as the narration prompt shows them: ``N. field: value | field: value``.

        With ``hoist``, a value that EVERY row of a register shares is printed once in a
        header for that register instead of on every row (BUG-546). Lifted records repeat
        their document, mapping, version, authority and retrieval stamp on every row; a
        16-route plus 28-workspace handover measured 42.8k characters, the model returned
        an empty completion three times, and the user got a raw dump. Nothing is dropped —
        the header states each shared value — so no fact leaves the prompt.
        """

        def _v(binding: Dict[str, Any], key: str) -> str:
            return str((binding.get(key) or {}).get("value", "N/A"))

        def _line(n: int, binding: Dict[str, Any], skip: set) -> str:
            cells = " | ".join(f"{k}: {_v(binding, k)}" for k in binding if k not in skip)
            return f"{n}. {cells}\n"

        if not hoist or len(bindings) < 2:
            return "".join(_line(i, b, set()) for i, b in enumerate(bindings, 1))

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for binding in bindings:
            groups.setdefault(_v(binding, "register") if "register" in binding else "", []).append(
                binding
            )
        out: List[str] = []
        n = 0
        for register, rows in groups.items():
            shared: set = set()
            if len(rows) > 1:
                common = set(rows[0]).intersection(*(set(r) for r in rows[1:]))
                shared = {
                    k
                    for k in common
                    if k not in cls._NEVER_HOISTED and len({_v(r, k) for r in rows}) == 1
                }
            if shared:
                scope = f" of register {register}" if register else ""
                filled = [k for k in rows[0] if k in shared and _v(rows[0], k) not in ("", "N/A")]
                empty = [k for k in rows[0] if k in shared and k not in filled]
                header = " | ".join(f"{k}: {_v(rows[0], k)}" for k in filled)
                if header:
                    out.append(f"All {len(rows)} records{scope} share: {header}\n")
                if empty:
                    # A merged handover pads each row with the other register's columns. A gap
                    # still reads as a gap, once, rather than as a column of blanks per row.
                    out.append(f"No record{scope} has a value for: {', '.join(empty)}\n")
            for row in rows:
                n += 1
                out.append(_line(n, row, shared))
        return "".join(out)

    @staticmethod
    def _register_fallback(bindings: List[Dict[str, Any]]) -> str:
        """What a register handover says when the model could not summarise it (BUG-546)."""

        def _v(binding: Dict[str, Any], key: str) -> str:
            return str((binding.get(key) or {}).get("value", "") or "")

        shown = []
        for binding in bindings[:15]:
            name = _v(binding, "label") or _v(binding, "recordId") or _v(binding, "record")
            name = name.rsplit("#", 1)[-1].rsplit("/", 1)[-1] if "://" in name else name
            status = _v(binding, "recordStatus")
            source = _v(binding, "register")
            detail = ", ".join(x for x in (source, status) if x)
            shown.append(f"- {name}" + (f" ({detail})" if detail else ""))
        more = f"\n- …and {len(bindings) - 15} more" if len(bindings) > 15 else ""
        return (
            f"I found **{len(bindings)} records** that bear on this, but I couldn't summarise "
            "them against your question just now, so I haven't drawn a conclusion from them. "
            "The records are:\n" + "\n".join(shown) + more + "\n\nAsk about one of them, or "
            "narrow the question, and I can answer from its detail."
        )

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
