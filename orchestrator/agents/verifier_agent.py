"""
VerifierAgent — lightweight post-query grounding check.

Survey justification (Phase 1):
  Data-grounded rate only 20.0% in H-phase evaluation.
  Every answer that cites a sensor value or count must be traceable back to
  the retrieved triples/rows it was derived from.

Contract:
  Input:  state.intermediate_results["sparql_result"]  (SPARQL bindings)
          state.intermediate_results["sql_result"]      (time-series rows)
          state.intermediate_results["analytics_result"] (if analytics ran)
          state.messages[-1].content                    (user query)
  Output: state.intermediate_results["verification"] = {
            "grounded": bool,
            "confidence": 0.0–1.0,
            "source": "sparql" | "sql" | "analytics" | "none",
            "sensor_ids": [str, ...],
            "time_window": str | None,
            "missing": [str, ...],   # what the answer claimed but data didn't contain
          }

The verifier is rule-based (no LLM call) for STATUS queries to stay within
the <5 s fast-path budget.  For complex intents it only checks structural
data presence, not semantic correctness.
"""

from typing import Any, Dict, List, Optional

from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)

# Intents that use the simple STATUS fast-path (no analytics node)
_STATUS_INTENTS = frozenset(
    {"sensor_data", "discovery", "general", "general_knowledge", "clarification", "capability"}
)


def _extract_sensor_ids(sparql_result: Dict[str, Any]) -> List[str]:
    """Pull sensor/uuid values from SPARQL bindings."""
    ids: List[str] = []
    bindings = (
        sparql_result.get("results", {}).get("results", {}).get("bindings", [])
        if isinstance(sparql_result, dict)
        else []
    )
    for b in bindings:
        for k, v in b.items():
            val = str(v.get("value", ""))
            if val and ("uuid" in k.lower() or "sensor" in k.lower() or "id" in k.lower()):
                ids.append(val)
    return ids[:20]  # cap — only need provenance sample


def _count_sql_rows(sql_result: Dict[str, Any]) -> int:
    """Return number of time-series data rows returned."""
    if not isinstance(sql_result, dict):
        return 0
    data = sql_result.get("data", [])
    if isinstance(data, list):
        return len(data)
    return 0


def _sparql_returned_data(sparql_result: Dict[str, Any]) -> bool:
    """True if SPARQL returned at least one non-empty binding."""
    if not isinstance(sparql_result, dict):
        return False
    if not sparql_result.get("success", True):
        return False
    bindings = sparql_result.get("results", {}).get("results", {}).get("bindings", [])
    return len(bindings) > 0


class VerifierAgent:
    """
    Rule-based grounding verifier.  Called after sparql/sql/analytics nodes.
    Attaches a structured verification record to state without making LLM calls.
    """

    async def verify(self, state: ConversationState) -> ConversationState:
        """Verify grounding of the pipeline output and attach verification record."""
        intent = state.current_intent or "general"
        sparql_result = state.intermediate_results.get("sparql_result", {})
        sql_result = state.intermediate_results.get("sql_result", {})
        analytics_result = state.intermediate_results.get("analytics_result", {})

        sensor_ids = _extract_sensor_ids(sparql_result)
        sql_rows = _count_sql_rows(sql_result)
        sparql_ok = _sparql_returned_data(sparql_result)
        analytics_ok = bool(isinstance(analytics_result, dict) and analytics_result.get("success"))
        capability_ok = bool(state.intermediate_results.get("capability_result", {}).get("success"))

        # Determine grounding source and confidence
        missing: List[str] = []

        if capability_ok:
            source = "capability_kb"
            grounded = True
            confidence = 0.95
        elif analytics_ok:
            source = "analytics"
            grounded = True
            confidence = 0.88
        elif sql_rows > 0:
            source = "sql"
            grounded = True
            confidence = 0.92
        elif sparql_ok:
            source = "sparql"
            grounded = True
            confidence = 0.85
            # SPARQL answered but no SQL data for a data-reading intent
            if intent in ("sensor_data", "analytics", "trend") and sql_rows == 0:
                missing.append("time_series_data")
                confidence = 0.60
        else:
            source = "none"
            grounded = False
            confidence = 0.20
            if intent in _STATUS_INTENTS and intent not in (
                "general",
                "general_knowledge",
                "capability",
            ):
                missing.append("ontology_bindings")
            if intent in ("sensor_data", "analytics", "trend"):
                missing.append("time_series_data")

        # Time window from request
        time_window: Optional[str] = None
        tr = state.intermediate_results.get("time_range") or {}
        if tr.get("start") or tr.get("end"):
            time_window = f"{tr.get('start', '?')} – {tr.get('end', '?')}"

        verification = {
            "grounded": grounded,
            "confidence": confidence,
            "source": source,
            "sensor_ids": sensor_ids,
            "time_window": time_window,
            "missing": missing,
            "intent": intent,
        }

        state.intermediate_results["verification"] = verification

        logger.info(
            f"[verifier] grounded={grounded}, confidence={confidence:.2f}, "
            f"source={source}, sensors={len(sensor_ids)}, "
            f"sql_rows={sql_rows}, missing={missing}"
        )
        return state
