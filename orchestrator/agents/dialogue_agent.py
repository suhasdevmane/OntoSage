"""
Dialogue Agent - LLM-Based Intent Detection and Query Generation
"""
import sys
sys.path.append('/app')

import json
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List
from shared.models import ConversationState, Message
from shared.utils import get_logger, generate_hash
from shared.config import settings
from orchestrator.llm_manager import llm_manager
from orchestrator.services.context_manager import ContextManager
from orchestrator.redis_manager import redis_manager

logger = get_logger(__name__)

# RAG Service URL for context retrieval
RAG_SERVICE_URL = f"http://{settings.RAG_SERVICE_HOST}:{settings.RAG_SERVICE_PORT}"

def format_conversation_history(messages: List[Message], max_messages: int = 5) -> str:
    """
    Format recent conversation messages for LLM context.
    
    Args:
        messages: List of conversation messages
        max_messages: Maximum number of recent messages to include (default: 5)
        
    Returns:
        Formatted string of conversation history
    """
    if not messages or len(messages) <= 1:
        return "(No previous conversation)"
    
    # Get last N messages (excluding the current one)
    recent_messages = messages[-(max_messages + 1):-1] if len(messages) > max_messages else messages[:-1]
    
    if not recent_messages:
        return "(No previous conversation)"
    
    formatted = "Previous Conversation:\n"
    for msg in recent_messages:
        role = "User" if msg.role == "user" else "Assistant"
        # Truncate very long messages
        content = msg.content if len(msg.content) <= 200 else msg.content[:200] + "..."
        formatted += f"{role}: {content}\n"
    
    return formatted.strip()

# Persona definitions
PERSONAS = {
    "student": {
        "system_message": """You are a helpful teaching assistant for building systems.
- Use simple, clear explanations
- Provide educational context
- Encourage learning and exploration
- Avoid jargon, explain technical terms""",
        "style": "educational and encouraging"
    },
    "researcher": {
        "system_message": """You are a research assistant for building data analysis.
- Provide precise, detailed information
- Include data provenance and methodology
- Use technical terminology appropriately
- Support hypothesis testing and analysis""",
        "style": "precise and analytical"
    },
    "facility_manager": {
        "system_message": """You are a facility management assistant.
- Focus on actionable insights
- Prioritize operational efficiency
- Provide maintenance recommendations
- Include cost and energy implications""",
        "style": "practical and action-oriented"
    },
    "general": {
        "system_message": """You are OntoSage, an intelligent building assistant.
- Be helpful, clear, and concise
- Provide relevant information
- Ask for clarification when needed
- Support various types of queries
- Provide detailed and comprehensive answers when asked for details""",
        "style": "balanced, professional, and detailed"
    }
}

class DialogueAgent:
    """Manages conversation flow and LLM-based intent detection"""
    
    def __init__(self):
        self.context_manager = ContextManager(llm_manager)
    
    async def _retrieve_ontology_context(self, query: str, top_k: int = 5) -> List[str]:
        """
        Retrieve relevant ontology context from RAG service
        
        Args:
            query: User's question
            top_k: Number of context items to retrieve
            
        Returns:
            List of context strings with ontology information
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Use GraphDB retrieval ONLY (per user requirement)
                try:
                    response = await client.post(
                        f"{RAG_SERVICE_URL}/graphdb/retrieve",
                        json={
                            "query": query,
                            "top_k": top_k,
                            "hops": 1
                        }
                    )
                    if response.status_code == 200:
                        data = response.json()
                        # Format GraphDB result as context strings
                        summary = data.get("summary", "")
                        triples = data.get("triples", [])
                        contexts = [summary] + triples
                        logger.info(f"✅ Retrieved {len(contexts)} context items from GraphDB RAG")
                        return contexts[:top_k]
                    else:
                        logger.warning(f"GraphDB retrieval returned status {response.status_code}")
                        return []
                except Exception as e:
                    logger.warning(f"GraphDB retrieval failed: {e}")
                    return []
        except Exception as e:
            logger.error(f"❌ Failed to retrieve ontology context: {e}")
            return []
    
    async def detect_intent(self, state: ConversationState) -> Dict[str, Any]:
        """
        Use LLM to detect user intent and generate SPARQL query if needed.
        
        Returns a dictionary with:
        - general (bool): True if general knowledge question, False if ontology-based
        - sparql_query (str): SPARQL query if general=False, empty otherwise
        - analytics (bool): True if analytics/aggregation needed
        - response (str): Direct answer if general=True
        """
        logger.info("═" * 80)
        logger.info("🤖 DIALOGUE AGENT: LLM-Based Intent Detection Started")
        logger.info("═" * 80)
        
        latest_message = state.messages[-1] if state.messages else None
        if not latest_message:
            logger.warning("❌ No messages in conversation state")
            return {
                "general": True,
                "sparql_query": "",
                "analytics": False,
                "response": "I didn't receive a question. How can I help you?"
            }
        
        user_query = latest_message.content
        logger.info(f"📥 User Query: {user_query}")
        logger.info(f"📜 Conversation History: {len(state.messages)} messages total")
        
        # Retrieve ontology context from RAG service
        logger.info("🔍 Retrieving ontology context from GraphDB RAG...")
        ontology_context = await self._retrieve_ontology_context(user_query, top_k=5)
        
        # Update context summary if needed
        if len(state.messages) > 5:
            # Summarize periodically or if not present
            if not state.summary or len(state.messages) % 5 == 0:
                logger.info("📝 Updating conversation summary...")
                state.summary = await self.context_manager.summarize_history(state.messages, state.summary)

        # Format conversation history (Summary + Recent)
        recent_messages = self.context_manager.prune_messages(state.messages, max_messages=5)
        conversation_history = format_conversation_history(recent_messages)
        
        if state.summary:
            conversation_history = f"Summary of previous conversation:\n{state.summary}\n\nRecent Messages:\n{conversation_history}"
        
        # Build the LLM prompt for intent detection and query generation
        prompt = self._build_intent_detection_prompt(
            user_query=user_query,
            ontology_context=ontology_context,
            conversation_history=conversation_history
        )
        
        # Check cache
        prompt_hash = generate_hash(prompt)
        cache_key = f"cache:intent:{prompt_hash}"
        cached_result = await redis_manager.get_cache(cache_key)
        
        if cached_result:
            logger.info(f"✅ Cache hit for intent detection: {prompt_hash}")
            return cached_result
        
        # Call LLM to detect intent
        logger.info("🧠 Calling LLM for intent detection and query generation...")
        try:
            llm_response = await llm_manager.generate(prompt)
            logger.info(f"📤 LLM Response received (length: {len(llm_response)} chars)")
            
            # Parse JSON response
            result = self._parse_llm_response(llm_response, user_query)
            
            # Cache result
            await redis_manager.set_cache(cache_key, result, ttl=3600)
            
            # Log the detected intent
            logger.info("═" * 80)
            logger.info(f"🎯 Intent Detection Result:")
            logger.info(f"   ├─ Intent: {result.get('intent', 'unknown')}")
            logger.info(f"   ├─ Entities: {result.get('entities', [])}")
            logger.info(f"   ├─ Analytics: {result.get('required_analytics', [])}")
            if result.get('intent') == 'general':
                logger.info(f"   └─ Direct Response: {result.get('response', '')[:100]}...")
            else:
                logger.info(f"   └─ Explanation: {result.get('explanation', '')}")
            logger.info("═" * 80)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ LLM intent detection failed: {e}", exc_info=True)
            # Fallback to safe default
            return {
                "general": True,
                "sparql_query": "",
                "analytics": False,
                "response": f"I encountered an error processing your question. Please try rephrasing: {str(e)}"
            }
    
    def _build_intent_detection_prompt(
        self,
        user_query: str,
        ontology_context: List[str],
        conversation_history: str
    ) -> str:
        """
        Build the prompt for LLM-based intent detection
        
        Args:
            user_query: The user's question
            ontology_context: Retrieved ontology fragments from vector DB
            conversation_history: Formatted conversation history
            
        Returns:
            Formatted prompt string
        """
        # Get current time in UK timezone
        try:
            uk_time = datetime.now(ZoneInfo("Europe/London"))
            current_time_str = uk_time.strftime("%A, %B %d, %Y, %H:%M %Z")
        except Exception as e:
            logger.warning(f"Failed to get UK time: {e}")
            current_time_str = datetime.now().strftime("%A, %B %d, %Y, %H:%M (UTC)")

        # Format ontology context
        context_str = ""
        if ontology_context:
            context_str = "\\n\\nRelevant Ontology Context (from vector database):\\n"
            for i, ctx in enumerate(ontology_context, 1):
                context_str += f"{i}. {ctx}\\n"
        
        prompt = f"""You are an intelligent assistant that analyzes user questions about a building management system.
Current Date and Time: {current_time_str}

Your task is to analyze the user's question and return a JSON response with the following fields:

1. "intent" (string): One of:
   - "general": General knowledge questions (e.g., "what is 2+2?", "hello").
   - "metadata": Questions about static properties (e.g., "list sensors", "where is X?", "what type is Y?").
   - "analytics": Questions about dynamic data/values (e.g., "current reading", "average temp", "history").

2. "entities" (list of strings): Extract all specific building entities mentioned (e.g., "Air_Temperature_Sensor_5.04", "Zone 5.12").
   - Normalize names if possible (e.g., "Sensor 5.04" -> "Air_Temperature_Sensor_5.04" if clear from context).
   - If "all sensors" or generic, leave empty or use ["all"].

3. "required_analytics" (list of strings): If intent="analytics", list required operations:
   - "min", "max", "avg", "count", "sum", "trend", "latest".

4. "time_range" (object):
   - "start": ISO date string or relative (e.g., "now-1d", "2023-01-01"). Default "now-1d" if not specified but analytics needed.
   - "end": ISO date string or relative (e.g., "now").

5. "response" (string): Direct answer if intent="general". Otherwise null.

6. "explanation" (string): Brief reasoning for your classification.

=== RELEVANT CONTEXT ===
{context_str}

=== CONVERSATION HISTORY ===
{conversation_history}

=== USER QUERY ===
{user_query}

Return ONLY the JSON object.
"""
        return prompt
    
    def _parse_llm_response(self, llm_response: str, user_query: str) -> Dict[str, Any]:
        """
        Parse the LLM's JSON response
        
        Args:
            llm_response: Raw LLM response
            user_query: Original user query (for fallback)
            
        Returns:
            Parsed dictionary with intent, entities, required_analytics, time_range, response fields
        """
        try:
            # Try to extract JSON from response (in case LLM adds explanation)
            # Look for JSON block
            json_start = llm_response.find('{')
            json_end = llm_response.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = llm_response[json_start:json_end]
                result = json.loads(json_str)
                
                # Validate and normalize required fields
                normalized = {
                    "intent": result.get("intent", "general"),
                    "entities": result.get("entities", []),
                    "required_analytics": result.get("required_analytics", []),
                    "time_range": result.get("time_range", {"start": None, "end": None}),
                    "response": result.get("response", ""),
                    "explanation": result.get("explanation", "")
                }
                
                # Backward compatibility for workflow.py until it's updated
                normalized["general"] = (normalized["intent"] == "general")
                normalized["analytics"] = (normalized["intent"] == "analytics")
                normalized["sparql_query"] = "" # No longer generated by LLM
                
                # Flatten time_range for backward compatibility
                if normalized["time_range"]:
                    normalized["start_date"] = normalized["time_range"].get("start")
                    normalized["end_date"] = normalized["time_range"].get("end")
                else:
                    normalized["start_date"] = None
                    normalized["end_date"] = None

                logger.info("✅ Successfully parsed LLM JSON response")
                return normalized
            else:
                raise ValueError("No JSON found in LLM response")
                
        except Exception as e:
            logger.error(f"❌ Failed to parse LLM response: {e}")
            logger.error(f"Raw response: {llm_response[:500]}...")
            
            # Fallback: treat as general question
            return {
                "intent": "general",
                "entities": [],
                "required_analytics": [],
                "time_range": {"start": None, "end": None},
                "response": f"I'll try to answer your question: {user_query}. However, I had trouble understanding the query format. Could you please rephrase?",
                "explanation": "Fallback due to parse error",
                # Backward compatibility
                "general": True,
                "analytics": False,
                "sparql_query": "",
                "start_date": None,
                "end_date": None
            }
    
    async def generate_response(
        self,
        state: ConversationState,
        persona: str = "general"
    ) -> str:
        """Generate a conversational response using selected persona"""
        
        persona_config = PERSONAS.get(persona, PERSONAS["general"])
        messages = state.messages
        
        if not messages:
            return "Hello! How can I help you with the building systems today?"
        
        # Get conversation history
        history = format_conversation_history(messages, max_messages=5)
        latest_query = messages[-1].content
        
        # Check if we have query results to incorporate
        context = ""
        if state.intermediate_results:
            if "sparql_results" in state.intermediate_results:
                context = f"\\n\\nQuery Results: {state.intermediate_results['sparql_results']}"
            elif "sql_results" in state.intermediate_results:
                context = f"\\n\\nData Analysis Results: {state.intermediate_results['sql_results']}"
        
        prompt = f"""{persona_config['system_message']}

{history}

{context}

User's current question: {latest_query}

Provide a helpful, {persona_config['style']} response."""
        
        response = await llm_manager.generate(prompt)
        return response
    
    async def request_clarification(self, state: ConversationState) -> str:
        """Request clarification when intent is unclear"""
        latest_message = state.messages[-1] if state.messages else None
        
        if not latest_message:
            return "I'm not sure what you're asking. Could you please provide more details?"
        
        prompt = f"""The user asked: "{latest_message.content}"

This question is unclear. Generate a helpful clarification request that:
1. Acknowledges their question
2. Explains what might be unclear
3. Suggests 2-3 specific ways they could rephrase

Keep it friendly and concise (<100 words)."""
        
        response = await llm_manager.generate(prompt)
        return response
    
    async def format_response(
        self,
        state: ConversationState,
        response: str,
        intent: str
    ) -> str:
        """
        Format response with optional persona styling
        
        Args:
            state: Conversation state
            response: Raw response text
            intent: Detected intent
            
        Returns:
            Formatted response string
        """
        # For now, return response as-is
        # Can add persona formatting here later if needed
        return response
