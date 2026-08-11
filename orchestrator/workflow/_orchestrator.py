"""
LangGraph Workflow - Orchestrates agent execution
"""

import asyncio
import json
import os
import re
import sys
import time

sys.path.append("/app")

from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import uuid4

from langgraph.graph import END, StateGraph

from orchestrator.agents import (
    AnalyticsAgent,
    DialogueAgent,
    SPARQLAgent,
    SQLAgent,
    VisualizationAgent,
)
from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent
from orchestrator.agents.capability_agent import CapabilityAgent
from orchestrator.agents.control_agent import ControlAgent
from orchestrator.agents.data_export_agent import DataExportAgent

# CAP-01: Document agent
from orchestrator.agents.document_agent import DocumentAgent
from orchestrator.agents.maintenance_agent import MaintenanceAgent
from orchestrator.agents.planner_agent import PlannerAgent

# Phase 4 agents
from orchestrator.agents.report_agent import ReportAgent
from orchestrator.agents.verifier_agent import VerifierAgent
from orchestrator.llm_manager import TaskType, llm_manager

# B.7: Deterministic analytics engine
from orchestrator.services import provenance as _prov
from orchestrator.services.analytics_engine import AnalysisRequest, AnalyticsEngine

# CAP-03: Persona-aware post-processing
from orchestrator.services.persona_adapter import get_persona_adapter

# CAP-07: Multi-hop reasoning engine
from orchestrator.services.reasoning_engine import get_reasoning_engine

# CAP-04: Compliance standards engine
from orchestrator.services.standards_engine import get_standards_engine
from shared.config import settings
from shared.models import ConversationState, Message
from shared.utils import get_logger

# WIRE-A: i18n service (translate query in, response out)
try:
    from orchestrator.services.i18n_service import I18nService

    _I18N_AVAILABLE = True
except Exception:  # noqa: BLE001 — catches ImportError, SyntaxError, etc.
    _I18N_AVAILABLE = False

from orchestrator.services.disambiguation_service import get_disambiguation_service

# Floor plan service
from orchestrator.services.floor_plan_service import floor_plan_service
from orchestrator.workflow._graph import WorkflowGraphMixin
from orchestrator.workflow._routing import WorkflowRoutingMixin

logger = get_logger(__name__)


# ── T34 what-if intent override ───────────────────────────────────────────────
# Interventional what-ifs ("what would happen if we lowered heating 2 degrees?")
# were LLM-classified as trend → forecast pipeline, bypassing the estimate-recipe
# analytics path entirely (T34 known WARN, fixed 2026-06-12). Override to
# analytics ONLY for hypothetical-intervention phrasing on data-pipeline intents;
# never hijack control / alert / report-intake (routing-precedence rules).
_WHATIF_INTERVENTION_RE = re.compile(
    r"\b(what if|if we|if you|suppose we|were we to)\b.{0,60}"
    r"\b(lower|raise|increase|decrease|reduce|change|adjust|double|halve|"
    r"turn\w* (down|up|off|on)|set)\w*\b"
)
_WHATIF_OVERRIDABLE_INTENTS = frozenset(
    {"trend", "forecast", "analytics", "sensor_data", "general", "compare", "recommend", "anomaly"}
)

# Intents that genuinely need a LIVE datasource — the only ones the datasource-toggle gate
# (_check_locked_capability) may intercept. Informational / how-to / report / capability
# questions that merely mention a disabled-source keyword must pass through (CAVEAT-017 fix).
_LIVE_DATA_INTENTS = frozenset(
    {
        "sensor_data",
        "analytics",
        "trend",
        "forecast",
        "anomaly",
        "compare",
        "comparison",
        "visualization",
        "compliance",
    }
)

# Metrics a bare anomaly query might name. When none is present ("are there any
# unusual readings today?"), SPARQL RAG picks an arbitrary sensor type that often
# has no time-series UUIDs and the pipeline dead-ends at "no data"; we default the
# SPARQL target to temperature (an always-instrumented comfort metric) instead.
_ANOMALY_METRIC_RE = re.compile(
    r"\b(temperature|temp|co2|carbon dioxide|humidity|humid|pm2|pm10|pm1|voc|tvoc|"
    r"illuminance|lux|gas|air quality|noise|sound|oxygen|formaldehyde|no2|methane)\b",
    re.IGNORECASE,
)


def whatif_intent_override(query_lower: str, current_intent: str) -> Optional[str]:
    """Return 'analytics' when an interventional what-if should override routing."""
    if current_intent in _WHATIF_OVERRIDABLE_INTENTS and _WHATIF_INTERVENTION_RE.search(
        query_lower
    ):
        return "analytics"
    return None


# ── General-knowledge answer-length control ───────────────────────────────────
# The user controls answer length by phrasing ("briefly", "in detail",
# "summarize") — auto-detected here — or by an explicit `answer_length` hint on
# state.intermediate_results. Detected length maps to a prompt directive (the
# fast model has a fixed max_tokens, so length is steered by instruction, which
# is reliable across OpenAI and Ollama).
_LENGTH_SHORT_KW = (
    "in short",
    "briefly",
    "in brief",
    "be brief",
    "one line",
    "one-line",
    "one sentence",
    "in a sentence",
    "quick answer",
    "short answer",
    "tl;dr",
    "tldr",
    "concise",
    "just the answer",
    "in a nutshell",
    "keep it short",
)
_LENGTH_LONG_KW = (
    "in detail",
    "in-depth",
    "in depth",
    "detailed",
    "explain fully",
    "comprehensive",
    "elaborate",
    "long answer",
    "thorough",
    "deep dive",
    "full explanation",
    "explain thoroughly",
    "as much detail",
    "everything about",
)
_LENGTH_SUMMARY_KW = (
    "summarize",
    "summarise",
    "summary",
    "in summary",
    "overview",
    "key points",
    "main points",
    "bullet points",
    "high level",
    "high-level",
)
_LENGTH_DIRECTIVES = {
    "short": "Answer in 1-2 short sentences. Be direct — no preamble, no caveats.",
    "summary": (
        "Provide a concise summary: 3-5 sentences or a short bulleted list of the "
        "key points. No filler."
    ),
    "long": (
        "Provide a thorough, well-structured explanation with relevant detail, "
        "examples, and context. Use short headings or bullet points where they aid "
        "readability."
    ),
    "medium": "Provide a clear, helpful answer of about one short paragraph.",
}


def _detect_answer_length(query: str, explicit: Optional[str] = None) -> str:
    """Pick answer length (short|summary|long|medium) from phrasing or explicit hint.

    Precedence: explicit hint → short → long → summary → medium default.
    """
    if explicit and isinstance(explicit, str) and explicit.lower() in _LENGTH_DIRECTIVES:
        return explicit.lower()
    q = (query or "").lower()
    if any(k in q for k in _LENGTH_SHORT_KW):
        return "short"
    if any(k in q for k in _LENGTH_LONG_KW):
        return "long"
    if any(k in q for k in _LENGTH_SUMMARY_KW):
        return "summary"
    return "medium"


# ── Live-data need detection (general_knowledge node) ─────────────────────────
# Heuristic gate: only questions that need CURRENT information (which the LLM
# cannot know from its training cutoff) trigger a live fetch. Everything else
# stays a pure-LLM answer. Weather is matched first (more specific) than the
# generic "current/latest" web signals.
_WEATHER_KW = (
    "weather",
    "forecast",
    "raining",
    "is it raining",
    "going to rain",
    "snowing",
    "is it sunny",
    "is it cloudy",
    "how hot is it",
    "how cold is it",
    "how warm is it",
    "temperature outside",
    "humidity outside",
    "wind speed",
    "how's the weather",
    "hows the weather",
    "what's the weather",
    "whats the weather",
)
_LIVE_WEB_KW = (
    "latest",
    "current",
    "currently",
    "right now",
    "as of today",
    "as of now",
    "today's",
    "todays",
    "this week",
    "this month",
    "this year",
    "recent",
    "recently",
    "news",
    "who won",
    "who is winning",
    "score",
    "results of",
    "price of",
    "stock price",
    "share price",
    "exchange rate",
    "how much is",
    "release date",
    "newest",
    "up to date",
    "up-to-date",
    "breaking",
    "who is the current",
    "what is the latest",
)
# Trailing time/qualifier words to strip off an extracted location.
_LOC_TRAILING = (
    "right now",
    "now",
    "today",
    "tonight",
    "tomorrow",
    "currently",
    "this week",
    "this weekend",
    "this morning",
    "this evening",
    "please",
)


def _extract_location(query: str) -> Optional[str]:
    """Pull a place name out of a weather question, or None if none is present.

    Matches a preposition (in/at/for/around/near) as a whole word — so "at" does
    not match inside "what" — and takes the LAST such phrase as the location.
    """
    import re as _re

    q = query.strip().rstrip("?.!")
    matches = list(
        _re.finditer(
            r"\b(?:in|at|for|around|near)\s+([A-Za-z][A-Za-z .,'\-]*)",
            q,
            _re.IGNORECASE,
        )
    )
    if not matches:
        return None
    loc = matches[-1].group(1).strip()
    loc_l = loc.lower()
    for t in _LOC_TRAILING:
        if loc_l.endswith(t):
            loc = loc[: len(loc) - len(t)].strip().rstrip(",")
            loc_l = loc.lower()
    return loc if len(loc) >= 2 else None


def _detect_live_data_need(query: str) -> Optional[Tuple[str, str]]:
    """Return ("weather", location) or ("web", query), else None.

    Heuristic — intentionally conservative so static-knowledge questions don't
    pay for a network round-trip. The answering node degrades to a plain LLM
    answer whenever the fetch yields nothing.
    """
    if not query:
        return None
    q = query.lower()
    if any(k in q for k in _WEATHER_KW):
        return ("weather", _extract_location(query) or "")
    if any(k in q for k in _LIVE_WEB_KW):
        return ("web", query.strip())
    return None


def _live_data_need_from_hint(hint: Optional[Any], query: str) -> Optional[Tuple[str, str]]:
    """Map the classifier's `live_data` hint to a (kind, arg) tuple, or None.

    This is the PRIMARY (smart) signal — the dialogue LLM already saw the query
    and conversation history. `_detect_live_data_need` is the keyword fallback.
    """
    if not isinstance(hint, dict):
        return None
    t = str(hint.get("type") or "").lower()
    if t == "weather":
        loc = (hint.get("location") or _extract_location(query) or "").strip()
        return ("weather", loc)
    if t == "web":
        return ("web", (hint.get("query") or query or "").strip())
    return None


class WorkflowOrchestrator(WorkflowGraphMixin, WorkflowRoutingMixin):
    """LangGraph-based conversation workflow.

    Phase 17 (2026-05-29) — the monolithic workflow.py was split into a package:
      * `_graph.py` (WorkflowGraphMixin) — `_build_graph()`
      * `_routing.py` (WorkflowRoutingMixin) — 4 downstream `_route_from_*` methods
      * `_orchestrator.py` — node implementations, `_route_from_dialogue`,
                              `_user_wants_visualization`, `_safe_node`, `_wants_document`

    Python MRO resolves attribute lookups across the mixins: when the graph
    mixin calls `self._dialogue_node`, MRO finds it on this class (defined below).
    """

    def __init__(self, redis_manager=None, postgres_manager=None):
        # Initialize agents
        self.dialogue_agent = DialogueAgent()
        self.sparql_agent = SPARQLAgent()
        self.sql_agent = SQLAgent()
        self.analytics_agent = AnalyticsAgent()
        self.viz_agent = VisualizationAgent()
        # Phase 4 agents
        self.report_agent = ReportAgent()
        self.export_agent = DataExportAgent()
        self.planner_agent = PlannerAgent()
        self.anomaly_agent = AnomalyDetectionAgent()
        # CAP-01: Document agent
        self.document_agent = DocumentAgent()
        self.control_agent = ControlAgent()
        self.maintenance_agent = MaintenanceAgent()
        self.capability_agent = CapabilityAgent()
        self.verifier_agent = VerifierAgent()
        self.redis_manager = redis_manager
        self.postgres_manager = postgres_manager
        self.response_cache = None  # injected by main.py lifespan after Redis is ready
        self.agent_memory = None  # injected by main.py lifespan after Qdrant is ready
        self.smart_cache = None  # injected by main.py lifespan after Redis is ready
        # B.7: Deterministic analytics engine (no LLM needed for known analysis types)
        self.analytics_engine = AnalyticsEngine()
        # WIRE-A: i18n service singleton (stateless, lazy-init)
        self._i18n: "I18nService | None" = None
        if _I18N_AVAILABLE:
            try:
                from orchestrator.llm_manager import llm_manager as _llm

                self._i18n = I18nService(llm_manager=_llm)
                logger.info("i18n service initialized")
            except Exception as _ie:
                logger.warning(f"i18n service init failed (non-fatal): {_ie}")
        # CAP-03: Persona adapter singleton
        self._persona_adapter = get_persona_adapter()
        # CAP-04: Standards engine singleton
        self._standards_engine = get_standards_engine()
        # CAP-07: Multi-hop reasoning engine
        self._reasoning_engine = get_reasoning_engine()

        # Load sensor map
        self.sensor_map = {}
        try:
            if os.path.exists(settings.SENSOR_MAP_PATH):
                with open(settings.SENSOR_MAP_PATH, "r", encoding="utf-8") as f:
                    self.sensor_map = json.load(f)
                logger.info(f"Loaded {len(self.sensor_map)} sensors from cache")
            else:
                logger.warning(
                    f"{settings.SENSOR_MAP_PATH} not found. Run scripts/cache_sensor_map.py"
                )
        except Exception as e:
            logger.error(f"Failed to load sensor map: {e}")

        # Configuration: Use semantic agent by default, fallback to SPARQL
        self.use_semantic_ontology = settings.USE_SEMANTIC_ONTOLOGY
        self.ontology_mode = settings.ONTOLOGY_QUERY_MODE

        logger.info(
            f"Ontology query mode: {self.ontology_mode}, Use semantic: {self.use_semantic_ontology}"
        )

        # Build workflow graph
        self.graph = self._build_graph()

    # Phase 17C (2026-05-29) — `_build_graph()` was extracted to
    # `workflow/_graph.py`'s `WorkflowGraphMixin`.  See the inheritance line
    # above.  All node methods and `_safe_node` remain here because they ARE
    # the orchestrator (the mixin just composes them into a graph).

    def _safe_node(self, node_fn, node_name: str):
        """
        Wrap a node function with try/except for graceful degradation.
        On unhandled exception, the pipeline continues with a user-friendly
        error stored in intermediate_results rather than crashing.
        """

        async def wrapper(state: ConversationState) -> ConversationState:
            try:
                return await node_fn(state)
            except Exception as e:
                logger.error(f"Node '{node_name}' failed: {e}", exc_info=True)
                friendly = self._user_friendly_error(e)
                state.intermediate_results[f"{node_name}_error"] = str(e)
                # For data nodes, ensure downstream nodes see empty-but-valid data
                if node_name == "sparql":
                    state.intermediate_results["sparql_result"] = {
                        "success": False,
                        "error": str(e),
                    }
                    state.query_results = {}
                elif node_name == "sql":
                    state.intermediate_results["sql_result"] = {
                        "success": False,
                        "error": str(e),
                    }
                    state.query_results = {"data": []}
                elif node_name == "analytics":
                    state.intermediate_results["analytics_result"] = {
                        "success": False,
                        "error": str(e),
                    }
                # Store the friendly error for the response node to pick up
                state.intermediate_results.setdefault("degraded_services", []).append(
                    {"node": node_name, "message": friendly}
                )
                return state

        return wrapper

    # Short affirmations that, after a chart offer, mean "yes, draw the chart".
    # Matched by EXACT equality (after lowercasing + trimming trailing punctuation)
    # so a "yes" buried in a substantive sentence never triggers this path.
    _CHART_AFFIRMATIONS = frozenset(
        [
            "yes",
            "yes please",
            "yeah",
            "yep",
            "yup",
            "sure",
            "ok",
            "okay",
            "ok please",
            "yes ok",
            "go ahead",
            "please do",
            "do it",
            "please",
            "y",
            "absolutely",
            "of course",
            "sounds good",
            "yes thanks",
            "yes thank you",
            "yes please do",
            "plot it",
            "plot it please",
            "show it",
            "show me",
            "draw it",
            "graph it",
            "chart it",
            "yes go ahead",
            "go for it",
            "that would be great",
            "great",
            "yes do it",
            "do that",
            "yes show me",
        ]
    )

    # Phrases an assistant uses when it OFFERS (but did not yet produce) a chart.
    _CHART_OFFER_MARKERS = (
        "create a graph",
        "create a chart",
        "graph for you",
        "chart for you",
        "visual representation",
        "see a graph",
        "see a chart",
        "i can plot",
        "i can create",
        "i can show",
        "show you a graph",
        "show you a chart",
        "would you like a chart",
        "would you like a graph",
        "would you like me to",
        "generate a chart",
        "generate a graph",
        "plot the graph",
        "visualize",
        "visualise",
        "couldn't render the chart",
        "could not render the chart",
    )

    def _affirmation_to_chart(self, state: ConversationState) -> Optional[str]:
        """If the user just affirmed a chart the assistant offered, return the
        chart request to run; otherwise ``None``.

        Detection requires BOTH: (a) the current message is a short, exact-match
        affirmation, and (b) the most recent assistant message offered a chart.
        The returned query is derived from the most recent prior USER message so
        the visualization node can re-fetch the series and plot it.
        """
        msgs = state.messages or []
        if len(msgs) < 3:
            return None
        cur = (msgs[-1].content or "").strip().lower().rstrip("!. ")
        if not cur or len(cur.split()) > 5 or cur not in self._CHART_AFFIRMATIONS:
            return None

        last_assistant = None
        prev_user = None
        for m in reversed(msgs[:-1]):
            role = getattr(m, "role", "") or ""
            if last_assistant is None and role == "assistant":
                last_assistant = (m.content or "").lower()
                continue
            if last_assistant is not None and role == "user":
                prev_user = (m.content or "").strip()
                break

        if not last_assistant or not prev_user:
            return None
        if not any(mark in last_assistant for mark in self._CHART_OFFER_MARKERS):
            return None

        # If the prior query was already a chart request, just re-run it (the
        # visualization path now produces a chart reliably).  Otherwise wrap it
        # into an explicit plot request so it routes to the visualization node.
        if self._user_wants_visualization(prev_user):
            return prev_user
        return f"plot {prev_user} as a line chart"

    def _spawn_background(self, coro) -> None:
        """Run a coroutine fire-and-forget without blocking the request path.

        Keeps a strong reference until completion so the task is not garbage-
        collected mid-flight (a known asyncio footgun).
        """
        if not hasattr(self, "_bg_tasks"):
            self._bg_tasks = set()
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _generate_title_bg(self, state: ConversationState) -> None:
        """Background conversation-title generation (cosmetic; non-blocking)."""
        try:
            title = await self.dialogue_agent.context_manager.generate_title(
                state.messages[0].content
            )
            state.title = title
            logger.info(f"🏷️ Title generated (bg): {title}")
            if self.redis_manager and state.user_id:
                await self.redis_manager.add_conversation_to_user(
                    state.user_id, state.conversation_id, title
                )
        except Exception as e:
            logger.error(f"Failed to generate title (bg): {e}")

    async def _dialogue_node(self, state: ConversationState) -> ConversationState:
        """Process dialogue using LLM-based intent detection"""
        logger.info("Executing dialogue node with LLM-based intent detection")

        # WIRE-A: i18n — detect language and translate query to English
        _user_lang = "en"
        if self._i18n and state.messages:
            try:
                _raw_query = state.messages[-1].content
                _en_query, _user_lang = await self._i18n.to_english(_raw_query)
                if _user_lang != "en":
                    logger.info(f"i18n: translated query from {_user_lang} to English")
                    # Replace last message content with translated version for pipeline
                    state.messages[-1] = Message(
                        role=state.messages[-1].role,
                        content=_en_query,
                        metadata=state.messages[-1].metadata,
                    )
                state.intermediate_results["_user_lang"] = _user_lang
            except Exception as _i18n_err:
                logger.debug(f"i18n input translation skipped: {_i18n_err}")

        # Auto-titling for new conversations — fire-and-forget so the ~1s title
        # LLM call does not block the user-facing response. The title is cosmetic
        # (sidebar label) and is written to Redis asynchronously.
        if len(state.messages) == 1 and state.title == "New Conversation":
            self._spawn_background(self._generate_title_bg(state))

        # B.3: Inject relevant user memories as context for the dialogue agent
        _fresh_session = state.intermediate_results.get("fresh_session", False)
        from orchestrator.services.agent_memory import CROSS_SESSION_MEMORY_ENABLED

        if (
            self.agent_memory
            and state.user_id
            and CROSS_SESSION_MEMORY_ENABLED
            and not _fresh_session
        ):
            try:
                user_query = state.messages[-1].content if state.messages else ""
                memory_context = await self.agent_memory.retrieve_context(state.user_id, user_query)
                if memory_context:
                    state.intermediate_results["memory_context"] = memory_context
            except Exception as _mem_err:
                logger.debug(f"Agent memory retrieve skipped: {_mem_err}")

        # ── Session-context: resolve pending clarification answer ─────────────
        # If the previous turn asked a clarification question (e.g. "which sensor?"),
        # parse the user's current message for an answer and accumulate it.
        _pending_qtype = state.intermediate_results.get("pending_clarification_type")
        _user_ctx: dict = state.intermediate_results.get("user_context", {})
        if _pending_qtype and state.messages:
            try:
                _disambig_svc_early = get_disambiguation_service()
                _ctx_answer = _disambig_svc_early.extract_clarification_answer(
                    state.messages[-1].content, _pending_qtype
                )
                if _ctx_answer:
                    _user_ctx = {**_user_ctx, **_ctx_answer}
                    state.intermediate_results["user_context"] = _user_ctx
                    logger.info(
                        f"[disambiguation] Session context updated from answer: {_ctx_answer}"
                    )
            except Exception as _ctx_err:
                logger.debug(f"Clarification answer extraction skipped: {_ctx_err}")
            # Clear the pending type regardless — don't keep re-asking
            state.intermediate_results.pop("pending_clarification_type", None)

        # ── Affirmation-to-chart follow-up ────────────────────────────────────
        # If the previous assistant turn OFFERED a chart ("I can create a graph
        # for you" / the honesty-guard note) and the user simply affirms ("yes
        # please", "sure", "go ahead"), rewrite that affirmation into the chart
        # request the prior substantive query implied, so it flows through the
        # visualization path instead of being treated as small-talk.
        _affirm_fired = False
        try:
            _affirm_rewrite = self._affirmation_to_chart(state)
            if _affirm_rewrite:
                _orig = state.messages[-1].content
                _meta = dict(state.messages[-1].metadata or {})
                _meta["original_query"] = _orig
                state.messages[-1] = Message(
                    role=state.messages[-1].role,
                    content=_affirm_rewrite,
                    metadata=_meta,
                )
                state.intermediate_results["affirmation_followup"] = {
                    "original": _orig,
                    "rewritten": _affirm_rewrite,
                }
                logger.info(
                    f"[affirm] chart affirmation rewritten: {_orig!r} -> {_affirm_rewrite!r}"
                )
                _affirm_fired = True
        except Exception as _aff_err:
            logger.debug(f"[affirm] follow-up handling skipped: {_aff_err}")

        # ── Co-reference resolution ───────────────────────────────────────────
        # Rewrite context-dependent follow-ups ("and humidity there?") into
        # self-contained queries BEFORE intent detection so entity extraction and
        # the downstream SPARQL node (both read messages[-1].content) resolve
        # references like "there"/"that" to the prior turn's entities.
        if not _affirm_fired:
            try:
                _standalone = await self.dialogue_agent.rewrite_to_standalone(state)
                if _standalone:
                    _orig = state.messages[-1].content
                    _meta = dict(state.messages[-1].metadata or {})
                    _meta["original_query"] = _orig
                    state.messages[-1] = Message(
                        role=state.messages[-1].role,
                        content=_standalone,
                        metadata=_meta,
                    )
                    state.intermediate_results["coref_rewrite"] = {
                        "original": _orig,
                        "rewritten": _standalone,
                    }
                    logger.info(f"[coref] follow-up rewritten: {_orig!r} -> {_standalone!r}")
            except Exception as _coref_err:
                logger.debug(f"[coref] resolution skipped: {_coref_err}")

        # NEW: Get LLM-based intent detection result
        intent_result = await self.dialogue_agent.detect_intent(state)

        # Extract fields from LLM response (New Structure)
        intent = intent_result.get("intent", "general")
        entities = intent_result.get("entities") or []
        required_analytics = intent_result.get("required_analytics") or []
        time_range = intent_result.get("time_range") or {}
        direct_response = intent_result.get("response", "")
        explanation = intent_result.get("explanation", "")
        clarification_question = intent_result.get("clarification_question", "")
        discovery_filter = intent_result.get("discovery_filter")

        # ── Follow-up context resolution ──────────────────────────────────────
        # Standard/regulation names (ASHRAE, WELL, BREEAM, …) are not building
        # entities.  For contextual follow-ups the LLM often returns only the
        # standard name with no zone/sensor.  Detect that case and (a) reuse
        # the existing query_results from the prior turn and (b) inherit the
        # real building entities so downstream nodes stay coherent.
        _STANDARD_NAMES = {
            "ashrae",
            "well",
            "breeam",
            "leed",
            "en15251",
            "en 15251",
            "iso",
            "iea",
            "smacna",
            "nfpa",
            "cibse",
            "iesve",
            "ies ve",
            "ashrae 55",
            "ashrae 62",
            "ashrae 90",
            "ashrae standard",
        }
        _CONTEXTUAL_INTENTS = {"compliance", "compare", "trend", "recommend"}

        if intent in _CONTEXTUAL_INTENTS:
            building_entities = [
                e for e in entities if not any(s in e.lower() for s in _STANDARD_NAMES)
            ]

            if not building_entities:
                # No real building entities — inherit from prior turn
                prior_entities = state.intermediate_results.get("entities") or []
                if prior_entities:
                    entities = list(prior_entities)
                    logger.info(
                        f"[context] Follow-up '{intent}' — inherited {len(entities)} "
                        f"entities from prior turn: {entities}"
                    )

                # If the prior turn already fetched sensor data, skip SPARQL+SQL
                _prior_data = state.query_results
                _has_prior_data = bool(isinstance(_prior_data, dict) and _prior_data.get("data"))
                if _has_prior_data:
                    state.intermediate_results["use_existing_query_results"] = True
                    logger.info(
                        f"[context] Reusing existing query_results "
                        f"({len(_prior_data['data'])} rows) for '{intent}' follow-up"
                    )

        # Backward compatibility mapping
        is_general = intent == "general"
        analytics_required = (intent == "analytics") or (len(required_analytics) > 0)
        # Contextual follow-up intents always need the full SPARQL→SQL→Analytics pipeline
        if intent in _CONTEXTUAL_INTENTS:
            analytics_required = True
        sparql_query = ""  # No longer generated by DialogueAgent

        start_date = time_range.get("start")
        end_date = time_range.get("end")

        logger.info(f"📊 Intent Analysis:")
        logger.info(f"   ├─ Intent: {intent}")
        logger.info(f"   ├─ Entities: {entities}")
        logger.info(f"   ├─ Analytics Required: {analytics_required}")

        # Store in state for routing decisions and downstream agents
        state.intermediate_results["llm_intent"] = intent_result
        state.intermediate_results["intent"] = intent
        state.intermediate_results["entities"] = entities
        state.intermediate_results["required_analytics"] = required_analytics
        state.intermediate_results["analytics_required"] = analytics_required
        state.intermediate_results["start_date"] = start_date
        state.intermediate_results["end_date"] = end_date
        # Reserved key per CLAUDE.md shared-state contract — analytics_agent and
        # verifier_agent read it, but it was never stored (fix 2026-06-12: both
        # always saw {} and lost the time-range context).
        state.intermediate_results["time_range"] = time_range or {}
        state.intermediate_results["explanation"] = explanation
        # Phase 4.1 new fields
        state.intermediate_results["export_format"] = intent_result.get("export_format")
        state.intermediate_results["report_type"] = intent_result.get("report_type")
        state.intermediate_results["recommendation_domain"] = intent_result.get(
            "recommendation_domain"
        )
        # Smart live-data routing hint from the classifier (general_knowledge node
        # reads this first; falls back to a keyword heuristic if absent).
        state.intermediate_results["live_data_hint"] = intent_result.get("live_data")
        # Phase 0 (cross-cutting): persist G1 six-tuple for every turn
        if "g1_taxonomy" in intent_result:
            state.intermediate_results["g1_taxonomy"] = intent_result["g1_taxonomy"]

        # T05: HBCO lay-term resolution — attach concept matches for SPARQL + analytics.
        # Non-fatal: failure only loses concept enrichment, never breaks routing.
        try:
            from orchestrator.services.concept_resolver import concept_resolver as _cr

            _concept_query = state.messages[-1].content if state.messages else ""
            _concepts = await _cr.resolve(_concept_query)
            state.intermediate_results["concepts"] = [c.to_dict() for c in _concepts]
            if _concepts:
                logger.info(f"[dialogue] HBCO concepts: {[c.concept_id for c in _concepts]}")
        except Exception as _cr_err:
            logger.debug(f"[dialogue] concept resolution skipped: {_cr_err}")
            state.intermediate_results.setdefault("concepts", [])

        # BUG-123: routing contract, concept stage. Lay-term resolution is the only
        # signal that separates a reading question worded in plain English ("is it
        # stuffy in RM157?") from a vocabulary question ("what is stuffiness?"), and
        # it is not available at the earlier stages — so the rule that keeps
        # building questions out of the open-domain answerer runs here.
        try:
            from orchestrator.services.routing_contract import apply_contract as _apply_rc

            _rc_state = {
                "intent": intent,
                "concepts": state.intermediate_results.get("concepts", []),
                "entities": state.intermediate_results.get("entities", []),
            }
            _rc_query = state.messages[-1].content if state.messages else ""
            if _apply_rc(_rc_query, _rc_state, stage="concept"):
                intent = _rc_state["intent"]
                state.intermediate_results["intent"] = intent
                if _rc_state.get("analytics"):
                    state.intermediate_results["analytics_required"] = True
                    state.analytics_required = True
                clarification_question = ""
        except Exception as _rc_err:  # routing must survive a broken rule
            logger.warning(f"[routing-contract] concept stage skipped: {_rc_err}")

        # TODO-050: concept-aware grounding override. When a lay-term resolves to a
        # building SENSOR class (e.g. "wind" -> Wind_Speed_Sensor via the exterior
        # weather feed) but the LLM asked for an external location/building/city, the
        # clarification is spurious — the location IS this building. Route to
        # sensor_data instead of deflecting. Tightly guarded (sensor concept AND a
        # location-style clarification) so genuine "which room?" clarifications stand.
        if intent in ("clarification", "general"):
            _resolved = state.intermediate_results.get("concepts", []) or []
            _has_sensor = any(
                str(bc).endswith("_Sensor")
                for c in _resolved
                for bc in (c.get("brick_classes", []) if isinstance(c, dict) else [])
            )
            _loc_clarify = any(
                w in (clarification_question or "").lower()
                for w in ("location", "building", "city", "region", "which city", "where are you")
            )
            if _has_sensor and _loc_clarify:
                logger.info(
                    "[intent-override] concept %s maps to a building sensor — routing "
                    "'%s' -> 'sensor_data' (location is this building)",
                    [c.get("concept_id") for c in _resolved if isinstance(c, dict)],
                    intent,
                )
                intent = "sensor_data"
                state.intermediate_results["intent"] = "sensor_data"
                clarification_question = ""

        # T34: What-if / scenario estimation — detect phrasing and attach recipe hint.
        # Keeps recipe selection in YAML (estimate kind); routing stays analytics.
        import re as _re_whatif

        _wq = (state.messages[-1].content if state.messages else "").lower()
        _WHATIF_RE = _re_whatif.compile(
            r"\b(what if|what would happen|what happens|if we (lower|raise|increase|decrease|reduce|"
            r"turn (down|up)|change|adjust|double|halve)|how (much|would|many) .{0,30}"
            r"(sav|reduc|lower|increas|decreas|would|save|chang))\b"
        )
        if _WHATIF_RE.search(_wq):
            # Determine which estimate recipe applies based on keywords
            if any(
                w in _wq
                for w in ("setpoint", "heating", "cooling", "temperature", "thermostat", "degree")
            ):
                _estimate_recipe = "hvac_setpoint_sensitivity"
            elif any(
                w in _wq for w in ("occupancy", "people", "persons", "occupant", "crowded", "busy")
            ):
                _estimate_recipe = "occupancy_impact_estimate"
            else:
                _estimate_recipe = "hvac_setpoint_sensitivity"  # default estimate
            state.intermediate_results["whatif_recipe"] = _estimate_recipe
            state.intermediate_results["is_whatif_query"] = True
            logger.info(f"[dialogue] what-if query detected → recipe={_estimate_recipe}")
            _wi_intent = state.intermediate_results.get("intent", "")
            _wi_override = whatif_intent_override(_wq, _wi_intent)
            if _wi_override:
                state.intermediate_results["intent"] = _wi_override
                logger.info(
                    f"[dialogue] interventional what-if → intent override "
                    f"{_wi_intent} → {_wi_override} (estimate recipe path)"
                )

        # T32: Benchmark detection — recognise peer/sector comparison questions.
        _BENCHMARK_RE = _re_whatif.compile(
            r"\b(benchmark|peer|similar buildings?|sector average|how does .{0,30} compare|"
            r"industry standard|typical (university|office|building)|above average|below average|"
            r"national average|good for a building|efficient compared)\b"
        )
        if _BENCHMARK_RE.search(_wq):
            if any(w in _wq for w in ("energy", "electricity", "kwh", "consumption")):
                _bench_recipe = "energy_intensity_benchmark"
            elif any(w in _wq for w in ("co2", "air quality", "carbon dioxide", "ventilation")):
                _bench_recipe = "co2_benchmark"
            else:
                _bench_recipe = "energy_intensity_benchmark"
            state.intermediate_results["benchmark_recipe"] = _bench_recipe
            state.intermediate_results["is_benchmark_query"] = True
            logger.info(f"[dialogue] benchmark query detected → recipe={_bench_recipe}")

        # T22: Automation-capability detection — "can the building automatically X when Y?"
        # Archetype-B: honest capability answer from system state, not a hallucinated yes.
        # Fires when the question asks ABOUT capability (not when creating a rule → alert intent).
        # Overrides intent to automation_capability so _REGISTERED_NODES routes correctly.
        _AUTOMATE_CAP_RE = _re_whatif.compile(
            r"\b("
            r"can (the building|it|the system|this building) (auto|automatically|detect|"
            r"monitor|watch|track|respond|alert|notify|send|adjust|switch|learn|manage)|"
            r"(will|would|could|does|should) (the building|it|the system) (auto|automatically|"
            r"detect|monitor|watch|respond|alert|notify|adjust|manage)|"
            r"is (it|the building|the system|there a way) "
            r"(possible|able|capable|configured|set up|designed)? ?(to auto|to automatically)|"
            r"(by itself|on its own|without (me|manual intervention|anyone))|"
            r"set (it|the system) (to automatically|up to auto)"
            r")\b"
        )
        _cur_intent = state.intermediate_results.get("intent", "")
        if _AUTOMATE_CAP_RE.search(_wq) and _cur_intent not in ("alert",):
            state.intermediate_results["is_automation_capability_query"] = True
            state.intermediate_results["intent"] = "automation_capability"
            logger.info(
                "[dialogue] automation-capability query detected → intent=automation_capability"
            )

        # T35: Personalised preference management detection.
        # Detects "remember I prefer...", "forget my preferences", "what are my preferences?"
        # Handles conversationally; requires authenticated user (guests declined).
        _PREF_STORE_RE = _re_whatif.compile(
            r"\b(remember (that )?(i|my)|i (like|prefer|want|need) (it |the |a )?("
            r"warmer|cooler|hotter|colder|quieter|brighter|darker|drier|more humid)|"
            r"my (ideal|preferred|comfortable|perfect) (temperature|humidity|co2|noise|light|"
            r"lux|brightness)|"
            r"set my (temperature|comfort|preference|humidity|noise|light) (preference|setting)s?|"
            r"i find .{0,30} (too (warm|cold|hot|cool|loud|bright|dark|humid|dry))|"
            r"comfortable (for me|at|between|around))\b"
        )
        _PREF_FORGET_RE = _re_whatif.compile(
            r"\b(forget (my|that|all|the) (preference|setting|temperature|comfort|"
            r"humidity|noise|light|lux)|clear my preference|reset my setting)\b"
        )
        _PREF_LIST_RE = _re_whatif.compile(
            r"\b(what are my (preference|setting|comfort|personalisation)s?|"
            r"show my (preference|setting|personalisation)s?|"
            r"list my (preference|setting)s?|"
            r"do i have any preference|my personal setting)\b"
        )
        if _PREF_LIST_RE.search(_wq) or _PREF_FORGET_RE.search(_wq) or _PREF_STORE_RE.search(_wq):
            state.intermediate_results["preference_management_detected"] = True
            state.intermediate_results["preference_raw_query"] = (
                state.messages[-1].content if state.messages else _wq
            )
            logger.info("[dialogue] preference management phrase detected")

        # ── Re-sync after deterministic overrides (fix 2026-06-12) ─────────
        # The T22 / T34 / benchmark overrides above write the corrected intent
        # to intermediate_results["intent"], but the dispatch chain below (and
        # therefore state.current_intent, which _route_from_dialogue reads)
        # switched on the stale local variable — so overrides never reached
        # live routing. Re-bind the local from the canonical value.
        _post_override_intent = state.intermediate_results.get("intent", intent)
        if _post_override_intent != intent:
            intent = _post_override_intent
            is_general = intent == "general"

        # ── Data-driven disambiguation (context-aware) ────────────────────
        # Check BEFORE routing: use the session context to avoid re-asking
        # questions the user already answered in a prior turn.
        _user_query_raw = state.messages[-1].content if state.messages else ""
        _user_ctx = state.intermediate_results.get("user_context", {})
        try:
            _disambig_svc = get_disambiguation_service()
            _clarify_msg, _ctx_updates, _pending_type = (
                await _disambig_svc.check_and_clarify_with_context(_user_query_raw, _user_ctx)
            )
            if _ctx_updates:
                _user_ctx = {**_user_ctx, **_ctx_updates}
                state.intermediate_results["user_context"] = _user_ctx
            if _pending_type:
                state.intermediate_results["pending_clarification_type"] = _pending_type
            if _clarify_msg:
                logger.info("[disambiguation] Ambiguous sensor ref — returning clarification")
                state.current_intent = "clarification"
                state.needs_clarification = True
                state.intermediate_results["dialogue_response"] = _clarify_msg
                state.intermediate_results["intent"] = "clarification"
                return state
        except Exception as _da_err:
            logger.debug(f"Disambiguation check skipped: {_da_err}")
        # ─────────────────────────────────────────────────────────────────

        if intent == "clarification":
            state.current_intent = "clarification"
            state.needs_clarification = True
            state.clarification_question = clarification_question
            state.intermediate_results["dialogue_response"] = (
                clarification_question
                or "Could you please provide more details about your question?"
            )

        elif intent == "discovery":
            state.current_intent = "discovery"
            # For spatial/zone queries, skip sensor-map response — let SPARQL handle it
            _uq = (state.messages[-1].content if state.messages else "").lower()
            _spatial = ["zone", "floor", "room", "space", "level", "area", "location"]
            if any(w in _uq for w in _spatial):
                pass  # dialogue_response intentionally not set; SPARQL node will answer
            else:
                # One pipeline for "what does this building have": discovery groups
                # by the SAME ontology census the capability path uses, so the two
                # question families cannot drift apart or disagree.
                _raw_q = state.messages[-1].content if state.messages else ""
                _census = await self._ontology_census(_raw_q or "sensors")
                _generic = None
                try:
                    from orchestrator.services.ontology_inventory import (
                        is_inventory_question,
                        render_census,
                    )

                    if is_inventory_question(_raw_q):
                        from orchestrator.services.building_context import (
                            resolve_building_context,
                        )

                        _bname = resolve_building_context(
                            state.building_id or settings.BUILDING_ID
                        ).name
                        _generic = render_census(_census, _bname)
                        if not _generic:
                            # The building genuinely holds nothing of that kind. Say
                            # so — falling through to the sensor lister answered
                            # "which meters do we have?" by listing all 600 sensors,
                            # which reads as if they were the meters.
                            from orchestrator.services.grounding_guard import (
                                enablement_hint,
                                SUBJECT_EQUIPMENT,
                            )

                            _generic = (
                                f"I couldn't find anything of that kind in "
                                f"**{_bname}**'s ontology, so there is nothing to list.\n\n"
                                + enablement_hint(SUBJECT_EQUIPMENT)
                            )
                except Exception as _inv_err:
                    logger.warning(f"[discovery] inventory render skipped: {_inv_err}")

                state.intermediate_results["dialogue_response"] = _generic or (
                    self._handle_sensor_discovery(discovery_filter, entities, census=_census)
                )

        elif intent in ("control",):
            state.current_intent = "control"

        elif intent == "greeting":
            state.current_intent = "greeting"
            state.intermediate_results["dialogue_response"] = (
                direct_response
                or "Hello! I'm OntoSage, your smart building assistant. How can I help you today?"
            )

        elif intent in ("planner",):
            state.current_intent = "planner"

        elif intent in ("report",):
            # Report needs SPARQL + SQL first; planner handles that
            state.current_intent = "report"

        elif intent in ("anomaly",):
            state.current_intent = "anomaly"

        elif intent in ("export",):
            state.current_intent = "export"

        elif intent == "capability":
            # Phase 0: off-ontology / building capability queries
            state.current_intent = "capability"

        elif intent in ("compare", "trend", "recommend", "compliance"):
            # Preserve specific intent — each routes via SPARQL→SQL→analytics pipeline
            # but the analytics node handles them differently (recommend→_recommend_node, etc.)
            logger.info(f"☕ Intent '{intent}' routes via SPARQL→SQL→Analytics")
            state.current_intent = intent

        elif intent == "visualization":
            state.current_intent = "visualization"

        elif intent == "floor_plan":
            state.current_intent = "floor_plan"

        elif intent == "spatial_query":
            state.current_intent = "spatial_query"

        elif intent == "maintenance":
            state.current_intent = "maintenance"

        elif intent in ("complaint", "feedback", "safety_report", "suggestion"):
            # Phase 19 — report-intake categories pass through to _report_intake_node
            state.current_intent = intent

        elif intent in ("sensor_data", "metadata"):
            # These flow through the SPARQL pipeline as before
            state.current_intent = intent

        elif is_general:
            # Open-domain general-knowledge question. The dedicated
            # _general_knowledge_node generates the answer (with length control
            # and conversation context) — do NOT inject a canned reply here.
            # Preserve any draft the classifier produced as a fallback hint only.
            state.current_intent = "general_knowledge"
            if direct_response:
                state.intermediate_results["general_knowledge_draft"] = direct_response

        else:
            # Registry fallthrough (fix 2026-06-12): YAML-registered intents that
            # this legacy chain doesn't name (alert, automation_capability,
            # preference_management, per-building overlays like lab_booking) were
            # falling into the sparql default — "list my alerts" ran the DATA
            # pipeline and returned power sensors. If the intent registry knows
            # the label, preserve it so _route_from_dialogue can dispatch it.
            _registry_known = False
            try:
                from orchestrator.intents import get_intent_registry as _gir

                _registry_known = (
                    _gir(getattr(state, "building_id", None)).route_target_for(intent) is not None
                )
            except Exception:
                _registry_known = False

            if _registry_known:
                state.current_intent = intent
            elif intent == "unknown" or not intent:
                # Unknown intent — return friendly error
                state.current_intent = "unknown"
                state.intermediate_results["dialogue_response"] = (
                    "I'm not sure I understood your question. Could you please rephrase or "
                    "ask about a specific aspect of the building such as sensors, temperature, "
                    "energy, or air quality?"
                )
            elif analytics_required:
                state.current_intent = "analytics"
            else:
                state.current_intent = "sparql"
            state.intermediate_results["llm_sparql_query"] = ""

        # ── Multi-intent decomposition ────────────────────────────────────
        # After single-intent classification, check whether the query is a
        # compound question spanning multiple intent domains.  If so, override
        # to "planner" so the enhanced PlannerAgent handles all sub-tasks.
        _skip_decompose = frozenset(
            {
                "clarification",
                "greeting",
                "general_knowledge",
                "unknown",
            }
        )
        if settings.MULTI_INTENT_ENABLED and state.current_intent not in _skip_decompose:
            try:
                from orchestrator.services.multi_intent_detector import (
                    MultiIntentDetector,
                )

                _detector = MultiIntentDetector()
                _user_q = state.messages[-1].content if state.messages else ""
                _sub_intents = await _detector.detect(_user_q, state.current_intent, entities)
                if _sub_intents and len(_sub_intents) > 1:
                    logger.info(
                        f"[multi-intent] Decomposed into {len(_sub_intents)} sub-intents: "
                        f"{[s.intent for s in _sub_intents]}"
                    )
                    state.intermediate_results["multi_intent_plan"] = {
                        "sub_intents": [s.to_dict() for s in _sub_intents],
                        "primary_intent": state.current_intent,
                    }
                    state.current_intent = "planner"
            except Exception as _mid_err:
                logger.warning(f"[multi-intent] Detection failed (non-fatal): {_mid_err}")

        logger.info(f"Final intent for routing: {state.current_intent}")
        return state

    async def _sparql_node(self, state: ConversationState) -> ConversationState:
        """
        Execute ontology query using LLM-generated SPARQL or semantic agent

        """
        logger.info("Executing SPARQL/ontology query node")

        latest_message = state.messages[-1].content if state.messages else ""

        # Bare anomaly queries ("are there any unusual readings today?") name no
        # metric, so SPARQL RAG picks an arbitrary sensor type that often lacks
        # time-series UUIDs → the pipeline dead-ends at "no data". Default the
        # SPARQL target to temperature so UUIDs resolve and anomaly detection runs.
        _sparql_query = latest_message
        if state.current_intent == "anomaly" and not _ANOMALY_METRIC_RE.search(latest_message):
            _sparql_query = f"{latest_message} temperature sensors"
            logger.info("[anomaly] no metric named — defaulting SPARQL target to temperature")

        # UNIFIED AGENT APPROACH:
        # Use SPARQLAgent for everything (it now handles semantic fallback internally)
        logger.info("Using Unified Ontology Agent (SPARQL + Semantic Fallback)")

        # Preserve any sensor data from the prior SQL turn before SPARQL overwrites query_results
        _prior_qr = state.query_results
        if isinstance(_prior_qr, dict) and _prior_qr.get("data"):
            state.intermediate_results["_saved_query_results"] = _prior_qr

        # Phase 3/14A: inject persona domain priors as a lightweight SPARQL context hint.
        # Phase 14A: when state.personas (list) is non-empty, blend priors across all
        # personas so SPARQL retrieval is biased toward every persona's domains.
        try:
            from shared.persona_registry import get_persona_registry as _get_preg

            _preg = _get_preg()
            _personas_list = list(getattr(state, "personas", []) or [])
            if _personas_list:
                _priors = _preg.get_blended_priors(_personas_list)
                _persona_label = "+".join(_priors.name.split("+")[:3])
            else:
                _persona_str = getattr(state, "persona", "general") or "general"
                _priors = _preg.get_priors(_persona_str)
                _persona_label = _persona_str
            if _priors.top_domains:
                state.intermediate_results["persona_domain_hint"] = (
                    f"User persona: {_persona_label}. "
                    f"Prioritise sensor types related to: "
                    f"{', '.join(_priors.top_domains[:3])}."
                )
                # Phase 14A diagnostics
                state.intermediate_results["persona_blended"] = {
                    "personas": _personas_list or [_persona_label],
                    "top_domains": _priors.top_domains[:6],
                    "complexity": _priors.default_complexity,
                    "clarification_threshold": _priors.clarification_threshold,
                }
        except Exception:
            pass

        # Phase 15A — set request-scoped building context so every SPARQL helper
        # (instance lookup, fallback pattern search, URI standardization, output
        # cleanup) uses THIS conversation's building namespace/prefix instead of
        # the process-global default.  Pair with reset in `finally` so the
        # ContextVar is unbound even on exceptions, preventing leak into the
        # next request on the same event loop.
        from orchestrator.agents.sparql_agent import (
            reset_request_bctx,
            set_request_bctx,
        )

        _bctx_token = set_request_bctx(getattr(state, "building_id", None))
        try:
            # ── Referent existence gate ──────────────────────────────────────────
            # Before the SPARQL/SQL fallback cascade can attribute another sensor's
            # readings to a nonexistent zone (e.g. "temperature in Zone 99.99"),
            # verify the named referent actually exists in THIS building's ontology.
            # Not found → honest clarification with real nearby zones. Fails open on
            # any SPARQL error, so a legitimate query is never blocked.
            if settings.REFERENT_VALIDATION_ENABLED:
                from orchestrator.agents.sparql_agent import _active_namespace
                from orchestrator.services.referent_resolver import (
                    GATED_INTENTS,
                    NOT_FOUND,
                    SKIPPED,
                    ReferentResolver,
                )

                _gate_intent = state.current_intent or state.intermediate_results.get("intent", "")
                if _gate_intent in GATED_INTENTS:
                    _resolution = await ReferentResolver(self.sparql_agent._execute_query).resolve(
                        query=latest_message,
                        entities=state.intermediate_results.get("entities", []),
                        namespace=_active_namespace(),
                        building_name=getattr(settings, "BUILDING_NAME", "this building"),
                    )
                    if _resolution.status == NOT_FOUND:
                        logger.info(
                            f"[referent_gate] '{_resolution.referent}' not found in ontology "
                            "— returning clarification instead of fabricated data"
                        )
                        state.intermediate_results["sparql_result"] = {
                            "success": True,
                            "analytics_required": False,
                            "formatted_response": _resolution.message,
                            "referent_not_found": _resolution.referent,
                        }
                        state.query_results = {}
                        state.analytics_required = False
                        state.intermediate_results["referent_resolution"] = "not_found"
                        return state
                    if _resolution.status == SKIPPED and _resolution.referent:
                        # BUG-136 — the question NAMED something and the existence
                        # check could not complete. Proceeding here hands the query
                        # to the fallback cascade, which is built to always surface
                        # SOME class-matching sensor's readings — i.e. the exact
                        # fabrication this gate exists to stop, reached through its
                        # own failure path. Failing open on a legitimate question
                        # loses one answer; failing open on an existence check
                        # produces a confident fabrication. Not symmetrical costs,
                        # so not symmetrical handling: refuse to assert, say why.
                        logger.warning(
                            f"[referent_gate] existence check for '{_resolution.referent}' "
                            "did not complete — refusing to assert rather than failing open"
                        )
                        state.intermediate_results["sparql_result"] = {
                            "success": True,
                            "analytics_required": False,
                            "formatted_response": (
                                f"I couldn't verify **{_resolution.referent}** against "
                                f"**{getattr(settings, 'BUILDING_NAME', 'this building')}**'s "
                                "model just now — the existence check didn't complete in "
                                "time. Rather than risk attributing another sensor's "
                                "readings to it, I'd rather you ask again in a moment."
                            ),
                            "referent_unverified": _resolution.referent,
                        }
                        state.query_results = {}
                        state.analytics_required = False
                        state.intermediate_results["referent_resolution"] = "unverified"
                        return state

                # Sensor-TYPE existence gate (BUG-063): honest "no such sensors" for a
                # sensor type the building lacks, instead of fabricating a count/answer
                # (e.g. "how many parking-space occupancy sensors"). Fails open.
                _type_decline = await self._absent_sensor_type_message(latest_message)
                if _type_decline:
                    logger.info("[sensor_type_gate] declining absent sensor type honestly")
                    state.intermediate_results["sparql_result"] = {
                        "success": True,
                        "analytics_required": False,
                        "formatted_response": _type_decline,
                    }
                    state.query_results = {}
                    state.analytics_required = False
                    state.intermediate_results["referent_resolution"] = "type_not_found"
                    return state

            result = await self.sparql_agent.generate_query(state, _sparql_query)
        finally:
            reset_request_bctx(_bctx_token)

        state.intermediate_results["sparql_result"] = result
        state.query_results = result.get("results", {})
        if result.get("success"):
            _prov.record(state, "ontology")

        # Set analytics_required:
        # - SPARQL's explicit False overrides dialogue True when SPARQL has a valid formatted_response
        #   (e.g. zone counts, sensor listings, floor hierarchy — no time-series data needed)
        # - SPARQL True always elevates to True (it knows it needs UUIDs)
        sparql_analytics = result.get("analytics_required", False)
        dialogue_analytics = state.intermediate_results.get("analytics_required", False)
        sparql_has_answer = result.get("success") and bool(result.get("formatted_response"))
        # Check if any sensor UUIDs were returned — if yes, SQL is needed for time-series data
        # answer_semantically() returns results as a list; guard against AttributeError.
        _raw_results = result.get("results", {})
        _bindings = (
            _raw_results.get("results", {}).get("bindings", [])
            if isinstance(_raw_results, dict)
            else []
        )
        _UUID_RE = re.compile(
            r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            re.IGNORECASE,
        )
        _sparql_has_uuids = any(
            _UUID_RE.match(str(b.get(v, {}).get("value", "")))
            for b in _bindings
            for v in b
            if "uuid" in v.lower() or "id" in v.lower()
        )
        # ── Compliance/follow-up: recover if SPARQL found ontology vocab but no sensor UUIDs ──
        _original_intent = state.intermediate_results.get("intent", "")
        # "recommend" is excluded: _recommend_node can answer without sensor UUIDs
        _contextual_intents = {"compliance", "compare", "trend"}
        if _original_intent in _contextual_intents and not _sparql_has_uuids:
            # SPARQL returned ontology vocabulary or empty results — no sensor data.
            # Check if the previous SQL turn left sensor readings in state.query_results.
            _saved_qr = state.intermediate_results.get("_saved_query_results")
            _prior_rows = _saved_qr.get("data") if isinstance(_saved_qr, dict) else None
            if _prior_rows:
                # Restore prior data and route to analytics
                state.query_results = _saved_qr
                state.intermediate_results["use_existing_query_results"] = True
                state.analytics_required = True
                logger.info(
                    f"[compliance] SPARQL returned no sensor UUIDs — "
                    f"restoring {len(_prior_rows)} prior rows for compliance analytics"
                )
            else:
                # No prior data — give an intent-appropriate clarification rather than
                # a compliance-specific template (which is confusing for trend/compare queries).
                _entities_hint = (
                    ", ".join(state.intermediate_results.get("entities", [])[:3])
                    or "the requested sensor or zone"
                )
                if _original_intent == "trend":
                    _fallback_msg = (
                        f"I couldn't retrieve trend data for {_entities_hint} directly. "
                        "The sensor may be referenced by a different label in the ontology. "
                        "To get a weekly or daily trend, try specifying the zone instead — "
                        "e.g. *'Show CO2 sensor trend for Zone 5.08 over the last 7 days'* "
                        "or *'What was the average CO2 in Zone 5.08 this week?'*  "
                        "Ventilation adequacy can be assessed once I have zone-level sensor data."
                    )
                elif _original_intent == "compare":
                    _fallback_msg = (
                        f"Comparing {_entities_hint} requires sensors with linked time-series data. "
                        "Floor-level energy or zone comparison works best when referencing specific "
                        "zone IDs — e.g. *'Compare temperature in Zone 5.01 vs Zone 5.28 last month'* "
                        "or *'Which floor had higher average CO2 this week?'*  "
                        "I can pull data for any sensor zone once a specific zone or sensor ID is provided."
                    )
                else:
                    _fallback_msg = (
                        "**Compliance Check — Zone or Sensor Required**\n\n"
                        "To assess ASHRAE / WELL / BREEAM compliance I need live sensor readings "
                        "from a specific zone or sensor.  Please try one of:\n\n"
                        "- *'Is the temperature in Zone 5.28 within ASHRAE 55 comfort limits?'*\n"
                        "- *'Check ASHRAE 62.1 compliance for Zone 5.28'*\n"
                        "- *'What is the temperature across all zones?'* (then click **Check compliance against ASHRAE?**)"
                    )
                state.intermediate_results["sparql_result"] = {
                    "success": True,
                    "analytics_required": False,
                    "formatted_response": _fallback_msg,
                }
                state.analytics_required = False
                logger.info(
                    f"[compliance] No sensor UUIDs and no prior data — returning {_original_intent}-specific clarification"
                )
        elif not sparql_analytics and sparql_has_answer and not _sparql_has_uuids:
            # SPARQL resolved the query with no sensor UUIDs (e.g. zone counts, floor listing,
            # hierarchy) — skip SQL entirely
            state.analytics_required = False
            logger.info(
                "✅ SPARQL resolved query fully (no UUIDs) — overriding dialogue analytics_required=True"
            )
        else:
            state.analytics_required = sparql_analytics or dialogue_analytics
            # The upstream analytics heuristics are phrase lists, so a reading request
            # worded even slightly off-pattern ("current air temperature" vs "current
            # temperature") lands here as False and the answer stops at metadata —
            # naming the sensor and its UUID but never reading it. When the graph has
            # handed us timeseries UUIDs and the intent is one that asks for readings,
            # that is signal enough to run the SQL stage.
            _reading_intents = {"sensor_data", "analytics", "anomaly", "visualization"}
            if (
                not state.analytics_required
                and _sparql_has_uuids
                and _original_intent in _reading_intents
            ):
                state.analytics_required = True
                logger.info(
                    f"[route] intent={_original_intent} with timeseries UUIDs — "
                    f"fetching readings despite heuristic analytics_required=False"
                )
        logger.info(
            f"✅ Ontology Agent determined: analytics_required={state.analytics_required} "
            f"(sparql={sparql_analytics}, dialogue={dialogue_analytics}, "
            f"sparql_has_answer={sparql_has_answer}, sparql_has_uuids={_sparql_has_uuids})"
        )
        if result.get("llm_reasoning"):
            logger.info(f"💭 LLM reasoning: {result.get('llm_reasoning')}")

        # NEW: Save analytics decision and results as JSON
        if result.get("success"):
            self._save_query_output(
                conversation_id=state.conversation_id,
                query=latest_message,
                sparql=result.get("query"),
                results=result.get("results"),
                analytics_required=state.analytics_required,
                llm_reasoning=result.get("llm_reasoning", ""),
                formatted_response=result.get("formatted_response"),
            )

        return state

    # DEPRECATED: Old logic removed
    async def _sparql_node_legacy(self, state: ConversationState) -> ConversationState:
        pass

    async def _sql_node(self, state: ConversationState) -> ConversationState:
        """Execute SQL query generation and execution"""
        logger.info("Executing SQL node")

        latest_message = state.messages[-1].content if state.messages else ""

        # Check if we have SPARQL results with UUIDs (from previous step)
        sparql_result = state.intermediate_results.get("sparql_result", {})

        # Recompute whether SPARQL returned any sensor UUIDs (needed for skip-SQL guards below)
        _UUID_RE_SQL = re.compile(
            r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
            re.IGNORECASE,
        )
        _sql_bindings = (
            sparql_result.get("results", {}).get("results", {}).get("bindings", [])
            if isinstance(sparql_result.get("results", {}), dict)
            else []
        )
        _sparql_has_uuids = any(
            _UUID_RE_SQL.match(str(b.get(v, {}).get("value", "")))
            for b in _sql_bindings
            for v in b
            if "uuid" in v.lower() or "id" in v.lower()
        )

        uuids = []
        storage_map = {}

        if state.analytics_required and sparql_result.get("success"):
            try:
                # Handle standard SPARQL JSON results
                bindings = sparql_result.get("results", {}).get("results", {}).get("bindings", [])
                sensor_metadata = self._build_sensor_metadata_from_bindings(bindings)
                for binding in bindings:
                    current_uuid = None
                    current_storage = None

                    # Look for 'uuid' or 'id' variable — validate with UUID4 regex
                    _UUID_RE = re.compile(
                        r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
                        re.IGNORECASE,
                    )
                    for var in binding:
                        if "uuid" in var.lower() or "id" in var.lower():
                            val = binding[var]["value"]
                            if val and _UUID_RE.match(val):
                                current_uuid = val

                        # Look for 'storage' variable
                        if "storage" in var.lower():
                            current_storage = binding[var]["value"]

                    if current_uuid:
                        uuids.append(current_uuid)
                        if current_storage:
                            storage_map[current_uuid] = current_storage

                uuids = list(set(uuids))

                # Disambiguate by sensor type if the user asked for a specific kind (e.g., temperature)
                preferred_kind = self._infer_query_kind(latest_message)
                if preferred_kind and sensor_metadata:
                    filtered = {
                        u: m for u, m in sensor_metadata.items() if m.get("kind") == preferred_kind
                    }
                    if filtered:
                        uuids = [u for u in uuids if u in filtered]
                        storage_map = {u: s for u, s in storage_map.items() if u in uuids}
                        state.intermediate_results["sensor_metadata"] = filtered
                    else:
                        state.intermediate_results["sensor_metadata"] = sensor_metadata
                elif sensor_metadata:
                    state.intermediate_results["sensor_metadata"] = sensor_metadata
            except Exception as e:
                logger.warning(f"Failed to extract UUIDs from SPARQL result: {e}")

        if uuids:
            logger.info("=" * 80)
            logger.info(f"🔍 Found {len(uuids)} UUIDs from SPARQL results, fetching data...")
            logger.info("UUID → Storage Mapping:")
            for uuid in uuids:
                storage = storage_map.get(uuid, "Unknown")
                logger.info(f"   • {uuid} → {storage}")
            logger.info("=" * 80)
            start_date = state.intermediate_results.get("start_date")
            end_date = state.intermediate_results.get("end_date")
            result = await self.sql_agent.fetch_data_for_uuids(
                uuids, latest_message, storage_map, start_date, end_date
            )
        elif sparql_result.get("method") == "semantic_rag" or (
            sparql_result.get("success")
            and not sparql_result.get("analytics_required", True)
            and sparql_result.get("formatted_response")
        ):
            # SPARQL fell back to semantic RAG (no sensor UUIDs for this query type).
            # Skip text-to-SQL — the semantic answer already covers what's available.
            logger.info(
                "No UUIDs and SPARQL used semantic RAG — skipping text-to-SQL, using semantic answer"
            )
            result = {
                "success": True,
                "query": "SEMANTIC_RAG_NO_UUIDS",
                "results": {"data": []},
                "formatted_response": sparql_result.get("formatted_response", ""),
                "analytics_required": False,
            }
            state.analytics_required = False
        elif not _sparql_has_uuids and state.current_intent in ("recommend", "forecast"):
            # No sensor UUIDs found for a recommend/forecast query.
            # Text-to-SQL would fetch unrelated rows → LLM spends 90s generating bad advice.
            # Skip SQL entirely; the analytics/recommend node will answer using SPARQL context
            # (building description) and domain knowledge alone — much faster and more accurate.
            logger.info(
                f"[{state.current_intent}] No UUIDs found — skipping text-to-SQL, "
                "analytics node will use building context only"
            )
            result = {
                "success": True,
                "query": "NO_UUIDS_SKIP_SQL",
                "results": {"data": []},
                "formatted_response": sparql_result.get("formatted_response", ""),
                "analytics_required": True,
            }
        elif not _sparql_has_uuids and state.current_intent in (
            "analytics",
            "compare",
            "trend",
            "anomaly",
            "compliance",
        ):
            # SPARQL returned no sensor UUIDs for an analytics-type query.
            # Text-to-SQL fallback would generate incorrect or wide-open queries that
            # take 60s+ and return unrelated data. Detect if the user asked about a
            # sensor type that's genuinely unavailable in this building, and return a
            # clear explanation rather than attempting a doomed SQL generation.
            _q = latest_message.lower()
            _unavailable = {
                "occupancy": {
                    "occupancy",
                    "people count",
                    "head count",
                    "how many people",
                    "occupant",
                    "occupants",
                    "presence",
                    "motion",
                    "desk usage",
                    "utilization",
                    "occupied",
                    "footfall",
                },
                "energy": {
                    "energy",
                    "power",
                    "electricity",
                    "kilowatt",
                    "kwh",
                    "watt",
                    "energy meter",
                    "energy consumption",
                    "power meter",
                    "eui",
                    "carbon footprint",
                    "co2e",
                    "energy cost",
                },
            }
            _missing_type = None
            for stype, keywords in _unavailable.items():
                if any(kw in _q for kw in keywords):
                    _missing_type = stype
                    break

            if _missing_type == "occupancy":
                logger.info(
                    f"[{state.current_intent}] No UUIDs + occupancy query — "
                    "Abacws has no occupancy sensors, skipping text-to-SQL"
                )
                result = {
                    "success": False,
                    "query": "NO_OCCUPANCY_SENSORS",
                    "results": {"data": []},
                    "formatted_response": (
                        "**0 occupancy sensors identified** — "
                        "occupancy data is not available for the Abacws building.\n\n"
                        "This building does not have occupancy sensors, motion detectors, "
                        "or desk-utilisation monitors installed. As a result, occupancy "
                        "patterns, headcounts, and space utilisation reports cannot be "
                        "generated from sensor data.\n\n"
                        "Abacws actively monitors: **temperature**, **CO₂**, **humidity**, "
                        "**air quality** (PM2.5 / TVOC / NO₂), **illuminance**, and **gas** sensors. "
                        "Would you like to check one of those instead?"
                    ),
                    "analytics_required": False,
                }
                state.analytics_required = False
            elif _missing_type == "energy":
                logger.info(
                    f"[{state.current_intent}] No UUIDs + energy query — "
                    "Abacws has no energy meters, skipping text-to-SQL"
                )
                result = {
                    "success": False,
                    "query": "NO_ENERGY_METERS",
                    "results": {"data": []},
                    "formatted_response": (
                        "**Energy meter data is not available for the Abacws building.**\n\n"
                        "This building does not have smart energy meters or power consumption "
                        "sensors. Direct kWh readings, Energy Use Intensity (EUI) calculations, "
                        "and energy cost estimates cannot be produced from the installed hardware.\n\n"
                        "Abacws actively monitors: **temperature**, **CO₂**, **humidity**, "
                        "**air quality** (PM2.5 / TVOC / NO₂), **illuminance**, and **gas** sensors. "
                        "Energy efficiency can be *inferred* from these — for example, "
                        "over-heating or poor ventilation often indicates wasted energy. "
                        "Would you like that kind of analysis instead?"
                    ),
                    "analytics_required": False,
                }
                state.analytics_required = False
            else:
                # Generic: no UUIDs, no specific unavailable type detected.
                # Still skip text-to-SQL to avoid slow/wrong queries.
                logger.info(
                    f"[{state.current_intent}] No UUIDs found — skipping text-to-SQL "
                    "(no specific sensor type detected; returning SPARQL context response)"
                )
                result = {
                    "success": False,
                    "query": "NO_UUIDS_NO_SQL",
                    "results": {"data": []},
                    "formatted_response": sparql_result.get("formatted_response")
                    or (
                        "I wasn't able to find specific sensor data for your request. "
                        "Try asking about temperature, CO₂, humidity, or air quality — "
                        "those are the sensor types available in this building."
                    ),
                    "analytics_required": False,
                }
                state.analytics_required = False
        else:
            # Fallback to standard SQL generation (text-to-SQL)
            logger.info("No UUIDs found or not analytics flow, using standard Text-to-SQL")
            result = await self.sql_agent.generate_and_execute(state, latest_message)

        state.intermediate_results["sql_result"] = result

        # Handle SQL failures properly
        if result.get("success"):
            state.query_results = result.get("results", {"data": []})
            row_count = len(result.get("results", {}).get("data", []))
            logger.info(f"SQL successful: {row_count} data records retrieved")
            if row_count > 0:
                _prov.record_sql_stores(state, storage_map)

            # Phase 3.1: Notify SmartCacheManager about new data for staleness tracking
            if self.smart_cache and uuids and row_count > 0:
                try:
                    for uid in uuids:
                        await self.smart_cache.on_new_readings(uid, row_count)
                except Exception as _sc_err:
                    logger.debug(f"SmartCache staleness update skipped: {_sc_err}")
        else:
            state.query_results = {"data": []}  # Empty but valid structure
            logger.error(f"SQL failed: {result.get('error', 'Unknown error')}")

        # Only mark analytics_required for intents that actually need data processing
        # Don't override False set by the semantic-RAG shortcut above.
        _analytics_intents = {
            "analytics",
            "compare",
            "trend",
            "recommend",
            "compliance",
            "anomaly",
        }
        if state.current_intent in _analytics_intents and state.analytics_required:
            # analytics_required already True (or set by UUID path) — keep it
            logger.info(
                f"✅ Intent '{state.current_intent}' requires analytics: analytics_required=True"
            )
        elif state.current_intent in _analytics_intents and not state.analytics_required:
            # Semantic-RAG shortcut already set analytics_required=False — respect it
            logger.info(
                f"ℹ️  Intent '{state.current_intent}' — analytics skipped (semantic RAG answered)"
            )
        else:
            state.analytics_required = False
            logger.info(f"ℹ️  Intent '{state.current_intent}' does not require analytics post-SQL")

        return state

    async def _recommend_node(
        self, state: ConversationState, query: str, data: Any
    ) -> ConversationState:
        """Generate actionable HVAC/energy/comfort recommendations from sensor data via LLM."""
        logger.info("[recommend] Generating recommendations (skipping code execution)")

        sparql_result = state.intermediate_results.get("sparql_result", {})
        sensor_metadata = state.intermediate_results.get("sensor_metadata", {})
        # "dialogue_result" is not a populated key — the dialogue node stores the
        # domain directly under "recommendation_domain" (fix 2026-06-12: the old
        # read always fell back to "general", so domain-specific recommendation
        # prompts never fired).
        recommendation_domain = state.intermediate_results.get("recommendation_domain") or "general"

        # Build a compact data summary (last 5 rows max)
        rows = (data.get("data", []) if isinstance(data, dict) else data) or []
        data_summary = ""
        if rows:
            sample = rows[-5:] if len(rows) >= 5 else rows
            data_summary = "\n".join(f"  {r}" for r in sample)
        sparql_summary = sparql_result.get("formatted_response", "")

        ontology_summary = ""
        if sensor_metadata:
            labels = [m.get("label", uid) for uid, m in list(sensor_metadata.items())[:10]]
            ontology_summary = "Available sensors: " + ", ".join(labels)

        # Detect if this is an energy-specific recommendation when no energy data is available
        _q_lower = query.lower()
        _energy_keywords = {
            "energy",
            "power",
            "electricity",
            "kWh",
            "kwh",
            "watt",
            "consumption",
            "eui",
            "carbon",
            "co2e",
        }
        _is_energy_focused = any(kw in _q_lower for kw in _energy_keywords)
        _has_energy_data = rows and any(
            any(kw in str(k).lower() for kw in ("power", "energy", "watt", "kwh"))
            for r in rows
            for k in r.keys()
        )

        # Context note about what sensors ARE available (for energy queries with no energy data)
        _sensor_context = ""
        if _is_energy_focused and not _has_energy_data:
            _sensor_context = (
                "\n\nNOTE: This building (Abacws) does NOT have energy meters or power consumption sensors. "
                "Available sensors: temperature, CO₂, humidity, air quality (PM2.5, TVOC, NO₂), illuminance. "
                "Recommendations should focus on HVAC efficiency, ventilation optimisation, and comfort "
                "improvements inferred from these environmental sensors (e.g. over-heating = wasted energy)."
            )

        prompt = f"""You are an expert smart-building consultant. The user asked:
"{query}"

Based on the building data below, provide clear, ACTIONABLE recommendations.
Focus on domain: {recommendation_domain or "general (HVAC, energy, air quality, comfort)"}.{_sensor_context}

=== SENSOR DATA (latest readings) ===
{data_summary if data_summary else "No real-time data available — provide general best-practice recommendations based on building type and available sensor types."}

=== BUILDING CONTEXT ===
{sparql_summary[:800] if sparql_summary else ontology_summary or "Smart building system."}

Instructions:
- Give 3-6 specific, numbered recommendations
- For each recommendation, explain WHY (link to a measured value if available)
- Use plain English — avoid jargon for general users
- If no energy meters are available, infer energy efficiency opportunities from temperature/CO₂/humidity readings
- If relevant, mention target setpoints, timings, or energy-saving percentages
- End with a brief priority summary: "Most important action first: ..."
"""
        try:
            response_text = await llm_manager.generate(
                prompt, task_type=TaskType.ANALYTICS  # o4-mini for best reasoning
            )
            state.intermediate_results["analytics_result"] = {
                "formatted_response": response_text,
                "success": True,
                "source": "recommend_llm",
            }
        except Exception as e:
            logger.error(f"[recommend] LLM call failed: {e}", exc_info=True)
            state.intermediate_results["analytics_result"] = {
                "formatted_response": (
                    "I was unable to generate recommendations at this time. "
                    "Please try again or rephrase your question."
                ),
                "success": False,
                "error": str(e),
            }

        return state

    async def _analytics_node(self, state: ConversationState) -> ConversationState:
        """Execute analytics code generation and execution"""
        logger.info("=" * 80)
        logger.info("🔬 Executing Analytics Node")
        logger.info("=" * 80)

        latest_message = state.messages[-1].content if state.messages else ""
        data = state.query_results

        # ── RECOMMEND shortcut: generate actionable advice via LLM, skip code execution ──
        if state.current_intent == "recommend":
            return await self._recommend_node(state, latest_message, data)

        # ── FORECAST shortcut: real multi-model time-series prediction ────────
        # Triggers when intent is "trend" AND the query contains forecast/predict
        # keywords. Uses ForecastAgent (ARIMA, Holt-Winters, Linear Trend) instead
        # of ad-hoc LLM code generation for statistically valid predictions.
        from orchestrator.agents.forecast_agent import ForecastAgent as _ForecastAgent
        from orchestrator.services.forecasting.horizon_parser import (
            parse_horizon as _parse_horizon,
        )

        _FORECAST_TRIGGER_KWS = (
            "predict",
            "forecast",
            "projected",
            "projection",
            "what will",
            "what would",
            "expected to be",
            "likely to be",
            "tomorrow",
            "next week",
            "next month",
            "next hour",
            "in the next",
        )
        _is_forecast = state.current_intent == "trend" and any(
            kw in latest_message.lower() for kw in _FORECAST_TRIGGER_KWS
        )

        if _is_forecast:
            logger.info(
                "[analytics_node] Forecast keywords detected → routing to ForecastAgent "
                f"(query: {latest_message[:80]!r})"
            )
            sql_data = state.intermediate_results.get("sql_result") or {}
            _sensor_meta = state.intermediate_results.get("sensor_metadata") or {}

            _forecast_agent = _ForecastAgent()
            _forecast_result = await _forecast_agent.predict(
                state, latest_message, sql_data, _sensor_meta
            )
            state.intermediate_results["forecast_result"] = _forecast_result
            # Also set analytics_result so the response node picks it up
            state.intermediate_results["analytics_result"] = {
                "success": _forecast_result.get("success", False),
                "formatted_response": _forecast_result.get("formatted_response", ""),
                "source": "forecast_agent",
                "model": _forecast_result.get("model"),
                "metrics": _forecast_result.get("metrics"),
            }
            logger.info(
                f"[analytics_node] ForecastAgent done: "
                f"model={_forecast_result.get('model','?')} "
                f"success={_forecast_result.get('success')}"
            )
            return state

        sensor_metadata = state.intermediate_results.get("sensor_metadata")
        if not sensor_metadata:
            sensor_metadata = {}
            sparql_result = state.intermediate_results.get("sparql_result", {})
            if sparql_result.get("success"):
                bindings = sparql_result.get("results", {}).get("results", {}).get("bindings", [])
                sensor_metadata = self._build_sensor_metadata_from_bindings(bindings)

        logger.info(f"📋 Extracted sensor metadata for {len(sensor_metadata)} sensors")
        for uuid, meta in sensor_metadata.items():
            logger.info(f"   • {uuid[:30]}... → {meta['label']}")

        # Store sensor metadata for response formatting
        state.intermediate_results["sensor_metadata"] = sensor_metadata

        # Save data to standard JSON format locally for analytics
        data_filename = "current_data.json"
        try:
            import json
            import os

            # Ensure directory exists
            os.makedirs(settings.OUTPUT_DATA_DIR, exist_ok=True)

            # Standard format: {"data": [...], "metadata": {...}}
            standard_data = {
                "data": data.get("data", []) if isinstance(data, dict) else data,
                "metadata": sensor_metadata,
            }

            # Save to shared volume path with unique filename per user/conversation
            # This ensures data isolation between users
            safe_user_id = "".join(c for c in state.user_id if c.isalnum() or c in ("-", "_"))
            safe_conv_id = "".join(
                c for c in state.conversation_id if c.isalnum() or c in ("-", "_")
            )
            data_filename = f"{safe_user_id}_{safe_conv_id}_data.json"
            data_path = f"{settings.OUTPUT_DATA_DIR}/{data_filename}"

            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(standard_data, f, indent=2, default=str)

            logger.info(f"💾 Saved analytics data to {data_path}")

        except Exception as e:
            logger.error(f"Failed to save analytics data locally: {e}")
            # Use a unique fallback name to prevent concurrent-request collisions
            data_filename = f"fallback_{uuid4().hex}_data.json"

        # B.7: Try deterministic Analytics Engine before falling back to LLM code generation
        det_result = await self._try_deterministic_analytics(
            intent=state.current_intent,
            query=latest_message,
            data=data,
        )
        if det_result:
            logger.info(
                f"✅ Deterministic analytics handled intent='{state.current_intent}' (saved LLM call)"
            )
            state.intermediate_results["analytics_result"] = {
                "formatted_response": det_result.formatted_response,
                "success": det_result.success,
                "metrics": det_result.metrics,
                "violations": det_result.violations,
                "grade": det_result.grade,
                "recommendations": det_result.recommendations,
                "source": "deterministic",
            }
            return state

        # T05: inject HBCO recipe thresholds so the analytics LLM can apply them
        try:
            from orchestrator.services.recipe_registry import recipe_registry as _rr

            _concepts = state.intermediate_results.get("concepts") or []
            _recipe_hints: list = []
            for _cm in _concepts:
                _rid = _cm.get("recipe_id")
                if _rid:
                    _recipe = _rr.get(_rid)
                    if _recipe:
                        _recipe_hints.append(
                            {
                                "recipe_id": _rid,
                                "concept_id": _cm.get("concept_id"),
                                "description": _recipe.get("description", ""),
                                "params": _recipe.get("params", {}),
                                "answer_template": _recipe.get("answer_template", ""),
                            }
                        )
            if _recipe_hints:
                state.intermediate_results["recipe_hints"] = _recipe_hints
                logger.info(
                    f"[analytics_node] recipe hints injected: "
                    f"{[h['recipe_id'] for h in _recipe_hints]}"
                )
        except Exception as _rh_err:
            logger.debug(f"[analytics_node] recipe hint injection skipped: {_rh_err}")

        # T34: What-if / estimate recipe — inject sensitivity factors for the analytics LLM.
        _whatif_rid = state.intermediate_results.get("whatif_recipe")
        if _whatif_rid:
            try:
                from orchestrator.services.recipe_registry import (
                    recipe_registry as _rr_wi,
                )

                _wi_recipe = _rr_wi.get(_whatif_rid)
                if _wi_recipe:
                    existing = state.intermediate_results.get("recipe_hints") or []
                    _wi_hint = {
                        "recipe_id": _whatif_rid,
                        "concept_id": "whatif_estimate",
                        "description": _wi_recipe.get("description", ""),
                        "params": _wi_recipe.get("params", {}),
                        "answer_template": _wi_recipe.get("answer_template", ""),
                    }
                    state.intermediate_results["recipe_hints"] = existing + [_wi_hint]
                    logger.info(f"[analytics_node] what-if recipe hint injected: {_whatif_rid}")
            except Exception as _wi_err:
                logger.debug(f"[analytics_node] what-if hint injection skipped: {_wi_err}")

        # T32: Benchmark recipe — inject sector comparison params for the analytics LLM.
        _bench_rid = state.intermediate_results.get("benchmark_recipe")
        if _bench_rid:
            try:
                from orchestrator.services.recipe_registry import (
                    recipe_registry as _rr_bm,
                )

                _bm_recipe = _rr_bm.get(_bench_rid)
                if _bm_recipe:
                    existing = state.intermediate_results.get("recipe_hints") or []
                    _bm_hint = {
                        "recipe_id": _bench_rid,
                        "concept_id": "sector_benchmark",
                        "description": _bm_recipe.get("description", ""),
                        "params": _bm_recipe.get("params", {}),
                        "answer_template": _bm_recipe.get("answer_template", ""),
                    }
                    state.intermediate_results["recipe_hints"] = existing + [_bm_hint]
                    logger.info(f"[analytics_node] benchmark recipe hint injected: {_bench_rid}")
            except Exception as _bm_err:
                logger.debug(f"[analytics_node] benchmark hint injection skipped: {_bm_err}")

        # T35: User preference overlay — inject personal comfort range if the user has one.
        # Only for authenticated users; silently skipped if Redis unavailable.
        _pref_user_id = state.intermediate_results.get("user_id", "")
        _concepts_for_pref = state.intermediate_results.get("concepts", [])
        if _pref_user_id and _concepts_for_pref:
            try:
                from orchestrator.services.user_preference_store import (
                    CATEGORY_KEYWORDS,
                    get_user_preference_store,
                )

                _pref_store = get_user_preference_store()
                # Map HBCO concept to a preference category
                _concept0 = _concepts_for_pref[0]
                _concept_id = _concept0.get("concept_id", "")
                _pref_category = None
                for kw, cat in CATEGORY_KEYWORDS.items():
                    if kw in _concept_id.replace("_", " "):
                        _pref_category = cat
                        break
                if _pref_category:
                    _user_pref = await _pref_store.get_preference(_pref_user_id, _pref_category)
                    if _user_pref:
                        _p_min = _user_pref.get("pref_min")
                        _p_max = _user_pref.get("pref_max")
                        _p_unit = _user_pref.get("unit", "")
                        _rng = (
                            f"{_p_min}–{_p_max} {_p_unit}"
                            if _p_min and _p_max
                            else f"≥{_p_min} {_p_unit}" if _p_min else f"≤{_p_max} {_p_unit}"
                        )
                        existing_hints = state.intermediate_results.get("recipe_hints") or []
                        _pref_hint = {
                            "recipe_id": "user_preference_overlay",
                            "concept_id": _pref_category,
                            "description": (
                                f"USER PERSONAL PREFERENCE (overrides standard guideline): "
                                f"This specific user prefers {_rng} for "
                                f"{_user_pref.get('label', _pref_category)}. "
                                f"Use this range when assessing comfort FOR THIS USER. "
                                f"State which range was applied in your answer."
                            ),
                            "params": {
                                "pref_min": _p_min,
                                "pref_max": _p_max,
                                "unit": _p_unit,
                                "label": _user_pref.get("label", _pref_category),
                            },
                            "answer_template": "",
                        }
                        state.intermediate_results["recipe_hints"] = existing_hints + [_pref_hint]
                        logger.info(
                            f"[analytics_node] user preference overlay injected: "
                            f"{_pref_category}={_rng}"
                        )
            except Exception as _pref_err:
                logger.debug(f"[analytics_node] preference overlay skipped: {_pref_err}")

        # Fallback: LLM-generated Python code via analytics_agent
        result = await self.analytics_agent.analyze(
            state, latest_message, data, sensor_metadata, data_filename
        )

        state.intermediate_results["analytics_result"] = result
        if isinstance(result, dict) and result.get("success"):
            _prov.record(state, "analytics")

        # ── CAP-04 Auto-compliance check ──────────────────────────────────────
        # After data is fetched, build a scalar readings dict from the latest
        # row and run auto_check() so compliance info can be appended to the
        # response without the user needing to explicitly ask.
        try:
            _rows = data.get("data", []) if isinstance(data, dict) else []
            if _rows:
                _latest_row = _rows[-1] if _rows else {}
                _param_col_map = {
                    "temp_c": ["temperature", "temp"],
                    "humidity_rh": ["humidity", "rh"],
                    "co2_ppm": ["co2", "co₂", "carbon"],
                    "pm25_ugm3": ["pm25", "pm2.5"],
                    "pm10_ugm3": ["pm10"],
                    "tvoc_ppb": ["tvoc", "voc"],
                    "illuminance_lux": ["illuminance", "light", "lux"],
                }
                _auto_readings: dict = {}
                for pkey, kws in _param_col_map.items():
                    for col, val in _latest_row.items():
                        if any(kw in str(col).lower() for kw in kws):
                            try:
                                _auto_readings[pkey] = float(val)
                            except (TypeError, ValueError):
                                pass
                            break

                if _auto_readings:
                    _auto_results = self._standards_engine.auto_check(_auto_readings)
                    _compliance_block = self._standards_engine.format_for_llm(_auto_results)
                    if _compliance_block:
                        state.intermediate_results["compliance_context"] = _compliance_block
                        logger.info(
                            f"[standards] Auto-check generated compliance block "
                            f"({len(_auto_results)} standards checked)"
                        )
        except Exception as _ac_err:
            logger.debug(f"Auto-compliance check skipped: {_ac_err}")

        return state

    # ──────────────────────────────────────────────────────────────────────────
    # B.7 helper: map intent/query to deterministic analyser
    # ──────────────────────────────────────────────────────────────────────────

    _INTENT_TO_ANALYSIS: dict = {
        "compliance": "compliance",
        "trend": "trend",
    }

    _QUERY_KEYWORDS_TO_ANALYSIS: list = [
        (
            {
                "comfort",
                "ashrae",
                "well",
                "en15251",
                "temperature range",
                "humidity range",
            },
            "comfort",
        ),
        ({"energy", "kwh", "watt", "power", "electricity", "peak", "eui"}, "energy"),
        ({"iaq", "air quality", "co2", "co₂", "voc", "pm2", "pm10"}, "iaq"),
        ({"trend", "increasing", "decreasing", "mann-kendall", "slope"}, "trend"),
        (
            {"comply", "compliance", "standard", "regulation", "breeam", "leed"},
            "compliance",
        ),
    ]

    async def _try_deterministic_analytics(self, intent: str, query: str, data) -> object:
        """
        Attempt to resolve the analytics request using a deterministic module.
        Returns an AnalysisResult if handled, or None to fall through to LLM.
        """
        rows = data.get("data", []) if isinstance(data, dict) else (data or [])
        if not rows:
            return None

        # Detect analysis type from intent or query keywords
        analysis_type = self._INTENT_TO_ANALYSIS.get(intent)
        if not analysis_type:
            query_lower = query.lower()
            for keywords, atype in self._QUERY_KEYWORDS_TO_ANALYSIS:
                if any(kw in query_lower for kw in keywords):
                    analysis_type = atype
                    break

        if not analysis_type:
            return None

        # Build schema: map first numeric column to the matching sensor type key
        schema: dict = {}
        if rows:
            for col in rows[0].keys():
                col_lower = col.lower()
                for known in (
                    "temperature",
                    "humidity",
                    "co2",
                    "voc",
                    "energy",
                    "power",
                ):
                    if known in col_lower and known not in schema:
                        schema[known] = col
                        break

        if not schema:
            return None

        try:
            req = AnalysisRequest(analysis_type=analysis_type, data=rows, schema=schema)
            result = await self.analytics_engine.run(req)

            # CAP-04: Augment compliance results with StandardsEngine checks
            if analysis_type == "compliance" and rows:
                try:
                    # Build a readings dict from latest sensor row
                    _latest = rows[-1] if rows else {}
                    _readings = {}
                    _param_map = {
                        "temperature": "temp_c",
                        "co2": "co2_ppm",
                        "humidity": "humidity_rh",
                        "pm25": "pm25_ugm3",
                        "pm10": "pm10_ugm3",
                        "voc": "tvoc_ppb",
                    }
                    for col, pkey in _param_map.items():
                        for k, v in _latest.items():
                            if col in str(k).lower():
                                try:
                                    _readings[pkey] = float(v)
                                except (TypeError, ValueError):
                                    pass

                    if _readings:
                        query_lower = query.lower()
                        for std_id in (
                            "breeam",
                            "well_v2",
                            "ashrae55",
                            "en15251",
                            "iso50001",
                        ):
                            if std_id.replace("_", "") in query_lower or std_id in query_lower:
                                std_check = self._standards_engine.check(std_id, _readings)
                                if result.metrics is None:
                                    result.metrics = {}
                                result.metrics[f"standards_{std_id}"] = std_check
                                logger.info(
                                    f"CAP-04: {std_id} compliance: {std_check['overall_status']}"
                                )
                                break
                except Exception as _std_err:
                    logger.debug(f"Standards engine augmentation skipped: {_std_err}")

            return result
        except Exception as e:
            logger.warning(f"Deterministic analytics failed ({analysis_type}): {e}")
            return None

    async def _visualization_node(self, state: ConversationState) -> ConversationState:
        """Execute visualization generation.

        Fast path: when the user asks to graph a *previous forecast result*
        (e.g. "show me the graph for the above", "plot that prediction"),
        we generate deterministic matplotlib code from the stored forecast_result
        instead of letting the LLM invent placeholder data.

        Normal path: delegate to viz_agent.create_visualization as before.
        """
        logger.info("Executing visualization node")

        latest_message = state.messages[-1].content if state.messages else ""
        data = state.query_results

        # ── Forecast chart fast path ──────────────────────────────────────────
        _forecast_result = state.intermediate_results.get("forecast_result") or {}
        _PREV_VIZ_KWS = (
            "previous",
            "above",
            "that forecast",
            "those results",
            "that prediction",
            "those predictions",
            "that result",
            "the prediction",
            "the forecast",
            "show the graph",
            "plot it",
            "graph it",
            "graph for the",
            "chart for the",
            "visualise it",
            "visualize it",
            "chart of that",
            "plot of that",
            "for the above",
            "from before",
            "last result",
            "previous result",
        )
        _is_prev_viz = _forecast_result.get("success") and any(
            kw in latest_message.lower() for kw in _PREV_VIZ_KWS
        )

        if _is_prev_viz:
            logger.info(
                "[viz_node] Detected 'visualize previous forecast' request — "
                "generating chart from stored forecast_result (no LLM code generation)"
            )
            result = await self._render_forecast_chart(state, _forecast_result)
            state.intermediate_results["viz_result"] = result
            return state

        # ── Normal visualization path ─────────────────────────────────────────
        # Cold "plot X" requests route straight here with no upstream data. If
        # there's nothing to chart yet, fetch the series via sparql -> sql first
        # (otherwise the chart is empty and the turn fails with a generic error).
        def _has_series(d) -> bool:
            if not d:
                return False
            if isinstance(d, dict):
                return bool(d.get("data"))
            return bool(d)

        if not _has_series(data):
            logger.info("[viz_node] no prior data — fetching via sparql -> sql before charting")
            try:
                await self._sparql_node(state)
                await self._sql_node(state)
                data = state.query_results
            except Exception as _viz_fetch_err:
                logger.warning(f"[viz_node] data fetch for visualization failed: {_viz_fetch_err}")

        result = await self.viz_agent.create_visualization(state, latest_message, data)
        state.intermediate_results["viz_result"] = result
        return state

    async def _render_forecast_chart(
        self,
        state: ConversationState,
        forecast_result: dict,
    ) -> dict:
        """Generate and execute a matplotlib forecast chart with CI bands.

        Uses the code executor sandbox so no matplotlib import is needed in
        the orchestrator process itself.  All forecast data is serialised as
        inline Python literals inside the generated code string.
        """
        import json as _json

        # Extract forecast data from the stored result
        future_index = forecast_result.get("future_index", [])
        fc_values = forecast_result.get("forecast", [])
        lower_80 = forecast_result.get("lower_80", [])
        upper_80 = forecast_result.get("upper_80", [])
        lower_95 = forecast_result.get("lower_95", [])
        upper_95 = forecast_result.get("upper_95", [])
        sensor_label = forecast_result.get("sensor_label", "Sensor")
        model_name = forecast_result.get("model", "Statistical Model")
        unit = forecast_result.get("unit", "")
        horizon = forecast_result.get("horizon", "forecast")
        metrics = forecast_result.get("metrics") or {}
        rmse = metrics.get("rmse", 0)
        mae = metrics.get("mae", 0)
        mape = metrics.get("mape", 0)

        if not future_index or not fc_values:
            logger.warning("[viz_node] forecast_result has no data — falling back to generic viz")
            latest_message = state.messages[-1].content if state.messages else ""
            return await self.viz_agent.create_visualization(
                state, latest_message, state.query_results
            )

        # Inline data as Python literals so the sandbox has no import dependency
        code = f"""
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import base64
import io as _io
import warnings
warnings.filterwarnings('ignore')

# ── Forecast data (from ForecastAgent, previous turn) ─────────────────────
future_index  = {_json.dumps(future_index)}
fc_values     = {_json.dumps(fc_values)}
lower_80      = {_json.dumps(lower_80)}
upper_80      = {_json.dumps(upper_80)}
lower_95      = {_json.dumps(lower_95)}
upper_95      = {_json.dumps(upper_95)}
sensor_label  = {_json.dumps(sensor_label)}
model_name    = {_json.dumps(model_name)}
unit          = {_json.dumps(unit)}
horizon_label = {_json.dumps(horizon)}
rmse          = {rmse}
mae           = {mae}
mape          = {mape}

ts = pd.to_datetime(future_index)
n  = len(ts)

fig, ax = plt.subplots(figsize=(13, 6))
plt.style.use('seaborn-v0_8-whitegrid')

# 95% confidence band (lightest)
if lower_95 and upper_95:
    ax.fill_between(ts, lower_95, upper_95, alpha=0.12, color='steelblue',
                    label='95% Confidence Interval')

# 80% confidence band (slightly darker)
if lower_80 and upper_80:
    ax.fill_between(ts, lower_80, upper_80, alpha=0.25, color='steelblue',
                    label='80% Confidence Interval')

# Point forecast line
ax.plot(ts, fc_values, color='steelblue', linewidth=2.5,
        marker='o', markersize=3.5, markerfacecolor='white',
        markeredgewidth=1.5, label='Predicted Value', zorder=5)

# Dashed horizontal reference at first predicted value
ax.axhline(y=fc_values[0], color='gray', linestyle='--', linewidth=0.8,
           alpha=0.6, label=f'Baseline ({fc_values[0]:.2f}{{unit}})')

# Axis formatting
ax.set_title(
    f'Forecast: {{sensor_label}}\\n'
    f'Horizon: {{horizon_label}}  ·  Model: {{model_name}}  ·  '
    f'RMSE={{rmse:.3f}}{{unit}}  ·  MAE={{mae:.3f}}{{unit}}  ·  MAPE={{mape:.1f}}%',
    fontsize=11, pad=12,
)
ax.set_xlabel('Time', fontsize=10)
ax.set_ylabel(f'{"Value" if not unit else unit}', fontsize=10)

# Rotate x-axis labels
if n > 12:
    plt.xticks(rotation=45, ha='right', fontsize=8)
else:
    plt.xticks(rotation=30, ha='right', fontsize=9)

ax.legend(loc='upper right', fontsize=9, framealpha=0.85)

# Annotate first and last predicted value
ax.annotate(f'{{fc_values[0]:.2f}}{{unit}}',
            xy=(ts[0], fc_values[0]),
            xytext=(8, 8), textcoords='offset points',
            fontsize=8, color='steelblue')
ax.annotate(f'{{fc_values[-1]:.2f}}{{unit}}',
            xy=(ts[-1], fc_values[-1]),
            xytext=(-40, 8), textcoords='offset points',
            fontsize=8, color='steelblue')

plt.tight_layout()

# Output as base64
_buf = _io.BytesIO()
plt.savefig(_buf, format='png', bbox_inches='tight', dpi=110)
plt.close()
_buf.seek(0)
print("PLOT_BASE64: " + base64.b64encode(_buf.read()).decode('utf-8'))
print(f"Forecast chart for {{sensor_label}}: {{len(fc_values)}} time steps, horizon={{horizon_label}}")
"""

        # Execute in the code executor sandbox
        try:
            import httpx as _httpx

            from shared.config import settings as _cfg

            executor_url = f"http://{_cfg.CODE_EXECUTOR_HOST}:{_cfg.CODE_EXECUTOR_PORT}"
            resp = await _httpx.AsyncClient(timeout=45).post(
                f"{executor_url}/execute",
                json={"code": code},
            )
            exec_result = resp.json()
        except Exception as e:
            logger.error(f"[viz_node] Code executor call failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "formatted_response": "Could not render the forecast chart — code executor unavailable.",
            }

        # Parse output
        output = exec_result.get("output", "")
        error = exec_result.get("error", "")

        if error and "PLOT_BASE64" not in output:
            logger.warning(f"[viz_node] Forecast chart code error: {error[:200]}")
            return {
                "success": False,
                "error": error,
                "formatted_response": f"Chart generation failed: {error[:200]}",
            }

        # Extract base64 image
        media_payload = None
        for line in output.split("\n"):
            if line.startswith("PLOT_BASE64: "):
                b64 = line[len("PLOT_BASE64: ") :]
                media_payload = {"type": "image", "format": "png", "data": b64}
                break

        desc = (
            f"Forecast chart for **{sensor_label}** — {horizon}\n\n"
            f"- **Model:** {model_name}\n"
            f"- **Shaded bands:** 80% and 95% confidence intervals\n"
            f"- **Accuracy (hold-out):** RMSE={rmse:.3f}{unit} · MAE={mae:.3f}{unit} · MAPE={mape:.1f}%\n\n"
            f"> The shaded areas show prediction uncertainty: inner band = 80% CI, "
            f"outer band = 95% CI. Bands widen over time because uncertainty grows with the forecast horizon."
        )

        return {
            "success": True,
            "formatted_response": desc,
            "media": media_payload,
            "chart_type": "forecast_ci",
            "sensor": sensor_label,
            "model": model_name,
        }

    async def _self_description_node(self, state: ConversationState) -> ConversationState:
        """Describe OntoSage from its live configuration and this building's data.

        Never a written-out blurb: prose drifts from the system the moment anyone
        changes it. The capability list comes from the intent registry (which already
        merges per-building overlays), the grounding sources from the shared schema,
        and the figures from the active building's own graph — so the answer differs
        per building because the building differs, and a new capability appears here
        without anyone remembering to edit a paragraph.
        """
        from orchestrator.services.self_description import describe

        building_id = state.building_id or settings.BUILDING_ID
        try:
            from orchestrator.services.building_context import resolve_building_context

            building_name = resolve_building_context(building_id).name
        except Exception:
            building_name = getattr(settings, "BUILDING_NAME", "this building")

        try:
            from orchestrator.intents import get_intent_registry

            registry = get_intent_registry(building_id)
        except Exception as e:
            logger.warning(f"[self_description] intent registry unavailable: {e}")
            registry = None

        # What this building actually holds, computed now.
        facts: Dict[str, Any] = {}
        try:
            from orchestrator.services.building_metrics import get_building_metrics

            snap = await get_building_metrics().snapshot(building_id)
            for label, attr in (
                ("Sensors in the ontology", "total_sensors"),
                ("Instrumented points", "total_points"),
                ("Zones", "zone_count"),
            ):
                value = getattr(snap, attr, None)
                if value:
                    facts[label] = f"{value:,}"
        except Exception as e:
            logger.debug(f"[self_description] metrics unavailable: {e}")

        try:
            from orchestrator.services.adapters.registry import adapter_registry

            backends = list(getattr(adapter_registry, "_adapters", {}) or {})
            if backends:
                facts["Connected databases"] = ", ".join(sorted(backends))
        except Exception:
            pass

        # The grounding vocabulary is TTL, like everything else.
        source_types = None
        try:
            from orchestrator.agents.sparql_agent import SPARQLAgent

            rows = await SPARQLAgent()._execute_query(
                """PREFIX ontosage: <http://ontosage.org/capabilities#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?l WHERE {
  ?s a ontosage:SourceType ; rdfs:label ?l .
  FILTER(!CONTAINS(LCASE(STR(?l)), "deprecated"))
}"""
            )
            source_types = [
                b["l"]["value"]
                for b in (rows or {}).get("results", {}).get("bindings", [])
                if b.get("l")
            ] or None
        except Exception as e:
            logger.debug(f"[self_description] source types unavailable: {e}")

        state.intermediate_results["dialogue_response"] = describe(
            registry, building_name, facts=facts, source_types=source_types
        )
        state.current_intent = "self_description"
        return state

    async def _general_knowledge_node(self, state: ConversationState) -> ConversationState:
        """Answer an open-domain general-knowledge question directly via the LLM.

        Building-specific questions never reach here (they route through the data
        pipeline). This node handles definitions, explanations, world facts, coding
        help, and "what can you do" — anything the LLM can answer on its own.
        Answer length is auto-detected from the user's phrasing (short / summary /
        long), with a medium default, and the recent conversation is passed in so
        follow-ups ("explain that further") stay coherent.
        """
        user_query = state.messages[-1].content if state.messages else ""
        explicit_len = state.intermediate_results.get("answer_length")
        length = _detect_answer_length(user_query, explicit_len)
        directive = _LENGTH_DIRECTIVES[length]
        logger.info(
            f"[general_knowledge] answering open-domain query "
            f"(length={length}): '{user_query[:80]}'"
        )

        # Recent conversation context (cheap, bounded) so co-referential
        # follow-ups resolve. Summary + last few turns, oldest→newest.
        history_lines = []
        if state.summary:
            history_lines.append(f"Summary of earlier conversation:\n{state.summary}")
        for msg in state.messages[-6:-1]:  # exclude the current question
            role = "User" if msg.role == "user" else "Assistant"
            history_lines.append(f"{role}: {msg.content}")
        history_block = "\n".join(history_lines).strip()

        # ── Live-data augmentation ───────────────────────────────────────────
        # If the question needs CURRENT info (weather, latest news/prices/etc.)
        # the LLM can't know from its training cutoff, fetch it and have the LLM
        # summarise it. Any miss (no location, no results, fetch error) silently
        # falls back to a plain LLM answer.
        live_context = ""
        live_kind = None
        if getattr(settings, "LIVE_DATA_ENABLED", False):
            # Routing precedence:
            #   1. Weather is deterministically detectable AND has a dedicated free
            #      structured API (Open-Meteo) — the keyword detector wins so the
            #      LLM can't mis-route "weather in X" to a generic web search.
            #   2. Otherwise trust the classifier's LLM hint (it saw the full query
            #      + history) for the fuzzier "does this need live web data" call.
            #   3. Fall back to the keyword web heuristic when no hint was emitted.
            heuristic = _detect_live_data_need(user_query)
            if heuristic and heuristic[0] == "weather":
                need, route_source = heuristic, "heuristic_weather"
            else:
                need = _live_data_need_from_hint(
                    state.intermediate_results.get("live_data_hint"), user_query
                )
                route_source = "llm_hint"
                if need is None:
                    need, route_source = heuristic, "heuristic"
            if need:
                state.intermediate_results["live_data_route"] = route_source
                kind, arg = need
                try:
                    from orchestrator.services.live_data_service import (
                        get_live_data_service,
                    )

                    svc = get_live_data_service()
                    if kind == "weather" and getattr(settings, "WEATHER_ENABLED", False) and arg:
                        wx = await svc.get_weather(arg)
                        if wx:
                            live_context = (
                                "=== Live weather data (use this; it is current) ===\n"
                                + svc.format_weather(wx)
                            )
                            live_kind = "weather"
                    elif kind == "web" and getattr(settings, "WEB_SEARCH_ENABLED", False):
                        results = await svc.web_search(arg)
                        if results:
                            live_context = (
                                "=== Live web search results (use these; they are current) ===\n"
                                + svc.format_search_results(results)
                            )
                            live_kind = "web"
                    if live_kind:
                        logger.info(f"[general_knowledge] live-data augmentation: {live_kind}")
                except Exception as _ld_err:  # noqa: BLE001
                    logger.warning(f"[general_knowledge] live-data fetch skipped: {_ld_err}")
        state.intermediate_results["general_knowledge_live"] = live_kind

        bctx_name = getattr(settings, "BUILDING_NAME", None) or "the building"
        _today = time.strftime("%Y-%m-%d")
        system_message = (
            "You are OntoSage, a helpful assistant. Your primary specialty is smart "
            f"building management for {bctx_name}, but you can and should answer "
            "general-knowledge questions directly and accurately when asked. "
            "Answer the user's question on its merits. Do not redirect the user back "
            "to building topics, and do not refuse simply because the question is not "
            "about the building. If you genuinely do not know, say so briefly. "
            f"Today's date is {_today}. "
        )
        # This node has no access to the building's sensors, so any figure it gives
        # for this building would be invented. Saying "the specialty is building
        # management" without this makes inventing one the natural completion —
        # observed live as a fabricated humidity and CO2 reading for a room that has
        # neither sensor (BUG-123). The routing contract's concept stage should have
        # sent such questions to the data path; this is the backstop for the ones it
        # misses, and it costs nothing on genuine open-domain questions.
        system_message += (
            f"HARD CONSTRAINT: you have NO access to live sensors, meters or records "
            f"for {bctx_name}. Never state a measurement, reading, status, count or "
            f"date for {bctx_name} — not even an estimate, typical value or plausible "
            "range. If the question asks for one, say plainly that you do not have "
            "that reading and that it must come from the building's own data, then "
            "stop. You may still explain concepts, standards and how things work in "
            "general. "
        )
        if live_context:
            system_message += (
                "Live data is provided below the question — base your answer ONLY on "
                "it for anything time-sensitive, and cite the source(s). "
            )
        system_message += f"LENGTH: {directive}"

        prompt_parts = []
        if history_block:
            prompt_parts.append(f"=== Conversation so far ===\n{history_block}\n")
        prompt_parts.append(f"=== Question ===\n{user_query}")
        if live_context:
            prompt_parts.append(f"\n{live_context}")
        prompt = "\n".join(prompt_parts)

        try:
            answer = await llm_manager.generate(
                prompt,
                system_message=system_message,
                task_type=TaskType.GENERAL,
            )
            answer = (answer or "").strip()
            if not answer:
                raise ValueError("empty LLM answer")
            state.intermediate_results["dialogue_response"] = answer
            state.intermediate_results["general_knowledge_answer"] = answer
            state.intermediate_results["answer_length_used"] = length
        except Exception as e:
            logger.error(f"[general_knowledge] LLM call failed: {e}", exc_info=True)
            # Fall back to any draft the classifier produced, else a graceful note.
            fallback = state.intermediate_results.get("general_knowledge_draft")
            state.intermediate_results["dialogue_response"] = fallback or (
                "I wasn't able to generate an answer just now. Please try asking "
                "again in a moment."
            )
            state.intermediate_results["error"] = f"general_knowledge: {e}"
        return state

    # Audience/voice hints for the P1.4 synthesis pass.
    _SYNTH_PERSONA_VOICE = {
        "general": "a general building occupant — clear, plain language",
        "occupant": "a building occupant — clear, plain language",
        "facility_manager": "a facility manager — operational, action-oriented",
        "stakeholder": "a facility manager — operational, action-oriented",
        "analyst": "a data analyst — precise and quantitative",
        "executive": "an executive — concise, outcome-focused, minimal jargon",
        "safety_officer": "a safety officer — compliance- and risk-focused",
        "researcher": "a researcher — detailed and technical",
        "student": "a student — approachable, lightly explanatory",
    }

    async def _synthesize_answer(self, state: ConversationState, draft: str) -> str:
        """P1.4 — rewrite the deterministic draft into one unified, persona-aware
        answer via a single grounded LLM pass.

        Strictly grounded: the model may use ONLY facts present in the draft.
        Falls back to the draft unchanged on any error (fully safe).
        """
        if not draft or not draft.strip():
            return draft
        persona = (getattr(state, "persona", "general") or "general").lower()
        voice = self._SYNTH_PERSONA_VOICE.get(persona, self._SYNTH_PERSONA_VOICE["general"])
        user_q = state.user_message or (state.messages[-1].content if state.messages else "")

        # A verdict ("very strong", "high") claims the value was compared against
        # something. When the number cannot be a reading of that quantity in ANY
        # usual unit there is nothing to compare it to, and the verdict is a
        # fabrication wearing a real number (CAVEAT-053). Attach the caveat to the
        # draft — synthesis is instructed to keep ⚠️ lines verbatim — and forbid the
        # judgement outright, so the reply reports the number without ruling on it.
        # The response node attaches the implausibility caveat before this runs. When
        # it is present, forbid the rewrite from re-introducing the judgement it was
        # added to remove — otherwise synthesis would keep the warning and restate
        # "very strong" underneath it.
        _no_verdict = ""
        if "raw or unscaled sensor output" in draft:
            _no_verdict = (
                "- The reading is flagged as implausible. Report the number, but do NOT "
                "describe it as high, low, strong, weak, normal or comfortable — there "
                "is no reliable scale to judge it against.\n"
            )
        system_message = (
            "You are OntoSage, the assistant for a smart building. You rewrite a "
            "draft answer into one clear, natural reply. You NEVER invent data."
        )
        prompt = (
            "Rewrite the DRAFT below into a single, well-structured answer.\n\n"
            "HARD RULES:\n"
            "- Use ONLY the facts, numbers, sensor names, units, links, ticket IDs, "
            "and notes that appear in the DRAFT. Do NOT add or guess any data.\n"
            "- Preserve every numeric value and unit exactly as written.\n"
            "- Preserve markdown links, download URLs, ticket IDs, and any lines "
            "starting with '⚠️' or '*Note:' verbatim.\n"
            "- Do NOT add a follow-up question or an 'you might also ask' section.\n"
            "- Be concise; no preamble like 'Sure' or 'Here is'.\n"
            f"{_no_verdict}"
            f"- Audience/voice: {voice}.\n\n"
            f"USER QUESTION: {user_q}\n\n"
            f"DRAFT:\n{draft}\n\n"
            "REWRITTEN ANSWER:"
        )
        try:
            from orchestrator.llm_manager import TaskType, llm_manager

            out = await llm_manager.generate(
                prompt,
                system_message=system_message,
                temperature=0.3,
                task_type=TaskType.GENERAL,
            )
            out = (out or "").strip()
            return out or draft
        except Exception as _se:
            logger.debug(f"[synthesis] fallback to draft: {_se}")
            return draft

    async def _response_node(self, state: ConversationState) -> ConversationState:
        """Format final response — with response-cache store after generation.

        Phase 7B — all READS of `intermediate_results` for response building
        now flow through the typed `state.pipeline_ctx` snapshot.  Writes
        (cache storage, follow-up suggestions) continue to use the dict.
        """
        logger.info("Executing response node")

        # Phase 1: attach grounding verification record (rule-based, no LLM call)
        try:
            state = await self.verifier_agent.verify(state)
        except Exception as _ve:
            logger.debug(f"Verifier skipped: {_ve}")

        # Phase 7B — typed snapshot of the pipeline state.  Subsequent reads
        # benefit from IDE autocomplete + mypy safety.  The snapshot is taken
        # AFTER verifier.verify() so any keys it sets are visible.
        ctx = state.pipeline_ctx

        # Gather all results (with sensible empty-dict fallbacks for the
        # ones we want to chain .get() on)
        sparql_result = ctx.sparql_result or {}
        sql_result = ctx.sql_result or {}
        analytics_result = ctx.analytics_result or {}
        viz_result = ctx.viz_result or {}
        document_result = ctx.document_result or {}
        dialogue_response = ctx.dialogue_response

        # Build response - Prioritize most downstream result
        media_payload = None
        # P1.4 (targeted) — True only when the draft is a canned f-string template
        # (document/export/control/maintenance). Prose paths (analytics/sparql/
        # capability/etc.) are already LLM-generated, so synthesis is skipped there.
        _template_draft = False
        if dialogue_response:
            final_response = dialogue_response
        elif viz_result.get("formatted_response") and viz_result.get("media"):
            # Only use viz_result if it actually produced an image (has media payload)
            final_response = viz_result["formatted_response"]
            media_payload = viz_result.get("media")
        # Phase 4 results (highest priority after viz)
        elif ctx.planner_result and (
            ctx.planner_result.get("formatted_response") or ctx.planner_result.get("formatted_text")
        ):
            pr = ctx.planner_result
            final_response = pr.get("formatted_response") or pr.get("formatted_text")
        elif ctx.floor_plan_result:
            final_response = ctx.floor_plan_result
        elif document_result.get("success"):
            _template_draft = True
            filename = document_result.get("filename", "document")
            download_url = document_result.get("download_url")
            if download_url:
                final_response = f"Document ready — **{filename}**\n\nDownload: {download_url}"
            else:
                final_response = f"Document generated — **{filename}**"
        elif ctx.report_result and ctx.report_result.get("formatted_text"):
            final_response = ctx.report_result["formatted_text"]
        elif ctx.anomaly_result and ctx.anomaly_result.get("formatted_response"):
            final_response = ctx.anomaly_result["formatted_response"]
        elif ctx.export_result and ctx.export_result.get("success"):
            _template_draft = True
            er = ctx.export_result
            final_response = (
                f"✅ Export complete — **{er['filename']}** ({er['row_count']} rows, {er['size_bytes']} bytes).\n\n"
                f"Preview (first 2000 chars):\n```\n{er['content'][:2000]}\n```"
            )
        elif ctx.control_result and ctx.control_result.get("message"):
            _template_draft = True
            cr = ctx.control_result
            final_response = cr["message"]
        elif ctx.maintenance_result:
            _template_draft = True
            mr = ctx.maintenance_result
            op = mr.get("operation", "UNKNOWN")
            ticket_id = mr.get("ticket_id")
            if op == "CREATE" and ticket_id:
                final_response = (
                    f"✅ Maintenance ticket **{ticket_id}** created.\n"
                    f"- **Location:** {mr.get('location', 'unspecified')}\n"
                    f"- **Description:** {mr.get('description', 'No description')}\n"
                    f"- **Reporter:** {mr.get('reporter_id', 'unknown')}\n\n"
                    "A facility manager will be notified. You can check the status with "
                    f"`Check status of ticket {ticket_id}`."
                )
            elif op == "STATUS" and ticket_id:
                ticket_data = mr.get("ticket_data")
                if ticket_data:
                    final_response = (
                        f"📋 Ticket **{ticket_id}** — Status: **{ticket_data.get('status', 'unknown')}**\n\n"
                        f"- **Description:** {ticket_data.get('description', 'N/A')}\n"
                        f"- **Assigned to:** {ticket_data.get('assigned_to', 'unassigned')}\n"
                        f"- **Created:** {ticket_data.get('created_at', 'unknown')}"
                    )
                else:
                    final_response = (
                        f"Ticket **{ticket_id}** not found. Please check the ticket number."
                    )
            elif op == "LIST":
                tickets = mr.get("tickets", [])
                if tickets:
                    lines = [
                        f"📋 Open maintenance tickets for **{mr.get('building_id', 'this building')}**:\n"
                    ]
                    for t in tickets[:10]:
                        lines.append(
                            f"- **{t.get('ticket_id')}**: {t.get('description', '')[:60]} [{t.get('status')}]"
                        )
                    final_response = "\n".join(lines)
                else:
                    final_response = f"No open maintenance tickets for this building. ✅"
            elif mr.get("message"):
                final_response = mr["message"]
            else:
                final_response = f"Maintenance request processed (operation: {op})."
        elif analytics_result.get("formatted_response"):
            final_response = analytics_result["formatted_response"]
            media_payload = analytics_result.get("media")
            # Replace UUIDs with human-readable sensor names
            analytics_node_metadata = ctx.sensor_metadata or {}
            if analytics_node_metadata:
                for uuid, metadata in analytics_node_metadata.items():
                    if uuid in final_response:
                        final_response = final_response.replace(
                            uuid, metadata.get("label", "Unknown Sensor")
                        )
        elif sql_result.get("formatted_response"):
            final_response = sql_result["formatted_response"]
        elif sparql_result.get("formatted_response"):
            final_response = sparql_result["formatted_response"]
        else:
            final_response = "I processed your request, but couldn't generate a response."

        # ── Visualization honesty guard ───────────────────────────────────────
        # If the user explicitly asked for a chart but no image was produced,
        # say so plainly.  Previously the response node fell back to the analytics
        # stats text silently (it requires viz_result.media to use the viz path),
        # leaving users with a summary that *offered* a graph but never showed one.
        _latest_msg = state.messages[-1].content if state.messages else ""
        if (
            self._user_wants_visualization(_latest_msg)
            and not media_payload
            and state.current_intent not in ("clarification", "greeting", "general_knowledge")
        ):
            final_response += (
                "\n\n---\n*⚠️ I summarised the data above but couldn't render the "
                "chart this time. Please try again, or rephrase the request as e.g. "
                '"plot sensor 5.27 temperature for the last 24 hours as a line chart".*'
            )

        # ── CAP-04: Append auto-compliance block (if produced by analytics node)
        _compliance_block = ctx.compliance_context
        if _compliance_block and state.current_intent not in (
            "clarification",
            "greeting",
            "general_knowledge",
            "recommend",  # recommendations already include relevant thresholds
        ):
            final_response = f"{final_response}\n\n{_compliance_block}"

        # ── Floor-plan card injection ─────────────────────────────────────────
        # When any sensor/analytics/SQL response resolves to a known zone,
        # append a small floor-plan link so users can locate it on the plan.
        # NOTE: must use raw dict for `key not in` semantics — `ctx.X is None`
        # doesn't distinguish "key absent" from "key set to None".
        _fp_intent_ok = state.current_intent not in (
            "floor_plan",
            "clarification",
            "greeting",
            "general_knowledge",
        )
        if _fp_intent_ok and "floor_plan_result" not in state.intermediate_results:
            _fc = state.floor_context or {}
            _zone = _fc.get("zone")
            _bid = _fc.get("building_id") or settings.BUILDING_ID
            if _zone and "floor-plans" not in final_response:
                try:
                    from orchestrator.services.floor_plan_service import (
                        floor_plan_service,
                    )

                    _fp_link = floor_plan_service.suggest_floor_plan_link(_zone, _bid)
                    if _fp_link:
                        final_response += _fp_link
                except Exception as _fpe:
                    logger.debug(f"Floor-plan card injection skipped: {_fpe}")

        # If any nodes degraded, append a brief notice so the user knows
        degraded = state.intermediate_results.get("degraded_services")
        if degraded:
            notices = set(d["message"] for d in degraded)
            notice_text = "\n\n---\n*Note: " + " ".join(notices) + "*"
            final_response += notice_text

        # CAVEAT-053 — a verdict ("very strong", "high") claims the value was
        # compared against something. When the number cannot be a reading of that
        # quantity in ANY usual unit there is nothing to compare it to, and the
        # verdict is a fabrication wearing a real number. Checked HERE, where every
        # path's answer converges: the analytics path writes its own prose and never
        # reaches the synthesis pass, which is exactly where this was first seen.
        try:
            from orchestrator.services.plausibility import implausibility_note

            _pl_note = implausibility_note(state.user_message or "", final_response)
            if _pl_note and _pl_note[:12] not in final_response:
                final_response = f"{_pl_note}\n\n{final_response}"
        except Exception as _ple:  # a guard must never cost the answer
            logger.debug(f"[plausibility] check skipped: {_ple}")

        # Phase 1.4 (targeted) — grounded synthesis ONLY rewrites canned-template
        # drafts (export/maintenance/control/document) into natural prose. The
        # already-LLM-generated prose paths keep the existing persona formatter,
        # so synthesis adds no extra round-trip where it isn't needed. Falls back
        # to the draft on any error.
        _synthesis_on = getattr(settings, "RESPONSE_SYNTHESIS_ENABLED", False)
        _did_synthesize = False
        if _synthesis_on and _template_draft:
            final_response = await self._synthesize_answer(state, final_response)
            _did_synthesize = True
        else:
            # Persona formatting (first pass)
            final_response = await self.dialogue_agent.format_response(
                state, final_response, state.current_intent
            )

        # Phase 7.2: Append proactive follow-up suggestions based on intent
        suggestions = self._get_follow_up_suggestions(state.current_intent)
        if suggestions:
            final_response += f"\n\n---\n**You might also ask:** {suggestions}"

        # CAP-03: Persona-aware post-processing (second pass). Skipped when synthesis
        # ran — synthesis already produced the persona-appropriate voice.
        persona = getattr(state, "persona", "general") or "general"
        if not _did_synthesize and persona and persona != "general":
            try:
                from orchestrator.llm_manager import llm_manager as _llm

                final_response = await self._persona_adapter.enhance(
                    final_response,
                    persona=persona,
                    intent=state.current_intent or "general",
                    llm_manager=_llm,
                )
            except Exception as _pa_err:
                logger.debug(f"Persona adapter skipped: {_pa_err}")

        # WIRE-A: i18n — translate response back to user's language
        _user_lang = state.intermediate_results.get("_user_lang", "en")
        if self._i18n and _user_lang and _user_lang != "en":
            try:
                final_response = await self._i18n.from_english(final_response, _user_lang)
                logger.info(f"i18n: translated response to {_user_lang}")
            except Exception as _i18n_out_err:
                logger.debug(f"i18n output translation skipped: {_i18n_out_err}")

        # Provenance chips — name the data source(s) that produced this answer.
        # No-op unless the datasource-toggles feature is on (guarded so existing
        # behaviour and tests are unchanged when the flag is off).
        if getattr(settings, "DATASOURCE_TOGGLES_ENABLED", False):
            try:
                _reg = getattr(self, "datasource_registry", None)
                _stores = state.intermediate_results.get("_prov_stores", [])
                _tags = _prov.build_tags(_stores, _reg)
                if _tags:
                    state.intermediate_results["sources"] = _prov.tags_to_dicts(_tags)
                    final_response += _prov.render_chips(_tags)
            except Exception as _pe:
                logger.debug(f"provenance rendering skipped: {_pe}")

        # Add to messages
        state.messages.append(
            Message(
                role="assistant",
                content=final_response,
                metadata={"media": media_payload} if media_payload else None,
            )
        )

        # B.2: Store in response cache (non-blocking, best-effort)
        if self.response_cache:
            try:
                original_query = state.messages[-2].content if len(state.messages) >= 2 else ""
                if original_query:
                    await self.response_cache.put(
                        question=original_query,
                        response=final_response,
                        intent=state.current_intent or "general",
                        media=[media_payload] if media_payload else [],
                        building_id=state.building_id,
                    )
            except Exception as _cache_err:
                logger.debug(f"Response cache store skipped: {_cache_err}")

        # B.3: Store successful interaction in agent memory for future context retrieval
        # Phase 5: Also store failures so the correction corpus grows.
        if self.agent_memory and state.user_id:
            try:
                original_query = state.messages[-2].content if len(state.messages) >= 2 else ""
                entities = state.intermediate_results.get("entities", [])
                _verification = state.intermediate_results.get("verification", {})
                _is_grounded = _verification.get("grounded", True)
                _degraded = state.intermediate_results.get("degraded_services")
                _has_error = bool(state.intermediate_results.get("error"))

                if _is_grounded and not _has_error and not _degraded:
                    await self.agent_memory.store_success(
                        user_id=state.user_id,
                        query=original_query,
                        intent=state.current_intent or "general",
                        entities=entities if isinstance(entities, list) else [],
                        answer_summary=final_response[:200],
                    )
                else:
                    # Phase 5 — capture failure for correction corpus
                    error_info = state.intermediate_results.get("error") or (
                        f"degraded: {_degraded}" if _degraded else "ungrounded"
                    )
                    await self.agent_memory.store_failure(
                        user_id=state.user_id,
                        query=original_query,
                        intent=state.current_intent or "general",
                        entities=entities if isinstance(entities, list) else [],
                        error_summary=str(error_info)[:200],
                        persona=getattr(state, "persona", "general") or "general",
                    )
                # ── Phase 7.4-B: Detect and persist user preferences ──────────
                if original_query:
                    try:
                        await self.agent_memory.detect_and_store_preferences(
                            user_id=state.user_id,
                            query=original_query,
                            answer_summary=final_response[:200],
                        )
                    except Exception as _pref_err:
                        logger.debug(f"Preference detection skipped: {_pref_err}")
            except Exception as _mem_err:
                logger.debug(f"Agent memory store skipped: {_mem_err}")

        # Phase 5.5: Clean up bulky intermediate results to reduce Redis state size
        _bulky_keys = [
            "sparql_result",
            "sql_result",
            "analytics_result",
            "viz_result",
            "sensor_metadata",
            "degraded_services",
            "memory_context",
            "compliance_context",  # consumed above; clear after appending
            "floor_plan_result",  # consumed above; clear after appending
            "floor_plan_structured",  # consumed by response node; clear after appending
            "floor_context_hint",  # consumed by SPARQL agent; clear so it doesn't bleed across turns
        ]
        for key in _bulky_keys:
            state.intermediate_results.pop(key, None)

        return state

    async def _ontology_census(self, query: str) -> List[Tuple[str, int]]:
        """Class→count for what this building holds, from the ontology.

        The one place any "what does this building have" answer gets its grouping,
        shared with the capability path so the two cannot disagree.
        """
        try:
            from orchestrator.agents.sparql_agent import (
                GRAPHDB_QUERY_ENDPOINT,
                _active_namespace,
            )
            from orchestrator.services.ontology_inventory import class_census

            return await class_census(query, _active_namespace(), GRAPHDB_QUERY_ENDPOINT)
        except Exception as e:
            logger.warning(f"[discovery] ontology census unavailable: {e}")
            return []

    def _handle_sensor_discovery(
        self,
        discovery_filter: str = None,
        entities: list = None,
        census: Optional[List[Tuple[str, int]]] = None,
    ) -> str:
        """
        Build a sensor discovery response from the cached sensor_map.

        Args:
            census: class→count from the ontology, used to group large result sets.
                Passed in (not fetched here) because this method is synchronous and
                per-request state must not live on the shared orchestrator instance.
            discovery_filter: Optional keyword to filter sensors (e.g. "temperature", "zone 5")
            entities: Optional entity list from intent detection

        Returns:
            Formatted string listing available sensors
        """
        if not self.sensor_map:
            return (
                "I don't have a cached sensor catalogue right now. "
                "You can ask me about specific sensor types like temperature, "
                "humidity, or air quality sensors."
            )

        # Deduplicate: sensor_map has multiple key formats (name, label, URI) pointing
        # to the same sensor. Collect unique sensors by their URI.
        unique_sensors = {}
        for key, info in self.sensor_map.items():
            uri = info.get("uri", key)
            if uri not in unique_sensors:
                unique_sensors[uri] = {
                    "label": info.get("label", key),
                    "uuid": info.get("uuid", ""),
                    "storage": info.get("storage", ""),
                }

        # Apply filter
        filter_text = discovery_filter or ""
        if entities and not filter_text:
            filter_text = " ".join(entities)
        filter_lower = filter_text.lower().strip()

        if filter_lower:
            filtered = {
                uri: s
                for uri, s in unique_sensors.items()
                if filter_lower in s["label"].lower() or filter_lower in uri.lower()
            }
        else:
            filtered = unique_sensors

        total = len(unique_sensors)
        matched = len(filtered)

        if matched == 0:
            # No match — show summary of available types
            type_counts = self._count_sensor_types(unique_sensors)
            type_summary = ", ".join(
                f"**{t}** ({c})" for t, c in sorted(type_counts.items(), key=lambda x: -x[1])[:10]
            )
            return (
                f'I couldn\'t find sensors matching **"{filter_text}"**.\n\n'
                f"I have **{total}** sensors total. Available types: {type_summary}.\n\n"
                f'Try asking about a specific type (e.g., *"list all temperature sensors"*).'
            )

        # If too many results, show a grouped summary. The grouping comes from the
        # ontology (the same census the capability path uses), never from the
        # labels — see _count_sensor_types for why label parsing cannot group.
        if matched > 20:
            if census:
                type_summary = "\n".join(f"- **{t.replace('_', ' ')}**: {c}" for t, c in census)
                filter_note = f' matching **"{filter_text}"**' if filter_lower else ""
                # `matched` counts instrumented POINTS (sensors, setpoints and
                # commands all carry a timeseries id); the census counts what the
                # ontology types as each class. Calling the first figure "sensors"
                # made the header contradict its own breakdown — 600 vs 304.
                return (
                    f"This building has **{matched}** instrumented points{filter_note} "
                    f"with live data. By ontology type:\n\n{type_summary}\n\n"
                    f'To see specific sensors, ask for one type — e.g. *"list the zone air '
                    f'temperature sensors"*.'
                )
            type_counts = self._count_sensor_types(filtered)
            type_summary = "\n".join(
                f"- **{t}**: {c} sensors"
                for t, c in sorted(type_counts.items(), key=lambda x: -x[1])
            )
            filter_note = f' matching **"{filter_text}"**' if filter_lower else ""
            return (
                f"Found **{matched}** sensors{filter_note} (out of {total} total):\n\n"
                f"{type_summary}\n\n"
                f'To see specific sensors, ask something like *"list all Air Temperature sensors"* '
                f'or *"what sensors are in zone 5?"*.'
            )

        # Show individual sensors
        lines = []
        for uri, s in sorted(filtered.items(), key=lambda x: x[1]["label"]):
            lines.append(f"- **{s['label']}** (storage: {s['storage'] or 'N/A'})")

        sensor_list = "\n".join(lines)
        filter_note = f' matching **"{filter_text}"**' if filter_lower else ""
        return (
            f"Found **{matched}** sensors{filter_note}:\n\n{sensor_list}\n\n"
            f"You can ask about any of these sensors, for example: "
            f"*\"What is the current reading of {list(filtered.values())[0]['label']}?\"*"
        )

    @staticmethod
    def _count_sensor_types(sensors: dict) -> dict:
        """Group sensors by type parsed from their LABEL — last-resort fallback only.

        This works only where a building encodes the type in the label and ends it
        with an identifier ("Air Temperature Sensor 5.04" → "Air Temperature
        Sensor"). A building whose labels do not follow that shape — e.g.
        "…RM163E.Zone Air Temp" — gets every sensor as its own "type", which is how
        600 sensors were once reported as 600 types of one each. Callers pass an
        ontology census instead; this remains for when the graph is unreachable.
        """
        type_counts = {}
        for uri, info in sensors.items():
            label = info.get("label", "")
            # Extract type: everything before the last underscore + number pattern
            # e.g. "Air Temperature Sensor 5.04" -> "Air Temperature Sensor"
            parts = label.rsplit(" ", 1)
            if len(parts) == 2 and any(c.isdigit() for c in parts[1]):
                sensor_type = parts[0]
            else:
                sensor_type = label
            type_counts[sensor_type] = type_counts.get(sensor_type, 0) + 1
        return type_counts

    async def _absent_sensor_type_message(self, query: str) -> Optional[str]:
        """Honest "no such sensors" when a count/list query names a sensor TYPE whose head
        term appears in NO sensor class or label of the ACTIVE building. Building-agnostic
        (checks the live graph); returns None (proceed normally) unless confident the type
        is absent, so legitimate types are never blocked."""
        if not getattr(settings, "REFERENT_VALIDATION_ENABLED", True):
            return None
        import re as _re

        ql = (query or "").lower()
        if not any(w in ql for w in ("how many", "number of", "count of", "are there", "list ")):
            return None
        if "sensor" not in ql:
            return None
        before = ql.split("sensor")[0]
        stop = {
            "how",
            "what",
            "does",
            "do",
            "did",
            "have",
            "has",
            "there",
            "are",
            "is",
            "was",
            "give",
            "show",
            "tell",
            "the",
            "me",
            "us",
            "you",
            "can",
            "could",
            "would",
            "list",
            "count",
            "many",
            "number",
            "of",
            "all",
            "any",
            "some",
            "other",
            "much",
            "most",
            "type",
            "types",
            "kind",
            "kinds",
            "level",
            "installed",
            "node",
            "space",
            "spaces",
            "indoor",
            "outdoor",
            "internal",
            "external",
            "main",
            "primary",
            "secondary",
            "total",
            "live",
            "current",
            "real",
            "new",
            "old",
            "room",
            "zone",
            "floor",
            "area",
            "building",
            "this",
            "that",
            "its",
            "in",
            "on",
            "for",
            "with",
        }
        words = [w for w in _re.split(r"[^a-z0-9]+", before) if len(w) > 2 and w not in stop]
        if not words:
            return None
        lead = words[0]
        try:
            q = (
                "PREFIX brick:<https://brickschema.org/schema/Brick#> "
                "PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#> "
                "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { "
                "?s a ?c . ?c rdfs:subClassOf* brick:Sensor . "
                "OPTIONAL { ?s rdfs:label ?l } "
                f'FILTER(CONTAINS(LCASE(STR(?c)), "{lead}") || CONTAINS(LCASE(STR(?l)), "{lead}")) }}'
            )
            res = await self.sparql_agent._execute_query(q)
            bindings = res.get("results", {}).get("bindings", [])
            n = int(bindings[0]["n"]["value"]) if bindings else 0
        except Exception as e:  # graph down / malformed → fail OPEN
            logger.warning(f"[sensor_type_gate] existence check failed, proceeding: {e}")
            return None
        if n > 0:
            return None  # the type is present → answer normally
        readable = " ".join(words)
        return (
            f"This building doesn't have any **{readable} sensors**. I only report what its "
            "ontology actually contains. Ask about a sensor type it has — e.g. temperature, "
            "humidity, CO₂, air quality, water flow, or pressure — or ask "
            '*"what types of sensors does this building have?"*'
        )

    def _check_locked_capability(self, state: ConversationState) -> Optional[str]:
        """Return the id of a DISABLED data source whose keyword the query matches.

        Conservative gate for the locked-capability UX: fires only when the
        datasource-toggles feature is on, a registry + manager are available, and
        a curated `match_keywords` phrase for a *disabled* source appears in the
        query. Returns None otherwise (so normal routing proceeds unchanged).
        """
        if not getattr(settings, "DATASOURCE_TOGGLES_ENABLED", False):
            return None
        reg = getattr(self, "datasource_registry", None)
        mgr = getattr(self, "datasource_manager", None)
        if reg is None or mgr is None:
            return None
        # Only gate genuine LIVE-DATA requests. An informational / how-to / report question
        # that merely mentions a disabled-source keyword ("how do I make a complaint", "what
        # are the occupancy limits", "the toilet is leaking") must pass through to normal
        # routing (documents / graph triples / report_intake) — the "enable X" toggle message
        # is only for "I want the live X data / metric / trend", not for policy/how-to/report
        # phrasings. Without this, the gate intercepts and mis-answers them (CAVEAT-017).
        _intent = state.current_intent or state.intermediate_results.get("intent")
        if _intent not in _LIVE_DATA_INTENTS:
            return None
        query = (state.messages[-1].content if state.messages else "") or ""
        ql = query.lower()
        role = state.intermediate_results.get("user_role")
        for spec in reg.list():
            if not spec.match_keywords:
                continue
            if not any(kw in ql for kw in spec.match_keywords):
                continue  # this question doesn't need this source
            # The question needs this source. Two ways it can be gated:
            if not mgr.is_enabled(spec.id):
                state.intermediate_results["locked_reason"] = "disabled"
                return spec.id  # globally off → "enable X to unlock"
            # enabled, but does this user's ROLE have access?
            try:
                from orchestrator.services import admin_config

                if not admin_config.is_source_allowed(role, spec.id):
                    state.intermediate_results["locked_reason"] = "forbidden"
                    state.intermediate_results["locked_role"] = role or "your role"
                    return spec.id
            except Exception as _ae:  # non-fatal: access check never blocks routing
                logger.debug(f"[locked_capability] role-access check skipped: {_ae}")
        return None

    async def _locked_capability_node(self, state: ConversationState) -> ConversationState:
        """Decline gracefully, naming the disabled source and what enabling unlocks."""
        logger.info(
            f"[locked_capability] node entered: intent={state.intermediate_results.get('intent')}"
        )
        # locked_source may be absent: routing-function state mutations are not
        # persisted by LangGraph, so re-derive the source here as the node entry point.
        source_id = state.intermediate_results.get("locked_source")
        if not source_id:
            source_id = self._check_locked_capability(state)
            if source_id:
                state.intermediate_results["locked_source"] = source_id
        reg = getattr(self, "datasource_registry", None)
        spec = reg.get(source_id) if (reg and source_id) else None
        if spec is None:
            state.intermediate_results["dialogue_response"] = (
                "That question needs a data source that isn't available yet."
            )
            return state
        reason = state.intermediate_results.get("locked_reason", "disabled")
        if reason == "forbidden":
            role = state.intermediate_results.get("locked_role", "your role")
            state.intermediate_results["dialogue_response"] = (
                f"🔒 This question needs the **{spec.provenance_system}**, but your role "
                f"(**{role}**) doesn't have access to the **{spec.label}** data source.\n\n"
                f"Ask an administrator to grant your role access in the admin console."
            )
            logger.info(f"[locked_capability] denied — role '{role}' lacks access to '{source_id}'")
            return state
        unlocks = (
            "\n".join(f"- {tag.replace('_', ' ')}" for tag in spec.unlocks)
            or "- additional question types"
        )
        note = (
            "\n\n_This is simulated data, injected to demonstrate the capability._"
            if spec.synthetic
            else ""
        )
        state.intermediate_results["dialogue_response"] = (
            f"🔒 This question needs the **{spec.provenance_system}**, which is currently "
            f"switched **off**.\n\n"
            f"Enable the **{spec.label}** data source in the configuration panel to unlock:\n"
            f"{unlocks}{note}"
        )
        logger.info(f"[locked_capability] declined — source '{source_id}' disabled")
        return state

    def _route_from_dialogue(self, state: ConversationState) -> str:
        """Route from dialogue node based on intent.

        Phase 6D — the imperative if/elif chain that lived here was replaced
        by `orchestrator.intents.IntentRegistry.route_target_for()`.  Routing
        for known intents is now data-driven: each intent declares its target
        node (or relies on the pipeline_group default) in `intent_definitions.yaml`.

        A handful of *contextual* overrides remain in code because they depend
        on the user query text, not just the intent label:
          - "floor_plan" keyword detection on the raw query
          - "floor_plan" misroute when comparison+data keywords appear
          - "discovery" with spatial words → sparql instead of response
          - cached-data short-circuit for analytics-family intents

        Phase 13A — every override/decision logs a structured route_decision
        record under state.intermediate_results["route_decision"] so we can
        audit routing correctness without guessing from interleaved logs.
        """
        intent = state.current_intent
        original_intent = intent  # for the audit trail
        user_query = state.messages[-1].content if state.messages else ""

        # ── Locked-capability gate (datasource-toggles) ─────────────────────
        # If the query explicitly needs a DISABLED synthetic source, decline with
        # an "enable X to unlock this" message instead of returning an empty/wrong
        # answer. Conservative + flag-gated; no-op when the feature is off.
        _locked_source = self._check_locked_capability(state)
        if _locked_source:
            state.intermediate_results["locked_source"] = _locked_source
            state.intermediate_results["route_decision"] = {
                "intent_from_dialogue": original_intent,
                "final_node": "locked_capability",
                "decision_source": "override",
                "overrides_applied": [f"locked_capability:{_locked_source}"],
            }
            return "locked_capability"

        # Phase 13A — structured audit trail.  Updated incrementally as we
        # walk through overrides; flushed at end of routing.
        route_decision: Dict[str, Any] = {
            "intent_from_dialogue": original_intent,
            "intent_after_overrides": original_intent,
            "overrides_applied": [],
            "final_node": None,
            "decision_source": "registry",  # 'registry' | 'override' | 'fallback'
        }

        # ── Contextual override #0: building-wide inventory-count / size ──────────
        # "how many sensors are there?" / "total floor area" must be answered from a
        # live SPARQL COUNT + DWG area — NOT the sensor_data pipeline (which fetches one
        # reading → "1 sensor") and not frozen KB prose. Route to the capability node,
        # whose BuildingMetrics grounding computes the figure from the graph. This is a
        # deterministic override because the LLM misclassifies these across
        # sensor_data / discovery / capability (FIX-003).
        try:
            from orchestrator.services.building_metrics import (
                is_inventory_count_question,
            )

            if is_inventory_count_question(user_query):
                logger.info(
                    "[route] inventory-count question → capability (live metrics grounding)"
                )
                state.current_intent = "capability"
                route_decision["intent_after_overrides"] = "capability"
                route_decision["overrides_applied"].append("inventory_count_to_metrics")
                route_decision["decision_source"] = "override"
                route_decision["final_node"] = "capability"
                state.intermediate_results["route_decision"] = route_decision
                return "capability"
        except Exception as e:  # never let routing crash on the override
            logger.debug(f"[route] inventory-count override skipped: {e}")

        # Lazy import to avoid circular load at module import time.
        # Phase 11A: pass per-request building_id so YAML overlays for the
        # active tenant apply (e.g. bldg2's lab_equipment intent).
        from orchestrator.intents import get_intent_registry

        _registry = get_intent_registry(getattr(state, "building_id", None))

        # The "non-floor-plan" exclusion set used by the floor-plan keyword
        # override.  Built from every intent that has its OWN grounding so
        # the heuristic doesn't steal queries that another agent answers.
        # That includes both the data pipeline group AND standalone agents
        # like capability (KB) and maintenance (ticket DB).
        _data_intents = (
            _registry.in_group("data")
            | _registry.in_group("standalone")
            | frozenset({"sparql", "sql", "comparison"})  # pipeline stages + alias
        ) - frozenset(
            {"floor_plan"}
        )  # floor_plan itself remains routable here

        # ── Contextual override #1: floor_plan misroute for compare queries ──
        if intent == "floor_plan":
            _ql = user_query.lower()
            _COMPARE_KW = frozenset(
                {"compare", "comparison", " vs ", " versus ", "difference between"}
            )
            _DATA_KW = frozenset(
                {
                    "temperature",
                    "co2",
                    "energy",
                    "humidity",
                    "sensor",
                    "consumption",
                    "usage",
                    "reading",
                    "level",
                    "analytics",
                    "trend",
                    "data",
                    "noise",
                    "light",
                    "occupancy",
                    "carbon",
                    "emission",
                }
            )
            if any(kw in _ql for kw in _COMPARE_KW) and any(kw in _ql for kw in _DATA_KW):
                logger.info(
                    "[route] floor_plan → comparison override (compare+data keywords in query)"
                )
                intent = "comparison"
                state.current_intent = "comparison"
                route_decision["intent_after_overrides"] = "comparison"
                route_decision["overrides_applied"].append("floor_plan_to_comparison_keywords")
                route_decision["decision_source"] = "override"

        # ── Contextual override #2: floor_plan keyword detection ──
        # Don't let a "floor N" mention steal an actuation command ("open the
        # windows on floor 3") or a report ("the toilet on floor 3 is leaking").
        _floor_plan_protected = (
            "control",
            "maintenance",
            "complaint",
            "safety_report",
            "suggestion",
            "feedback",
        )
        if intent == "floor_plan" or (
            floor_plan_service.is_floor_plan_query(user_query)
            and intent not in _data_intents
            and intent not in _floor_plan_protected
        ):
            logger.info(f"[route] floor_plan query detected (intent={intent})")
            if intent != "floor_plan":
                route_decision["overrides_applied"].append("floor_plan_keyword_detection")
                route_decision["decision_source"] = "override"
            state.current_intent = "floor_plan"
            route_decision["intent_after_overrides"] = "floor_plan"
            route_decision["final_node"] = "floor_plan"
            state.intermediate_results["route_decision"] = route_decision
            return "floor_plan"

        # ── Contextual override #3: discovery with spatial words → sparql ──
        if intent == "discovery":
            _ql = user_query.lower()
            spatial_words = [
                "zone",
                "floor",
                "room",
                "space",
                "level",
                "area",
                "location",
                "list zone",
                "list floor",
                "list room",
                "how many zone",
                "how many floor",
                "how many room",
            ]
            if any(w in _ql for w in spatial_words):
                route_decision["overrides_applied"].append("discovery_spatial_words")
                route_decision["decision_source"] = "override"
                route_decision["final_node"] = "sparql"
                state.intermediate_results["route_decision"] = route_decision
                return "sparql"
            route_decision["final_node"] = "response"
            state.intermediate_results["route_decision"] = route_decision
            return "response"

        # Open-domain general-knowledge → dedicated answering node.
        if intent == "general_knowledge":
            route_decision["final_node"] = "general_knowledge"
            state.intermediate_results["route_decision"] = route_decision
            return "general_knowledge"

        # Direct-to-response group (no override needed beyond what the registry
        # already says: pipeline_group=meta → route_target=response).
        if intent in ("greeting", "clarification", "unknown"):
            route_decision["final_node"] = "response"
            state.intermediate_results["route_decision"] = route_decision
            return "response"

        # ── Contextual override #4: analytics-family short-circuit when prior data exists ──
        if intent in ("analytics", "compare", "trend", "recommend", "compliance"):
            if state.intermediate_results.get("use_existing_query_results"):
                logger.info(
                    "[route] Compliance/follow-up with existing data — routing directly to analytics"
                )
                route_decision["overrides_applied"].append("analytics_followup_existing_data")
                route_decision["decision_source"] = "override"
                route_decision["final_node"] = "analytics"
                state.intermediate_results["route_decision"] = route_decision
                return "analytics"
            # Fall through to registry dispatch (default → sparql)

        # ── Default dispatch from the registry ──
        target = _registry.route_target_for(intent)
        if target:
            # Phase 10G — safety net: if a YAML-added intent's route_target
            # points to a node that isn't registered in _build_graph, fall
            # back to "response" so LangGraph doesn't crash with
            # "branch returned unknown node".
            # Prefer the ACTUAL registered node set captured by _build_graph, so
            # this safety net checks reality rather than a hand-maintained copy.
            # Otherwise a newly-added intent (YAML + node_method, auto-registered by
            # Phase 13B) would be silently rerouted to "response" whenever the two
            # drift — quietly breaking the documented "2 steps to add an intent".
            # The inline set is only a fallback for a router built without the graph.
            _fallback_registered = frozenset(
                {
                    "sparql",
                    "sql",
                    "analytics",
                    "visualization",
                    "planner",
                    "report",
                    "anomaly",
                    "export",
                    "floor_plan",
                    "spatial_query",
                    "control",
                    "maintenance",
                    "capability",
                    "response",
                    "general_knowledge",
                    # Phase 19 - unified report-intake category nodes.
                    "complaint",
                    "feedback",
                    "safety_report",
                    "suggestion",
                    # T21 — per-user alert management (create/list/delete).
                    "alert_mgmt",
                    # T22 — honest automation-capability answers.
                    "automation_capability_check",
                    # T35 — personalised comfort preference management.
                    "preference_management",
                    "locked_capability",
                }
            )
            _registered_nodes = getattr(self, "_registered_nodes", None) or _fallback_registered
            if target not in _registered_nodes:
                logger.info(
                    f"[route] intent '{intent}' has route_target='{target}' "
                    "which is not a registered workflow node — falling back to response"
                )
                # Surface a polite message via dialogue_response so the
                # response node has something to say.
                state.intermediate_results["dialogue_response"] = (
                    f"I understand you're asking about '{intent}', but that capability "
                    "is not yet wired up in this deployment.  Please rephrase your "
                    "question or contact the operator if you expect this feature."
                )
                route_decision["overrides_applied"].append("unregistered_node_safety_net")
                route_decision["decision_source"] = "fallback"
                route_decision["final_node"] = "response"
                state.intermediate_results["route_decision"] = route_decision
                return "response"
            route_decision["final_node"] = target
            state.intermediate_results["route_decision"] = route_decision
            return target

        # Last-resort: legacy pipeline stage names not in the registry.
        if intent in ("sparql", "metadata", "sensor_data"):
            route_decision["overrides_applied"].append("legacy_pipeline_alias")
            route_decision["final_node"] = "sparql"
            state.intermediate_results["route_decision"] = route_decision
            return "sparql"
        if intent == "sql":
            route_decision["overrides_applied"].append("legacy_pipeline_alias")
            route_decision["final_node"] = "sql"
            state.intermediate_results["route_decision"] = route_decision
            return "sql"

        logger.info(f"[route] no target for intent '{intent}' — falling through to response")
        route_decision["decision_source"] = "fallback"
        route_decision["final_node"] = "response"
        state.intermediate_results["route_decision"] = route_decision
        return "response"

    # ── Negation-aware visualization intent detection ─────────────────────────
    #
    # _VIZ_KEYWORDS  — any word/phrase that signals "I want a visual output"
    # _VIZ_NEGATIONS — any word/phrase that cancels a visualization request
    #
    # Rules:
    #   1. If ANY negation phrase appears → False (no chart), full stop.
    #   2. If ANY positive keyword appears (and no negation) → True.
    #   3. Otherwise → False.

    _VIZ_KEYWORDS = frozenset(
        [
            # --- direct chart/plot/graph requests ---
            "plot",
            "plots",
            "plotted",
            "plotting",
            "chart",
            "charts",
            "charted",
            "charting",
            "graph",
            "graphs",
            "graphed",
            "graphing",
            "diagram",
            "diagrams",
            "figure",
            "figures",
            "visualize",
            "visualise",
            "visualization",
            "visualisation",
            "visualizing",
            "visualising",
            "draw",
            "drawing",
            "render",
            "rendered",
            "display",
            "displays",
            # --- specific chart types ---
            "line chart",
            "line graph",
            "line plot",
            "bar chart",
            "bar graph",
            "bar plot",
            "histogram",
            "scatter plot",
            "scatter chart",
            "scatter graph",
            "pie chart",
            "pie graph",
            "area chart",
            "area graph",
            "heatmap",
            "heat map",
            "box plot",
            "boxplot",
            "violin plot",
            "time series",
            "time-series chart",
            "time series chart",
            "sparkline",
            "candlestick",
            "waterfall chart",
            "gantt chart",
            "bubble chart",
            "bubble plot",
            "radar chart",
            "spider chart",
            "map",
            "geo map",
            "choropleth",
            "dashboard",
            "panel",
            # --- "show me" intent with visual objects ---
            "show graph",
            "show chart",
            "show plot",
            "show figure",
            "show me the graph",
            "show me the chart",
            "show me the plot",
            "show me a graph",
            "show me a chart",
            "show me a plot",
            "show trend",
            "show the trend",
            "show trends",
            "show pattern",
            "show patterns",
            "show distribution",
            "show correlation",
            "show comparison",
            "show over time",
            "show visually",
            "show graphically",
            "show me visually",
            "show me graphically",
            "see the graph",
            "see the chart",
            "see the plot",
            "view the graph",
            "view the chart",
            # --- "create / generate / make / produce" intent ---
            "create chart",
            "create graph",
            "create plot",
            "create visualization",
            "generate chart",
            "generate graph",
            "generate plot",
            "generate visualization",
            "generate a chart",
            "generate a graph",
            "generate a plot",
            "make chart",
            "make graph",
            "make plot",
            "make a chart",
            "make me a chart",
            "make me a graph",
            "make me a plot",
            "produce chart",
            "produce graph",
            "produce visualization",
            "build chart",
            "build graph",
            "draw chart",
            "draw graph",
            "draw a chart",
            # --- image / picture requests ---
            "image",
            "picture",
            "visual",
            "visuals",
            "illustration",
            "screenshot",
            "snapshot",
            "thumbnail",
            # --- trend / pattern requests implying visual output ---
            "trend chart",
            "trend graph",
            "trend line",
            "trendline",
            "show the trend line",
            "show trendline",
            "plot the trend",
            "graph the trend",
            "chart the trend",
            # --- explicit output format ---
            "png",
            "svg",
            "jpeg",
            "pdf chart",
            "pdf graph",
            "export chart",
            "export graph",
            "export plot",
            "save chart",
            "save graph",
            "save plot",
            "embed chart",
            "embed graph",
            # --- implicit visual intent phrases ---
            "graphically",
            "visually",
            "in a chart",
            "in a graph",
            "as a chart",
            "as a graph",
            "as a plot",
            "as a figure",
            "into a chart",
            "into a graph",
            "overlay",
            "annotate on chart",
            "compare visually",
            "plot comparison",
        ]
    )

    _VIZ_NEGATIONS = (
        # --- direct negations ---
        "do not",
        "don't",
        "dont",
        "no need",
        "not needed",
        "don't need",
        "do not need",
        "i don't want",
        "i do not want",
        "no, don't",
        "please don't",
        "please do not",
        # --- "no <viz-word>" patterns ---
        "no chart",
        "no charts",
        "no graph",
        "no graphs",
        "no plot",
        "no plots",
        "no figure",
        "no figures",
        "no image",
        "no images",
        "no picture",
        "no pictures",
        "no visual",
        "no visuals",
        "no visualization",
        "no visualisation",
        "no diagram",
        "no diagrams",
        "no display",
        # --- "without <viz-word>" patterns ---
        "without chart",
        "without charts",
        "without graph",
        "without graphs",
        "without plot",
        "without plots",
        "without image",
        "without images",
        "without visual",
        "without visualization",
        "without visualisation",
        "without diagram",
        "without figure",
        # --- "skip/omit/exclude/hide/remove <viz-word>" ---
        "skip chart",
        "skip graph",
        "skip plot",
        "skip visual",
        "skip the chart",
        "skip the graph",
        "skip the plot",
        "omit chart",
        "omit graph",
        "omit plot",
        "omit visual",
        "omit the chart",
        "omit the graph",
        "omit the plot",
        "exclude chart",
        "exclude graph",
        "exclude plot",
        "hide chart",
        "hide graph",
        "hide plot",
        "remove chart",
        "remove graph",
        "remove plot",
        "suppress chart",
        "suppress graph",
        "suppress plot",
        "avoid chart",
        "avoid graph",
        "avoid plot",
        # --- "not a/the <viz-word>" ---
        "not a chart",
        "not a graph",
        "not a plot",
        "not a figure",
        "not the chart",
        "not the graph",
        "not the plot",
        # --- "text-only / numbers-only / stats-only" ---
        "just text",
        "text only",
        "text-only",
        "numbers only",
        "numbers-only",
        "just numbers",
        "stats only",
        "stats-only",
        "just stats",
        "data only",
        "data-only",
        "just data",
        "raw data only",
        "raw numbers only",
        "words only",
        "in words",
        "no visuals",
        "purely text",
        "plain text",
        "just the numbers",
        "just statistics",
        "just the stats",
        # --- "don't show" patterns ---
        "don't show a chart",
        "do not show a chart",
        "don't show a graph",
        "do not show a graph",
        "don't show a plot",
        "do not show a plot",
        "don't show the chart",
        "do not show the chart",
        "don't display",
        "do not display",
        # --- informal negations ---
        "no viz",
        "no charts please",
        "no graphs please",
        "no plots please",
        "charts not needed",
        "graph not needed",
        "plot not needed",
        "chart not required",
        "graph not required",
        "chart not necessary",
        "visualization not needed",
        "i don't need a chart",
        "i don't need a graph",
        "i do not need a chart",
        "i do not need a graph",
        "no need for a chart",
        "no need for a graph",
        "no need for a plot",
        "no need for visualization",
    )

    @classmethod
    def _user_wants_visualization(cls, message: str) -> bool:
        """
        Return True only when the user explicitly asks for a chart/plot/graph
        AND has NOT negated that request in the same message.

        Decision logic (in order):
          1. Scan for any negation phrase → return False immediately.
          2. Scan for any positive keyword  → return True.
          3. Default                        → False (no implicit chart).

        Examples
        --------
          "show me a chart"                    → True
          "do not give me a chart"             → False
          "compute avg, no chart"              → False
          "plot the trend"                     → True
          "show the trend"                     → True   (trend + show)
          "show me the numbers"                → False  (no viz keyword)
          "generate a line graph"              → True
          "just give me the stats, skip graph" → False
          "visualize zone temperatures"        → True
          "as a bar chart please"              → True
          "numbers only, no viz"               → False
          "i don't need a chart here"          → False
        """
        msg = message.lower()
        for neg in cls._VIZ_NEGATIONS:
            if neg in msg:
                return False
        return any(kw in msg for kw in cls._VIZ_KEYWORDS)

    # Phase 17B (2026-05-29) — `_route_from_data_node`, `_route_from_analytics_node`,
    # `_route_from_sql`, and `_route_from_report` were extracted to
    # `workflow/_routing.py`'s `WorkflowRoutingMixin`.  See the inheritance line above.

    @staticmethod
    def _wants_document(state: ConversationState) -> bool:
        """Detect if the user requested a formal document (PDF/DOCX/HTML).

        Phase 7B — typed read of `pipeline_ctx.export_format`.
        """
        fmt = (state.pipeline_ctx.export_format or "").lower().strip()
        if fmt in ("pdf", "docx", "html"):
            return True
        msg = (state.messages[-1].content if state.messages else "").lower()
        keywords = [
            "pdf",
            "docx",
            "word document",
            "download report",
            "report file",
            "formal report",
            "document",
        ]
        return any(k in msg for k in keywords)

    # ------------------------------------------------------------------
    # Phase 4 Node Implementations
    # ------------------------------------------------------------------

    async def _planner_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.4 — Multi-step planner for complex queries."""
        logger.info("Executing Phase 4 Planner Node")
        latest_message = state.messages[-1].content if state.messages else ""
        result = await self.planner_agent.plan_and_execute(state, latest_message)
        state.intermediate_results["planner_result"] = result
        return state

    async def _report_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.2 — Report generation node."""
        logger.info("Executing Phase 4 Report Node")
        latest_message = state.messages[-1].content if state.messages else ""
        sql_result = state.intermediate_results.get("sql_result")
        sparql_result = state.intermediate_results.get("sparql_result")
        export_fmt = state.intermediate_results.get("export_format")
        result = await self.report_agent.generate(
            state,
            latest_message,
            sensor_data=sql_result,
            metadata=sparql_result,
            export_format=export_fmt,
        )
        state.intermediate_results["report_result"] = result
        return state

    async def _anomaly_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.7 — Anomaly detection node."""
        logger.info("Executing Phase 4 Anomaly Detection Node")
        latest_message = state.messages[-1].content if state.messages else ""
        sql_result = state.intermediate_results.get("sql_result")
        result = await self.anomaly_agent.detect(state, latest_message, sensor_data=sql_result)
        state.intermediate_results["anomaly_result"] = result
        return state

    async def _export_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.3 — Data export node."""
        logger.info("Executing Phase 4 Export Node")
        fmt = state.intermediate_results.get("export_format") or "csv"
        latest_message = state.messages[-1].content if state.messages else "export"

        # If SPARQL hasn't run yet (export intent bypasses sparql node), run it now
        if not state.intermediate_results.get("sparql_result"):
            logger.info("Export: running SPARQL agent to get sensor UUIDs")
            sparql_result = await self.sparql_agent.generate_query(state, latest_message)
            state.intermediate_results["sparql_result"] = sparql_result
            state.query_results = sparql_result.get("results", {})

        # If SQL hasn't run yet, run the SQL agent to get time-series data
        if not state.intermediate_results.get("sql_result"):
            logger.info("Export: running SQL agent to fetch sensor data")
            # Enable UUID-based fetching for export
            state.analytics_required = True
            state = await self._sql_node(state)

        sql_result = state.intermediate_results.get("sql_result") or {}
        # Extract raw rows list from sql_result (result.results.data)
        rows = (
            sql_result.get("results", {}).get("data", [])
            or sql_result.get("data")
            or sql_result.get("rows")
            or []
        )
        if not rows and isinstance(sql_result, list):
            rows = sql_result

        result = await self.export_agent.export(
            data=rows, label="sensor_export", fmt=fmt, title=latest_message[:80]
        )
        state.intermediate_results["export_result"] = result
        return state

    # ──────────────────────────────────────────────────────────────────────────
    # Helper functions for sensor disambiguation and units
    # ──────────────────────────────────────────────────────────────────────────

    def _infer_query_kind(self, text: str) -> Optional[str]:
        if not text:
            return None
        t = text.lower()
        if "temperature" in t or "temp" in t:
            return "temperature"
        if "humidity" in t:
            return "humidity"
        if "co2" in t or "carbon dioxide" in t:
            return "co2"
        if "air quality" in t or "iaq" in t:
            return "air_quality"
        if "occupancy" in t or "occupant" in t:
            return "occupancy"
        if "energy" in t or "electric" in t or "power" in t or "kwh" in t or "kw" in t:
            return "energy"
        if "pressure" in t:
            return "pressure"
        if "flow" in t:
            return "flow"
        return None

    def _infer_sensor_kind(self, label: Optional[str], sensor_uri: Optional[str]) -> Optional[str]:
        text = f"{label or ''} {sensor_uri or ''}".lower()
        if "temperature" in text or "temp" in text:
            return "temperature"
        if "humidity" in text:
            return "humidity"
        if "co2" in text or "carbon dioxide" in text:
            return "co2"
        if "air quality" in text or "iaq" in text:
            return "air_quality"
        if "occupancy" in text or "occupant" in text:
            return "occupancy"
        if (
            "energy" in text
            or "electric" in text
            or "power" in text
            or "kwh" in text
            or "kw" in text
        ):
            return "energy"
        if "pressure" in text:
            return "pressure"
        if "flow" in text:
            return "flow"
        return None

    def _unit_for_kind(self, kind: Optional[str]) -> str:
        if kind == "temperature":
            return "°C"
        if kind == "humidity":
            return "%"
        if kind == "co2":
            return "ppm"
        if kind == "air_quality":
            return "level"
        if kind == "occupancy":
            return "count"
        if kind == "energy":
            return "kWh"
        if kind == "pressure":
            return "Pa"
        if kind == "flow":
            return "m³/s"
        return ""

    def _build_sensor_metadata_from_bindings(self, bindings: list) -> Dict[str, Dict[str, str]]:
        sensor_metadata: Dict[str, Dict[str, str]] = {}
        for binding in bindings:
            uuid_val = None
            label_val = None
            sensor_val = None
            unit_val = None

            for var in binding:
                if "uuid" in var.lower() or "id" in var.lower() or "timeseries" in var.lower():
                    uuid_val = binding[var]["value"]
                elif "label" in var.lower():
                    label_val = binding[var]["value"]
                elif "sensor" in var.lower():
                    sensor_val = binding[var]["value"]
                elif "unit" in var.lower():
                    unit_val = binding[var]["value"]

            if uuid_val:
                if not label_val and sensor_val:
                    sensor_name = (
                        sensor_val.split("#")[-1]
                        if "#" in sensor_val
                        else sensor_val.split("/")[-1]
                    )
                    label_val = sensor_name.replace("_", " ")

                kind = self._infer_sensor_kind(label_val, sensor_val)
                unit = unit_val or self._unit_for_kind(kind)
                sensor_metadata[uuid_val] = {
                    "label": label_val or "Unknown Sensor",
                    "sensor_uri": sensor_val or "Unknown",
                    "uuid": uuid_val,
                    "kind": kind or "",
                    "unit": unit or "",
                }

        return sensor_metadata

    async def _floor_plan_node(self, state: ConversationState) -> ConversationState:
        """
        Floor Plan node — thin wrapper around FloorPlanAgent.resolve().

        Delegates all resolution logic to the agent (which uses manifests
        when available, falling back to legacy PDF-text extraction).

        State keys written:
          intermediate_results["floor_plan_result"]   — markdown for response node
          intermediate_results["floor_plan_structured"] — FloorPlanResult dict
          intermediate_results["floor_context_hint"]  — spatial hint for SPARQL agent
          state.floor_context                         — persisted across turns
        """
        from orchestrator.agents.floor_plan_agent import get_floor_plan_agent

        logger.info("[floor_plan] Executing Floor Plan Node (manifest-aware)")
        user_query = state.user_message or (state.messages[-1].content if state.messages else "")

        try:
            agent = get_floor_plan_agent()
            result = await agent.resolve(user_query, state)

            # Persist floor context for subsequent turns
            if result.floor is not None:
                state.floor_context = {
                    "building_id": result.building_id,
                    "floor": result.floor,
                    "zone": result.selected_space.zone_id if result.selected_space else None,
                    "pdf_url": result.pdf_url or "",
                    "image_url": result.image_url or "",
                }

            # Store structured result for response node and potential SPARQL pass-through
            state.intermediate_results["floor_plan_result"] = result.markdown
            state.intermediate_results["floor_plan_structured"] = result.model_dump(
                exclude_none=True
            )

            # Bridge selected space into SPARQL/SQL pipeline
            if result.selected_space:
                space = result.selected_space
                _user_ctx = state.intermediate_results.get("user_context", {})
                _user_ctx["resolved_floor"] = result.floor
                _user_ctx["resolved_zone"] = space.zone_id
                state.intermediate_results["user_context"] = _user_ctx
                building_name = result.building_id.replace("_", " ").title()
                state.intermediate_results["floor_context_hint"] = (
                    f"Spatial context: the user is asking about "
                    f"{space.label} (zone {space.zone_id}) "
                    f"on {state.floor_context.get('floor', result.floor)} "
                    f"of the {building_name} building. "
                    f"Constrain SPARQL/SQL queries to this zone."
                )
                if space.ontology_iri:
                    state.intermediate_results[
                        "floor_context_hint"
                    ] += f" Ontology IRI: {space.ontology_iri}"
                logger.info(
                    f"[floor_plan] Resolved: floor={result.floor}, "
                    f"zone={space.zone_id}, type={space.type}"
                )
            elif not result.candidates:
                # No space, no candidates → needs clarification
                state.needs_clarification = True
                state.clarification_question = result.markdown
                state.intermediate_results["pending_clarification_type"] = "floor"
            else:
                # Has candidates → waiting for user to pick
                state.needs_clarification = True
                state.clarification_question = result.markdown
                state.intermediate_results["pending_clarification_type"] = "zone"
                logger.info(
                    f"[floor_plan] Disambiguation: floor={result.floor}, "
                    f"candidates={len(result.candidates)}"
                )

        except Exception as e:
            logger.error(f"[floor_plan] Unexpected error: {e}", exc_info=True)
            state.intermediate_results["error"] = f"floor_plan: {str(e)}"
            state.intermediate_results["floor_plan_result"] = (
                "I encountered an error loading the floor plan. Please try again."
            )

        return state

    async def _spatial_query_node(self, state: ConversationState) -> ConversationState:
        """DW4 — Answer quantitative geometry questions from DWG manifest data."""
        user_query = state.messages[-1].content if state.messages else state.user_message
        # Phase 4 — alias-aware: floor_context > state.building_id > settings.
        # The BuildingRegistry alias map resolves legacy slugs to the logical ID.
        building_id = (
            (state.floor_context or {}).get("building_id")
            or state.building_id
            or settings.BUILDING_ID
        )
        floor = state.floor_context.get("floor") if state.floor_context else None

        logger.info(
            f"[spatial_query] intent={state.current_intent}, "
            f"building={building_id}, floor={floor}"
        )

        try:
            from orchestrator.agents.spatial_agent import get_spatial_agent

            agent = get_spatial_agent()
            markdown = await agent.resolve(user_query, building_id, floor)
            state.intermediate_results["floor_plan_result"] = markdown
        except Exception as e:
            logger.error(f"[spatial_query] Unexpected error: {e}", exc_info=True)
            state.intermediate_results["error"] = f"spatial_query: {str(e)}"
            state.intermediate_results["floor_plan_result"] = (
                "I encountered an error analysing the spatial data. Please try again."
            )

        return state

    async def _control_node(self, state: ConversationState) -> ConversationState:
        """Execute RBAC-gated device control command."""
        logger.info(f"[control_node] intent={state.intermediate_results.get('intent')}")
        try:
            result = await self.control_agent.execute_command(state)
            state.intermediate_results["control_result"] = result
            if self.postgres_manager and result.get("log_entry"):
                await self._persist_control_log(result["log_entry"])
        except Exception as e:
            logger.error(f"[control_node] Error: {e}", exc_info=True)
            state.intermediate_results["error"] = f"control: {e}"
        return state

    async def _persist_control_log(self, log_entry: Dict[str, Any]) -> None:
        """Write control command to control_log table."""
        try:
            async with self.postgres_manager.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO control_log
                        (building_id, device, action, target_value, status, user_id, role, session_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    log_entry.get("building_id"),
                    log_entry.get("device"),
                    log_entry.get("action"),
                    log_entry.get("target_value"),
                    log_entry.get("status"),
                    log_entry.get("user_id"),
                    log_entry.get("user_role"),
                    log_entry.get("session_id"),
                )
        except Exception as e:
            logger.warning(f"[control_node] Failed to persist log: {e}")

    async def _report_intake_node(self, state: ConversationState) -> ConversationState:
        """Phase 19 - unified user-report intake.

        Handles maintenance / complaint / feedback / safety / suggestion in one
        node.  The report CATEGORY comes from the classified intent; the ACTION
        (create / status / list) comes from the message text.  Every report is
        persisted to the `user_reports` Postgres table with the reporter's
        blended persona, and the user always gets an honest acknowledgment with
        a tracking ID (never a silent drop).
        """
        intent = state.current_intent or "maintenance"
        user_message = state.messages[-1].content if state.messages else state.user_message
        logger.info(f"[report_intake] intent={intent}")
        try:
            from orchestrator.services.report_intake_service import (
                get_report_intake_service,
            )

            service = get_report_intake_service(self.postgres_manager)
            category = service.category_for_intent(intent)
            action = service.classify_action(user_message or "")
            reporter_id = (
                getattr(state, "user_id", None)
                or state.intermediate_results.get("user_id")
                or "anonymous"
            )
            building_id = getattr(state, "building_id", None) or settings.BUILDING_ID
            personas_list = list(getattr(state, "personas", []) or [])
            persona_label = (
                "+".join(personas_list[:3])
                if personas_list
                else (getattr(state, "persona", "general") or "general")
            )

            if action == "status":
                rid = service.extract_report_id(user_message or "")
                if not rid:
                    msg = (
                        "Please include the report ID (format **REP-XXXXXX**) so "
                        "I can look it up."
                    )
                else:
                    res = await service.get_report_status(rid, reporter_id=reporter_id)
                    msg = res.get("message", "I couldn't retrieve that report.")
            elif action == "list":
                res = await service.list_user_reports(reporter_id)
                msg = res.get("message", "I couldn't list your reports.")
            else:  # create
                entities = state.intermediate_results.get("entities", []) or []
                location = next(
                    (
                        e.get("value")
                        for e in entities
                        if isinstance(e, dict) and e.get("type") == "location"
                    ),
                    None,
                )
                device = next(
                    (
                        e.get("value")
                        for e in entities
                        if isinstance(e, dict) and e.get("type") in ("device", "equipment")
                    ),
                    None,
                )
                res = await service.create_report(
                    description=user_message or "(no description provided)",
                    building_id=building_id,
                    category=category,
                    reporter_id=reporter_id,
                    persona=persona_label,
                    location=location,
                    device=device,
                    session_id=state.conversation_id,
                )
                msg = res.get("message", "Your report has been received.")

            state.intermediate_results["report_intake_result"] = {
                "category": category,
                "action": action,
                "persona": persona_label,
            }
            state.intermediate_results["dialogue_response"] = msg
        except Exception as e:
            logger.error(f"[report_intake] Error: {e}", exc_info=True)
            state.intermediate_results["error"] = f"report_intake: {e}"
            state.intermediate_results["dialogue_response"] = (
                "I wasn't able to log your report just now. Please try again, or "
                "contact facilities directly if it's urgent."
            )
        return state

    async def _maintenance_node(self, state: ConversationState) -> ConversationState:
        """Backward-compat alias - Phase 19 routes maintenance through the
        unified report intake.  Retained so any external reference to the old
        node name keeps working."""
        return await self._report_intake_node(state)

    async def _execute_maintenance_db(
        self, result: Dict[str, Any], state: ConversationState
    ) -> None:
        """Persist maintenance ticket operation to PostgreSQL."""
        op = result.get("operation")
        try:
            async with self.postgres_manager.pool.acquire() as conn:
                if op == "CREATE":
                    counter = await conn.fetchval(
                        "SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 4) AS INTEGER)), 0) + 1 "
                        "FROM maintenance_tickets WHERE building_id = $1",
                        result.get("building_id"),
                    )
                    ticket_id = self.maintenance_agent._generate_ticket_id(counter)
                    await conn.execute(
                        """
                        INSERT INTO maintenance_tickets
                            (id, building_id, location, description, status, reporter_id, session_id)
                        VALUES ($1,$2,$3,$4,'OPEN',$5,$6)
                        """,
                        ticket_id,
                        result.get("building_id"),
                        result.get("location"),
                        result.get("description"),
                        result.get("reporter_id"),
                        result.get("session_id"),
                    )
                    result["ticket_id"] = ticket_id
                    result["message"] = (
                        f"🔧 Maintenance ticket created: {ticket_id}\n"
                        f"Location: {result.get('location')}\n"
                        f"Issue: {result.get('description')}\n"
                        f"Status: OPEN\n\n"
                        f'Use "Check ticket {ticket_id}" to follow up.'
                    )
                elif op == "STATUS":
                    row = await conn.fetchrow(
                        "SELECT * FROM maintenance_tickets WHERE id = $1",
                        result.get("ticket_id"),
                    )
                    if row:
                        result["message"] = (
                            f"📋 Ticket {row['id']}\n"
                            f"Location: {row['location']}\n"
                            f"Status: {row['status']}\n"
                            f"Assignee: {row['assignee'] or 'unassigned'}\n"
                            f"Last updated: {row['updated_at']}"
                        )
                    else:
                        result["message"] = f"Ticket {result.get('ticket_id')} not found."
                elif op == "LIST":
                    rows = await conn.fetch(
                        "SELECT id, location, description, status FROM maintenance_tickets "
                        "WHERE building_id = $1 AND status = $2 LIMIT 10",
                        result.get("building_id"),
                        result.get("filter", "OPEN"),
                    )
                    if rows:
                        lines = [f"📋 Open tickets ({len(rows)}):"]
                        for r in rows:
                            lines.append(f"• {r['id']}: {r['location']} — {r['description'][:60]}")
                        result["message"] = "\n".join(lines)
                    else:
                        result["message"] = "No open tickets found."
                elif op == "ASSIGN":
                    await conn.execute(
                        "UPDATE maintenance_tickets SET assignee=$1, status='ASSIGNED', "
                        "updated_at=NOW() WHERE id=$2",
                        result.get("assignee"),
                        result.get("ticket_id"),
                    )
                    result["message"] = (
                        f"✅ Ticket {result.get('ticket_id')} assigned to {result.get('assignee')}."
                    )
                elif op in ("RESOLVE", "CLOSE"):
                    new_status = "RESOLVED" if op == "RESOLVE" else "CLOSED"
                    await conn.execute(
                        "UPDATE maintenance_tickets SET status=$1, updated_at=NOW() WHERE id=$2",
                        new_status,
                        result.get("ticket_id"),
                    )
                    result["message"] = (
                        f"✅ Ticket {result.get('ticket_id')} marked as {new_status}."
                    )
        except Exception as e:
            logger.warning(f"[maintenance_node] DB operation failed: {e}")
            if "message" not in result:
                result["message"] = f"Operation completed but could not update database: {e}"

    async def _capability_node(self, state: ConversationState) -> ConversationState:
        """Answer CAPABILITY / off-ontology queries from the building's own data.

        TTL-first single chain (TODO-012): the CapabilityAgent resolves metrics →
        ontology triples (ontosage:Amenity / KnowledgeTopic) → uploaded documents →
        honest "no info". There is no capability.yaml / Qdrant capability-KB fallback.
        """
        logger.info(
            f"[capability_node] intent={state.current_intent}, " f"building={state.building_id}"
        )
        state = await self.capability_agent.answer(state)
        # Surface the response into the standard dialogue_response slot so the
        # response node picks it up consistently; record the ACTUAL source.
        result = state.intermediate_results.get("capability_result", {})
        if result.get("response"):
            state.intermediate_results["dialogue_response"] = result["response"]
            _prov.record(state, result.get("provenance") or "capability")
        return state

    async def _document_node(self, state: ConversationState) -> ConversationState:
        """CAP-01 — Generate a formal document from current pipeline outputs."""
        logger.info("Executing Document Node")

        report_type = (state.intermediate_results.get("report_type") or "summary").lower()
        doc_type_map = {
            "summary": "summary",
            "anomaly": "anomaly_digest",
            "comparison": "comparison",
            "trend": "trend",
            "full": "full",
        }
        document_type = state.intermediate_results.get("document_type") or doc_type_map.get(
            report_type, "summary"
        )
        if state.current_intent == "compliance":
            document_type = "compliance_report"

        fmt = (state.intermediate_results.get("export_format") or "pdf").lower().strip()
        if fmt not in ("pdf", "docx", "html"):
            fmt = "pdf"

        result = await self.document_agent.generate(
            state,
            document_type=document_type,
            output_format=fmt,
        )
        state.intermediate_results["document_result"] = result
        return state

    async def _alert_mgmt_node(self, state: ConversationState) -> ConversationState:
        """T21 — Create / list / delete per-user threshold alert rules conversationally."""
        import re

        logger.info(f"[alert_mgmt] intent={state.current_intent}")

        # RBAC: guest users cannot manage alert rules
        user_role = state.intermediate_results.get("user_role", "guest")
        user_id = state.intermediate_results.get("user_id", "")
        if not user_id or user_role in ("guest", "anonymous"):
            state.intermediate_results["dialogue_response"] = (
                "Alert management requires you to be logged in. "
                "Please authenticate to create or manage personal alerts."
            )
            return state

        building_id = state.building_id or "bldg1"
        query = (state.messages[-1].content if state.messages else "").lower()

        # Detect subcommand
        if re.search(r"\b(list|show|view|what alerts|my alerts)\b", query):
            subcommand = "list"
        elif re.search(r"\b(delete|remove|cancel|stop|disable)\b", query):
            subcommand = "delete"
        else:
            subcommand = "create"

        try:
            from orchestrator.services.user_alert_store import get_user_alert_store

            store = get_user_alert_store()

            if subcommand == "list":
                rules = await store.list_alerts(user_id, building_id)
                if not rules:
                    response = "You have no active alert rules. Say 'alert me when CO2 exceeds 1000 ppm' to create one."
                else:
                    lines = [f"Your active alerts ({len(rules)}):"]
                    for i, r in enumerate(rules, 1):
                        t = r.get("trigger", {})
                        concept = t.get("concept") or "sensor"
                        op = t.get("op", ">")
                        thresh = t.get("threshold", 0)
                        # The auto-generated name already embeds "{concept} {op}
                        # {threshold}" — don't append the condition twice.
                        label = r.get("name") or f"{concept} {op} {thresh}"
                        lines.append(
                            f"  {i}. [{r.get('id')}] {label} "
                            f"— {r.get('action', {}).get('severity', 'warning')}"
                        )
                    response = "\n".join(lines)

            elif subcommand == "delete":
                # Try to find a rule_id in the message (8-char hex)
                id_match = re.search(r"\b([0-9a-f]{8})\b", query)
                if id_match:
                    rule_id = id_match.group(1)
                    ok = await store.delete_alert(user_id, building_id, rule_id)
                    response = (
                        f"Alert {rule_id} deleted."
                        if ok
                        else f"Could not find alert {rule_id} — check 'list my alerts'."
                    )
                else:
                    response = (
                        "Please include the alert ID to delete it "
                        "(e.g. 'delete alert abc12345'). "
                        "Use 'list my alerts' to see your alert IDs."
                    )

            else:  # create
                # Extract trigger parameters from entities + message
                entities = state.intermediate_results.get("entities") or []
                concepts = state.intermediate_results.get("concepts") or []

                # Threshold extraction (e.g. "exceeds 1000", "above 28", "below 30%")
                thresh_match = re.search(
                    r"\b(above|below|exceeds?|greater than|less than|drops? below|over|under)\s+([\d.]+)",
                    query,
                )
                threshold = float(thresh_match.group(2)) if thresh_match else 0.0
                op_word = thresh_match.group(1) if thresh_match else "above"
                op = "<" if any(w in op_word for w in ("below", "less", "drops", "under")) else ">"

                # Duration (e.g. "for 10 minutes")
                dur_match = re.search(r"for (\d+)\s*min", query)
                duration_min = int(dur_match.group(1)) if dur_match else 0

                # Concept / sensor class from HBCO resolution
                concept_id = None
                brick_class = None
                if concepts:
                    cm = concepts[0]
                    concept_id = cm.get("concept_id")
                    bc = cm.get("brick_classes") or []
                    brick_class = bc[0] if bc else None

                trigger: dict = {
                    "op": op,
                    "threshold": threshold,
                    "duration_min": duration_min,
                }
                if concept_id:
                    trigger["concept"] = concept_id
                else:
                    # Fallback: try to infer from keyword
                    if "co2" in query or "carbon" in query:
                        trigger["concept"] = "stuffy"
                    elif "temp" in query or "warm" in query or "hot" in query:
                        trigger["concept"] = "warmth"
                    elif "humid" in query or "damp" in query:
                        trigger["concept"] = "dampness"
                    else:
                        trigger["concept"] = "sensor"

                action = {
                    "type": "notify",
                    "message": f"Alert condition triggered: {trigger.get('concept')} {op} {threshold}",
                    "severity": "warning",
                }

                rule_id = await store.create_alert(user_id, building_id, trigger, action)
                response = (
                    f"Alert created (ID: **{rule_id}**). "
                    f"I'll notify you when {trigger.get('concept')} {op} {threshold}"
                    + (f" for {duration_min} minutes" if duration_min else "")
                    + f". Use 'list my alerts' to manage your alerts."
                )

        except Exception as e:
            logger.error(f"[alert_mgmt] error: {e}", exc_info=True)
            response = "I couldn't manage your alert right now. Please try again."

        state.intermediate_results["dialogue_response"] = response
        return state

    async def _preference_management_node(self, state: ConversationState) -> ConversationState:
        """T35 — Store, list, or delete per-user comfort preferences conversationally."""
        import re as _re_pref

        logger.info(f"[preference_mgmt] intent={state.intermediate_results.get('intent')}")

        user_role = state.intermediate_results.get("user_role", "guest")
        user_id = state.intermediate_results.get("user_id", "")

        if not user_id or user_role in ("guest", "anonymous"):
            state.intermediate_results["dialogue_response"] = (
                "Personalised preferences require you to be logged in. "
                "Please sign in to save your comfort preferences."
            )
            return state

        from orchestrator.services.user_preference_store import (
            CATEGORY_KEYWORDS,
            get_user_preference_store,
        )

        store = get_user_preference_store()
        query = (state.messages[-1].content if state.messages else "").lower()

        # ── Subcommand detection ──────────────────────────────────────────
        _FORGET_RE = _re_pref.compile(
            r"\b(forget|clear|reset|delete|remove) (my|all|the)? ?"
            r"(preference|setting|temperature|humidity|noise|light|comfort|personalisation)s?\b"
        )
        _LIST_RE = _re_pref.compile(
            r"\b(what are|show|list|display) (my|all)? ?(preference|setting|personalisation)s?\b"
        )

        try:
            if _FORGET_RE.search(query):
                # Identify category if specified, else delete all
                category = None
                for kw, cat in CATEGORY_KEYWORDS.items():
                    if kw in query:
                        category = cat
                        break
                if category:
                    deleted = await store.delete_preference(user_id, category)
                    response = (
                        f"Done — I've forgotten your {category.replace('_', ' ')} preference."
                        if deleted
                        else f"You didn't have a {category.replace('_', ' ')} preference saved."
                    )
                else:
                    count = await store.delete_all_preferences(user_id)
                    response = (
                        f"Done — I've cleared all {count} of your saved preferences."
                        if count
                        else "You don't have any saved preferences yet."
                    )

            elif _LIST_RE.search(query):
                prefs = await store.list_preferences(user_id)
                if not prefs:
                    response = (
                        "You don't have any saved preferences yet. "
                        "Try: 'Remember I prefer temperatures between 22 and 24°C.'"
                    )
                else:
                    lines = ["**Your saved comfort preferences:**"]
                    for p in prefs:
                        rng = ""
                        if p.get("pref_min") is not None and p.get("pref_max") is not None:
                            rng = f"{p['pref_min']}–{p['pref_max']} {p.get('unit', '')}"
                        elif p.get("pref_min") is not None:
                            rng = f"≥{p['pref_min']} {p.get('unit', '')}"
                        elif p.get("pref_max") is not None:
                            rng = f"≤{p['pref_max']} {p.get('unit', '')}"
                        lines.append(f"- {p.get('label', p['category'])}: **{rng}**")
                    response = "\n".join(lines)

            else:
                # Store preference — extract category + numeric range from query
                category = None
                for kw, cat in CATEGORY_KEYWORDS.items():
                    if kw in query:
                        category = cat
                        break
                if not category:
                    category = "temperature_comfort"  # sensible default

                # Extract numeric range (e.g. "22 and 24", "22-24", "around 23")
                _NUM_RANGE_RE = _re_pref.compile(
                    r"\b(\d{1,3}(?:\.\d)?)\s*(?:and|to|-|–)\s*(\d{1,3}(?:\.\d)?)\b"
                )
                _NUM_SINGLE_RE = _re_pref.compile(r"\baround\s+(\d{1,3}(?:\.\d)?)\b")
                pref_min: Optional[float] = None
                pref_max: Optional[float] = None
                m_range = _NUM_RANGE_RE.search(query)
                m_single = _NUM_SINGLE_RE.search(query)
                if m_range:
                    pref_min = float(m_range.group(1))
                    pref_max = float(m_range.group(2))
                elif m_single:
                    v = float(m_single.group(1))
                    pref_min = v - 1
                    pref_max = v + 1

                # Directional adjustments ("warmer", "cooler")
                if not m_range and not m_single:
                    if any(w in query for w in ("warmer", "hotter")):
                        pref_min = 23.0
                        pref_max = 26.0
                    elif any(w in query for w in ("cooler", "colder")):
                        pref_min = 19.0
                        pref_max = 22.0
                    elif "quieter" in query:
                        category = "noise_comfort"
                        pref_max = 45.0
                    elif "brighter" in query:
                        category = "illuminance_comfort"
                        pref_min = 400.0
                    elif "darker" in query:
                        category = "illuminance_comfort"
                        pref_max = 300.0

                success = await store.set_preference(
                    user_id, category, pref_min=pref_min, pref_max=pref_max, raw=query
                )
                if success:
                    from orchestrator.services.user_preference_store import (
                        _CATEGORY_META,
                    )

                    meta = _CATEGORY_META.get(category, {"label": category, "unit": ""})
                    rng_str = ""
                    if pref_min is not None and pref_max is not None:
                        rng_str = f"{pref_min}–{pref_max} {meta['unit']}"
                    elif pref_min is not None:
                        rng_str = f"≥{pref_min} {meta['unit']}"
                    elif pref_max is not None:
                        rng_str = f"≤{pref_max} {meta['unit']}"
                    else:
                        rng_str = "(direction noted)"
                    response = (
                        f"Saved! I'll use **{rng_str}** as your personal "
                        f"{meta['label'].lower()} preference. "
                        "This will override the standard guideline range whenever I assess "
                        "comfort for you specifically."
                    )
                else:
                    response = "I couldn't save your preference right now. Please try again."

        except Exception as exc:
            logger.error(f"[preference_mgmt] error: {exc}", exc_info=True)
            response = "I couldn't manage your preferences right now. Please try again."

        state.intermediate_results["dialogue_response"] = response
        return state

    async def _automation_capability_check_node(
        self, state: ConversationState
    ) -> ConversationState:
        """T22 — Honest automation-capability answers (Archetype-B from master-table analysis).

        For 'can the building automatically X when Y?' questions, answer truthfully from
        system state: (a) does a sensor point exist for X, (b) is notify-able via rules engine,
        (c) physical actuation requires a BMS driver (per the active building's actuation config).
        """
        import re as _re_ac

        logger.info(f"[automation_capability] intent={state.intermediate_results.get('intent')}")

        query_text = (state.messages[-1].content if state.messages else "").lower()
        entities = state.intermediate_results.get("entities", [])
        concepts = state.intermediate_results.get("concepts", [])
        building_id = state.intermediate_results.get("building_id") or settings.BUILDING_ID

        # ── Identify what the user wants to monitor ──────────────────────
        # Try concept resolver results first (HBCO lay-term → Brick class)
        concept_label = None
        brick_class = None
        recipe_id = None
        if concepts and isinstance(concepts[0], dict):
            first = concepts[0]
            concept_label = first.get("concept_id", "").replace("_", " ")
            classes = first.get("brick_classes", [])
            brick_class = classes[0] if classes else None
            recipe_id = first.get("recipe_id")

        # Fallback: extract noun from entities or keyword scan. The LLM emits
        # entities as plain STRINGS ('Outdoor_Air_Intake'); only dict-shaped
        # entities carry a type — strings fall through to the keyword scan.
        if not concept_label:
            for e in entities:
                if isinstance(e, dict) and e.get("type") in (
                    "sensor_type",
                    "metric",
                    "concept",
                    "parameter",
                ):
                    concept_label = str(e.get("value", "")).lower()
                    break

        if not concept_label:
            _KW_MAP = {
                "co2": ("CO2 / air quality", "brick:CO2_Level_Sensor"),
                "carbon dioxide": ("CO2 / air quality", "brick:CO2_Level_Sensor"),
                "air quality": ("CO2 / air quality", "brick:CO2_Level_Sensor"),
                "temperature": ("temperature", "brick:Temperature_Sensor"),
                "warm": ("temperature", "brick:Temperature_Sensor"),
                "hot": ("temperature", "brick:Temperature_Sensor"),
                "humid": ("humidity", "brick:Relative_Humidity_Sensor"),
                "humidity": ("humidity", "brick:Relative_Humidity_Sensor"),
                "energy": ("energy use", "brick:Electrical_Energy_Sensor"),
                "electricity": ("energy use", "brick:Electrical_Energy_Sensor"),
                "occupancy": ("occupancy / busyness", "brick:Occupancy_Sensor"),
                "busy": ("occupancy / busyness", "brick:Occupancy_Sensor"),
                "leak": ("water / leak", "brick:Water_Flow_Sensor"),
                "water": ("water / leak", "brick:Water_Flow_Sensor"),
                "noise": ("noise level", "brick:Noise_Level_Sensor"),
                "fault": ("equipment faults", None),
            }
            for kw, (label, cls) in _KW_MAP.items():
                if kw in query_text:
                    concept_label = label
                    brick_class = cls
                    break

        if not concept_label:
            concept_label = "the condition you mentioned"

        # ── Determine monitoring capability ──────────────────────────────
        # (a) Sensor point: available if brick_class maps to a known sensor type in this building.
        _KNOWN_SENSOR_CLASSES = {
            "brick:CO2_Level_Sensor",
            "brick:Temperature_Sensor",
            "brick:Relative_Humidity_Sensor",
            "brick:Electrical_Energy_Sensor",
            "brick:Occupancy_Sensor",
            "brick:Outside_Air_Temperature_Sensor",
        }
        sensor_available = brick_class is not None and brick_class in _KNOWN_SENSOR_CLASSES

        # (b) Notify: rules engine is always running (T20); user can create personal alert rules
        # (T21) for any sensor that has a UUID in the building.
        notify_available = True  # T20 rules engine is always active when orchestrator is up

        # (c) Physical actuation: Phase G actuation driver not yet configured for this building.
        # Building.yaml actuation block would need driver: bms|bacnet; currently only sim/none.
        actuation_available = False

        # ── Build the honest capability answer ───────────────────────────
        monitoring_str = (
            f"**{concept_label}**"
            if concept_label != "the condition you mentioned"
            else concept_label
        )

        if sensor_available and notify_available:
            answer_parts = [
                f"Yes — I can already watch {monitoring_str} and send you a personalised alert "
                f"when it crosses a threshold you choose.",
                "",
                "**What I can do right now:**",
                f"- Monitor {monitoring_str} continuously (sensors are live and streaming)",
                "- Trigger a notification rule when a threshold is breached — say the word and "
                "I'll set one up for you",
                "- Log every breach for audit / historical review",
                "",
                "**What I cannot do yet (physical actuation):**",
                "- Automatically change a physical system (e.g. open a valve, adjust a thermostat "
                "setpoint) — that requires a BMS driver integration that is not yet configured for "
                f"this building.",
                "",
                f"Want me to create an alert rule for {monitoring_str}? "
                "Tell me the threshold (e.g. 'above 1000 ppm' / 'above 25 °C') and I'll set it up.",
            ]
        elif notify_available:
            answer_parts = [
                f"I don't have a dedicated sensor for {monitoring_str} wired up in this building yet, "
                "but the monitoring framework is in place.",
                "",
                "**What's possible:**",
                "- Once a sensor point is registered for that metric, the rules engine can watch it "
                "and send you alerts automatically",
                "- Notify-only automation is available today; physical actuation (valves, setpoints) "
                "needs a BMS driver not yet configured here",
                "",
                "If you can confirm the sensor exists or share the data source, I can register it "
                "and set up the alert rule.",
            ]
        else:
            answer_parts = [
                f"Automatic responses related to {monitoring_str} are not currently configured "
                "for this building.",
                "Contact your facility manager to discuss what automation extensions are available.",
            ]

        response = "\n".join(answer_parts)
        logger.info(
            f"[automation_capability] concept={concept_label!r} "
            f"sensor_available={sensor_available} notify={notify_available} "
            f"actuate={actuation_available}"
        )

        state.intermediate_results["automation_capability_result"] = {
            "concept": concept_label,
            "brick_class": brick_class,
            "sensor_available": sensor_available,
            "notify_available": notify_available,
            "actuation_available": actuation_available,
        }
        state.intermediate_results["dialogue_response"] = response
        return state

    async def execute(self, state: ConversationState) -> ConversationState:
        """
        Execute workflow for given state

        Args:
            state: Initial conversation state

        Returns:
            Updated conversation state with response
        """
        try:
            logger.info(f"Starting workflow execution for conversation {state.conversation_id}")

            # B.2: Check response cache before running the full pipeline
            if self.response_cache:
                user_query = state.messages[-1].content if state.messages else ""
                cached = await self.response_cache.get(
                    question=user_query,
                    building_id=state.building_id,
                    user_id=state.user_id,
                )
                if cached:
                    logger.info(
                        f"Response cache HIT — skipping pipeline (type={cached.get('cache_type')})"
                    )
                    state.messages.append(
                        Message(
                            role="assistant",
                            content=cached["response"],
                            metadata={
                                "cache_hit": True,
                                "cache_type": cached.get("cache_type"),
                            },
                        )
                    )
                    state.current_intent = cached.get("intent", "general")
                    state.intermediate_results["cache_hit"] = True
                    return state

            # Run the graph with timeout
            timeout_s = getattr(settings, "WORKFLOW_TIMEOUT_S", 120)
            try:
                final_state = await asyncio.wait_for(
                    self.graph.ainvoke(state),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.error(f"Workflow timed out after {timeout_s}s for {state.conversation_id}")
                state.messages.append(
                    Message(
                        role="assistant",
                        content="Your request took too long to process. Please try a simpler question or try again later.",
                    )
                )
                return state

            # LangGraph may return a dict-like state; rehydrate if needed
            if not isinstance(final_state, ConversationState):
                try:
                    final_state = ConversationState(**dict(final_state))
                except Exception as conv_err:
                    logger.error(f"State rehydration failed: {conv_err}")
                    final_state = state

            logger.info(f"Workflow completed for conversation {state.conversation_id}")
            return final_state

        except asyncio.TimeoutError:
            raise  # Already handled above, but safety net

        except Exception as e:
            logger.error(f"Workflow execution error: {e}", exc_info=True)

            # Map known error types to user-friendly messages
            error_msg = self._user_friendly_error(e)
            state.messages.append(Message(role="assistant", content=error_msg))

            return state

    @staticmethod
    def _user_friendly_error(e: Exception) -> str:
        """Map exceptions to user-friendly messages."""
        error_str = str(e).lower()
        error_type = type(e).__name__

        if "rate limit" in error_str or "429" in error_str:
            return "I'm receiving too many requests right now. Please wait a moment and try again."
        if "timeout" in error_type.lower() or "timeout" in error_str:
            return "Your request took too long to process. Please try a simpler query."
        if "connection" in error_str or "connect" in error_type.lower():
            return "I'm having trouble reaching one of the backend services. Please try again in a moment."
        if "authentication" in error_str or "401" in error_str:
            return "There was an authentication issue. Please log in again."

        return "I wasn't able to process your request. Could you try rephrasing your question?"

    _FOLLOW_UP_MAP = {
        "analytics": "Plot this data? | Check compliance against ASHRAE? | Compare with another zone?",
        "compliance": "Generate a full compliance report? | Export results as PDF? | Show trend over time?",
        "trend": "Detect anomalies in this trend? | Compare with another sensor? | Export as CSV?",
        "anomaly": "Show the full anomaly report? | Check compliance? | View historical trend?",
        "metadata": "Show current readings for these sensors? | Compare zones? | Generate a report?",
        "compare": "Plot the comparison? | Export results? | Check for anomalies?",
        "report": "Export this report as PDF? | Compare with last month? | View raw data?",
        "discovery": "Show live data for these sensors? | Generate a summary report?",
    }

    @classmethod
    def _get_follow_up_suggestions(cls, intent: str) -> str:
        """Return contextual follow-up suggestions based on the current intent."""
        return cls._FOLLOW_UP_MAP.get(intent, "")

    def _save_query_output(
        self,
        conversation_id: str,
        query: str,
        sparql: str,
        results: Dict[str, Any],
        analytics_required: bool,
        llm_reasoning: str,
        formatted_response: str,
    ):
        """
        Save query output as JSON file with analytics decision

        Output format:
        {
            "conversation_id": "...",
            "timestamp": "...",
            "user_query": "...",
            "analytics": true/false,
            "llm_reasoning": "...",
            "sparql_query": "...",
            "sparql_results": {...},
            "formatted_response": "..."
        }
        """
        import json
        from datetime import datetime
        from pathlib import Path

        try:
            # Create output directory if it doesn't exist
            output_dir = Path(settings.QUERY_RESULTS_DIR)
            output_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{conversation_id}_{timestamp}.json"
            filepath = output_dir / filename

            # Prepare output data
            output_data = {
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat(),
                "user_query": query,
                "analytics": analytics_required,
                "llm_reasoning": llm_reasoning,
                "sparql_query": sparql,
                "sparql_results": results,
                "formatted_response": formatted_response,
                "metadata": {
                    "result_count": (
                        len(results.get("results", {}).get("bindings", []))
                        if isinstance(results, dict)
                        else 0
                    ),
                    "execution_successful": True,
                },
            }

            # Save to file
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            logger.info(f"✅ Saved query output to: {filepath}")
            logger.info(f"   Analytics required: {analytics_required}")

        except Exception as e:
            logger.error(f"Failed to save query output: {e}", exc_info=True)

    async def stream_execute(self, state: ConversationState):
        """
        Execute workflow with streaming

        Yields:
            Intermediate states as they're processed
        """
        try:
            logger.info(f"Starting streaming workflow for conversation {state.conversation_id}")

            async for step in self.graph.astream(state):
                yield step

        except Exception as e:
            logger.error(f"Streaming workflow error: {e}", exc_info=True)
            yield {"error": str(e), "state": state}
