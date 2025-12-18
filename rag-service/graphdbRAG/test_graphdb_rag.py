"""
Test script for GraphDB RAG Pipeline
Tests the complete flow: GraphDB Similarity Index -> Entity Context -> LLM SPARQL Generation
"""
import asyncio
import sys
from pathlib import Path
import importlib.util

# Add parent directory to path
SCRIPT_DIR = Path(__file__).parent.absolute()
sys.path.append(str(SCRIPT_DIR))

# Import the module with space in filename
spec = importlib.util.spec_from_file_location(
    "Get_llm_response",
    SCRIPT_DIR / "Get llm response.py"
)
get_llm_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(get_llm_module)

run_debug_test = get_llm_module.run_debug_test


async def main():
    """Run test queries against GraphDB RAG pipeline"""
    
    print("=" * 80)
    print("GraphDB RAG Pipeline Test Suite")
    print("=" * 80)
    print("\nThis test will:")
    print("1. Query GraphDB similarity index for relevant entities")
    print("2. Retrieve entity context (labels, types, descriptions)")
    print("3. Send context to GPT-4o-mini to generate SPARQL query")
    print("=" * 80)
    
    # Test queries
    test_queries = [
        "Air quality level in room 5.26",
        "What temperature sensors are in room 5.01?",
        "How many CO2 sensors are there in the building?",
        "Show me all oxygen sensors",
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n\n{'#' * 80}")
        print(f"TEST {i}/{len(test_queries)}")
        print(f"{'#' * 80}")
        
        await run_debug_test(query)
        
        if i < len(test_queries):
            print("\n" + "=" * 80)
            input("Press Enter to continue to next test...")
    
    print("\n\n" + "=" * 80)
    print("✅ All tests completed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
