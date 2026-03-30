"""
Multi-Hop Reasoning Engine — CAP-07
=====================================
Decomposes complex, cross-entity questions into sequential sub-queries and
synthesises the results into a coherent answer.

This handles the top ~15% of queries that current straight LangGraph routing
fails to answer correctly — typically questions that require:
  - Discovering entities (which sensors/zones/floors exist?) → SPARQL
  - Fetching per-entity data in parallel → SQL
  - Aggregating and ranking → Analytics
  - Synthesising the ranked result into a natural language answer → LLM

Example queries handled:
  "Which floor has the highest average CO2 this week?"
  "Compare energy consumption per zone for the last 30 days"
  "Which sensor has had the most anomalies in the past month?"
  "What is the relationship between CO2 and occupancy across zones?"

Usage:
    from orchestrator.services.reasoning_engine import ReasoningEngine

    engine = ReasoningEngine()
    result = await engine.reason(state, user_query)
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Query plan data structures
# ─────────────────────────────────────────────────────────────────────────────

class QueryStep:
    """A single step in a multi-hop query plan."""

    def __init__(
        self,
        step_id: str,
        step_type: str,   # "sparql", "sql", "analytics", "synthesise"
        query: str,
        depends_on: List[str] = None,
        description: str = "",
    ):
        self.step_id = step_id
        self.step_type = step_type
        self.query = query
        self.depends_on = depends_on or []
        self.description = description
        self.result: Optional[Any] = None
        self.error: Optional[str] = None
        self.success: bool = False


class QueryPlan:
    """Ordered list of QuerySteps forming a multi-hop reasoning plan."""

    def __init__(self, user_query: str, steps: List[QueryStep]):
        self.user_query = user_query
        self.steps = steps

    @property
    def step_count(self) -> int:
        return len(self.steps)


# ─────────────────────────────────────────────────────────────────────────────
# Reasoning Engine
# ─────────────────────────────────────────────────────────────────────────────

class ReasoningEngine:
    """
    Decomposes complex multi-hop building queries into executable sub-plans
    and synthesises results.

    The engine works in 3 phases:
      1. Plan  — LLM decomposes the user query into ordered sub-queries
      2. Execute — sub-queries run (SPARQL → SQL → analytics)
      3. Synthesise — results combined into final answer
    """

    # Multi-hop trigger patterns
    _MULTI_HOP_PATTERNS = [
        r"\bwhich\s+(floor|zone|room|sensor|building)\s+has\s+the\s+(highest|lowest|most|least)\b",
        r"\bcompare\b.{5,50}\b(per|across|between|for each)\b",
        r"\b(rank|sort|order)\b.{5,50}\b(floor|zone|room|sensor)\b",
        r"\brelationship\b.{5,50}\bco2|temp|energy|humidity\b",
        r"\bhow\s+does\b.{5,50}\bcompare\b",
        r"\bfor\s+each\s+(floor|zone|room|building)\b",
    ]

    def __init__(self, max_hop_steps: int = 4):
        self.max_hop_steps = max_hop_steps
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self._MULTI_HOP_PATTERNS]

    def is_multi_hop(self, user_query: str) -> bool:
        """Check if the query is a multi-hop reasoning candidate."""
        return any(p.search(user_query) for p in self._compiled)

    async def reason(
        self,
        state,
        user_query: str,
        llm_manager=None,
    ) -> Dict[str, Any]:
        """
        Execute a multi-hop reasoning plan for the given query.

        Args:
            state:       ConversationState (for context)
            user_query:  The user's question
            llm_manager: LLM manager for planning and synthesis

        Returns:
            Dict with success, formatted_response, plan_steps, sub_results
        """
        try:
            logger.info(f"ReasoningEngine: starting multi-hop for: {user_query[:80]}")

            # Step 1: Generate query plan using LLM
            plan = await self._plan(user_query, llm_manager)
            if not plan or not plan.steps:
                return {
                    "success": False,
                    "error": "Could not generate a reasoning plan",
                    "formatted_response": "I had difficulty planning how to answer this multi-step question. Please try breaking it into simpler parts.",
                }

            logger.info(f"ReasoningEngine: plan has {plan.step_count} steps")

            # Step 2: Execute each step
            context: Dict[str, Any] = {}
            for step in plan.steps:
                result = await self._execute_step(step, context, state, llm_manager)
                step.result = result
                step.success = result.get("success", False)
                context[step.step_id] = result
                logger.info(f"ReasoningEngine: step {step.step_id} ({step.step_type}) success={step.success}")

            # Step 3: Synthesise
            synthesis = await self._synthesise(plan, context, user_query, llm_manager)

            return {
                "success": True,
                "formatted_response": synthesis,
                "plan_steps": [
                    {
                        "step_id": s.step_id,
                        "type": s.step_type,
                        "description": s.description,
                        "success": s.success,
                    }
                    for s in plan.steps
                ],
                "sub_results": {s.step_id: s.result for s in plan.steps},
                "multi_hop": True,
            }

        except Exception as e:
            logger.error(f"ReasoningEngine: reasoning failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "formatted_response": f"Multi-hop reasoning failed: {str(e)[:100]}. Please try rephrasing.",
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: Plan
    # ─────────────────────────────────────────────────────────────────────────

    async def _plan(self, user_query: str, llm_manager) -> Optional[QueryPlan]:
        """Ask the LLM to decompose the query into a step plan."""
        if not llm_manager:
            logger.warning("ReasoningEngine: no llm_manager — using fallback 2-step plan")
            return self._fallback_plan(user_query)

        plan_prompt = f"""You are an expert at decomposing complex smart building questions into
step-by-step data retrieval plans.

Building ontology: Brick Schema + REC, namespace prefix '{settings.BUILDING_PREFIX}:'
Building name: {settings.BUILDING_NAME}

USER QUESTION: {user_query}

Decompose this into at most {self.max_hop_steps} ordered steps. Each step must be one of:
- "discover_sparql": SPARQL to find entities (sensors, zones, floors)
- "fetch_sql": SQL to get time-series readings for discovered entities
- "aggregate": Python aggregation logic (avg, max, rank) on fetched data
- "synthesise": Combine all results into a final answer (always last step)

Return JSON array:
[
  {{"step_id": "step1", "type": "discover_sparql", "description": "what this step does", "query_intent": "concise SPARQL goal"}},
  {{"step_id": "step2", "type": "fetch_sql",       "description": "what this step does", "query_intent": "concise SQL goal", "depends_on": ["step1"]}},
  {{"step_id": "step3", "type": "aggregate",        "description": "ranking logic"}},
  {{"step_id": "step4", "type": "synthesise",       "description": "combine and explain"}}
]

Return ONLY the JSON array."""

        try:
            import json
            response = await llm_manager.generate(plan_prompt)
            json_match = re.search(r'\[[\s\S]*\]', response)
            if not json_match:
                return self._fallback_plan(user_query)

            raw_steps = json.loads(json_match.group(0))
            steps = []
            for s in raw_steps[:self.max_hop_steps + 1]:
                steps.append(QueryStep(
                    step_id=s.get("step_id", f"step{len(steps)+1}"),
                    step_type=s.get("type", "sparql"),
                    query=s.get("query_intent", ""),
                    depends_on=s.get("depends_on", []),
                    description=s.get("description", ""),
                ))
            return QueryPlan(user_query, steps)

        except Exception as e:
            logger.warning(f"ReasoningEngine: plan LLM call failed ({e}), using fallback")
            return self._fallback_plan(user_query)

    def _fallback_plan(self, user_query: str) -> QueryPlan:
        """Minimal 2-step fallback: SPARQL discovery + LLM synthesis."""
        steps = [
            QueryStep("step1", "discover_sparql",
                      "List sensors with their zones and UUIDs",
                      description="Discover available sensor entities"),
            QueryStep("step2", "synthesise",
                      user_query,
                      depends_on=["step1"],
                      description="Synthesise available data into answer"),
        ]
        return QueryPlan(user_query, steps)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: Execute
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_step(
        self,
        step: QueryStep,
        context: Dict,
        state,
        llm_manager,
    ) -> Dict[str, Any]:
        """Execute a single plan step."""
        try:
            if step.step_type in ("discover_sparql", "sparql"):
                return await self._run_sparql_step(step, context, state, llm_manager)
            elif step.step_type in ("fetch_sql", "sql"):
                return await self._run_sql_step(step, context, state, llm_manager)
            elif step.step_type == "aggregate":
                return self._run_aggregate_step(step, context)
            elif step.step_type == "synthesise":
                return {"success": True, "data": context, "type": "synthesise"}
            else:
                return {"success": False, "error": f"Unknown step type: {step.step_type}"}
        except Exception as e:
            logger.error(f"ReasoningEngine: step {step.step_id} failed: {e}")
            return {"success": False, "error": str(e)}

    async def _run_sparql_step(self, step, context, state, llm_manager) -> Dict:
        """Run a SPARQL discovery step using the SPARQL agent."""
        try:
            from orchestrator.agents.sparql_agent import SPARQLAgent
            agent = SPARQLAgent()
            result = await agent.generate_query(state, step.query or step.description)
            return {"success": result.get("success", False), "type": "sparql", "data": result}
        except Exception as e:
            return {"success": False, "error": str(e), "type": "sparql"}

    async def _run_sql_step(self, step, context, state, llm_manager) -> Dict:
        """Run a SQL data fetch step."""
        try:
            # Get UUIDs from prior SPARQL step if available
            prior = next((v for v in context.values() if v.get("type") == "sparql" and v.get("success")), {})
            sparql_data = prior.get("data", {})

            from orchestrator.agents.sql_agent import SQLAgent
            agent = SQLAgent()
            result = await agent.generate_and_execute(
                state,
                step.query or step.description,
                sparql_results=sparql_data.get("standardized", []),
            )
            return {"success": result.get("success", False), "type": "sql", "data": result}
        except Exception as e:
            return {"success": False, "error": str(e), "type": "sql"}

    def _run_aggregate_step(self, step, context) -> Dict:
        """Aggregate data from prior steps (rank, sort, etc.)."""
        try:
            # Gather all sql result data
            all_rows = []
            for v in context.values():
                if v.get("type") == "sql" and v.get("success"):
                    all_rows.extend(v.get("data", {}).get("data", []))

            if not all_rows:
                return {"success": False, "error": "No SQL data to aggregate", "data": []}

            # Simple aggregation: group by entity, compute mean value
            from collections import defaultdict
            groups: Dict[str, List[float]] = defaultdict(list)
            for row in all_rows:
                uuid = str(row.get("uuid", row.get("entity", "unknown")))
                try:
                    groups[uuid].append(float(row.get("value", 0)))
                except (TypeError, ValueError):
                    pass

            import statistics
            aggregated = [
                {
                    "entity": k,
                    "count": len(v),
                    "mean": round(statistics.mean(v), 2) if v else None,
                    "max": round(max(v), 2) if v else None,
                    "min": round(min(v), 2) if v else None,
                }
                for k, v in groups.items()
                if v
            ]
            aggregated.sort(key=lambda x: x.get("mean", 0) or 0, reverse=True)

            return {"success": True, "type": "aggregate", "data": aggregated}
        except Exception as e:
            return {"success": False, "error": str(e), "type": "aggregate"}

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3: Synthesise
    # ─────────────────────────────────────────────────────────────────────────

    async def _synthesise(
        self,
        plan: QueryPlan,
        context: Dict,
        user_query: str,
        llm_manager,
    ) -> str:
        """Synthesise all step results into a final response."""
        if not llm_manager:
            # Fallback: dump aggregated data as text
            agg = next((v for v in context.values() if v.get("type") == "aggregate"), {})
            if agg.get("success") and agg.get("data"):
                rows = agg["data"][:5]
                lines = [f"{i+1}. {r['entity']}: mean={r['mean']}" for i, r in enumerate(rows)]
                return "Top results:\n" + "\n".join(lines)
            return "Multi-hop reasoning completed. Please rephrase for more specific results."

        # Prepare summary of all step results
        parts = []
        for step in plan.steps:
            if step.success and step.result:
                r = step.result
                if r.get("type") == "sparql":
                    sparql_data = r.get("data", {})
                    parts.append(f"Step '{step.step_id}' (SPARQL discovery): {sparql_data.get('formatted_response', '')[:300]}")
                elif r.get("type") == "sql":
                    sql_data = r.get("data", {})
                    row_count = len(sql_data.get("data", []))
                    parts.append(f"Step '{step.step_id}' (SQL fetch): Retrieved {row_count} data rows")
                elif r.get("type") == "aggregate":
                    agg_data = r.get("data", [])[:5]
                    ranked = "; ".join(f"{x['entity']}: {x['mean']}" for x in agg_data)
                    parts.append(f"Step '{step.step_id}' (Aggregation - top 5): {ranked}")

        context_text = "\n".join(parts) if parts else "Limited data available."

        synth_prompt = f"""You are an intelligent building data analyst.

Answer the following question using the multi-step query results below.
Be concise, data-driven, and use the exact numbers from the results.

USER QUESTION: {user_query}

MULTI-STEP RESULTS:
{context_text}

Synthesise these results into a clear, direct answer. If ranking was performed, state the winner.
If data is incomplete, acknowledge it and give the best partial answer."""

        try:
            response = await llm_manager.generate(synth_prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"ReasoningEngine: synthesis failed: {e}")
            return f"Multi-hop analysis complete. {context_text[:500]}"


# Module-level singleton
_engine_instance: Optional[ReasoningEngine] = None


def get_reasoning_engine() -> ReasoningEngine:
    """Return the shared ReasoningEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ReasoningEngine()
    return _engine_instance
