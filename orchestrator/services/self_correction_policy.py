"""
SelfCorrectionPolicy — unified repair interface for all data nodes.

Survey justification (Phase 2 / Thesis Contribution):
  G4 "Future work hooks" calls for a closed-loop feedback log.
  Self-correction is the headline research methodology: the system repairs
  its own failures without user intervention.

  SPARQL already has a 4-strategy repair engine (self_correction_engine.py).
  Analytics already has a code-repair loop in analytics_agent.py.
  SQL has NO repair loop — this module adds that gap.

Contract:
  Each data node that wants repair calls:
      trace = await self_correction_policy.repair(node_name, state, attempt_fn)

  Where attempt_fn is an async callable that takes state and returns state.
  The policy wraps it with bounded retry (MAX_ATTEMPTS=2 re-tries = 3 total),
  logs a structured correction_trace, and returns the final state.

Emits per-query: state.intermediate_results["correction_trace"] = [
    {
      "node": str,          # "sparql" | "sql" | "analytics"
      "attempt": int,       # 1-based
      "strategy": str,      # what was tried
      "success": bool,
      "error": str | None,
      "query_before": str | None,
      "query_after": str | None,
      "confidence_before": float | None,
      "confidence_after": float | None,
    },
    ...
]
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 2  # re-tries; total = MAX_ATTEMPTS + 1 original attempt


class SelfCorrectionPolicy:
    """
    Bounded reflexion policy shared by sparql, sql, and analytics nodes.
    Each node registers its own repair callable; this class runs the loop
    and emits the correction_trace.
    """

    async def repair(
        self,
        node_name: str,
        state: ConversationState,
        attempt_fn: Callable[[ConversationState, int, Optional[str]], Any],
        success_fn: Callable[[ConversationState], bool],
        error_fn: Callable[[ConversationState], Optional[str]],
        strategy_name: str = "llm_repair",
    ) -> ConversationState:
        """
        Run attempt_fn up to MAX_ATTEMPTS+1 times, stopping on first success.

        attempt_fn(state, attempt_number, last_error) -> state
        success_fn(state) -> bool  (was the last attempt successful?)
        error_fn(state) -> str | None  (extract error message from state)
        """
        traces: List[Dict[str, Any]] = state.intermediate_results.get(
            "correction_trace", []
        )
        last_error: Optional[str] = None

        for attempt in range(1, MAX_ATTEMPTS + 2):  # 1, 2, 3
            strategy = "original" if attempt == 1 else strategy_name
            try:
                state = await attempt_fn(state, attempt, last_error)
            except Exception as exc:
                logger.warning(
                    f"[self_correction] {node_name} attempt {attempt} raised: {exc}"
                )
                last_error = str(exc)
                traces.append(
                    {
                        "node": node_name,
                        "attempt": attempt,
                        "strategy": strategy,
                        "success": False,
                        "error": last_error,
                    }
                )
                state.intermediate_results["correction_trace"] = traces
                continue

            succeeded = success_fn(state)
            current_error = error_fn(state) if not succeeded else None

            traces.append(
                {
                    "node": node_name,
                    "attempt": attempt,
                    "strategy": strategy,
                    "success": succeeded,
                    "error": current_error,
                }
            )
            state.intermediate_results["correction_trace"] = traces

            if succeeded:
                if attempt > 1:
                    logger.info(
                        f"[self_correction] {node_name} recovered on attempt {attempt} "
                        f"via {strategy}"
                    )
                break

            last_error = current_error
            logger.info(
                f"[self_correction] {node_name} attempt {attempt} failed "
                f"(error={current_error!r}); "
                + (f"retrying with {strategy_name}" if attempt <= MAX_ATTEMPTS else "giving up")
            )

        return state


# Module-level singleton — imported by sql_agent and analytics_agent
self_correction_policy = SelfCorrectionPolicy()
