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
os.environ["REDIS_HOST"] = "localhost"
os.environ["RAG_SERVICE_HOST"] = "localhost"
os.environ["CODE_EXECUTOR_HOST"] = "localhost"
os.environ["CODE_EXECUTOR_PORT"] = "8002"
os.environ["CODE_EXECUTOR_HOST"] = "localhost"
os.environ["CODE_EXECUTOR_PORT"] = "8002"

from orchestrator.workflow import WorkflowOrchestrator
from shared.models import ConversationState, Message
from orchestrator.llm_manager import llm_manager
from shared.structured_logger import setup_structured_logging
import uuid

# Setup structured logging
setup_structured_logging("debug_output.jsonl")

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
    
    return final_state

async def run_debug():
    """Run debug with multiple questions"""
    print("\n" + "="*100)
    print("UNIFIED AGENT DEBUG SESSION")
    print("="*100)
    
    print("\n⚙️  Initializing workflow orchestrator...")
    workflow = WorkflowOrchestrator()
    print("✅ Workflow ready!\n")
    
    # Define test questions
    questions = [
        "What is the current temperature of Air_Temperature_Sensor_5.04?", # Should use SPARQL -> Analytics
        "What is the address of the Abacws building?" # Should use SPARQL or Semantic Fallback
    ]
    
    results = []
    
    for i, question in enumerate(questions, 1):
        result = await debug_single_query(workflow, i, question)
        results.append(result)
        
        # Add pause between questions for readability
        if i < len(questions):
            print("\n" + "="*100)
            print("Preparing next question...")
            print("="*100 + "\n")
            await asyncio.sleep(1)
    
    print("\n" + "="*100)
    print("FINAL SUMMARY")
    print("="*100)
    
    for i, (question, result) in enumerate(zip(questions, results), 1):
        print(f"\nQ{i}: {question}")
        if result.messages and result.messages[-1].role == "assistant":
            print(f"A{i}: {result.messages[-1].content}")
        else:
            print(f"A{i}: ❌ No response generated")
        
        # Check intent detection results
        if "llm_intent" in result.intermediate_results:
            print(f"Intent: {result.intermediate_results['llm_intent'].get('intent')}")
            
        # Check SPARQL/Semantic method
        if "sparql_result" in result.intermediate_results:
            method = result.intermediate_results["sparql_result"].get("method", "unknown")
            print(f"Method: {method}")

    print("\n" + "="*100)
    print("LOG ANALYSIS (from debug_output.jsonl)")
    print("="*100)
    
    try:
        with open("debug_output.jsonl", "r", encoding="utf-8") as f:
            logs = [json.loads(line) for line in f]
            
        # Filter for key events
        unified_logs = [l for l in logs if "Using Unified Ontology Agent" in l.get("message", "")]
        fallback_logs = [l for l in logs if "attempting semantic fallback" in l.get("message", "")]
        
        print(f"\n📊 Metrics:")
        print(f"   • Unified Agent Calls: {len(unified_logs)}")
        print(f"   • Semantic Fallbacks: {len(fallback_logs)}")
            
    except Exception as e:
        print(f"❌ Failed to analyze logs: {e}")

if __name__ == "__main__":
    asyncio.run(run_debug())
