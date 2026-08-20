"""
Document Agent — Generate Formal Building Reports (PDF / Word)
==============================================================
Phase CAP-01: Formal document generation pipeline for compliance officers,
executives, auditors, and researchers.

Assembles structured reports from OntoSage pipeline outputs and renders them
using Jinja2 HTML templates → WeasyPrint (PDF) or python-docx (Word).

Supported document types:
  - weekly_summary        : 7-day aggregate KPIs
  - executive_kpi         : High-level metrics for leadership
  - anomaly_digest        : Flagged sensor anomalies with context
  - compliance_report     : Standards-based evidence (BREEAM, WELL, ASHRAE)
  - energy_report         : Energy consumption + carbon + cost breakdown
  - iaq_report            : Indoor Air Quality analysis
  - research_export       : Full data exports with provenance metadata

Usage:
    from orchestrator.agents.document_agent import DocumentAgent
    agent = DocumentAgent()
    result = await agent.generate(state, document_type="compliance_report", format="pdf")
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# Document output directory
DOCS_DIR = Path(os.environ.get("DOCS_OUTPUT_DIR", "/app/outputs/documents"))
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "document_templates"

# Map document types to template filenames
TEMPLATE_MAP: Dict[str, str] = {
    "weekly_summary": "weekly_summary.html",
    "executive_kpi": "executive_kpi.html",
    "anomaly_digest": "anomaly_digest.html",
    "compliance_report": "compliance_report.html",
    "energy_report": "energy_report.html",
    "iaq_report": "base.html",  # fallback to base template
    "research_export": "base.html",
    "summary": "weekly_summary.html",
    "full": "base.html",
    "trend": "weekly_summary.html",
    "comparison": "executive_kpi.html",
}


class DocumentAgent:
    """
    Phase CAP-01: Formal document generation agent.

    Converts pipeline intermediate_results into structured PDF/Word documents
    using Jinja2 templates.
    """

    async def generate(
        self,
        state,
        document_type: str = "summary",
        output_format: str = "pdf",
        title: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a formal document from the current conversation state.

        Args:
            state:          ConversationState with intermediate_results populated
            document_type:  Type of document (see TEMPLATE_MAP keys)
            output_format:  "pdf", "docx", or "html"
            title:          Optional custom document title
            extra_data:     Additional data to inject into the template

        Returns:
            Dict with success, download_url, filename, format, size_bytes
        """
        try:
            logger.info(f"DocumentAgent: generating {document_type} as {output_format}")

            # Assemble context from state
            context = self._build_context(state, document_type, title, extra_data)

            # Resolve template
            template_name = TEMPLATE_MAP.get(document_type, "base.html")

            # Delegate to DocumentBuilder
            from orchestrator.services.document_builder import DocumentBuilder

            builder = DocumentBuilder()

            doc_result = builder.render(
                report_data=context,
                report_type=document_type,
                output_format=output_format,
                title=context.get("title", title or document_type.replace("_", " ").title()),
                template_name=template_name,
            )

            if not doc_result.get("success"):
                return {
                    "success": False,
                    "error": doc_result.get("error", "Document generation failed"),
                    "format": output_format,
                }

            # Save to disk and generate download URL
            download_url = builder.save_to_exports(doc_result)
            doc_result["download_url"] = download_url

            logger.info(f"DocumentAgent: document ready at {download_url}")
            return doc_result

        except Exception as e:
            logger.error(f"DocumentAgent: generation failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "format": output_format,
            }

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def _build_context(
        self,
        state,
        document_type: str,
        title: Optional[str],
        extra_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Extract and structure data from conversation state for template rendering."""
        ir = getattr(state, "intermediate_results", {}) or {}

        # Time context
        try:
            now = datetime.now(ZoneInfo(settings.BUILDING_TIMEZONE))
        except Exception:
            now = datetime.utcnow()
        generated_at = now.strftime("%Y-%m-%d %H:%M %Z")

        # Resolve persona
        persona = getattr(state, "persona", "general") or "general"

        # Analytics result
        analytics_result = ir.get("analytics_result", {})
        analytics_output = analytics_result.get("output", "") if analytics_result else ""

        # Anomaly result
        anomaly_result = ir.get("anomaly_result", {})
        anomalies: List[Dict] = []
        if anomaly_result and isinstance(anomaly_result, dict):
            anomalies = anomaly_result.get("anomalies", [])

        # SQL data summary
        sql_result = ir.get("sql_result", {})
        data_rows: List[Dict] = []
        if sql_result and isinstance(sql_result, dict):
            data_rows = sql_result.get("data", [])[:200]  # cap for doc

        # SPARQL metadata
        sparql_result = ir.get("sparql_result", {})
        sensor_count = 0
        if sparql_result:
            bindings = sparql_result.get("results", {}).get("results", {}).get("bindings", [])
            sensor_count = len(bindings)

        # Build readings summary for template
        readings_summary: Dict[str, Any] = {}
        if data_rows:
            import statistics

            try:
                values = [float(r.get("value", 0)) for r in data_rows if r.get("value") is not None]
                if values:
                    readings_summary = {
                        "count": len(values),
                        "mean": round(statistics.mean(values), 2),
                        "min": round(min(values), 2),
                        "max": round(max(values), 2),
                        "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0,
                    }
            except Exception:
                pass

        # Build highlights from analytics output
        highlights: List[str] = []
        if analytics_output:
            for line in str(analytics_output).split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 10:
                    highlights.append(line)
            highlights = highlights[:10]

        # Narrative from report agent
        report_result = ir.get("report_result", {})
        narrative = ""
        if report_result and isinstance(report_result, dict):
            narrative = report_result.get("formatted_response", "")

        # Phase 10 — per-request building context.  The document template
        # uses building name / id from the conversation's building, not the
        # process-global setting.
        from orchestrator.services.building_context import resolve_building_context

        bctx = resolve_building_context(getattr(state, "building_id", None))

        # Best title
        doc_title = (
            title
            or ir.get("document_title")
            or f"{document_type.replace('_', ' ').title()} — {bctx.name} — {generated_at}"
        )

        ctx: Dict[str, Any] = {
            "title": doc_title,
            "building_name": bctx.name,
            "building_id": bctx.building_id,
            "generated_at": generated_at,
            "document_type": document_type,
            "persona": persona,
            "sensor_count": sensor_count,
            "data_row_count": len(data_rows),
            "readings_summary": readings_summary,
            "anomalies": anomalies,
            "highlights": highlights,
            "narrative": narrative,
            "analytics_output": analytics_output,
            "data_rows": data_rows[:50],  # first 50 rows for table rendering
        }

        if extra_data:
            ctx.update(extra_data)

        return ctx


# Module-level singleton
_document_agent: Optional[DocumentAgent] = None


def get_document_agent() -> DocumentAgent:
    """Return the shared DocumentAgent singleton."""
    global _document_agent
    if _document_agent is None:
        _document_agent = DocumentAgent()
    return _document_agent
