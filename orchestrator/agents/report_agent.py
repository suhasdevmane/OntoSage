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

            # Build report sections
            sections = await self._build_sections(
                user_query, report_type, sensor_data or {}, metadata or {}
            )

            # LLM narration
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
    ) -> Dict[str, Any]:
        """Extract structured sections from raw data."""
        records = sensor_data.get("data", []) or []
        sensors = metadata.get("sensors", []) or []

        # Section 1: Overview
        overview = {
            "building": (
                settings.BUILDING_NAME if hasattr(settings, "BUILDING_NAME") else "Smart Building"
            ),
            "report_type": rtype.value,
            "generated_at": datetime.now(ZoneInfo(settings.BUILDING_TIMEZONE)).isoformat(),
            "sensor_count": len(sensors),
            "data_points": len(records),
        }

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

    async def _narrate(self, query: str, rtype: ReportType, sections: Dict) -> str:
        """LLM narration of the report findings."""
        prompt = f"""Generate a concise building management {rtype.value} report based on the following data.

User Request: "{query}"

Findings:
{json.dumps(sections, indent=2, default=str)[:3000]}

Write a professional, structured report with:
1. Executive Summary (2-3 sentences)
2. Key Findings (bullet points from highlights)
3. Anomalies / Concerns (if any)
4. Recommendations (2-3 actionable items)

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
