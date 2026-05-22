"""
Dialogue Agent - LLM-Based Intent Detection and Query Generation
"""

import sys

sys.path.append("/app")

import json
from datetime import datetime
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



# P6: Few-shot library for intent detection
_FEW_SHOT_LIB: Optional[Dict] = None
_FEW_SHOT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "few_shot_library.json"
)


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
        messages[-(max_messages + 1) : -1]
        if len(messages) > max_messages
        else messages[:-1]
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


# ── G1 six-tuple taxonomy derivation ─────────────────────────────────────────
# Survey corpus: 5,916 classified questions across 81 participants.
# G1 classification framework: (domain_l1, query_type_l2, intent,
#   temporal, spatial, complexity).

_DOMAIN_MAP = {
    "THERMAL": ("temperature", "thermal", "hvac", "heating", "cooling", "comfort",
                "warm", "cold", "hot", "thermostat"),
    "AIR_QUALITY": ("co2", "carbon dioxide", "air quality", "humidity", "ventilation",
                    "pm2.5", "pm10", "voc", "pollut", "stuffy", "fresh air"),
    "ENERGY": ("energy", "electricity", "power", "kwh", "watt", "consumption",
               "usage", "load", "metering"),
    "LIGHTING": ("light", "lighting", "lux", "bright", "dim", "led", "daylight",
                 "blind", "shading"),
    "OCCUPANCY": ("occupancy", "occupied", "people", "crowd", "headcount", "presence",
                  "how many people", "attendance"),
    "ACCESS_SECURITY": ("access", "security", "cctv", "camera", "lock", "door",
                        "card", "badge", "swipe", "entry"),
    "FIRE_SAFETY": ("fire", "evacuation", "alarm", "sprinkler", "extinguisher",
                    "emergency exit", "muster", "assembly"),
    "INFORMATIONAL": ("policy", "rule", "procedure", "contact", "helpdesk",
                      "booking", "amenity", "cafe", "wifi", "hours", "open",
                      "capability", "feature", "what can"),
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

_SPATIAL_KW = ("zone", "floor", "room", "area", "space", "section", "level",
               "corridor", "lab", "office", "building")
_TIME_KW = ("today", "yesterday", "last", "past", "hour", "day", "week",
            "month", "year", "since", "between", "trend", "history", "historical")


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
    elif intent in ("analytics", "compare", "anomaly", "compliance", "trend", "forecast") or n_entities >= 2:
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

    async def _retrieve_ontology_context(self, query: str, top_k: int = 5) -> List[str]:
        """
        Retrieve relevant ontology context from RAG service

        Args:
            query: User's question
            top_k: Number of context items to retrieve

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
                        # Format GraphDB result as context strings
                        summary = data.get("summary", "")
                        triples = data.get("triples", [])
                        contexts = [summary] + triples
                        logger.info(
                            f"✅ Retrieved {len(contexts)} context items from GraphDB RAG"
                        )
                        return contexts[:top_k]
                    else:
                        logger.warning(
                            f"GraphDB retrieval returned status {response.status_code}"
                        )
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

        # ── Capability semantic-first routing (Phase 1 migration) ──
        # Flag-gated. When the flag is OFF, this block is a no-op and the legacy
        # keyword-based override (further down) handles capability routing as today.
        #
        # When ON: query Qdrant for a high-confidence capability match BEFORE the
        # LLM intent call.  A score >= override_min lets us skip the LLM entirely
        # (saves ~200ms).  A score in [threshold, override_min) is recorded on
        # state for the post-LLM soft-override step.  Below threshold → no signal.
        #
        # Failures (Qdrant down, embedding API down) return source="fallback" and
        # the LLM intent classification proceeds normally — non-fatal by design.
        if (
self.semantic_router is not None
            and user_query
            and user_query.strip()
        ):
            try:
                bldg_id = state.building_id or "bldg1"
                semantic_result = await self.semantic_router.classify(user_query, bldg_id)
                state.intermediate_results["_semantic_route"] = {
                    "score": semantic_result.score,
                    "source": semantic_result.source,
                    "match_count": len(semantic_result.matches),
                }
                if semantic_result.intent == "capability":
                    state.intermediate_results["capability_matches"] = semantic_result.matches
                    state.intermediate_results["semantic_route_score"] = semantic_result.score
                    logger.info(
                        f"[semantic-route] HIGH-CONFIDENCE capability hit "
                        f"(score={semantic_result.score:.3f}, top={semantic_result.matches[0].entry_id if semantic_result.matches else '?'}) "
                        f"— skipping LLM intent call"
                    )
                    return {
                        "intent": "capability",
                        "general": False,
                        "analytics": False,
                        "sparql_query": "",
                        "response": "",
                    }
                elif semantic_result.intent:
                    # Multi-intent extension: any other registered intent (floor_plan,
                    # spatial_query, ...) that crossed override_min. No pre-fetched
                    # data — the downstream node (floor_plan node, spatial_query node)
                    # owns its own data path.
                    state.intermediate_results["semantic_route_score"] = semantic_result.score
                    state.intermediate_results["semantic_route_intent"] = semantic_result.intent
                    logger.info(
                        f"[semantic-route] HIGH-CONFIDENCE {semantic_result.intent} hit "
                        f"(score={semantic_result.score:.3f}) — skipping LLM intent call"
                    )
                    return {
                        "intent": semantic_result.intent,
                        "general": False,
                        "analytics": False,
                        "sparql_query": "",
                        "response": "",
                    }
            except Exception as e:
                # Never let semantic routing block intent detection
                logger.warning(f"[semantic-route] check failed (non-fatal): {e}")

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
        recent_messages = self.context_manager.prune_messages(
            state.messages, max_messages=5
        )
        conversation_history = format_conversation_history(recent_messages)

        if state.summary:
            conversation_history = f"Summary of previous conversation:\n{state.summary}\n\nRecent Messages:\n{conversation_history}"

        # Phase 3.2: Retrieve memory context (set by workflow _dialogue_node B.3 block)
        memory_context = state.intermediate_results.get("memory_context", "")

        # Build the LLM prompt for intent detection and query generation
        prompt = self._build_intent_detection_prompt(
            user_query=user_query,
            ontology_context=ontology_context,
            conversation_history=conversation_history,
            persona=getattr(state, "persona", "general") or "general",
            memory_context=memory_context,
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
            result = self._parse_llm_response(llm_response, user_query)

            # ── Capability semantic SOFT override (medium-band) ────────────────
            # Flag-gated. Runs AFTER _parse_llm_response so the keyword override
            # has had a chance to fire first. Only kicks in when:
            #   - Flag enabled AND semantic router available
            #   - LLM picked a NON-data intent AND keyword override did NOT already
            #     route to capability
            #   - Semantic score is in [threshold, override_min) — the medium band
            # High-band overrides already short-circuited before the LLM call.
            if (
self.semantic_router is not None
                and result.get("intent") != "capability"
            ):
                _sem_meta = state.intermediate_results.get("_semantic_route") or {}
                _sem_score = float(_sem_meta.get("score") or 0.0)
                _llm_intent = result.get("intent")
                _NON_DATA_INTENTS = {
                    "general", "clarification", "unknown", "general_knowledge",
                    "sparql", "discovery", "metadata",
                }
                if (
                    _sem_score > 0.0
                    and _sem_meta.get("match_count", 0) > 0
                    and _llm_intent in _NON_DATA_INTENTS
                ):
                    try:
                        _bldg_id = state.building_id or "bldg1"
                        _sem = await self.semantic_router.classify(user_query, _bldg_id)
                        if _sem.matches:
                            state.intermediate_results["capability_matches"] = _sem.matches
                            state.intermediate_results["semantic_route_score"] = _sem.score
                            logger.info(
                                f"[semantic-route] SOFT override (was '{_llm_intent}', "
                                f"score={_sem.score:.3f}) → capability"
                            )
                            result["intent"] = "capability"
                            result["analytics"] = False
                            result["general"] = False
                    except Exception as _sem_e:
                        logger.debug(f"[semantic-route] soft override skipped: {_sem_e}")

            # Cache result
            await redis_manager.set_cache(cache_key, result, ttl=3600)

            # Log the detected intent
            logger.info("═" * 80)
            logger.info(f"🎯 Intent Detection Result:")
            logger.info(f"   ├─ Intent: {result.get('intent', 'unknown')}")
            logger.info(f"   ├─ Entities: {result.get('entities', [])}")
            logger.info(f"   ├─ Analytics: {result.get('required_analytics', [])}")
            if result.get("intent") == "general":
                logger.info(
                    f"   └─ Direct Response: {result.get('response', '')[:100]}..."
                )
            else:
                logger.info(f"   └─ Explanation: {result.get('explanation', '')}")
            logger.info("═" * 80)

            return result

        except Exception as e:
            logger.error(f"❌ LLM intent detection failed: {e}", exc_info=True)
            # Fallback to safe default
            return {
                "general": True,
                "sparql_query": "",
                "analytics": False,
                "response": f"I encountered an error processing your question. Please try rephrasing: {str(e)}",
            }

    def _build_intent_detection_prompt(
        self,
        user_query: str,
        ontology_context: List[str],
        conversation_history: str,
        persona: str = "general",
        memory_context: str = "",
    ) -> str:
        """
        Build the prompt for LLM-based intent detection

        Args:
            user_query: The user's question
            ontology_context: Retrieved ontology fragments from vector DB
            conversation_history: Formatted conversation history

        Returns:
            Formatted prompt string
        """
        # Get current time in building's local timezone
        try:
            local_time = datetime.now(ZoneInfo(settings.BUILDING_TIMEZONE))
            current_time_str = local_time.strftime("%A, %B %d, %Y, %H:%M %Z")
        except Exception as e:
            logger.warning(f"Failed to get local time: {e}")
            current_time_str = datetime.now().strftime("%A, %B %d, %Y, %H:%M (UTC)")

        # Format ontology context
        context_str = ""
        if ontology_context:
            context_str = "\\n\\nRelevant Ontology Context (from vector database):\\n"
            for i, ctx in enumerate(ontology_context, 1):
                context_str += f"{i}. {ctx}\\n"

        # Phase 4.1 — Expanded 14-intent taxonomy
        prompt = f"""You are an intelligent assistant analyzing user questions about a smart building management system.
Current Date and Time: {current_time_str}

Your task is to analyze the user's question and return a JSON response.

1. "intent" (string): One of the following 15 intents. Choose the MOST SPECIFIC one that applies.

   === INTENT DEFINITIONS WITH EXAMPLES ===

   - "general"       : General knowledge / greetings / non-building questions.
                        e.g. "Hello", "What can you do?", "What is HVAC?"

   - "metadata"      : Static structure queries — list entities, look up types, describe a thing.
                        e.g. "What sensors are in zone 5?", "What type of sensor is X?", "List all floors."

   - "discovery"     : Explore available sensors, zones, data types, system capabilities.
                        e.g. "What can I monitor?", "Show me all available data types.", "How many sensors does the building have?"

   - "analytics"     : ONLY for direct statistical computation on a single dataset — averages, min/max, sums,
                        counts, histograms, distribution, current readings. NOT for comparisons, NOT for recommendations.
                        e.g. "What is the average CO2 last week?", "Show temperature history for zone 5.", "Current humidity?"

   - "compare"       : Side-by-side comparison of TWO OR MORE sensors, zones, floors, or time periods.
                        ALWAYS use this when the user says "compare", "vs", "versus", "difference between",
                        "higher/lower than", "which is better/worse", or names two distinct things.
                        e.g. "Compare air quality between floor 1 and floor 5.", "Is zone 3 hotter than zone 5?",
                        "How does this week compare to last week?"

   - "trend"         : How a single metric has CHANGED OVER TIME — increasing, decreasing, stable, rate of change.
                        e.g. "Is energy consumption trending up?", "How has CO2 changed since Monday?", "Is temperature rising?"

   - "recommend"     : Request ACTIONABLE ADVICE — what to change, how to improve, what settings to use.
                        ALWAYS use this when the user says "recommend", "suggest", "should I", "how can I improve",
                        "what settings", "optimize", "what should I do", "tips", "advice".
                        e.g. "What HVAC settings do you recommend?", "How can I improve air quality?",
                        "Suggest energy saving measures.", "What should the temperature setpoint be?"

   - "anomaly"       : Detect out-of-range, spike, drop, or unusual sensor readings.
                        e.g. "Any unusual readings today?", "Are there temperature spikes?", "Detect anomalies in CO2."

   - "report"        : Generate a structured building report (daily/weekly summary, full energy report).
                        e.g. "Generate a weekly energy report.", "Create a building summary.", "Daily occupancy report."

   - "export"        : Export query results or report to a file (CSV, JSON, HTML, Markdown).
                        e.g. "Export last week's data as CSV.", "Download the report as JSON."

   - "compliance"    : Check sensor readings against regulatory or comfort standards (ASHRAE, WELL, BREEAM, EN15251).
                        e.g. "Is zone 5 within ASHRAE 55 limits?", "Check BREEAM compliance.", "Is CO2 within safe limits?"

   - "planner"       : Multi-step task requiring multiple agents or producing multiple outputs.
                        e.g. "Generate CO2 report and export as CSV.", "Analyse energy, then create a chart and export."

   - "control"      : User issues a command to physically change a building system state.
                       e.g. "Set HVAC zone 3 to 21°C", "Turn off the lights in room 2.04",
                       "Lock down floor 4", "Increase ventilation in Lab 3.07".
                       Entities: device (the system to control), action (set/on/off/lock/
                       unlock/increase/decrease), target_value (e.g. "21°C", "50%"),
                       zone/room.

   - "maintenance"   : User reports a fault, raises a work order, checks ticket status,
                       or updates a maintenance ticket.
                       Trigger phrases: "broken", "not working", "report fault", "raise ticket",
                       "fix the", "maintenance request", "check ticket", "status of MT-".
                       Entities: device, location, fault_description, ticket_id (format MT-XXXX),
                       assignee.

   - "clarification" : Query is too vague to proceed without more information.
                        e.g. "Show me data." (no sensor/zone specified), "What happened?" (no context)

   - "floor_plan"    : User wants to see a floor plan, locate a room/zone/sensor on a floor,
                        navigate the building layout, or get a building overview.
                        ALWAYS use this when the user says: "floor plan", "show me floor", "layout",
                        "where is [room/zone/facility]", "which floor is", "locate", "find my location",
                        "building map", "navigate", "directions to", "how do I get to",
                        "where can I find", "building directory", "building overview", "all floors",
                        "which floor has", "find the office", "where is the lab", "server room location",
                        "toilet", "meeting room location", "lift", "elevator", "staircase",
                        or mentions a floor number with spatial/location intent.
                        e.g. "Show me floor 3 plan.", "Where is zone 5.12?", "Which floor am I on?",
                        "Can you show me the layout of floor 2?", "Where is the server room?",
                        "Which floor has the meeting rooms?", "Navigate me to the lab.",
                        "Show me what's on each floor.", "Where are the toilets?",
                        "Give me a building overview.", "Find the reception."

   - "spatial_query" : User asks quantitative/analytical geometry questions about the building —
                        room sizes, areas, adjacency relationships, counts, or MEP block locations.
                        Use this when the user asks ABOUT DATA derived from the floor plan, not to SEE it.
                        e.g. "Which rooms are larger than 50 m²?", "What is the total area of floor 3?",
                        "How many meeting rooms are on floor 4?", "Which rooms are adjacent to 3.01?",
                        "What is the smallest room on floor 2?", "How many sensors are on floor 3?",
                        "List all labs with area between 20 and 80 m².", "Where are the fire exits?",
                        "What rooms are next to the server room?", "Total area of the building.",
                        "How many doors are on floor 1?", "Count the rooms on each floor."
                        DISAMBIGUATION: "show me / where is / find" → "floor_plan". "how many / area / size / adjacent" → "spatial_query".

   === DISAMBIGUATION RULES (apply in this priority order) ===
   - If the user asks to see a floor plan, map, or layout → "floor_plan"
   - If the user asks where a room/zone/facility is located → "floor_plan"
   - If the user asks for counts, areas, sizes, or adjacency data → "spatial_query"
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

5. "response" (string): Direct answer if intent="general". null otherwise.

6. "clarification_question" (string): If intent="clarification", ask a helpful targeted question with 2-3 options.

7. "discovery_filter" (string|null): If intent="discovery", optional filter (e.g., "temperature", "zone 5").

8. "export_format" (string|null): If intent="export" or "planner", the requested format: "json", "csv", "html", "markdown".

9. "report_type" (string|null): If intent="report", one of: "summary", "anomaly", "comparison", "trend", "full".

10. "recommendation_domain" (string|null): If intent="recommend", domain: "hvac", "air_quality", "energy", "comfort", "general".

11. "explanation" (string): Brief reasoning for your classification.

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

    def _parse_llm_response(self, llm_response: str, user_query: str) -> Dict[str, Any]:
        """
        Parse the LLM's JSON response

        Args:
            llm_response: Raw LLM response
            user_query: Original user query (for fallback)

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
                    "time_range": result.get(
                        "time_range", {"start": None, "end": None}
                    ),
                    "response": result.get("response", ""),
                    "clarification_question": result.get("clarification_question", ""),
                    "discovery_filter": result.get("discovery_filter"),
                    "explanation": result.get("explanation", ""),
                }

                # Backward compatibility for workflow.py until it's updated
                normalized["general"] = normalized["intent"] == "general"
                normalized["analytics"] = normalized["intent"] == "analytics"
                normalized["sparql_query"] = ""  # No longer generated by LLM

                # Flatten time_range for backward compatibility
                if normalized["time_range"]:
                    normalized["start_date"] = normalized["time_range"].get("start")
                    normalized["end_date"] = normalized["time_range"].get("end")
                else:
                    normalized["start_date"] = None
                    normalized["end_date"] = None

                # Deterministic override: force "compare" when comparison keywords
                # appear with two distinct entity references, regardless of LLM choice.
                # LLMs reliably fail on this: "Compare CO2 in zones A and B" → compliance.
                _q_lower = user_query.lower()
                _has_compare_kw = any(
                    kw in _q_lower
                    for kw in ("compare ", "comparison", " vs ", " vs.", " versus ", "difference between",
                               "higher than", "lower than", "more than", "less than")
                )
                _two_zones = len(normalized.get("entities", [])) >= 2
                if (
                    _has_compare_kw
                    and normalized.get("intent") in ("compliance", "analytics", "trend")
                    and _two_zones
                ):
                    logger.info(
                        f"[intent-override] Forcing 'compare' (was '{normalized['intent']}') "
                        f"— compare keyword + {len(normalized['entities'])} entities"
                    )
                    normalized["intent"] = "compare"
                    normalized["analytics"] = False
                    normalized["general"] = False

                # Correlation queries are analytics, not clarification.
                # gpt-4o-mini tends to escalate multi-variable queries to clarification;
                # override when the query explicitly asks for a correlation/relationship analysis.
                _has_correlate_kw = any(
                    kw in _q_lower
                    for kw in ("correlat", "correlation between", "relationship between",
                               "relationship of", "pattern between", "link between")
                )
                if _has_correlate_kw and normalized.get("intent") == "clarification":
                    logger.info(
                        "[intent-override] Forcing 'analytics' (was 'clarification') "
                        "— correlation keyword detected"
                    )
                    normalized["intent"] = "analytics"
                    normalized["analytics"] = True
                    normalized["general"] = False

                # Floor plan navigation queries must always route to floor_plan, not sparql.
                # gpt-4o-mini occasionally classifies "Show me floor N" as "sparql" or
                # "discovery" because it interprets "floor" as an ontology entity lookup.
                # These phrases unambiguously request a visual/structural floor plan.
                _FLOOR_PLAN_KWS = (
                    "show me floor", "floor plan", "floor layout", "floor map",
                    "building map", "building layout", "building overview",
                    "all floors", "where is room", "where is zone",
                    "locate room", "find room", "navigate to room",
                    "directions to room", "how do i get to",
                )
                _has_floor_plan_kw = any(kw in _q_lower for kw in _FLOOR_PLAN_KWS)
                if _has_floor_plan_kw and normalized.get("intent") not in (
                    "floor_plan", "spatial_query"
                ):
                    logger.info(
                        f"[intent-override] Forcing 'floor_plan' (was '{normalized.get('intent')}') "
                        "— floor plan navigation keyword detected"
                    )
                    normalized["intent"] = "floor_plan"
                    normalized["analytics"] = False
                    normalized["general"] = False

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
                    "capability", "general", "general_knowledge", "clarification"
                ):
                    try:
                        _persona_key = getattr(state, "persona", "general") or "general"
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

    async def generate_response(
        self, state: ConversationState, persona: str = "general"
    ) -> str:
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
                context = f"\\n\\nData Analysis Results: {state.intermediate_results['sql_results']}"

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

    async def format_response(
        self, state: ConversationState, response: str, intent: str
    ) -> str:
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
