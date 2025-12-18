"""
SPARQL Agent - Ontology query generation with RAG
"""
import sys
sys.path.append('/app')

import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List
import re
import json
from shared.models import ConversationState
from shared.utils import get_logger, extract_sparql_from_llm_response, validate_sparql_syntax, generate_hash
from shared.config import settings
from orchestrator.llm_manager import llm_manager
from orchestrator.agents.dialogue_agent import format_conversation_history
from orchestrator.redis_manager import redis_manager

logger = get_logger(__name__)

RAG_SERVICE_URL = f"http://{settings.RAG_SERVICE_HOST}:{settings.RAG_SERVICE_PORT}"
# GraphDB SPARQL endpoint (new architecture)
GRAPHDB_QUERY_ENDPOINT = f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}/repositories/{settings.GRAPHDB_REPOSITORY}"
# Fuseki fallback endpoint
_base_fuseki = settings.FUSEKI_URL.rstrip('/')
FUSEKI_QUERY_ENDPOINT = _base_fuseki + ("/query" if not _base_fuseki.endswith('/query') else "")

# Ensure GraphDB endpoint is correct
if not settings.GRAPHDB_HOST:
    settings.GRAPHDB_HOST = "graphdb"
if not settings.GRAPHDB_PORT:
    settings.GRAPHDB_PORT = 7200
if not settings.GRAPHDB_REPOSITORY:
    settings.GRAPHDB_REPOSITORY = "bldg"

GRAPHDB_QUERY_ENDPOINT = f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}/repositories/{settings.GRAPHDB_REPOSITORY}"

EXTENDED_PREFIXES = [
    'PREFIX br: <http://vocab.deri.ie/br#>',
    'PREFIX bl: <https://w3id.org/biolink/vocab/>',
    'PREFIX bld: <http://biglinkeddata.com/>',
    'PREFIX brick: <https://brickschema.org/schema/Brick#>',
    'PREFIX dcterms: <http://purl.org/dc/terms/>',
    'PREFIX owl: <http://www.w3.org/2002/07/owl#>',
    'PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>',
    'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>',
    'PREFIX sh: <http://www.w3.org/ns/shacl#>',
    'PREFIX skos: <http://www.w3.org/2004/02/skos/core#>',
    'PREFIX sosa: <http://www.w3.org/ns/sosa/>',
    'PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>',
    'PREFIX tag: <https://brickschema.org/schema/BrickTag#>',
    'PREFIX bsh: <https://brickschema.org/schema/BrickShape#>',
    'PREFIX s223: <http://data.ashrae.org/standard223#>',
    'PREFIX ashrae: <http://data.ashrae.org/standard223#>',
    'PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>',
    'PREFIX g36: <http://data.ashrae.org/standard223/1.0/extensions/g36#>',
    'PREFIX qkdv: <http://qudt.org/vocab/dimensionvector/>',
    'PREFIX quantitykind: <http://qudt.org/vocab/quantitykind/>',
    'PREFIX qudt: <http://qudt.org/schema/qudt/>',
    'PREFIX rec: <https://w3id.org/rec#>',
    'PREFIX ref: <https://brickschema.org/schema/Brick/ref#>',
    'PREFIX s223tobrick: <https://brickschema.org/extension/brick_extension_interpret_223#>',
    'PREFIX schema1: <http://schema.org/>',
    'PREFIX unit: <http://qudt.org/vocab/unit/>',
    'PREFIX vcard: <http://www.w3.org/2006/vcard/ns#>',
    'PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>'
]

class SPARQLAgent:
    """Generates and executes SPARQL queries with RAG support"""
    
    def __init__(self):
        self.max_retries = 3
        self._instance_cache: Dict[str, List[str]] = {}
    
    async def _reason_over_ontology(
        self,
        user_query: str,
        context: List[str]
    ) -> Dict[str, Any]:
        """
        Use LLM to reason over retrieved ontology fragments and answer question directly
        (Semantic Fallback)
        """
        # Build context from ontology fragments
        context_text = "\n".join(context)
        
        if not context_text.strip():
            context_text = "No relevant ontology information found."
        
        # Build reasoning prompt
        reasoning_prompt = f"""You are an expert at understanding building ontologies. Answer the user's question based ONLY on the provided ontology fragments.

User Question: "{user_query}"

Relevant Ontology Data:
{context_text}

Instructions:
1. Carefully read the ontology fragments above
2. Find the exact information the user is asking for
3. Answer concisely and accurately
4. If you find a label (rdfs:label), definition (rdfs:comment or skos:definition), or other properties, include them
5. If the information is NOT in the ontology fragments, say "I couldn't find this information in the ontology"
6. Format your answer clearly (use bold for labels, bullets for multiple items)

Your Answer:"""

        try:
            response = await llm_manager.generate(reasoning_prompt, temperature=0.1)
            return {
                "text": response.strip(),
                "confidence": "high" if len(context_text) > 100 else "low"
            }
            
        except Exception as e:
            logger.error(f"LLM reasoning error: {e}")
            return {
                "text": f"I found relevant ontology data but had trouble interpreting it: {str(e)}",
                "confidence": "low"
            }

    async def answer_semantically(
        self,
        state: ConversationState,
        user_query: str,
        context: List[str] = None
    ) -> Dict[str, Any]:
        """
        Answer using Semantic RAG (no SPARQL)
        """
        if not context:
            context = await self._retrieve_context(user_query)
            
        answer = await self._reason_over_ontology(user_query, context)
        
        return {
            "success": True,
            "query": "SEMANTIC_RAG_NO_SPARQL",
            "results": [{"answer": answer["text"]}], # Mock results for compatibility
            "formatted_response": answer["text"],
            "standardized": [],
            "context": context,
            "analytics_required": False,
            "llm_reasoning": "Semantic RAG fallback used",
            "method": "semantic_rag"
        }

    async def generate_query(
        self,
        state: ConversationState,
        user_query: str
    ) -> Dict[str, Any]:

        """
        Generate SPARQL query using RAG
        
        Returns:
            Dict with 'query', 'explanation', 'context'
        """
        try:
            # Attempt deterministic template first (avoids LLM latency for common patterns)
            context = await self._retrieve_context(user_query)
            
            # NEW: Check intent for direct semantic answer (skip SPARQL)
            intent = state.intermediate_results.get("intent", "metadata")
            if intent == "general_knowledge":
                logger.info("Intent is general_knowledge (building), using Semantic RAG directly")
                return await self.answer_semantically(state, user_query, context)

            # Extract explicit entity references first
            # NEW: Use entities from DialogueAgent if available
            entities = state.intermediate_results.get("entities", [])
            if not entities:
                entities = self._extract_entities(user_query)
            else:
                logger.info(f"Using entities extracted by DialogueAgent: {entities}")
            # Derive class target (reuse mapping logic)
            class_target = self._infer_class(user_query.lower())
            instance_candidates = []
            if not entities and class_target:
                # attempt instance discovery before LLM
                try:
                    instance_candidates = await self._get_instances_for_class(class_target, limit=40)
                    if not instance_candidates:
                        # fallback pattern search
                        pattern_candidates = await self._pattern_instance_search(class_target, limit=40)
                        instance_candidates.extend(pattern_candidates)
                    if instance_candidates:
                        logger.info(f"Discovered {len(instance_candidates)} instance candidates for {class_target}")
                except Exception as e:
                    logger.warning(f"Instance candidate discovery failed: {e}")
            
            # Disable template SPARQL per user requirement
            # sparql_query = self._template_sparql(user_query, entities)
            sparql_query = None
            
            used_template = sparql_query is not None
            # Default analytics decision for template queries
            # Most sensor queries need analytics=True because users want DATA/VALUES
            analytics_required = self._should_require_analytics(user_query, entities)
            llm_reasoning = "Template-based query - analytics decision heuristic"
            
            # Format conversation history for context
            conversation_history = format_conversation_history(state.messages, max_messages=5)
            logger.info("─" * 80)
            logger.info("SPARQL AGENT: Conversation History")
            logger.info("─" * 80)
            if conversation_history and conversation_history != "(No previous conversation)":
                logger.info(f"📜 Including conversation context:\n{conversation_history}")
            else:
                logger.info("📜 No previous conversation context")
            logger.info("─" * 80)
            
            if sparql_query is None:
                logger.info("🤖 Using LLM to generate SPARQL query with conversation context")
                # LLM generation - returns dict with sparql, analytics, reasoning
                llm_result = await self._generate_sparql(user_query, context, instance_candidates, class_target, conversation_history)
                sparql_query = llm_result["sparql"]
                analytics_required = llm_result["analytics"]
                llm_reasoning = llm_result.get("reasoning", "")
                logger.info(f"✅ LLM determined: analytics_required={analytics_required}")
                logger.info(f"💭 LLM reasoning: {llm_reasoning}")
            else:
                logger.info(f"Using template SPARQL (entities={entities}):")
                logger.info(sparql_query)
            
            # Step 3: Legacy-style postprocessing fixes (spacing/prefix issues) then validate
            sparql_query = self._postprocess_query(sparql_query)
            # Ensure required prefixes present (legacy add_sparql_prefixes behavior)
            sparql_query = self._ensure_prefixes(sparql_query)
            # Step 4: Validate syntax
            if not validate_sparql_syntax(sparql_query):
                logger.warning("Generated SPARQL has syntax errors, attempting repair")
                sparql_query = await self._repair_query(sparql_query, user_query, context)

            logger.info("Final SPARQL to execute:\n" + sparql_query)
            
            # Step 5: Execute query
            results = await self._execute_query(sparql_query)
            
            # NEW: Fallback if no results
            has_results = False
            if results and isinstance(results, dict):
                bindings = results.get("results", {}).get("bindings", [])
                has_results = len(bindings) > 0
            
            if not has_results:
                logger.warning("SPARQL returned no results, attempting semantic fallback")
                return await self.answer_semantically(state, user_query, context)
            
            # Step 6: Standardize + Format results
            standardized = self._standardize_results(results, user_query, sparql_query)
            formatted = await self._format_results(results, user_query, sparql_query, used_template)
            
            return {
                "success": True,
                "query": sparql_query,
                "results": results,
                "formatted_response": formatted,
                "standardized": standardized,
                "context": context,
                "analytics_required": analytics_required,  # NEW: Flag for further analysis
                "llm_reasoning": llm_reasoning  # NEW: LLM's reasoning about analytics decision
            }
            
        except Exception as e:
            logger.error(f"SPARQL generation error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "query": None,
                "results": None
            }
    
    async def _retrieve_context(self, query: str) -> List[str]:
        """
        🧠 GRAPHDB RAG RETRIEVAL (New Architecture)
        
        Uses GraphDB's 2-step Ontotext technique:
        1. Vector similarity search returns entity IRIs
        2. SPARQL fetches bounded context (triples around entities)
        
        Returns: List of context strings with prefixes and triples for SPARQL generation
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Use GraphDB RAG endpoint
                try:
                    logger.info(f"🔍 Using GraphDB RAG retrieval for: {query[:100]}")
                    
                    graphdb_response = await client.post(
                        f"{RAG_SERVICE_URL}/graphdb/retrieve",
                        json={
                            "query": query,
                            "top_k": 10,  # Entity retrieval limit
                            "hops": 2,    # Graph traversal depth
                            "min_score": 0.3  # Similarity threshold
                        }
                    )
                    graphdb_response.raise_for_status()
                    graphdb_data = graphdb_response.json()
                    
                    # Extract structured context
                    if graphdb_data.get("status") == "success":
                        logger.info(f"✅ GraphDB RAG successful:")
                        logger.info(f"   - Entities: {graphdb_data['metadata']['entity_count']}")
                        logger.info(f"   - Triples: {graphdb_data['metadata']['triple_count']}")
                        
                        # Build context for SPARQL generation
                        prefix_declarations = graphdb_data.get('prefix_declarations', '')
                        summary = graphdb_data.get('summary', '')
                        triples = graphdb_data.get('triples', [])
                        
                        # Format triples for LLM
                        triple_text = "\n".join([
                            f"  {t['subject']} {t['predicate']} {t['object']} ."
                            for t in triples[:50]  # Limit to prevent token explosion
                        ])
                        
                        # Build unified context
                        context_text = f"""=== GRAPHDB KNOWLEDGE BASE ===

PREFIXES:
{prefix_declarations}

{summary}

TRIPLES (Graph Structure):
{triple_text}
"""
                        
                        return [context_text]
                    
                    logger.warning("GraphDB RAG returned unsuccessful status")
                    return []
                    
                except Exception as e:
                    logger.warning(f"GraphDB RAG failed: {e}")
                    return []
                
        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")
            return []
                
        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")
            return []
    
    async def _generate_sparql(self, user_query: str, context: List[str], candidates: List[str], class_target: Optional[str], conversation_history: str = "") -> Dict[str, Any]:
        """
        Generate SPARQL query using LLM with Brick Schema context
        
        Args:
            user_query: The current user query
            context: RAG context from knowledge graph
            candidates: Candidate instances
            class_target: Target class (if identified)
            conversation_history: Formatted conversation history for context
        
        Returns:
            Dict with:
                - 'sparql': str - The SPARQL query
                - 'analytics': bool - Whether further analysis is needed after SPARQL execution
                - 'reasoning': str - LLM's reasoning about whether exact answer exists in context
        """
        
        # Get current time in UK timezone
        try:
            uk_time = datetime.now(ZoneInfo("Europe/London"))
            current_time_str = uk_time.strftime("%A, %B %d, %Y, %H:%M %Z")
        except Exception:
            current_time_str = datetime.now().strftime("%A, %B %d, %Y, %H:%M (UTC)")
        
        # Check if we have a unified smart context (starts with header)
        is_smart_context = len(context) > 0 and "=== ONTOLOGY KNOWLEDGE BASE ===" in context[0]
        
        # Add conversation history section if available
        history_section = f"\n\n=== CONVERSATION HISTORY ===\n{conversation_history}\n" if conversation_history and conversation_history != "(No previous conversation)" else ""
        
        if is_smart_context:
            # Use the pre-built unified context directly
            full_context = "\n\n".join(context)
            sparql_prompt = f"""Given a natural language query about a building and context from GraphRAG knowledge graph, generate an accurate SPARQL query using correct RDF prefixes.
Current Date and Time: {current_time_str}

=== GRAPHRAG CONTEXT ===
{full_context}{history_section}

=== USER QUERY ===
{user_query}

NOTE: If this query references previous results (e.g., "give me all", "detailed list", "show everything"), use the conversation history to understand what was previously requested and expand on it.

=== OUTPUT FORMAT ===
Respond with JSON containing exactly TWO keys:

1. "analytics" (boolean) - Determines if SPARQL results need further processing:
   
   FALSE = Query is about METADATA (structural information already in ontology):
   - "List all sensors" → Just entity names/types
   - "Where is sensor X located?" → Location property from ontology
   - "What equipment in zone Y?" → Equipment list from ontology
   - "What is the UUID of X?" → UUID property from ontology
   
   TRUE = Query is about DATA/VALUES (requires time-series database access or analytics):
   - "What temperature sensors in room 5.01?" → Needs CURRENT temperature readings
   - "What is the CO2 level?" → Needs REAL-TIME sensor values
   - "Average temperature in building?" → Needs to COMPUTE from readings
   - "Which rooms have high CO2?" → Needs to COMPARE values against threshold
   - Any query with: "level", "reading", "value", "current", "yesterday", "trend", "average", "min", "max"
   - any computation or comparison on sensor data
   KEY INSIGHT: Most sensor queries = TRUE (users want data, not just sensor names!)

2. "sparql" (string) - The SPARQL query to execute

=== SPARQL GENERATION RULES ===

1. Analyze the query to identify:
   - Entities being asked about (sensors, zones, equipment)
   - Properties/relationships needed
   - Filters or conditions

2. Map to ontology concepts using context:
   - "temperature sensors" → brick:Air_Temperature_Sensor
   - "room 5.01" → bldg:Room_5.01 or filter CONTAINS "5.01"
   - "location" → brick:hasLocation property
   - "next to", "adjacent", "nearby" → rec:adjacentElement
   - "contains", "inside" → rec:containsElement or rec:locatedIn (inverse)
   - "zone", "floor" → rec:Zone, rec:Level

3. Construct query with:
   - PREFIX declarations (ONLY what's actually used)
   - SELECT clause with all needed variables
   - WHERE clause with triple patterns from context
   - FILTER clauses for conditions
   - OPTIONAL blocks for non-critical data

4. CRITICAL - External Timeseries References:
   For ANY sensor/device query, ALWAYS include UUID retrieval using the exact path from the ontology context:
   
   OPTIONAL {{
     ?sensor ref:hasExternalReference ?ref .
     ?ref ref:hasTimeseriesId ?uuid .
     ?ref ref:storedAt ?storage .
   }}
   
   Add ?uuid and ?storage to SELECT clause. This enables downstream time-series queries.
   KEY INSIGHT: when "analytics" (boolean) is TRUE, UUID and storedAt are ESSENTIAL for data retrieval!
   
   DO NOT use 'bldg:connstring' unless it explicitly appears in the context triples.

5. use only following prefixes if needed.
    'PREFIX br: <http://vocab.deri.ie/br#>',
    'PREFIX bl: <https://w3id.org/biolink/vocab/>',
    'PREFIX bld: <http://biglinkeddata.com/>',
    'PREFIX brick: <https://brickschema.org/schema/Brick#>',
    'PREFIX dcterms: <http://purl.org/dc/terms/>',
    'PREFIX owl: <http://www.w3.org/2002/07/owl#>',
    'PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>',
    'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>',
    'PREFIX sh: <http://www.w3.org/ns/shacl#>',
    'PREFIX skos: <http://www.w3.org/2004/02/skos/core#>',
    'PREFIX sosa: <http://www.w3.org/ns/sosa/>',
    'PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>',
    'PREFIX tag: <https://brickschema.org/schema/BrickTag#>',
    'PREFIX bsh: <https://brickschema.org/schema/BrickShape#>',
    'PREFIX s223: <http://data.ashrae.org/standard223#>',
    'PREFIX bacnet: <http://data.ashrae.org/bacnet/2020#>',
    'PREFIX g36: <http://data.ashrae.org/standard223/1.0/extensions/g36#>',
    'PREFIX qkdv: <http://qudt.org/vocab/dimensionvector/>',
    'PREFIX quantitykind: <http://qudt.org/vocab/quantitykind/>',
    'PREFIX qudt: <http://qudt.org/schema/qudt/>',
    'PREFIX rec: <https://w3id.org/rec#>',
    'PREFIX ref: <https://brickschema.org/schema/Brick/ref#>',
    'PREFIX s223tobrick: <https://brickschema.org/extension/brick_extension_interpret_223#>',
    'PREFIX schema1: <http://schema.org/>',
    'PREFIX unit: <http://qudt.org/vocab/unit/>',
    'PREFIX vcard: <http://www.w3.org/2006/vcard/ns#>',
    'PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>'
]

6. Use exact URIs from context. Prefer OPTIONAL for optional properties.

=== EXAMPLE OUTPUT ===

{{
  "analytics": true,
  "sparql": "PREFIX brick: <https://brickschema.org/schema/Brick#>\\nPREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>\\nPREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\\nPREFIX ref: <https://brickschema.org/schema/Brick/ref#>\\n\\nSELECT ?sensor ?location ?uuid ?storage WHERE {{\\n  BIND(bldg:CO2_Level_Sensor_5.08 AS ?sensor)\\n  OPTIONAL {{ ?sensor brick:hasLocation ?location . }}\\n  OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }}\\n}} LIMIT 50"
}}

=== STRICT REQUIREMENTS ===
- USE ONLY classes/properties from the provided context
- If specific instance URI provided in context, USE IT directly (e.g. BIND(bldg:X AS ?sensor))
- DO NOT attempt to compute averages, min/max, or retrieve time-series values (like brick:hasValue) in SPARQL.
- If analytics=true, ONLY retrieve the UUID and storage location. The analytics engine will handle the data.
- Use 'bldg:' prefix for building instances, 'brick:' for schema classes
- Escape newlines as \\n for valid JSON
- Include LIMIT clause (default 50) to prevent large result sets
- Ensure syntactically valid SPARQL (matching braces, correct syntax)

=== MANDATORY SPARQL PATTERN FOR SENSORS ===
If the query involves a specific sensor or device, you MUST generate a query matching this EXACT pattern:

PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX ashrae: <http://data.ashrae.org/standard223#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?timeseriesID ?database
WHERE {{
    ?sensor ashrae:hasExternalReference ?extRef .
    
    ?extRef ref:hasTimeseriesId ?timeseriesID ;
            ref:storedAt ?database .
            
    # Filter for the specific entity found in context/query
    FILTER(?sensor = bldg:ENTITY_NAME)
}}

Replace bldg:ENTITY_NAME with the actual URI found in the context (e.g. bldg:CO2_Level_Sensor_5.08).
Do NOT add other OPTIONAL blocks or properties.
Do NOT use 'bldg:connstring'.
Do NOT use 'ref:hasExternalReference' directly on the sensor (use ashrae:hasExternalReference).
"""
        else:
            # Fallback: Limited context available
            context_preview = "\n".join(context[:10]) if context else "No context available"
            candidate_preview = "\n".join(candidates[:30]) if candidates else "None"
            class_hint = class_target or "Unknown"
            
            sparql_prompt = f"""Given a natural language query about a building, generate SPARQL using Brick Schema.

=== AVAILABLE CONTEXT ===
{context_preview}

=== CANDIDATE INSTANCES ===
{candidate_preview}

=== TARGET CLASS ===
{class_hint}{history_section}

=== USER QUERY ===
{user_query}

NOTE: If this query references previous results (e.g., "give me all", "detailed list"), check the conversation history above.

=== OUTPUT FORMAT ===
JSON with TWO keys:

1. "analytics" (boolean):
   FALSE = Metadata query (list sensors, get UUID, show location)
   TRUE = Data query (sensor readings, current values, computations, trends)
   
   Most sensor queries need TRUE (users want data, not just names!)

2. "sparql" (string): The SPARQL query

=== SPARQL RULES ===
1. Use ONLY given prefixes.

2. For sensor queries, ALWAYS retrieve UUID and Storage Location when "analytics" (boolean): guessed TRUE
   You MUST use this EXACT pattern:
   
   ?sensor ashrae:hasExternalReference ?extRef .
   ?extRef ref:hasTimeseriesId ?timeseriesID ;
           ref:storedAt ?database .
   
   DO NOT use 'bldg:connstring'.
   DO NOT retrieve time-series data (values, timestamps) or perform aggregations (AVG, MIN, MAX) in SPARQL.
   ONLY retrieve metadata (UUID, storage).

3. Use candidate instances if available.
   - If user asks for a specific sensor by name (e.g. "Sensor_5.08"), FILTER by URI or Label:
     FILTER(CONTAINS(STR(?sensor), "5.08") || CONTAINS(STR(?label), "5.08"))
   - Ensure ?label is retrieved: OPTIONAL {{ ?sensor rdfs:label ?label }}

4. Add FILTER for specific room/zone mentions
5. Include LIMIT only when user explicitely saids so
6. Escape newlines as \\n

Example:
{{
  "analytics": true,
  "sparql": "PREFIX brick: <...>\\nPREFIX ref: <...>\\nSELECT ?sensor ?uuid ?storage WHERE {{ ?sensor rdf:type brick:Air_Temperature_Sensor . OPTIONAL {{ ?sensor ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} }}"
}}"""

        # Check cache
        prompt_hash = generate_hash(sparql_prompt)
        cache_key = f"cache:sparql_gen:{prompt_hash}"
        cached_result = await redis_manager.get_cache(cache_key)
        
        if cached_result:
            logger.info(f"✅ Cache hit for SPARQL generation: {prompt_hash}")
            return cached_result

        response = await llm_manager.generate(sparql_prompt)
        
        # Parse JSON response from LLM
        try:
            # Try to extract JSON from response (in case LLM wraps it in markdown)
            json_match = re.search(r'\{[\s\S]*"analytics"[\s\S]*"sparql"[\s\S]*\}', response)
            if json_match:
                response = json_match.group(0)
            
            parsed = json.loads(response)
            
            analytics = parsed.get("analytics", False)
            sparql = parsed.get("sparql", "")
            
            # Unescape newlines in SPARQL
            sparql = sparql.replace("\\n", "\n").replace("\\t", "\t")
            
            # Validate we got both required fields
            if not sparql:
                raise ValueError("SPARQL query is empty in LLM response")
            
            logger.info(f"LLM Analysis Decision: analytics={analytics}")
            logger.info(f"Generated SPARQL query:\n{sparql}")
            
            result = {
                "sparql": sparql,
                "analytics": analytics,
                "reasoning": f"LLM determined analytics={'required' if analytics else 'not required'}"
            }
            
            # Cache result
            await redis_manager.set_cache(cache_key, result, ttl=3600)
            
            return result
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse JSON response from LLM: {e}")
            logger.warning(f"Raw LLM response: {response[:500]}")
            
            # Fallback: Extract SPARQL using traditional method and assume analytics=False
            sparql = extract_sparql_from_llm_response(response)
            
            return {
                "sparql": sparql,
                "analytics": False,  # Default to no analytics if parsing fails
                "reasoning": "Fallback: Could not parse JSON, using traditional SPARQL extraction"
            }
    
    async def _repair_query(self, query: str, user_query: str, context: List[str]) -> str:
        """Attempt to repair invalid SPARQL query"""
        
        repair_prompt = f"""The following SPARQL query has syntax errors:

{query}

Original user request: {user_query}

Please fix the syntax errors and return a valid SPARQL query. Common issues:
- Missing or incorrect prefixes
- Unclosed braces
- Invalid URI syntax
- Missing periods or semicolons

Return ONLY the corrected SPARQL query."""

        response = await llm_manager.generate(repair_prompt)
        repaired = extract_sparql_from_llm_response(response)
        
        logger.info(f"Repaired SPARQL query:\n{repaired}")
        return repaired
    
    def _template_sparql(self, user_query: str, entities: List[str]) -> Optional[str]:
        """Return a direct SPARQL template for common sensor/location/entity queries with feature detection."""
        uq = user_query.lower()
        features = self._classify_query(uq)
        
        # Special case: Building name query
        if ('building' in uq and 'name' in uq) or 'name of' in uq or 'which building' in uq:
            # Query for building entity with rdfs:label
            return self._prefix_block() + """
SELECT ?building ?label ?comment WHERE {
  ?building a brick:Building .
  OPTIONAL { ?building rdfs:label ?label . }
  OPTIONAL { ?building rdfs:comment ?comment . }
} LIMIT 5"""
        
        # Entity-focused specialized queries
        if entities:
            # Order of checks matters: prioritize equipment and definition before uuid-only
            if features['wants_equipment']:
                patterns = []
                for ent in entities:
                    # Support both directions: sensor brick:isPointOf equipment OR equipment brick:hasPoint sensor
                    patterns.append(f"{{ {ent} brick:isPointOf ?equipment . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} }}")
                    patterns.append(f"{{ ?equipment brick:hasPoint {ent} . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} }}")
                union_block = " \n UNION \n ".join(patterns)
                return self._prefix_block() + f"\nSELECT ?label ?equipment ?equipLabel WHERE {{ {union_block} }}"
            
            # Enhanced definition query - get label AND definition for specific entity
            if features['wants_definition'] or 'label' in uq or 'definition' in uq:
                # Query for specific entity's label and definition
                patterns = []
                for ent in entities:
                    patterns.append(f"""{{
  {ent} rdfs:label ?label .
  OPTIONAL {{ {ent} rdfs:comment ?def . }}
  OPTIONAL {{ {ent} skos:definition ?def2 . }}
  BIND(COALESCE(?def, ?def2, "No definition available") AS ?definition)
}}""")
                union_block = " \n UNION \n ".join(patterns)
                return self._prefix_block() + f"\nSELECT ?label ?definition WHERE {{ {union_block} }}"
            
            if features['wants_location']:
                patterns = []
                for ent in entities:
                    patterns.append(
                        f"{{ {ent} brick:hasLocation ?location . OPTIONAL {{ ?location rdfs:label ?locLabel . }} OPTIONAL {{ {ent} rdfs:label ?label . }} OPTIONAL {{ {ent} ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} OPTIONAL {{ {ent} bldg:connstring ?uuid . }} }}"
                    )
                union_block = " \n UNION \n ".join(patterns)
                return self._prefix_block() + f"\nSELECT ?label ?location ?locLabel ?uuid ?storage WHERE {{ {union_block} }}"
            if features['wants_uuid'] and not features['wants_label'] and not features['wants_location']:
                patterns = []
                for ent in entities:
                    patterns.append(f"{{ {ent} ref:hasExternalReference ?ref . ?ref ref:hasTimeseriesId ?uuid . ?ref ref:storedAt ?storage . }} UNION {{ {ent} bldg:connstring ?uuid . }}")
                union_block = " \n UNION \n ".join(patterns)
                return self._prefix_block() + f"\nSELECT ?uuid ?storage WHERE {{ {union_block} }}"
            if (features['wants_label'] or features['wants_uuid']) and not features['wants_location']:
                patterns = []
                for ent in entities:
                    patterns.append(f"{{ {ent} rdfs:label ?label . OPTIONAL {{ {ent} bldg:connstring ?uuid . }} }}")
                union_block = " \n UNION \n ".join(patterns)
                return self._prefix_block() + f"\nSELECT ?label ?uuid WHERE {{ {union_block} }}"
        # Map keywords to Brick classes for class-level queries
        class_map = {
            'air temperature': 'brick:Air_Temperature_Sensor',
            'temperature': 'brick:Air_Temperature_Sensor',
            'humidity': 'brick:Humidity_Sensor',
            'co2': 'brick:CO2_Sensor',
            'occupancy': 'brick:Occupancy_Sensor',
            'pressure': 'brick:Pressure_Sensor'
        }
        target_class = None
        for k, v in class_map.items():
            if k in uq:
                target_class = v
                break
        if features['wants_count'] and target_class:
            return self._prefix_block() + f"\nSELECT (COUNT(?sensor) AS ?count) WHERE {{ ?sensor rdf:type {target_class} . }}"
        if features['wants_definition'] and target_class:
            return self._prefix_block() + f"\nSELECT ?def WHERE {{ {target_class} (rdfs:comment|skos:definition) ?def . }} LIMIT 5"
        if features['wants_equipment'] and target_class:
            # Include UNION for inverse relation
            return self._prefix_block() + f"\nSELECT ?sensor ?equipment ?equipLabel WHERE {{ {{ ?sensor rdf:type {target_class} . ?sensor brick:isPointOf ?equipment . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} }} UNION {{ ?sensor rdf:type {target_class} . ?equipment brick:hasPoint ?sensor . OPTIONAL {{ ?equipment rdfs:label ?equipLabel . }} }} }} LIMIT 50"
        if target_class:
            # Provide dual strategy: attempt direct class typing then fallback pattern search if zero results.
            # The fallback will be triggered in postprocess stage if needed (handled by execution wrapper).
            return self._prefix_block() + f"\nSELECT ?sensor ?location ?uuid WHERE {{\n  ?sensor rdf:type {target_class} .\n  OPTIONAL {{ ?sensor brick:hasLocation ?location . }}\n  OPTIONAL {{ ?sensor bldg:connstring ?uuid . }}\n}} LIMIT 50"
        # Generic sensor listing fallback
        sensor_words = ['sensor', 'sensors', 'point', 'points']
        if any(w in uq for w in sensor_words):
            return self._prefix_block() + "\nSELECT ?sensor ?type ?location ?uuid WHERE {\n  ?sensor rdf:type ?type .\n  FILTER(CONTAINS(STR(?type), 'Sensor') || CONTAINS(STR(?type), 'Point'))\n  OPTIONAL { ?sensor brick:hasLocation ?location . }\n  OPTIONAL { ?sensor bldg:connstring ?uuid . }\n} LIMIT 50"
        return None

    def _infer_class(self, uq: str) -> Optional[str]:
        mapping = {
            'air temperature': 'brick:Air_Temperature_Sensor',
            'temperature': 'brick:Air_Temperature_Sensor',
            'humidity': 'brick:Humidity_Sensor',
            'air humidity': 'brick:Humidity_Sensor',
            'co2': 'brick:CO2_Sensor',
            'pressure': 'brick:Pressure_Sensor',
            'occupancy': 'brick:Occupancy_Sensor'
        }
        for k, v in mapping.items():
            if k in uq:
                return v
        return None

    async def _get_instances_for_class(self, brick_class: str, limit: int = 40) -> List[str]:
        """Query GraphDB for instances of a Brick class. Returns bldg: URIs only."""
        if brick_class in self._instance_cache:
            return self._instance_cache[brick_class]
        q = f"""{self._prefix_block()}
SELECT ?s WHERE {{ ?s rdf:type {brick_class} . FILTER(STRSTARTS(STR(?s), 'http://abacwsbuilding.cardiff.ac.uk/abacws#')) }} LIMIT {limit}"""
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                auth = (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD) if settings.GRAPHDB_USER else None
                resp = await client.post(GRAPHDB_QUERY_ENDPOINT, auth=auth, data={"query": q}, headers={"Accept": "application/sparql-results+json"})
                resp.raise_for_status()
                data = resp.json()
                out = []
                for b in data.get('results', {}).get('bindings', []):
                    uri = b.get('s', {}).get('value')
                    if uri and uri.startswith('http://abacwsbuilding.cardiff.ac.uk/abacws#'):
                        out.append('bldg:' + uri.split('#', 1)[1])
                self._instance_cache[brick_class] = out
                return out
        except Exception as e:
            logger.warning(f"Class instance query failed for {brick_class}: {e}")
            return []

    async def _pattern_instance_search(self, brick_class: str, limit: int = 40) -> List[str]:
        """Fallback: search for URIs containing core type token (e.g., Humidity_Sensor) when rdf:type lookup empty."""
        token = None
        m = re.search(r'brick:([A-Za-z0-9_]+)', brick_class)
        if m:
            token = m.group(1).replace('Air_Temperature', 'Air_Temperature').replace('Humidity', 'Humidity').replace('CO2', 'CO2').replace('Pressure', 'Pressure').replace('Occupancy', 'Occupancy')
        if not token:
            return []
        # Use regex on URI string via FILTER(CONTAINS())
        q = f"""{self._prefix_block()}
SELECT ?s WHERE {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s),'http://abacwsbuilding.cardiff.ac.uk/abacws#') && CONTAINS(STR(?s), '{token}_Sensor')) }} LIMIT {limit}"""
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                auth = (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD) if settings.GRAPHDB_USER else None
                resp = await client.post(GRAPHDB_QUERY_ENDPOINT, auth=auth, data={"query": q}, headers={"Accept": "application/sparql-results+json"})
                resp.raise_for_status()
                data = resp.json()
                out = []
                for b in data.get('results', {}).get('bindings', []):
                    uri = b.get('s', {}).get('value')
                    if uri and uri.startswith('http://abacwsbuilding.cardiff.ac.uk/abacws#'):
                        out.append('bldg:' + uri.split('#', 1)[1])
                return out
        except Exception as e:
            logger.warning(f"Pattern instance search failed for token {token}: {e}")
            return []

    def _classify_query(self, uq: str) -> Dict[str, bool]:
        return {
            'wants_label': any(w in uq for w in ['label', 'name', 'called']),
            'wants_uuid': any(w in uq for w in ['uuid', 'id', 'identifier']),
            'wants_location': any(w in uq for w in ['location', 'located']) or 'where is' in uq or 'where are' in uq,
            'wants_count': any(w in uq for w in ['how many', 'count', 'number of']),
            'wants_equipment': 'equipment' in uq or 'device' in uq,
            'wants_definition': any(w in uq for w in ['definition', 'describe', 'meaning'])
        }

    def _ensure_prefixes(self, sparql: str) -> str:
        """Ensure the full extended prefix block is present (idempotent)."""
        if not isinstance(sparql, str):
            return sparql
            
        # Remove any existing PREFIX lines to avoid duplicates
        lines = sparql.split('\n')
        clean_lines = [line for line in lines if not line.strip().lower().startswith('prefix ')]
        clean_sparql = '\n'.join(clean_lines).strip()
        
        return self._prefix_block() + "\n" + clean_sparql

    def _prefix_block(self) -> str:
        return "\n".join(EXTENDED_PREFIXES)

    def _extract_entities(self, user_query: str) -> List[str]:
        """Extract explicit bldg: entities or construct them from patterns like 'Air Humidity Sensor 5.01'."""
        entities = []
        # Direct bldg: references
        for token in re.findall(r"bldg:[A-Za-z0-9_\.]+", user_query):
            entities.append(token)
        # Unified sensor pattern extraction
        sensor_pattern = re.findall(r"(Zone|Room|Space|Air)?\s*(Air Temperature|Temperature|Air Humidity|Humidity|CO2|Pressure|Occupancy) Sensor\s*(\d+\.\d+|\d+)", user_query, re.IGNORECASE)
        for prefix, stype, num in sensor_pattern:
            stype_norm = stype.lower().strip()
            mapping = {
                'air temperature': 'Air_Temperature',
                'temperature': 'Air_Temperature',
                'air humidity': 'Air_Humidity',
                'humidity': 'Air_Humidity',
                'co2': 'CO2',
                'pressure': 'Pressure',
                'occupancy': 'Occupancy'
            }
            base_type = mapping.get(stype_norm, stype_norm.title().replace(' ', '_'))
            base = f"{base_type}_Sensor_{num}"
            zone_base = "Zone_" + base
            chosen = zone_base if prefix and prefix.lower() == 'zone' else base
            entities.append("bldg:" + chosen)
            if chosen != zone_base:
                entities.append("bldg:" + zone_base)
        return list(dict.fromkeys(entities))  # dedupe preserving order

    def _infer_class_from_entity(self, entity: str) -> Optional[str]:
        """Derive Brick class from an instance local name pattern."""
        if not entity.startswith('bldg:'):
            return None
        local = entity.split(':',1)[1]  # Zone_Air_Humidity_Sensor_5.01
        # Strip Zone_ prefix
        if local.startswith('Zone_'):
            local = local[5:]
        # Match core type before _Sensor_
        m = re.match(r'([A-Za-z_]+)_Sensor_', local)
        if not m:
            return None
        core = m.group(1)
        mapping = {
            'Air_Temperature': 'brick:Air_Temperature_Sensor',
            'Air_Humidity': 'brick:Humidity_Sensor',
            'CO2': 'brick:CO2_Sensor',
            'Pressure': 'brick:Pressure_Sensor',
            'Occupancy': 'brick:Occupancy_Sensor'
        }
        return mapping.get(core)

    def _postprocess_query(self, sparql: Optional[str]) -> Optional[str]:
        """Apply legacy fixes: sensor name spacing and instance prefix corrections."""
        if not sparql or not isinstance(sparql, str):
            return sparql
        fixed = re.sub(r'(\w+_Sensor)\s+(\d+\.?\d*)', r'\1_\2', sparql)
        # brick:Some_Sensor_x => bldg:Some_Sensor_x for instance lookups
        fixed = re.sub(r'brick:([A-Za-z0-9_]+_Sensor_\d+(?:\.\d+)?)', r'bldg:\1', fixed)
        if fixed != sparql:
            logger.info("Applied SPARQL postprocessing corrections")
        return fixed

    def _standardize_results(self, results: Dict[str, Any], question: str, sparql_query: str) -> Dict[str, Any]:
        """Produce standardized JSON similar to legacy Rasa action for downstream summarization."""
        standardized = {
            'question': question,
            'query': sparql_query,
            'results': []
        }
        try:
            bindings = results.get('results', {}).get('bindings', []) if isinstance(results, dict) else []
            for b in bindings:
                entry = {}
                for var, val in b.items():
                    value = val.get('value')
                    vtype = val.get('type')
                    if vtype == 'uri':
                        # Compact known namespaces
                        for ns, pref in (
                            ('https://brickschema.org/schema/Brick#', 'brick:'),
                            ('http://abacwsbuilding.cardiff.ac.uk/abacws#', 'bldg:'),
                            ('http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdf:'),
                            ('http://www.w3.org/2000/01/rdf-schema#', 'rdfs:'),
                            ('http://www.w3.org/2002/07/owl#', 'owl:'),
                            ('https://brickschema.org/schema/Brick/ref#', 'ref:'),
                            ('https://w3id.org/rec#', 'rec:'),
                            ('http://www.w3.org/ns/sosa/', 'sosa:')
                        ):
                            if value.startswith(ns):
                                value = pref + value[len(ns):]
                                break
                    entry[var] = value
                standardized['results'].append(entry)
        except Exception as e:
            standardized['error'] = f'standardization_failed: {e}'
    async def _execute_query(self, sparql: str) -> Dict[str, Any]:
        """Execute SPARQL query against GraphDB (with Fuseki fallback)"""
        # Check cache
        query_hash = generate_hash(sparql)
        cache_key = f"cache:sparql_exec:{query_hash}"
        cached_result = await redis_manager.get_cache(cache_key)
        
        if cached_result:
            logger.info(f"✅ Cache hit for SPARQL execution: {query_hash}")
            return cached_result

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try GraphDB first
                try:
                    logger.info(f"🔍 Executing SPARQL on GraphDB: {GRAPHDB_QUERY_ENDPOINT}")
                    
                    # GraphDB uses basic auth
                    auth = (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD) if settings.GRAPHDB_USER else None
                    
                    response = await client.post(
                        GRAPHDB_QUERY_ENDPOINT,
                        auth=auth,
                        data={"query": sparql},
                        headers={"Accept": "application/sparql-results+json"}
                    )
                    response.raise_for_status()
                    
                    results = response.json()
                    result_count = len(results.get('results', {}).get('bindings', []))
                    logger.info(f"✅ GraphDB query returned {result_count} results")
                    
                    # If zero results, try fallback pattern search
                    if result_count == 0:
                        logger.info("Zero results from GraphDB, attempting pattern-based fallback")
                        fallback_results = await self._fallback_pattern_search(sparql, client, auth)
                        if fallback_results:
                            await redis_manager.set_cache(cache_key, fallback_results, ttl=3600)
                            return fallback_results
                    
                    await redis_manager.set_cache(cache_key, results, ttl=3600)
                    return results
                    
                except Exception as e:
                    logger.warning(f"GraphDB query failed: {e}, trying Fuseki fallback")
                    
                    # Fallback to Fuseki if GraphDB fails
                    response = await client.post(
                        FUSEKI_QUERY_ENDPOINT,
                        data={"query": sparql},
                        headers={"Accept": "application/sparql-results+json"}
                    )
                    response.raise_for_status()
                    
                    results = response.json()
                    logger.info(f"Fuseki fallback returned {len(results.get('results', {}).get('bindings', []))} results")
                    
                    # Fallback pattern search for Fuseki too
                    if len(results.get('results', {}).get('bindings', [])) == 0:
                        fallback_results = await self._fallback_pattern_search(sparql, client, None)
                        if fallback_results:
                            await redis_manager.set_cache(cache_key, fallback_results, ttl=3600)
                            return fallback_results
                    
                    await redis_manager.set_cache(cache_key, results, ttl=3600)
                    return results
                
        except httpx.HTTPError as e:
            logger.error(f"SPARQL query error: {e}")
            raise Exception(f"Failed to execute SPARQL query: {str(e)}")
    
    async def _fallback_pattern_search(
        self, 
        sparql: str, 
        client: httpx.AsyncClient, 
        auth: Optional[tuple] = None
    ) -> Optional[Dict[str, Any]]:
        """Fallback pattern-based search when class-based query returns zero results"""
        # Extract class from query
        m = re.search(r"rdf:type\s+(brick:[A-Za-z0-9_]+_Sensor)", sparql)
        if not m:
            m = re.search(r"rdf:type\s+(brick:[A-Za-z0-9_]+)", sparql)
        if not m:
            return None
        
        brick_class = m.group(1)
        token = brick_class.split(':', 1)[1].replace('_Sensor', '')
        
        # Pattern-based query
        alt_query = self._prefix_block() + f"""
SELECT ?sensor ?location ?uuid WHERE {{
    ?sensor ?p ?o .
    FILTER(STRSTARTS(STR(?sensor), 'http://abacwsbuilding.cardiff.ac.uk/abacws#') && CONTAINS(STR(?sensor), '{token}_Sensor'))
    OPTIONAL {{ ?sensor brick:hasLocation ?location . }}
    OPTIONAL {{ ?sensor bldg:connstring ?uuid . }}
}} LIMIT 50"""
        
        logger.info(f"Attempting pattern fallback for token: {token}")
        
        try:
            # Try current endpoint (GraphDB)
            endpoint = GRAPHDB_QUERY_ENDPOINT
            response = await client.post(
                endpoint,
                auth=auth,
                data={"query": alt_query},
                headers={"Accept": "application/sparql-results+json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                count = len(data.get('results', {}).get('bindings', []))
                if count > 0:
                    logger.info(f"✅ Pattern fallback succeeded: {count} results")
                    return data
        except Exception as e:
            logger.warning(f"Pattern fallback failed: {e}")
        
        return None
    
    async def _format_results(
        self,
        results: Dict[str, Any],
        user_query: str,
        sparql_query: str,
        used_template: bool
    ) -> str:
        """Format SPARQL results into natural language"""
        
        bindings = results.get("results", {}).get("bindings", [])
        # Deduplicate rows based on concatenated variable values
        seen = set()
        deduped = []
        for b in bindings:
            sig = tuple(sorted((var, val.get('value')) for var, val in b.items()))
            if sig not in seen:
                seen.add(sig)
                deduped.append(b)
        bindings = deduped
        
        if not bindings:
            return "No results found for your query."
        
        # Special formatting for label+definition queries
        uq = user_query.lower()
        if ('label' in uq and 'definition' in uq) or ('#' in user_query):
            # Format as: "Label: X, Definition: Y"
            if len(bindings) == 1:
                b = bindings[0]
                label = b.get('label', {}).get('value', 'N/A')
                definition = b.get('definition', {}).get('value') or b.get('def', {}).get('value', 'N/A')
                return f"**{label}**\n\nDefinition: {definition}"
            else:
                result_text = f"Found {len(bindings)} result(s):\n\n"
                for i, b in enumerate(bindings[:10], 1):
                    label = b.get('label', {}).get('value', 'N/A')
                    definition = b.get('definition', {}).get('value') or b.get('def', {}).get('value', 'N/A')
                    result_text += f"{i}. **{label}**: {definition}\n\n"
                return result_text
        
        # Special formatting for building name query
        if 'building' in uq and 'name' in uq:
            if bindings:
                b = bindings[0]
                label = b.get('label', {}).get('value', 'Unknown Building')
                comment = b.get('comment', {}).get('value', '')
                if comment:
                    return f"The building name is: **{label}**\n\n{comment}"
                return f"The building name is: **{label}**"
        
        # Convert results to readable format
        result_text = f"Found {len(bindings)} result(s):\n\n"
        
        # Check if user wants all results
        user_query_lower = user_query.lower()
        show_all = any(k in user_query_lower for k in ["all", "complete", "full", "everything", "list"])
        
        # Set limit based on user intent (default 10, but higher if "all" requested)
        # Cap at 100 to prevent context window overflow
        limit = 100 if show_all else 10
        
        for i, binding in enumerate(bindings[:limit], 1):
            result_text += f"{i}. "
            for var, value in binding.items():
                result_text += f"{var}: {value.get('value', 'N/A')} | "
            result_text = result_text.rstrip(" | ") + "\n"
        
        if len(bindings) > limit:
            result_text += f"\n... and {len(bindings) - limit} more results (truncated for brevity)"
        
        # Generate human-readable natural language response
        summary_prompt = f"""You are a helpful building management assistant. Convert these SPARQL query results into a clear, natural language response for the user.

=== USER QUESTION ===
{user_query}

=== QUERY RESULTS ===
{result_text}

=== YOUR TASK ===
Create a human-readable response that:

1. **Directly answers the user's question** in natural language
2. **Presents information clearly** - extract sensor names from URIs (e.g., "Air_Temperature_Sensor_5.01" instead of full URI)
3. **Groups related information** - organize by location/zone if applicable
4. **Uses formatting** for readability:
   - Use bullet points (•) or numbered lists
   - Group sensors by location/zone when relevant
   - Highlight key information
5. **Provides context** - mention total count and any patterns
6. **Keep it concise** - summarize if more than 50 results if user did not asked for all details explicitly

=== OUTPUT FORMAT EXAMPLES ===

Example 1 (Sensor List):
"I found 34 temperature sensors in the building. Here are the sensors organized by zone:

**West Zone:**
• Air_Temperature_Sensor_5.01
• Air_Temperature_Sensor_5.02
• Air_Temperature_Sensor_5.10
• Air_Temperature_Sensor_5.15
• Air_Temperature_Sensor_5.16

**North Zone:**
• Air_Temperature_Sensor_5.06
• Air_Temperature_Sensor_5.07
• Air_Temperature_Sensor_5.12
... (and 26 more sensors across other zones)

Would you like to see the complete list or get data from specific sensors?"

Example 2 (Location Query):
"The CO2 sensor in room 5.06 is located in the **North-East Zone**. Its UUID for data retrieval is: 791284f8-..."

Example 3 (Equipment List):
"There are 5 Air Handling Units (AHUs) on the first floor:
1. AHU_01 - Serves West Zone
2. AHU_02 - Serves East Zone
..."

=== IMPORTANT ===
- Extract readable names from URIs (remove "http://abacwsbuilding.cardiff.ac.uk/abacws#")
- Be conversational and helpful
- Don't show raw URIs unless specifically asked
- If results contain UUIDs, mention they're available for data queries

Generate your response now:"""

        if used_template:
            # For template queries, always use LLM formatting for better UX
            try:
                summary = await llm_manager.generate(summary_prompt)
                return summary.strip()
            except Exception as e:
                logger.warning(f"LLM formatting failed, using structured fallback: {e}")
                # Fallback: Clean up URIs in the result text
                return self._clean_uri_output(result_text)
        
        try:
            summary = await llm_manager.generate(summary_prompt)
            return summary.strip()
        except Exception as e:
            logger.warning(f"LLM summarization failed, fallback to cleaned output: {e}")
            return self._clean_uri_output(result_text)
    
    def _should_require_analytics(self, user_query: str, entities: List[str]) -> bool:
        """
        Determine if query requires analytics/time-series data processing
        
        Args:
            user_query: User's natural language query
            entities: Extracted entities
            
        Returns:
            True if analytics needed, False if ontology metadata sufficient
        """
        query_lower = user_query.lower()
        
        # **PRIORITY 1: Metadata-only patterns** (check FIRST!)
        # These are static ontology properties - NEVER require analytics
        metadata_patterns = [
            "what is the label", "what is the uuid", "what is the id", 
            "what is the type", "what is the location", "where is",
            "what is the definition", "what is the description",
            "list all", "show all", "how many", "count",
            "which equipment", "what type", "explain", "describe",
            "in ontology", "in the ontology", "from ontology",
            "hasLocation", "isPointOf", "feeds", "hasPart"
        ]
        
        for pattern in metadata_patterns:
            if pattern in query_lower:
                return False  # Metadata query - NO analytics needed
        
        # **PRIORITY 2: Analytics/Time-series patterns**
        # These require sensor DATA (readings, values, trends)
        analytics_patterns = [
            "current temperature", "current reading", "current value",
            "average temperature", "min temperature", "max temperature",
            "temperature reading", "co2 reading", "humidity reading",
            "above", "below", "higher than", "lower than",
            "trend", "history", "yesterday", "last week", "last hour",
            "graph", "chart", "plot", "visualize", "visualise",
            "show me the data", "get readings", "fetch values"
        ]
        
        for pattern in analytics_patterns:
            if pattern in query_lower:
                return True  # Analytics query - need time-series data
        
        # **PRIORITY 3: Ambiguous cases** - Conservative default
        # If no clear pattern, assume metadata (safer default)
        return False
    
    def _clean_uri_output(self, result_text: str) -> str:
        """
        Clean up raw SPARQL results by removing URI prefixes for better readability
        
        Args:
            result_text: Raw formatted results with full URIs
            
        Returns:
            Cleaned text with shortened entity names
        """
        import re
        
        # Remove common URI prefixes
        cleaned = result_text
        
        # Replace full URIs with just the local name
        uri_patterns = [
            (r'http://abacwsbuilding\.cardiff\.ac\.uk/abacws#', ''),
            (r'https://brickschema\.org/schema/Brick#', 'brick:'),
            (r'http://www\.w3\.org/1999/02/22-rdf-syntax-ns#', 'rdf:'),
            (r'http://www\.w3\.org/2000/01/rdf-schema#', 'rdfs:'),
        ]
        
        for pattern, replacement in uri_patterns:
            cleaned = re.sub(pattern, replacement, cleaned)
        
        return cleaned

