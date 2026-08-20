"""Phase 17B — WorkflowRoutingMixin.

Houses the downstream routing functions that decide where a pipeline goes
AFTER the data-fetch stages (sparql / sql / analytics).  Extracted from the
original monolithic workflow.py to make routing logic reviewable in isolation.

The big one — `_route_from_dialogue` — stays on `WorkflowOrchestrator` itself
because it pulls in viz-keyword sets, the intent registry, and ~12 contextual
overrides that are too tightly coupled to the orchestrator class to mix out
without architectural rework.  Phase 17B is the safe slice.

Dependencies provided by the inheriting class:
  * self._user_wants_visualization(message) — viz keyword detection
  * self._wants_document(state) — document-format detection
  * state.pipeline_ctx, state.messages, state.current_intent — ConversationState
"""

from __future__ import annotations

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)


class WorkflowRoutingMixin:
    """Mix into WorkflowOrchestrator for the 4 post-data-stage routing methods.

    Inheriting class MUST provide:
        * `_user_wants_visualization(message: str) -> bool` (class method)
        * `_wants_document(state: ConversationState) -> bool` (staticmethod)
    """

    def _route_from_data_node(self, state: ConversationState) -> str:
        """Route from SPARQL based on whether analytics/visualization is needed.

        Phase 7B — read access uses typed `state.pipeline_ctx` snapshot for
        IDE autocomplete + safety on the known pipeline keys.
        """
        ctx = state.pipeline_ctx

        # Short-circuit: compliance/follow-up recovered prior sensor data → go direct to analytics
        if ctx.use_existing_query_results and state.analytics_required:
            logger.info("[route] SPARQL→Analytics (prior data recovered for compliance)")
            return "analytics"

        # Check if analytics is required (and we are coming from SPARQL)
        # Allow routing to SQL for any data-fetching intent
        _sql_intents = {
            "sparql",
            "sensor_data",
            "analytics",
            "compare",
            "trend",
            "recommend",
            "compliance",
            "visualization",
            "anomaly",
        }
        if state.analytics_required and state.current_intent in _sql_intents:
            logger.info("Routing SPARQL -> SQL for data fetching (analytics=True)")
            return "sql"

        latest_message = state.messages[-1].content if state.messages else ""
        if self._user_wants_visualization(latest_message):
            return "visualization"

        return "response"

    def _route_from_analytics_node(self, state: ConversationState) -> str:
        """Route from Analytics based on whether visualization is needed.

        Phase 7B — typed read via `state.pipeline_ctx.analytics_result`.
        """
        ctx = state.pipeline_ctx
        # If analytics already embedded a plot in its output, skip the separate viz node
        if ctx.analytics_result and ctx.analytics_result.get("media"):
            logger.info("[route] Analytics already produced a plot — skipping visualization node")
            return "response"

        latest_message = state.messages[-1].content if state.messages else ""
        if self._user_wants_visualization(latest_message):
            return "visualization"

        return "response"

    def _route_from_sql(self, state: ConversationState) -> str:
        """Route from SQL node — extended for Phase 4 anomaly/report intents."""
        intent = state.current_intent

        # Phase 4: anomaly and report intents use SQL data for their agents
        if intent == "anomaly":
            return "anomaly"
        if intent in ("report",):
            return "report"
        # Visualization intent: always route to viz after SQL (data is now loaded)
        if intent == "visualization":
            return "visualization"

        if state.analytics_required:
            return "analytics"

        latest_message = state.messages[-1].content if state.messages else ""
        if self._user_wants_visualization(latest_message):
            return "visualization"
        analytics_keywords = [
            "analyze",
            "analysis",
            "pattern",
            "correlation",
            "statistics",
        ]
        if any(keyword in latest_message.lower() for keyword in analytics_keywords):
            return "analytics"
        return "response"

    def _route_from_report(self, state: ConversationState) -> str:
        """Route from report node to optional document generation."""
        return "document" if self._wants_document(state) else "response"
