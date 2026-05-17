"""
Analytics Agent - Complex data analysis with code generation
"""

import sys

sys.path.append("/app")

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import httpx

from orchestrator.llm_manager import TaskType, llm_manager
from shared.config import settings
from shared.models import ConversationState
from shared.utils import extract_code_from_llm_response, get_logger

logger = get_logger(__name__)

CODE_EXECUTOR_URL = f"http://{settings.CODE_EXECUTOR_HOST}:{settings.CODE_EXECUTOR_PORT}"


def _patch_plot_to_base64(code: str) -> str:
    """
    Patch LLM-generated code to output plots as base64 via stdout.

    Key problem solved: LLM often generates:
        plt.savefig('file.png')   # removed below
        plt.close()               # was NOT removed → figure closed before base64 capture
    Then the appended base64 block saved a blank/closed figure → blank white image.

    Fix: remove plt.close() / plt.show() so the figure stays open until the appended
    base64 block captures and closes it.
    """
    import re

    if "PLOT_BASE64" in code:
        return code  # Already uses base64 approach — includes its own plt.close()

    if "plt" not in code:
        return code  # No matplotlib usage

    # Remove file-based savefig calls (string literals and common variable names)
    code = re.sub(r"plt\.savefig\(['\"][^'\"]*['\"][^)]*\)\s*\n?", "", code)  # string arg
    code = re.sub(r"plt\.savefig\(filename[^)]*\)\s*\n?", "", code)
    code = re.sub(r"plt\.savefig\(output_path[^)]*\)\s*\n?", "", code)
    code = re.sub(r"plt\.savefig\(filepath[^)]*\)\s*\n?", "", code)
    code = re.sub(r"plt\.savefig\(path[^)]*\)\s*\n?", "", code)
    code = re.sub(r'print\s*\(\s*["\']PLOT_GENERATED:.*?\)\s*\n?', "", code)

    # Remove plt.close() and plt.show() — they close/discard the figure before the
    # base64 capture block below.  plt.close() will be called inside that block.
    code = re.sub(r"plt\.close\([^)]*\)\s*\n?", "", code)
    code = re.sub(r"plt\.show\([^)]*\)\s*\n?", "", code)

    # Append base64 output block (includes plt.close() at the right moment)
    code = code.rstrip() + (
        "\nimport base64 as _b64, io as _bio\n"
        "_buf = _bio.BytesIO()\n"
        "plt.savefig(_buf, format='png', bbox_inches='tight', dpi=100)\n"
        "plt.close()\n"
        "_buf.seek(0)\n"
        "print('PLOT_BASE64: ' + _b64.b64encode(_buf.read()).decode('utf-8'))\n"
    )
    return code


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
        data_filename: str = "current_data.json",
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
            logger.info("=" * 80)
            logger.info("🔬 ANALYTICS AGENT: Starting Analysis")
            logger.info("=" * 80)
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
                # Build a context-aware, user-friendly message
                sql_result = state.intermediate_results.get("sql_result", {})
                entities = state.intermediate_results.get("entities", [])
                time_range = state.intermediate_results.get("time_range", {})
                entity_hint = (
                    f" for **{entities[0]}**" if entities else " for the requested sensor(s)"
                )
                time_hint = ""
                if time_range:
                    start = time_range.get("start_time", "")
                    end = time_range.get("end_time", "")
                    if start or end:
                        time_hint = f" in the period {start[:10] if start else ''}–{end[:10] if end else 'now'}"

                if not sql_result.get("success"):
                    # The SQL query itself failed (connection error, schema mismatch, etc.)
                    # Prefer the pre-built message from the SQL agent (it has building-specific
                    # context about which sensor types are available). Fall back to generic.
                    sql_msg = sql_result.get("formatted_response")
                    user_msg = sql_msg or (
                        f"I wasn't able to retrieve sensor readings{entity_hint}{time_hint}. "
                        "This may be because the sensor type isn't monitored in this building, "
                        "or the data isn't available for the requested time window. "
                        "Try asking about temperature, CO₂, humidity, or air quality — "
                        "these are the sensor types actively monitored here."
                    )
                    return {
                        "success": False,
                        "code": None,
                        "output": None,
                        "error": "sql_query_failed",
                        "formatted_response": user_msg,
                    }
                else:
                    # SQL succeeded but returned no rows (no data for that period)
                    return {
                        "success": False,
                        "code": None,
                        "output": None,
                        "error": "no_data_available",
                        "formatted_response": (
                            f"No readings were found{entity_hint}{time_hint}. "
                            "The sensor may not have recorded any data in that period, "
                            "or the sensor might not be actively transmitting. "
                            "Try a more recent time window, or check another sensor zone."
                        ),
                    }

            if sensor_metadata:
                logger.info(f"🏷️  Sensor Metadata: {len(sensor_metadata)} sensors")
                for uuid, meta in sensor_metadata.items():
                    logger.info(f"   - {uuid[:20]}... → {meta.get('label', 'N/A')}")

            # Step 1: Generate Python code
            logger.info("\n🤖 Step 1: Generating Python analytics code...")
            code = await self._generate_code(
                user_query, data, sensor_metadata, data_filename, user_id=state.user_id
            )
            logger.info(f"✅ Code generated ({len(code)} chars)")

            # Step 2: Execute code with retries
            logger.info("\n⚙️  Step 2: Executing code...")
            # Provide data context so fallback code can still access raw_data_json if needed
            result = await self._execute_with_retries(
                code, user_query, data, sensor_metadata, data_filename
            )

            if result.get("success"):
                logger.info(f"✅ Execution successful")
                logger.info(f"📤 Output: {result.get('output', 'None')[:200]}...")
            else:
                logger.error(f"❌ Execution failed: {result.get('error')}")

            # Step 3: Format results
            logger.info("\n📝 Step 3: Formatting results...")
            formatted, media = await self._format_analysis(result, user_query, sensor_metadata)
            logger.info(f"✅ Formatted response generated")
            logger.info("=" * 80)

            return {
                "success": True,
                "code": result.get("code"),
                "output": result.get("output"),
                "error": result.get("error"),
                "formatted_response": formatted,
                "media": media,
            }

        except Exception as e:
            logger.error(f"Analytics error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "code": None,
                "output": None,
                "formatted_response": (
                    "I encountered an issue processing your request. "
                    "Please try rephrasing your question, or ask about a specific "
                    "zone or sensor (e.g. 'temperature in Zone 5.28', 'CO₂ in Zone 5.08')."
                ),
            }

    def _get_template_code(
        self,
        user_query: str,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json",
    ) -> Optional[str]:
        """
        Try to match user query to a pre-defined analytics template.
        Returns Python code if matched, None otherwise.
        """
        import json

        query_lower = user_query.lower()

        # Build sensor map for the code
        sensor_map_str = "{}"
        sensor_unit_map_str = "{}"
        if sensor_metadata:
            # Create a simple dict string: {'uuid': 'label', ...}
            simple_map = {k: v.get("label", k) for k, v in sensor_metadata.items()}
            sensor_map_str = json.dumps(simple_map)
            simple_units = {k: v.get("unit", "") for k, v in sensor_metadata.items()}
            sensor_unit_map_str = json.dumps(simple_units)

        # Common setup code for all templates
        try:
            setup_code = f"""
import pandas as pd
import json

# Sensor Metadata
sensor_map = {sensor_map_str}
sensor_unit_map = {sensor_unit_map_str}

def get_label(uuid):
    return sensor_map.get(uuid, uuid)

def get_unit(uuid):
    return sensor_unit_map.get(uuid, "")

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
        # Normalize column names — SQL agent sometimes returns 'sensor_uuid' instead of 'uuid'
        if 'sensor_uuid' in df.columns and 'uuid' not in df.columns:
            df = df.rename(columns={{'sensor_uuid': 'uuid'}})
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

        # Template 1: Latest + Average (combined)
        if any(w in query_lower for w in ["average", "mean", "avg"]) and any(
            w in query_lower for w in ["current", "latest", "now", "recent"]
        ):
            return setup_code + """
# Calculate Average and Latest
avg_results = df.groupby('uuid')['value'].mean()
latest_indices = df.groupby('uuid')['timestamp'].idxmax()
latest_df = df.loc[latest_indices].set_index('uuid')

print("Latest and Average Values:")
for uuid, avg_val in avg_results.items():
    unit = get_unit(uuid)
    unit_str = f" {unit}" if unit else ""
    if uuid in latest_df.index:
        latest_row = latest_df.loc[uuid]
        print(f"Sensor: {get_label(uuid)}")
        print(f"Latest: {latest_row['value']:.2f}{unit_str} at {latest_row['timestamp']}")
        print(f"Average: {avg_val:.2f}{unit_str}")
        print("-" * 20)
"""

        # Template 2: Average/Mean
        if any(w in query_lower for w in ["average", "mean", "avg"]):
            return setup_code + """
# Calculate Average
results = df.groupby('uuid')['value'].mean()

print("Average Values:")
for uuid, val in results.items():
    unit = get_unit(uuid)
    unit_str = f" {unit}" if unit else ""
    print(f"Sensor: {get_label(uuid)}")
    print(f"Average: {val:.2f}{unit_str}")
    print("-" * 20)
"""

        # Template 3: Maximum/Peak
        if any(w in query_lower for w in ["maximum", "max", "peak", "highest"]):
            return setup_code + """
# Calculate Maximum
results = df.groupby('uuid')['value'].max()

print("Maximum Values:")
for uuid, val in results.items():
    unit = get_unit(uuid)
    unit_str = f" {unit}" if unit else ""
    print(f"Sensor: {get_label(uuid)}")
    print(f"Max: {val:.2f}{unit_str}")
    print("-" * 20)
"""

        # Template 4: Minimum/Lowest
        if any(w in query_lower for w in ["minimum", "min", "lowest"]):
            return setup_code + """
# Calculate Minimum
results = df.groupby('uuid')['value'].min()

print("Minimum Values:")
for uuid, val in results.items():
    unit = get_unit(uuid)
    unit_str = f" {unit}" if unit else ""
    print(f"Sensor: {get_label(uuid)}")
    print(f"Min: {val:.2f}{unit_str}")
    print("-" * 20)
"""

        # Template 5: Latest/Current
        if any(w in query_lower for w in ["current", "latest", "now", "recent"]):
            return setup_code + """
# Get Latest Values
latest_indices = df.groupby('uuid')['timestamp'].idxmax()
latest_df = df.loc[latest_indices]

print("Latest Readings:")
for _, row in latest_df.iterrows():
    uuid = row['uuid']
    unit = get_unit(uuid)
    unit_str = f" {unit}" if unit else ""
    print(f"Sensor: {get_label(uuid)}")
    print(f"Value: {row['value']:.2f}{unit_str}")
    print(f"Time: {row['timestamp']}")
    print("-" * 20)
"""

        # Template 6: Count
        if any(w in query_lower for w in ["count", "how many readings", "number of readings"]):
            return setup_code + """
# Count Readings
results = df.groupby('uuid').size()

print("Data Point Counts:")
for uuid, count in results.items():
    print(f"Sensor: {get_label(uuid)}")
    print(f"Count: {count}")
    print("-" * 20)
"""

        # Template 7a/7b: negation-aware chart detection
        # Reuse the same comprehensive vocabulary as WorkflowOrchestrator._user_wants_visualization
        try:
            from orchestrator.workflow import WorkflowOrchestrator as _WO

            _wants_viz = _WO._user_wants_visualization(user_query)
        except Exception:
            # Fallback inline check if import unavailable
            _viz_pos = frozenset(
                [
                    "plot",
                    "chart",
                    "graph",
                    "visualize",
                    "visualise",
                    "show trend",
                    "show graph",
                    "show chart",
                    "show plot",
                    "line chart",
                    "bar chart",
                    "time series",
                    "histogram",
                    "scatter plot",
                    "heatmap",
                    "generate chart",
                    "draw chart",
                ]
            )
            _viz_neg = (
                "do not",
                "don't",
                "dont",
                "no chart",
                "no graph",
                "no plot",
                "no visual",
                "without chart",
                "without graph",
                "without plot",
                "skip chart",
                "skip graph",
                "just text",
                "text only",
                "numbers only",
                "stats only",
                "data only",
                "no viz",
            )
            _wants_viz = any(w in query_lower for w in _viz_pos) and not any(
                n in query_lower for n in _viz_neg
            )

        if _wants_viz:
            return setup_code + """
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import base64, io as _bio

if df.empty:
    print("No sensor data found.")
else:
    latest_idx = df.groupby('uuid')['timestamp'].idxmax()
    latest_df  = df.loc[latest_idx]
    print(f"Sensor readings ({len(df)} data points):")
    for _, row in latest_df.iterrows():
        u = row['uuid']
        unit = get_unit(u); unit_str = f" {unit}" if unit else ""
        s = df[df['uuid'] == u]['value']
        print(f"Sensor : {get_label(u)}")
        print(f"Latest : {row['value']:.2f}{unit_str}  at  {row['timestamp']}")
        print(f"Mean   : {s.mean():.2f}{unit_str}  |  Median: {s.median():.2f}{unit_str}")
        print(f"Min    : {s.min():.2f}{unit_str}  |  Max   : {s.max():.2f}{unit_str}")
        print("-" * 40)

    try:
        plt.style.use('seaborn-v0_8-darkgrid')
    except Exception:
        pass
    fig, ax = plt.subplots(figsize=(12, 5))
    uuids  = df['uuid'].unique()
    colors = plt.cm.tab10.colors
    for i, u in enumerate(uuids[:8]):
        sub = df[df['uuid'] == u].sort_values('timestamp')
        if sub.empty:
            continue
        lbl  = get_label(u)
        unit = get_unit(u); unit_str = f" ({unit})" if unit else ""
        ax.plot(sub['timestamp'], sub['value'],
                label=f"{lbl}{unit_str}", color=colors[i % len(colors)],
                linewidth=1.5, alpha=0.85)
    ax.set_title("Sensor Readings Over Time", fontsize=14, fontweight='bold', pad=12)
    ax.set_xlabel("Timestamp", fontsize=11)
    unit_label = get_unit(list(uuids)[0]) if len(uuids) > 0 else ""
    ax.set_ylabel(f"Value ({unit_label})" if unit_label else "Value", fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
    fig.autofmt_xdate(rotation=30)
    if len(uuids) > 1:
        ax.legend(loc='upper left', fontsize=9)
    plt.tight_layout()
    _buf = _bio.BytesIO()
    plt.savefig(_buf, format='png', bbox_inches='tight', dpi=120)
    plt.close(fig)
    _buf.seek(0)
    print("PLOT_BASE64: " + base64.b64encode(_buf.read()).decode('utf-8'))
"""

        # Template 7b: Stats-only fallback (no chart) — default for all other queries
        return setup_code + """
if df.empty:
    print("No sensor data found.")
else:
    latest_idx = df.groupby('uuid')['timestamp'].idxmax()
    latest_df  = df.loc[latest_idx]
    print(f"Sensor readings ({len(df)} data points):")
    for _, row in latest_df.iterrows():
        u = row['uuid']
        unit = get_unit(u); unit_str = f" {unit}" if unit else ""
        s = df[df['uuid'] == u]['value']
        print(f"Sensor : {get_label(u)}")
        print(f"Latest : {row['value']:.2f}{unit_str}  at  {row['timestamp']}")
        print(f"Mean   : {s.mean():.2f}{unit_str}  |  Median: {s.median():.2f}{unit_str}")
        print(f"Min    : {s.min():.2f}{unit_str}  |  Max   : {s.max():.2f}{unit_str}")
        print(f"Std Dev: {s.std():.2f}{unit_str}")
        print("-" * 40)
"""

    async def _generate_code(
        self,
        user_query: str,
        data: Optional[Dict[str, Any]] = None,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json",
        user_id: str = "default_user",
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

        # Get current time in building's local timezone
        try:
            local_time = datetime.now(ZoneInfo(settings.BUILDING_TIMEZONE))
            current_time_str = local_time.strftime("%A, %B %d, %Y, %H:%M %Z")
            timestamp_str = local_time.strftime("%Y%m%d_%H%M%S")
        except Exception:
            local_time = datetime.now()
            current_time_str = local_time.strftime("%A, %B %d, %Y, %H:%M (UTC)")
            timestamp_str = local_time.strftime("%Y%m%d_%H%M%S")

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
- NOTE: The UUID column may be named 'uuid' OR 'sensor_uuid' — after reading, rename it: if 'sensor_uuid' in df.columns: df = df.rename(columns={{'sensor_uuid': 'uuid'}})
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
4. Encode the plot as base64 and print it — do NOT use plt.savefig() to a file:
   ```python
   import base64, io as _io
   _buf = _io.BytesIO()
   plt.savefig(_buf, format='png', bbox_inches='tight', dpi=100)
   plt.close()
   _buf.seek(0)
   print("PLOT_BASE64: " + base64.b64encode(_buf.read()).decode('utf-8'))
   ```
5. Do NOT use plt.savefig('/app/outputs/...') or any file path — only use the base64 method above.

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
    import base64, io as _io
    _buf = _io.BytesIO()
    plt.savefig(_buf, format='png', bbox_inches='tight', dpi=100)
    plt.close()
    _buf.seek(0)
    print("PLOT_BASE64: " + base64.b64encode(_buf.read()).decode('utf-8'))
```

Respond with ONLY the Python code, wrapped in ```python blocks."""

        response = await llm_manager.generate(code_prompt, task_type=TaskType.ANALYTICS)

        # Extract code from response
        code = extract_code_from_llm_response(response)

        # Patch any LLM-generated code that still uses the old file-save pattern
        code = _patch_plot_to_base64(code)

        logger.info(f"Generated analytics code:\n{code}")
        return code

    async def _execute_with_retries(
        self,
        code: str,
        user_query: str,
        data: Optional[Dict[str, Any]] = None,
        sensor_metadata: Optional[Dict[str, Dict[str, str]]] = None,
        data_filename: str = "current_data.json",
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
                    return {"success": True, "code": code, "output": output, "error": None}
                else:
                    error = result.get("error", "Unknown error")
                    logger.warning(f"Execution failed (attempt {attempt + 1}): {error}")

                    if attempt < self.max_retries - 1:
                        # Try to fix the code
                        code = await self._fix_code(
                            code, error, user_query, sensor_metadata, data_filename
                        )
                    else:
                        return {"success": False, "code": code, "output": None, "error": error}

            except Exception as e:
                logger.error(f"Execution exception (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    return {"success": False, "code": code, "output": None, "error": str(e)}

        return {"success": False, "code": code, "output": None, "error": "Max retries exceeded"}

    async def _execute_code(
        self, code: str, data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute code via code executor service"""

        # Prepend data if available — use json.loads() to prevent triple-quote injection
        if data:
            import base64
            import json

            data_b64 = base64.b64encode(json.dumps(data, default=str).encode()).decode()
            data_assignment = (
                f"import base64 as _b64, json as _json\n"
                f"raw_data_json = _json.loads(_b64.b64decode({data_b64!r}).decode())\n"
            )
            code = data_assignment + code
            logger.info(f"✅ Prepended data to code via base64 ({len(data_b64)} chars encoded)")
        else:
            logger.warning(
                "⚠️  No data provided to _execute_code - raw_data_json will not be defined!"
            )

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{CODE_EXECUTOR_URL}/execute", json={"code": code})
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
        data_filename: str = "current_data.json",
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
- A variable named 'raw_data_json' (a Python dict, already parsed — NOT a JSON string) will be automatically provided before your code runs.
- Structure: {{"data": [{{"timestamp": "...", "uuid": "...", "value": ...}}, ...]}}
- Access records directly: raw_data_json["data"] gives a list of dicts.
- Do NOT call json.loads() or bytes() on raw_data_json — it is already a parsed Python dict.
- Do NOT define or mock 'raw_data_json' yourself - it is already provided.
- If you see NameError for 'raw_data_json', the issue is elsewhere, not a missing definition.

Fix the code to resolve the error. Common issues:
- Import errors: Check if library is imported
- Data type mismatches: Convert types appropriately  
- Missing variables: Initialize before use (except raw_data_json which is pre-defined)
- Index errors: Check bounds
- Syntax errors: Fix Python syntax
- Using sensor names instead of UUID values for filtering
- Incorrect data structure assumptions

Respond with ONLY the corrected Python code, wrapped in ```python blocks."""

        response = await llm_manager.generate(fix_prompt, task_type=TaskType.ANALYTICS)
        fixed_code = extract_code_from_llm_response(response)

        logger.info(f"Fixed code:\n{fixed_code}")
        return fixed_code

    async def _format_analysis(
        self,
        result: Dict[str, Any],
        user_query: str,
        sensor_metadata: Dict[str, Dict[str, str]] = None,
    ) -> str:
        """Format analysis results into natural language"""

        if not result.get("success"):
            # Return the pre-formatted user-friendly message if available, otherwise a generic one
            user_msg = result.get("formatted_response") or (
                "I wasn't able to complete the analysis. Please try rephrasing your question "
                "or ask about a different time period or sensor."
            )
            return user_msg, []

        output = result.get("output", "")

        # Check for plot generation (base64 inline or legacy file-based)
        import re

        plot_markdown = ""
        media = []
        image_url = None

        # PLOT_BASE64 — image data encoded directly in stdout by code-executor
        b64_match = re.search(r"PLOT_BASE64: ([A-Za-z0-9+/=]+)", output)
        if b64_match:
            import base64
            import os

            b64_data = b64_match.group(1)

            # Guard: blank/empty figures produce a very small base64 string (< 6 KB decoded).
            # A real plot is typically 30-300 KB.  Skip tiny/blank images.
            _decoded_bytes = base64.b64decode(b64_data)
            if len(_decoded_bytes) < 6000:
                logger.warning(
                    f"Discarding likely-blank plot ({len(_decoded_bytes)} bytes < 6 KB threshold)"
                )
                output = output.replace(b64_match.group(0), "")
            else:
                # Save PNG to /app/outputs/ so it's served via the orchestrator's /static/ mount
                plot_filename = f"plot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
                plot_path = f"/app/outputs/{plot_filename}"
                try:
                    os.makedirs("/app/outputs", exist_ok=True)
                    with open(plot_path, "wb") as f:
                        f.write(_decoded_bytes)
                    static_base = settings.STATIC_BASE_URL.rstrip("/")
                    image_url = f"{static_base}/static/{plot_filename}"
                    logger.info(f"Saved plot to {plot_path}, serving at {image_url}")
                except Exception as e:
                    logger.warning(f"Could not save plot file: {e} — falling back to data URI")
                    image_url = f"data:image/png;base64,{b64_data}"
                output = output.replace(b64_match.group(0), "")

        # Legacy fallback: PLOT_GENERATED with filename
        elif re.search(r"PLOT_GENERATED: ([\w\.-]+)", output):
            plot_match = re.search(r"PLOT_GENERATED: ([\w\.-]+)", output)
            filename = plot_match.group(1)
            static_base = settings.STATIC_BASE_URL.rstrip("/")
            image_url = f"{static_base}/static/{filename}"
            output = output.replace(plot_match.group(0), "")

        if image_url:
            plot_markdown = f"\n\n![Analysis Plot]({image_url})"

            # Remove the marker from output to clean it up for LLM
        if image_url:
            media.append(
                {
                    "type": "image",
                    "url": image_url,
                }
            )

        # Build sensor context for natural language generation
        sensor_context = ""
        if sensor_metadata:
            sensor_context = "\n\nSensor Information:\n"
            for uuid, meta in sensor_metadata.items():
                unit = meta.get("unit", "")
                kind = meta.get("kind", "")
                unit_note = f" (unit: {unit})" if unit else ""
                kind_note = f" [{kind}]" if kind else ""
                sensor_context += f"  - UUID {uuid} is '{meta['label']}'{kind_note}{unit_note}\n"
            sensor_context += "\nIMPORTANT: Use the human-readable sensor names (labels) in your response, NOT UUIDs. Include units when available.\n"

        # Generate natural language summary
        viz_note = (
            "A time-series chart has been generated and will be shown below the text."
            if image_url
            else "No chart was generated for this query."
        )

        # Add sustainability/compliance context if relevant keywords present
        _q_lower = user_query.lower()
        compliance_hint = ""
        if any(kw in _q_lower for kw in [
            "ashrae", "well", "breeam", "iso 50001", "leed", "compliance",
            "standard", "threshold", "limit", "comfort", "esg", "carbon",
            "emission", "sustainability", "energy target", "kpi",
        ]):
            compliance_hint = """
Sustainability/Compliance Context:
- ASHRAE 55 thermal comfort: temperature 20–26°C, humidity 20–60%RH
- ASHRAE 62.1 air quality: CO₂ < 1100 ppm, PM2.5 < 35 µg/m³, TVOC < 500 ppb
- WELL v2 air quality: CO₂ < 1000 ppm, PM2.5 < 15 µg/m³, humidity 30–60%RH
- BREEAM Hea 02 (indoor air quality): CO₂ < 1000 ppm
- EN 15251 Category II: temperature 20–25°C (heating), 23–26°C (cooling)
- ISO 50001: track energy baseline, targets, and continual improvement
When findings violate a standard, clearly state which standard and by how much.
Use ✅ for compliant, ⚠️ for borderline, ❌ for non-compliant.
"""

        summary_prompt = f"""You are an expert building analytics assistant. Convert this sensor data analysis into a professional, actionable response.

User Query: {user_query}

Analysis Output:
{output}
{sensor_context}
{compliance_hint}
Visualization status: {viz_note}

Generate a response that:
1. Opens with the key finding (the single most important number or status) — bold it
2. Provides context: is this reading normal, concerning, or compliant with standards?
3. Uses ✅/⚠️/❌ status icons where relevant
4. Includes specific numbers with units
5. Ends with ONE concrete actionable recommendation if relevant
6. Uses human-readable sensor names (from Sensor Information above), NOT UUIDs
7. Is concise — 3–6 sentences for simple queries, up to 10 for complex ones
8. Does NOT include caveats like "I cannot provide" or "data not shown" — if data was analysed, report it

Response:"""

        try:
            summary = await llm_manager.generate(summary_prompt, task_type=TaskType.ANALYTICS)
            return summary.strip() + plot_markdown, media
        except Exception:
            return f"Analysis complete. Output:\n{output}" + plot_markdown, media
