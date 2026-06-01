"""
Visualization Agent - Chart generation and PDF reporting
"""

import sys

sys.path.append("/app")

import json
import uuid
from typing import Any, Dict, List, Optional

import httpx

from orchestrator.llm_manager import llm_manager
from shared.config import settings
from shared.models import ConversationState
from shared.utils import extract_code_from_llm_response, get_logger

logger = get_logger(__name__)

CODE_EXECUTOR_URL = f"http://{settings.CODE_EXECUTOR_HOST}:{settings.CODE_EXECUTOR_PORT}"


class VisualizationAgent:
    """Generates visualizations and reports"""

    async def create_visualization(
        self,
        state: ConversationState,
        user_query: str,
        data: Optional[Dict[str, Any]] = None,
        analysis_output: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create visualization from data

        Args:
            state: Conversation state
            user_query: User's visualization request
            data: Optional data to visualize
            analysis_output: Optional analysis results

        Returns:
            Dict with 'code', 'chart_type', 'image_path', 'description'
        """
        try:
            # Step 1: Determine chart type
            chart_type = await self._determine_chart_type(user_query, data)

            # filename arg kept for prompt compat but plot is returned as base64 in stdout
            filename = f"viz_{uuid.uuid4().hex[:8]}.png"

            # Step 2: Generate visualization code
            code = await self._generate_viz_code(user_query, data, chart_type, filename)

            # Patch any LLM-generated code that still uses the old file-save pattern
            code = self._patch_plot_to_base64(code, filename)

            # Step 3: Execute visualization code
            result = await self._execute_viz_code(code)

            # Step 4: Generate description
            description = await self._generate_description(user_query, chart_type, data)

            # Extract base64 from stdout, save to /app/outputs/, return HTTP URL
            import base64 as _b64
            import os as _os
            import re as _re
            from datetime import datetime as _dt

            image_url = None
            output_text = result.get("stdout") or result.get("output") or ""
            b64_match = _re.search(r"PLOT_BASE64: ([A-Za-z0-9+/=]+)", output_text)
            if b64_match:
                plot_filename = f"viz_{_dt.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
                plot_path = f"/app/outputs/{plot_filename}"
                try:
                    _os.makedirs("/app/outputs", exist_ok=True)
                    with open(plot_path, "wb") as _f:
                        _f.write(_b64.b64decode(b64_match.group(1)))
                    from shared.config import settings as _s

                    image_url = f"{_s.STATIC_BASE_URL.rstrip('/')}/static/{plot_filename}"
                    logger.info(f"Saved viz plot to {plot_path}, serving at {image_url}")
                except Exception as _e:
                    logger.warning(f"Could not save viz plot: {_e}")
                    image_url = f"data:image/png;base64,{b64_match.group(1)}"
            else:
                logger.warning(
                    "No PLOT_BASE64 in code-executor output — visualization may not render"
                )
                image_url = ""

            formatted_response = (
                f"{description}\n\n![Visualization]({image_url})" if image_url else description
            )

            return {
                "success": True,
                "code": code,
                "chart_type": chart_type,
                "output": output_text,
                "description": description,
                "formatted_response": formatted_response,
                "media": [{"type": "image", "url": image_url}] if image_url else [],
            }

        except Exception as e:
            logger.error(f"Visualization error: {e}", exc_info=True)
            return {"success": False, "error": str(e), "code": None, "chart_type": None}

    async def _determine_chart_type(
        self, user_query: str, data: Optional[Dict[str, Any]] = None
    ) -> str:
        """Determine appropriate chart type"""

        query_lower = user_query.lower()

        # Pattern matching for chart types
        if any(word in query_lower for word in ["line", "trend", "over time", "time series"]):
            return "line_chart"
        elif any(word in query_lower for word in ["bar", "compare", "comparison"]):
            return "bar_chart"
        elif any(word in query_lower for word in ["scatter", "correlation", "relationship"]):
            return "scatter_plot"
        elif any(word in query_lower for word in ["histogram", "distribution"]):
            return "histogram"
        elif any(word in query_lower for word in ["heatmap", "matrix", "correlation matrix"]):
            return "heatmap"
        elif any(word in query_lower for word in ["pie", "proportion", "percentage"]):
            return "pie_chart"
        else:
            # Use LLM to determine
            chart_prompt = f"""Determine the best chart type for this request:

User Query: {user_query}
Data: {str(data)[:200] if data else "Not specified"}

Choose ONE of: line_chart, bar_chart, scatter_plot, histogram, heatmap, pie_chart

Respond with ONLY the chart type name."""

            try:
                response = await llm_manager.generate(chart_prompt)
                chart_type = response.strip().lower()

                valid_types = [
                    "line_chart",
                    "bar_chart",
                    "scatter_plot",
                    "histogram",
                    "heatmap",
                    "pie_chart",
                ]
                return chart_type if chart_type in valid_types else "bar_chart"
            except:
                return "bar_chart"  # Default fallback

    async def _generate_viz_code(
        self, user_query: str, data: Optional[Dict[str, Any]], chart_type: str, filename: str
    ) -> str:
        """Generate Matplotlib/Seaborn visualization code"""

        data_context = ""
        if data:
            # Limit data context size to avoid token limits
            data_str = str(data)
            if len(data_str) > 2000:
                data_str = data_str[:2000] + "... (truncated)"
            data_context = f"\nData to visualize:\n{data_str}\n"

        viz_prompt = f"""Generate Python code to create a {chart_type} using matplotlib/seaborn.

{data_context}

User Request: {user_query}
Output Filename: {filename}

Generate code that:
1. Imports matplotlib.pyplot, seaborn, pandas, json
2. Prepares the data (convert from dict/json to DataFrame)
3. Creates a {chart_type} using seaborn or matplotlib
4. Includes proper labels, title, and styling
5. Encodes the plot as base64 and prints it to stdout — do NOT use plt.savefig() to a file path:
   ```python
   import base64, io as _io
   _buf = _io.BytesIO()
   plt.savefig(_buf, format='png', bbox_inches='tight', dpi=100)
   plt.close()
   _buf.seek(0)
   print("PLOT_BASE64: " + base64.b64encode(_buf.read()).decode('utf-8'))
   ```

Example structure:
```python
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import json
import base64, io as _io

# Prepare data
raw_data = {json.dumps(data) if data else "{}"}
# If raw_data is a dict with 'data' list, extract it
if isinstance(raw_data, dict) and 'data' in raw_data:
    df = pd.DataFrame(raw_data['data'])
else:
    df = pd.DataFrame(raw_data)

# Ensure numeric/datetime types
# ...

# Create plot
plt.figure(figsize=(10, 6))
sns.lineplot(data=df, x='timestamp', y='value') # Example
plt.title("Chart Title")
plt.tight_layout()

# Output as base64 (not file)
_buf = _io.BytesIO()
plt.savefig(_buf, format='png', bbox_inches='tight', dpi=100)
plt.close()
_buf.seek(0)
print("PLOT_BASE64: " + base64.b64encode(_buf.read()).decode('utf-8'))
```

Respond with ONLY the Python code, wrapped in ```python blocks."""

        response = await llm_manager.generate(viz_prompt)
        code = extract_code_from_llm_response(response)

        logger.info(f"Generated visualization code for {chart_type}")
        return code

    async def _execute_viz_code(self, code: str) -> Dict[str, Any]:
        """Execute visualization code"""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{CODE_EXECUTOR_URL}/execute", json={"code": code})
                response.raise_for_status()
                return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Visualization execution error: {e}")
            raise Exception(f"Failed to create visualization: {str(e)}")

    def _patch_plot_to_base64(self, code: str, filename: str) -> str:
        """Delegate to module-level patch function (shared with analytics_agent)."""
        from orchestrator.agents.analytics_agent import _patch_plot_to_base64

        return _patch_plot_to_base64(code)

    async def _generate_description(
        self, user_query: str, chart_type: str, data: Optional[Dict[str, Any]]
    ) -> str:
        """Generate natural language description of visualization"""

        desc_prompt = f"""Generate a brief description of a visualization.

User Query: {user_query}
Chart Type: {chart_type}
Data Summary: {str(data)[:200] if data else "Not specified"}

Generate 1-2 sentences describing:
1. What the visualization shows
2. Key insights or patterns

Description:"""

        try:
            description = await llm_manager.generate(desc_prompt)
            return description.strip()
        except Exception as e:
            logger.warning(f"[visualization_agent] Description generation failed: {e}")
            return f"Created a {chart_type.replace('_', ' ')} visualization."

    async def create_report(
        self, state: ConversationState, title: str, sections: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Generate PDF report

        Args:
            state: Conversation state
            title: Report title
            sections: List of {"heading": ..., "content": ...}

        Returns:
            Dict with 'pdf_path', 'success'
        """
        # Generate report code
        report_code = self._generate_report_code(title, sections)

        try:
            # Execute report generation
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{CODE_EXECUTOR_URL}/execute", json={"code": report_code}
                )
                response.raise_for_status()
                result = response.json()

                return {"success": True, "pdf_path": "report.pdf", "output": result.get("output")}

        except Exception as e:
            logger.error(f"Report generation error: {e}")
            return {"success": False, "error": str(e)}

    def _generate_report_code(self, title: str, sections: List[Dict[str, str]]) -> str:
        """Generate Python code for PDF report"""

        code = f"""
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# Create PDF
pdf = SimpleDocTemplate("report.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = []

# Title
title = Paragraph("{title}", styles['Title'])
story.append(title)
story.append(Spacer(1, 12))

"""

        for section in sections:
            heading = section.get("heading", "Section")
            content = section.get("content", "").replace('"', '\\"')

            code += f"""
# Section: {heading}
story.append(Paragraph("{heading}", styles['Heading1']))
story.append(Spacer(1, 6))
story.append(Paragraph("{content}", styles['BodyText']))
story.append(Spacer(1, 12))

"""

        code += """
# Build PDF
pdf.build(story)
print("Report generated: report.pdf")
"""

        return code
