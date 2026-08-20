"""
Shared Pydantic models for OntoSage 2.0
Used across all microservices for type safety
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

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
        "docs",
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
    metadata: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Metadata for each text"
    )


# ==================== Code Execution Models ====================


class CodeExecutionRequest(BaseModel):
    """Request to execute Python code in sandbox"""

    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(default=30, description="Execution timeout in seconds")
    context: Optional[Dict[str, Any]] = Field(
        default=None, description="Context variables to inject (e.g., df, sensor_data)"
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
        default=None, description="Data context (e.g., dataframes, sensor readings)"
    )


class AnalyticsResult(BaseModel):
    """Analytics execution result"""

    success: bool = Field(..., description="Whether analytics succeeded")
    code_generated: str = Field(..., description="Generated Python code")
    execution_result: Optional[CodeExecutionResult] = Field(
        default=None, description="Execution result"
    )
    visualization_path: Optional[str] = Field(
        default=None, description="Path to generated visualization"
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
    building_id: str = Field(
        default_factory=lambda: __import__(
            "shared.config", fromlist=["settings"]
        ).settings.BUILDING_ID,
        description="Building context — defaults to the ACTIVE building, never a literal",
    )
    # Phase 14A — persona is now `str` not `Literal[...]` so YAML-added
    # personas resolve without a code change.  When `personas` (list) is
    # populated, it takes precedence; `persona` is the primary/legacy
    # single-string value and the first element of `personas` is used
    # to back-fill it.
    persona: str = Field(
        default="general",
        description=(
            "Primary user persona (legacy single-string field).  When "
            "`personas` is non-empty, this is set to personas[0] for "
            "backward compat."
        ),
    )
    personas: List[str] = Field(
        default_factory=list,
        description=(
            "Phase 14A — list of stacked personas.  When non-empty, the "
            "PersonaRegistry blends priors across all entries.  Empty "
            "list means single-persona mode (uses the `persona` field)."
        ),
    )

    # Current interaction
    user_message: str = Field(..., description="Current user input")
    messages: List[Message] = Field(default_factory=list, description="Conversation history")
    # current_intent is the authoritative routing field; intent is a read alias
    current_intent: Optional[str] = Field(
        default=None, description="Detected intent (used for routing)"
    )
    intermediate_results: Dict[str, Any] = Field(
        default_factory=dict, description="Temporary results between agents"
    )
    query_results: Any = Field(default_factory=dict, description="Last query results (SPARQL/SQL)")

    # ── Phase 7A — typed view over intermediate_results ───────────────────
    #
    # Use `state.pipeline_ctx.<field>` for IDE autocomplete + mypy safety on
    # any of the 49 known pipeline keys.  Returns a SNAPSHOT (mutations on
    # the returned object are NOT written back unless you call
    # `pipeline_ctx.apply_to_state(self)` afterwards).
    #
    # Existing callers using `state.intermediate_results["key"]` continue to
    # work; this property is additive only.
    @property
    def pipeline_ctx(self) -> Any:
        """Return a typed PipelineContext snapshot of intermediate_results."""
        from shared.pipeline_context import PipelineContext

        return PipelineContext.from_state(self)

    user_preferences: Dict[str, Any] = Field(
        default_factory=dict, description="User preferences/persona/language"
    )

    # Floor plan / spatial context — persisted across turns within a session
    floor_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Active floor/zone context carried across turns. "
            "Keys: floor (int), zone (str|None), pdf_url (str)."
        ),
    )

    # Intent understanding
    needs_clarification: bool = Field(default=False, description="Whether to ask for clarification")
    clarification_question: Optional[str] = Field(default=None, description="Question to ask user")

    # RAG retrieval results
    ontology_context: List[RetrievalResult] = Field(
        default_factory=list, description="Retrieved ontology snippets"
    )
    query_examples: List[RetrievalResult] = Field(
        default_factory=list, description="Retrieved past query examples"
    )
    code_examples: List[RetrievalResult] = Field(
        default_factory=list, description="Retrieved code examples"
    )

    # Generated queries
    sparql_query: Optional[SPARQLQuery] = Field(default=None, description="Generated SPARQL query")
    sql_query: Optional[SQLQuery] = Field(default=None, description="Generated SQL query")

    # Query results
    sparql_results: Optional[SPARQLResult] = Field(
        default=None, description="SPARQL execution results"
    )
    sql_results: Optional[SQLResult] = Field(default=None, description="SQL execution results")

    # Analytics
    analytics_request: Optional[AnalyticsRequest] = Field(
        default=None, description="Analytics request"
    )
    analytics_required: bool = Field(
        default=False,
        description="Whether analytics/data processing is required (set by SPARQL/SQL agents)",
    )
    analytics_result: Optional[AnalyticsResult] = Field(
        default=None, description="Analytics execution result"
    )

    # Error handling
    errors: List[str] = Field(default_factory=list, description="Errors encountered")
    retry_count: int = Field(default=0, description="Number of retry attempts")

    # Final response
    assistant_message: Optional[str] = Field(default=None, description="Final assistant response")

    # Routing flags
    next_step: Optional[str] = Field(default=None, description="Next agent to invoke")
    is_complete: bool = Field(default=False, description="Whether conversation turn is complete")

    # Phase 4 — structured dialogue state (survey H: 26.7% disambiguation rate)
    dialogue_state: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Structured clarification state: turn_phase, pending_clarification, "
            "bound_entities, candidates.  Persisted across turns so the system "
            "can resume on a bound entity without re-asking."
        ),
    )

    class Config:
        arbitrary_types_allowed = True


# ==================== Data Source / Provenance Models ====================
#
# Toggleable synthetic data sources (occupancy, energy, noise, …) and the
# per-answer provenance tags they produce. See
# tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.


class DataSourcePoint(BaseModel):
    """A single sensor/device synthesized for a data source.

    UUID is derived deterministically from (building_id, source_id, local) when
    absent, so re-generation is idempotent and the TTL, MySQL rows, and provenance
    all agree on the same identifier.
    """

    local: str = Field(..., description="Entity local name -> bldg:<local>")
    brick_class: str = Field(..., description="Prefixed Brick class, e.g. brick:Occupancy_Sensor")
    location: str = Field(..., description="Prefixed location entity, e.g. bldg:Room_5.01")
    unit: Optional[str] = Field(default=None, description="Prefixed QUDT unit, e.g. unit:PERCENT")
    label: Optional[str] = Field(default=None, description="Human-readable label")
    uuid: Optional[str] = Field(default=None, description="Timeseries id (auto-derived if unset)")


class DataSourceGenerator(BaseModel):
    """Synthetic-data generator configuration for one data source."""

    kind: str = Field(..., description="Generator plugin key, e.g. occupancy_profile")
    window_days: int = Field(default=30, ge=1, description="Days of history to synthesize")
    interval_minutes: int = Field(default=15, ge=1, description="Sampling interval in minutes")
    params: Dict[str, Any] = Field(default_factory=dict, description="Plugin-specific parameters")
    anomalies: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Optional labeled anomalies (ground truth): [{type, at, magnitude}, ...]",
    )


class DataSourceSpec(BaseModel):
    """One toggleable data source: ontology triples + timeseries table + generator.

    Enabling a source loads its Brick point triples into a dedicated GraphDB named
    graph (the named graph IS the on/off switch) and makes its narrow MySQL table
    (`ref:storedAt bldg:<ts_table>`) reachable, which unlocks the `unlocks`
    capability tags.
    """

    id: str = Field(..., description="Stable key; used in URIs, table names, UUID derivation")
    label: str = Field(..., description="Human-readable name")
    modality: str = Field(..., description="occupancy | energy | noise | iaq | light | ...")
    kind: str = Field(default="timeseries", description="timeseries | text_reports")
    enabled: bool = Field(default=False, description="Manifest default state")
    synthetic: bool = Field(default=True, description="Rendered on the provenance tag")
    provenance_system: str = Field(..., description="Source-system label for provenance tags")
    color: str = Field(default="#888888", description="Provenance chip color (hex)")
    ts_table: Optional[str] = Field(
        default=None, description="Narrow MySQL table == ref:storedAt key (timeseries kind)"
    )
    named_graph: Optional[str] = Field(
        default=None, description="GraphDB named graph URI (defaults to urn:ontosage:ds:<id>)"
    )
    unlocks: List[str] = Field(
        default_factory=list, description="Capability tags this source enables"
    )
    match_keywords: List[str] = Field(
        default_factory=list,
        description=(
            "Lowercase phrases that, when found in a query while this source is "
            "DISABLED, trigger the locked-capability decline. Curated + conservative: "
            "no keywords = never auto-locks (avoids false positives)."
        ),
    )
    points: List[DataSourcePoint] = Field(default_factory=list, description="Devices to synthesize")
    generator: Optional[DataSourceGenerator] = Field(default=None, description="Generator config")

    def graph_uri(self) -> str:
        """Named graph URI for this source (explicit override or derived default)."""
        return self.named_graph or f"urn:ontosage:ds:{self.id}"


class ProvenanceTag(BaseModel):
    """A single provenance annotation on an answer — one per contributing source."""

    source_id: str = Field(..., description="'occupancy' | 'ontology' | 'analytics' | ...")
    label: str = Field(..., description="Display label, e.g. 'Occupancy Sensing System'")
    color: str = Field(default="#888888", description="Chip color (hex)")
    synthetic: bool = Field(default=False, description="True -> rendered as 'simulated'")
    store: str = Field(
        default="", description="Backing store, e.g. 'graphdb' | 'mysql:occupancy_data'"
    )


# ==================== Floor Plan Models ====================


class NormalisedPoint(BaseModel):
    """2-D coordinate normalised to [0, 1] relative to rendered image dimensions."""

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)


class NormalisedBBox(BaseModel):
    """Bounding box normalised to [0, 1]. (x, y) is the top-left corner."""

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., ge=0.0, le=1.0)
    h: float = Field(..., ge=0.0, le=1.0)


SpaceType = Literal[
    "office",
    "lab",
    "meeting_room",
    "classroom",
    "lecture",
    "toilet",
    "kitchen",
    "server_room",
    "storage",
    "staircase",
    "lift",
    "reception",
    "corridor",
    "utility",
    "zone",
    "unknown",
]


BlockType = Literal[
    "door",
    "window",
    "fire_exit",
    "sensor",
    "hvac_diffuser",
    "fire_alarm",
    "light_fixture",
    "power_outlet",
    "equipment",
    "unknown",
]


class Block(BaseModel):
    """A DWG INSERT entity (door, sensor, equipment, etc.) placed on the floor plan."""

    type: BlockType = "unknown"
    block_name: str
    position: NormalisedPoint
    layer: Optional[str] = None
    attributes: Dict[str, str] = Field(default_factory=dict)
    space_id: Optional[str] = None


class Space(BaseModel):
    """
    A single identifiable space (room, zone, corridor, facility) on a floor.

    ``id`` is globally unique: ``"<building_id>.<zone_id>"``.
    All spatial coordinates are normalised [0, 1] relative to the rendered PNG.
    """

    id: str = Field(..., description="Global unique ID: <building_id>.<zone_id>")
    zone_id: str = Field(..., description="Zone/room identifier, e.g. '3.01'")
    label: str = Field(..., description="Human-readable label extracted from the floor plan")
    aliases: List[str] = Field(default_factory=list)
    type: SpaceType = Field(default="unknown")
    tags: List[str] = Field(default_factory=list)
    centroid: Optional[NormalisedPoint] = None
    bbox: Optional[NormalisedBBox] = None
    polygon: Optional[List[NormalisedPoint]] = None
    sensor_uuids: List[str] = Field(default_factory=list)
    ontology_iri: Optional[str] = None
    source: Literal["text_extraction", "llm", "manual", "dwg"] = "text_extraction"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # DW2 — geometry enrichment from DWG source
    area_m2: Optional[float] = None
    perimeter_m: Optional[float] = None
    layer: Optional[str] = None
    adjacent_spaces: List[str] = Field(default_factory=list)


class RenderedImage(BaseModel):
    """Metadata about the PNG render of a floor plan page."""

    png_url: str
    thumbnail_url: str
    width_px: int
    height_px: int
    dpi: int


class FloorPlanManifest(BaseModel):
    """
    Canonical representation of one floor of one building.

    Generated once from the source PDF by FloorPlanPipeline and consumed
    by every downstream component (FloorPlanAgent, API, frontend viewer).
    Schema version is ``"1.0"``; readers must reject unknown versions.
    """

    schema_version: Literal["1.0", "2.0"] = "1.0"
    building_id: str
    building_name: str
    floor: int
    floor_label: str
    source_pdf: str
    source_sha256: str
    generated_at: datetime
    generator_version: str = "1.0.0"
    page_count: int = 1
    rendered_image: RenderedImage
    pdf_url: str
    bounding_box: Dict[str, float] = Field(default_factory=dict)
    spaces: List[Space] = Field(default_factory=list)
    facilities: Dict[str, List[str]] = Field(default_factory=dict)
    ontology_links: Dict[str, str] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    # DW2 — v2.0 fields (populated when DWG source is available)
    source_dwg: Optional[str] = None
    source_dwg_sha256: Optional[str] = None
    dwg_units: str = "m"
    data_sources: List[str] = Field(default_factory=lambda: ["pdf"])
    total_area_m2: Optional[float] = None
    blocks: List[Block] = Field(default_factory=list)
    layers: List[Dict[str, Any]] = Field(default_factory=list)
    adjacency: Dict[str, List[str]] = Field(default_factory=dict)


class FloorPlanResult(BaseModel):
    """
    Structured result returned by FloorPlanAgent.resolve().

    ``markdown`` is always populated for fallback text rendering.
    ``interactive=True`` signals that the frontend should render the viewer.
    """

    building_id: str
    floor: Optional[int] = None
    selected_space: Optional[Space] = None
    candidates: List[Space] = Field(default_factory=list)
    manifest_url: Optional[str] = None
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    pdf_url: Optional[str] = None
    interactive: bool = True
    markdown: str = ""


# ==================== API Response Models ====================


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
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Health check timestamp"
    )
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional health details")


class APIResponse(BaseModel):
    """Standard API Response Wrapper"""

    success: bool = Field(..., description="Request success status")
    data: Optional[Any] = Field(default=None, description="Response payload")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    meta: Optional[Dict[str, Any]] = Field(
        default=None, description="Metadata (pagination, timing, etc)"
    )


# ==================== Request Validation Models ====================

# Maximum allowed message length (chars). Prevents abuse and LLM token overflow.
CHAT_MAX_MESSAGE_LENGTH = 10_000

import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_user_input(text: str) -> str:
    """Strip null bytes and control characters from user-provided text."""
    return _CONTROL_CHARS_RE.sub("", text).strip()


class ChatRequest(BaseModel):
    """Validated chat request body — replaces raw Dict[str, Any] on chat endpoints."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=CHAT_MAX_MESSAGE_LENGTH,
        description="User message (1-10 000 chars)",
    )
    conversation_id: Optional[str] = Field(
        default=None, max_length=200, description="Existing conversation ID"
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Session ID for conversation continuity",
    )
    persona: Optional[str] = Field(
        default="general", description="Persona for response style (legacy single-string)"
    )
    personas: List[str] = Field(
        default_factory=list,
        description=(
            "Phase 14A — list of stacked personas to blend.  Empty list = "
            "single-persona mode (uses `persona`).  Non-empty = registry "
            "blends top_domains, complexity, and clarification thresholds."
        ),
    )
    language: Optional[str] = Field(default="en", max_length=10, description="Response language")
    building: Optional[str] = Field(default=None, max_length=100, description="Target building ID")
    fresh_session: bool = Field(
        default=False,
        description="When True, skip injecting prior cross-session memory context for this request",
    )

    @classmethod
    def _sanitize(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return sanitize_user_input(v)

    def sanitized(self) -> "ChatRequest":
        """Return a copy with all string fields sanitized."""
        return self.model_copy(
            update={
                "message": sanitize_user_input(self.message),
                "conversation_id": self._sanitize(self.conversation_id),
                "session_id": self._sanitize(self.session_id),
                "persona": self._sanitize(self.persona),
                "language": self._sanitize(self.language),
                "building": self._sanitize(self.building),
            }
        )
