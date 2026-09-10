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

#: Intents this verifier can actually ASSESS, because their evidence flows through one of
#: the four buses it reads (sparql / sql / analytics / capability).
#:
#: Everything else -- floor_plan, spatial_query, register, events, deliberate, asset_state,
#: observability, diagnosis, control, the report-intake family -- answers from a bus this
#: module never opens. For those the ``else`` branch below produced
#: ``source="none", grounded=False, confidence=0.20``, which reads as "I checked and found
#: no support" when the truth is "I was not looking". Those are different facts, and
#: collapsing them is the same error the review names on p. 8 about absence.
#:
#: It matters now because V12-03 made ``grounded`` decide PUBLICATION. Gating on a flag
#: that means "not my lane" would withhold every register, floor-plan and deliberation
#: answer in the system. The ``applicable`` field below is what the publication gate reads.
_ASSESSABLE_INTENTS = frozenset(
    {
        "sensor_data",
        "analytics",
        "compare",
        "trend",
        "metadata",
        "discovery",
        "recommend",
        "anomaly",
        "compliance",
        "capability",
    }
)

#: `report` and `export` are DELIBERATELY ABSENT, and it costs us something to leave them
#: out, so the reason is written down rather than implied.
#:
#: Both route via `planner`, and `PlannerAgent._execute_step` writes every result it
#: produces -- `sparql_result`, `sql_result`, `analytics_result`, `report_result`,
#: `export_result` -- into a LOCAL `context` dict that is never merged into
#: `state.intermediate_results`. Only `planner_result` reaches the bus. Measured live on
#: 2026-09-10: a report built from real rows verified as
#: `sensors=0, sql_rows=0, report_rows=0` -- the verifier was not looking at a stale bus,
#: it was looking at an empty one (BUG-509).
#:
#: Claiming to assess them anyway is what broke reports: the gate withheld a good answer
#: because "no evidence visible" was reported as "no evidence exists". Until the planner's
#: context reaches the bus, the honest statement is that this verifier cannot assess a
#: planner-routed turn -- which means **R1 remains open for the report lane, which is
#: exactly where BUG-475 happened**. That gap is real and is tracked, not hidden.


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
    """Number of time-series rows, in whichever shape the SQL lane produced (BUG-508).

    This read ``sql_result["data"]`` only -- ONE LEVEL TOO SHALLOW. The sql node writes its
    rows at ``["results"]["data"]``, so this returned 0 on every turn where SQL actually
    returned data, and the verifier concluded ``source="none", grounded=False,
    confidence=0.20`` for answers built from thousands of real rows.

    That is BUG-477 exactly, one layer up: the report agent read the same dict one level
    too shallow and "has never once seen the data either caller fetched". The same mistake
    sat in the component whose whole job is to decide whether an answer is grounded -- and
    it is why BUG-475's report carried ``sql_rows=0`` beside a log line reading "Query
    returned 1000 rows", and went out anyway.

    BOTH shapes are read rather than the nested one alone, for the reason ``_records_from``
    gives: the unwrapped form is what a direct caller and the tests pass, and narrowing to
    a single accepted shape is how a working caller gets broken silently.
    """
    if not isinstance(sql_result, dict):
        return 0
    for candidate in (
        sql_result.get("data"),
        (sql_result.get("results") or {}).get("data")
        if isinstance(sql_result.get("results"), dict)
        else None,
        sql_result.get("results") if isinstance(sql_result.get("results"), list) else None,
    ):
        if isinstance(candidate, list) and candidate:
            return len(candidate)
    return 0


def _count_report_rows(report_result: Any) -> int:
    """How many records the REPORT lane built its figures on (BUG-508).

    The report intent routes via ``planner``, which runs the report itself and writes only
    ``report_result``; ``sql_result`` never reaches the bus on that path. So the verifier,
    which reads four buses and none of them this one, saw nothing for every report ever
    generated and concluded ``grounded=False`` -- while the report agent had already
    counted its own rows into ``sections.overview.data_points``.

    That is the number to trust: it is what the narration was actually built from, which
    is a closer question than "did some SQL somewhere return rows".
    """
    if not isinstance(report_result, dict):
        return 0
    sections = report_result.get("sections")
    if not isinstance(sections, dict):
        return 0
    overview = sections.get("overview")
    if not isinstance(overview, dict):
        return 0
    try:
        return int(overview.get("data_points") or 0)
    except (TypeError, ValueError):
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
        # The report lane routes via `planner` and writes only `report_result`; its rows
        # never reach `sql_result`. Reading its own record count is the only way this
        # verifier can assess a report at all (BUG-508).
        report_rows = _count_report_rows(state.intermediate_results.get("report_result"))

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
        elif report_rows > 0:
            # A report narrating N real records is grounded in them, even though the rows
            # arrived by a path this module cannot otherwise see.
            source = "report"
            grounded = True
            confidence = 0.85
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
            # Whether this verifier could assess this lane AT ALL. False means "not my
            # lane", which is NOT the same as "unsupported" -- see _ASSESSABLE_INTENTS.
            # The publication gate refuses to act unless this is True, because withholding
            # an answer on the strength of a check that never ran would be the same class
            # of error as publishing one whose check failed.
            "applicable": intent in _ASSESSABLE_INTENTS,
        }

        state.intermediate_results["verification"] = verification

        logger.info(
            f"[verifier] grounded={grounded}, confidence={confidence:.2f}, "
            f"source={source}, sensors={len(sensor_ids)}, "
            f"sql_rows={sql_rows}, report_rows={report_rows}, missing={missing}"
        )
        return state
