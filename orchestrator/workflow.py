"""
LangGraph Workflow - Orchestrates agent execution
"""
import sys
import os
import json
sys.path.append('/app')

from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END
from shared.models import ConversationState, Message
from shared.utils import get_logger
from shared.config import settings
from orchestrator.agents import (
    DialogueAgent,
    SPARQLAgent,
    SQLAgent,
    AnalyticsAgent,
    VisualizationAgent
)

logger = get_logger(__name__)

class WorkflowOrchestrator:
    """LangGraph-based conversation workflow"""
    
    def __init__(self, redis_manager=None, postgres_manager=None):
        # Initialize agents
        self.dialogue_agent = DialogueAgent()
        self.sparql_agent = SPARQLAgent()
        # self.semantic_agent = SemanticOntologyAgent()  # DEPRECATED: Merged into SPARQLAgent
        self.sql_agent = SQLAgent()
        self.analytics_agent = AnalyticsAgent()
        self.viz_agent = VisualizationAgent()
        self.redis_manager = redis_manager  # Store reference to avoid circular imports
        self.postgres_manager = postgres_manager
        
        # Load sensor map
        self.sensor_map = {}
        try:
            if os.path.exists("data/sensor_map.json"):
                with open("data/sensor_map.json", "r", encoding="utf-8") as f:
                    self.sensor_map = json.load(f)
                logger.info(f"Loaded {len(self.sensor_map)} sensors from cache")
            else:
                logger.warning("data/sensor_map.json not found. Run scripts/cache_sensor_map.py")
        except Exception as e:
            logger.error(f"Failed to load sensor map: {e}")
        
        # Configuration: Use semantic agent by default, fallback to SPARQL
        self.use_semantic_ontology = settings.USE_SEMANTIC_ONTOLOGY
        self.ontology_mode = settings.ONTOLOGY_QUERY_MODE
        
        logger.info(f"Ontology query mode: {self.ontology_mode}, Use semantic: {self.use_semantic_ontology}")
        
        # Build workflow graph
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build LangGraph state machine"""
        
        # Create state graph
        workflow = StateGraph(ConversationState)
        
        # Add nodes for each stage
        workflow.add_node("dialogue", self._dialogue_node)
        workflow.add_node("sparql", self._sparql_node)
        workflow.add_node("sql", self._sql_node)
        workflow.add_node("analytics", self._analytics_node)
        workflow.add_node("visualization", self._visualization_node)
        workflow.add_node("response", self._response_node)
        
        # Set entry point
        workflow.set_entry_point("dialogue")
        
        # Add conditional routing from dialogue
        workflow.add_conditional_edges(
            "dialogue",
            self._route_from_dialogue,
            {
                "sparql": "sparql",
                "sql": "sql",
                "analytics": "analytics",
                "visualization": "visualization",
                "response": "response",
                "end": END
            }
        )
        
        # SPARQL -> Response or Visualization or SQL
        workflow.add_conditional_edges(
            "sparql",
            self._route_from_data_node,
            {
                "visualization": "visualization",
                "response": "response",
                "sql": "sql"
            }
        )
        
        # SQL -> Response or Analytics or Visualization
        workflow.add_conditional_edges(
            "sql",
            self._route_from_sql,
            {
                "analytics": "analytics",
                "visualization": "visualization",
                "response": "response"
            }
        )
        
        # Analytics -> Visualization or Response
        workflow.add_conditional_edges(
            "analytics",
            self._route_from_analytics_node,
            {
                "visualization": "visualization",
                "response": "response"
            }
        )
        
        # Visualization -> Response
        workflow.add_edge("visualization", "response")
        
        # Response -> END
        workflow.add_edge("response", END)
        
        return workflow.compile()
    
    async def _dialogue_node(self, state: ConversationState) -> ConversationState:
        """Process dialogue using LLM-based intent detection"""
        logger.info("Executing dialogue node with LLM-based intent detection")
        
        # NEW: Auto-titling for new conversations
        if len(state.messages) == 1 and state.title == "New Conversation":
            try:
                logger.info("🏷️ Generating conversation title...")
                title = await self.dialogue_agent.context_manager.generate_title(state.messages[0].content)
                state.title = title
                logger.info(f"🏷️ Title generated: {title}")
                
                # Update user's conversation list in Redis
                if self.redis_manager and state.user_id:
                    await self.redis_manager.add_conversation_to_user(
                        state.user_id, 
                        state.conversation_id, 
                        title
                    )
            except Exception as e:
                logger.error(f"Failed to generate title: {e}")
        
        # NEW: Get LLM-based intent detection result
        intent_result = await self.dialogue_agent.detect_intent(state)
        
        # Extract fields from LLM response (New Structure)
        intent = intent_result.get("intent", "general")
        entities = intent_result.get("entities", [])
        required_analytics = intent_result.get("required_analytics", [])
        time_range = intent_result.get("time_range", {})
        direct_response = intent_result.get("response", "")
        explanation = intent_result.get("explanation", "")
        
        # Backward compatibility mapping
        is_general = (intent == "general")
        analytics_required = (intent == "analytics") or (len(required_analytics) > 0)
        sparql_query = "" # No longer generated by DialogueAgent
        
        start_date = time_range.get("start")
        end_date = time_range.get("end")
        
        logger.info(f"📊 Intent Analysis:")
        logger.info(f"   ├─ Intent: {intent}")
        logger.info(f"   ├─ Entities: {entities}")
        logger.info(f"   ├─ Analytics Required: {analytics_required}")
        
        # Store in state for routing decisions and downstream agents
        state.intermediate_results["llm_intent"] = intent_result
        state.intermediate_results["intent"] = intent
        state.intermediate_results["entities"] = entities
        state.intermediate_results["required_analytics"] = required_analytics
        state.intermediate_results["analytics_required"] = analytics_required
        state.intermediate_results["start_date"] = start_date
        state.intermediate_results["end_date"] = end_date
        state.intermediate_results["explanation"] = explanation
        
        if is_general:
            # General knowledge question - use direct LLM response
            logger.info("✅ General knowledge question detected - returning direct answer")
            state.current_intent = "general_knowledge"
            state.intent = "general_knowledge"
            state.intermediate_results["dialogue_response"] = direct_response
            
        else:
            # Ontology/database query required
            if analytics_required:
                # Analytics query - route to SPARQL first to get UUIDs, then SQL
                logger.info("✅ Analytics query detected - routing to SPARQL (for UUIDs)")
                state.current_intent = "analytics"
                state.intent = "analytics"
            else:
                # Metadata query - route to SPARQL
                logger.info("✅ Metadata query detected - routing to SPARQL")
                state.current_intent = "sparql"
                state.intent = "sparql"
            
            # Clear any legacy LLM SPARQL query to force generation in SPARQL node
            state.intermediate_results["llm_sparql_query"] = ""
            
        logger.info(f"Final intent for routing: {state.current_intent}")
        return state
    
    async def _sparql_node(self, state: ConversationState) -> ConversationState:
        """
        Execute ontology query using LLM-generated SPARQL or semantic agent
        
        """
        logger.info("Executing SPARQL/ontology query node")
        
        latest_message = state.messages[-1].content if state.messages else ""
        
        # UNIFIED AGENT APPROACH:
        # Use SPARQLAgent for everything (it now handles semantic fallback internally)
        logger.info("Using Unified Ontology Agent (SPARQL + Semantic Fallback)")
        result = await self.sparql_agent.generate_query(state, latest_message)
        
        state.intermediate_results["sparql_result"] = result
        state.query_results = result.get("results", {})
        
        # Set analytics_required from LLM output (no default)
        state.analytics_required = result.get("analytics_required", False)
        logger.info(f"✅ Ontology Agent determined: analytics_required={state.analytics_required}")
        if result.get("llm_reasoning"):
            logger.info(f"💭 LLM reasoning: {result.get('llm_reasoning')}")
        
        # NEW: Save analytics decision and results as JSON
        if result.get("success"):
            self._save_query_output(
                conversation_id=state.conversation_id,
                query=latest_message,
                sparql=result.get("query"),
                results=result.get("results"),
                analytics_required=state.analytics_required,
                llm_reasoning=result.get("llm_reasoning", ""),
                formatted_response=result.get("formatted_response")
            )
        
        return state

    # DEPRECATED: Old logic removed
    async def _sparql_node_legacy(self, state: ConversationState) -> ConversationState:
        pass
    
    async def _sql_node(self, state: ConversationState) -> ConversationState:
        """Execute SQL query generation and execution"""
        logger.info("Executing SQL node")
        
        latest_message = state.messages[-1].content if state.messages else ""
        
        # Check if we have SPARQL results with UUIDs (from previous step)
        sparql_result = state.intermediate_results.get("sparql_result", {})
        
        uuids = []
        storage_map = {}
        
        if state.analytics_required and sparql_result.get("success"):
            try:
                # Handle standard SPARQL JSON results
                bindings = sparql_result.get("results", {}).get("results", {}).get("bindings", [])
                for binding in bindings:
                    current_uuid = None
                    current_storage = None
                    
                    # Look for 'uuid' or 'id' variable
                    for var in binding:
                        if "uuid" in var.lower() or "id" in var.lower():
                            val = binding[var]["value"]
                            if val and len(val) > 5: 
                                current_uuid = val
                        
                        # Look for 'storage' variable
                        if "storage" in var.lower():
                            current_storage = binding[var]["value"]
                    
                    if current_uuid:
                        uuids.append(current_uuid)
                        if current_storage:
                            storage_map[current_uuid] = current_storage
                
                uuids = list(set(uuids))
            except Exception as e:
                logger.warning(f"Failed to extract UUIDs from SPARQL result: {e}")

        if uuids:
            logger.info("="*80)
            logger.info(f"🔍 Found {len(uuids)} UUIDs from SPARQL results, fetching data...")
            logger.info("UUID → Storage Mapping:")
            for uuid in uuids:
                storage = storage_map.get(uuid, 'Unknown')
                logger.info(f"   • {uuid} → {storage}")
            logger.info("="*80)
            start_date = state.intermediate_results.get("start_date")
            end_date = state.intermediate_results.get("end_date")
            result = await self.sql_agent.fetch_data_for_uuids(uuids, latest_message, storage_map, start_date, end_date)
        else:
            # Fallback to standard SQL generation (text-to-SQL)
            logger.info("No UUIDs found or not analytics flow, using standard Text-to-SQL")
            result = await self.sql_agent.generate_and_execute(state, latest_message)
        
        state.intermediate_results["sql_result"] = result
        
        # Handle SQL failures properly
        if result.get("success"):
            state.query_results = result.get("results", {"data": []})
            logger.info(f"✅ SQL successful: {len(result.get('results', {}).get('data', []))} data records retrieved")
        else:
            state.query_results = {"data": []}  # Empty but valid structure
            logger.error(f"❌ SQL failed: {result.get('error', 'Unknown error')}")
        
        # SQL queries are always data queries requiring analytics
        state.analytics_required = True
        logger.info("✅ SQL query detected: analytics_required=True")
        
        return state
    
    async def _analytics_node(self, state: ConversationState) -> ConversationState:
        """Execute analytics code generation and execution"""
        logger.info("="*80)
        logger.info("🔬 Executing Analytics Node")
        logger.info("="*80)
        
        latest_message = state.messages[-1].content if state.messages else ""
        data = state.query_results
        
        # Extract sensor metadata (UUID to human-readable label mapping) from SPARQL results
        sensor_metadata = {}
        sparql_result = state.intermediate_results.get("sparql_result", {})
        if sparql_result.get("success"):
            bindings = sparql_result.get("results", {}).get("results", {}).get("bindings", [])
            for binding in bindings:
                uuid_val = None
                label_val = None
                sensor_val = None
                
                for var in binding:
                    # Look for UUID/ID/timeseries variables
                    if "uuid" in var.lower() or "id" in var.lower() or "timeseries" in var.lower():
                        uuid_val = binding[var]["value"]
                    elif "label" in var.lower():
                        label_val = binding[var]["value"]
                    elif "sensor" in var.lower():
                        sensor_val = binding[var]["value"]
                
                if uuid_val:
                    # Extract human-readable name from sensor URI if label is missing
                    if not label_val and sensor_val:
                        # Extract the last part after # or /
                        sensor_name = sensor_val.split('#')[-1] if '#' in sensor_val else sensor_val.split('/')[-1]
                        # Replace underscores with spaces for readability
                        label_val = sensor_name.replace('_', ' ')
                    
                    sensor_metadata[uuid_val] = {
                        "label": label_val or "Unknown Sensor",
                        "sensor_uri": sensor_val or "Unknown",
                        "uuid": uuid_val  # Store UUID for reference
                    }
        
        logger.info(f"📋 Extracted sensor metadata for {len(sensor_metadata)} sensors")
        for uuid, meta in sensor_metadata.items():
            logger.info(f"   • {uuid[:30]}... → {meta['label']}")
        
        # Store sensor metadata for response formatting
        state.intermediate_results["sensor_metadata"] = sensor_metadata
        
        # Save data to standard JSON format locally for analytics
        data_filename = "current_data.json"
        try:
            import json
            import os
            
            # Ensure directory exists
            os.makedirs("outputs/data", exist_ok=True)
            
            # Standard format: {"data": [...], "metadata": {...}}
            standard_data = {
                "data": data.get("data", []) if isinstance(data, dict) else data,
                "metadata": sensor_metadata
            }
            
            # Save to shared volume path with unique filename per user/conversation
            # This ensures data isolation between users
            safe_user_id = "".join(c for c in state.user_id if c.isalnum() or c in ('-', '_'))
            safe_conv_id = "".join(c for c in state.conversation_id if c.isalnum() or c in ('-', '_'))
            data_filename = f"{safe_user_id}_{safe_conv_id}_data.json"
            data_path = f"outputs/data/{data_filename}"
            
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(standard_data, f, indent=2, default=str)
            
            logger.info(f"💾 Saved analytics data to {data_path}")
            
        except Exception as e:
            logger.error(f"Failed to save analytics data locally: {e}")
            # Fallback to default if error occurs
            data_filename = "current_data.json"

        result = await self.analytics_agent.analyze(state, latest_message, data, sensor_metadata, data_filename)
        
        state.intermediate_results["analytics_result"] = result
        
        return state
    
    async def _visualization_node(self, state: ConversationState) -> ConversationState:
        """Execute visualization generation"""
        logger.info("Executing visualization node")
        
        latest_message = state.messages[-1].content if state.messages else ""
        data = state.query_results
        
        result = await self.viz_agent.create_visualization(state, latest_message, data)
        
        state.intermediate_results["viz_result"] = result
        
        return state
    
    async def _response_node(self, state: ConversationState) -> ConversationState:
        """Format final response"""
        logger.info("Executing response node")
        
        # Gather all results
        sparql_result = state.intermediate_results.get("sparql_result", {})
        sql_result = state.intermediate_results.get("sql_result", {})
        analytics_result = state.intermediate_results.get("analytics_result", {})
        viz_result = state.intermediate_results.get("viz_result", {})
        dialogue_response = state.intermediate_results.get("dialogue_response")
        
        # Build response - Prioritize most downstream result
        media_payload = None
        if dialogue_response:
            # Greeting or clarification or direct answer
            final_response = dialogue_response
        elif viz_result.get("formatted_response"):
            final_response = viz_result["formatted_response"]
            media_payload = viz_result.get("media")
        elif analytics_result.get("formatted_response"):
            final_response = analytics_result["formatted_response"]
            media_payload = analytics_result.get("media")
            
            # Replace any UUIDs in the response with human-readable sensor names
            # This ensures responses always use sensor names, not technical UUIDs
            analytics_node_metadata = state.intermediate_results.get("sensor_metadata", {})
            if analytics_node_metadata:
                for uuid, metadata in analytics_node_metadata.items():
                    if uuid in final_response:
                        final_response = final_response.replace(uuid, metadata.get("label", "Unknown Sensor"))
        elif sql_result.get("formatted_response"):
            final_response = sql_result["formatted_response"]
        elif sparql_result.get("formatted_response"):
            final_response = sparql_result["formatted_response"]
        else:
            final_response = "I processed your request, but couldn't generate a response."
        
        # Apply persona formatting
        final_response = await self.dialogue_agent.format_response(
            state, 
            final_response,
            state.current_intent
        )
        
        # Add to messages
        state.messages.append(Message(
            role="assistant",
            content=final_response,
            metadata={"media": media_payload} if media_payload else None
        ))
        
        return state

    def _route_from_dialogue(self, state: ConversationState) -> str:
        """Route from dialogue node based on intent"""
        intent = state.current_intent
        
        if intent in ["greeting", "clarification", "unknown", "general_knowledge"]:
            return "response"  # Skip to response
        elif intent == "sparql":
            return "sparql"
        elif intent == "sql":
            return "sql"
        elif intent == "analytics":
            # Analytics requires data fetching first (SPARQL -> SQL)
            return "sparql"
        elif intent == "visualization":
            return "visualization"
        else:
            return "response"
    
    def _route_from_data_node(self, state: ConversationState) -> str:
        """Route from SPARQL based on whether analytics/visualization is needed"""
        # Check if analytics is required (and we are coming from SPARQL)
        # Allow routing to SQL if intent is 'sparql' OR 'analytics'
        if state.analytics_required and (state.current_intent == "sparql" or state.current_intent == "analytics"):
             logger.info("Routing SPARQL -> SQL for data fetching (analytics=True)")
             return "sql"

        latest_message = state.messages[-1].content.lower() if state.messages else ""
        
        # Check if user wants visualization
        viz_keywords = ["plot", "chart", "graph", "visualize", "show", "display"]
        if any(keyword in latest_message for keyword in viz_keywords):
            return "visualization"
        
        return "response"

    def _route_from_analytics_node(self, state: ConversationState) -> str:
        """Route from Analytics based on whether visualization is needed"""
        # Check if analytics already generated a plot
        analytics_result = state.intermediate_results.get("analytics_result", {})
        output = analytics_result.get("output", "")
        if "PLOT_GENERATED" in str(output):
            logger.info("Analytics agent already generated a plot. Skipping separate visualization step.")
            return "response"

        # Analytics is done, check for visualization or finish
        latest_message = state.messages[-1].content.lower() if state.messages else ""
        
        # Check if user wants visualization
        viz_keywords = ["plot", "chart", "graph", "visualize", "show", "display"]
        if any(keyword in latest_message for keyword in viz_keywords):
            return "visualization"
        
        return "response"
    
    def _route_from_sql(self, state: ConversationState) -> str:
        """Route from SQL node"""
        # If analytics is required (which is true for all SQL queries in this pipeline),
        # route to analytics agent to process the data
        if state.analytics_required:
            return "analytics"

        latest_message = state.messages[-1].content.lower() if state.messages else ""
        
        # Check for visualization request
        viz_keywords = ["plot", "chart", "graph", "visualize", "show", "display"]
        if any(keyword in latest_message for keyword in viz_keywords):
            return "visualization"
        
        # Check for analytics request
        analytics_keywords = ["analyze", "analysis", "pattern", "correlation", "statistics"]
        if any(keyword in latest_message for keyword in analytics_keywords):
            return "analytics"
        
        return "response"
    
    async def execute(self, state: ConversationState) -> ConversationState:
        """
        Execute workflow for given state
        
        Args:
            state: Initial conversation state
            
        Returns:
            Updated conversation state with response
        """
        try:
            logger.info(f"Starting workflow execution for conversation {state.conversation_id}")
            
            # Run the graph
            final_state = await self.graph.ainvoke(state)

            # LangGraph may return a dict-like state; rehydrate if needed
            if not isinstance(final_state, ConversationState):
                try:
                    # Convert AddableValuesDict / dict into ConversationState
                    final_state = ConversationState(**dict(final_state))
                except Exception as conv_err:
                    logger.error(f"State rehydration failed: {conv_err}")
                    # Fallback: attach minimal fields
                    final_state = state
            
            logger.info(f"Workflow completed for conversation {state.conversation_id}")
            return final_state
            
        except Exception as e:
            logger.error(f"Workflow execution error: {e}", exc_info=True)
            
            # Add error message
            state.messages.append(Message(
                role="assistant",
                content=f"I encountered an error processing your request: {str(e)}"
            ))
            
            return state
    
    def _save_query_output(
        self,
        conversation_id: str,
        query: str,
        sparql: str,
        results: Dict[str, Any],
        analytics_required: bool,
        llm_reasoning: str,
        formatted_response: str
    ):
        """
        Save query output as JSON file with analytics decision
        
        Output format:
        {
            "conversation_id": "...",
            "timestamp": "...",
            "user_query": "...",
            "analytics": true/false,
            "llm_reasoning": "...",
            "sparql_query": "...",
            "sparql_results": {...},
            "formatted_response": "..."
        }
        """
        import json
        from datetime import datetime
        from pathlib import Path
        
        try:
            # Create output directory if it doesn't exist
            output_dir = Path("/app/outputs/query_results")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{conversation_id}_{timestamp}.json"
            filepath = output_dir / filename
            
            # Prepare output data
            output_data = {
                "conversation_id": conversation_id,
                "timestamp": datetime.now().isoformat(),
                "user_query": query,
                "analytics": analytics_required,
                "llm_reasoning": llm_reasoning,
                "sparql_query": sparql,
                "sparql_results": results,
                "formatted_response": formatted_response,
                "metadata": {
                    "result_count": len(results.get("results", {}).get("bindings", [])) if isinstance(results, dict) else 0,
                    "execution_successful": True
                }
            }
            
            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✅ Saved query output to: {filepath}")
            logger.info(f"   Analytics required: {analytics_required}")
            
        except Exception as e:
            logger.error(f"Failed to save query output: {e}", exc_info=True)
    
    async def stream_execute(self, state: ConversationState):
        """
        Execute workflow with streaming
        
        Yields:
            Intermediate states as they're processed
        """
        try:
            logger.info(f"Starting streaming workflow for conversation {state.conversation_id}")
            
            async for step in self.graph.astream(state):
                yield step
                
        except Exception as e:
            logger.error(f"Streaming workflow error: {e}", exc_info=True)
            yield {
                "error": str(e),
                "state": state
            }
