"""
Semantic Ontology Agent - RAG + LLM based ontology querying
NO SPARQL generation - Pure semantic understanding approach

Architecture:
1. Extract concepts from user query using LLM
2. Search ontology via RAG (vector similarity)
3. LLM reasons over retrieved ontology fragments
4. Return direct answer

This approach works with ANY ontology without hardcoded templates!
"""
import sys
sys.path.append('/app')

import httpx
from typing import Dict, Any, List, Optional, Tuple
import json
from shared.models import ConversationState
from shared.utils import get_logger
from shared.config import settings
from orchestrator.llm_manager import llm_manager

logger = get_logger(__name__)

RAG_SERVICE_URL = f"http://{settings.RAG_SERVICE_HOST}:{settings.RAG_SERVICE_PORT}"


class SemanticOntologyAgent:
    """
    Semantic-first ontology agent that uses RAG + LLM reasoning
    instead of brittle SPARQL generation
    """
    
    def __init__(self):
        self.tbox_collection = settings.TBOX_COLLECTION or "brick_schema"
        self.abox_collection = settings.ABOX_COLLECTION or "building_instances"
        self.max_context_chunks = 10
        self.cache = {}  # Simple in-memory cache for repeated queries
    
    async def answer_query(
        self,
        state: ConversationState,
        user_query: str
    ) -> Dict[str, Any]:
        """
        Main entry point - Answer ontology question using semantic understanding
        
        Args:
            state: Conversation state
            user_query: User's natural language question
            
        Returns:
            Dict with 'success', 'answer', 'evidence', 'reasoning_steps'
        """
        try:
            logger.info(f"Semantic ontology query: {user_query}")
            
            # Step 1: Extract key concepts and intent from user query
            concepts = await self._extract_concepts(user_query)
            logger.info(f"Extracted concepts: {concepts}")
            
            # Step 2: Retrieve relevant ontology fragments via RAG
            ontology_context = await self._retrieve_ontology_context(user_query, concepts)
            logger.info(f"Retrieved {len(ontology_context)} ontology fragments")
            
            # Step 3: Use LLM to reason over ontology context and answer question
            answer = await self._reason_over_ontology(user_query, concepts, ontology_context)
            
            return {
                "success": True,
                "answer": answer["text"],
                "evidence": ontology_context,
                "concepts_extracted": concepts,
                "reasoning_steps": answer.get("reasoning", []),
                "confidence": answer.get("confidence", "high")
            }
            
        except Exception as e:
            logger.error(f"Semantic ontology query error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "answer": f"I encountered an error while searching the ontology: {str(e)}"
            }
    
    async def _extract_concepts(self, user_query: str) -> Dict[str, List[str]]:
        """
        Use LLM to extract key concepts from user query
        
        Returns:
            Dict with 'entities', 'properties', 'classes', 'intent'
        """
        extraction_prompt = f"""Analyze this user question about a building ontology and extract key concepts.

User Question: "{user_query}"

Extract the following (JSON format):
1. **entities**: Specific instances mentioned (e.g., "CO2_Level_Sensor_5.01", "Room_101", "Building_A")
2. **properties**: Properties/attributes asked about (e.g., "label", "definition", "location", "temperature", "uuid")
3. **classes**: General types mentioned (e.g., "sensor", "building", "room", "equipment", "temperature sensor")
4. **intent**: What user wants to know (e.g., "find definition", "get label", "list sensors", "find location")
5. **keywords**: Important domain terms (e.g., "CO2", "humidity", "HVAC", "zone")

Return ONLY valid JSON with these 5 keys. Be generous - extract anything that might help find relevant ontology data.

Example output:
{{
  "entities": ["CO2_Level_Sensor_5.01"],
  "properties": ["label", "definition"],
  "classes": ["CO2 sensor", "sensor"],
  "intent": "get label and definition of specific sensor",
  "keywords": ["CO2", "level", "sensor", "5.01"]
}}

Your JSON:"""

        try:
            response = await llm_manager.generate(extraction_prompt, temperature=0.1)
            
            # Extract JSON from response
            json_match = response.strip()
            # Remove markdown code blocks if present
            if "```json" in json_match:
                json_match = json_match.split("```json")[1].split("```")[0].strip()
            elif "```" in json_match:
                json_match = json_match.split("```")[1].split("```")[0].strip()
            
            concepts = json.loads(json_match)
            
            # Validate structure
            required_keys = ["entities", "properties", "classes", "intent", "keywords"]
            for key in required_keys:
                if key not in concepts:
                    concepts[key] = []
            
            return concepts
            
        except Exception as e:
            logger.error(f"Concept extraction error: {e}")
            # Fallback: simple keyword extraction
            words = user_query.lower().replace("?", "").split()
            return {
                "entities": [],
                "properties": ["label", "definition"] if "label" in user_query.lower() or "definition" in user_query.lower() else [],
                "classes": [],
                "intent": user_query,
                "keywords": words
            }
    
    async def _retrieve_ontology_context(
        self,
        user_query: str,
        concepts: Dict[str, List[str]]
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant ontology fragments from vector store using RAG
        
        Returns:
            List of ontology fragments with metadata
        """
        context_fragments = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Strategy 1: Search using extracted entities (Highest Priority)
            # This solves the issue where the full question dilutes the vector search
            if concepts.get("entities"):
                for entity in concepts.get("entities", []):
                    if not entity:
                        continue
                    try:
                        # Search for the exact entity name
                        logger.info(f"Searching for specific entity: {entity}")
                        entity_response = await client.post(
                            f"{RAG_SERVICE_URL}/graphdb/retrieve",
                            json={
                                "query": entity,  # Send JUST the entity name
                                "top_k": 5,
                                "hops": 2  # Ensure 2-hop context
                            }
                        )
                        if entity_response.status_code == 200:
                            data = entity_response.json()
                            if data.get("summary"):
                                context_fragments.append({
                                    "text": data["summary"],
                                    "score": 0.95,
                                    "source": f"entity_{entity}",
                                    "metadata": data.get("metadata", {})
                                })
                    except Exception as e:
                        logger.warning(f"Entity search for '{entity}' failed: {e}")

            # Strategy 2: Search using keywords (Medium Priority)
            # If no specific entities found, or to supplement context
            if not context_fragments and concepts.get("keywords"):
                keywords_query = " ".join(concepts["keywords"])
                try:
                    logger.info(f"Searching with keywords: {keywords_query}")
                    keyword_response = await client.post(
                        f"{RAG_SERVICE_URL}/graphdb/retrieve",
                        json={
                            "query": keywords_query,
                            "top_k": 5,
                            "hops": 2
                        }
                    )
                    if keyword_response.status_code == 200:
                        data = keyword_response.json()
                        if data.get("summary"):
                            context_fragments.append({
                                "text": data["summary"],
                                "score": 0.85,
                                "source": "keywords",
                                "metadata": data.get("metadata", {})
                            })
                except Exception as e:
                    logger.warning(f"Keyword search failed: {e}")

            # Strategy 3: Fallback to full user query (Lowest Priority)
            # Only if we still have nothing
            if not context_fragments:
                try:
                    logger.info(f"Fallback: Searching with full query: {user_query}")
                    query_response = await client.post(
                        f"{RAG_SERVICE_URL}/graphdb/retrieve",
                        json={
                            "query": user_query,
                            "top_k": 5,
                            "hops": 2
                        }
                    )
                    if query_response.status_code == 200:
                        data = query_response.json()
                        if data.get("summary"):
                            context_fragments.append({
                                "text": data["summary"],
                                "score": 0.8,
                                "source": "full_query",
                                "metadata": data.get("metadata", {})
                            })
                except Exception as e:
                    logger.warning(f"Full query search failed: {e}")
            
        return context_fragments
    
    async def _reason_over_ontology(
        self,
        user_query: str,
        concepts: Dict[str, List[str]],
        ontology_context: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Use LLM to reason over retrieved ontology fragments and answer question
        
        Returns:
            Dict with 'text', 'reasoning', 'confidence'
        """
        # Build context from ontology fragments
        context_text = ""
        for i, fragment in enumerate(ontology_context, 1):
            context_text += f"\n--- Ontology Fragment {i} (score: {fragment['score']:.3f}) ---\n"
            context_text += fragment["text"]
            context_text += "\n"
        
        if not context_text.strip():
            context_text = "No relevant ontology information found."
        
        # Build reasoning prompt
        reasoning_prompt = f"""You are an expert at understanding building ontologies. Answer the user's question based ONLY on the provided ontology fragments.

User Question: "{user_query}"

Extracted Concepts:
- Entities: {', '.join(concepts.get('entities', [])) or 'None'}
- Properties: {', '.join(concepts.get('properties', [])) or 'None'}
- Classes: {', '.join(concepts.get('classes', [])) or 'None'}
- Intent: {concepts.get('intent', 'Unknown')}

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
            
            # Parse response
            answer_text = response.strip()
            
            # Determine confidence based on whether we found relevant context
            confidence = "high" if len(ontology_context) >= 3 else "medium" if len(ontology_context) >= 1 else "low"
            
            return {
                "text": answer_text,
                "reasoning": [
                    f"Extracted {len(concepts.get('entities', []))} entities, {len(concepts.get('properties', []))} properties",
                    f"Retrieved {len(ontology_context)} relevant ontology fragments",
                    f"LLM reasoning over context with {confidence} confidence"
                ],
                "confidence": confidence
            }
            
        except Exception as e:
            logger.error(f"LLM reasoning error: {e}")
            return {
                "text": f"I found relevant ontology data but had trouble interpreting it: {str(e)}",
                "reasoning": ["Error during LLM reasoning"],
                "confidence": "low"
            }
    
    def get_info(self) -> Dict[str, Any]:
        """Get agent information"""
        return {
            "agent": "SemanticOntologyAgent",
            "approach": "RAG + LLM reasoning (no SPARQL)",
            "tbox_collection": self.tbox_collection,
            "abox_collection": self.abox_collection,
            "max_context": self.max_context_chunks
        }


# Global instance
semantic_agent = SemanticOntologyAgent()
