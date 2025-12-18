import sys
import os
import asyncio
import json
import shutil
from datetime import datetime

# Set environment variables BEFORE importing shared.config
os.environ["CODE_EXECUTOR_HOST"] = "localhost"
os.environ["CODE_EXECUTOR_PORT"] = "8002"
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11435"
os.environ["MODEL_PROVIDER"] = "local"

# Add project root to path
sys.path.append(os.getcwd())

# MOCK LLM MANAGER to avoid dependency issues and control output
from unittest.mock import MagicMock
mock_llm_module = MagicMock()
mock_manager = MagicMock()

# Define the code we expect the LLM to generate
EXPECTED_CODE = """
import pandas as pd
import json
import matplotlib.pyplot as plt
import seaborn as sns

# Load data from file
# Note: In the real container, this path is /app/outputs/data/...
# But for this local test, we need to handle the path correctly or ensure the file exists where the code runs.
# The code runs in the code-executor container, which mounts ./outputs to /app/outputs.
# So /app/outputs/data/test_viz_data.json IS correct for the container.
# BUT, if we are running this test script LOCALLY (not in container), we need to adjust.
# However, the agent sends this code to the code-executor container!
# So the path MUST be /app/outputs/data/...

full_data = pd.read_json('/app/outputs/data/test_viz_data.json', typ='series')
df = pd.DataFrame(full_data['data'])

# Data preparation
df['value'] = pd.to_numeric(df['value'], errors='coerce')
df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')

# Filter by actual UUID
sensor_uuid = '550e8400-e29b-41d4-a716-446655440000'
filtered_df = df[df['uuid'] == sensor_uuid]

if filtered_df.empty:
    print("No data available for this sensor.")
else:
    # Analysis
    mean_val = filtered_df['value'].mean()
    print(f"Mean Value: {mean_val}")
    
    # Visualization
    plt.figure(figsize=(10, 6))
    sns.lineplot(data=filtered_df, x='timestamp', y='value')
    plt.title('Temperature over Time (Room 5.12)')
    
    # Generate filename dynamically based on what the agent would do? 
    # No, the agent generates the filename in the prompt.
    # We need to match the filename the agent expects.
    # The agent passes the filename in the prompt.
    # Let's assume the agent generates a filename like 'plot_test_user_viz_...png'
    # We will capture the filename from the prompt or just hardcode one that matches the regex.
    
    # Actually, the agent generates the code. The agent's prompt contains the filename.
    # We need to extract the filename from the prompt passed to generate()
    # But here we are mocking generate().
    # So we should just pick a filename and ensure our mock returns code that uses it.
    
    plot_filename = 'plot_test_user_viz_20251217_TEST.png'
    plt.savefig(f'/app/outputs/{plot_filename}')
    print(f"PLOT_GENERATED: {plot_filename}")
"""

async def mock_generate(prompt):
    if "Generate Python code" in prompt:
        # Extract the plot filename from the prompt to ensure consistency
        import re
        match = re.search(r"outputs/({plot_.*?})", prompt) # Wait, prompt has /app/outputs/{plot_filename}
        # The prompt has: save the plot to: `/app/outputs/{plot_filename}`
        # We can just return the EXPECTED_CODE but replace the filename if needed.
        # For simplicity, let's just return the EXPECTED_CODE and hope the filename matches or we adjust.
        
        # Actually, the agent constructs the filename in Python before calling LLM.
        # We can't easily know it in the mock without parsing the prompt.
        # Let's parse the prompt to find the expected filename.
        match = re.search(r"outputs/([^`\n]+)", prompt)
        if match:
            filename = match.group(1).strip('}') # remove closing brace if captured
            # The prompt says: /app/outputs/{plot_filename} -> /app/outputs/plot_...
            # Regex: `/app/outputs/(plot_[\w\.-]+)`
            m2 = re.search(r"/app/outputs/(plot_[\w\.-]+)", prompt)
            if m2:
                filename = m2.group(1)
                return EXPECTED_CODE.replace("plot_test_user_viz_20251217_TEST.png", filename)
        
        return EXPECTED_CODE
    return "Analysis complete. The average temperature is 22.5C."

mock_manager.generate = mock_generate
mock_llm_module.llm_manager = mock_manager
mock_llm_module.LLMManager = MagicMock(return_value=mock_manager)

sys.modules['orchestrator.llm_manager'] = mock_llm_module

from orchestrator.agents.analytics_agent import AnalyticsAgent
from shared.models import ConversationState

async def test_analytics_visualization():
    print("🚀 Starting Analytics Visualization Test")
    
    # 1. Setup Dummy Data
    data_dir = os.path.join("outputs", "data")
    os.makedirs(data_dir, exist_ok=True)
    
    data_filename = "test_viz_data.json"
    local_data_path = os.path.join(data_dir, data_filename)
    
    # Create dummy temperature data for Room 5.12
    # 24 hours of data, every hour
    dummy_data = {
        "data": []
    }
    
    base_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sensor_uuid = "550e8400-e29b-41d4-a716-446655440000"
    
    import random
    for i in range(24):
        # Temperature varies between 20 and 25
        temp = 20 + (5 * math.sin(i / 24 * 2 * math.pi)) + random.uniform(-0.5, 0.5)
        timestamp = base_time.replace(hour=i).isoformat()
        dummy_data["data"].append({
            "timestamp": timestamp,
            "uuid": sensor_uuid,
            "value": round(temp, 2)
        })
        
    with open(local_data_path, "w") as f:
        json.dump(dummy_data, f)
        
    print(f"✅ Created dummy data at {local_data_path}")
    
    # 2. Initialize Agent
    agent = AnalyticsAgent()
    
    # 3. Prepare Input
    user_query = "show me the temperature variation in room 5.12 over last 1 day"
    
    state = ConversationState(
        conversation_id="test_conv_123",
        user_id="test_user_viz",
        history=[],
        user_message=user_query
    )
    
    sensor_metadata = {
        sensor_uuid: {"label": "Room 5.12 Temperature Sensor"}
    }
    
    # 4. Run Analysis
    print("🤖 Invoking Analytics Agent...")
    result = await agent.analyze(
        state=state,
        user_query=user_query,
        data=dummy_data,
        sensor_metadata=sensor_metadata,
        data_filename=data_filename
    )
    
    # 5. Verify Results
    print("\n📊 Analysis Result:")
    print(json.dumps(result, indent=2))
    
    if result["success"]:
        print("\n✅ Analysis Successful")
        
        # Check for plot in output
        formatted_response = result["formatted_response"]
        if "![Analysis Plot]" in formatted_response:
            print("✅ Plot link found in response")
            
            # Extract filename
            import re
            match = re.search(r"static/(plot_[\w\.-]+)", formatted_response)
            if match:
                plot_filename = match.group(1)
                local_plot_path = os.path.join("outputs", plot_filename)
                
                if os.path.exists(local_plot_path):
                    print(f"✅ Plot file exists locally at: {local_plot_path}")
                else:
                    print(f"❌ Plot file NOT found at: {local_plot_path}")
            else:
                print("❌ Could not extract plot filename from response")
        else:
            print("❌ No plot link in response")
    else:
        print(f"❌ Analysis Failed: {result.get('error')}")

import math

if __name__ == "__main__":
    asyncio.run(test_analytics_visualization())
