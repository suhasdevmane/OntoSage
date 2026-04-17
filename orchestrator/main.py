"""
OntoSage 2.0 Orchestrator - Main FastAPI Application
"""

import sys

sys.path.append("/app")

import collections
import json
import os
import time
import uuid as _uuid_mod
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from orchestrator.auth_manager import AuthManager
from orchestrator.middleware.rbac import (
    RBACMiddleware,
    get_auth_manager,
    get_user_store,
)
from orchestrator.postgres_manager import PostgresManager
from orchestrator.redis_manager import RedisManager
from orchestrator.services.adapters.registry import adapter_registry
from orchestrator.services.agent_memory import AgentMemoryService
from orchestrator.services.hybrid_retrieval import hybrid_retrieval
from orchestrator.services.multi_building_manager import get_building_manager
from orchestrator.services.ontology_detector import OntologySchemaDetector
from orchestrator.services.ontology_introspector import ontology_introspector
from orchestrator.services.ontology_validator import ontology_validator
from orchestrator.services.plugin_registry import PluginRegistry, get_plugin_registry
from orchestrator.services.response_cache import ResponseCacheService
from orchestrator.services.sparql_validator import sparql_validator
from orchestrator.workflow import WorkflowOrchestrator
from shared.config import settings
from shared.models import APIResponse, ChatRequest, ConversationState, Message
from shared.utils import generate_conversation_id, get_logger

# All valid personas (must match shared/models.py ConversationState.persona Literal)
VALID_PERSONAS = {
    "student",
    "researcher",
    "facility_manager",
    "occupant",
    "energy_manager",
    "safety_officer",
    "it_admin",
    "executive",
    "sustainability_officer",
    "general",
    # Legacy aliases
    "stakeholder",
    "guest",
    "officer",
}

# ---------------------------------------------------------------------------
# Persona auto-detection for OpenWebUI and other generic OpenAI clients
# ---------------------------------------------------------------------------
import re as _re

# Ordered list of (keywords, canonical_persona).  More specific first.
_PERSONA_KEYWORD_MAP = [
    (
        [
            "facility_manager",
            "facility manager",
            "building manager",
            "building operator",
            "building technician",
        ],
        "facility_manager",
    ),
    (
        [
            "sustainability_officer",
            "sustainability officer",
            "sustainability manager",
            "esg manager",
            "esg officer",
        ],
        "sustainability_officer",
    ),
    (
        ["safety_officer", "safety officer", "hse officer", "health and safety", "h&s officer"],
        "safety_officer",
    ),
    (["energy_manager", "energy manager", "energy analyst", "energy engineer"], "energy_manager"),
    (
        [
            "it_admin",
            "it admin",
            "sysadmin",
            "system administrator",
            "it administrator",
            "it manager",
        ],
        "it_admin",
    ),
    (["researcher", "analyst", "data scientist", "ontologist", "data analyst"], "researcher"),
    (
        [
            "executive",
            "c-level",
            "cfo",
            "ceo",
            "coo",
            "vp ",
            "vice president",
            "director",
            "board member",
        ],
        "executive",
    ),
    (["occupant", "tenant", "office worker", "building occupant", "end user"], "occupant"),
    (["student", "learner", "intern", "trainee"], "student"),
]

# Regex that matches an "As <role>:" prefix the user types in the chat box
_AS_ROLE_RE = _re.compile(
    r"^[Aa]s\s+(?:an?\s+)?"
    r"(facility[_ ]manager|sustainability[_ ]officer|safety[_ ]officer|"
    r"energy[_ ]manager|it[_ ]admin|researcher|analyst|executive|"
    r"occupant|student|facility\s+manager|sustainability\s+officer|"
    r"safety\s+officer|energy\s+manager|it\s+admin|guest|general)"
    r"\s*[:;,\-]\s*",
    _re.IGNORECASE,
)

_ROLE_NORMALIZE = {
    "facility_manager": "facility_manager",
    "facility manager": "facility_manager",
    "sustainability_officer": "sustainability_officer",
    "sustainability officer": "sustainability_officer",
    "safety_officer": "safety_officer",
    "safety officer": "safety_officer",
    "energy_manager": "energy_manager",
    "energy manager": "energy_manager",
    "it_admin": "it_admin",
    "it admin": "it_admin",
    "researcher": "researcher",
    "analyst": "researcher",
    "executive": "executive",
    "occupant": "occupant",
    "student": "student",
    "guest": "occupant",
    "general": "general",
}


def _detect_persona(messages: list, explicit_persona: str) -> tuple:
    """
    Auto-detect the user persona when not explicitly set in the request body.

    Priority order:
      1. Explicit persona already set (non-general) — trust it, return as-is.
      2. OpenWebUI system prompt — scan for role/occupation keywords.
      3. Last user message prefix "As facility_manager: ..." — extract and strip.
      4. Fall back to "general".

    Returns:
        (persona: str, stripped_message: str | None)
        stripped_message is non-None only when a "As role:" prefix was removed
        from the user message, so the caller can replace user_message with it.
    """
    # 1. Explicit non-general persona — pass straight through
    if explicit_persona and explicit_persona != "general" and explicit_persona in VALID_PERSONAS:
        return explicit_persona, None

    # 2. System prompt scan (OpenWebUI system prompt is a {"role":"system"} message)
    system_content = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    if system_content:
        sys_lower = system_content.lower()
        for keywords, persona in _PERSONA_KEYWORD_MAP:
            if any(kw in sys_lower for kw in keywords):
                return persona, None

    # 3. "As <role>:" prefix in the last user message
    raw_user = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
    )
    if raw_user:
        m = _AS_ROLE_RE.match(raw_user.strip())
        if m:
            raw_role = m.group(1).lower().strip()
            persona = _ROLE_NORMALIZE.get(raw_role, "general")
            stripped = raw_user[m.end() :].strip()
            return persona, stripped if stripped else None

    return "general", None


# E.9 — Prometheus metrics (optional; graceful degradation if unavailable)
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _PROM_REQUESTS = Counter(
        "ontosage_http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )
    _PROM_LATENCY = Histogram(
        "ontosage_request_duration_seconds",
        "HTTP request duration in seconds",
        ["endpoint"],
    )
    _PROM_CHAT_TOTAL = Counter(
        "ontosage_chat_messages_total",
        "Total chat messages processed",
        ["intent"],
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

logger = get_logger(__name__)

# Initialize components
redis_manager: RedisManager = None
postgres_manager: PostgresManager = None
orchestrator: WorkflowOrchestrator = None
auth_manager: AuthManager = None
response_cache: ResponseCacheService = None
ontology_detector: OntologySchemaDetector = None
agent_memory: AgentMemoryService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown"""
    global redis_manager, postgres_manager, orchestrator, auth_manager, response_cache, ontology_detector, agent_memory

    # Startup
    logger.info("Starting OntoSage 2.0 Orchestrator...")

    # Initialize Redis
    redis_manager = RedisManager()
    await redis_manager.connect()
    logger.info("Redis connected")

    # Initialize Postgres
    postgres_manager = PostgresManager()
    await postgres_manager.connect()
    logger.info("Postgres connected")

    # Initialize authentication manager
    auth_manager = AuthManager(redis_manager, postgres_manager)
    logger.info("Auth manager initialized")

    # Initialize workflow with redis_manager reference
    orchestrator = WorkflowOrchestrator(
        redis_manager=redis_manager, postgres_manager=postgres_manager
    )
    logger.info("Workflow orchestrator initialized")

    # Phase 1: Validate ontology and introspect building schema at startup
    try:
        logger.info(f"Building: {settings.BUILDING_NAME} ({settings.BUILDING_ID})")
        logger.info(f"Namespace: {settings.BUILDING_NAMESPACE}")
        logger.info(f"Timezone: {settings.BUILDING_TIMEZONE}")
        val_result = await ontology_validator.validate()
        if val_result.ok:
            await ontology_introspector.initialize()

            # C.3: Auto-generate sensor_map.json if file is missing or stale
            try:
                import json as _json
                import os as _os

                _sensor_map_path = settings.SENSOR_MAP_PATH
                _needs_regen = not _os.path.exists(_sensor_map_path)
                if not _needs_regen and ontology_introspector.entity_types:
                    # Regen if cached entity count differs significantly from discovered
                    try:
                        with open(_sensor_map_path) as _f:
                            _cached = _json.load(_f)
                        _needs_regen = len(_cached) == 0
                    except Exception:
                        _needs_regen = True
                if _needs_regen and ontology_introspector.sensor_classes:
                    _sensor_map = {
                        cls.split("#")[-1].split("/")[-1]: {
                            "uri": cls,
                            "label": cls.split("#")[-1].split("/")[-1],
                            "uuid": "",
                            "storage": "",
                        }
                        for cls in ontology_introspector.sensor_classes
                    }
                    _os.makedirs(_os.path.dirname(_sensor_map_path) or ".", exist_ok=True)
                    with open(_sensor_map_path, "w") as _f:
                        _json.dump(_sensor_map, _f, indent=2)
                    logger.info(
                        f"C.3: Auto-generated {_sensor_map_path} with {len(_sensor_map)} sensor class entries"
                    )
                    # Reload into running orchestrator
                    if orchestrator:
                        orchestrator.sensor_map = _sensor_map
            except Exception as _e:
                logger.warning(f"Sensor map auto-generation failed (non-fatal): {_e}")

            # B.4: Auto-detect ontology schema from live GraphDB after validation
            try:
                ontology_detector = OntologySchemaDetector()
                graphdb_url = f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
                detect_result = await ontology_detector.detect_from_graphdb(
                    graphdb_url, settings.GRAPHDB_REPOSITORY
                )
                if detect_result.detected:
                    logger.info(
                        f"Ontology schemas detected: {detect_result.schemas} "
                        f"(confidence={detect_result.confidence:.0%})"
                    )
                    # Store on app state for downstream use
                    app.state.detected_ontology = detect_result
                else:
                    logger.warning(f"Ontology auto-detection inconclusive: {detect_result.notes}")
            except Exception as e:
                logger.warning(f"Ontology detector failed (non-fatal): {e}")
        else:
            logger.warning(
                f"Ontology validation failed: {val_result.errors}. Introspector skipped."
            )
    except Exception as e:
        logger.warning(f"Ontology startup check failed (non-fatal): {e}")

    # Phase 2: Initialize database adapter registry (storage-aware routing)
    try:
        await adapter_registry.initialize()
    except Exception as e:
        logger.warning(f"AdapterRegistry initialization failed (non-fatal): {e}")

    # B.2: Initialize response cache backed by async Redis client
    try:
        response_cache = ResponseCacheService(redis_client=redis_manager.client)
        logger.info("Response cache initialized")
        # Expose on orchestrator so workflow can use it
        if orchestrator:
            orchestrator.response_cache = response_cache
    except Exception as e:
        logger.warning(f"Response cache initialization failed (non-fatal): {e}")

    # B.3: Initialize agent memory service (per-user episodic memory in Qdrant)
    try:
        agent_memory = AgentMemoryService(qdrant_url=settings.QDRANT_URL)
        await agent_memory.initialise()
        if orchestrator:
            orchestrator.agent_memory = agent_memory
        logger.info("Agent memory service initialized")
    except Exception as e:
        logger.warning(f"Agent memory initialization failed (non-fatal): {e}")

    # B.6: Initialize multi-building manager — discovers and loads all building configs
    try:
        building_manager = get_building_manager(
            config_dir=settings.BUILDING_CONFIG_FILE.rsplit("/", 1)[0] or "config"
        )
        logger.info(building_manager.summary())
        app.state.building_manager = building_manager
    except Exception as e:
        logger.warning(f"Multi-building manager initialization failed (non-fatal): {e}")

    # P1: Initialize plugin registry — discovers plugins from plugins/ dir, env var, and entry_points
    try:
        plugin_registry = get_plugin_registry()
        app.state.plugin_registry = plugin_registry
        logger.info(plugin_registry.summary())
    except Exception as e:
        logger.warning(f"Plugin registry initialization failed (non-fatal): {e}")

    # Phase 3.1: Initialize SmartCacheManager for event-driven cache invalidation
    try:
        from orchestrator.services.smart_cache import SmartCacheManager

        smart_cache = SmartCacheManager(redis_client=redis_manager.client)
        app.state.smart_cache = smart_cache
        orchestrator.smart_cache = smart_cache
        logger.info("SmartCacheManager initialized and wired into orchestrator")
    except Exception as e:
        logger.warning(f"SmartCacheManager initialization failed (non-fatal): {e}")

    yield

    # Shutdown
    logger.info("Shutting down OntoSage 2.0 Orchestrator...")
    await redis_manager.close()
    await postgres_manager.close()
    await adapter_registry.close_all()
    # Phase 3.4: Invalidate SPARQL cache on shutdown (optional — Redis flush)
    # await sparql_validator.invalidate()


# Create FastAPI app
app = FastAPI(
    title="OntoSage 2.0 Orchestrator",
    description="Agentic AI orchestration for intelligent building queries",
    version="2.0.0",
    lifespan=lifespan,
)

# Ensure outputs directory exists
os.makedirs("/app/outputs", exist_ok=True)

# Mount static files for serving plots and data
app.mount("/static", StaticFiles(directory="/app/outputs"), name="static")

# E.1: CORS — use CORS_ORIGINS env var; '*' for dev, explicit origins for production
_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(f"CORS origins: {_cors_origins}")

# E.2: Request tracing — attach a trace_id to every request + contextvars for log propagation
from orchestrator.services.logging_context import get_trace_id, set_trace_id


class TracingMiddleware(BaseHTTPMiddleware):
    """Generates a unique trace_id per request; propagates via contextvars so all logs include it."""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or _uuid_mod.uuid4().hex[:12]
        set_trace_id(trace_id)
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response


app.add_middleware(TracingMiddleware)

# E.3: Per-IP rate limiting — simple token-bucket in memory
_RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "60"))  # per window
_RATE_LIMIT_WINDOW_S = int(os.environ.get("RATE_LIMIT_WINDOW_S", "60"))  # seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-process per-IP rate limiter (token bucket, not distributed)."""

    def __init__(
        self, app, requests: int = _RATE_LIMIT_REQUESTS, window: int = _RATE_LIMIT_WINDOW_S
    ):
        super().__init__(app)
        self._requests = requests
        self._window = window
        self._counts: dict = {}  # ip → deque of timestamps

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - self._window
        bucket = self._counts.setdefault(client_ip, collections.deque())
        # Remove old timestamps outside current window
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= self._requests:
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests. Please wait before retrying."},
                headers={"Retry-After": str(self._window)},
            )
        bucket.append(now)
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)

# B.1: RBAC middleware — enabled when RBAC_ENABLED=true in env
if settings.RBAC_ENABLED:
    app.add_middleware(RBACMiddleware, secret_key=settings.SECRET_KEY)
    logger.info("RBAC middleware activated")


@app.get("/", response_model=APIResponse)
async def root():
    """Root endpoint"""
    return APIResponse(
        success=True,
        data={"service": "OntoSage 2.0 Orchestrator", "version": "2.0.0", "status": "running"},
    )


@app.get("/health", response_model=APIResponse)
async def health_check():
    """
    Comprehensive health check — probes ALL dependencies and returns per-service status.
    Overall: healthy (all OK), degraded (some down), unhealthy (critical down).
    """
    import httpx

    checks: Dict[str, Any] = {}
    start = time.time()

    # 1. Redis
    try:
        if hasattr(redis_manager, "redis") and redis_manager.redis:
            pong = await redis_manager.redis.ping()
            checks["redis"] = {"status": "ok" if pong else "no-pong"}
        else:
            await redis_manager.connect()
            checks["redis"] = {"status": "connected"}
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)}

    # 2. PostgreSQL (user data)
    try:
        if postgres_manager and postgres_manager.pool:
            async with postgres_manager.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["postgresql"] = {"status": "ok"}
        else:
            checks["postgresql"] = {"status": "not_configured"}
    except Exception as e:
        checks["postgresql"] = {"status": "error", "error": str(e)}

    # 3. MySQL (sensor data via adapter registry)
    try:
        if adapter_registry.is_available:
            adapter = adapter_registry.get()
            if adapter:
                qr = await adapter.execute_query("SELECT 1 AS ping")
                checks["mysql"] = {
                    "status": "ok" if qr.success else "error",
                    "backends": [t.value for t in adapter_registry._adapters],
                }
            else:
                checks["mysql"] = {"status": "no_adapter"}
        else:
            checks["mysql"] = {"status": "unavailable"}
    except Exception as e:
        checks["mysql"] = {"status": "error", "error": str(e)}

    # 4. GraphDB
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}/rest/repositories"
            )
            checks["graphdb"] = {
                "status": "ok" if r.status_code == 200 else "error",
                "http_status": r.status_code,
            }
    except Exception as e:
        checks["graphdb"] = {"status": "unreachable", "error": str(e)}

    # 5. RAG Service
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"http://{settings.RAG_SERVICE_HOST}:{settings.RAG_SERVICE_PORT}/health"
            )
            checks["rag_service"] = {"status": "ok" if r.status_code == 200 else "error"}
    except Exception as e:
        checks["rag_service"] = {"status": "unreachable", "error": str(e)}

    # 6. Code Executor
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"http://{settings.CODE_EXECUTOR_HOST}:{settings.CODE_EXECUTOR_PORT}/health"
            )
            checks["code_executor"] = {"status": "ok" if r.status_code == 200 else "error"}
    except Exception as e:
        checks["code_executor"] = {"status": "unreachable", "error": str(e)}

    # 7. Qdrant (agent memory vector store)
    try:
        qdrant_url = os.environ.get("QDRANT_URL", "http://qdrant:6333")
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{qdrant_url}/healthz")
            checks["qdrant"] = {"status": "ok" if r.status_code == 200 else "error"}
    except Exception as e:
        checks["qdrant"] = {"status": "unreachable", "error": str(e)}

    # 8. Circuit breakers
    try:
        from orchestrator.services.circuit_breaker import all_breaker_statuses

        checks["circuit_breakers"] = all_breaker_statuses()
    except Exception:
        checks["circuit_breakers"] = []

    # Overall status
    critical = ["redis", "mysql", "graphdb"]
    critical_ok = all(checks.get(k, {}).get("status") in ("ok", "connected") for k in critical)
    any_error = any(
        checks.get(k, {}).get("status") in ("error", "unreachable", "unavailable")
        for k in checks
        if k != "circuit_breakers"
    )

    if critical_ok and not any_error:
        overall = "healthy"
    elif critical_ok:
        overall = "degraded"
    else:
        overall = "unhealthy"

    duration_ms = round((time.time() - start) * 1000, 1)

    return APIResponse(
        success=overall != "unhealthy",
        data={
            "status": overall,
            "duration_ms": duration_ms,
            "services": checks,
            "building": settings.BUILDING_NAME,
            "ontology_valid": ontology_validator.last_result.ok,
            "introspector_ready": ontology_introspector.is_ready(),
        },
    )


@app.get("/conversations/{user_id}", response_model=APIResponse)
async def get_conversations(user_id: str):
    """Get list of conversations for a user"""
    try:
        conversations = []

        # Try Postgres first
        if postgres_manager and postgres_manager.pool:
            conversations = await postgres_manager.get_user_conversations(user_id)

        # Fallback to Redis if empty or not available
        if not conversations and redis_manager:
            conversations = await redis_manager.get_user_conversations(user_id)

        return APIResponse(success=True, data={"conversations": conversations})
    except Exception as e:
        logger.error(f"Failed to get conversations: {e}")
        return APIResponse(success=False, error=str(e))


@app.get("/conversations/{conversation_id}/messages", response_model=APIResponse)
async def get_conversation_messages(conversation_id: str):
    """Get messages for a specific conversation"""
    try:
        messages = []

        # Try Postgres first
        if postgres_manager and postgres_manager.pool:
            messages = await postgres_manager.get_conversation_messages(conversation_id)

        # Fallback to Redis if empty or not available
        if not messages and redis_manager:
            messages = await redis_manager.get_messages(conversation_id)

        return APIResponse(success=True, data={"messages": messages})
    except Exception as e:
        logger.error(f"Failed to get messages for {conversation_id}: {e}")
        return APIResponse(success=False, error=str(e))


# Authentication helper
async def get_current_user(
    session_token: Optional[str] = Cookie(None, alias="session_token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Optional[str]:
    """
    Get current user from session token (cookie or header)

    Returns username or None
    """
    # Try cookie first
    if session_token:
        username = await auth_manager.validate_session(session_token)
        if username:
            return username

    # Try Authorization header
    if authorization:
        # Handle both "Bearer token" and raw token formats
        if isinstance(authorization, str) and authorization.startswith("Bearer "):
            token = authorization.replace("Bearer ", "").strip()
        elif isinstance(authorization, str):
            token = authorization.strip()
        else:
            token = str(authorization).strip()

        if token:
            username = await auth_manager.validate_session(token)
            if username:
                return username

    return None


# ==================== Authentication Endpoints ====================


@app.post("/api/v1/auth/login", response_model=APIResponse)
async def rbac_login(request: Dict[str, Any]):
    """
    B.1 — RBAC JWT login endpoint.
    Issues a short-lived JWT token for role-based API access.

    Request: {"username": "...", "password": "..."}
    Response: {"token": "<jwt>", "role": "...", "permissions": [...]}
    """
    username = request.get("username", "").strip()
    password = request.get("password", "")
    if not username or not password:
        return APIResponse(success=False, error="username and password required")

    token_mgr = get_auth_manager(settings.SECRET_KEY)
    user_store = get_user_store()
    user = user_store.authenticate(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = token_mgr.issue_token(user)
    return APIResponse(
        success=True,
        data={
            "token": token,
            "role": user.role,
            "permissions": sorted(user.all_permissions),
            "user_id": user.user_id,
        },
    )


@app.post("/auth/register", response_model=APIResponse)
async def register_user(request: Dict[str, Any]):
    """
    Register a new user

    Request:
        {
            "username": "user123",
            "password": "password",
            "email": "user@example.com" (optional)
        }
    """
    try:
        username = request.get("username")
        password = request.get("password")
        email = request.get("email")

        if not username or not password:
            return APIResponse(success=False, error="Username and password required")

        result = await auth_manager.register_user(username, password, email)

        if not result["success"]:
            return APIResponse(success=False, error=result["error"])

        return APIResponse(success=True, data=result)

    except Exception as e:
        logger.error(f"Registration endpoint error: {e}", exc_info=True)
        return APIResponse(success=False, error="Registration failed")


@app.post("/auth/login", response_model=APIResponse)
async def login_user(request: Dict[str, Any]):
    """
    Login user and create session

    Request:
        {
            "username": "user123",
            "password": "password"
        }

    Returns:
        {
            "success": true,
            "data": {
                "username": "user123",
                "session_token": "...",
                "expires_in": 604800
            }
        }
    """
    try:
        username = request.get("username")
        password = request.get("password")

        if not username or not password:
            return APIResponse(success=False, error="Username and password required")

        result = await auth_manager.login_user(username, password)

        if not result["success"]:
            return APIResponse(success=False, error=result["error"])

        # Set session cookie
        response_data = APIResponse(success=True, data=result).dict()
        response = JSONResponse(content=response_data)
        response.set_cookie(
            key="session_token",
            value=result["session_token"],
            max_age=result["expires_in"],
            httponly=True,
            samesite="lax",
        )

        return response

    except Exception as e:
        logger.error(f"Login endpoint error: {e}", exc_info=True)
        return APIResponse(success=False, error="Login failed")


@app.post("/auth/logout", response_model=APIResponse)
async def logout_user(
    current_user: Optional[str] = Depends(get_current_user),
    session_token: str = Cookie(None, alias="session_token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Logout user and invalidate session"""
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")

        # Get the actual token from cookie or header
        token = session_token
        if not token and authorization:
            if isinstance(authorization, str) and authorization.startswith("Bearer "):
                token = authorization.replace("Bearer ", "").strip()
            elif isinstance(authorization, str):
                token = authorization.strip()

        if not token:
            return APIResponse(success=False, error="No active session")

        result = await auth_manager.logout_user(token)

        response_data = APIResponse(success=True, data=result).dict()
        response = JSONResponse(content=response_data)
        response.delete_cookie("session_token")

        return response

    except Exception as e:
        logger.error(f"Logout endpoint error: {e}")
        return APIResponse(success=False, error="Logout failed")


@app.get("/auth/me", response_model=APIResponse)
async def get_current_user_info(current_user: Optional[str] = Depends(get_current_user)):
    """Get current authenticated user info"""
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")

        user_info = await auth_manager.get_user_info(current_user)

        if not user_info:
            return APIResponse(success=False, error="User not found")

        return APIResponse(success=True, data=user_info)

    except Exception as e:
        logger.error(f"Get user info error: {e}")
        return APIResponse(success=False, error="Failed to get user info")


# ==================== Chat History Endpoints ====================


@app.get("/history/{username}", response_model=APIResponse)
async def get_user_history(username: str, current_user: Optional[str] = Depends(get_current_user)):
    """
    Get chat history for a specific user

    Returns user's conversation history
    """
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")

        # Users can only access their own history
        if current_user != username:
            return APIResponse(success=False, error="Access denied")

        conversations = []

        # Try Postgres first
        if postgres_manager and postgres_manager.pool:
            pg_convs = await postgres_manager.get_user_conversations(username)
            for conv in pg_convs:
                conv_id = conv["id"]
                messages = await postgres_manager.get_conversation_messages(conv_id)

                if messages:
                    conversations.append(
                        {
                            "conversation_id": conv_id,
                            "messages": messages,
                            "message_count": len(messages),
                            "last_message": messages[-1] if messages else None,
                            "created_at": (
                                conv["created_at"].isoformat() if conv["created_at"] else None
                            ),
                        }
                    )

        # Fallback to Redis if Postgres is empty or not available (and we want to support migration/hybrid)
        # For now, let's just use Postgres if available, otherwise Redis
        if not conversations and redis_manager:
            # Get all conversation IDs for this user
            pattern = f"conversation:*:{username}"
            keys = await redis_manager.client.keys(pattern)

            for key in keys:
                # Redis keys are already strings in newer versions
                key_str = key if isinstance(key, str) else key.decode("utf-8")
                # Extract conversation_id by removing only the "conversation:" prefix
                conv_id = key_str.replace("conversation:", "", 1)

                # Get messages
                messages = await redis_manager.get_messages(conv_id)

                if messages:
                    conversations.append(
                        {
                            "conversation_id": conv_id,
                            "messages": messages,
                            "message_count": len(messages),
                            "last_message": messages[-1] if messages else None,
                        }
                    )

        return APIResponse(
            success=True,
            data={
                "username": username,
                "conversations": conversations,
                "total_conversations": len(conversations),
            },
        )

    except Exception as e:
        logger.error(f"Get history error: {e}", exc_info=True)
        return APIResponse(success=False, error="Failed to get history")


@app.post("/history/{username}", response_model=APIResponse)
async def save_user_history(
    username: str, request: Dict[str, Any], current_user: Optional[str] = Depends(get_current_user)
):
    """
    Save chat history for a user

    Request:
        {
            "messages": [...]
        }
    """
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")

        if current_user != username:
            return APIResponse(success=False, error="Access denied")

        messages = request.get("messages", [])

        # Generate conversation ID
        conv_id = generate_conversation_id()

        # Save to Postgres if available
        if postgres_manager and postgres_manager.pool:
            # Create conversation first
            await postgres_manager.create_conversation(conv_id, username, title="Imported Chat")

            for msg in messages:
                await postgres_manager.save_message(
                    conv_id,
                    msg.get("sender", "user"),  # Map 'sender' to 'role'
                    msg.get("text", ""),
                    username,
                )

        # Also save to Redis for session continuity if needed, or just as fallback
        if redis_manager:
            for msg in messages:
                await redis_manager.save_message(
                    conv_id, msg.get("sender", "user"), msg.get("text", "")
                )

        return APIResponse(
            success=True, data={"conversation_id": conv_id, "message_count": len(messages)}
        )

    except Exception as e:
        logger.error(f"Save history error: {e}")
        return APIResponse(success=False, error="Failed to save history")


@app.delete("/history/{username}", response_model=APIResponse)
async def clear_user_history(
    username: str, current_user: Optional[str] = Depends(get_current_user)
):
    """Clear all chat history for a user"""
    try:
        if not current_user:
            return APIResponse(success=False, error="Not authenticated")

        if current_user != username:
            return APIResponse(success=False, error="Access denied")

        deleted_count = 0

        # Clear from Postgres
        if postgres_manager and postgres_manager.pool:
            await postgres_manager.clear_user_history(username)
            # We don't get a count back easily, but assume success

        # Clear from Redis
        if redis_manager:
            # Delete all conversations for this user
            pattern = f"conversation:*:{username}"
            keys = await redis_manager.client.keys(pattern)

            for key in keys:
                await redis_manager.client.delete(key)
                deleted_count += 1

            # Delete messages
            msg_pattern = f"messages:*:{username}"
            msg_keys = await redis_manager.client.keys(msg_pattern)

            for key in msg_keys:
                await redis_manager.client.delete(key)

        return APIResponse(
            success=True,
            data={
                "deleted_conversations": deleted_count,  # This might be just Redis count
                "message": "History cleared successfully",
            },
        )

    except Exception as e:
        logger.error(f"Clear history error: {e}")
        return APIResponse(success=False, error="Failed to clear history")


@app.get("/health/aggregate", response_model=APIResponse)
async def aggregate_health():
    """Aggregated health including Redis and Ollama readiness (via sidecar or direct)."""
    status: Dict[str, Any] = {
        "service": "orchestrator",
        "version": "2.0.0",
    }
    # Redis status
    try:
        # redis_manager.connect() populates internal client; some implementations keep .redis attribute, else provide method
        # Fallback: attempt a lightweight state fetch to validate connectivity
        if hasattr(redis_manager, "redis") and redis_manager.redis:
            pong = await redis_manager.redis.ping()
            status["redis"] = "ok" if pong else "no-pong"
        else:
            await redis_manager.connect()
            # After reconnect attempt ping again if attribute now exists
            if hasattr(redis_manager, "redis") and redis_manager.redis:
                pong = await redis_manager.redis.ping()
                status["redis"] = "ok" if pong else "no-pong"
            else:
                status["redis"] = "connected"  # minimal confirmation
    except Exception as re:
        status["redis"] = f"error: {re}"

    import httpx

    ollama_base = settings.OLLAMA_BASE_URL
    sidecar_candidates = ["http://ollama-health:8005", "http://localhost:8005"]
    ollama_info = {"reachable": False}
    async with httpx.AsyncClient(timeout=5) as client:
        for c in sidecar_candidates:
            try:
                r = await client.get(f"{c}/status")
                if r.status_code == 200:
                    d = r.json()
                    ollama_info.update(
                        {
                            "reachable": True,
                            "models": d.get("available_models", []),
                            "configured_model": d.get("configured_model"),
                            "generate_ready": d.get("generate_ready", False),
                            "source": "sidecar",
                        }
                    )
                    break
            except Exception:
                continue
        if not ollama_info["reachable"]:
            try:
                tags = await client.get(f"{ollama_base}/api/tags")
                if tags.status_code == 200:
                    tjson = tags.json()
                    names = [m.get("name") for m in tjson.get("models", [])]
                    ollama_info.update(
                        {
                            "reachable": True,
                            "models": names,
                            "configured_model": settings.OLLAMA_MODEL,
                            "generate_ready": settings.OLLAMA_MODEL in names,
                            "source": "direct",
                        }
                    )
            except Exception as oe:
                ollama_info["error"] = str(oe)

    status["ollama"] = ollama_info
    # Normalize Redis health: treat 'ok', 'no-pong', or 'connected' as acceptable
    redis_healthy = status.get("redis") in ["ok", "no-pong", "connected"]
    status["status"] = "healthy" if redis_healthy and ollama_info.get("reachable") else "degraded"
    return APIResponse(success=True, data=status)


@app.post("/chat", response_model=APIResponse)
async def chat(request: ChatRequest, current_user: Optional[str] = Depends(get_current_user)):
    """
    Synchronous chat endpoint (requires authentication)

    Request body validated via ChatRequest Pydantic model.
    Max message length: 10 000 chars. Null bytes / control chars stripped.
    """
    try:
        # Validate authentication
        if not current_user:
            return APIResponse(success=False, error="Authentication required")

        username = current_user

        # Sanitize all input fields
        req = request.sanitized()
        user_message = req.message

        # Use session_id if provided, otherwise conversation_id, otherwise generate new one
        session_id = req.session_id
        conversation_id = req.conversation_id

        if session_id:
            conversation_id = f"conv_{session_id}:{username}"
            logger.info(f"Using session_id for conversation: {conversation_id}")
        elif not conversation_id:
            conversation_id = f"{generate_conversation_id()}:{username}"
            logger.info(f"Generated new conversation_id: {conversation_id}")
        else:
            logger.info(f"Using provided conversation_id: {conversation_id}")

        persona = req.persona or "general"
        language = req.language or "en"
        building = req.building or settings.BUILDING_ID

        # Load or create conversation state
        state = await redis_manager.load_state(conversation_id)

        if not state:
            # New conversation
            state = ConversationState(
                conversation_id=conversation_id,
                user_message=user_message,  # Add current message
                messages=[],
                building_id=building,
                persona=persona if persona in VALID_PERSONAS else "general",
            )
            # Store user association
            state.user_id = username
        else:
            # Update existing conversation with new message
            state.user_message = user_message

        # Add user message
        from datetime import datetime

        state.messages.append(Message(role="user", content=user_message, timestamp=datetime.now()))

        # Save message
        await redis_manager.save_message(conversation_id, "user", user_message)

        # Save to Postgres if available
        if postgres_manager and postgres_manager.pool:
            await postgres_manager.save_message(conversation_id, "user", user_message, username)

        # Execute workflow
        logger.info("=" * 100)
        logger.info("🚀 FRONTEND REQUEST - Starting Workflow Execution")
        logger.info("=" * 100)
        logger.info(f"📝 Conversation ID: {conversation_id}")
        logger.info(f"👤 User: {username}")
        logger.info(f"💬 Message: {user_message}")
        logger.info(f"🏢 Building: {state.building_id}")
        logger.info(f"🎭 Persona: {state.persona}")
        logger.info("=" * 100)

        updated_state = await orchestrator.execute(state)

        # Log intermediate results
        logger.info("\n" + "=" * 100)
        logger.info("📊 WORKFLOW RESULTS SUMMARY")
        logger.info("=" * 100)
        logger.info(f"🎯 Intent: {updated_state.current_intent}")

        if updated_state.intermediate_results:
            logger.info("\n📋 Intermediate Results:")

            # SPARQL Results
            sparql_result = updated_state.intermediate_results.get("sparql_result", {})
            if sparql_result:
                logger.info("\n1️⃣ SPARQL Agent Results:")
                sparql_output = sparql_result.get("output", {})
                if isinstance(sparql_output, dict):
                    results = sparql_output.get("results", {}).get("bindings", [])
                    logger.info(f"   📊 Found {len(results)} results")
                    if results:
                        logger.info(f"   🔍 Sample result: {results[0]}")

            # SQL Results
            sql_result = updated_state.intermediate_results.get("sql_result", {})
            if sql_result:
                logger.info("\n2️⃣ SQL Agent Results:")
                sql_output = sql_result.get("output", {})
                if isinstance(sql_output, dict):
                    data = sql_output.get("data", [])
                    logger.info(f"   📊 Found {len(data)} data rows")
                    if data:
                        logger.info(f"   🔍 Sample row: {data[0]}")

            # Analytics Results
            analytics_result = updated_state.intermediate_results.get("analytics_result", {})
            if analytics_result:
                logger.info("\n3️⃣ Analytics Agent Results:")
                analytics_output = analytics_result.get("output")
                if analytics_output:
                    logger.info(f"   📈 Output: {str(analytics_output)[:200]}...")
                analytics_code = analytics_result.get("code")
                if analytics_code:
                    logger.info(f"   💻 Code executed: {len(analytics_code)} chars")

        logger.info("=" * 100 + "\n")

        # Save updated state
        await redis_manager.save_state(updated_state)

        # Get assistant response
        assistant_entry = updated_state.messages[-1] if updated_state.messages else None
        assistant_message = assistant_entry.content if assistant_entry else "No response generated"
        assistant_metadata = assistant_entry.metadata if assistant_entry else None
        logger.info(f"✅ Assistant Response: {assistant_message[:200]}...")

        # Save assistant message
        await redis_manager.save_message(
            conversation_id, "assistant", assistant_message, metadata=assistant_metadata
        )

        # Save to Postgres if available
        if postgres_manager and postgres_manager.pool:
            await postgres_manager.save_message(
                conversation_id, "assistant", assistant_message, username
            )

        # Get analytics flag from state (set by SPARQL/SQL agents)
        analytics_flag = getattr(updated_state, "analytics_required", False)

        return APIResponse(
            success=True,
            data={
                "conversation_id": conversation_id,
                "response": assistant_message,
                "intent": updated_state.current_intent,
                "username": username,
                "analytics": analytics_flag,
                "media": assistant_metadata.get("media") if assistant_metadata else None,
            },
        )

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return APIResponse(success=False, error=str(e))


@app.post("/chat/stream")
async def chat_stream(
    request: ChatRequest, current_user: Optional[str] = Depends(get_current_user)
):
    """
    Streaming chat endpoint (Server-Sent Events).
    Request body validated via ChatRequest Pydantic model.
    """
    try:
        username = current_user or "guest"

        req = request.sanitized()
        user_message = req.message

        conversation_id = req.conversation_id
        if not conversation_id:
            conversation_id = f"{generate_conversation_id()}:{username}"

        persona = req.persona or "general"
        if persona not in VALID_PERSONAS:
            persona = "general"

        language = req.language or "en"
        building = req.building or settings.BUILDING_ID

        async def event_generator():
            try:
                # Send conversation ID first
                yield f"data: {json.dumps({'type': 'conversation_id', 'id': conversation_id})}\n\n"

                # Load or create state
                state = await redis_manager.load_state(conversation_id)
                if not state:
                    state = ConversationState(
                        conversation_id=conversation_id,
                        user_message=user_message,
                        messages=[],
                        building_id=building,
                        persona=persona,
                        user_id=username,
                    )
                else:
                    state.user_message = user_message

                # Add user message
                from datetime import datetime

                state.messages.append(
                    Message(role="user", content=user_message, timestamp=datetime.now())
                )
                await redis_manager.save_message(conversation_id, "user", user_message)

                # Save to Postgres if available
                if postgres_manager and postgres_manager.pool:
                    await postgres_manager.save_message(
                        conversation_id, "user", user_message, username
                    )

                # Add to user's conversation list if new
                await redis_manager.add_conversation_to_user(
                    username, conversation_id, user_message[:30] + "..."
                )

                # Execute workflow (Synchronous for now to ensure full context)
                # We simulate streaming by sending the full response
                updated_state = await orchestrator.execute(state)

                assistant_entry = updated_state.messages[-1] if updated_state.messages else None
                full_response = (
                    assistant_entry.content if assistant_entry else "No response generated"
                )
                assistant_metadata = assistant_entry.metadata if assistant_entry else None

                # Save assistant message
                await redis_manager.save_message(
                    conversation_id, "assistant", full_response, metadata=assistant_metadata
                )

                # Save to Postgres if available
                if postgres_manager and postgres_manager.pool:
                    await postgres_manager.save_message(
                        conversation_id, "assistant", full_response, username
                    )

                # Save updated state
                await redis_manager.save_state(updated_state)

                # Stream the response (simulate chunks or send all at once)
                # Frontend expects {"type": "token", "content": "..."}
                yield f"data: {json.dumps({'type': 'token', 'content': full_response})}\n\n"
                if assistant_metadata and assistant_metadata.get("media"):
                    yield f"data: {json.dumps({'type': 'metadata', 'media': assistant_metadata['media']})}\n\n"
                yield f"data: [DONE]\n\n"

            except Exception as e:
                logger.error(f"Stream error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Chat stream setup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for streaming responses

    Client sends:
        {
            "message": "user message",
            "conversation_id": "optional-id",
            "persona": "student|researcher|facility_manager|general"
        }

    Server streams:
        {"type": "intent", "data": "sparql"}
        {"type": "progress", "data": "Querying ontology..."}
        {"type": "result", "data": {...}}
        {"type": "response", "data": "Final response"}
        {"type": "done"}
    """
    await websocket.accept()

    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            request = json.loads(data)

            user_message = request.get("message")
            if not user_message:
                await websocket.send_json({"type": "error", "data": "Message is required"})
                continue

            conversation_id = request.get("conversation_id") or generate_conversation_id()
            persona = request.get("persona", "general")
            language = request.get("language", "en")
            building = request.get("building", settings.BUILDING_ID)

            # Load or create state
            state = await redis_manager.load_state(conversation_id)

            if not state:
                state = ConversationState(
                    conversation_id=conversation_id,
                    messages=[],
                    current_intent="unknown",
                    query_results={},
                    intermediate_results={},
                    user_preferences={
                        "persona": persona,
                        "language": language,
                        "building": building,
                    },
                )

            # Add user message
            state.messages.append(Message(role="user", content=user_message, timestamp=None))

            await redis_manager.save_message(conversation_id, "user", user_message)

            # Stream workflow execution — capture last step as final state
            last_step = None
            async for step in orchestrator.stream_execute(state):
                last_step = step
                # Send progress updates
                if "dialogue" in step:
                    await websocket.send_json({"type": "progress", "data": "Analyzing intent..."})
                elif "sparql" in step:
                    await websocket.send_json(
                        {"type": "progress", "data": "Querying building ontology..."}
                    )
                elif "sql" in step:
                    await websocket.send_json(
                        {"type": "progress", "data": "Fetching sensor data..."}
                    )
                elif "analytics" in step:
                    await websocket.send_json(
                        {"type": "progress", "data": "Performing analysis..."}
                    )
                elif "visualization" in step:
                    await websocket.send_json(
                        {"type": "progress", "data": "Creating visualization..."}
                    )

            # Extract final state from last streamed step (avoid re-executing entire pipeline)
            final_state = state
            if last_step and isinstance(last_step, dict):
                # LangGraph astream yields {node_name: state_dict}
                for node_name, node_state in last_step.items():
                    if isinstance(node_state, ConversationState):
                        final_state = node_state
                    elif isinstance(node_state, dict) and "messages" in node_state:
                        final_state = ConversationState(**node_state)

            # Save state
            await redis_manager.save_state(final_state)

            # Get response
            assistant_message = (
                final_state.messages[-1].content if final_state.messages else "No response"
            )

            await redis_manager.save_message(conversation_id, "assistant", assistant_message)

            # Send final response
            await websocket.send_json(
                {
                    "type": "response",
                    "data": assistant_message,
                    "conversation_id": conversation_id,
                    "intent": final_state.current_intent,
                }
            )

            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except:
            pass


@app.get("/conversation/{conversation_id}", response_model=APIResponse)
async def get_conversation(conversation_id: str):
    """Get conversation history"""
    try:
        messages = await redis_manager.get_messages(conversation_id)

        return APIResponse(
            success=True,
            data={"conversation_id": conversation_id, "messages": messages, "count": len(messages)},
        )

    except Exception as e:
        logger.error(f"Get conversation error: {e}")
        return APIResponse(success=False, error=str(e))


@app.delete("/conversation/{conversation_id}", response_model=APIResponse)
async def delete_conversation(conversation_id: str):
    """Delete conversation"""
    try:
        # Delete state and messages
        await redis_manager.redis.delete(f"conversation:{conversation_id}")
        await redis_manager.redis.delete(f"messages:{conversation_id}")

        return APIResponse(
            success=True, data={"message": f"Conversation {conversation_id} deleted"}
        )

    except Exception as e:
        logger.error(f"Delete conversation error: {e}")
        return APIResponse(success=False, error=str(e))


@app.post("/preferences", response_model=APIResponse)
async def update_preferences(request: Dict[str, Any]):
    """Update user preferences"""
    try:
        conversation_id = request.get("conversation_id")
        if not conversation_id:
            return APIResponse(success=False, error="conversation_id required")

        preferences = {
            "persona": request.get("persona"),
            "language": request.get("language"),
            "building": request.get("building"),
        }

        # Remove None values
        preferences = {k: v for k, v in preferences.items() if v is not None}

        await redis_manager.save_user_preferences(conversation_id, preferences)

        return APIResponse(success=True, data={"preferences": preferences})

    except Exception as e:
        logger.error(f"Update preferences error: {e}")
        return APIResponse(success=False, error=str(e))


# ==================== Report Generation ====================


@app.post("/api/v1/report")
async def generate_report(
    request: Dict[str, Any], current_user: Optional[str] = Depends(get_current_user)
):
    """
    Generate a building report as PDF, DOCX, or HTML.

    Request body:
        {
            "report_type": "summary|anomaly|compliance|trend|comparison|full",
            "output_format": "html|pdf|docx",
            "persona": "executive|facility_manager|general|...",
            "building_id": settings.BUILDING_ID,
            "title": "Optional custom title",
            "date_range": {"start": "2025-01-01", "end": "2025-01-31"}
        }
    """
    try:
        username = current_user or "guest"
        report_type = request.get("report_type", "summary")
        output_format = request.get("output_format", "html")
        persona = request.get("persona", "general")
        building_id = request.get("building_id", settings.BUILDING_ID)
        title = request.get("title")
        date_range = request.get("date_range", {})

        from orchestrator.services.document_builder import DocumentBuilder

        builder = DocumentBuilder()

        # Collect data for the report via a lightweight chat pipeline
        report_data = {
            "narrative": f"Auto-generated {report_type} report for {building_id}.",
            "building_id": building_id,
            "date_range": date_range,
            "generated_by": username,
        }

        # If we have SQL adapter available, fetch latest readings
        if adapter_registry.is_available:
            try:
                adapter = adapter_registry.get()
                if adapter:
                    recent_sql = "SELECT * FROM sensor_data ORDER BY Datetime DESC LIMIT 50"
                    qr = await adapter.execute_query(recent_sql)
                    if qr.success and qr.data:
                        report_data["readings"] = qr.data[:20]
                        report_data["readings_summary"] = {
                            "row_count": qr.row_count,
                            "sample": qr.data[:5],
                        }
            except Exception as _db_err:
                logger.warning(f"Report: could not fetch latest readings: {_db_err}")

        result = builder.render(
            report_data=report_data,
            report_type=report_type,
            persona=persona,
            output_format=output_format,
            title=title,
        )

        if not result.get("success"):
            return APIResponse(success=False, error=result.get("error", "Report generation failed"))

        # For binary formats, save to exports and return download path
        if output_format in ("pdf", "docx"):
            export_path = builder.save_to_exports(result)
            return APIResponse(
                success=True,
                data={
                    "filename": result.get("filename"),
                    "format": output_format,
                    "size_bytes": result.get("size_bytes"),
                    "export_path": export_path,
                },
            )

        # HTML: return inline
        return APIResponse(
            success=True,
            data={
                "filename": result.get("filename"),
                "format": "html",
                "content": result.get("content"),
                "size_bytes": result.get("size_bytes"),
            },
        )

    except Exception as e:
        logger.error(f"Report generation error: {e}", exc_info=True)
        return APIResponse(success=False, error=str(e))


# ==================== OpenAI Compatibility Layer ====================


@app.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request, authorization: Optional[str] = Header(None, alias="Authorization")
):
    """
    OpenAI-compatible endpoint for Open WebUI integration.
    Allows Open WebUI to use the OntoSage pipeline as a backend.
    """
    try:
        # Basic auth check (accept any token for now)
        # username = "openwebui_user" # Moved below to support 'user' field

        data = await request.json()
        messages = data.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")

        # Determine username from request or default
        # Open WebUI and other clients may send a 'user' field
        username = data.get("user") or "openwebui_user"

        # Extract last user message
        last_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if not last_user_msg:
            raise HTTPException(status_code=400, detail="No user message found")

        from shared.models import CHAT_MAX_MESSAGE_LENGTH, sanitize_user_input

        user_message = sanitize_user_input(last_user_msg["content"])
        if len(user_message) > CHAT_MAX_MESSAGE_LENGTH:
            raise HTTPException(
                status_code=400, detail=f"Message too long (max {CHAT_MAX_MESSAGE_LENGTH} chars)"
            )
        if not user_message:
            raise HTTPException(status_code=400, detail="Message is empty after sanitization")

        # Generate conversation ID
        conversation_id = f"owui_{generate_conversation_id()}:{username}"

        # Auto-detect persona from system prompt or "As <role>:" prefix when
        # the client (e.g. OpenWebUI) does not send an explicit persona field.
        explicit_persona = data.get("persona", "general")
        if explicit_persona not in VALID_PERSONAS:
            explicit_persona = "general"
        req_persona, stripped_message = _detect_persona(messages, explicit_persona)

        # If an "As <role>:" prefix was stripped, use the cleaned message
        if stripped_message:
            from shared.models import sanitize_user_input as _san

            user_message = _san(stripped_message)
            if not user_message:
                raise HTTPException(
                    status_code=400, detail="Message is empty after stripping persona prefix"
                )

        # Reconstruct prior conversation history from the OpenAI-format
        # messages array so the dialogue agent can resolve co-references
        # ("the same sensor", "that zone", "yesterday") and follow-up
        # questions without asking for clarification.
        # We take all turns EXCEPT the last (current) user message, cap at
        # MAX_CONVERSATION_HISTORY to avoid context overflow, and skip
        # system/tool messages that are not meaningful for entity resolution.
        max_history = int(getattr(settings, "MAX_CONVERSATION_HISTORY", 10))
        prior_messages: List[Message] = []
        for m in messages[:-1]:  # exclude the current (last) user turn
            role = m.get("role", "user")
            content = m.get("content") or ""
            if role in ("user", "assistant") and content.strip():
                prior_messages.append(
                    Message(role=role, content=content, timestamp=datetime.now())
                )
        prior_messages = prior_messages[-max_history:]

        state = ConversationState(
            conversation_id=conversation_id,
            user_message=user_message,
            messages=prior_messages,
            building_id=data.get("building_id", settings.BUILDING_ID),
            persona=req_persona,
            user_id=username,
        )

        logger.info(
            f"[persona-detect] explicit={explicit_persona!r} → resolved={req_persona!r}"
            + (" (prefix stripped)" if stripped_message else "")
        )
        logger.info(
            f"[/v1/chat/completions] loaded {len(prior_messages)} prior turns into state"
        )

        # Add the current message to the history so the agent can see it
        state.messages.append(Message(role="user", content=user_message, timestamp=datetime.now()))

        stream = bool(data.get("stream"))
        show_status = bool(data.get("show_status", True))

        if stream:

            async def event_generator():
                created_ts = int(datetime.now().timestamp())
                chunk_id = f"chatcmpl-{conversation_id}"

                def sse_chunk(content=None, role=None, finish_reason=None):
                    payload = {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created_ts,
                        "model": data.get("model", "ontobot-pipeline"),
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                    }
                    if role:
                        payload["choices"][0]["delta"]["role"] = role
                    if content is not None:
                        payload["choices"][0]["delta"]["content"] = content
                    return f"data: {json.dumps(payload)}\n\n"

                # Initial role chunk
                yield sse_chunk(role="assistant")

                # Collect status steps; emit as a collapsible <details> block so
                # they are visible during processing but do not pollute the final
                # answer.  Open WebUI (and any markdown-capable UI) renders
                # <details> as a collapsed toggle — the answer appears cleanly
                # below it, matching the behaviour of ChatGPT / Claude.
                status_steps = []
                last_step = None
                async for step in orchestrator.stream_execute(state):
                    last_step = step
                    if not show_status:
                        continue
                    status = None
                    if "dialogue" in step:
                        status = "Analyzing intent"
                    elif "sparql" in step:
                        status = "Querying building ontology"
                    elif "sql" in step:
                        status = "Fetching sensor data"
                    elif "analytics" in step:
                        status = "Performing analysis"
                    elif "visualization" in step:
                        status = "Creating visualization"
                    elif "report" in step:
                        status = "Assembling report"
                    elif "document" in step:
                        status = "Generating document output"
                    if status:
                        status_steps.append(status)

                # Emit status steps as a single collapsed block (visible on
                # expand, does not appear inline with the answer)
                if show_status and status_steps:
                    steps_md = "\n".join(f"- {s}" for s in status_steps)
                    yield sse_chunk(
                        content=f"<details>\n<summary>Pipeline steps</summary>\n\n{steps_md}\n\n</details>\n\n"
                    )

                # Extract final state from last streamed step (avoid re-executing)
                final_state = state
                if last_step and isinstance(last_step, dict):
                    for node_name, node_state in last_step.items():
                        if isinstance(node_state, ConversationState):
                            final_state = node_state
                        elif isinstance(node_state, dict) and "messages" in node_state:
                            final_state = ConversationState(**node_state)

                assistant_message = (
                    final_state.messages[-1].content
                    if final_state.messages
                    else "No response generated"
                )

                # Save to Postgres if available
                if postgres_manager and postgres_manager.pool:
                    await postgres_manager.create_user(
                        username,
                        "placeholder_hash",
                        "placeholder_salt",
                        metadata={"source": "open_webui"},
                    )
                    await postgres_manager.save_message(
                        conversation_id, "user", user_message, username
                    )
                    await postgres_manager.save_message(
                        conversation_id, "assistant", assistant_message, username
                    )

                # Stream final response in chunks (helps UI show gradual output)
                chunk_size = 200
                for i in range(0, len(assistant_message), chunk_size):
                    yield sse_chunk(content=assistant_message[i : i + chunk_size])

                # Finalize stream
                yield sse_chunk(finish_reason="stop")
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        # Non-streaming: Execute workflow
        updated_state = await orchestrator.execute(state)

        assistant_message = (
            updated_state.messages[-1].content
            if updated_state.messages
            else "No response generated"
        )

        if postgres_manager and postgres_manager.pool:
            await postgres_manager.create_user(
                username, "placeholder_hash", "placeholder_salt", metadata={"source": "open_webui"}
            )
            await postgres_manager.save_message(conversation_id, "user", user_message, username)
            await postgres_manager.save_message(
                conversation_id, "assistant", assistant_message, username
            )

        return {
            "id": f"chatcmpl-{conversation_id}",
            "object": "chat.completion",
            "created": int(datetime.now().timestamp()),
            "model": data.get("model", "ontobot-pipeline"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": assistant_message},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    except Exception as e:
        logger.error(f"OpenAI endpoint error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/models")
async def openai_models():
    """List available models for Open WebUI"""
    return {
        "object": "list",
        "data": [
            {
                "id": "ontobot-pipeline",
                "object": "model",
                "created": 1677610602,
                "owned_by": "ontosage",
            }
        ],
    }


@app.get("/api/files/{filename}")
async def download_export(filename: str):
    """D.2: Download a previously generated export file (CSV, JSON, HTML, Markdown)."""
    import re as _re

    from fastapi.responses import FileResponse

    # Sanitise: allow alphanum, dash, underscore, dot only
    if not _re.match(r"^[\w\-. ]+$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = os.path.join(settings.EXPORTS_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"Export file '{filename}' not found")
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@app.get("/buildings", response_model=APIResponse)
async def list_buildings():
    """B.6: List all registered buildings and their configurations."""
    try:
        from orchestrator.services.multi_building_manager import get_building_manager

        mgr = get_building_manager()
        return APIResponse(success=True, data={"buildings": mgr.list_buildings()})
    except Exception as e:
        logger.error(f"List buildings failed: {e}")
        return APIResponse(success=False, error=str(e), data={"buildings": []})


# ── E.9: Prometheus metrics endpoint ─────────────────────────────────────────

from fastapi.responses import Response as _FastAPIResponse


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """
    E.9: Expose Prometheus-compatible metrics at GET /metrics.
    Scraped by Prometheus or compatible observability stacks.
    Returns 503 if prometheus_client is not installed.
    """
    if not _PROMETHEUS_AVAILABLE:
        return _FastAPIResponse(
            content="# prometheus_client not installed\n",
            status_code=503,
            media_type="text/plain",
        )
    return _FastAPIResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
