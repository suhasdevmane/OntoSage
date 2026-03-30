"""
LangGraph Workflow - Orchestrates agent execution
"""
import sys
import os
import json
import re
import asyncio
sys.path.append('/app')

from typing import Dict, Any, Literal
from uuid import uuid4
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
# Phase 4 agents
from orchestrator.agents.report_agent import ReportAgent
from orchestrator.agents.data_export_agent import DataExportAgent
from orchestrator.agents.planner_agent import PlannerAgent
from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent
# CAP-01: Document agent
from orchestrator.agents.document_agent import DocumentAgent
# B.7: Deterministic analytics engine
from orchestrator.services.analytics_engine import AnalyticsEngine, AnalysisRequest
# CAP-03: Persona-aware post-processing
from orchestrator.services.persona_adapter import get_persona_adapter
# CAP-04: Compliance standards engine
from orchestrator.services.standards_engine import get_standards_engine
# CAP-07: Multi-hop reasoning engine
from orchestrator.services.reasoning_engine import get_reasoning_engine
# WIRE-A: i18n service (translate query in, response out)
try:
    from orchestrator.services.i18n_service import I18nService
    _I18N_AVAILABLE = True
except ImportError:
    _I18N_AVAILABLE = False

logger = get_logger(__name__)

class WorkflowOrchestrator:
    """LangGraph-based conversation workflow"""
    
    def __init__(self, redis_manager=None, postgres_manager=None):
        # Initialize agents
        self.dialogue_agent = DialogueAgent()
        self.sparql_agent = SPARQLAgent()
        self.sql_agent = SQLAgent()
        self.analytics_agent = AnalyticsAgent()
        self.viz_agent = VisualizationAgent()
        # Phase 4 agents
        self.report_agent = ReportAgent()
        self.export_agent = DataExportAgent()
        self.planner_agent = PlannerAgent()
        self.anomaly_agent = AnomalyDetectionAgent()
        # CAP-01: Document agent
        self.document_agent = DocumentAgent()
        self.redis_manager = redis_manager
        self.postgres_manager = postgres_manager
        self.response_cache = None  # injected by main.py lifespan after Redis is ready
        self.agent_memory = None    # injected by main.py lifespan after Qdrant is ready
        self.smart_cache = None     # injected by main.py lifespan after Redis is ready
        # B.7: Deterministic analytics engine (no LLM needed for known analysis types)
        self.analytics_engine = AnalyticsEngine()
        # WIRE-A: i18n service singleton (stateless, lazy-init)
        self._i18n: 'I18nService | None' = None
        if _I18N_AVAILABLE:
            try:
                from orchestrator.llm_manager import llm_manager as _llm
                self._i18n = I18nService(llm_manager=_llm)
                logger.info("i18n service initialized")
            except Exception as _ie:
                logger.warning(f"i18n service init failed (non-fatal): {_ie}")
        # CAP-03: Persona adapter singleton
        self._persona_adapter = get_persona_adapter()
        # CAP-04: Standards engine singleton
        self._standards_engine = get_standards_engine()
        # CAP-07: Multi-hop reasoning engine
        self._reasoning_engine = get_reasoning_engine()
        
        # Load sensor map
        self.sensor_map = {}
        try:
            if os.path.exists(settings.SENSOR_MAP_PATH):
                with open(settings.SENSOR_MAP_PATH, "r", encoding="utf-8") as f:
                    self.sensor_map = json.load(f)
                logger.info(f"Loaded {len(self.sensor_map)} sensors from cache")
            else:
                logger.warning(f"{settings.SENSOR_MAP_PATH} not found. Run scripts/cache_sensor_map.py")
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
        
        # Core nodes — dialogue and response are never wrapped (they are the
        # entry/exit of the pipeline and must always run).  Data-fetching nodes
        # are wrapped with _safe_node for graceful degradation on failures.
        workflow.add_node("dialogue", self._dialogue_node)
        workflow.add_node("sparql", self._safe_node(self._sparql_node, "sparql"))
        workflow.add_node("sql", self._safe_node(self._sql_node, "sql"))
        workflow.add_node("analytics", self._safe_node(self._analytics_node, "analytics"))
        workflow.add_node("visualization", self._safe_node(self._visualization_node, "visualization"))
        workflow.add_node("response", self._response_node)
        # Phase 4 nodes
        workflow.add_node("planner", self._safe_node(self._planner_node, "planner"))
        workflow.add_node("report", self._safe_node(self._report_node, "report"))
        workflow.add_node("anomaly", self._safe_node(self._anomaly_node, "anomaly"))
        workflow.add_node("export", self._safe_node(self._export_node, "export"))
        
        # Entry
        workflow.set_entry_point("dialogue")
        
        # Dialogue routing (14 intents)
        workflow.add_conditional_edges(
            "dialogue",
            self._route_from_dialogue,
            {
                "sparql": "sparql",
                "sql": "sql",
                "analytics": "analytics",
                "visualization": "visualization",
                "planner": "planner",
                "report": "report",
                "anomaly": "anomaly",
                "export": "export",
                "response": "response",
                "end": END
            }
        )
        
        # SPARQL → SQL / response
        workflow.add_conditional_edges(
            "sparql",
            self._route_from_data_node,
            {"visualization": "visualization", "response": "response", "sql": "sql"}
        )
        
        # SQL → Analytics / response
        workflow.add_conditional_edges(
            "sql",
            self._route_from_sql,
            {"analytics": "analytics", "visualization": "visualization",
             "anomaly": "anomaly", "report": "report", "response": "response"}
        )
        
        # Analytics → Viz / response
        workflow.add_conditional_edges(
            "analytics",
            self._route_from_analytics_node,
            {"visualization": "visualization", "response": "response"}
        )
        
        # Phase 4 nodes all lead to response
        workflow.add_edge("planner", "response")
        workflow.add_edge("report", "response")
        workflow.add_edge("anomaly", "response")
        workflow.add_edge("export", "response")
        workflow.add_edge("visualization", "response")
        workflow.add_edge("response", END)
        
        return workflow.compile()
    
    def _safe_node(self, node_fn, node_name: str):
        """
        Wrap a node function with try/except for graceful degradation.
        On unhandled exception, the pipeline continues with a user-friendly
        error stored in intermediate_results rather than crashing.
        """
        async def wrapper(state: ConversationState) -> ConversationState:
            try:
                return await node_fn(state)
            except Exception as e:
                logger.error(f"Node '{node_name}' failed: {e}", exc_info=True)
                friendly = self._user_friendly_error(e)
                state.intermediate_results[f"{node_name}_error"] = str(e)
                # For data nodes, ensure downstream nodes see empty-but-valid data
                if node_name == "sparql":
                    state.intermediate_results["sparql_result"] = {"success": False, "error": str(e)}
                    state.query_results = {}
                elif node_name == "sql":
                    state.intermediate_results["sql_result"] = {"success": False, "error": str(e)}
                    state.query_results = {"data": []}
                elif node_name == "analytics":
                    state.intermediate_results["analytics_result"] = {"success": False, "error": str(e)}
                # Store the friendly error for the response node to pick up
                state.intermediate_results.setdefault("degraded_services", []).append(
                    {"node": node_name, "message": friendly}
                )
                return state
        return wrapper

    async def _dialogue_node(self, state: ConversationState) -> ConversationState:
        """Process dialogue using LLM-based intent detection"""
        logger.info("Executing dialogue node with LLM-based intent detection")

        # WIRE-A: i18n — detect language and translate query to English
        _user_lang = "en"
        if self._i18n and state.messages:
            try:
                _raw_query = state.messages[-1].content
                _en_query, _user_lang = await self._i18n.to_english(_raw_query)
                if _user_lang != "en":
                    logger.info(f"i18n: translated query from {_user_lang} to English")
                    # Replace last message content with translated version for pipeline
                    state.messages[-1] = Message(
                        role=state.messages[-1].role,
                        content=_en_query,
                        metadata=state.messages[-1].metadata,
                    )
                state.intermediate_results["_user_lang"] = _user_lang
            except Exception as _i18n_err:
                logger.debug(f"i18n input translation skipped: {_i18n_err}")
        
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
        
        # B.3: Inject relevant user memories as context for the dialogue agent
        if self.agent_memory and state.user_id:
            try:
                user_query = state.messages[-1].content if state.messages else ""
                memory_context = await self.agent_memory.retrieve_context(state.user_id, user_query)
                if memory_context:
                    state.intermediate_results["memory_context"] = memory_context
            except Exception as _mem_err:
                logger.debug(f"Agent memory retrieve skipped: {_mem_err}")

        # NEW: Get LLM-based intent detection result
        intent_result = await self.dialogue_agent.detect_intent(state)
        
        # Extract fields from LLM response (New Structure)
        intent = intent_result.get("intent", "general")
        entities = intent_result.get("entities") or []
        required_analytics = intent_result.get("required_analytics") or []
        time_range = intent_result.get("time_range") or {}
        direct_response = intent_result.get("response", "")
        explanation = intent_result.get("explanation", "")
        clarification_question = intent_result.get("clarification_question", "")
        discovery_filter = intent_result.get("discovery_filter")
        
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
        # Phase 4.1 new fields
        state.intermediate_results["export_format"] = intent_result.get("export_format")
        state.intermediate_results["report_type"] = intent_result.get("report_type")
        state.intermediate_results["recommendation_domain"] = intent_result.get("recommendation_domain")
        
        if intent == "clarification":
            state.current_intent = "clarification"
            state.needs_clarification = True
            state.clarification_question = clarification_question
            state.intermediate_results["dialogue_response"] = clarification_question or \
                "Could you please provide more details about your question?"

        elif intent == "discovery":
            state.current_intent = "discovery"
            # For spatial/zone queries, skip sensor-map response — let SPARQL handle it
            _uq = (state.messages[-1].content if state.messages else "").lower()
            _spatial = ['zone', 'floor', 'room', 'space', 'level', 'area', 'location']
            if any(w in _uq for w in _spatial):
                pass  # dialogue_response intentionally not set; SPARQL node will answer
            else:
                discovery_response = self._handle_sensor_discovery(discovery_filter, entities)
                state.intermediate_results["dialogue_response"] = discovery_response

        elif intent in ("control",):
            # Control commands not yet supported
            state.current_intent = "control"
            state.intermediate_results["dialogue_response"] = (
                "🔒 Building system control commands are not yet supported in this version. "
                "Please contact your facilities team for manual adjustments."
            )

        elif intent == "greeting":
            state.current_intent = "greeting"
            state.intermediate_results["dialogue_response"] = (
                direct_response or "Hello! I'm OntoSage, your smart building assistant. How can I help you today?"
            )

        elif intent in ("planner",):
            state.current_intent = "planner"

        elif intent in ("report",):
            # Report needs SPARQL + SQL first; planner handles that
            state.current_intent = "report"

        elif intent in ("anomaly",):
            state.current_intent = "anomaly"

        elif intent in ("export",):
            state.current_intent = "export"

        elif intent in ("compare", "trend", "recommend", "compliance"):
            # For these intents, run through SPARQL + SQL + analytics pipeline
            logger.info(f"☕ Intent '{intent}' routes via SPARQL→SQL→Analytics")
            state.current_intent = "analytics"

        elif intent == "visualization":
            state.current_intent = "visualization"

        elif is_general:
            state.current_intent = "general_knowledge"
            state.intermediate_results["dialogue_response"] = direct_response

        else:
            # Unknown intent — return friendly error
            if intent == "unknown" or not intent:
                state.current_intent = "unknown"
                state.intermediate_results["dialogue_response"] = (
                    "I'm not sure I understood your question. Could you please rephrase or "
                    "ask about a specific aspect of the building such as sensors, temperature, "
                    "energy, or air quality?"
                )
            elif analytics_required:
                state.current_intent = "analytics"
            else:
                state.current_intent = "sparql"
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
        
        # Set analytics_required: SPARQL agent can elevate to True, but
        # if dialogue node already set it True (intent==analytics), keep True.
        sparql_analytics = result.get("analytics_required", False)
        dialogue_analytics = state.intermediate_results.get("analytics_required", False)
        state.analytics_required = sparql_analytics or dialogue_analytics
        logger.info(f"✅ Ontology Agent determined: analytics_required={state.analytics_required} "
                    f"(sparql={sparql_analytics}, dialogue={dialogue_analytics})")
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
                    
                    # Look for 'uuid' or 'id' variable — validate with UUID4 regex
                    _UUID_RE = re.compile(
                        r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$',
                        re.IGNORECASE
                    )
                    for var in binding:
                        if "uuid" in var.lower() or "id" in var.lower():
                            val = binding[var]["value"]
                            if val and _UUID_RE.match(val):
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
            row_count = len(result.get("results", {}).get("data", []))
            logger.info(f"SQL successful: {row_count} data records retrieved")

            # Phase 3.1: Notify SmartCacheManager about new data for staleness tracking
            if self.smart_cache and uuids and row_count > 0:
                try:
                    for uid in uuids:
                        await self.smart_cache.on_new_readings(uid, row_count)
                except Exception as _sc_err:
                    logger.debug(f"SmartCache staleness update skipped: {_sc_err}")
        else:
            state.query_results = {"data": []}  # Empty but valid structure
            logger.error(f"SQL failed: {result.get('error', 'Unknown error')}")
        
        # Only mark analytics_required for intents that actually need data processing
        _analytics_intents = {"analytics", "compare", "trend", "recommend", "compliance", "anomaly"}
        if state.current_intent in _analytics_intents:
            state.analytics_required = True
            logger.info(f"✅ Intent '{state.current_intent}' requires analytics: analytics_required=True")
        else:
            logger.info(f"ℹ️  Intent '{state.current_intent}' does not require analytics post-SQL")
        
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
            os.makedirs(settings.OUTPUT_DATA_DIR, exist_ok=True)

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
            data_path = f"{settings.OUTPUT_DATA_DIR}/{data_filename}"
            
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(standard_data, f, indent=2, default=str)
            
            logger.info(f"💾 Saved analytics data to {data_path}")
            
        except Exception as e:
            logger.error(f"Failed to save analytics data locally: {e}")
            # Use a unique fallback name to prevent concurrent-request collisions
            data_filename = f"fallback_{uuid4().hex}_data.json"

        # B.7: Try deterministic Analytics Engine before falling back to LLM code generation
        det_result = await self._try_deterministic_analytics(
            intent=state.current_intent,
            query=latest_message,
            data=data,
        )
        if det_result:
            logger.info(f"✅ Deterministic analytics handled intent='{state.current_intent}' (saved LLM call)")
            state.intermediate_results["analytics_result"] = {
                "formatted_response": det_result.formatted_response,
                "success": det_result.success,
                "metrics": det_result.metrics,
                "violations": det_result.violations,
                "grade": det_result.grade,
                "recommendations": det_result.recommendations,
                "source": "deterministic",
            }
            return state

        # Fallback: LLM-generated Python code via analytics_agent
        result = await self.analytics_agent.analyze(state, latest_message, data, sensor_metadata, data_filename)

        state.intermediate_results["analytics_result"] = result

        return state

    # ──────────────────────────────────────────────────────────────────────────
    # B.7 helper: map intent/query to deterministic analyser
    # ──────────────────────────────────────────────────────────────────────────

    _INTENT_TO_ANALYSIS: dict = {
        "compliance": "compliance",
        "trend":      "trend",
    }

    _QUERY_KEYWORDS_TO_ANALYSIS: list = [
        ({"comfort", "ashrae", "well", "en15251", "temperature range", "humidity range"}, "comfort"),
        ({"energy", "kwh", "watt", "power", "electricity", "peak", "eui"},               "energy"),
        ({"iaq", "air quality", "co2", "co₂", "voc", "pm2", "pm10"},                     "iaq"),
        ({"trend", "increasing", "decreasing", "mann-kendall", "slope"},                  "trend"),
        ({"comply", "compliance", "standard", "regulation", "breeam", "leed"},            "compliance"),
    ]

    async def _try_deterministic_analytics(self, intent: str, query: str, data) -> object:
        """
        Attempt to resolve the analytics request using a deterministic module.
        Returns an AnalysisResult if handled, or None to fall through to LLM.
        """
        rows = data.get("data", []) if isinstance(data, dict) else (data or [])
        if not rows:
            return None

        # Detect analysis type from intent or query keywords
        analysis_type = self._INTENT_TO_ANALYSIS.get(intent)
        if not analysis_type:
            query_lower = query.lower()
            for keywords, atype in self._QUERY_KEYWORDS_TO_ANALYSIS:
                if any(kw in query_lower for kw in keywords):
                    analysis_type = atype
                    break

        if not analysis_type:
            return None

        # Build schema: map first numeric column to the matching sensor type key
        schema: dict = {}
        if rows:
            for col in rows[0].keys():
                col_lower = col.lower()
                for known in ("temperature", "humidity", "co2", "voc", "energy", "power"):
                    if known in col_lower and known not in schema:
                        schema[known] = col
                        break

        if not schema:
            return None

        try:
            req = AnalysisRequest(analysis_type=analysis_type, data=rows, schema=schema)
            result = await self.analytics_engine.run(req)

            # CAP-04: Augment compliance results with StandardsEngine checks
            if analysis_type == "compliance" and rows:
                try:
                    # Build a readings dict from latest sensor row
                    _latest = rows[-1] if rows else {}
                    _readings = {}
                    _param_map = {
                        "temperature": "temp_c", "co2": "co2_ppm",
                        "humidity": "humidity_rh", "pm25": "pm25_ugm3",
                        "pm10": "pm10_ugm3", "voc": "tvoc_ppb",
                    }
                    for col, pkey in _param_map.items():
                        for k, v in _latest.items():
                            if col in str(k).lower():
                                try:
                                    _readings[pkey] = float(v)
                                except (TypeError, ValueError):
                                    pass

                    if _readings:
                        query_lower = query.lower()
                        for std_id in ("breeam", "well_v2", "ashrae55", "en15251", "iso50001"):
                            if std_id.replace("_", "") in query_lower or std_id in query_lower:
                                std_check = self._standards_engine.check(std_id, _readings)
                                if result.metrics is None:
                                    result.metrics = {}
                                result.metrics[f"standards_{std_id}"] = std_check
                                logger.info(f"CAP-04: {std_id} compliance: {std_check['overall_status']}")
                                break
                except Exception as _std_err:
                    logger.debug(f"Standards engine augmentation skipped: {_std_err}")

            return result
        except Exception as e:
            logger.warning(f"Deterministic analytics failed ({analysis_type}): {e}")
            return None
    
    async def _visualization_node(self, state: ConversationState) -> ConversationState:
        """Execute visualization generation"""
        logger.info("Executing visualization node")
        
        latest_message = state.messages[-1].content if state.messages else ""
        data = state.query_results
        
        result = await self.viz_agent.create_visualization(state, latest_message, data)
        
        state.intermediate_results["viz_result"] = result
        
        return state
    
    async def _response_node(self, state: ConversationState) -> ConversationState:
        """Format final response — with response-cache store after generation."""
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
            final_response = dialogue_response
        elif viz_result.get("formatted_response"):
            final_response = viz_result["formatted_response"]
            media_payload = viz_result.get("media")
        # Phase 4 results (highest priority after viz)
        elif state.intermediate_results.get("planner_result", {}).get("formatted_response") or \
             state.intermediate_results.get("planner_result", {}).get("formatted_text"):
            pr = state.intermediate_results["planner_result"]
            final_response = pr.get("formatted_response") or pr.get("formatted_text")
        elif state.intermediate_results.get("report_result", {}).get("formatted_text"):
            final_response = state.intermediate_results["report_result"]["formatted_text"]
        elif state.intermediate_results.get("anomaly_result", {}).get("formatted_response"):
            final_response = state.intermediate_results["anomaly_result"]["formatted_response"]
        elif state.intermediate_results.get("export_result", {}).get("success"):
            er = state.intermediate_results["export_result"]
            final_response = (
                f"✅ Export complete — **{er['filename']}** ({er['row_count']} rows, {er['size_bytes']} bytes).\n\n"
                f"Preview (first 2000 chars):\n```\n{er['content'][:2000]}\n```"
            )
        elif analytics_result.get("formatted_response"):
            final_response = analytics_result["formatted_response"]
            media_payload = analytics_result.get("media")
            # Replace UUIDs with human-readable sensor names
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

        
        # If any nodes degraded, append a brief notice so the user knows
        degraded = state.intermediate_results.get("degraded_services")
        if degraded:
            notices = set(d["message"] for d in degraded)
            notice_text = "\n\n---\n*Note: " + " ".join(notices) + "*"
            final_response += notice_text

        # Apply persona formatting
        final_response = await self.dialogue_agent.format_response(
            state,
            final_response,
            state.current_intent
        )

        # Phase 7.2: Append proactive follow-up suggestions based on intent
        suggestions = self._get_follow_up_suggestions(state.current_intent)
        if suggestions:
            final_response += f"\n\n---\n**You might also ask:** {suggestions}"

        # CAP-03: Persona-aware post-processing (reframes facts per persona)
        persona = getattr(state, "persona", "general") or "general"
        if persona and persona != "general":
            try:
                from orchestrator.llm_manager import llm_manager as _llm
                final_response = await self._persona_adapter.enhance(
                    final_response,
                    persona=persona,
                    intent=state.current_intent or "general",
                    llm_manager=_llm,
                )
            except Exception as _pa_err:
                logger.debug(f"Persona adapter skipped: {_pa_err}")

        # WIRE-A: i18n — translate response back to user's language
        _user_lang = state.intermediate_results.get("_user_lang", "en")
        if self._i18n and _user_lang and _user_lang != "en":
            try:
                final_response = await self._i18n.from_english(final_response, _user_lang)
                logger.info(f"i18n: translated response to {_user_lang}")
            except Exception as _i18n_out_err:
                logger.debug(f"i18n output translation skipped: {_i18n_out_err}")

        # Add to messages
        state.messages.append(Message(
            role="assistant",
            content=final_response,
            metadata={"media": media_payload} if media_payload else None
        ))

        # B.2: Store in response cache (non-blocking, best-effort)
        if self.response_cache:
            try:
                original_query = state.messages[-2].content if len(state.messages) >= 2 else ""
                if original_query:
                    await self.response_cache.put(
                        question=original_query,
                        response=final_response,
                        intent=state.current_intent or "general",
                        media=[media_payload] if media_payload else [],
                        building_id=state.building_id,
                    )
            except Exception as _cache_err:
                logger.debug(f"Response cache store skipped: {_cache_err}")

        # B.3: Store successful interaction in agent memory for future context retrieval
        if self.agent_memory and state.user_id:
            try:
                original_query = state.messages[-2].content if len(state.messages) >= 2 else ""
                entities = state.intermediate_results.get("entities", [])
                await self.agent_memory.store_success(
                    user_id=state.user_id,
                    query=original_query,
                    intent=state.current_intent or "general",
                    entities=entities if isinstance(entities, list) else [],
                    answer_summary=final_response[:200],
                )
            except Exception as _mem_err:
                logger.debug(f"Agent memory store skipped: {_mem_err}")

        # Phase 5.5: Clean up bulky intermediate results to reduce Redis state size
        _bulky_keys = ["sparql_result", "sql_result", "analytics_result", "viz_result",
                       "sensor_metadata", "degraded_services", "memory_context"]
        for key in _bulky_keys:
            state.intermediate_results.pop(key, None)

        return state

    def _handle_sensor_discovery(self, discovery_filter: str = None, entities: list = None) -> str:
        """
        Build a sensor discovery response from the cached sensor_map.
        
        Args:
            discovery_filter: Optional keyword to filter sensors (e.g. "temperature", "zone 5")
            entities: Optional entity list from intent detection
            
        Returns:
            Formatted string listing available sensors
        """
        if not self.sensor_map:
            return ("I don't have a cached sensor catalogue right now. "
                    "You can ask me about specific sensor types like temperature, "
                    "humidity, or air quality sensors.")
        
        # Deduplicate: sensor_map has multiple key formats (name, label, URI) pointing
        # to the same sensor. Collect unique sensors by their URI.
        unique_sensors = {}
        for key, info in self.sensor_map.items():
            uri = info.get("uri", key)
            if uri not in unique_sensors:
                unique_sensors[uri] = {
                    "label": info.get("label", key),
                    "uuid": info.get("uuid", ""),
                    "storage": info.get("storage", ""),
                }
        
        # Apply filter
        filter_text = discovery_filter or ""
        if entities and not filter_text:
            filter_text = " ".join(entities)
        filter_lower = filter_text.lower().strip()
        
        if filter_lower:
            filtered = {
                uri: s for uri, s in unique_sensors.items()
                if filter_lower in s["label"].lower() or filter_lower in uri.lower()
            }
        else:
            filtered = unique_sensors
        
        total = len(unique_sensors)
        matched = len(filtered)
        
        if matched == 0:
            # No match — show summary of available types
            type_counts = self._count_sensor_types(unique_sensors)
            type_summary = ", ".join(f"**{t}** ({c})" for t, c in sorted(type_counts.items(), key=lambda x:-x[1])[:10])
            return (f"I couldn't find sensors matching **\"{filter_text}\"**.\n\n"
                    f"I have **{total}** sensors total. Available types: {type_summary}.\n\n"
                    f"Try asking about a specific type (e.g., *\"list all temperature sensors\"*).")
        
        # If too many results, show a grouped summary
        if matched > 20:
            type_counts = self._count_sensor_types(filtered)
            type_summary = "\n".join(f"- **{t}**: {c} sensors" for t, c in sorted(type_counts.items(), key=lambda x:-x[1]))
            filter_note = f" matching **\"{filter_text}\"**" if filter_lower else ""
            return (f"Found **{matched}** sensors{filter_note} (out of {total} total):\n\n"
                    f"{type_summary}\n\n"
                    f"To see specific sensors, ask something like *\"list all Air Temperature sensors\"* "
                    f"or *\"what sensors are in zone 5?\"*.")
        
        # Show individual sensors
        lines = []
        for uri, s in sorted(filtered.items(), key=lambda x: x[1]["label"]):
            lines.append(f"- **{s['label']}** (storage: {s['storage'] or 'N/A'})")
        
        sensor_list = "\n".join(lines)
        filter_note = f" matching **\"{filter_text}\"**" if filter_lower else ""
        return (f"Found **{matched}** sensors{filter_note}:\n\n{sensor_list}\n\n"
                f"You can ask about any of these sensors, for example: "
                f"*\"What is the current reading of {list(filtered.values())[0]['label']}?\"*")
    
    @staticmethod
    def _count_sensor_types(sensors: dict) -> dict:
        """Group sensors by type (e.g. Air_Temperature, Humidity, CO2)"""
        type_counts = {}
        for uri, info in sensors.items():
            label = info.get("label", "")
            # Extract type: everything before the last underscore + number pattern
            # e.g. "Air Temperature Sensor 5.04" -> "Air Temperature Sensor"
            parts = label.rsplit(" ", 1)
            if len(parts) == 2 and any(c.isdigit() for c in parts[1]):
                sensor_type = parts[0]
            else:
                sensor_type = label
            type_counts[sensor_type] = type_counts.get(sensor_type, 0) + 1
        return type_counts

    def _route_from_dialogue(self, state: ConversationState) -> str:
        """Route from dialogue node based on intent (17 intents supported)."""
        intent = state.current_intent

        # Direct-to-response intents (no data fetching needed)
        # Exception: discovery with spatial/zone keywords should run SPARQL
        if intent == "discovery":
            user_query = (state.messages[-1].content if state.messages else "").lower()
            spatial_words = ['zone', 'floor', 'room', 'space', 'level', 'area', 'location',
                             'list zone', 'list floor', 'list room', 'how many zone',
                             'how many floor', 'how many room']
            if any(w in user_query for w in spatial_words):
                return "sparql"
            return "response"
        if intent in ["greeting", "clarification", "unknown",
                      "general_knowledge", "control"]:
            return "response"
        # Phase 4 multi-agent paths
        elif intent == "planner":
            return "planner"
        elif intent == "report":
            return "planner"  # report routes through planner for SPARQL+SQL+report
        elif intent == "anomaly":
            return "sparql"  # need UUIDs first, then SQL, then anomaly in _route_from_sql
        elif intent == "export":
            return "export"
        # Standard paths
        elif intent in ["sparql", "metadata"]:
            return "sparql"
        elif intent == "sql":
            return "sql"
        elif intent in ["analytics", "compare", "trend", "recommend", "compliance"]:
            return "sparql"  # SPARQL → SQL → Analytics
        elif intent == "visualization":
            # BUG-C FIX: visualization needs data first → route through SPARQL → SQL → viz
            # The visualization node is reached after SQL via _route_from_sql→visualization
            return "sparql"
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
        """Route from SQL node — extended for Phase 4 anomaly/report intents."""
        intent = state.current_intent

        # Phase 4: anomaly and report intents use SQL data for their agents
        if intent == "anomaly":
            return "anomaly"
        if intent in ("report",):
            return "report"

        if state.analytics_required:
            return "analytics"

        latest_message = state.messages[-1].content.lower() if state.messages else ""
        viz_keywords = ["plot", "chart", "graph", "visualize", "show", "display"]
        if any(keyword in latest_message for keyword in viz_keywords):
            return "visualization"
        analytics_keywords = ["analyze", "analysis", "pattern", "correlation", "statistics"]
        if any(keyword in latest_message for keyword in analytics_keywords):
            return "analytics"
        return "response"

    # ------------------------------------------------------------------
    # Phase 4 Node Implementations
    # ------------------------------------------------------------------

    async def _planner_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.4 — Multi-step planner for complex queries."""
        logger.info("Executing Phase 4 Planner Node")
        latest_message = state.messages[-1].content if state.messages else ""
        result = await self.planner_agent.plan_and_execute(state, latest_message)
        state.intermediate_results["planner_result"] = result
        return state

    async def _report_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.2 — Report generation node."""
        logger.info("Executing Phase 4 Report Node")
        latest_message = state.messages[-1].content if state.messages else ""
        sql_result = state.intermediate_results.get("sql_result")
        sparql_result = state.intermediate_results.get("sparql_result")
        export_fmt = state.intermediate_results.get("export_format")
        result = await self.report_agent.generate(
            state, latest_message,
            sensor_data=sql_result, metadata=sparql_result,
            export_format=export_fmt,
        )
        state.intermediate_results["report_result"] = result
        return state

    async def _anomaly_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.7 — Anomaly detection node."""
        logger.info("Executing Phase 4 Anomaly Detection Node")
        latest_message = state.messages[-1].content if state.messages else ""
        sql_result = state.intermediate_results.get("sql_result")
        result = await self.anomaly_agent.detect(state, latest_message, sensor_data=sql_result)
        state.intermediate_results["anomaly_result"] = result
        return state

    async def _export_node(self, state: ConversationState) -> ConversationState:
        """Phase 4.3 — Data export node."""
        logger.info("Executing Phase 4 Export Node")
        fmt = state.intermediate_results.get("export_format") or "csv"
        latest_message = state.messages[-1].content if state.messages else "export"

        # If SPARQL hasn't run yet (export intent bypasses sparql node), run it now
        if not state.intermediate_results.get("sparql_result"):
            logger.info("Export: running SPARQL agent to get sensor UUIDs")
            sparql_result = await self.sparql_agent.generate_query(state, latest_message)
            state.intermediate_results["sparql_result"] = sparql_result
            state.query_results = sparql_result.get("results", {})

        # If SQL hasn't run yet, run the SQL agent to get time-series data
        if not state.intermediate_results.get("sql_result"):
            logger.info("Export: running SQL agent to fetch sensor data")
            # Enable UUID-based fetching for export
            state.analytics_required = True
            state = await self._sql_node(state)

        sql_result = state.intermediate_results.get("sql_result") or {}
        # Extract raw rows list from sql_result (result.results.data)
        rows = sql_result.get("results", {}).get("data", []) or \
               sql_result.get("data") or sql_result.get("rows") or []
        if not rows and isinstance(sql_result, list):
            rows = sql_result

        result = await self.export_agent.export(
            data=rows, label="sensor_export", fmt=fmt,
            title=latest_message[:80]
        )
        state.intermediate_results["export_result"] = result
        return state

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

            # B.2: Check response cache before running the full pipeline
            if self.response_cache:
                user_query = state.messages[-1].content if state.messages else ""
                cached = await self.response_cache.get(
                    question=user_query,
                    building_id=state.building_id,
                    user_id=state.user_id,
                )
                if cached:
                    logger.info(f"Response cache HIT — skipping pipeline (type={cached.get('cache_type')})")
                    state.messages.append(Message(
                        role="assistant",
                        content=cached["response"],
                        metadata={"cache_hit": True, "cache_type": cached.get("cache_type")}
                    ))
                    state.current_intent = cached.get("intent", "general")
                    state.intermediate_results["cache_hit"] = True
                    return state

            # Run the graph with timeout
            timeout_s = getattr(settings, "WORKFLOW_TIMEOUT_S", 120)
            try:
                final_state = await asyncio.wait_for(
                    self.graph.ainvoke(state),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.error(f"Workflow timed out after {timeout_s}s for {state.conversation_id}")
                state.messages.append(Message(
                    role="assistant",
                    content="Your request took too long to process. Please try a simpler question or try again later."
                ))
                return state

            # LangGraph may return a dict-like state; rehydrate if needed
            if not isinstance(final_state, ConversationState):
                try:
                    final_state = ConversationState(**dict(final_state))
                except Exception as conv_err:
                    logger.error(f"State rehydration failed: {conv_err}")
                    final_state = state

            logger.info(f"Workflow completed for conversation {state.conversation_id}")
            return final_state

        except asyncio.TimeoutError:
            raise  # Already handled above, but safety net

        except Exception as e:
            logger.error(f"Workflow execution error: {e}", exc_info=True)

            # Map known error types to user-friendly messages
            error_msg = self._user_friendly_error(e)
            state.messages.append(Message(
                role="assistant",
                content=error_msg
            ))

            return state

    @staticmethod
    def _user_friendly_error(e: Exception) -> str:
        """Map exceptions to user-friendly messages."""
        error_str = str(e).lower()
        error_type = type(e).__name__

        if "rate limit" in error_str or "429" in error_str:
            return "I'm receiving too many requests right now. Please wait a moment and try again."
        if "timeout" in error_type.lower() or "timeout" in error_str:
            return "Your request took too long to process. Please try a simpler query."
        if "connection" in error_str or "connect" in error_type.lower():
            return "I'm having trouble reaching one of the backend services. Please try again in a moment."
        if "authentication" in error_str or "401" in error_str:
            return "There was an authentication issue. Please log in again."

        return "I wasn't able to process your request. Could you try rephrasing your question?"

    _FOLLOW_UP_MAP = {
        "analytics": "Plot this data? | Check compliance against ASHRAE? | Compare with another zone?",
        "compliance": "Generate a full compliance report? | Export results as PDF? | Show trend over time?",
        "trend": "Detect anomalies in this trend? | Compare with another sensor? | Export as CSV?",
        "anomaly": "Show the full anomaly report? | Check compliance? | View historical trend?",
        "metadata": "Show current readings for these sensors? | Compare zones? | Generate a report?",
        "compare": "Plot the comparison? | Export results? | Check for anomalies?",
        "report": "Export this report as PDF? | Compare with last month? | View raw data?",
        "discovery": "Show live data for these sensors? | Generate a summary report?",
    }

    @classmethod
    def _get_follow_up_suggestions(cls, intent: str) -> str:
        """Return contextual follow-up suggestions based on the current intent."""
        return cls._FOLLOW_UP_MAP.get(intent, "")

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
            output_dir = Path(settings.QUERY_RESULTS_DIR)
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
