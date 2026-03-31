import sys
from pathlib import Path
import os
import time
import httpx
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SCRIPT_DIR = Path(__file__).parent.absolute()
OPENAI_MODEL = "gpt-4o-mini"  # Using GPT-4o-mini model
GRAPHDB_URL = "http://localhost:7200"
GRAPHDB_REPOSITORY = "bldg"
SIMILARITY_INDEX = "bldg_index"

# Logging configuration - Set to False for detailed verbose output, True for truncated logs
TRUNCATE_LOGS = True  # Change to True for minimal logs

# Add SCRIPT_DIR to sys.path
sys.path.append(str(SCRIPT_DIR))

# Import prompt template
try:
    from src.ontology_prompts import create_sparql_generation_prompt
except ImportError:
    print("❌ Could not import src.ontology_prompts. Make sure you are running this from the correct directory.")
    sys.exit(1)

# --- Helper Data ---
PREFIXES_HEADER = """
PREFIX rec: <https://w3id.org/rec#>
PREFIX sh: <http://www.w3.org/ns/shacl#>
PREFIX bsh: <https://brickschema.org/schema/BrickShape#>
PREFIX ashrae: <http://data.ashrae.org/standard223#>
PREFIX schema: <http://schema.org/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX tag: <https://brickschema.org/schema/BrickTag#>
PREFIX xml: <http://www.w3.org/XML/1998/namespace>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>
PREFIX qudt: <http://qudt.org/schema/qudt/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX sosa: <http://www.w3.org/ns/sosa/>
PREFIX unit: <http://qudt.org/vocab/unit/>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>
PREFIX qudtqk: <http://qudt.org/vocab/quantitykind/>
PREFIX dcterms: <http://purl.org/dc/terms/>
"""

# Namespace prefix mappings
NAMESPACE_PREFIXES = {
    'https://brickschema.org/schema/Brick#': 'brick:',
    'http://abacwsbuilding.cardiff.ac.uk/abacws#': 'bldg:',
    'https://w3id.org/rec#': 'rec:',
    'http://www.w3.org/2000/01/rdf-schema#': 'rdfs:',
    'http://www.w3.org/1999/02/22-rdf-syntax-ns#': 'rdf:',
    'http://www.w3.org/2002/07/owl#': 'owl:',
    'http://www.w3.org/2004/02/skos/core#': 'skos:',
    'http://www.w3.org/ns/sosa/': 'sosa:',
    'http://www.w3.org/2001/XMLSchema#': 'xsd:',
    'https://brickschema.org/schema/BrickTag#': 'tag:',
    'http://data.ashrae.org/standard223#': 'ashrae:',
    'http://data.ashrae.org/bacnet/2020#': 'bacnet:',
    'http://schema.org/': 'schema:',
    'http://purl.org/dc/terms/': 'dcterms:',
    'https://brickschema.org/schema/Brick/ref#': 'ref:',
    'http://qudt.org/schema/qudt/': 'qudt:',
    'http://qudt.org/vocab/unit/': 'unit:',
    'http://qudt.org/vocab/quantitykind/': 'qudtqk:',
    'http://www.w3.org/ns/shacl#': 'sh:',
    'https://brickschema.org/schema/BrickShape#': 'bsh:',
}

def uri_to_prefix(uri: str) -> str:
    """
    Convert a full URI to prefixed notation.
    
    Args:
        uri: Full URI string
        
    Returns:
        Prefixed URI (e.g., brick:Temperature_Sensor) or original URI if no match
    """
    for namespace, prefix in NAMESPACE_PREFIXES.items():
        if uri.startswith(namespace):
            return prefix + uri.replace(namespace, "")
    return uri

async def query_graphdb_similarity_index(search_term: str, top_k: int = 20, verbose: bool = True) -> list:
    """
    Query GraphDB similarity index to retrieve top entities matching the search term.
    
    Args:
        search_term: Natural language query
        top_k: Number of top entities to retrieve
        verbose: If True, show detailed logs including full SPARQL query
    
    Returns:
        List of entity URIs (without scores)
    """
    similarity_query = f"""
PREFIX : <http://www.ontotext.com/graphdb/similarity/>
PREFIX inst: <http://www.ontotext.com/graphdb/similarity/instance/>

SELECT ?entity (MAX(?score) AS ?bestScore)
WHERE {{
    ?search a inst:{SIMILARITY_INDEX} ;
            :searchTerm "{search_term}" ;
            :documentResult ?result .
    ?result :value ?entity ;
            :score ?score .
}}
GROUP BY ?entity
ORDER BY DESC(?bestScore)
LIMIT {top_k}
"""
    
    if verbose:
        print(f"\n{'─'*80}")
        print("📋 SIMILARITY SEARCH SPARQL QUERY:")
        print(f"{'─'*80}")
        print(similarity_query)
        print(f"{'─'*80}\n")
    
    sparql_endpoint = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                sparql_endpoint,
                params={"query": similarity_query},
                headers={"Accept": "application/sparql-results+json"}
            )
            response.raise_for_status()
            
            data = response.json()
            entities = []
            
            if verbose:
                print(f"📊 RAW GRAPHDB RESPONSE:")
                print(f"{'─'*80}")
                import json
                print(json.dumps(data, indent=2))
                print(f"{'─'*80}\n")
            
            if "results" in data and "bindings" in data["results"]:
                for binding in data["results"]["bindings"]:
                    if "entity" in binding:
                        entity_uri = binding["entity"]["value"]
                        entities.append(entity_uri)
            
            print(f"✅ Retrieved {len(entities)} entities from GraphDB similarity index")
            
            if verbose:
                print(f"\n📝 EXTRACTED ENTITY URIs:")
                print(f"{'─'*80}")
                for i, entity in enumerate(entities, 1):
                    print(f"  {i:2d}. {entity}")
                print(f"{'─'*80}\n")
            
            return entities
            
    except Exception as e:
        print(f"❌ Error querying GraphDB similarity index: {e}")
        if verbose:
            import traceback
            print(f"\n🔍 FULL ERROR TRACEBACK:")
            print(f"{'─'*80}")
            traceback.print_exc()
            print(f"{'─'*80}\n")
        return []


async def get_entity_context(entities: list, verbose: bool = True) -> str:
    """
    Retrieve entity labels, types, and descriptions for context building.
    Returns individual entity-type combinations with prefixed URIs for richer context.
    
    Args:
        entities: List of entity URIs (top-k from similarity search)
        verbose: If True, show detailed logs including full SPARQL query and results
        
    Returns:
        Formatted context string for LLM with all entity-type combinations
    """
    if not entities:
        return ""
    
    # Build VALUES clause for filtering
    values_clause = "VALUES ?entity { " + " ".join([f"<{entity}>" for entity in entities]) + " }"
    
    context_query = f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>

SELECT ?entity ?label ?type ?comment
WHERE {{
    {values_clause}
    OPTIONAL {{ ?entity rdfs:label ?label . }}
    OPTIONAL {{ ?entity rdf:type ?type . }}
    OPTIONAL {{ ?entity rdfs:comment ?comment . }}
}}
"""
    
    if verbose:
        print(f"\n{'─'*80}")
        print("📋 CONTEXT RETRIEVAL SPARQL QUERY:")
        print(f"{'─'*80}")
        print(context_query)
        print(f"{'─'*80}\n")
    
    sparql_endpoint = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                sparql_endpoint,
                params={"query": context_query},
                headers={"Accept": "application/sparql-results+json"}
            )
            response.raise_for_status()
            
            data = response.json()
            
            if verbose:
                print(f"📊 RAW CONTEXT RESPONSE:")
                print(f"{'─'*80}")
                import json
                print(json.dumps(data, indent=2))
                print(f"{'─'*80}\n")
            
            # Use set to track unique entity-type combinations
            seen_combinations = set()
            context_parts = []
            
            if "results" in data and "bindings" in data["results"]:
                for binding in data["results"]["bindings"]:
                    entity_uri = binding.get("entity", {}).get("value", "")
                    label = binding.get("label", {}).get("value", "")
                    type_uri = binding.get("type", {}).get("value", "")
                    comment = binding.get("comment", {}).get("value", "")
                    
                    if not entity_uri:
                        continue
                    
                    # Create unique combination key
                    combo_key = (entity_uri, type_uri)
                    
                    # Skip if we've already seen this exact combination
                    if combo_key in seen_combinations:
                        continue
                    
                    seen_combinations.add(combo_key)
                    
                    # Convert URIs to prefixes
                    entity_prefixed = uri_to_prefix(entity_uri)
                    type_prefixed = uri_to_prefix(type_uri) if type_uri else ""
                    
                    # Build individual entity-type entry
                    context_entry = f"Entity: {entity_prefixed}\n"
                    
                    if label:
                        context_entry += f"Label: {label}\n"
                    
                    if type_prefixed:
                        context_entry += f"Type: {type_prefixed}\n"
                    
                    if comment:
                        context_entry += f"Description: {comment}\n"
                    
                    context_parts.append(context_entry)
            
            context_text = "\n".join(context_parts)
            print(f"✅ Built context for {len(context_parts)} entity-type combinations from {len(entities)} retrieved entities")
            
            if verbose:
                print(f"\n📝 FULL CONSTRUCTED CONTEXT:")
                print(f"{'─'*80}")
                print(context_text)
                print(f"{'─'*80}\n")
            
            return context_text
            
    except Exception as e:
        print(f"❌ Error retrieving entity context: {e}")
        if verbose:
            import traceback
            print(f"\n🔍 FULL ERROR TRACEBACK:")
            print(f"{'─'*80}")
            traceback.print_exc()
            print(f"{'─'*80}\n")
        return ""

# --- Main Test Logic ---

async def run_debug_test(question, truncate: bool = None):
    """
    Run the complete GraphDB RAG pipeline test.
    
    Args:
        question: Natural language query
        truncate: If True, show minimal logs. If False, show detailed verbose logs.
                 If None, uses global TRUNCATE_LOGS setting.
    """
    # Use global setting if not specified
    verbose = not truncate if truncate is not None else not TRUNCATE_LOGS
    
    print(f"\n{'='*80}")
    print(f"🧪 TESTING GraphDB RAG PIPELINE")
    print(f"{'='*80}")
    print(f"📋 Question: {question}")
    print(f"🔧 Verbose Mode: {'ON' if verbose else 'OFF'}")
    print(f"{'='*80}\n")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found.")
        return

    # 1. Query GraphDB Similarity Index
    print(f"\n{'🔍 STEP 1: GRAPHDB SIMILARITY INDEX SEARCH':^80}")
    print(f"{'='*80}")
    print(f"Query: '{question}'")
    print(f"Top-K: 20")
    print(f"{'─'*80}")
    
    entities = await query_graphdb_similarity_index(question, top_k=20, verbose=verbose)
    
    if not entities:
        print("❌ No entities retrieved from similarity index")
        return
    
    # Show retrieved entities (always show summary, detailed list only if verbose)
    print(f"\n📊 RETRIEVED ENTITIES SUMMARY:")
    print(f"{'─'*80}")
    print(f"Total entities retrieved: {len(entities)}")
    
    if verbose:
        print(f"\nAll entities with prefixes:")
        for i, entity in enumerate(entities, 1):
            entity_prefixed = uri_to_prefix(entity)
            print(f"  {i:2d}. {entity_prefixed}")
    else:
        print(f"\nTop 10 entities (with prefixes):")
        for i, entity in enumerate(entities[:10], 1):
            entity_prefixed = uri_to_prefix(entity)
            print(f"  {i:2d}. {entity_prefixed}")
        if len(entities) > 10:
            print(f"  ... and {len(entities) - 10} more")
    print(f"{'─'*80}")

    # 2. Get Entity Context
    print(f"\n{'📊 STEP 2: ENTITY CONTEXT RETRIEVAL':^80}")
    print(f"{'='*80}")
    print(f"Fetching labels, types, and descriptions for {len(entities)} entities...")
    print(f"{'─'*80}")
    
    context_text = await get_entity_context(entities, verbose=verbose)
    
    if not context_text:
        print("⚠️ No context retrieved, using entity URIs only")
        context_text = "\n".join([f"Entity: {entity}" for entity in entities])
    
    if not verbose:
        print(f"\n📄 CONTEXT PREVIEW (First 800 chars):")
        print(f"{'─'*80}")
        print(context_text[:800])
        if len(context_text) > 800:
            print("...")
        print(f"{'─'*80}")
    # Full context already shown in verbose mode by get_entity_context()

    # 3. Prompt Construction
    print(f"\n{'📝 STEP 3: LLM PROMPT CONSTRUCTION':^80}")
    print(f"{'='*80}")
    print(f"Creating SPARQL generation prompt with context...")
    print(f"{'─'*80}")
    
    sparql_prompt = create_sparql_generation_prompt()
    
    # Format the prompt to see exactly what goes to the LLM
    formatted_prompt = sparql_prompt.format(
        user_query=question,
        graphrag_context=context_text,
        prefixes=PREFIXES_HEADER
    )
    
    if verbose:
        print(f"\n📨 FULL PROMPT SENT TO LLM:")
        print(f"{'─'*80}")
        print(formatted_prompt)
        print(f"{'─'*80}")
    else:
        print(f"\n📨 PROMPT PREVIEW (First 1500 chars):")
        print(f"{'─'*80}")
        print(formatted_prompt[:1500])
        if len(formatted_prompt) > 1500:
            print("...")
        print(f"{'─'*80}")
    
    print(f"\nPrompt Statistics:")
    print(f"  - Total length: {len(formatted_prompt)} characters")
    print(f"  - Estimated tokens: ~{len(formatted_prompt) // 4}")

    # 4. LLM Generation
    print(f"\n{'🤖 STEP 4: LLM SPARQL GENERATION':^80}")
    print(f"{'='*80}")
    print(f"Model: {OPENAI_MODEL}")
    print(f"Temperature: 0 (deterministic)")
    print(f"{'─'*80}")
    print("Sending request to OpenAI API...")
    
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, api_key=api_key)
    chain = sparql_prompt | llm | StrOutputParser()
    
    start_time = time.time()
    response = chain.invoke({
        "user_query": question, 
        "graphrag_context": context_text,
        "prefixes": PREFIXES_HEADER
    })
    end_time = time.time()

    print(f"✅ Response received in {end_time - start_time:.2f}s")
    
    print(f"\n{'📤 FINAL SPARQL QUERY OUTPUT':^80}")
    print(f"{'='*80}")
    print(response)
    print(f"{'='*80}")
    
    # Summary
    print(f"\n{'✅ PIPELINE EXECUTION SUMMARY':^80}")
    print(f"{'='*80}")
    print(f"Question: {question}")
    print(f"Entities Retrieved: {len(entities)}")
    print(f"Context Size: {len(context_text)} characters ({len(context_text.splitlines())} lines)")
    print(f"LLM Response Time: {end_time - start_time:.2f}s")
    print(f"Verbose Mode: {'ON' if verbose else 'OFF'}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    import asyncio
    
    # Test question
    test_query = "Air quality level in room 5.26"
    
    # Run async test
    # Change TRUNCATE_LOGS at top of file to switch between verbose/minimal modes
    # Or pass truncate parameter: asyncio.run(run_debug_test(test_query, truncate=True))
    asyncio.run(run_debug_test(test_query))


