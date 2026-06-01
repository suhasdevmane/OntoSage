"""Phase 17C — WorkflowGraphMixin.

Extracted `_build_graph` from the monolithic workflow.py into its own module
for reviewability.  Graph construction is the most critical piece of the
orchestrator — having it isolated makes the pipeline topology easy to audit
without scrolling past 3,000 lines of node implementations.

The mixin reads from the intent registry to auto-register graph nodes (Phase 13B)
and only adds CONDITIONAL EDGES whose targets are actually registered (preventing
LangGraph from rejecting the graph build when a YAML-added intent has no
matching `node_method`).

Dependencies the inheriting class MUST provide:
  * All `_*_node` methods referenced (dialogue, sparql, sql, analytics, response,
    report, anomaly, document, plus every intent's `node_method` declared in
    intent_definitions.yaml)
  * `_safe_node(fn, name)` wrapper for graceful degradation
  * `_route_from_dialogue`, `_route_from_data_node`, `_route_from_sql`,
    `_route_from_analytics_node`, `_route_from_report` (the routing functions)
"""

from __future__ import annotations

from typing import List

from langgraph.graph import END, StateGraph

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)


class WorkflowGraphMixin:
    """Mix into WorkflowOrchestrator for `_build_graph()`.

    The inheriting class must define every node method referenced by name in
    the intent registry (auto-wire) and by the shared-infra hardcoded list.
    """

    def _build_graph(self) -> StateGraph:
        """Build LangGraph state machine.

        Phase 13B (2026-05-29): nodes that are 1:1 with an intent are auto-registered
        from `orchestrator/intents/intent_definitions.yaml` via the `node_method`
        field.  Pipeline-stage nodes (dialogue, sparql, sql, analytics, response)
        and downstream-only nodes (report, anomaly, document) remain hardcoded
        because they are shared infrastructure, not 1:1 with any single intent.

        Adding a new intent that needs its own graph node now requires:
          1. Add the intent entry to intent_definitions.yaml with `node_method: _foo_node`
          2. Implement `_foo_node` on WorkflowOrchestrator
        No further `workflow.py` edits.

        Phase 17C: moved into this mixin module for reviewability; behavior unchanged.
        """

        # Create state graph
        workflow = StateGraph(ConversationState)

        # ── Shared infrastructure nodes (NOT in intent registry) ─────────────
        # These exist regardless of the intent taxonomy; they back the data
        # pipeline (sparql→sql→analytics) and the entry/exit of every flow.
        workflow.add_node("dialogue", self._dialogue_node)
        workflow.add_node("sparql", self._safe_node(self._sparql_node, "sparql"))
        workflow.add_node("sql", self._safe_node(self._sql_node, "sql"))
        workflow.add_node(
            "analytics", self._safe_node(self._analytics_node, "analytics")
        )
        workflow.add_node("response", self._response_node)
        # Downstream nodes invoked from the data pipeline, not from dialogue
        # routing — kept hardcoded because they are NOT primary intent targets.
        workflow.add_node("report", self._safe_node(self._report_node, "report"))
        workflow.add_node("anomaly", self._safe_node(self._anomaly_node, "anomaly"))
        workflow.add_node("document", self._safe_node(self._document_node, "document"))

        # ── Registry-driven intent nodes (Phase 13B) ─────────────────────────
        # Every intent declaring `node_method:` gets its graph node registered
        # here automatically.  Iteration order = YAML order = stable.
        from orchestrator.intents import get_intent_registry
        _registry_for_graph = get_intent_registry()
        _registered_intent_nodes: List[str] = []
        for _intent_def in _registry_for_graph.with_node_method():
            node_name = _intent_def.route_target or _intent_def.name
            method_name = _intent_def.node_method
            # Skip if a shared-infra node with the same name was already
            # registered above (e.g. visualization → keep the shared registration).
            if node_name in _registered_intent_nodes:
                continue
            method = getattr(self, method_name, None)
            if method is None:
                logger.error(
                    f"[graph_build] intent '{_intent_def.name}' declares "
                    f"node_method='{method_name}' but no such method exists on "
                    "WorkflowOrchestrator — node NOT registered."
                )
                continue
            workflow.add_node(node_name, self._safe_node(method, node_name))
            _registered_intent_nodes.append(node_name)
            logger.debug(
                f"[graph_build] registered node '{node_name}' from intent "
                f"'{_intent_def.name}' via {method_name}"
            )

        # Entry
        workflow.set_entry_point("dialogue")

        # ── Conditional edges from dialogue (Phase 13B: registry-driven dict) ─
        # The dialogue routing target dict is the union of:
        #   * shared pipeline stages (sparql, sql, analytics, response)
        #   * every registered intent node (auto-wired above)
        #   * downstream-only nodes that dialogue routing may target directly
        #     (anomaly, report — kept for legacy direct routing)
        # We intersect with "actually registered" so an unregistered YAML-added
        # intent's route_target cannot crash the graph build.  At runtime, the
        # Phase 10G safety net inside `_route_from_dialogue` rewrites such
        # intents to "response" before they reach LangGraph.
        _shared_targets = {
            "sparql", "sql", "analytics", "response",
            # Downstream nodes that dialogue can route to in the (rare)
            # case the LLM picks a downstream label directly.
            "anomaly", "report",
        }
        _registered = frozenset(workflow.nodes.keys())
        _all_targets = (
            _shared_targets
            | set(_registry_for_graph.route_targets())
        ) & _registered
        _dialogue_route_map = {tgt: tgt for tgt in sorted(_all_targets)}
        _dialogue_route_map["end"] = END
        workflow.add_conditional_edges(
            "dialogue",
            self._route_from_dialogue,
            _dialogue_route_map,
        )

        # SPARQL → SQL / analytics / response
        workflow.add_conditional_edges(
            "sparql",
            self._route_from_data_node,
            {
                "visualization": "visualization",
                "response": "response",
                "sql": "sql",
                "analytics": "analytics",
            },
        )

        # SQL → Analytics / response
        workflow.add_conditional_edges(
            "sql",
            self._route_from_sql,
            {
                "analytics": "analytics",
                "visualization": "visualization",
                "anomaly": "anomaly",
                "report": "report",
                "response": "response",
            },
        )

        # Analytics → Viz / response
        workflow.add_conditional_edges(
            "analytics",
            self._route_from_analytics_node,
            {"visualization": "visualization", "response": "response"},
        )

        # Phase 4 nodes all lead to response (report may optionally create a document)
        workflow.add_edge("planner", "response")
        workflow.add_conditional_edges(
            "report",
            self._route_from_report,
            {"document": "document", "response": "response"},
        )
        workflow.add_edge("anomaly", "response")
        workflow.add_edge("export", "response")
        workflow.add_edge("visualization", "response")
        workflow.add_edge("document", "response")
        workflow.add_edge("floor_plan", "response")
        workflow.add_edge("spatial_query", "response")
        workflow.add_edge("control", "response")
        workflow.add_edge("maintenance", "response")
        # Phase 19 - unified report-intake categories all terminate at response.
        for _report_node in ("complaint", "feedback", "safety_report", "suggestion"):
            if _report_node in workflow.nodes:
                workflow.add_edge(_report_node, "response")
        workflow.add_edge("capability", "response")
        workflow.add_edge("response", END)

        return workflow.compile()
