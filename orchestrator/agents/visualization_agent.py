"""
Visualization Agent - Chart generation and PDF reporting
"""
import sys
sys.path.append('/app')

import httpx
import uuid
import json
from typing import Dict, Any, Optional, List
from shared.models import ConversationState
from shared.utils import get_logger, extract_code_from_llm_response
from shared.config import settings
from orchestrator.llm_manager import llm_manager

logger = get_logger(__name__)

CODE_EXECUTOR_URL = f"http://{settings.CODE_EXECUTOR_HOST}:{settings.CODE_EXECUTOR_PORT}"

class VisualizationAgent:
    """Generates visualizations and reports"""
    
    async def create_visualization(
        self,
        state: ConversationState,
        user_query: str,
        data: Optional[Dict[str, Any]] = None,
        analysis_output: Optional[str] = None
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
            
            # Generate unique filename
            filename = f"viz_{uuid.uuid4().hex[:8]}.png"
            
            # Step 2: Generate visualization code
            code = await self._generate_viz_code(user_query, data, chart_type, filename)
            
            # Step 3: Execute visualization code
            result = await self._execute_viz_code(code)
            
            # Step 4: Generate description
            description = await self._generate_description(user_query, chart_type, data)
            
            # Try to embed image as base64 to avoid localhost/network issues
            try:
                import base64
                import os
                
                # Check multiple possible paths
                possible_paths = [
                    f"/app/outputs/{filename}",  # Docker
                    f"outputs/{filename}",       # Local relative
                    os.path.join(os.getcwd(), "outputs", filename) # Local absolute
                ]
                
                file_path = None
                for path in possible_paths:
                    if os.path.exists(path):
                        file_path = path
                        break
                
                if file_path:
                    with open(file_path, "rb") as img_file:
                        b64_data = base64.b64encode(img_file.read()).decode('utf-8')
                        image_url = f"data:image/png;base64,{b64_data}"
                        logger.info(f"Embedded image {filename} as base64 from {file_path}")
                else:
                    # Fallback to URL if file not found
                    logger.warning(f"Image file not found in {possible_paths}, falling back to URL")
                    static_base = settings.STATIC_BASE_URL.rstrip('/')
                    image_url = f"{static_base}/static/{filename}"
            except Exception as e:
                logger.error(f"Error embedding image: {e}")
                static_base = settings.STATIC_BASE_URL.rstrip('/')
                image_url = f"{static_base}/static/{filename}"

            # Construct response with image link
            formatted_response = f"{description}\n\n![Visualization]({image_url})"
            
            return {
                "success": True,
                "code": code,
                "chart_type": chart_type,
                "output": result.get("output"),
                "description": description,
                "formatted_response": formatted_response,
                "media": [
                    {
                        "type": "image",
                        "url": image_url,
                        "filename": filename
                    }
                ]
            }
            
        except Exception as e:
            logger.error(f"Visualization error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "code": None,
                "chart_type": None
            }
    
    async def _determine_chart_type(
        self,
        user_query: str,
        data: Optional[Dict[str, Any]] = None
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
                
                valid_types = ["line_chart", "bar_chart", "scatter_plot", "histogram", "heatmap", "pie_chart"]
                return chart_type if chart_type in valid_types else "bar_chart"
            except:
                return "bar_chart"  # Default fallback
    
    async def _generate_viz_code(
        self,
        user_query: str,
        data: Optional[Dict[str, Any]],
        chart_type: str,
        filename: str
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
5. Saves the plot to '/app/outputs/{filename}'
6. Prints confirmation message "PLOT_GENERATED: {filename}"

Example structure:
```python
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import json

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

# Save
plt.savefig('/app/outputs/{filename}')
print("PLOT_GENERATED: {filename}")
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
                response = await client.post(
                    f"{CODE_EXECUTOR_URL}/execute",
                    json={"code": code}
                )
                response.raise_for_status()
                return response.json()
                
        except httpx.HTTPError as e:
            logger.error(f"Visualization execution error: {e}")
            raise Exception(f"Failed to create visualization: {str(e)}")
    
    async def _generate_description(
        self,
        user_query: str,
        chart_type: str,
        data: Optional[Dict[str, Any]]
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
        except:
            return f"Created a {chart_type.replace('_', ' ')} visualization."
    
    async def create_report(
        self,
        state: ConversationState,
        title: str,
        sections: List[Dict[str, str]]
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
                    f"{CODE_EXECUTOR_URL}/execute",
                    json={"code": report_code}
                )
                response.raise_for_status()
                result = response.json()
                
                return {
                    "success": True,
                    "pdf_path": "report.pdf",
                    "output": result.get("output")
                }
                
        except Exception as e:
            logger.error(f"Report generation error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
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
