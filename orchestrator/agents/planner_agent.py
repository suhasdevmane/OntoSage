"""
PlannerAgent — Multi-Step Query Planner (Phase 4.4 + Multi-Intent Extension)
=============================================================================
Orchestrates complex multi-step queries that require multiple agents.

For a user query, the PlannerAgent:
  1. Decomposes the query into an ordered execution plan (via LLM)
  2. Executes each step in sequence, passing outputs forward
  3. Routes the final assembled answer back to the user

Agent Registry (step types):
  - "sparql"        → SPARQLAgent
  - "sql"           → SQLAgent
  - "analytics"     → AnalyticsAgent
  - "report"        → ReportAgent
  - "export"        → DataExportAgent
  - "anomaly"       → AnomalyDetectionAgent
  - "capability"    → CapabilityAgent      (standalone — no data pipeline)
  - "floor_plan"    → FloorPlanAgent       (standalone — reads manifests)
  - "spatial_query" → SpatialAgent         (standalone — reads manifests)

Usage:
    from orchestrator.agents.planner_agent import PlannerAgent
    planner = PlannerAgent()
    result = await planner.plan_and_execute(state, user_query)
"""

import sys

sys.path.append("/app")

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from orchestrator.llm_manager import llm_manager
from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Phase 6 — the intent registry is the single source of truth.  These two sets
# previously had to be kept in sync with dialogue_agent.py, multi_intent_detector.py,
# and the YAML registry.  Now they derive from the registry; legacy hardcoded sets
# remain as a fallback when the registry can't load.

_LEGACY_DATA_PIPELINE_AGENTS = frozenset(
    {
        "sparql",
        "sql",
        "analytics",
        "anomaly",
        "compare",
        "trend",
        "recommend",
        "compliance",
        "report",
        "export",
        "sensor_data",
    }
)

_LEGACY_STANDALONE_AGENTS = frozenset(
    {
        "capability",
        "floor_plan",
        "spatial_query",
        "maintenance",
        "control",
        "general",
        "discovery",
        "metadata",
    }
)


def _load_pipeline_groups():
    try:
        from orchestrator.intents import get_intent_registry

        reg = get_intent_registry()
        # sparql / sql are pipeline-stage agent names, not LLM intents — keep
        # them in the data set even though they aren't in the registry.
        data = reg.in_group("data") | frozenset({"sparql", "sql"})
        standalone = reg.in_group("standalone")
        if data and standalone:
            return data, standalone
    except Exception:
        pass
    return _LEGACY_DATA_PIPELINE_AGENTS, _LEGACY_STANDALONE_AGENTS


_DATA_PIPELINE_AGENTS, _STANDALONE_AGENTS = _load_pipeline_groups()


@dataclass
class PlanStep:
    """A single step in the execution plan."""

    index: int
    agent: str
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    success: bool = False
    error: Optional[str] = None


@dataclass
class ExecutionPlan:
    """A fully resolved execution plan."""

    user_query: str
    steps: List[PlanStep]
    rationale: str = ""
    multi_intent: bool = False


class PlannerAgent:
    """Orchestrates complex queries requiring multiple agent types."""

    MAX_STEPS = settings.PLANNER_MAX_STEPS

    COMPLEX_TRIGGERS = [
        "report",
        "export",
        "generate",
        "create",
        "download",
        "anomaly",
        "alert",
        "trend report",
        "weekly",
        "monthly",
        "compare and export",
        "analyze and report",
    ]

    def is_complex_query(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in self.COMPLEX_TRIGGERS)

    async def plan_and_execute(self, state: ConversationState, user_query: str) -> Dict[str, Any]:
        """Main entry: build a plan then execute it step-by-step."""
        logger.info("=" * 70)
        logger.info("PLANNER AGENT: Building execution plan")
        logger.info("=" * 70)
        logger.info(f"Query: {user_query}")

        try:
            multi_plan = state.intermediate_results.get("multi_intent_plan")
            if multi_plan:
                plan = self._build_from_multi_intent(user_query, multi_plan)
                logger.info(
                    f"[multi-intent] Pre-built plan: {len(plan.steps)} steps " f"— {plan.rationale}"
                )
            else:
                plan = await self._build_plan(user_query)
                logger.info(f"Plan: {len(plan.steps)} steps — {plan.rationale}")

            result = await self._execute_plan(state, plan)
            return result
        except Exception as e:
            logger.error(f"PlannerAgent failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "formatted_response": f"Planning failed: {e}",
            }

    # ------------------------------------------------------------------
    # Plan building
    # ------------------------------------------------------------------

    def _build_from_multi_intent(
        self, user_query: str, multi_plan: Dict[str, Any]
    ) -> ExecutionPlan:
        """Build an ExecutionPlan from pre-decomposed multi-intent sub-intents."""
        sub_intents = multi_plan.get("sub_intents", [])

        group_a = [s for s in sub_intents if s["intent"] in _DATA_PIPELINE_AGENTS]
        group_b = [s for s in sub_intents if s["intent"] in _STANDALONE_AGENTS]

        steps: List[PlanStep] = []
        idx = 1

        # Build a focused data query from Group A sub-queries (not the full compound)
        data_sub_queries = [s.get("sub_query", "") for s in group_a if s.get("sub_query")]
        focused_data_query = "; ".join(data_sub_queries) if data_sub_queries else ""

        if group_a:
            steps.append(
                PlanStep(
                    index=idx,
                    agent="sparql",
                    description="Retrieve sensor metadata and UUIDs",
                    params={"focused_query": focused_data_query},
                )
            )
            idx += 1
            steps.append(
                PlanStep(
                    index=idx,
                    agent="sql",
                    description="Fetch time-series sensor data",
                    params={"focused_query": focused_data_query},
                )
            )
            idx += 1

            for sub in group_a:
                agent = sub["intent"]
                if agent in ("sparql", "sql", "sensor_data"):
                    continue
                steps.append(
                    PlanStep(
                        index=idx,
                        agent=agent,
                        description=sub.get("sub_query", sub["intent"]),
                        params={"sub_query": sub.get("sub_query", "")},
                    )
                )
                idx += 1

        for sub in group_b:
            steps.append(
                PlanStep(
                    index=idx,
                    agent=sub["intent"],
                    description=sub.get("sub_query", sub["intent"]),
                    params={"sub_query": sub.get("sub_query", "")},
                )
            )
            idx += 1

        intents = [s["intent"] for s in sub_intents]
        return ExecutionPlan(
            user_query=user_query,
            steps=steps[: self.MAX_STEPS],
            rationale=f"Multi-intent decomposition: {', '.join(intents)}",
            multi_intent=True,
        )

    async def _build_plan(self, user_query: str) -> ExecutionPlan:
        """Ask LLM to decompose query into an ordered execution plan."""
        prompt = f"""You are an execution planner for a smart building Q&A system.

Decompose the following user request into an ordered sequence of agent calls.

User Request: "{user_query}"

Available agents:
- "sparql"    → Queries the ontology graph (GraphDB) for sensor metadata and UUIDs
- "sql"       → Fetches time-series sensor readings from the database
- "analytics" → Performs statistical analysis (trends, averages, correlations)
- "report"    → Generates a structured narrative report
- "export"    → Exports data to JSON/CSV/HTML/Markdown
- "anomaly"   → Detects anomalous readings based on comfort thresholds

Return a JSON object:
{{
  "rationale": "one sentence explaining the plan",
  "steps": [
    {{"index": 1, "agent": "sparql", "description": "what to query", "params": {{}}}},
    {{"index": 2, "agent": "sql",    "description": "what data to fetch", "params": {{"time_range": "last_week"}}}},
    ...
  ]
}}

Rules:
- Maximum {self.MAX_STEPS} steps
- "sparql" must come before "sql" (we need UUIDs first)
- "sql" must come before "analytics", "anomaly", "report", "export"
- Only include "export" if user explicitly asks for file output
- Return ONLY the JSON object"""

        try:
            response = await llm_manager.generate(prompt, temperature=0.1)
            match = re.search(r"\{[\s\S]*\}", response)
            if not match:
                raise ValueError("LLM returned no JSON")
            plan_dict = json.loads(match.group(0))
            steps = [
                PlanStep(
                    index=s.get("index", i + 1),
                    agent=s.get("agent", "sparql"),
                    description=s.get("description", ""),
                    params=s.get("params", {}),
                )
                for i, s in enumerate(plan_dict.get("steps", []))
            ]
            return ExecutionPlan(
                user_query=user_query,
                steps=steps[: self.MAX_STEPS],
                rationale=plan_dict.get("rationale", ""),
            )
        except Exception as e:
            logger.warning(f"LLM plan building failed ({e}), using fallback plan")
            return self._fallback_plan(user_query)

    def _fallback_plan(self, user_query: str) -> ExecutionPlan:
        """Minimal 2-step plan as fallback when LLM decomposition fails."""
        q = user_query.lower()
        steps = [
            PlanStep(index=1, agent="sparql", description="Retrieve sensor metadata and UUIDs")
        ]
        if any(w in q for w in ["current", "reading", "value", "data", "average", "trend"]):
            steps.append(
                PlanStep(index=2, agent="sql", description="Fetch sensor time-series data")
            )
        if "report" in q:
            steps.append(
                PlanStep(index=len(steps) + 1, agent="report", description="Generate report")
            )
        if "export" in q or "download" in q:
            fmt = "csv" if "csv" in q else ("html" if "html" in q else "json")
            steps.append(
                PlanStep(
                    index=len(steps) + 1,
                    agent="export",
                    description=f"Export as {fmt}",
                    params={"format": fmt},
                )
            )
        return ExecutionPlan(user_query=user_query, steps=steps, rationale="Fallback plan")

    # ------------------------------------------------------------------
    # Plan execution
    # ------------------------------------------------------------------

    async def _execute_plan(self, state: ConversationState, plan: ExecutionPlan) -> Dict[str, Any]:
        """Execute plan steps, running standalone agents in parallel."""
        import asyncio

        context: Dict[str, Any] = {}
        provenance: List[str] = []
        section_results: List[Dict[str, str]] = []

        if plan.multi_intent:
            return await self._execute_multi_intent(state, plan)

        for step in plan.steps:
            logger.info(f"  Step {step.index}/{len(plan.steps)}: [{step.agent}] {step.description}")
            try:
                result = await self._dispatch_step(state, plan, step, context)
                step.result = result
                step.success = True
                provenance.append(f"Step {step.index} [{step.agent}]: done — {step.description}")
            except Exception as e:
                step.error = str(e)
                step.success = False
                logger.warning(f"  Step {step.index} failed: {e}")
                provenance.append(f"Step {step.index} [{step.agent}]: failed — {e}")

        return self._assemble_result(plan, context, provenance)

    async def _execute_multi_intent(
        self, state: ConversationState, plan: ExecutionPlan
    ) -> Dict[str, Any]:
        """Execute multi-intent plan: data pipeline sequential, standalone parallel."""
        import asyncio

        context: Dict[str, Any] = {}
        provenance: List[str] = []
        section_results: List[Dict[str, str]] = []

        # Split steps into sequential (data pipeline) and parallel (standalone)
        data_steps = [s for s in plan.steps if s.agent in ("sparql", "sql")]
        post_data_steps = [
            s
            for s in plan.steps
            if s.agent not in ("sparql", "sql") and s.agent in _DATA_PIPELINE_AGENTS
        ]
        standalone_steps = [s for s in plan.steps if s.agent in _STANDALONE_AGENTS]

        _STEP_TIMEOUT = 45  # seconds per individual step

        # Phase 1: Run sparql→sql sequentially (data pipeline prefix)
        for step in data_steps:
            logger.info(f"  [data] Step {step.index}: [{step.agent}] {step.description}")
            try:
                result = await asyncio.wait_for(
                    self._dispatch_step(state, plan, step, context),
                    timeout=_STEP_TIMEOUT,
                )
                step.result = result
                step.success = True
                provenance.append(f"Step {step.index} [{step.agent}]: done")
            except asyncio.TimeoutError:
                step.error = f"timeout after {_STEP_TIMEOUT}s"
                step.success = False
                logger.warning(f"  [data] Step {step.index} timed out after {_STEP_TIMEOUT}s")
                provenance.append(f"Step {step.index} [{step.agent}]: timeout")
            except Exception as e:
                step.error = str(e)
                step.success = False
                logger.warning(f"  [data] Step {step.index} failed: {e}")
                provenance.append(f"Step {step.index} [{step.agent}]: failed — {e}")

        # After data pipeline: if sensor_data was a requested sub-intent,
        # inject the SQL time-series result as a section so it appears in
        # the aggregated response. Previously sensor_data was silently
        # skipped in _build_from_multi_intent (group_a filter).
        _multi_plan = state.intermediate_results.get("multi_intent_plan", {})
        _requested_sub_intents = {s.get("intent") for s in _multi_plan.get("sub_intents", [])}
        if "sensor_data" in _requested_sub_intents:
            _sql_r = context.get("sql_result")
            if _sql_r:
                _sensor_content = self._extract_section_content("sql", _sql_r)
                if _sensor_content and _sensor_content.strip():
                    _sub_query_for_label = next(
                        (
                            s.get("sub_query", "sensor readings")
                            for s in _multi_plan.get("sub_intents", [])
                            if s.get("intent") == "sensor_data"
                        ),
                        "sensor readings",
                    )
                    section_results.append(
                        {
                            "agent": "sensor_data",
                            "description": _sub_query_for_label,
                            "content": _sensor_content,
                        }
                    )
                    logger.info(
                        "[multi-intent] injected sensor_data section from SQL result "
                        f"({len(_sensor_content)} chars)"
                    )

        # Phase 2: Run post-data agents AND standalone agents in parallel
        parallel_steps = post_data_steps + standalone_steps
        if parallel_steps:
            logger.info(
                f"  [parallel] Running {len(parallel_steps)} agents: "
                f"{[s.agent for s in parallel_steps]}"
            )

            async def _run_one(step: PlanStep) -> Dict[str, str]:
                try:
                    result = await asyncio.wait_for(
                        self._dispatch_step(state, plan, step, context),
                        timeout=_STEP_TIMEOUT,
                    )
                    step.result = result
                    step.success = True
                    return {
                        "agent": step.agent,
                        "description": step.description,
                        "content": self._extract_section_content(step.agent, result),
                    }
                except asyncio.TimeoutError:
                    step.error = f"timeout after {_STEP_TIMEOUT}s"
                    step.success = False
                    logger.warning(f"  [{step.agent}] timed out after {_STEP_TIMEOUT}s")
                    return {
                        "agent": step.agent,
                        "description": step.description,
                        "content": "This part took too long and was skipped.",
                    }
                except Exception as e:
                    step.error = str(e)
                    step.success = False
                    logger.warning(f"  [{step.agent}] failed: {e}")
                    return {
                        "agent": step.agent,
                        "description": step.description,
                        "content": f"This part could not be answered: {e}",
                    }

            results = await asyncio.gather(
                *[_run_one(s) for s in parallel_steps],
                return_exceptions=False,
            )
            section_results.extend(results)
            for s in parallel_steps:
                status = "done" if s.success else f"failed — {s.error}"
                provenance.append(f"Step {s.index} [{s.agent}]: {status}")

        if section_results:
            return self._assemble_multi_intent(plan, section_results, provenance)
        return self._assemble_result(plan, context, provenance)

    async def _dispatch_step(
        self,
        state: ConversationState,
        plan: ExecutionPlan,
        step: PlanStep,
        context: Dict[str, Any],
    ) -> Any:
        """Route a plan step to the appropriate agent delegate."""
        agent = step.agent
        # For multi-intent plans, use the focused data query instead of the
        # full compound question — produces better SPARQL/SQL generation.
        effective_query = step.params.get("focused_query") or plan.user_query

        if agent == "sparql":
            result = await self._run_sparql(state, effective_query, step.params)
            context["sparql_result"] = result
            context["uuids"] = self._extract_uuids(result)
            context["storage_map"] = self._extract_storage_map(result)
            return result

        elif agent == "sql":
            uuids = context.get("uuids", [])
            storage_map = context.get("storage_map", {})
            result = await self._run_sql(state, effective_query, uuids, storage_map, step.params)
            context["sql_result"] = result
            return result

        elif agent == "analytics":
            query = step.params.get("sub_query") or effective_query
            result = await self._run_analytics(state, query, context)
            context["analytics_result"] = result
            return result

        elif agent == "anomaly":
            query = step.params.get("sub_query") or effective_query
            result = await self._run_anomaly(state, query, context)
            context["anomaly_result"] = result
            return result

        elif agent == "report":
            query = step.params.get("sub_query") or effective_query
            result = await self._run_report(state, query, context, step.params)
            context["report_result"] = result
            return result

        elif agent == "export":
            result = await self._run_export(context, step.params)
            context["export_result"] = result
            return result

        elif agent == "capability":
            result = await self._run_capability(state, step)
            context["capability_result"] = result
            return result

        elif agent == "floor_plan":
            result = await self._run_floor_plan(state, step)
            context["floor_plan_result"] = result
            return result

        elif agent == "spatial_query":
            result = await self._run_spatial_query(state, step)
            context["spatial_result"] = result
            return result

        elif agent in ("compare", "trend", "recommend", "compliance", "sensor_data"):
            query = step.params.get("sub_query") or effective_query
            result = await self._run_analytics(state, query, context)
            context["analytics_result"] = result
            return result

        elif agent == "maintenance":
            result = await self._run_maintenance(state, step)
            context["maintenance_result"] = result
            return result

        else:
            logger.warning(f"[planner] Unknown agent type: {agent}")
            return {"success": False, "error": f"Unknown agent: {agent}"}

    # ------------------------------------------------------------------
    # Result assembly
    # ------------------------------------------------------------------

    def _assemble_multi_intent(
        self,
        plan: ExecutionPlan,
        section_results: List[Dict[str, str]],
        provenance: List[str],
    ) -> Dict[str, Any]:
        """Build a sectioned response from multi-intent sub-task results."""
        sections = []
        for sec in section_results:
            content = sec["content"]
            if not content or content.strip() == "":
                continue
            header = self._section_header(sec["agent"], sec["description"])
            sections.append(f"## {header}\n\n{content}")

        if not sections:
            return {
                "success": False,
                "formatted_response": (
                    "I tried to address each part of your question but could not "
                    "produce usable results. Please try asking each part separately."
                ),
                "provenance": provenance,
                "multi_intent": True,
            }

        combined = "\n\n---\n\n".join(sections)
        return {
            "success": True,
            "formatted_response": combined,
            "provenance": provenance,
            "plan_rationale": plan.rationale,
            "multi_intent": True,
        }

    def _section_header(self, agent: str, description: str) -> str:
        """Generate a human-readable section header."""
        _HEADERS = {
            "analytics": "Sensor Data Analysis",
            "anomaly": "Anomaly Detection",
            "capability": "Building Information",
            "floor_plan": "Floor Plan",
            "spatial_query": "Spatial Information",
            "report": "Report",
            "compare": "Comparison",
            "trend": "Trend Analysis",
            "recommend": "Recommendations",
            "compliance": "Compliance Check",
            "maintenance": "Maintenance",
            "export": "Data Export",
            "sensor_data": "Sensor Readings",
            "sql": "Sensor Readings",
        }
        return _HEADERS.get(agent, description[:60])

    def _extract_section_content(self, agent: str, result: Any) -> str:
        """Extract displayable text from an agent result."""
        if result is None:
            return ""
        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            for key in (
                "formatted_response",
                "formatted_text",
                "response",
                "markdown",
                "content",
                "message",
            ):
                val = result.get(key)
                if val and isinstance(val, str):
                    return val
            if result.get("success") is False:
                return result.get("error", "No data available.")

        return str(result) if result else ""

    def _assemble_result(
        self, plan: ExecutionPlan, context: Dict, provenance: List[str]
    ) -> Dict[str, Any]:
        """Build final response from accumulated context (single-intent planner)."""
        for key in [
            "report_result",
            "analytics_result",
            "export_result",
            "sql_result",
            "sparql_result",
        ]:
            if key in context:
                r = context[key]
                if isinstance(r, dict) and r.get("success"):
                    return {
                        "success": True,
                        "formatted_response": r.get("formatted_text")
                        or r.get("formatted_response")
                        or str(r),
                        "provenance": provenance,
                        "plan_rationale": plan.rationale,
                        "context": context,
                    }
        return {
            "success": False,
            "formatted_response": "The plan executed but produced no usable output.",
            "provenance": provenance,
        }

    # ------------------------------------------------------------------
    # Agent delegates — data pipeline
    # ------------------------------------------------------------------

    async def _run_sparql(self, state: ConversationState, query: str, params: Dict) -> Dict:
        from orchestrator.agents.sparql_agent import SPARQLAgent

        return await SPARQLAgent().generate_query(state, query)

    async def _run_sql(
        self,
        state: ConversationState,
        query: str,
        uuids: List,
        storage_map: Dict,
        params: Dict,
    ) -> Dict:
        from orchestrator.agents.sql_agent import SQLAgent

        if uuids:
            return await SQLAgent().fetch_data_for_uuids(uuids, query, storage_map)
        return await SQLAgent().generate_and_execute(state, query)

    async def _run_analytics(self, state: ConversationState, query: str, ctx: Dict) -> Dict:
        from orchestrator.agents.analytics_agent import AnalyticsAgent

        sql_result = ctx.get("sql_result", {})
        data = sql_result.get("results", {}) if isinstance(sql_result, dict) else {}
        if not isinstance(data, dict) or "data" not in data:
            data = {"data": data} if isinstance(data, list) else {"data": []}
        sensor_metadata = self._extract_sensor_metadata(ctx.get("sparql_result", {}))
        return await AnalyticsAgent().analyze(
            state, query, data=data, sensor_metadata=sensor_metadata
        )

    async def _run_anomaly(self, state: ConversationState, query: str, ctx: Dict) -> Dict:
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent

        sql_result = ctx.get("sql_result", {})
        data = sql_result.get("results", sql_result) if isinstance(sql_result, dict) else sql_result
        return await AnomalyDetectionAgent().detect(state, query, sensor_data=data)

    async def _run_report(
        self, state: ConversationState, query: str, ctx: Dict, params: Dict
    ) -> Dict:
        from orchestrator.agents.report_agent import ReportAgent

        return await ReportAgent().generate(
            state,
            query,
            sensor_data=ctx.get("sql_result"),
            metadata=ctx.get("sparql_result"),
            export_format=params.get("export_format"),
        )

    async def _run_export(self, ctx: Dict, params: Dict) -> Dict:
        from orchestrator.agents.data_export_agent import DataExportAgent

        data = (
            ctx.get("sql_result") or ctx.get("anomaly_result") or ctx.get("analytics_result") or {}
        )
        fmt = params.get("format", "json")
        return await DataExportAgent().export(data=data, label="planner_export", fmt=fmt)

    # ------------------------------------------------------------------
    # Agent delegates — standalone (no data pipeline needed)
    # ------------------------------------------------------------------

    async def _run_capability(self, state: ConversationState, step: PlanStep) -> Dict:
        from orchestrator.agents.capability_agent import CapabilityAgent

        sub_query = step.params.get("sub_query", step.description)
        temp_state = self._clone_state_for_sub(state, sub_query, "capability")
        temp_state = await CapabilityAgent().answer(temp_state)
        result = temp_state.intermediate_results.get("capability_result", {})
        return {
            "success": bool(result.get("response")),
            "formatted_response": result.get("response", ""),
            "response": result.get("response", ""),
        }

    async def _run_floor_plan(self, state: ConversationState, step: PlanStep) -> Dict:
        from orchestrator.agents.floor_plan_agent import get_floor_plan_agent

        sub_query = step.params.get("sub_query", step.description)
        agent = get_floor_plan_agent()
        result = await agent.resolve(sub_query, state)
        return {
            "success": True,
            "formatted_response": result.markdown,
            "markdown": result.markdown,
        }

    async def _run_spatial_query(self, state: ConversationState, step: PlanStep) -> Dict:
        from orchestrator.agents.spatial_agent import get_spatial_agent

        sub_query = step.params.get("sub_query", step.description)
        # Phase 4 — alias-aware: floor_context > state.building_id > settings.
        # The BuildingRegistry alias map resolves legacy slugs to the logical ID.
        building_id = (
            (state.floor_context or {}).get("building_id")
            or state.building_id
            or settings.BUILDING_ID
        )
        floor = (state.floor_context or {}).get("floor")

        agent = get_spatial_agent()
        markdown = await agent.resolve(sub_query, building_id, floor)
        return {
            "success": True,
            "formatted_response": markdown,
            "markdown": markdown,
        }

    async def _run_maintenance(self, state: ConversationState, step: PlanStep) -> Dict:
        sub_query = step.params.get("sub_query", step.description)
        return {
            "success": True,
            "formatted_response": (
                "To report a maintenance issue, please use the command: "
                "'Report fault in [location]: [description]'. "
                "A facility manager will be notified and a ticket created."
            ),
            "response": sub_query,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clone_state_for_sub(
        self, state: ConversationState, sub_query: str, intent: str
    ) -> ConversationState:
        """Create a shallow copy of state with overridden message + intent for a sub-task."""
        from copy import copy

        from shared.models import Message

        cloned = copy(state)
        cloned.intermediate_results = dict(state.intermediate_results)
        cloned.messages = list(state.messages)
        if cloned.messages:
            cloned.messages[-1] = Message(role="user", content=sub_query)
        cloned.current_intent = intent
        return cloned

    def _extract_uuids(self, sparql_result: Dict) -> List[str]:
        if not isinstance(sparql_result, dict):
            return []
        standardized = sparql_result.get("standardized", {})
        results = standardized.get("results", []) if isinstance(standardized, dict) else []
        return [r.get("uuid") for r in results if r.get("uuid")]

    def _extract_storage_map(self, sparql_result: Dict) -> Dict[str, str]:
        if not isinstance(sparql_result, dict):
            return {}
        standardized = sparql_result.get("standardized", {})
        results = standardized.get("results", []) if isinstance(standardized, dict) else []
        return {r["uuid"]: r.get("storage", "") for r in results if r.get("uuid")}

    def _extract_sensor_metadata(self, sparql_result: Dict) -> Dict[str, Dict]:
        """Extract uuid→{label, type} mapping from SPARQL results."""
        if not isinstance(sparql_result, dict):
            return {}
        standardized = sparql_result.get("standardized", {})
        results = standardized.get("results", []) if isinstance(standardized, dict) else []
        metadata = {}
        for r in results:
            uuid = r.get("uuid")
            if uuid:
                metadata[uuid] = {
                    "label": r.get("label", r.get("name", uuid)),
                    "type": r.get("type", ""),
                }
        return metadata


# Module-level singleton
planner_agent = PlannerAgent()
