import asyncio
import sys
import os
import json
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

# Load environment variables
load_dotenv()

# Override for local debugging
os.environ["GRAPHDB_HOST"] = "localhost"
os.environ["QDRANT_HOST"] = "localhost"
os.environ["MYSQL_HOST"] = "localhost"
os.environ["MYSQL_PORT"] = "3307" # Mapped port for mysql-bldg1
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5433" # Mapped port for postgres-user-data
os.environ["REDIS_HOST"] = "localhost"
os.environ["REDIS_URL"] = "redis://localhost:6379/0" # Explicitly set URL
os.environ["RAG_SERVICE_HOST"] = "localhost"
os.environ["CODE_EXECUTOR_HOST"] = "localhost"
os.environ["CODE_EXECUTOR_PORT"] = "8002"
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11435" # Mapped port for ollama

from orchestrator.workflow import WorkflowOrchestrator
from shared.models import ConversationState, Message
from orchestrator.llm_manager import llm_manager
from shared.structured_logger import setup_structured_logging
import uuid

# Setup structured logging
setup_structured_logging("debug_output_viz.jsonl")

# Capture LLM interactions
llm_logs = []
original_generate = llm_manager.generate

async def captured_generate(prompt, *args, **kwargs):
    llm_logs.append({"prompt": prompt})
    response = await original_generate(prompt, *args, **kwargs)
    llm_logs[-1]["response"] = response
    return response

llm_manager.generate = captured_generate

def print_section_header(section_num, title):
    """Print formatted section header"""
    print("\n" + "="*80)
    print(f"[{section_num}] {title}")
    print("="*80)

async def debug_single_query(workflow, query_num, user_query):
    """Debug a single query and print detailed results"""
    print("\n" + "#"*100)
    print(f"{'#'*40} QUESTION {query_num} {'#'*40}")
    print("#"*100)
    print(f"\n📝 Query: {user_query}\n")
    
    # Clear previous logs
    llm_logs.clear()
    
    state = ConversationState(
        conversation_id=str(uuid.uuid4()),
        user_id="test_user_viz",
        user_message=user_query,
        messages=[Message(role="user", content=user_query)],
        building="building1",
        persona="stakeholder"
    )
    
    print("⏳ Executing workflow...\n")
    final_state = await workflow.execute(state)
    
    print("\n" + "="*80)
    print(f"✅ QUESTION {query_num} COMPLETED")
    print("="*80 + "\n")
    
    # Check for visualization
    if hasattr(final_state, "response") and final_state.response:
        print("Response:", final_state.response)
        if "![Analysis Plot]" in final_state.response:
            print("\n🎉 SUCCESS: Visualization link found in response!")
        else:
            print("\n⚠️ WARNING: No visualization link found.")
    
    return final_state

async def run_debug():
    """Run debug with visualization question"""
    print("\n" + "="*100)
    print("VISUALIZATION WORKFLOW TEST")
    print("="*100)
    
    print("\n⚙️  Initializing workflow orchestrator...")
    try:
        workflow = WorkflowOrchestrator()
        print("✅ Workflow ready!\n")
    except Exception as e:
        print(f"❌ Failed to initialize workflow: {e}")
        return
    
    # Define test question
    # "show me the temperature variation in room 5.12 over last 1 day"
    # This requires:
    # 1. Intent -> Analytics
    # 2. SQL -> Fetch data for Room 5.12 (Air_Temperature_Sensor_5.12 or similar)
    # 3. Analytics -> Generate plot
    
    # Note: We need to ensure the sensor exists in MySQL.
    # Based on previous context, 'Air_Temperature_Sensor_5.12' might not exist, but 'Air_Temperature_Sensor_5.04' does.
    # Let's use a known sensor or a generic query.
    # "room 5.12" might map to a sensor if the mapping is good.
    # Let's try "Air_Temperature_Sensor_5.04" to be safe, or stick to the user's query if we trust the mapping.
    # The user asked for "room 5.12". Let's try that first.
    
    questions = [
        "show me the temperature variation in room 5.12 over last 1 day"
    ]
    
    results = []
    
    for i, question in enumerate(questions, 1):
        result = await debug_single_query(workflow, i, question)
        results.append(result)

if __name__ == "__main__":
    asyncio.run(run_debug())
