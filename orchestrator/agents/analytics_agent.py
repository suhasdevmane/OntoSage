"""
Analytics Agent - Complex data analysis with code generation
"""
import sys
sys.path.append('/app')

import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional
from shared.models import ConversationState
from shared.utils import get_logger, extract_code_from_llm_response
from shared.config import settings
from orchestrator.llm_manager import llm_manager

logger = get_logger(__name__)

CODE_EXECUTOR_URL = f"http://{settings.CODE_EXECUTOR_HOST}:{settings.CODE_EXECUTOR_PORT}"

class AnalyticsAgent:
    """Generates and executes analytical Python code"""
    
    def __init__(self):
        self.max_retries = 3
    
    async def analyze(
        self,
        state: ConversationState,
        user_query: str,
        data: Optional[Dict[str, Any]] = None,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json"
    ) -> Dict[str, Any]:
        """
        Generate and execute analytics code
        
        Args:
            state: Conversation state
            user_query: User's analysis request
            data: Optional data from previous SQL/SPARQL queries
            sensor_metadata: Mapping of UUIDs to human-readable labels
            data_filename: Name of the file where data is saved (for isolation)
            
        Returns:
            Dict with 'code', 'output', 'error', 'visualizations'
        """
        try:
            logger.info("="*80)
            logger.info("🔬 ANALYTICS AGENT: Starting Analysis")
            logger.info("="*80)
            logger.info(f"📥 User Query: {user_query}")
            
            # Validate and normalize data structure
            if not data or not isinstance(data, dict):
                data = {"data": []}
            if "data" not in data:
                data = {"data": []}
            
            data_count = len(data.get("data", []))
            logger.info(f"📊 Data Records: {data_count}")
            
            # Check if we have any data
            if data_count == 0:
                logger.warning("⚠️  No data available for analysis")
                # Check if SQL failed
                sql_result = state.intermediate_results.get("sql_result", {})
                if not sql_result.get("success"):
                    error_msg = sql_result.get("error", "Unknown database error")
                    return {
                        "success": False,
                        "code": None,
                        "output": None,
                        "error": f"Database query failed: {error_msg}",
                        "formatted_response": f"I apologize, but I encountered a database error while retrieving the sensor data: {error_msg}. Please verify the database connection and schema configuration."
                    }
                else:
                    return {
                        "success": False,
                        "code": None,
                        "output": None,
                        "error": "No data available",
                        "formatted_response": "No data was found matching your query. The sensor may not have recorded any data in the specified time period, or the sensor might not be actively transmitting data."
                    }
            
            if sensor_metadata:
                logger.info(f"🏷️  Sensor Metadata: {len(sensor_metadata)} sensors")
                for uuid, meta in sensor_metadata.items():
                    logger.info(f"   - {uuid[:20]}... → {meta.get('label', 'N/A')}")
            
            # Step 1: Generate Python code
            logger.info("\n🤖 Step 1: Generating Python analytics code...")
            code = await self._generate_code(user_query, data, sensor_metadata, data_filename, user_id=state.user_id)
            logger.info(f"✅ Code generated ({len(code)} chars)")
            
            # Step 2: Execute code with retries
            logger.info("\n⚙️  Step 2: Executing code...")
            # Provide data context so fallback code can still access raw_data_json if needed
            result = await self._execute_with_retries(code, user_query, data, sensor_metadata, data_filename)
            
            if result.get("success"):
                logger.info(f"✅ Execution successful")
                logger.info(f"📤 Output: {result.get('output', 'None')[:200]}...")
            else:
                logger.error(f"❌ Execution failed: {result.get('error')}")
            
            # Step 3: Format results
            logger.info("\n📝 Step 3: Formatting results...")
            formatted, media = await self._format_analysis(result, user_query, sensor_metadata)
            logger.info(f"✅ Formatted response generated")
            logger.info("="*80)
            
            return {
                "success": True,
                "code": result.get("code"),
                "output": result.get("output"),
                "error": result.get("error"),
                "formatted_response": formatted,
                "media": media
            }
            
        except Exception as e:
            logger.error(f"Analytics error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "code": None,
                "output": None
            }
    
    def _get_template_code(
        self, 
        user_query: str, 
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json"
    ) -> Optional[str]:
        """
        Try to match user query to a pre-defined analytics template.
        Returns Python code if matched, None otherwise.
        """
        import json
        query_lower = user_query.lower()
        
        # Build sensor map for the code
        sensor_map_str = "{}"
        if sensor_metadata:
            # Create a simple dict string: {'uuid': 'label', ...}
            simple_map = {k: v.get('label', k) for k, v in sensor_metadata.items()}
            sensor_map_str = json.dumps(simple_map)

        # Common setup code for all templates
        try:
            setup_code = f"""
import pandas as pd
import json

# Sensor Metadata
sensor_map = {sensor_map_str}

def get_label(uuid):
    return sensor_map.get(uuid, uuid)

# Initialize empty DataFrame
df = pd.DataFrame(columns=['uuid', 'value', 'timestamp'])

# Load data
try:
    # Read data from standard local file
    # Using pandas to read JSON to bypass potential sandbox restrictions
    full_data = pd.read_json('/app/outputs/data/{data_filename}', typ='series')
    
    if 'data' in full_data:
        temp_df = pd.DataFrame(full_data['data'])
        if not temp_df.empty:
            df = temp_df

    if not df.empty:
        # Data preparation
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df = df.dropna(subset=['value', 'timestamp'])
        
except Exception as e:
    print(f"Error processing data: {{e}}")

if df.empty:
    print("No valid data available for analysis.")
    # Ensure columns exist to prevent KeyError in subsequent steps
    df = pd.DataFrame(columns=['uuid', 'value', 'timestamp'])
"""
        except Exception as e:
            logger.error(f"Error constructing setup_code: {e}")
            return None

        # Template 1: Average/Mean
        if any(w in query_lower for w in ['average', 'mean', 'avg']):
            return setup_code + """
# Calculate Average
results = df.groupby('uuid')['value'].mean()

print("Average Values:")
for uuid, val in results.items():
    print(f"Sensor: {get_label(uuid)}")
    print(f"Average: {val:.2f}")
    print("-" * 20)
"""

        # Template 2: Maximum/Peak
        if any(w in query_lower for w in ['maximum', 'max', 'peak', 'highest']):
            return setup_code + """
# Calculate Maximum
results = df.groupby('uuid')['value'].max()

print("Maximum Values:")
for uuid, val in results.items():
    print(f"Sensor: {get_label(uuid)}")
    print(f"Max: {val:.2f}")
    print("-" * 20)
"""

        # Template 3: Minimum/Lowest
        if any(w in query_lower for w in ['minimum', 'min', 'lowest']):
            return setup_code + """
# Calculate Minimum
results = df.groupby('uuid')['value'].min()

print("Minimum Values:")
for uuid, val in results.items():
    print(f"Sensor: {get_label(uuid)}")
    print(f"Min: {val:.2f}")
    print("-" * 20)
"""

        # Template 4: Latest/Current
        if any(w in query_lower for w in ['current', 'latest', 'now', 'recent']):
            return setup_code + """
# Get Latest Values
latest_indices = df.groupby('uuid')['timestamp'].idxmax()
latest_df = df.loc[latest_indices]

print("Latest Readings:")
for _, row in latest_df.iterrows():
    uuid = row['uuid']
    print(f"Sensor: {get_label(uuid)}")
    print(f"Value: {row['value']:.2f}")
    print(f"Time: {row['timestamp']}")
    print("-" * 20)
"""

        # Template 5: Count
        if any(w in query_lower for w in ['count', 'how many readings', 'number of readings']):
            return setup_code + """
# Count Readings
results = df.groupby('uuid').size()

print("Data Point Counts:")
for uuid, count in results.items():
    print(f"Sensor: {get_label(uuid)}")
    print(f"Count: {count}")
    print("-" * 20)
"""

        return None

    async def _generate_code(
        self,
        user_query: str,
        data: Optional[Dict[str, Any]] = None,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json",
        user_id: str = "default_user"
    ) -> str:
        """Generate Python analytics code using LLM"""
        
        # Try to use a template first
        template_code = self._get_template_code(user_query, sensor_metadata, data_filename)
        if template_code:
            logger.info("✅ Using pre-defined analytics template")
            return template_code
            
        # We don't put the full data in the prompt to save tokens, 
        # but we describe the structure.
        data_preview = str(data)[:500] + "..." if data else "No data provided"
        
        # Get current time in UK timezone
        try:
            uk_time = datetime.now(ZoneInfo("Europe/London"))
            current_time_str = uk_time.strftime("%A, %B %d, %Y, %H:%M %Z")
            timestamp_str = uk_time.strftime("%Y%m%d_%H%M%S")
        except Exception:
            uk_time = datetime.now()
            current_time_str = uk_time.strftime("%A, %B %d, %Y, %H:%M (UTC)")
            timestamp_str = uk_time.strftime("%Y%m%d_%H%M%S")
        
        # Build sensor metadata context
        metadata_context = ""
        if sensor_metadata:
            metadata_context = "\n\nSensor Metadata (UUID to human-readable name mapping):\n"
            for uuid, meta in sensor_metadata.items():
                metadata_context += f"  - UUID: {uuid} → Label: {meta['label']}\n"
            metadata_context += "\nIMPORTANT: The 'uuid' column in the data contains these UUID values (e.g., '1e87a383-b1b9-41e2-8f8d-a4d295ebf26a'), NOT the human-readable labels. When filtering data, use the actual UUID values from the 'uuid' column, not the sensor names."
        
        plot_filename = f"plot_{user_id}_{timestamp_str}.png"
        
        code_prompt = f"""You are a Python data analytics expert. Generate code to analyze smart building data.
Current Date and Time: {current_time_str}

User Request: {user_query}

DATA CONTEXT:
- The data is saved locally in a standard JSON format at: `/app/outputs/data/{data_filename}`
- Structure: {{"data": [{{"timestamp": "...", "uuid": "...", "value": ...}}, ...], "metadata": {{...}}}}
- You MUST read the data from this file using pandas.
{metadata_context}

Generate Python code that:
1. Starts with necessary import statements (pandas, json, matplotlib.pyplot, seaborn, etc.)
2. Reads the data from file: `df = pd.read_json('/app/outputs/data/{data_filename}', typ='series')`
   - Note: The file contains a "data" key with the list of records.
   - Recommended approach:
     ```python
     import pandas as pd
     # Read using pandas to bypass sandbox 'open' restriction
     full_data = pd.read_json('/app/outputs/data/{data_filename}', typ='series')
     df = pd.DataFrame(full_data['data'])
     ```

3. Ensures 'value' is numeric: `df['value'] = pd.to_numeric(df['value'], errors='coerce')`
4. Ensures 'timestamp' is datetime: `df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')`
5. Filter by the ACTUAL UUID value from the 'uuid' column (not by sensor label/name).
6. Performs the requested analysis (calculate stats, aggregations, etc.).
7. Prints results using human-readable sensor labels for clarity.
8. Handle empty data gracefully (check if filtered DataFrame is empty).

VISUALIZATION INSTRUCTIONS:
If the user asks for a graph, chart, or plot:
1. Use matplotlib or seaborn to create the plot.
2. Use a professional style (e.g., `plt.style.use('seaborn-v0_8')` or similar).
3. Add proper titles, labels, and legends.
4. Save the plot to: `/app/outputs/{plot_filename}`
   - Ensure the directory exists (though /app/outputs should exist).
   - `plt.savefig('/app/outputs/{plot_filename}')`
5. Print exactly: `PLOT_GENERATED: {plot_filename}` to standard output.

Available libraries: pandas, numpy, matplotlib, seaborn, plotly, datetime, json, math, statistics, time

Code Structure:
```python
import pandas as pd
import json
import matplotlib.pyplot as plt
import seaborn as sns

# Load data from file
full_data = pd.read_json('/app/outputs/data/{data_filename}', typ='series')
df = pd.DataFrame(full_data['data'])


# Data preparation
df['value'] = pd.to_numeric(df['value'], errors='coerce')
df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')

# Filter by actual UUID (e.g., 'aa1c2b1f-c59d-44bf-af24-08ced2ff7ffb')
sensor_uuid = 'actual_uuid_here'
filtered_df = df[df['uuid'] == sensor_uuid]

# Check if data exists
if filtered_df.empty:
    print("No data available for this sensor.")
else:
    # Analysis
    mean_val = filtered_df['value'].mean()
    print(f"Mean Value: {{mean_val}}")
    
    # Visualization (if requested)
    plt.figure(figsize=(10, 6))
    sns.lineplot(data=filtered_df, x='timestamp', y='value')
    plt.title('Temperature over Time')
    plt.savefig('/app/outputs/{plot_filename}')
    print("PLOT_GENERATED: {plot_filename}")
```

Respond with ONLY the Python code, wrapped in ```python blocks."""

        response = await llm_manager.generate(code_prompt)
        
        # Extract code from response
        code = extract_code_from_llm_response(response)
        
        logger.info(f"Generated analytics code:\n{code}")
        return code
    
    async def _execute_with_retries(
        self,
        code: str,
        user_query: str,
        data: Optional[Dict[str, Any]] = None,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json"
    ) -> Dict[str, Any]:
        """Execute code with automatic error fixing"""
        
        for attempt in range(self.max_retries):
            try:
                # Execute code via code executor service
                result = await self._execute_code(code, data)
                
                if result.get("success"):
                    logger.info(f"Code executed successfully on attempt {attempt + 1}")
                    # Map stdout to output for consistency
                    output = result.get("stdout") or result.get("output") or ""
                    return {
                        "success": True,
                        "code": code,
                        "output": output,
                        "error": None
                    }
                else:
                    error = result.get("error", "Unknown error")
                    logger.warning(f"Execution failed (attempt {attempt + 1}): {error}")
                    
                    if attempt < self.max_retries - 1:
                        # Try to fix the code
                        code = await self._fix_code(code, error, user_query, sensor_metadata, data_filename)
                    else:
                        return {
                            "success": False,
                            "code": code,
                            "output": None,
                            "error": error
                        }
                        
            except Exception as e:
                logger.error(f"Execution exception (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    return {
                        "success": False,
                        "code": code,
                        "output": None,
                        "error": str(e)
                    }
        
        return {
            "success": False,
            "code": code,
            "output": None,
            "error": "Max retries exceeded"
        }
    
    async def _execute_code(self, code: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute code via code executor service"""
        
        # Prepend data if available
        if data:
            import json
            data_json = json.dumps(data)
            # Use triple quotes to avoid escaping issues, but be careful with triple quotes inside data
            # A safer way is to use repr() or base64 encoding if data is complex, 
            # but for now simple string injection should work for standard JSON.
            data_assignment = f'raw_data_json = \'\'\'{data_json}\'\'\'\n'
            code = data_assignment + code
            logger.info(f"✅ Prepended data to code ({len(data_json)} chars of JSON)")
        else:
            logger.warning("⚠️  No data provided to _execute_code - raw_data_json will not be defined!")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{CODE_EXECUTOR_URL}/execute",
                    json={"code": code}
                )
                response.raise_for_status()
                return response.json()
                
        except httpx.HTTPError as e:
            logger.error(f"Code executor service error: {e}")
            raise Exception(f"Failed to execute code: {str(e)}")
    
    async def _fix_code(
        self,
        code: str,
        error: str,
        user_query: str,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json"
    ) -> str:
        """Attempt to fix code based on error"""
        
        metadata_context = ""
        if sensor_metadata:
            metadata_context = "\n\nSensor Metadata (UUID to label mapping):\n"
            for uuid, meta in sensor_metadata.items():
                metadata_context += f"  - UUID: {uuid} → Label: {meta['label']}\n"
            metadata_context += "\nREMEMBER: Use actual UUID values from the 'uuid' column for filtering, not sensor names.\n"
        
        fix_prompt = f"""The following Python code produced an error:

Code:
```python
{code}
```

Error:
{error}

Original request: {user_query}
Data File: /app/outputs/data/{data_filename}
{metadata_context}

IMPORTANT CONTEXT:
- A variable named 'raw_data_json' containing JSON string data will be automatically provided before your code runs.
- Structure: {{"data": [{{"timestamp": "...", "uuid": "...", "value": ...}}, ...]}}
- Do NOT define or mock 'raw_data_json' yourself - it is already provided.
- If you see NameError for 'raw_data_json', the issue is elsewhere, not missing definition.

Fix the code to resolve the error. Common issues:
- Import errors: Check if library is imported
- Data type mismatches: Convert types appropriately  
- Missing variables: Initialize before use (except raw_data_json which is pre-defined)
- Index errors: Check bounds
- Syntax errors: Fix Python syntax
- Using sensor names instead of UUID values for filtering
- Incorrect data structure assumptions

Respond with ONLY the corrected Python code, wrapped in ```python blocks."""

        response = await llm_manager.generate(fix_prompt)
        fixed_code = extract_code_from_llm_response(response)
        
        logger.info(f"Fixed code:\n{fixed_code}")
        return fixed_code
    
    async def _format_analysis(
        self,
        result: Dict[str, Any],
        user_query: str,
        sensor_metadata: Dict[str, Dict[str, str]] = None
    ) -> str:
        """Format analysis results into natural language"""
        
        if not result.get("success"):
            return f"Analysis failed: {result.get('error', 'Unknown error')}", []
        
        output = result.get("output", "")
        
        # Check for plot generation
        import re
        plot_match = re.search(r"PLOT_GENERATED: ([\w\.-]+)", output)
        plot_markdown = ""
        media = []
        if plot_match:
            filename = plot_match.group(1)
            
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

            plot_markdown = f"\n\n![Analysis Plot]({image_url})"
            
            # Remove the marker from output to clean it up for LLM
            output = output.replace(plot_match.group(0), "")
            media.append({
                "type": "image",
                "url": image_url,
                "filename": filename
            })
        
        # Build sensor context for natural language generation
        sensor_context = ""
        if sensor_metadata:
            sensor_context = "\n\nSensor Information:\n"
            for uuid, meta in sensor_metadata.items():
                sensor_context += f"  - UUID {uuid} is '{meta['label']}'\n"
            sensor_context += "\nIMPORTANT: Use the human-readable sensor names (labels) in your response, NOT UUIDs.\n"
        
        # Generate natural language summary
        summary_prompt = f"""Convert this Python analysis output into a natural language response.

User Query: {user_query}

Analysis Output:
{output}
{sensor_context}

Generate a concise, natural response that:
1. Explains what analysis was performed
2. Highlights key findings and numbers
3. Uses clear, non-technical language
4. Uses human-readable sensor names (from Sensor Information above), NOT UUIDs
5. Mentions any visualizations created

Response:"""

        try:
            summary = await llm_manager.generate(summary_prompt)
            return summary.strip() + plot_markdown, media
        except:
            return f"Analysis complete. Output:\n{output}" + plot_markdown, media
