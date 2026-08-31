"""
Dialogue Agent - LLM-Based Intent Detection and Query Generation
"""

import sys

sys.path.append("/app")

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from orchestrator.llm_manager import TaskType, llm_manager
from orchestrator.redis_manager import redis_manager
from orchestrator.services.context_manager import ContextManager
from shared.config import settings
from shared.models import ConversationState, Message
from shared.persona_registry import get_persona_registry
from shared.utils import generate_hash, get_logger

logger = get_logger(__name__)


# "now", "now-1d", "now-24h", "now-2w" — the relative forms the intent prompt
# invites the LLM to produce for a time bound.
_RELATIVE_DT_RE = re.compile(
    r"^now(?:\s*-\s*(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|"
    r"d|day|days|w|wk|week|weeks|mo|month|months|y|yr|year|years))?$",
    re.IGNORECASE,
)

_RELATIVE_DT_UNITS = {
    "m": "minutes",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
    "d": "days",
    "day": "days",
    "days": "days",
    "w": "weeks",
    "wk": "weeks",
    "week": "weeks",
    "weeks": "weeks",
    "mo": "days",
    "month": "days",
    "months": "days",
    "y": "days",
    "yr": "days",
    "year": "days",
    "years": "days",
}

# Calendar units the LLM may ask for that timedelta has no field for.
_RELATIVE_DT_SCALE = {
    "mo": 30,
    "month": 30,
    "months": 30,
    "y": 365,
    "yr": 365,
    "year": 365,
    "years": 365,
}


def _resolve_relative_dt(value: Optional[str]) -> Optional[str]:
    """Turn a relative time bound into an absolute 'YYYY-MM-DD HH:MM:SS' stamp.

    The intent prompt accepts relative bounds, but every SQL builder downstream
    treats a bound as a literal. An unresolved "now-24h" therefore reaches the
    WHERE clause, where sanitising strips it to "-24" — MySQL then matches no
    rows and Postgres rejects it as a timezone. Resolving here keeps that
    contract in one place. Values already absolute pass through untouched.
    """
    if not value or not isinstance(value, str):
        return value
    s = value.strip()
    m = _RELATIVE_DT_RE.match(s)
    if not m:
        return s
    now = datetime.utcnow()
    amount, unit = m.group(1), m.group(2)
    if amount and unit:
        u = unit.lower()
        n = int(amount) * _RELATIVE_DT_SCALE.get(u, 1)
        now = now - timedelta(**{_RELATIVE_DT_UNITS[u]: n})
    return now.strftime("%Y-%m-%d %H:%M:%S")


# P6: Few-shot library for intent detection
_FEW_SHOT_LIB: Optional[Dict] = None
_FEW_SHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "few_shot_library.json"


def _load_few_shot_library() -> Dict:
    global _FEW_SHOT_LIB
    if _FEW_SHOT_LIB is None:
        try:
            with open(_FEW_SHOT_PATH) as f:
                _FEW_SHOT_LIB = json.load(f)
            logger.info(f"Few-shot library loaded: {len(_FEW_SHOT_LIB)} keys")
        except Exception as e:
            logger.warning(f"Few-shot library not loaded: {e}")
            _FEW_SHOT_LIB = {}
    return _FEW_SHOT_LIB


def _get_few_shot_examples(persona: str, max_examples: int = 2) -> str:
    """Get few-shot examples matching the persona. Falls back to 'general|*' keys."""
    lib = _load_few_shot_library()
    if not lib:
        return ""
    examples = []
    # Collect examples for this persona
    for key, items in lib.items():
        if key.startswith("_"):
            continue
        parts = key.split("|", 1)
        if len(parts) != 2:
            continue
        p, intent = parts
        if p == persona or p == "general":
            for item in items:
                examples.append(item)
    if not examples:
        return ""
    # Take up to max_examples, preferring persona-specific
    selected = examples[:max_examples]
    lines = ["", "=== FEW-SHOT EXAMPLES ==="]
    for ex in selected:
        lines.append(f"User: {ex['q']}")
        lines.append(f"Response: {ex['a']}")
        lines.append("")
    return "\n".join(lines)


# RAG Service URL for context retrieval
RAG_SERVICE_URL = f"http://{settings.RAG_SERVICE_HOST}:{settings.RAG_SERVICE_PORT}"


def _format_triple(triple: Any) -> str:
    """Render one retrieved triple as a readable line for the prompt.

    The retriever returns triples as dicts; interpolating those straight into the
    prompt gave the model Python dict reprs to read (BUG-170). Anything that is
    already a string is passed through, so a change in the retriever's shape
    degrades to the old behaviour instead of raising.
    """
    if isinstance(triple, dict):
        subject = triple.get("subject", "")
        predicate = triple.get("predicate", "")
        obj = triple.get("object", "")
        return f"{subject} {predicate} {obj}".strip()
    return str(triple)


def format_conversation_history(messages: List[Message], max_messages: int = 5) -> str:
    """
    Format recent conversation messages for LLM context.

    Args:
        messages: List of conversation messages
        max_messages: Maximum number of recent messages to include (default: 5)

    Returns:
        Formatted string of conversation history
    """
    if not messages or len(messages) <= 1:
        return "(No previous conversation)"

    # Get last N messages (excluding the current one)
    recent_messages = (
        messages[-(max_messages + 1) : -1] if len(messages) > max_messages else messages[:-1]
    )

    if not recent_messages:
        return "(No previous conversation)"

    formatted = "Previous Conversation:\n"
    for msg in recent_messages:
        role = "User" if msg.role == "user" else "Assistant"
        # Truncate very long messages
        content = msg.content if len(msg.content) <= 200 else msg.content[:200] + "..."
        formatted += f"{role}: {content}\n"

    return formatted.strip()


# ── Co-reference / follow-up detection ───────────────────────────────────────
# Cheap, zero-LLM gate used to decide whether a turn is a context-dependent
# follow-up worth rewriting into a self-contained query. Conservative: a false
# positive only costs one fast-LLM call (the rewrite no-ops self-contained
# queries), while a false negative leaves the reference unresolved.
_FOLLOWUP_MARKER_WORDS = frozenset(
    {
        "there",
        "that",
        "those",
        "these",
        "it",
        "them",
        "they",
        "same",
        "again",
        "instead",
        "ones",
        "one",
    }
)
_FOLLOWUP_MARKER_PHRASES = (
    "the same",
    "the above",
    "the previous",
    "that one",
    "those ones",
    "what about",
    "how about",
    "what of",
)
_FOLLOWUP_START_PREFIXES = (
    "and ",
    "also ",
    "then ",
    "what about",
    "how about",
    "and what",
    "and how",
    "ok ",
    "okay ",
)


def _is_followup_query(query: str) -> bool:
    """Heuristic: does this query likely depend on prior-turn context?

    Returns True for short queries or ones containing deictic/anaphoric markers
    ("there", "that", "the same", "what about", a leading "and", etc.).
    """
    q = (query or "").strip().lower()
    if not q:
        return False
    words = q.split()
    if len(words) <= 4:
        return True
    if any(q.startswith(p) for p in _FOLLOWUP_START_PREFIXES):
        return True
    if any(p in q for p in _FOLLOWUP_MARKER_PHRASES):
        return True
    return bool(_FOLLOWUP_MARKER_WORDS.intersection(words))


# ── G1 six-tuple taxonomy derivation ─────────────────────────────────────────
# Survey corpus: 5,916 classified questions across 81 participants.
# G1 classification framework: (domain_l1, query_type_l2, intent,
#   temporal, spatial, complexity).

_DOMAIN_MAP = {
    "THERMAL": (
        "temperature",
        "thermal",
        "hvac",
        "heating",
        "cooling",
        "comfort",
        "warm",
        "cold",
        "hot",
        "thermostat",
    ),
    "AIR_QUALITY": (
        "co2",
        "carbon dioxide",
        "air quality",
        "humidity",
        "ventilation",
        "pm2.5",
        "pm10",
        "voc",
        "pollut",
        "stuffy",
        "fresh air",
    ),
    "ENERGY": (
        "energy",
        "electricity",
        "power",
        "kwh",
        "watt",
        "consumption",
        "usage",
        "load",
        "metering",
    ),
    "LIGHTING": (
        "light",
        "lighting",
        "lux",
        "bright",
        "dim",
        "led",
        "daylight",
        "blind",
        "shading",
    ),
    "OCCUPANCY": (
        "occupancy",
        "occupied",
        "people",
        "crowd",
        "headcount",
        "presence",
        "how many people",
        "attendance",
    ),
    "ACCESS_SECURITY": (
        "access",
        "security",
        "cctv",
        "camera",
        "lock",
        "door",
        "card",
        "badge",
        "swipe",
        "entry",
    ),
    "FIRE_SAFETY": (
        "fire",
        "evacuation",
        "alarm",
        "sprinkler",
        "extinguisher",
        "emergency exit",
        "muster",
        "assembly",
    ),
    "INFORMATIONAL": (
        "policy",
        "rule",
        "procedure",
        "contact",
        "helpdesk",
        "booking",
        "amenity",
        "cafe",
        "wifi",
        "hours",
        "open",
        "capability",
        "feature",
        "what can",
    ),
}

_QUERY_TYPE_MAP = {
    # intent → query_type_l2
    "sensor_data": "STATUS",
    "analytics": "AGGREGATION",
    "compare": "COMPARISON",
    "anomaly": "ANOMALY",
    "discovery": "LOOKUP",
    "report": "AGGREGATION",
    "trend": "HISTORICAL",
    "forecast": "HISTORICAL",
    "compliance": "AGGREGATION",
    "recommend": "AGGREGATION",
    "export": "AGGREGATION",
    "planner": "MULTI_STEP",
    "capability": "CAPABILITY",
    "general": "LOOKUP",
    "clarification": "LOOKUP",
    "floor_plan": "LOOKUP",
    "spatial_query": "LOOKUP",
    "maintenance": "STATUS",
    "alert": "ANOMALY",
    "control": "CAPABILITY",
}

_SPATIAL_KW = (
    "zone",
    "floor",
    "room",
    "area",
    "space",
    "section",
    "level",
    "corridor",
    "lab",
    "office",
    "building",
)
_TIME_KW = (
    "today",
    "yesterday",
    "last",
    "past",
    "hour",
    "day",
    "week",
    "month",
    "year",
    "since",
    "between",
    "trend",
    "history",
    "historical",
)

# Question-shape keyword sets moved to the routing contract (TODO-050) — re-exported
# here under their historical names for tests and backward compatibility.
from orchestrator.services.routing_contract import (
    BUILDING_INFO_KWS as _BUILDING_INFO_KWS,
)
from orchestrator.services.routing_contract import (
    COUNT_TRIGGER_KWS as _COUNT_TRIGGER_KWS,
)
from orchestrator.services.routing_contract import (
    COUNTABLE_DEVICE_KWS as _COUNTABLE_DEVICE_KWS,
)
from orchestrator.services.routing_contract import FORECAST_KWS as _FORECAST_KWS
from orchestrator.services.routing_contract import (
    MAINTENANCE_SCHEDULE_KWS as _MAINTENANCE_SCHEDULE_KWS,
)
from orchestrator.services.routing_contract import (
    ROOM_GEOMETRY_KWS as _ROOM_GEOMETRY_KWS,
)
from orchestrator.services.routing_contract import (
    SENSOR_METRIC_KWS as _SENSOR_METRIC_KWS,
)
from orchestrator.services.routing_contract import (
    STRUCTURE_COUNT_KWS as _STRUCTURE_COUNT_KWS,
)


def _derive_g1_taxonomy(
    query: str,
    intent: str,
    entities: list,
    time_range: dict | None,
) -> dict:
    """Derive the G1 survey-taxonomy six-tuple from query + parsed intent."""
    q = query.lower()

    # domain_l1
    domain_l1 = "OTHER"
    best_hits = 0
    for domain, kws in _DOMAIN_MAP.items():
        hits = sum(1 for kw in kws if kw in q)
        if hits > best_hits:
            best_hits = hits
            domain_l1 = domain

    # query_type_l2
    query_type_l2 = _QUERY_TYPE_MAP.get(intent, "LOOKUP")

    # temporal — has an explicit time range or time keywords
    has_temporal = bool(
        (time_range and (time_range.get("start") or time_range.get("end")))
        or any(kw in q for kw in _TIME_KW)
    )

    # spatial — mentions a zone/room/floor
    has_spatial = any(kw in q for kw in _SPATIAL_KW)

    # complexity
    n_entities = len(entities) if isinstance(entities, list) else 0
    if intent in ("planner", "report") or n_entities >= 3:
        complexity = "COMPLEX"
    elif (
        intent in ("analytics", "compare", "anomaly", "compliance", "trend", "forecast")
        or n_entities >= 2
    ):
        complexity = "MODERATE"
    else:
        complexity = "SIMPLE"

    return {
        "domain_l1": domain_l1,
        "query_type_l2": query_type_l2,
        "intent": intent,
        "temporal": has_temporal,
        "spatial": has_spatial,
        "complexity": complexity,
    }


# Phase 4.5 — Expanded persona system (10 personas)
PERSONAS = {
    "student": {
        "system_message": """You are a helpful teaching assistant for building systems.
- Use simple, clear explanations and educational context
- Avoid jargon; explain technical terms when used
- Encourage learning and exploration""",
        "style": "educational and encouraging",
    },
    "researcher": {
        "system_message": """You are a research assistant for building data analysis.
- Provide precise, detailed information with data provenance
- Use technical terminology and support hypothesis testing
- Include statistical context where relevant""",
        "style": "precise and analytical",
    },
    "facility_manager": {
        "system_message": """You are a facility management assistant.
- Focus on actionable insights and operational efficiency
- Provide maintenance recommendations with cost/energy implications
- Prioritize reliability and safety""",
        "style": "practical and action-oriented",
    },
    "occupant": {
        "system_message": """You are a friendly building assistant for occupants.
- Use everyday language, avoid technical jargon
- Focus on comfort, air quality, temperature, and amenities
- Provide simple, reassuring answers""",
        "style": "friendly and simple",
    },
    "energy_manager": {
        "system_message": """You are an energy management specialist.
- Focus on energy consumption, efficiency, and cost analysis
- Highlight patterns in energy usage and optimization opportunities
- Use kWh, carbon footprint, and cost metrics""",
        "style": "data-driven and efficiency-focused",
    },
    "safety_officer": {
        "system_message": """You are a health & safety compliance assistant.
- Prioritize occupant safety, air quality thresholds, and regulatory compliance
- Flag anomalies and threshold violations immediately
- Use standards-based language (ASHRAE, WELL, EN standards)""",
        "style": "compliance-focused and alert",
    },
    "it_admin": {
        "system_message": """You are an IT/BMS system administrator assistant.
- Focus on system connectivity, sensor status, data pipelines, and integration
- Use technical terminology for BMS, IoT, and ontology systems
- Provide diagnostic and configuration guidance""",
        "style": "technical and systematic",
    },
    "executive": {
        "system_message": """You are a high-level building intelligence assistant for executives.
- Provide concise, high-level summaries and KPIs
- Focus on business impact: cost, efficiency, sustainability, risk
- Avoid low-level technical details unless asked""",
        "style": "concise and strategic",
    },
    "sustainability_officer": {
        "system_message": """You are a sustainability and ESG reporting assistant.
- Focus on energy efficiency, carbon footprint, and green building metrics
- Reference LEED, BREEAM, and ISO 50001 standards where relevant
- Provide trend analysis and benchmark comparisons""",
        "style": "sustainability-focused and benchmark-aware",
    },
    "general": {
        "system_message": """You are OntoSage, an intelligent building assistant.
- Be helpful, clear, and concise
- Provide relevant information and ask for clarification when needed
- Support various types of queries with detailed, comprehensive answers""",
        "style": "balanced, professional, and detailed",
    },
}


class DialogueAgent:
    """Manages conversation flow and LLM-based intent detection"""

    def __init__(self):
        self.context_manager = ContextManager(llm_manager)
        # Injected by main.py lifespan once Qdrant + EmbeddingService are ready.
        # When None (e.g. during unit tests, or if init failed), semantic routing
        # is silently skipped — the legacy keyword override path runs as before.
        self.semantic_router = None  # type: ignore[assignment]

    async def rewrite_to_standalone(self, state: ConversationState) -> Optional[str]:
        """Rewrite a context-dependent follow-up into a self-contained query.

        Industry-standard "condense question" step: when the latest message is a
        likely follow-up (gated by `_is_followup_query`), a fast LLM resolves
        references like "there"/"that"/"the same" against recent history so that
        downstream intent classification, entity extraction, and SPARQL all see a
        query that stands on its own.

        Returns the rewritten standalone query, or None when no rewrite is
        warranted or anything fails (fully graceful — caller keeps the original).
        """
        if not getattr(settings, "COREFERENCE_REWRITE_ENABLED", True):
            return None
        msgs = state.messages or []
        if len(msgs) < 2 or not msgs[-1]:  # need at least one prior turn
            return None
        latest = (msgs[-1].content or "").strip()
        if not latest or not _is_followup_query(latest):
            return None

        history = format_conversation_history(msgs, max_messages=6)
        if history == "(No previous conversation)":
            return None

        prompt = (
            "You rewrite a user's latest message into a fully self-contained "
            "question for a smart-building assistant.\n\n"
            f"Conversation so far:\n{history}\n\n"
            f'Latest user message: "{latest}"\n\n'
            "Rewrite the latest message so it can be understood with NO prior "
            'context. Resolve references such as "there", "that", "it", '
            '"those", "the same", "again" to the concrete entity (room, '
            "floor, zone, sensor, system, or time period) mentioned earlier. "
            "Preserve the user's intent and any NEW details they added. If the "
            "message is already self-contained, return it unchanged. Return ONLY "
            "the rewritten question — no quotes, labels, or explanation."
        )

        try:
            rewritten = await llm_manager.generate(prompt, task_type=TaskType.REWRITE)
        except Exception as e:  # graceful — keep original on any LLM failure
            logger.debug(f"[coref] rewrite skipped: {e}")
            return None

        if not rewritten:
            return None
        rewritten = rewritten.strip().strip('"').strip()
        # Reject empty, over-long, or no-op rewrites.
        if not rewritten or len(rewritten) > 500:
            return None
        if rewritten.lower() == latest.lower():
            return None
        return rewritten

    async def _retrieve_ontology_context(
        self, query: str, top_k: int = 5, max_context_items: int = 30
    ) -> List[str]:
        """
        Retrieve relevant ontology context from RAG service

        Args:
            query: User's question
            top_k: Number of ENTITIES the retriever should find (its own contract)
            max_context_items: How many context lines to keep for the prompt

        Returns:
            List of context strings with ontology information
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Use GraphDB retrieval ONLY (per user requirement)
                try:
                    response = await client.post(
                        f"{RAG_SERVICE_URL}/graphdb/retrieve",
                        json={"query": query, "top_k": top_k, "hops": 1},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        # BUG-170: top_k is the retriever's ENTITY budget, but this
                        # method used it again to truncate the returned CONTEXT — so
                        # a 5-entity retrieval yielding ~1000 triples was cut to the
                        # summary plus four triples, throwing away nearly all of the
                        # context that was just fetched. The two budgets are separate.
                        summary = data.get("summary", "")
                        triples = data.get("triples", [])
                        contexts = ([summary] if summary else []) + [
                            _format_triple(t) for t in triples
                        ]
                        kept = contexts[:max_context_items]
                        logger.info(
                            f"✅ GraphDB RAG: {data.get('metadata', {}).get('entity_count', '?')} "
                            f"entities / {len(triples)} triples → keeping {len(kept)} context lines"
                        )
                        return kept
                    else:
                        logger.warning(f"GraphDB retrieval returned status {response.status_code}")
                        return []
                except Exception as e:
                    logger.warning(f"GraphDB retrieval failed: {e}")
                    return []
        except Exception as e:
            logger.error(f"❌ Failed to retrieve ontology context: {e}")
            return []

    async def detect_intent(self, state: ConversationState) -> Dict[str, Any]:
        """
        Use LLM to detect user intent and generate SPARQL query if needed.

        Returns a dictionary with:
        - general (bool): True if general knowledge question, False if ontology-based
        - sparql_query (str): SPARQL query if general=False, empty otherwise
        - analytics (bool): True if analytics/aggregation needed
        - response (str): Direct answer if general=True
        """
        logger.info("═" * 80)
        logger.info("🤖 DIALOGUE AGENT: LLM-Based Intent Detection Started")
        logger.info("═" * 80)

        latest_message = state.messages[-1] if state.messages else None
        if not latest_message:
            logger.warning("❌ No messages in conversation state")
            return {
                "general": True,
                "sparql_query": "",
                "analytics": False,
                "response": "I didn't receive a question. How can I help you?",
            }

        user_query = latest_message.content
        logger.info(f"📥 User Query: {user_query}")
        logger.info(f"📜 Conversation History: {len(state.messages)} messages total")

        # "What is OntoSage / what can you do / how do you work" is settled HERE,
        # before the capability probe and before the LLM sees it. Left to run, the
        # probe matched "What is OntoSage?" against a building document that happened
        # to mention the name — an answer that exists on exactly one building — and
        # anything it missed reached the open-domain answerer, which claimed to be
        # "a large-language model built by OpenAI". This question has one correct
        # answer on every building, including one with no documents and no data yet,
        # so nothing downstream is allowed a say in it.
        from orchestrator.services.self_description import is_self_question

        if is_self_question(user_query):
            logger.info("[dialogue] self-description question — answered from configuration")
            return {
                "intent": "self_description",
                "entities": [],
                "required_analytics": [],
                "time_range": {"start": None, "end": None},
                "general": False,
                "analytics": False,
                "sparql_query": "",
                "start_date": None,
                "end_date": None,
                "explanation": "Question about OntoSage itself.",
                "routing_rules_applied": ["self_description_early"],
            }

        # ── Capability routing — TTL-first, SINGLE path (TODO-012) ──────────────
        # Capabilities are ontosage:Amenity / ontosage:KnowledgeTopic TRIPLES, authored via the
        # admin Capabilities GUI or the OCBV TBox. A query routes to the capability intent when it
        # matches an amenity/topic triple by lay-term (deterministic), or a genuinely-uploaded
        # manual scores strongly in the document KB. The legacy Qdrant capability-KB probe,
        # the medium-band soft override, and capability.yaml have all been removed — there is no
        # second path. `_SR` is still used below for the report/control/floor-plan/spatial bypasses.
        # V4: a constraint-recommendation query ("where can I sit that's quiet …
        # near drinking water") mentions amenity lay-terms but is NOT an
        # amenity-info question — it must reach the deliberate pipeline, so it
        # bypasses the capability short-circuit (same guard family as the
        # data/report/control bypasses above it).
        from orchestrator.services.anomaly.diagnosis import (
            is_why_question as _is_why_question,
        )
        from orchestrator.services.asset_state_service import (
            is_asset_state_question as _is_asset_state_question,
        )
        from orchestrator.services.observability import (
            is_observability_question as _is_observability_question,
        )
        from orchestrator.services.routing_contract import DELIBERATE_RE as _DELIB_RE
        from orchestrator.services.routing_contract import EVENTS_RE as _EVENTS_RE
        from orchestrator.services.routing_contract import WAYFIND_RE as _WAYFIND_RE
        from orchestrator.services.routing_contract import (
            consumption_question as _consumption_question,
        )
        from orchestrator.services.routing_contract import (
            plant_point_question as _plant_point_question,
        )
        from orchestrator.services.routing_contract import (
            register_question as _register_q,
        )
        from orchestrator.services.routing_contract import (
            report_request_about_data as _report_request_about_data,
        )
        from orchestrator.services.semantic_router import (
            SemanticRouter as _SR,  # local import avoids cycle
        )

        # V7-T21: a class the building demonstrably HOLDS outranks a lay-term match.
        #
        # Lifting the permit register into 15 queryable instances changed nothing on its
        # own, because this short-circuit fired first: "how many permits are open?"
        # matched *open* against the Working Hours topic's lay terms and returned the
        # building's opening times, never reaching classification. Every lifted register
        # would have been swallowed the same way. Instance counts come from the graph, so
        # a building without a permit register is unaffected and nothing here is a literal.
        _held_record = None
        try:
            from orchestrator.services.record_registry import held_record_class, record_classes

            _held_record = held_record_class(user_query, await record_classes())
        except Exception as _rr_err:  # pragma: no cover - never block routing on this
            logger.debug(f"[ttl-route] record registry unavailable: {_rr_err}")

        if _held_record and not _SR.is_report_intake_query(user_query):
            # The building holds this class as DATA, so the question is answerable by
            # SPARQL and must not be handed to a lane that can only quote prose. A
            # statement ("the permit expired") is still a report and keeps its intake
            # route — only questions are claimed here.
            logger.info(
                f"[ttl-route] metadata via held record class: "
                f"{_held_record.local_name} ({_held_record.instances} instances) "
                f"— skipping LLM intent call"
            )
            return {
                "intent": "metadata",
                "general": False,
                "analytics": False,
                "sparql_query": "",
                "response": "",
            }

        if (
            user_query
            and user_query.strip()
            and not _held_record
            and not _SR.is_data_query(user_query)
            and not _SR.is_report_intake_query(user_query)
            and not _SR.is_control_command(user_query)
            # bge-large's higher scores make the document probe fire more, so honour the
            # same floor-plan/spatial bypass the KB router uses — "show me floor 3 layout"
            # must reach the floor_plan agent, not a floor-areas capability document.
            and not _SR.is_floor_plan_query(user_query)
            and not _SR.is_spatial_query(user_query)
            # BUG-231: route questions had NO bypass here. Measured, neither
            # is_floor_plan_query nor is_spatial_query matches "take me to the nearest
            # accessible toilet", "where's the nearest fire exit" or "how do I get to the
            # seminar room" -- so all three were answered from a document before the LLM
            # classified anything, in 250ms. WAYFIND_RE is the contract's existing definition
            # of a route question and is what _r_wayfinding_spatial routes on; reusing it
            # keeps one definition rather than two that can drift.
            and not _WAYFIND_RE.search(user_query)
            and not _DELIB_RE.search(user_query)
            # V6-T24: event-store questions had no bypass either. "How many work
            # orders are open?" matched the building-hours document on "open" and was
            # answered from prose before the LLM classified anything -- the routing
            # contract sends all four probe phrasings to the events lane and never got
            # a say. Same remedy and same reasoning as WAYFIND_RE above: EVENTS_RE is
            # the contract's own definition of an event-store question, so reusing it
            # keeps one definition instead of two that drift.
            and not _EVENTS_RE.search(user_query)
            # V6-T26: plant/BMS point questions had no bypass. Measured with the points
            # connected and readable: "is the supply fan running on floor 5?" returned a
            # maintenance-log excerpt and "what is the filter differential pressure on
            # AHU_F5?" returned the building-statistics block. `is_data_query` cannot catch
            # these because an equipment id (AHU_F5, VAV_Floor5_West) matches none of its
            # sensor / zone / room / floor patterns. Fourth member of BUG-231's family.
            and not _plant_point_question(user_query)
            # V6-T27: metered-consumption questions had no bypass. "How much energy did the
            # building use last week?" was answered "I don't have that on record" while six
            # floor meters held the data, and "How much electricity does the lab on floor 5
            # use?" returned the room-bookings document. A question answered from prose never
            # reaches a lane that can state a figure -- so it can state no BOUNDARY either,
            # which is the whole point of this turn. Sixth member of BUG-231's family.
            and not _consumption_question(user_query)
            # V6-T10: "can you measure X here?" is a question about the system's own reach.
            # Answered from a document it becomes a claim about instrumentation sourced from
            # prose -- BUG-192's shape, where a sensor class was denied from a retrieval
            # window. Seventh member of BUG-231's family.
            and not _is_observability_question(user_query)
            # V6-T58/T60: service and asset STATE questions had no bypass. "Are the lifts
            # working?" and "is the wifi down on floor 3?" were answered from the building
            # documents -- "the ontology does not contain any information about lifts" --
            # while 21 AssetStatus records sat in the graph with a value, an observation
            # time and an assistance contact for each one. The capability probe claims the
            # question before the LLM, and the parse stage never runs on that path, so the
            # asset_state rule could not get a say however it was ordered. Eighth member of
            # BUG-231's family, and the same remedy: reuse the lane's own definition rather
            # than write a second one here.
            and not _is_asset_state_question(user_query)
            # V6-T26: a WHY-question belongs to the diagnosis lane, never to a document.
            # "Why is room 5.01 stuffy?" was answered here in 1.3s with "I don't have that
            # specific information on record" -- for a room whose CO2, AHU fan state and VAV
            # damper position are all connected and readable. It previously survived only
            # because a later concept-stage rule converted it to sensor_data, which produced a
            # reading plus a guess at the cause; with that rule correctly declining to claim
            # why-questions, this bypass is what gets it to the lane built for it.
            # Fifth member of BUG-231's family.
            and not _is_why_question(user_query)
            # V5-T26: "when was the fire alarm last tested?" matches the fire-safety
            # topic by lay-term, but it asks for a DATE — the register lane answers
            # with one; the topic prose admits it holds none. Same guard family.
            and not _register_q(user_query)
            # CAVEAT-201: "give me a report on energy use last week" asks for a
            # document about MEASURED data. The ontology holds a topic whose lay
            # terms cover "energy", so without this the amenity prose answers a
            # question about readings — with no readings in it. Same guard
            # family as the data/report/control bypasses above.
            and not _report_request_about_data(user_query)
            # V5-T42: individual-tracking / private-content shapes must reach the
            # privacy-refusal rule — never a topic document about 'security'.
            and not __import__(
                "orchestrator.services.privacy.inference_classes",
                fromlist=["classify_inference"],
            ).classify_inference(user_query)
        ):
            try:
                from orchestrator.services.capability_graph_resolver import (
                    get_capability_graph_resolver,
                )

                _facts = await get_capability_graph_resolver().resolve(user_query)
                if _facts:
                    logger.info(
                        f"[ttl-route] capability via ontology triples: "
                        f"{[f.label for f in _facts]} — skipping LLM intent call"
                    )
                    return {
                        "intent": "capability",
                        "general": False,
                        "analytics": False,
                        "sparql_query": "",
                        "response": "",
                    }
                # Prose fallback: only a STRONG document-KB match routes to capability.
                from orchestrator.agents.capability_agent import _search_documents

                _bldg = state.building_id or settings.BUILDING_ID
                _docs = await _search_documents(user_query, _bldg)
                # Threshold calibrated on bge-large scores: real capability prose lands
                # >=0.55 (wifi 0.55, GDPR 0.67, parking 0.64) while general questions land
                # <=0.43 ("capital of France" 0.43). 0.50 sits in that gap so prose routes
                # DETERMINISTICALLY via the probe instead of falling to LLM-variance, and
                # general queries are still rejected. (0.55 sat exactly on wifi's score.)
                if any(d.get("score", 0) >= 0.50 for d in _docs):
                    logger.info(
                        f"[ttl-route] capability via document KB ({len(_docs)} chunk(s)) "
                        f"— skipping LLM intent call"
                    )
                    return {
                        "intent": "capability",
                        "general": False,
                        "analytics": False,
                        "sparql_query": "",
                        "response": "",
                    }
            except Exception as e:
                logger.warning(f"[ttl-route] check failed (non-fatal): {e}")

        # Retrieve ontology context from RAG service
        logger.info("🔍 Retrieving ontology context from GraphDB RAG...")
        ontology_context = await self._retrieve_ontology_context(user_query, top_k=5)

        # Update context summary if needed
        if len(state.messages) > 5:
            # Summarize periodically or if not present
            if not state.summary or len(state.messages) % 5 == 0:
                logger.info("📝 Updating conversation summary...")
                state.summary = await self.context_manager.summarize_history(
                    state.messages, state.summary
                )

        # Format conversation history (Summary + Recent)
        recent_messages = self.context_manager.prune_messages(state.messages, max_messages=5)
        conversation_history = format_conversation_history(recent_messages)

        if state.summary:
            conversation_history = f"Summary of previous conversation:\n{state.summary}\n\nRecent Messages:\n{conversation_history}"

        # Phase 3.2: Retrieve memory context (set by workflow _dialogue_node B.3 block)
        memory_context = state.intermediate_results.get("memory_context", "")

        # Build the LLM prompt for intent detection and query generation.
        # Phase 10 — pass the conversation's building_id so the prompt scope
        # rule uses the right per-building name/timezone instead of the
        # process-global active building's settings.
        # Phase 14A: if `state.personas` (list) is non-empty, pass it as a
        # joined label so the prompt's persona hint reflects the blend.
        _personas_list = list(getattr(state, "personas", []) or [])
        if _personas_list:
            _persona_label = "+".join(_personas_list[:3])
        else:
            _persona_label = getattr(state, "persona", "general") or "general"
        prompt = self._build_intent_detection_prompt(
            user_query=user_query,
            ontology_context=ontology_context,
            conversation_history=conversation_history,
            persona=_persona_label,
            memory_context=memory_context,
            building_id=getattr(state, "building_id", None),
        )

        # Check cache
        prompt_hash = generate_hash(prompt)
        cache_key = f"cache:intent:{prompt_hash}"
        cached_result = await redis_manager.get_cache(cache_key)

        if cached_result:
            logger.info(f"✅ Cache hit for intent detection: {prompt_hash}")
            return cached_result

        # Call LLM to detect intent
        logger.info("🧠 Calling LLM for intent detection and query generation...")
        try:
            llm_response = await llm_manager.generate(prompt, task_type=TaskType.INTENT)
            logger.info(f"📤 LLM Response received (length: {len(llm_response)} chars)")

            # Parse JSON response
            result = self._parse_llm_response(llm_response, user_query, state=state)

            # ── Routing contract, post stage (TODO-050) ────────────────────────
            # Data-query promotion runs after parsing (covers the JSON-parse
            # fallback path too), exactly where the historical override ran.
            from orchestrator.services.routing_contract import (
                apply_contract as _apply_rc,
            )

            # V5-T24 fix: the JSON-parse FALLBACK path returns intent 'general'
            # without ever running the parse-stage rules, so post-stage
            # promotion could hijack event/booking questions into sensor_data.
            # Run parse-stage here whenever it hasn't run for this result.
            if "parse" not in (result.get("routing_stages_run") or []):
                _apply_rc(user_query, result, stage="parse")
            _apply_rc(user_query, result, stage="post")

            # (Legacy medium-band capability SOFT override removed — TODO-012. Capability
            # routing is now the deterministic TTL-first probe above; there is no Qdrant
            # capability-KB fallback to soft-override from.)

            # Cache result — but never a classification failure, which would pin a
            # wrong intent to this question for the whole TTL.
            if result.get("classification_failed"):
                logger.warning("[dialogue] classification failed — not caching this result")
            else:
                await redis_manager.set_cache(cache_key, result, ttl=3600)

            # Log the detected intent
            logger.info("═" * 80)
            logger.info(f"🎯 Intent Detection Result:")
            logger.info(f"   ├─ Intent: {result.get('intent', 'unknown')}")
            logger.info(f"   ├─ Entities: {result.get('entities', [])}")
            logger.info(f"   ├─ Analytics: {result.get('required_analytics', [])}")
            if result.get("intent") == "general":
                logger.info(f"   └─ Direct Response: {result.get('response', '')[:100]}...")
            else:
                logger.info(f"   └─ Explanation: {result.get('explanation', '')}")
            logger.info("═" * 80)

            return result

        except Exception as e:
            logger.error(f"❌ LLM intent detection failed: {e}", exc_info=True)
            # BUG-167: the deterministic routing contract must survive an LLM
            # outage — an empty completion used to return a bare 'general'
            # fallback that skipped every rule, so shape-routable questions
            # (events, register, diagnosis…) fell into the open-domain answerer.
            fallback = {
                "intent": "general",
                "general": True,
                "entities": [],
                "required_analytics": [],
                "time_range": {"start": None, "end": None},
                "start_date": None,
                "end_date": None,
                "sparql_query": "",
                "analytics": False,
                "response": "",
                "classification_failed": True,
            }
            try:
                from orchestrator.services.routing_contract import apply_contract as _rc

                _rc(user_query, fallback, stage="parse")
                _rc(user_query, fallback, stage="post")
            except Exception as rc_err:  # never let routing break the fallback
                logger.warning(f"[dialogue] contract on fallback skipped: {rc_err}")
            fallback["general"] = fallback.get("intent") == "general"
            return fallback

    def _build_intent_detection_prompt(
        self,
        user_query: str,
        ontology_context: List[str],
        conversation_history: str,
        persona: str = "general",
        memory_context: str = "",
        building_id: Optional[str] = None,
    ) -> str:
        """
        Build the prompt for LLM-based intent detection

        Args:
            user_query: The user's question
            ontology_context: Retrieved ontology fragments from vector DB
            conversation_history: Formatted conversation history
            building_id: ConversationState building_id; when provided, the
                SCOPE rule + timezone come from THIS building's config
                (per-request multi-tenant).  When None, falls back to the
                active settings building (legacy behaviour).

        Returns:
            Formatted prompt string
        """
        # Phase 10 — resolve per-request building context once and use it for
        # both the timezone and the SCOPE rule.  Falls back to settings.
        from orchestrator.services.building_context import resolve_building_context

        bctx = resolve_building_context(building_id)

        # Get current time in building's local timezone
        try:
            local_time = datetime.now(ZoneInfo(bctx.timezone))
            current_time_str = local_time.strftime("%A, %B %d, %Y, %H:%M %Z")
        except Exception as e:
            logger.warning(f"Failed to get local time: {e}")
            current_time_str = datetime.now().strftime("%A, %B %d, %Y, %H:%M (UTC)")

        # Format ontology context. HARD CAP (BUG-168): the RAG retrieve has
        # returned 270 items for a single query, inflating this prompt to
        # ~30k chars — past the local model's num_ctx, which then returns an
        # EMPTY completion and drops the whole turn to the fallback path.
        # 30 items is far more than classification uses.
        context_str = ""
        if ontology_context:
            capped = list(ontology_context)[:30]
            if len(capped) < len(ontology_context):
                logger.warning(
                    f"[dialogue] ontology context capped {len(ontology_context)} → "
                    f"{len(capped)} items for the intent prompt (BUG-168 guard)"
                )
            context_str = "\\n\\nRelevant Ontology Context (from vector database):\\n"
            for i, ctx in enumerate(capped, 1):
                context_str += f"{i}. {ctx}\\n"

        # Phase 6 — intent definitions come from orchestrator/intents/intent_definitions.yaml
        # so adding/tuning intents no longer requires editing this prompt by hand.
        # Phase 11A — pass the active building_id so per-building intent overlays
        # (e.g. bldg2's lab_equipment) appear in the LLM's intent list.
        from orchestrator.intents import get_intent_registry

        _registry_for_prompt = get_intent_registry(building_id)
        _intent_block = _registry_for_prompt.descriptions_markdown()
        _intent_count = len(_registry_for_prompt.names())

        # Phase 16B — surface blended persona priors to the LLM so intent
        # classification is informed by WHO is asking, not just WHAT they're
        # asking.  A facility_manager+researcher blend tells the LLM:
        #   * prefer ENERGY/THERMAL domains when ambiguous
        #   * expect COMPLEX-level depth in the response
        #   * be willing to ask for clarification (low threshold)
        # `persona` arrives here as either a single name or "name1+name2+..."
        # (joined by the caller when state.personas is non-empty).
        try:
            from shared.persona_registry import get_persona_registry

            _preg_for_prompt = get_persona_registry()
            _personas_for_prompt = (
                [p for p in persona.split("+") if p] if "+" in (persona or "") else [persona]
            )
            _priors_for_prompt = _preg_for_prompt.get_blended_priors(_personas_for_prompt)
            _persona_hint_block = (
                f"\n   === USER PERSONA HINTS (Phase 16B — informs classification) ===\n"
                f"   Active persona(s): {', '.join(_personas_for_prompt)}\n"
                f"   Priority domains (use to break ties when intent is "
                f"ambiguous): {', '.join(_priors_for_prompt.top_domains[:5])}\n"
                f"   Expected answer depth: {_priors_for_prompt.default_complexity} "
                f"(prefer concise lookups for SIMPLE, detailed analysis for COMPLEX)\n"
                f"   Clarification threshold: "
                f"{_priors_for_prompt.clarification_threshold:.2f} "
                f"(lower = ask for clarification more readily; >= 0.7 = answer "
                f"with best guess instead of asking)\n"
            )
        except Exception:
            # Persona priors are an OPTIONAL signal — don't fail intent
            # classification if the registry blows up.
            _persona_hint_block = ""

        prompt = f"""You are an intelligent assistant analyzing user questions about a smart building management system.
Current Date and Time: {current_time_str}

Your task is to analyze the user's question and return a JSON response.

1. "intent" (string): One of the following {_intent_count} intents. Choose the MOST SPECIFIC one that applies.

   === INTENT DEFINITIONS WITH EXAMPLES ===

{_intent_block}
{_persona_hint_block}
   === SCOPE RULE (highest priority — apply before everything else) ===
   OntoSage's PRIMARY specialty is smart building management for the {bctx.name},
   but it ALSO answers open-domain general-knowledge questions directly.
   - If the question is about THIS building's data, structure, or operations
     (sensors, zones, floors, temperature, CO2, humidity, energy, occupancy, HVAC,
     air quality, fire safety, floor plans, equipment, compliance) → choose the most
     specific BUILDING intent from the list below.
   - If the question is general knowledge / not building-specific (definitions,
     explanations, world facts, "how does X work", coding help, "what can you do")
     → set intent = "general". Leave "response" empty ("") — a dedicated step
     generates the answer. Do NOT redirect the user and do NOT refuse.
   Examples of intent = "general":
     "What is the capital of France?" → general
     "Write me a Python script to sort a list." → general
     "Who won the Premier League?" → general
     "Explain how photosynthesis works." → general

   === DISAMBIGUATION RULES (apply in this priority order) ===
   - If the user asks to see a floor plan, map, or layout → "floor_plan"
   - If the user asks where a room/zone/facility is located → "floor_plan"
   - If the user asks for the AREA, SIZE, DIMENSIONS, or physical ADJACENCY of rooms/spaces/floors → "spatial_query" (floor-plan geometry). Examples: "area of floor 3", "which rooms are adjacent to 5.08", "how big is the atrium".
   - BUT a COUNT of sensors, devices, equipment, meters, zones, or any Brick class is "metadata" (answered by a graph COUNT), NOT "spatial_query". Examples: "how many temperature sensors are there?" → "metadata"; "number of CO2 sensors" → "metadata".
   - If the user asks for a building overview or wants to know what's on each floor → "floor_plan"
   - If the user mentions navigation, directions, or finding a specific room/facility → "floor_plan"
   - If the query contains "recommend", "suggest", "improve", "optimize", "what should" → "recommend"
   - CRITICAL: If the query explicitly uses the word "compare", "vs", "versus", "difference between",
     "higher than", "lower than", or names TWO OR MORE distinct zones/sensors/time-periods side-by-side
     → ALWAYS "compare". This overrides compliance even if CO2/temperature/air quality is mentioned.
     Examples: "Compare CO2 in zones 5.08 and 5.10" → "compare" (NOT compliance)
               "Is zone 3 warmer than zone 5?" → "compare" (NOT analytics)
               "Average CO2 this week vs last week" → "compare" (NOT trend)
   - If the query asks about change over time for a SINGLE entity → "trend"
   - If the query ONLY checks whether readings comply with ASHRAE/WELL/BREEAM/ISO standard
     AND does NOT use the word "compare" → "compliance"
   - Use "analytics" ONLY when none of the above apply and the user wants raw statistics

2. "entities" (list): All specific building entities mentioned. Normalize names if possible.

3. "required_analytics" (list): If intent involves data — list needed operations:
   "min", "max", "avg", "count", "sum", "trend", "latest", "anomaly".

4. "time_range" (object):
   - "start": ISO or relative ("now-1d"). null if not specified.
   - "end": ISO or relative ("now"). null if not specified.
   Only set when user explicitly mentions a time period.

5. "response" (string): Leave empty ("") — for intent="general" a dedicated step
   writes the answer; for all other intents downstream agents produce the response.

6. "clarification_question" (string): If intent="clarification", ask a helpful targeted question with 2-3 options.

7. "discovery_filter" (string|null): If intent="discovery", optional filter (e.g., "temperature", "zone 5").

8. "export_format" (string|null): If intent="export" or "planner", the requested format: "json", "csv", "html", "markdown".

9. "report_type" (string|null): If intent="report", one of: "summary", "anomaly", "comparison", "trend", "full".

10. "recommendation_domain" (string|null): If intent="recommend", domain: "hvac", "air_quality", "energy", "comfort", "general".

11. "explanation" (string): Brief reasoning for your classification.

12. "live_data" (object|null): ONLY for intent="general". Decide if a correct answer
    needs CURRENT, real-world information you cannot know from your training data:
      - {{"type": "weather", "location": "<city/place>"}} for current weather/forecast.
      - {{"type": "web", "query": "<concise search query>"}} for anything time-sensitive:
        latest/current facts, news, prices, sports results, "who is the current ...",
        newest software versions, recent events.
      - null when the question is timeless knowledge you already know (definitions,
        history, how-things-work, math, coding). Be conservative — prefer null unless
        the answer genuinely depends on up-to-date information.

=== CONVERSATION HISTORY ===
{conversation_history}

=== RELEVANT CONTEXT ===
{context_str}
{f"=== USER INTERACTION MEMORY ==={chr(10)}{memory_context}{chr(10)}" if memory_context else ""}
{_get_few_shot_examples(persona)}
=== USER QUERY ===
{user_query}

Return ONLY the JSON object.
"""
        return prompt

    def _parse_llm_response(
        self,
        llm_response: str,
        user_query: str,
        state: Optional["ConversationState"] = None,
    ) -> Dict[str, Any]:
        """
        Parse the LLM's JSON response

        Args:
            llm_response: Raw LLM response
            user_query: Original user query (for fallback)
            state: ConversationState (optional, enables persona-biased domain disambiguation)

        Returns:
            Parsed dictionary with intent, entities, required_analytics, time_range, response fields
        """
        try:
            # Try to extract JSON from response (in case LLM adds explanation)
            # Look for JSON block
            json_start = llm_response.find("{")
            json_end = llm_response.rfind("}") + 1

            if json_start != -1 and json_end > json_start:
                json_str = llm_response[json_start:json_end]
                result = json.loads(json_str)

                # Validate and normalize required fields
                normalized = {
                    "intent": result.get("intent", "general"),
                    "entities": result.get("entities", []),
                    "required_analytics": result.get("required_analytics", []),
                    "time_range": result.get("time_range", {"start": None, "end": None}),
                    "response": result.get("response", ""),
                    "clarification_question": result.get("clarification_question", ""),
                    "discovery_filter": result.get("discovery_filter"),
                    "explanation": result.get("explanation", ""),
                    # Smart live-data routing hint (general_knowledge only). The
                    # general_knowledge node consults this first, falling back to a
                    # keyword heuristic when the LLM omits it.
                    "live_data": result.get("live_data"),
                }

                # Backward compatibility for workflow.py until it's updated
                normalized["general"] = normalized["intent"] == "general"
                normalized["analytics"] = normalized["intent"] == "analytics"
                normalized["sparql_query"] = ""  # No longer generated by LLM

                # Flatten time_range for backward compatibility. The prompt invites
                # relative bounds ("now-1d"), which every downstream SQL builder
                # would otherwise splice in as a literal — so resolve them here,
                # once, into absolute timestamps.
                if normalized["time_range"]:
                    normalized["start_date"] = _resolve_relative_dt(
                        normalized["time_range"].get("start")
                    )
                    normalized["end_date"] = _resolve_relative_dt(
                        normalized["time_range"].get("end")
                    )
                    normalized["time_range"] = {
                        "start": normalized["start_date"],
                        "end": normalized["end_date"],
                    }
                else:
                    normalized["start_date"] = None
                    normalized["end_date"] = None

                # NOTE: The former out-of-domain guard that rewrote "general"
                # answers into a building-scope redirect was removed — OntoSage now
                # answers open-domain general-knowledge questions. Classification as
                # "general" routes to the dedicated _general_knowledge_node, which
                # generates the answer with user-controlled length.

                # ── Undefined intents are not classifications ──────────────────
                # The model occasionally answers with an intent name that exists
                # in no registry — an observed case was the literal string
                # "failure". It parses cleanly, so nothing downstream treats it as
                # an error, but it matches no route and it is not in the WEAK set
                # the routing contract is allowed to override. The question then
                # skipped every deterministic rule and fell through to the default
                # data lane: "what is the area of room 3.50" was answered from
                # sensor counts while the floor plan held that room's measured
                # 8.87 m2. Demoting it to "general" restores the ordinary
                # unclassified path — the contract gets its chance, and the result
                # is not cached, so one bad completion cannot pin a wrong route to
                # this question for an hour.
                _raw_intent = normalized.get("intent")
                if _raw_intent:
                    try:
                        from orchestrator.intents.registry import get_intent_registry

                        _reg = get_intent_registry(getattr(state, "building_id", None))
                        if _reg.resolve_name(str(_raw_intent)) is None:
                            logger.warning(
                                f"[dialogue] LLM returned undefined intent "
                                f"{_raw_intent!r} — treating as unclassified"
                            )
                            normalized["intent"] = "general"
                            normalized["general"] = True
                            normalized["classification_failed"] = True
                    except Exception as _reg_err:  # never let this break routing
                        logger.warning(f"[dialogue] intent validation skipped: {_reg_err}")

                # ── Deterministic routing contract (TODO-050) ──────────────────
                # Every question-shape → intent override lives in ONE ordered,
                # tested, building-agnostic contract — see
                # services/routing_contract.py for the rules and precedence.
                from orchestrator.services.routing_contract import apply_contract

                apply_contract(user_query, normalized, stage="parse")

                # ── G1 six-tuple emission (cross-cutting, survey taxonomy) ─────────
                # Emitted on every turn; persisted in intermediate_results["g1_taxonomy"].
                # Drives Phase 0 routing, makes every phase measurable against the
                # survey's own taxonomy, and enables production traffic analysis
                # with the same Phase-B scripts.
                g1 = _derive_g1_taxonomy(
                    query=user_query,
                    intent=normalized.get("intent", "general"),
                    entities=normalized.get("entities", []),
                    time_range=normalized.get("time_range"),
                )
                normalized["g1_taxonomy"] = g1

                # Phase 3 — Persona-biased domain disambiguation
                # When the G1 domain is OTHER (ambiguous/tie) and the current
                # persona has strong priors, override with the persona's top domain.
                # This implements D3 survey finding: personas have distinct domain
                # mixes, not just tone differences.
                if g1.get("domain_l1") == "OTHER" and normalized.get("intent") not in (
                    "capability",
                    "general",
                    "general_knowledge",
                    "clarification",
                ):
                    try:
                        _persona_key = (
                            getattr(state, "persona", "general") if state is not None else "general"
                        ) or "general"
                        _registry = get_persona_registry()
                        _priors = _registry.get_priors(_persona_key)
                        if _priors.top_domains:
                            g1 = dict(g1)
                            g1["domain_l1"] = _priors.top_domains[0]
                            normalized["g1_taxonomy"] = g1
                            logger.info(
                                f"[persona-domain-bias] {_persona_key} → "
                                f"domain_l1={g1['domain_l1']}"
                            )
                    except Exception:
                        pass

                logger.info("✅ Successfully parsed LLM JSON response")
                return normalized
            else:
                raise ValueError("No JSON found in LLM response")

        except Exception as e:
            logger.error(f"❌ Failed to parse LLM response: {e}")
            logger.error(f"Raw response: {llm_response[:500]}...")

            # Fallback: treat as general question
            return {
                "intent": "general",
                # Marks this as "we could not classify", not "the user asked a
                # general question" — the caller must not cache it as a result.
                "classification_failed": True,
                "entities": [],
                "required_analytics": [],
                "time_range": {"start": None, "end": None},
                "response": f"I'll try to answer your question: {user_query}. However, I had trouble understanding the query format. Could you please rephrase?",
                "explanation": "Fallback due to parse error",
                # Backward compatibility
                "general": True,
                "analytics": False,
                "sparql_query": "",
                "start_date": None,
                "end_date": None,
            }

    async def generate_response(self, state: ConversationState, persona: str = "general") -> str:
        """Generate a conversational response using selected persona"""

        persona_config = PERSONAS.get(persona, PERSONAS["general"])
        messages = state.messages

        if not messages:
            return "Hello! How can I help you with the building systems today?"

        # Get conversation history
        history = format_conversation_history(messages, max_messages=5)
        latest_query = messages[-1].content

        # Check if we have query results to incorporate
        context = ""
        if state.intermediate_results:
            if "sparql_results" in state.intermediate_results:
                context = f"\\n\\nQuery Results: {state.intermediate_results['sparql_results']}"
            elif "sql_results" in state.intermediate_results:
                context = (
                    f"\\n\\nData Analysis Results: {state.intermediate_results['sql_results']}"
                )

        prompt = f"""{persona_config['system_message']}

{history}

{context}

User's current question: {latest_query}

Provide a helpful, {persona_config['style']} response."""

        response = await llm_manager.generate(prompt, task_type=TaskType.GENERAL)
        return response

    async def request_clarification(self, state: ConversationState) -> str:
        """Request clarification when intent is unclear"""
        latest_message = state.messages[-1] if state.messages else None

        if not latest_message:
            return "I'm not sure what you're asking. Could you please provide more details?"

        prompt = f"""The user asked: "{latest_message.content}"

This question is unclear. Generate a helpful clarification request that:
1. Acknowledges their question
2. Explains what might be unclear
3. Suggests 2-3 specific ways they could rephrase

Keep it friendly and concise (<100 words)."""

        response = await llm_manager.generate(prompt, task_type=TaskType.DISAMBIGUATION)
        return response

    async def format_response(self, state: ConversationState, response: str, intent: str) -> str:
        """
        Format response with persona-aware styling via a single LLM call.

        Skips reformatting when:
          - persona is "general" (no reframing needed)
          - response is short (<200 chars — minimal benefit)
          - persona definition not found in PERSONAS dict
        """
        persona = getattr(state, "persona", "general") or "general"

        # Legacy alias mapping
        _alias = {
            "stakeholder": "facility_manager",
            "guest": "occupant",
            "officer": "safety_officer",
        }
        persona = _alias.get(persona, persona)

        if persona == "general" or len(response) < 200:
            return response

        persona_cfg = PERSONAS.get(persona)
        if not persona_cfg:
            return response

        prompt = f"""{persona_cfg['system_message']}

Rewrite the following building-data response so it matches the style described below.
Keep ALL factual data, numbers, sensor names, and units intact — do not invent or omit data.
Only adjust tone, structure, and emphasis to suit the target audience.

Target style: {persona_cfg['style']}

---
ORIGINAL RESPONSE:
{response}
---

Rewritten response:"""

        try:
            formatted = await llm_manager.generate(prompt, task_type=TaskType.REWRITE)
            if formatted and len(formatted.strip()) > 20:
                return formatted.strip()
        except Exception as e:
            logger.warning(f"Persona formatting failed (returning raw): {e}")

        return response
