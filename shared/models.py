"""
Shared Pydantic models for OntoSage 2.0
Used across all microservices for type safety
"""
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# ==================== Message Models ====================

class Message(BaseModel):
    """Single message in a conversation"""
    role: Literal["user", "assistant", "system"] = Field(..., description="Message sender role")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message timestamp")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")

class ConversationHistory(BaseModel):
    """Conversation history container"""
    messages: List[Message] = Field(default_factory=list, description="List of messages")
    conversation_id: str = Field(..., description="Unique conversation ID")
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a message to history"""
        self.messages.append(Message(role=role, content=content, metadata=metadata))
    
    def get_recent_messages(self, n: int = 10) -> List[Message]:
        """Get the last n messages"""
        return self.messages[-n:]

# ==================== RAG Models ====================

class RetrievalRequest(BaseModel):
    """Request to retrieve similar vectors from Qdrant"""
    query: str = Field(..., description="Query text to search for")
    # Extended to support new ontology collections actually in use
    collection: Literal[
        "ontology",  # legacy name
        "brick_schema",  # TBox collection
        "building_instances",  # ABox collection
        "queries",
        "analytics",
        "docs"
    ] = Field(..., description="Collection to search in")
    top_k: int = Field(default=5, description="Number of results to return")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Metadata filters")

class RetrievalResult(BaseModel):
    """Single retrieval result"""
    text: str = Field(..., description="Retrieved text content")
    score: float = Field(..., description="Similarity score")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Associated metadata")

class RetrievalResponse(BaseModel):
    """Response from RAG retrieval"""
    results: List[RetrievalResult] = Field(default_factory=list, description="Retrieved results")
    query: str = Field(..., description="Original query")
    collection: str = Field(..., description="Collection searched")

class EmbeddingRequest(BaseModel):
    """Request to embed and store text"""
    texts: List[str] = Field(..., description="Texts to embed")
    collection: str = Field(..., description="Collection to store in")
    metadata: Optional[List[Dict[str, Any]]] = Field(default=None, description="Metadata for each text")

# ==================== Code Execution Models ====================

class CodeExecutionRequest(BaseModel):
    """Request to execute Python code in sandbox"""
    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(default=30, description="Execution timeout in seconds")
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Context variables to inject (e.g., df, sensor_data)"
    )

class CodeExecutionResult(BaseModel):
    """Result from code execution"""
    success: bool = Field(..., description="Whether execution succeeded")
    stdout: str = Field(default="", description="Standard output")
    stderr: str = Field(default="", description="Standard error")
    result: Optional[Any] = Field(default=None, description="Execution result value")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    execution_time: float = Field(..., description="Execution time in seconds")

# ==================== STT Models ====================

class TranscriptionRequest(BaseModel):
    """Request to transcribe audio"""
    audio_file: str = Field(..., description="Base64 encoded audio file or file path")
    language: Optional[str] = Field(default="en", description="Audio language code")

class TranscriptionResponse(BaseModel):
    """Transcription result"""
    text: str = Field(..., description="Transcribed text")
    language: str = Field(..., description="Detected language")
    confidence: Optional[float] = Field(default=None, description="Confidence score")

# ==================== SPARQL Models ====================

class SPARQLQuery(BaseModel):
    """SPARQL query and metadata"""
    query: str = Field(..., description="SPARQL query string")
    explanation: Optional[str] = Field(default=None, description="Human-readable explanation")
    generated_by: str = Field(default="sparql_agent", description="Agent that generated query")

class SPARQLResult(BaseModel):
    """SPARQL query execution result"""
    success: bool = Field(..., description="Whether query executed successfully")
    data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Query results")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    query: str = Field(..., description="Executed query")

# ==================== SQL Models ====================

class SQLQuery(BaseModel):
    """SQL query and metadata"""
    query: str = Field(..., description="SQL query string")
    database: Literal["mysql", "timescale", "cassandra"] = Field(..., description="Target database")
    explanation: Optional[str] = Field(default=None, description="Human-readable explanation")

class SQLResult(BaseModel):
    """SQL query execution result"""
    success: bool = Field(..., description="Whether query executed successfully")
    data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Query results")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    query: str = Field(..., description="Executed query")
    row_count: int = Field(default=0, description="Number of rows returned")

# ==================== Analytics Models ====================

class AnalyticsRequest(BaseModel):
    """Request to generate and execute analytics code"""
    user_query: str = Field(..., description="Natural language analytics request")
    data_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Data context (e.g., dataframes, sensor readings)"
    )

class AnalyticsResult(BaseModel):
    """Analytics execution result"""
    success: bool = Field(..., description="Whether analytics succeeded")
    code_generated: str = Field(..., description="Generated Python code")
    execution_result: Optional[CodeExecutionResult] = Field(
        default=None,
        description="Execution result"
    )
    visualization_path: Optional[str] = Field(
        default=None,
        description="Path to generated visualization"
    )
    insights: Optional[str] = Field(default=None, description="LLM-generated insights")

# ==================== Conversation State (LangGraph) ====================

class ConversationState(BaseModel):
    """
    Complete state for LangGraph workflow
    Passed between all agents
    """
    # User context
    conversation_id: str = Field(..., description="Unique conversation ID")
    user_id: str = Field(default="anonymous", description="User identifier")
    title: Optional[str] = Field(default="New Conversation", description="Conversation title")
    summary: Optional[str] = Field(default=None, description="Conversation summary")
    building_id: str = Field(default="bldg1", description="Building context")
    persona: Literal["stakeholder", "guest", "officer", "facility_manager"] = Field(
        default="guest",
        description="User persona for response customization"
    )
    
    # Current interaction
    user_message: str = Field(..., description="Current user input")
    messages: List[Message] = Field(default_factory=list, description="Conversation history")
    # Legacy / workflow compatibility fields
    current_intent: Optional[str] = Field(default=None, description="Detected intent (legacy name)")
    intent: Optional[str] = Field(default=None, description="Detected user intent (preferred field)")
    intermediate_results: Dict[str, Any] = Field(default_factory=dict, description="Temporary results between agents")
    query_results: Any = Field(default_factory=dict, description="Last query results (SPARQL/SQL)")
    user_preferences: Dict[str, Any] = Field(default_factory=dict, description="User preferences/persona/language")
    
    # Intent understanding
    intent: Optional[str] = Field(default=None, description="Detected user intent")
    needs_clarification: bool = Field(default=False, description="Whether to ask for clarification")
    clarification_question: Optional[str] = Field(default=None, description="Question to ask user")
    
    # RAG retrieval results
    ontology_context: List[RetrievalResult] = Field(
        default_factory=list,
        description="Retrieved ontology snippets"
    )
    query_examples: List[RetrievalResult] = Field(
        default_factory=list,
        description="Retrieved past query examples"
    )
    code_examples: List[RetrievalResult] = Field(
        default_factory=list,
        description="Retrieved code examples"
    )
    
    # Generated queries
    sparql_query: Optional[SPARQLQuery] = Field(default=None, description="Generated SPARQL query")
    sql_query: Optional[SQLQuery] = Field(default=None, description="Generated SQL query")
    
    # Query results
    sparql_results: Optional[SPARQLResult] = Field(default=None, description="SPARQL execution results")
    sql_results: Optional[SQLResult] = Field(default=None, description="SQL execution results")
    
    # Analytics
    analytics_request: Optional[AnalyticsRequest] = Field(
        default=None,
        description="Analytics request"
    )
    analytics_required: bool = Field(
        default=False,
        description="Whether analytics/data processing is required (set by SPARQL/SQL agents)"
    )
    analytics_result: Optional[AnalyticsResult] = Field(
        default=None,
        description="Analytics execution result"
    )
    
    # Error handling
    errors: List[str] = Field(default_factory=list, description="Errors encountered")
    retry_count: int = Field(default=0, description="Number of retry attempts")
    
    # Final response
    assistant_message: Optional[str] = Field(default=None, description="Final assistant response")
    
    # Routing flags
    next_step: Optional[str] = Field(default=None, description="Next agent to invoke")
    is_complete: bool = Field(default=False, description="Whether conversation turn is complete")
    
    class Config:
        arbitrary_types_allowed = True

# ==================== API Response Models ====================

class ChatRequest(BaseModel):
    """Request to /chat endpoint"""
    message: str = Field(..., description="User message")
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID (optional)")
    user_id: str = Field(default="anonymous", description="User ID")
    persona: Literal["stakeholder", "guest", "officer", "facility_manager"] = Field(
        default="guest",
        description="User persona"
    )
    audio_data: Optional[str] = Field(default=None, description="Base64 encoded audio (optional)")

class ChatResponse(BaseModel):
    """Response from /chat endpoint"""
    conversation_id: str = Field(..., description="Conversation ID")
    message: str = Field(..., description="Assistant response")
    sparql_query: Optional[str] = Field(default=None, description="Generated SPARQL query")
    sql_query: Optional[str] = Field(default=None, description="Generated SQL query")
    visualization_url: Optional[str] = Field(default=None, description="URL to visualization")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")

class HealthResponse(BaseModel):
    """Health check response"""
    status: Literal["healthy", "unhealthy"] = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    version: str = Field(default="2.0.0", description="Service version")
    model_provider: Optional[str] = Field(default=None, description="Current model provider")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Health check timestamp")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional health details")

class APIResponse(BaseModel):
    """Standard API Response Wrapper"""
    success: bool = Field(..., description="Request success status")
    data: Optional[Any] = Field(default=None, description="Response payload")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    meta: Optional[Dict[str, Any]] = Field(default=None, description="Metadata (pagination, timing, etc)")

