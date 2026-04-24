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

   - "control"       : Request to physically change a building system state (not yet supported).
                        e.g. "Turn on the AC.", "Set temperature to 22°C."

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

   === DISAMBIGUATION RULES ===
   - If the user asks to see a floor plan, map, or layout → "floor_plan"
   - If the user asks where a room/zone/facility is located → "floor_plan"
   - If the user asks for counts, areas, sizes, or adjacency data → "spatial_query"
   - If the user asks for a building overview or wants to know what's on each floor → "floor_plan"
   - If the user mentions navigation, directions, or finding a specific room/facility → "floor_plan"
   - If the query contains "recommend", "suggest", "improve", "optimize", "what should" → "recommend"
   - If the query compares two or more entities/periods → "compare"
   - If the query asks about change over time → "trend"
   - If the query checks a standard or regulation → "compliance"
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
