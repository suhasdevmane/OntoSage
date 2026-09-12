"""
ReportAgent — Phase 4.2 & 4.6 (Report Generation & Document Generation Pipeline)
===================================================================================
Generates structured building management reports from SPARQL + SQL data.

Supports:
  - Summary reports (daily/weekly overview of sensor readings)
  - Anomaly reports (highlight out-of-range values)
  - Comparison reports (multi-zone, multi-period)
  - Full PDF/HTML/JSON export via DataExportAgent

Usage:
    from orchestrator.agents.report_agent import ReportAgent
    agent = ReportAgent()
    result = await agent.generate(state, user_query, sensor_data)
"""

import sys

sys.path.append("/app")

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from orchestrator.llm_manager import llm_manager
from shared.config import settings
from shared.constants import COMFORT_RANGES as _SHARED_COMFORT_RANGES
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)


class ReportType(str, Enum):
    SUMMARY = "summary"  # General overview
    ANOMALY = "anomaly"  # Out-of-range highlights
    COMPARISON = "comparison"  # Cross-zone or cross-period
    TREND = "trend"  # Time-series evolution
    FULL = "full"  # Complete building report


def _records_from(sensor_data: Any) -> List[Dict]:
    """The rows in a SQL lane result, whichever wrapper the caller passed (BUG-477).

    Both callers hand this agent the WHOLE `sql_result` — `_run_report` in the planner and
    the report node in the workflow — and that dict carries its rows at
    `["results"]["data"]`. This module read `sensor_data.get("data")`, one level too
    shallow, so it found nothing every time and the report agent has never once seen the
    data either caller fetched.

    Measured: the planner logged "Fetching data for 1 UUIDs" and "Query returned 1000
    rows", and the report built from those 1,000 rows said no data was retrieved.

    Reading both shapes rather than picking one: the unwrapped form is what a direct
    caller and the tests pass, and narrowing to a single accepted shape is how a working
    caller gets broken silently — which is this bug.
    """
    if isinstance(sensor_data, list):
        return sensor_data
    if not isinstance(sensor_data, dict):
        return []
    direct = sensor_data.get("data")
    if isinstance(direct, list):
        return direct
    inner = sensor_data.get("results")
    if isinstance(inner, list):
        return inner
    if isinstance(inner, dict) and isinstance(inner.get("data"), list):
        return inner["data"]
    return []


def _is_capped(sensor_data: Any) -> bool:
    """Did the SQL lane stop at its row limit (BUG-479)?

    Read from the flag the fetch sets rather than re-derived here: comparing a length to a
    literal 1000 in a second file is exactly how the cap and the check that detects it
    drift apart. Absent flag means "not known to be capped" — the honest default for a
    direct caller or an older result, since claiming truncation that did not happen is its
    own false statement.
    """
    if not isinstance(sensor_data, dict):
        return False
    if "rows_capped" in sensor_data:
        return bool(sensor_data["rows_capped"])
    inner = sensor_data.get("results")
    if isinstance(inner, dict) and "rows_capped" in inner:
        return bool(inner["rows_capped"])
    return False


def _sensors_from(metadata: Any) -> List:
    """The sensors behind a report, from a SPARQL lane result or a plain metadata dict.

    Same mismatch as `_records_from`: the callers pass the whole `sparql_result`, which
    holds its rows under `["standardized"]["results"]` and has no `sensors` key at all —
    so `sensor_count` was 0 on every report ever generated.
    """
    if isinstance(metadata, list):
        return metadata
    if not isinstance(metadata, dict):
        return []
    direct = metadata.get("sensors")
    if isinstance(direct, list):
        return direct
    std = metadata.get("standardized")
    if isinstance(std, dict) and isinstance(std.get("results"), list):
        return std["results"]
    return []


def _detect_report_type(query: str) -> ReportType:
    q = query.lower()
    if any(w in q for w in ["anomal", "spike", "unusual", "alert", "out of range"]):
        return ReportType.ANOMALY
    if any(w in q for w in ["compare", "versus", "vs ", "differ", "across"]):
        return ReportType.COMPARISON
    if any(w in q for w in ["trend", "over time", "historica", "evolution"]):
        return ReportType.TREND
    if any(w in q for w in ["full report", "comprehensive", "complete"]):
        return ReportType.FULL
    return ReportType.SUMMARY


class ReportAgent:
    """
    Phase 4.2 + 4.6: Structured building report generator.

    Pipeline:
      1. Classify report type
      2. Structure data into sections (metadata, readings, highlights, recommendations)
      3. LLM narration per section
      4. Assemble final report (dict + formatted text)
      5. Hand off to DataExportAgent for file export if requested
    """

    # Comfort/safe ranges per sensor type — sourced from shared/constants.py
    COMFORT_RANGES = _SHARED_COMFORT_RANGES

    async def generate(
        self,
        state: ConversationState,
        user_query: str,
        sensor_data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        export_format: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point. Returns a structured report dict + formatted text.

        Args:
            state:         Conversation state
            user_query:    User's report request
            sensor_data:   Time-series data from SQL agent
            metadata:      Sensor metadata from SPARQL agent
            export_format: Optional — 'json', 'csv', 'html', 'markdown'
        """
        try:
            logger.info("=" * 70)
            logger.info("📋 REPORT AGENT: Generating Report")
            logger.info("=" * 70)

            report_type = _detect_report_type(user_query)
            logger.info(f"Report type: {report_type.value}")

            # Build report sections.  Phase 10 — pass building_id so the
            # report uses the right per-building name/timezone.
            sections = await self._build_sections(
                user_query,
                report_type,
                sensor_data or {},
                metadata or {},
                building_id=getattr(state, "building_id", None),
            )

            # What the narration will be given, so a figure in the prose can be checked
            # against the figure that was computed. Without this the only way to tell an
            # arithmetic error from an invented number is to re-derive both by hand.
            logger.info(
                "[report] computed sections: points=%s sensors=%s readings=%s",
                sections.get("overview", {}).get("data_points"),
                sections.get("overview", {}).get("sensor_count"),
                json.dumps(sections.get("readings_summary", {}), default=str)[:400],
            )

            # NOTHING RETRIEVED IS NOT A FINDING ABOUT THE BUILDING.
            #
            # Measured live 2026-09-07. "Give me a report on the CO2 in room 5.01
            # yesterday" produced a query with `WHERE uuid = '5.01'` — the ROOM NUMBER as
            # a sensor id — which matched nothing. `_narrate` was then handed
            # `data_points: 0` and asked for "Recommendations (2-3 actionable items)", and
            # returned:
            #
            #     "No CO2 sensor was active or present in Room 5.01 during the reporting
            #      period ... Data Void: a critical monitoring gap ... Potential System
            #      Failure ... Verify Sensor Installation ... Deploy a secondary CO2
            #      monitoring device"
            #
            # `co2_data` held 77,088 rows for that day. The system turned its own query
            # error into a confident claim about the building's hardware, plus a
            # recommendation to buy more of it. The verifier had already scored the turn
            # `grounded=False, source=none, sql_rows=0` and the report went out anyway.
            #
            # So an empty retrieval is stated and NOT explained. Whether the rows are
            # absent because nothing happened, because the sensor does not exist, or
            # because the query was wrong is not knowable from a row count — and only the
            # graph can answer the second. Narrating here is guessing with a house style.
            if not (sections.get("overview", {}).get("data_points") or 0):
                narrative = self._no_data_narrative(user_query, sections)
                logger.info("[report] no rows retrieved — reporting that, not explaining it")
            else:
                narrative = await self._narrate(user_query, report_type, sections)

            # Assemble
            report = self._assemble_report(report_type, sections, narrative)

            # Optional export — PDF/DOCX via DocumentBuilder, others via DataExportAgent
            export_result = None
            if export_format:
                fmt_lower = (export_format or "").lower().strip()
                if fmt_lower in ("pdf", "docx", "html"):
                    from orchestrator.services.document_builder import DocumentBuilder

                    builder = DocumentBuilder()
                    persona = getattr(state, "persona", "general") or "general"
                    doc_data = {
                        "narrative": narrative,
                        "readings_summary": sections.get("readings_summary", {}),
                        "anomalies": sections.get("anomalies", []),
                        "highlights": sections.get("highlights", []),
                    }
                    doc_result = builder.render(
                        report_data=doc_data,
                        report_type=report_type.value,
                        persona=persona,
                        output_format=fmt_lower,
                        title=f"{report_type.value.title()} Report — {sections['overview']['building']}",
                    )
                    if doc_result.get("success"):
                        download_url = builder.save_to_exports(doc_result)
                        doc_result["download_url"] = download_url
                    export_result = doc_result
                else:
                    from orchestrator.agents.data_export_agent import DataExportAgent

                    export_agent = DataExportAgent()
                    export_result = await export_agent.export(
                        data=report["sections_data"],
                        label=f"report_{report_type.value}",
                        fmt=export_format,
                    )
                report["export"] = export_result

            logger.info(f"✅ Report generated: {len(report['formatted_text'])} chars")
            return report

        except Exception as e:
            logger.error(f"ReportAgent failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "formatted_text": f"I encountered an error generating the report: {e}",
            }

    async def _build_sections(
        self,
        query: str,
        rtype: ReportType,
        sensor_data: Dict,
        metadata: Dict,
        building_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract structured sections from raw data."""
        records = _records_from(sensor_data)
        sensors = _sensors_from(metadata)

        # Phase 10 — per-request building context: name and timezone come
        # from this conversation's building, not the process-global setting.
        from orchestrator.services.building_context import resolve_building_context

        bctx = resolve_building_context(building_id)

        # Section 1: Overview
        #
        # `data_points` is HOW MANY ROWS WE READ, which is only a count of what the period
        # holds when the query was not cut short. A report said "Room 5.01 recorded 1,000
        # CO2 sensor readings yesterday" against a true 2,770 — 1,000 being the row limit
        # (BUG-479). The statistics over those rows were correct; the sentence was a false
        # claim about the building, and nothing in the sections could have told the
        # narrator otherwise. So the truncation travels WITH the number.
        capped = bool(_is_capped(sensor_data))
        overview = {
            "building": bctx.name,
            "report_type": rtype.value,
            "generated_at": datetime.now(ZoneInfo(bctx.timezone)).isoformat(),
            "sensor_count": len(sensors),
            "data_points": len(records),
            "data_points_are_complete": not capped,
        }
        if capped:
            overview["data_points_note"] = (
                f"{len(records)} is the number of readings ANALYSED, not the number "
                f"recorded: the query stopped at its row limit, so this is the most recent "
                f"slice of the period and the true count is higher."
            )

        # Section 2: Sensor readings summary (min/max/avg per sensor type)
        readings_summary = self._summarize_readings(records)

        # Section 3: Anomalies / out-of-range
        anomalies = self._detect_anomalies(records)

        # Section 4: Top insights
        highlights = self._extract_highlights(readings_summary, anomalies, rtype)

        return {
            "overview": overview,
            "readings_summary": readings_summary,
            "anomalies": anomalies,
            "highlights": highlights,
        }

    def _summarize_readings(self, records: List[Dict]) -> Dict[str, Dict]:
        """Compute min/max/avg per detected column."""
        summary: Dict[str, Dict] = {}
        numeric_fields = set()

        for row in records[:500]:  # cap for performance
            for k, v in row.items():
                if isinstance(v, (int, float)):
                    numeric_fields.add(k)

        for field in numeric_fields:
            vals = [r[field] for r in records if isinstance(r.get(field), (int, float))]
            if vals:
                summary[field] = {
                    "count": len(vals),
                    "min": round(min(vals), 3),
                    "max": round(max(vals), 3),
                    "avg": round(sum(vals) / len(vals), 3),
                    "latest": vals[-1],
                }
        return summary

    def _detect_anomalies(self, records: List[Dict]) -> List[Dict]:
        """Flag readings outside comfort ranges."""
        anomalies = []
        for row in records:
            for col, val in row.items():
                if not isinstance(val, (int, float)):
                    continue
                col_lower = col.lower()
                for sensor_type, bounds in self.COMFORT_RANGES.items():
                    if sensor_type in col_lower:
                        if val < bounds["min"] or val > bounds["max"]:
                            anomalies.append(
                                {
                                    "column": col,
                                    "value": val,
                                    "unit": bounds["unit"],
                                    "threshold": bounds,
                                    "timestamp": row.get("Datetime")
                                    or row.get("timestamp")
                                    or "unknown",
                                    "severity": (
                                        "high"
                                        if (val < bounds["min"] * 0.8 or val > bounds["max"] * 1.2)
                                        else "medium"
                                    ),
                                }
                            )
        return anomalies[:50]  # cap

    def _extract_highlights(self, readings: Dict, anomalies: List, rtype: ReportType) -> List[str]:
        """Bullet-point key findings."""
        highlights = []
        for field, stats in readings.items():
            highlights.append(
                f"• {field}: avg={stats['avg']}, min={stats['min']}, max={stats['max']} ({stats['count']} readings)"
            )
        if anomalies:
            high = sum(1 for a in anomalies if a["severity"] == "high")
            highlights.append(f"• ⚠️ {len(anomalies)} anomalies detected ({high} high-severity)")
        return highlights[:15]

    @staticmethod
    def _no_data_narrative(query: str, sections: Dict) -> str:
        """What a report says when the retrieval came back empty.

        Deterministic on purpose. There is no LLM call here because there is nothing to
        narrate: every sentence a model could add about WHY the rows are missing is a
        guess, and the guess it actually produced was a fabricated monitoring gap with
        hardware recommendations attached.

        It says what happened and stops. It does not say the sensor is missing, that the
        data is not collected, or that anything is wrong with the building — none of which
        a row count can establish.

        V12-05: it now also NAMES which nothing this is, where the lane genuinely knows.
        Refusing to explain was the safe fix; refusing to distinguish is a separate loss.
        Two facts are already in hand — whether any sensor was identified, and that no rows
        came back — and they separate the two states that matter most here:

          * no sensor identified  -> NOT_DECLARED. The building's model has nothing of
            that kind, and saying so is a fact about the model, not a fault.
          * sensors identified, no rows -> SERIES_UNRESOLVED. This is BUG-475's case, and
            the honest statement is that absence was not established — the store cannot
            distinguish a wrong identifier from a quiet period without a series catalogue
            (review C08).

        Still no LLM call, and still no claim the sensor is missing or the building is at
        fault, because neither follows from a row count.
        """
        from orchestrator.services.retrieval_outcome import (
            SeriesResolution,
            classify,
            describe,
        )

        sensor_count = int(sections.get("overview", {}).get("sensor_count") or 0)
        subject = "the sensors for this request" if sensor_count else "a sensor of that kind"
        outcome = classify(
            declared=bool(sensor_count),
            # The report lane has no series catalogue, so resolution is genuinely UNKNOWN
            # and must not be inferred from the empty result.
            series=SeriesResolution.UNKNOWN,
            rows=0,
            subject=subject,
        )

        lines = [
            "**No data was retrieved for this request, so there is no report to give.**",
            "",
            describe(outcome),
            "",
            "That is a statement about this query, not about the building. It does not "
            "mean the sensor is missing, that the readings are not collected, or that "
            "anything is wrong with the monitoring — none of which follows from an empty "
            "result.",
        ]
        if sensor_count:
            lines.append(
                f"\n{sensor_count} sensor(s) were identified for this request but returned "
                f"no rows over the period asked about."
            )
        lines.append(
            '\nTo narrow it down, ask "what sensors are in <the space you mean>?" to see '
            "what is instrumented there, or ask for a different period."
        )
        return "\n".join(lines)

    async def _narrate(self, query: str, rtype: ReportType, sections: Dict) -> str:
        """LLM narration of the report findings."""
        # THE COUNT RULE, STATED — not left for the model to infer from a nested flag.
        #
        # `data_points_note` is already in the findings JSON below, but a note buried in
        # a serialised dict competes with an instruction that says "be specific". The
        # sentence that went out was "Room 5.01 recorded 1,000 CO2 sensor readings
        # yesterday" against a true 2,770 (BUG-479): specific, confident, false.
        counts_rule = (
            "- data_points is HOW MANY READINGS WERE ANALYSED. Say it that way.\n"
            if sections.get("overview", {}).get("data_points_are_complete", True)
            else (
                "- CRITICAL: data_points_are_complete is false. The query stopped at its "
                "row limit, so data_points is the size of the SLICE ANALYSED and NOT how "
                "many readings were recorded. Never write that the room, sensor or "
                "building 'recorded' that many. Say the statistics cover that many "
                "readings and state that the period holds more.\n"
            )
        )
        prompt = f"""Generate a concise building management {rtype.value} report based on the following data.

User Request: "{query}"

Findings:
{json.dumps(sections, indent=2, default=str)[:3000]}

Write a professional, structured report with:
1. Executive Summary (2-3 sentences)
2. Key Findings (bullet points from highlights)
3. Anomalies / Concerns (if any)
4. Recommendations (2-3 actionable items)

Rules about the numbers:
{counts_rule}- Every figure must come from the findings above. Do not estimate or round to a
  friendlier number, and do not introduce a figure that is not there.

Use factual language. Be concise and specific."""
        try:
            return await llm_manager.generate(prompt, temperature=0.2)
        except Exception as e:
            logger.warning(f"Report narration LLM failed: {e}")
            return "\n".join(sections.get("highlights", []))

    def _assemble_report(self, rtype: ReportType, sections: Dict, narrative: str) -> Dict[str, Any]:
        """Package final report."""
        return {
            "success": True,
            "report_type": rtype.value,
            "sections_data": sections,
            "formatted_text": narrative,
            "anomaly_count": len(sections.get("anomalies", [])),
            "generated_at": sections["overview"]["generated_at"],
        }
