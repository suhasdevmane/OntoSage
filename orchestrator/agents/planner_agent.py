"""
PlannerAgent — Phase 4.4 (Multi-Step Query Planner)
=====================================================
Orchestrates complex multi-step queries that require multiple agents.

For a user query, the PlannerAgent:
  1. Decomposes the query into an ordered execution plan (via LLM)
  2. Executes each step in sequence, passing outputs forward
  3. Routes the final assembled answer back to the user

Agent Registry (step types):
  - "sparql" → SPARQLAgent
  - "sql"    → SQLAgent
  - "analytics" → AnalyticsAgent
  - "report" → ReportAgent
  - "export" → DataExportAgent
  - "anomaly" → AnomalyDetectionAgent

Usage:
    from orchestrator.agents.planner_agent import PlannerAgent
    planner = PlannerAgent()
    result = await planner.plan_and_execute(state, user_query)
"""
import sys
sys.path.append('/app')

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.config import settings
from shared.models import ConversationState
from shared.utils import get_logger
from orchestrator.llm_manager import llm_manager

logger = get_logger(__name__)


@dataclass
class PlanStep:
    """A single step in the execution plan."""
    index: int
    agent: str          # "sparql" | "sql" | "analytics" | "report" | "export" | "anomaly"
    description: str    # Human-readable description
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


class PlannerAgent:
    """
    Phase 4.4: Orchestrates complex queries requiring multiple agent types.

    Example plans:
      "Generate a CO2 trend report for last week"
        → Step 1: sparql (get CO2 sensor UUIDs)
        → Step 2: sql   (fetch last-week readings)
        → Step 3: analytics (compute trend)
        → Step 4: report (generate report document)

      "Export temperature anomaly data as CSV"
        → Step 1: sparql (get temperature UUIDs)
        → Step 2: sql   (fetch data)
        → Step 3: anomaly (detect anomalies)
        → Step 4: export (CSV export)
    """

    MAX_STEPS = settings.PLANNER_MAX_STEPS

    # Keywords that trigger planner routing (vs direct SPARQL)
    COMPLEX_TRIGGERS = [
        "report", "export", "generate", "create", "download",
        "anomaly", "alert", "trend report", "weekly", "monthly",
        "compare and export", "analyze and report",
    ]

    def is_complex_query(self, query: str) -> bool:
        q = query.lower()
        return any(kw in q for kw in self.COMPLEX_TRIGGERS)

    async def plan_and_execute(
        self, state: ConversationState, user_query: str
    ) -> Dict[str, Any]:
        """
        Main entry: build a plan then execute it step-by-step.
        """
        logger.info("=" * 70)
        logger.info("🗺️  PLANNER AGENT: Building execution plan")
        logger.info("=" * 70)
        logger.info(f"Query: {user_query}")

        try:
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
            match = re.search(r'\{[\s\S]*\}', response)
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
        steps = [PlanStep(index=1, agent="sparql", description="Retrieve sensor metadata and UUIDs")]
        if any(w in q for w in ["current", "reading", "value", "data", "average", "trend"]):
            steps.append(PlanStep(index=2, agent="sql", description="Fetch sensor time-series data"))
        if "report" in q:
            steps.append(PlanStep(index=len(steps) + 1, agent="report", description="Generate report"))
        if "export" in q or "download" in q:
            fmt = "csv" if "csv" in q else ("html" if "html" in q else "json")
            steps.append(PlanStep(index=len(steps) + 1, agent="export",
                                  description=f"Export as {fmt}", params={"format": fmt}))
        return ExecutionPlan(user_query=user_query, steps=steps, rationale="Fallback plan")

    # ------------------------------------------------------------------
    # Plan execution
    # ------------------------------------------------------------------

    async def _execute_plan(
        self, state: ConversationState, plan: ExecutionPlan
    ) -> Dict[str, Any]:
        """Execute plan steps sequentially, passing context forward."""
        context: Dict[str, Any] = {}
        provenance: List[str] = []

        for step in plan.steps:
            logger.info(f"  Step {step.index}/{len(plan.steps)}: [{step.agent}] {step.description}")
            try:
                if step.agent == "sparql":
                    result = await self._run_sparql(state, plan.user_query, step.params)
                    context["sparql_result"] = result
                    context["uuids"] = self._extract_uuids(result)
                    context["storage_map"] = self._extract_storage_map(result)

                elif step.agent == "sql":
                    uuids = context.get("uuids", [])
                    storage_map = context.get("storage_map", {})
                    result = await self._run_sql(state, plan.user_query, uuids, storage_map, step.params)
                    context["sql_result"] = result

                elif step.agent == "analytics":
                    result = await self._run_analytics(state, plan.user_query, context)
                    context["analytics_result"] = result

                elif step.agent == "anomaly":
                    result = await self._run_anomaly(state, plan.user_query, context)
                    context["anomaly_result"] = result

                elif step.agent == "report":
                    result = await self._run_report(state, plan.user_query, context, step.params)
                    context["report_result"] = result

                elif step.agent == "export":
                    result = await self._run_export(context, step.params)
                    context["export_result"] = result

                step.result = result
                step.success = True
                provenance.append(f"Step {step.index} [{step.agent}]: ✅ {step.description}")

            except Exception as e:
                step.error = str(e)
                step.success = False
                logger.warning(f"  Step {step.index} failed: {e}")
                provenance.append(f"Step {step.index} [{step.agent}]: ❌ {e}")
                # Continue with remaining steps if possible

        return self._assemble_result(plan, context, provenance)

    def _assemble_result(
        self, plan: ExecutionPlan, context: Dict, provenance: List[str]
    ) -> Dict[str, Any]:
        """Build final response from accumulated context."""
        # Prefer report > analytics > sql > sparql for the formatted response
        for key in ["report_result", "analytics_result", "export_result", "sql_result", "sparql_result"]:
            if key in context:
                r = context[key]
                if isinstance(r, dict) and r.get("success"):
                    return {
                        "success": True,
                        "formatted_response": r.get("formatted_text") or r.get("formatted_response") or str(r),
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
    # Agent delegates
    # ------------------------------------------------------------------

    async def _run_sparql(self, state: ConversationState, query: str, params: Dict) -> Dict:
        from orchestrator.agents.sparql_agent import SPARQLAgent
        return await SPARQLAgent().generate_query(state, query)

    async def _run_sql(self, state: ConversationState, query: str,
                       uuids: List, storage_map: Dict, params: Dict) -> Dict:
        from orchestrator.agents.sql_agent import SQLAgent
        if uuids:
            return await SQLAgent().fetch_data_for_uuids(uuids, query, storage_map)
        return await SQLAgent().generate_and_execute(state, query)

    async def _run_analytics(self, state: ConversationState, query: str, ctx: Dict) -> Dict:
        from orchestrator.agents.analytics_agent import AnalyticsAgent
        sql_result = ctx.get("sql_result", {})
        return await AnalyticsAgent().analyze(state, query, data=sql_result)

    async def _run_anomaly(self, state: ConversationState, query: str, ctx: Dict) -> Dict:
        from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent
        sql_result = ctx.get("sql_result", {})
        return await AnomalyDetectionAgent().detect(state, query, sensor_data=sql_result)

    async def _run_report(self, state: ConversationState, query: str,
                          ctx: Dict, params: Dict) -> Dict:
        from orchestrator.agents.report_agent import ReportAgent
        return await ReportAgent().generate(
            state, query,
            sensor_data=ctx.get("sql_result"),
            metadata=ctx.get("sparql_result"),
            export_format=params.get("export_format"),
        )

    async def _run_export(self, ctx: Dict, params: Dict) -> Dict:
        from orchestrator.agents.data_export_agent import DataExportAgent
        data = (ctx.get("sql_result") or ctx.get("anomaly_result") or
                ctx.get("analytics_result") or {})
        fmt = params.get("format", "json")
        return await DataExportAgent().export(data=data, label="planner_export", fmt=fmt)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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


# Module-level singleton
planner_agent = PlannerAgent()
