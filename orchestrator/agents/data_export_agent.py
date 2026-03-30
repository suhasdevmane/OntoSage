"""
DataExportAgent — Phase 4.3 (Data Export Agent)
=================================================
Exports query results and reports into multiple formats:
  - JSON  (structured, machine-readable)
  - CSV   (spreadsheet-compatible)
  - HTML  (browser-renderable report)
  - Markdown (documentation-friendly)

Usage:
    from orchestrator.agents.data_export_agent import DataExportAgent
    agent = DataExportAgent()
    result = await agent.export(data=rows, label="co2_readings", fmt="csv")
"""
import sys
sys.path.append('/app')

import csv
import html as html_lib
import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

SUPPORTED_FORMATS = {"json", "csv", "html", "markdown", "md", "pdf", "docx"}


class DataExportAgent:
    """
    Phase 4.3: Converts arbitrary tabular data into exportable formats.

    Returns a dict with:
      - success: bool
      - format: str
      - content: str  (the exported text/bytes as a string)
      - filename: str (suggested filename)
      - size_bytes: int
    """

    async def export(
        self,
        data: Union[List[Dict], Dict[str, Any]],
        label: str = "export",
        fmt: str = "json",
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Export data to the specified format.

        Args:
            data:   List of row dicts OR nested dict with 'data' key
            label:  Used for filename generation
            fmt:    Output format: json / csv / html / markdown
            title:  Optional report title for HTML/Markdown
        """
        fmt = fmt.lower().strip()
        if fmt not in SUPPORTED_FORMATS:
            return {"success": False, "error": f"Unsupported format '{fmt}'. Use: {SUPPORTED_FORMATS}"}

        # Normalize input to list of dicts
        rows = self._normalize(data)
        if not rows:
            return {"success": False, "error": "No data to export", "content": "", "format": fmt}

        ts = datetime.now(ZoneInfo(settings.BUILDING_TIMEZONE)).strftime("%Y%m%d_%H%M%S")
        ext = "md" if fmt == "markdown" else fmt
        filename = f"{label}_{ts}.{ext}"

        try:
            # PDF/DOCX: delegate to DocumentBuilder
            if fmt in ("pdf", "docx"):
                from orchestrator.services.document_builder import DocumentBuilder
                builder = DocumentBuilder()
                doc_data = {"readings_summary": {}, "anomalies": [], "highlights": [],
                            "narrative": f"Data export: {len(rows)} records"}
                doc_result = builder.render(
                    report_data=doc_data, report_type="summary",
                    output_format=fmt, title=title or label,
                )
                if doc_result.get("success"):
                    download_url = builder.save_to_exports(doc_result)
                    doc_result["download_url"] = download_url
                    doc_result["row_count"] = len(rows)
                return doc_result

            if fmt == "json":
                content = self._to_json(rows)
            elif fmt == "csv":
                content = self._to_csv(rows)
            elif fmt == "html":
                content = self._to_html(rows, title or label)
            else:  # markdown / md
                content = self._to_markdown(rows, title or label)

            size_bytes = len(content.encode())
            logger.info(f"DataExportAgent: exported {len(rows)} rows as {fmt} ({size_bytes} bytes)")

            # D.2: Persist to exports directory and generate a download URL
            download_url: Optional[str] = None
            try:
                exports_dir = Path(settings.EXPORTS_DIR)
                exports_dir.mkdir(parents=True, exist_ok=True)
                file_path = exports_dir / filename
                file_path.write_text(content, encoding="utf-8")
                # Download URL served by the /static mount (outputs/ is mounted at /static)
                download_url = f"{settings.STATIC_BASE_URL}/static/exports/{filename}"
                logger.info(f"DataExportAgent: saved export to {file_path} → {download_url}")
            except Exception as _save_err:
                logger.warning(f"DataExportAgent: could not save file to disk: {_save_err}")

            return {
                "success": True,
                "format": fmt,
                "filename": filename,
                "content": content,
                "size_bytes": size_bytes,
                "row_count": len(rows),
                "download_url": download_url,
            }

        except Exception as e:
            logger.error(f"DataExportAgent export failed: {e}", exc_info=True)
            return {"success": False, "error": str(e), "format": fmt}

    # ------------------------------------------------------------------
    # Normalizer
    # ------------------------------------------------------------------

    def _normalize(self, data: Any) -> List[Dict]:
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                return self._normalize(data["data"])
            # Try to treat dict of lists as columnar data
            lengths = {k: len(v) for k, v in data.items() if isinstance(v, list)}
            if lengths:
                n = min(lengths.values())
                keys = list(lengths.keys())
                return [{k: data[k][i] for k in keys} for i in range(n)]
        return []

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _to_json(self, rows: List[Dict]) -> str:
        return json.dumps(
            {"exported_at": datetime.utcnow().isoformat() + "Z", "count": len(rows), "data": rows},
            indent=2, default=str
        )

    def _to_csv(self, rows: List[Dict]) -> str:
        if not rows:
            return ""
        buf = io.StringIO()
        keys = list(rows[0].keys())
        writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    def _to_html(self, rows: List[Dict], title: str) -> str:
        keys = list(rows[0].keys())
        safe_title = html_lib.escape(str(title))
        header = "".join(f"<th>{html_lib.escape(str(k))}</th>" for k in keys)
        body_rows = ""
        for row in rows:
            cells = "".join(f"<td>{html_lib.escape(str(row.get(k, '')))}</td>" for k in keys)
            body_rows += f"<tr>{cells}</tr>\n"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{safe_title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; }}
    h1 {{ color: #1a1a2e; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th {{ background: #16213e; color: white; padding: 8px 12px; text-align: left; }}
    td {{ padding: 7px 12px; border-bottom: 1px solid #ddd; }}
    tr:hover {{ background: #f5f5f5; }}
    .meta {{ color: #666; font-size: 0.85em; margin-bottom: 12px; }}
  </style>
</head>
<body>
  <h1>{safe_title}</h1>
  <p class="meta">Exported: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")} &mdash; {len(rows)} records</p>
  <table>
    <thead><tr>{header}</tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
</body>
</html>"""

    def _to_markdown(self, rows: List[Dict], title: str) -> str:
        if not rows:
            return f"# {title}\n\n*No data available.*"
        keys = list(rows[0].keys())
        header_row = "| " + " | ".join(str(k) for k in keys) + " |"
        sep_row = "| " + " | ".join("---" for _ in keys) + " |"
        data_rows = "\n".join(
            "| " + " | ".join(str(row.get(k, "")) for k in keys) + " |"
            for row in rows
        )
        return f"# {title}\n\n*{len(rows)} records — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*\n\n{header_row}\n{sep_row}\n{data_rows}\n"
