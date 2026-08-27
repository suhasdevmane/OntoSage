"""
OntoSage 2.0 Orchestrator - Main FastAPI Application
"""

import sys

sys.path.append("/app")

import asyncio
import collections
import hashlib
import hmac
import ipaddress
import json
import os
import signal
import time
import uuid as _uuid_mod
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from orchestrator.auth_manager import AuthManager
from orchestrator.llm_manager import begin_llm_trace, llm_degradation
from orchestrator.middleware.rbac import ROLE_PERMISSIONS, UserContext
from orchestrator.postgres_manager import PostgresManager
from orchestrator.redis_manager import RedisManager
from orchestrator.services.adapters.registry import adapter_registry
from orchestrator.services.agent_memory import AgentMemoryService
from orchestrator.services.alert_monitor import AlertMonitor
from orchestrator.services.connection_manager import ConnectionManager
from orchestrator.services.floor_plan_service import floor_plan_service
from orchestrator.services.hybrid_retrieval import hybrid_retrieval
from orchestrator.services.job_queue import JobQueue
from orchestrator.services.job_queue import JobStatus as _JobStatus
from orchestrator.services.multi_building_manager import get_building_manager
from orchestrator.services.ontology_detector import OntologySchemaDetector
from orchestrator.services.ontology_introspector import ontology_introspector
from orchestrator.services.ontology_validator import ontology_validator
from orchestrator.services.plugin_registry import PluginRegistry, get_plugin_registry
from orchestrator.services.response_cache import ResponseCacheService
from orchestrator.services.sparql_validator import sparql_validator
from orchestrator.workflow import WorkflowOrchestrator
from shared.config import settings, validate_config
from shared.models import (
    APIResponse,
    ChatRequest,
    ConversationState,
    DataSourceSpec,
    Message,
)
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
        [
            "safety_officer",
            "safety officer",
            "hse officer",
            "health and safety",
            "h&s officer",
        ],
        "safety_officer",
    ),
    (
        ["energy_manager", "energy manager", "energy analyst", "energy engineer"],
        "energy_manager",
    ),
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
    (
        ["researcher", "analyst", "data scientist", "ontologist", "data analyst"],
        "researcher",
    ),
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
    (
        ["occupant", "tenant", "office worker", "building occupant", "end user"],
        "occupant",
    ),
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
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
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
# Tracks which OpenWebUI-proxied usernames have already been registered in Postgres
# so we don't issue an INSERT on every streaming/non-streaming turn.
_pipeline_users_created: Set[str] = set()
orchestrator: WorkflowOrchestrator = None
auth_manager: AuthManager = None
response_cache: ResponseCacheService = None
ontology_detector: OntologySchemaDetector = None
agent_memory: AgentMemoryService = None
job_queue: Optional[JobQueue] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown"""
    global redis_manager, postgres_manager, orchestrator, auth_manager, response_cache, ontology_detector, agent_memory, job_queue

    # Startup
    logger.info("Starting OntoSage 2.0 Orchestrator...")

    # Validate configuration — hard-fail in production (STRICT_SECRETS=true),
    # warn-only in local dev so a missing SECRET_KEY doesn't block the dev server.
    try:
        validate_config()
    except ValueError as _cfg_err:
        if settings.STRICT_SECRETS:
            raise
        logger.warning(
            f"[config] Non-fatal configuration issue (set STRICT_SECRETS=true for hard-fail): {_cfg_err}"
        )

    # Initialize Redis
    redis_manager = RedisManager()
    await redis_manager.connect()
    logger.info("Redis connected")

    # Task 5: Initialize async job queue (backed by Redis)
    job_queue = JobQueue(redis_manager.client)
    logger.info("Job queue initialised")

    # Initialize Postgres.
    # Phase-18 (2026-05-29): retry with exponential backoff to survive the
    # well-known race where the orchestrator container starts before
    # postgres-user-data reports `healthy` (docker-compose `depends_on:
    # service_healthy` is enforced but not 100% reliable on some hosts).
    # When the orchestrator booted before Postgres came up, the previous code
    # logged "Postgres connected" but left `postgres_manager.pool == None`,
    # making `auth_manager.login` fail with confusing "Invalid password" errors.
    postgres_manager = PostgresManager()
    _pg_attempts = 5
    _pg_backoff = 2  # seconds
    for _attempt in range(1, _pg_attempts + 1):
        try:
            await postgres_manager.connect()
            if postgres_manager.pool is not None:
                logger.info(f"Postgres connected (attempt {_attempt}/{_pg_attempts})")
                break
            logger.warning(
                f"Postgres connect attempt {_attempt}/{_pg_attempts} returned "
                f"None pool; retrying in {_pg_backoff}s"
            )
        except Exception as _pg_err:
            logger.warning(
                f"Postgres connect attempt {_attempt}/{_pg_attempts} failed: "
                f"{type(_pg_err).__name__}: {_pg_err}; retrying in {_pg_backoff}s"
            )
        await asyncio.sleep(_pg_backoff)
        _pg_backoff = min(_pg_backoff * 2, 30)  # 2, 4, 8, 16, 30
    else:
        # Connect did not succeed in any attempt — log loudly and proceed.
        # Auth/login will fail closed (Phase-18 guard in auth_manager) until
        # the operator restarts the orchestrator after Postgres recovers.
        logger.error(
            f"Postgres did not become available after {_pg_attempts} attempts; "
            "auth + RBAC features will be DEGRADED until orchestrator restart."
        )

    # Create control_log table if not exists
    try:
        async with postgres_manager.pool.acquire() as _conn:
            await _conn.execute(
                """
                CREATE TABLE IF NOT EXISTS control_log (
                    id           SERIAL PRIMARY KEY,
                    timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    building_id  VARCHAR(64),
                    device       VARCHAR(256),
                    action       VARCHAR(64),
                    target_value VARCHAR(128),
                    status       VARCHAR(32),
                    user_id      VARCHAR(256),
                    role         VARCHAR(64),
                    session_id   VARCHAR(256)
                )
            """
            )
        logger.info("control_log table ready")
    except Exception as _e:
        logger.warning(f"control_log table creation skipped: {_e}")

    # Create maintenance_tickets table if not exists
    try:
        async with postgres_manager.pool.acquire() as _conn:
            await _conn.execute(
                """
                CREATE TABLE IF NOT EXISTS maintenance_tickets (
                    id          VARCHAR(12)  PRIMARY KEY,
                    building_id VARCHAR(64)  NOT NULL,
                    location    VARCHAR(256),
                    device      VARCHAR(256),
                    description TEXT         NOT NULL,
                    status      VARCHAR(32)  DEFAULT 'OPEN',
                    reporter_id VARCHAR(256),
                    assignee    VARCHAR(256),
                    created_at  TIMESTAMPTZ  DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ  DEFAULT NOW(),
                    session_id  VARCHAR(256)
                )
            """
            )
        logger.info("maintenance_tickets table ready")
    except Exception as _e:
        logger.warning(f"maintenance_tickets table creation skipped: {_e}")

    # Phase 19 — Unified user-report intake table.
    # Holds EVERY kind of user-submitted issue: maintenance, complaint,
    # feedback, safety, suggestion.  Admins triage it in pgAdmin
    # (port 5050, postgres-user-data).  Reporter persona is captured so admins
    # can see which kind of user raised each issue.
    try:
        async with postgres_manager.pool.acquire() as _conn:
            await _conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_reports (
                    id           VARCHAR(16)  PRIMARY KEY,
                    building_id  VARCHAR(64)  NOT NULL,
                    category     VARCHAR(32)  NOT NULL DEFAULT 'maintenance',
                    priority     VARCHAR(16)  NOT NULL DEFAULT 'NORMAL',
                    status       VARCHAR(24)  NOT NULL DEFAULT 'OPEN',
                    title        VARCHAR(256),
                    description  TEXT         NOT NULL,
                    location     VARCHAR(256),
                    device       VARCHAR(256),
                    reporter_id  VARCHAR(256),
                    persona      VARCHAR(128),
                    assignee     VARCHAR(256),
                    admin_notes  TEXT,
                    session_id   VARCHAR(256),
                    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                    resolved_at  TIMESTAMPTZ,
                    -- V6-T23: the space this report is ABOUT, resolved once at intake against
                    -- the active building's graph. NULL when no space was named or the named
                    -- one does not exist -- a guessed IRI would put a fabricated location on
                    -- a record that feeds work orders.
                    space_iri    VARCHAR(512),
                    observed_at  TIMESTAMPTZ
                )
            """
            )
            # V6-T23: existing deployments gain the columns in place; IF NOT EXISTS makes
            # every boot after the first a no-op, so no migration runner is needed.
            for _alter in (
                "ALTER TABLE user_reports ADD COLUMN IF NOT EXISTS space_iri VARCHAR(512)",
                "ALTER TABLE user_reports ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ",
                # V6-T24: the EXPLICIT link to a work order. Never inferred — a report and a
                # work order in the same room on the same day are not necessarily the same
                # issue, and merging them on proximity would combine two people's problems.
                "ALTER TABLE user_reports ADD COLUMN IF NOT EXISTS work_order_id VARCHAR(64)",
            ):
                await _conn.execute(_alter)
            for _idx_sql in (
                "CREATE INDEX IF NOT EXISTS idx_user_reports_status ON user_reports (status)",
                "CREATE INDEX IF NOT EXISTS idx_user_reports_space ON user_reports (building_id, space_iri)",
                "CREATE INDEX IF NOT EXISTS idx_user_reports_wo ON user_reports (work_order_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_reports_category ON user_reports (category)",
                "CREATE INDEX IF NOT EXISTS idx_user_reports_priority ON user_reports (priority)",
                "CREATE INDEX IF NOT EXISTS idx_user_reports_building ON user_reports (building_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_reports_reporter ON user_reports (reporter_id)",
            ):
                await _conn.execute(_idx_sql)
        logger.info("user_reports table + indexes ready (Phase 19 intake)")
    except Exception as _e:
        logger.warning(f"user_reports table creation skipped: {_e}")

    # Phase 19 — backward-compat: expose the maintenance subset of user_reports
    # as the legacy `maintenance_tickets` shape, but ONLY when no real
    # maintenance_tickets table already exists (fresh deployments).  Existing
    # deployments keep their real table untouched; new reports go to user_reports.
    try:
        async with postgres_manager.pool.acquire() as _conn:
            _is_table = await _conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'maintenance_tickets' AND table_type = 'BASE TABLE'
                )
                """
            )
            if not _is_table:
                await _conn.execute(
                    """
                    CREATE OR REPLACE VIEW maintenance_tickets AS
                    SELECT id, building_id, location, device, description,
                           status, reporter_id, assignee, created_at, updated_at,
                           session_id
                    FROM user_reports
                    WHERE category = 'maintenance'
                """
                )
                logger.info("maintenance_tickets compat VIEW created over user_reports")
            else:
                logger.info(
                    "maintenance_tickets exists as a real table — leaving it; "
                    "new reports go to user_reports"
                )
    except Exception as _e:
        logger.warning(f"maintenance_tickets compat view skipped: {_e}")

    # Phase 19 - admin triage VIEWS over user_reports, auto-created so admins
    # can open pgAdmin and double-click them with no SQL.  Canonical definitions
    # live in scripts/sql/report_admin_views.sql.
    try:
        async with postgres_manager.pool.acquire() as _conn:
            await _conn.execute(
                """
                CREATE OR REPLACE VIEW v_open_reports AS
                SELECT id, created_at, building_id, category, priority, status,
                       persona, title, location, device, reporter_id, assignee
                FROM user_reports
                WHERE status NOT IN ('RESOLVED', 'CLOSED', 'REJECTED')
                ORDER BY CASE priority WHEN 'URGENT' THEN 0 WHEN 'HIGH' THEN 1
                                       WHEN 'NORMAL' THEN 2 ELSE 3 END,
                         created_at DESC
            """
            )
            await _conn.execute(
                """
                CREATE OR REPLACE VIEW v_urgent_reports AS
                SELECT id, created_at, building_id, category, priority, status,
                       persona, title, location, device, reporter_id
                FROM user_reports
                WHERE priority IN ('URGENT', 'HIGH')
                  AND status IN ('OPEN', 'ACKNOWLEDGED')
                ORDER BY CASE priority WHEN 'URGENT' THEN 0 ELSE 1 END,
                         created_at ASC
            """
            )
            await _conn.execute(
                """
                CREATE OR REPLACE VIEW v_reports_by_persona AS
                SELECT COALESCE(persona, '(unknown)') AS persona, category,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (
                         WHERE status NOT IN ('RESOLVED','CLOSED','REJECTED')
                       ) AS open_count,
                       MAX(created_at) AS latest
                FROM user_reports
                GROUP BY COALESCE(persona, '(unknown)'), category
                ORDER BY total DESC
            """
            )
            await _conn.execute(
                """
                CREATE OR REPLACE VIEW v_reports_by_category AS
                SELECT category, status, priority, COUNT(*) AS total,
                       MAX(created_at) AS latest
                FROM user_reports
                GROUP BY category, status, priority
                ORDER BY category, status
            """
            )
        logger.info("user_reports admin triage views ready (Phase 19)")
    except Exception as _e:
        logger.warning(f"user_reports admin views skipped: {_e}")

    # Initialize authentication manager
    auth_manager = AuthManager(redis_manager, postgres_manager)
    logger.info("Auth manager initialized")

    # Bootstrap admin from .env (safe-create only): create the ADMIN_USERNAME
    # admin-role account if both creds are set and the user doesn't exist yet.
    # Never overwrites an existing account. Enables sign-in to the :3001 console.
    if settings.ADMIN_USERNAME and settings.ADMIN_PASSWORD:
        try:
            existing = await postgres_manager.get_user(settings.ADMIN_USERNAME)
            if existing:
                logger.info(
                    f"[admin_bootstrap] '{settings.ADMIN_USERNAME}' already exists — "
                    "leaving it unchanged"
                )
            else:
                res = await auth_manager.register_user(
                    settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD, role="admin"
                )
                if res.get("success"):
                    logger.info(f"[admin_bootstrap] created admin user '{settings.ADMIN_USERNAME}'")
                else:
                    logger.warning(f"[admin_bootstrap] could not create admin: {res.get('error')}")
        except Exception as _abe:
            logger.warning(f"[admin_bootstrap] skipped (non-fatal): {_abe}")
    else:
        logger.info("[admin_bootstrap] ADMIN_USERNAME/ADMIN_PASSWORD unset — no admin bootstrap")

    # Initialize workflow with redis_manager reference
    orchestrator = WorkflowOrchestrator(
        redis_manager=redis_manager, postgres_manager=postgres_manager
    )
    logger.info("Workflow orchestrator initialized")

    # Start proactive alert monitor
    try:
        alert_monitor = AlertMonitor(
            sql_agent=orchestrator.sql_agent,
            connection_manager=connection_manager,
            redis_client=redis_manager.client,
        )
        asyncio.create_task(alert_monitor.run_forever())
        logger.info("AlertMonitor started")
    except Exception as _e:
        logger.warning(f"AlertMonitor not started: {_e}")

    # Phase 1: Validate ontology and introspect building schema at startup.
    # Wrapped in a callable so Phase 3 (startup TTL ingestion) can re-run it on a
    # cold boot where the graph loads AFTER this first attempt (BUG-100) — a
    # building swap must not require a manual orchestrator restart.
    _phase1_state = {"inited": False}

    async def _ontology_phase1(force_sensor_map: bool = False) -> None:
        """Validate ontology; on success introspect, build sensor map, detect schemas."""
        try:
            logger.info(f"Building: {settings.BUILDING_NAME} ({settings.BUILDING_ID})")
            logger.info(f"Namespace: {settings.BUILDING_NAMESPACE}")
            logger.info(f"Timezone: {settings.BUILDING_TIMEZONE}")
            val_result = await ontology_validator.validate()
            if val_result.ok:
                _phase1_state["inited"] = True
                await ontology_introspector.initialize()

                # C.3: Build the per-building sensor map from the LIVE graph. Regenerate
                # when the cache is missing/empty OR does not match the ACTIVE building
                # (no cached sensor URI belongs to its namespace) — this prevents another
                # building's cached catalogue from leaking in (portability). Building-agnostic:
                # accepts both ref: and ASHRAE-223 external-reference predicates; keyed off
                # the timeseries link (which defines a sensor), so no type-path explosion.
                try:
                    import json as _json
                    import os as _os

                    _sensor_map_path = settings.SENSOR_MAP_PATH
                    _ns = settings.BUILDING_NAMESPACE or ""
                    _needs_regen = force_sensor_map or not _os.path.exists(_sensor_map_path)
                    if not _needs_regen:
                        try:
                            with open(_sensor_map_path) as _f:
                                _cached = _json.load(_f)
                            _match = bool(_ns) and any(
                                isinstance(v, dict) and _ns in v.get("uri", "")
                                for v in _cached.values()
                            )
                            # stale if empty, or the active building isn't represented
                            _needs_regen = (len(_cached) == 0) or (bool(_ns) and not _match)
                        except Exception:
                            _needs_regen = True
                    if _needs_regen:
                        import httpx as _httpx

                        _ep = (
                            f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
                            f"/repositories/{settings.GRAPHDB_REPOSITORY}"
                        )
                        _q = (
                            "PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#> "
                            "PREFIX ashrae:<http://data.ashrae.org/standard223#> "
                            "PREFIX ref:<https://brickschema.org/schema/Brick/ref#> "
                            "SELECT DISTINCT ?sensor ?label ?uuid ?storage WHERE { "
                            "{ ?sensor ref:hasExternalReference ?e } "
                            "UNION { ?sensor ashrae:hasExternalReference ?e } "
                            "?e ref:hasTimeseriesId ?uuid ; ref:storedAt ?storage . "
                            "OPTIONAL { ?sensor rdfs:label ?label } }"
                        )
                        _auth = (
                            (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                            if settings.GRAPHDB_USER
                            else None
                        )
                        async with _httpx.AsyncClient(timeout=90.0) as _c:
                            _resp = await _c.post(
                                _ep,
                                auth=_auth,
                                data={"query": _q},
                                headers={"Accept": "application/sparql-results+json"},
                            )
                            _resp.raise_for_status()
                            _rows = _resp.json()["results"]["bindings"]
                        _sensor_map = {}
                        for _b in _rows:
                            _uri = _b["sensor"]["value"]
                            _ln = _uri.split("#")[-1].split("/")[-1]
                            _uuid = _b["uuid"]["value"]
                            _st = _b["storage"]["value"].split("#")[-1].split("/")[-1]
                            _lab = _b.get("label", {}).get("value", _ln)
                            _entry = {"uri": _uri, "uuid": _uuid, "storage": _st, "label": _lab}
                            _sensor_map[_ln] = _entry
                            _sensor_map[_lab] = _entry
                            _sensor_map[_uri] = _entry
                        if _sensor_map:
                            # reload the RUNNING orchestrator first (fixes it even if the
                            # cache path is read-only); then try to persist for next boot.
                            if orchestrator:
                                orchestrator.sensor_map = _sensor_map
                            try:
                                _os.makedirs(
                                    _os.path.dirname(_sensor_map_path) or ".", exist_ok=True
                                )
                                with open(_sensor_map_path, "w") as _f:
                                    _json.dump(_sensor_map, _f, indent=2)
                            except OSError as _we:
                                logger.warning(
                                    f"Sensor map cache path not writable ({_we}); using in-memory only"
                                )
                            _n = len({v["uri"] for v in _sensor_map.values()})
                            logger.info(
                                f"Sensor map: built {_n} sensors from the live graph for "
                                f"{settings.BUILDING_ID}"
                            )
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
                        logger.warning(
                            f"Ontology auto-detection inconclusive: {detect_result.notes}"
                        )
                except Exception as e:
                    logger.warning(f"Ontology detector failed (non-fatal): {e}")
            else:
                logger.warning(
                    f"Ontology validation failed: {val_result.errors}. Introspector skipped."
                )
        except Exception as e:
            logger.warning(f"Ontology startup check failed (non-fatal): {e}")

    await _ontology_phase1()

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

    # Floor plan registry — runs DWG + PDF pipelines in parallel, merges results (idempotent)
    try:
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry

        _fp_registry = get_floor_plan_registry()
        manifests = await _fp_registry.ingest_all()

        pdf_only = [m for m in manifests if m.data_sources == ["pdf"]]
        dwg_only = [m for m in manifests if m.data_sources == ["dwg"]]
        both = [m for m in manifests if "pdf" in m.data_sources and "dwg" in m.data_sources]
        skipped = sum(
            1 for m in manifests if not any(w for w in m.warnings if "unchanged" not in w.lower())
        )

        logger.info(
            f"Floor plan registry ready — {len(manifests)} floor(s) ingested: "
            f"{len(both)} PDF+DWG merged, {len(pdf_only)} PDF-only, {len(dwg_only)} DWG-only. "
            f"Floors: {sorted(m.floor for m in manifests)}"
        )
        if not manifests:
            logger.info(
                "Floor plan registry: no PDF or DWG files found in /app/input/ — "
                "drop files there and they will be auto-ingested by the file watcher."
            )
    except Exception as e:
        logger.warning(f"Floor plan registry failed (non-fatal): {e}")

    # Legacy Qdrant text-index — run as background task so it doesn't block server startup
    async def _legacy_index():
        try:
            await floor_plan_service.index_all()
        except Exception as e:
            logger.debug(f"Legacy floor plan index skipped: {e}")

    asyncio.create_task(_legacy_index())

    # File watcher — auto-reingest when PDFs are dropped into /app/input/
    try:
        from orchestrator.services.floor_plan_watcher import watch_forever as _fp_watch

        asyncio.create_task(_fp_watch())
        logger.info("Floor plan file watcher started")
    except Exception as e:
        logger.warning(f"Floor plan file watcher failed to start (non-fatal): {e}")

    # T12: Generic feed adapter framework — loads per-building feeds.yaml and polls
    try:
        from orchestrator.services.feeds.registry import FeedRegistry as _FeedRegistry

        _feed_registry = _FeedRegistry(building_id=settings.BUILDING_ID)
        _feed_count = _feed_registry.load()
        if _feed_count > 0:
            asyncio.create_task(_feed_registry.run_forever())
            logger.info(f"[feeds] polling loop started for {_feed_count} feed(s)")
            # T13: register feed points in GraphDB so SPARQL can discover them
            asyncio.create_task(_feed_registry.register_in_graphdb())
        else:
            logger.info("[feeds] no feeds configured — polling loop idle")
        app.state.feed_registry = _feed_registry
    except Exception as e:
        logger.warning(f"[feeds] feed registry failed to start (non-fatal): {e}")

    # Toggleable synthetic data sources + provenance (flag-gated).
    app.state.datasource_manager = None
    if settings.DATASOURCE_TOGGLES_ENABLED:
        try:
            from orchestrator.services.datasource_manager import DataSourceManager
            from orchestrator.services.datasource_registry import DataSourceRegistry

            _ds_registry = DataSourceRegistry(settings.BUILDING_ID)
            _ds_count = _ds_registry.load()
            _ds_manager = DataSourceManager(settings.BUILDING_ID, _ds_registry)
            # Re-assert enabled sources into GraphDB so state survives a repo reset.
            for _sid in _ds_manager.enabled_ids():
                asyncio.create_task(_ds_manager.enable(_sid))
            app.state.datasource_registry = _ds_registry
            app.state.datasource_manager = _ds_manager
            # Give the workflow orchestrator the registry + manager so the
            # response node can resolve provenance tags and the routing gate can
            # decline questions that need a disabled source.
            if orchestrator is not None:
                orchestrator.datasource_registry = _ds_registry
                orchestrator.datasource_manager = _ds_manager
            logger.info(
                f"[datasources] loaded {_ds_count} source(s); "
                f"enabled={_ds_manager.enabled_ids()}"
            )
        except Exception as e:
            logger.warning(f"[datasources] failed to start (non-fatal): {e}")
    else:
        logger.info("[datasources] DATASOURCE_TOGGLES_ENABLED=false — feature idle")

    # T20: ECA rules engine — load + start polling loop
    try:
        from orchestrator.services.rules_engine import RulesEngine as _RulesEngine

        _rules_engine = _RulesEngine(building_id=settings.BUILDING_ID)
        _rule_count = _rules_engine.load()
        if _rule_count > 0:
            asyncio.create_task(_rules_engine.run_forever(interval_s=60))
            logger.info(f"[rules_engine] polling loop started for {_rule_count} rule(s)")
        else:
            logger.info("[rules_engine] no rules configured — engine idle")
        app.state.rules_engine = _rules_engine
    except Exception as _re_err:
        logger.warning(f"[rules_engine] failed to start (non-fatal): {_re_err}")

    # V5-T39: PROTECT — warm-load the policy engine so the first fetch doesn't pay
    if str(getattr(settings, "PROTECT_ENFORCE", "shadow")).lower() != "off":
        try:
            from orchestrator.services.privacy.enforcement import get_policy_engine

            async def _pdp_warm_load() -> None:
                await asyncio.sleep(150)  # GraphDB must be up before policies load
                engine = await get_policy_engine()
                if engine is not None:
                    logger.info(
                        f"[protect] PDP ready (mode={settings.PROTECT_ENFORCE}, "
                        f"policies={len(engine._policies or [])})"
                    )

            asyncio.create_task(_pdp_warm_load())
        except Exception as _pdp_err:
            logger.warning(f"[protect] PDP warm-load not scheduled: {_pdp_err}")

    # V5-T19: anomaly scanner — scheduled sweep persisting episodes to the events store
    if settings.ANOMALY_SCAN_INTERVAL_SECS > 0:
        try:
            from orchestrator.services.anomaly.scanner import (
                AnomalyScanner as _AScanner,
            )

            async def _anomaly_scan_loop() -> None:
                await asyncio.sleep(180)  # let GraphDB/adapters warm up after boot
                scanner = _AScanner(settings.BUILDING_ID, settings.BUILDING_NAMESPACE)
                while True:
                    try:
                        await scanner.scan_once()
                    except Exception as scan_err:
                        logger.warning(f"[anomaly-scan] sweep failed (will retry): {scan_err}")
                    await asyncio.sleep(settings.ANOMALY_SCAN_INTERVAL_SECS)

            app.state.anomaly_scan_task = asyncio.create_task(_anomaly_scan_loop())
            logger.info(
                f"[anomaly-scan] scheduled every {settings.ANOMALY_SCAN_INTERVAL_SECS}s "
                "(first sweep ~3min after boot)"
            )
        except Exception as _as_err:
            logger.warning(f"[anomaly-scan] failed to schedule (non-fatal): {_as_err}")
    else:
        logger.info("[anomaly-scan] ANOMALY_SCAN_INTERVAL_SECS=0 — scanner idle")

    # B.6: Initialize multi-building manager — discovers and loads all building configs
    try:
        building_manager = get_building_manager(
            config_dir=settings.BUILDING_CONFIG_FILE.rsplit("/", 1)[0] or "config"
        )
        logger.info(building_manager.summary())
        app.state.building_manager = building_manager
    except Exception as e:
        logger.warning(f"Multi-building manager initialization failed (non-fatal): {e}")

    # Phase 12B (2026-05-29): TTL validation BEFORE upload.
    # Ensures the TTL's `@prefix bldg:` matches building.yaml's
    # `ontology_namespace`.  Mismatch → hard-fail (orchestrator refuses to boot)
    # because SPARQL queries would silently return zero rows otherwise.
    # SHACL conformance is checked when run_shacl=True (off by default to keep
    # startup fast and avoid requiring the optional brickschema package).
    try:
        from orchestrator.services.building_context import resolve_building_context
        from orchestrator.services.ttl_validator import assert_ttl_validation_or_die

        _bctx_for_validation = resolve_building_context(settings.BUILDING_ID)
        assert_ttl_validation_or_die(
            building_id=settings.BUILDING_ID,
            declared_namespace=_bctx_for_validation.namespace,
            building_prefix=_bctx_for_validation.prefix,
            run_shacl=bool(getattr(settings, "TTL_VALIDATION_SHACL", False)),
        )
    except Exception as _ttl_err:
        # `assert_ttl_validation_or_die` raises TTLValidationError on
        # hard-failures — re-raise so the orchestrator process exits with a
        # clear, actionable error.  Other unexpected errors also propagate
        # because a TTL deployment bug is exactly the case we want loud.
        logger.error(f"[ttl_validator] startup HALTED — TTL validation failed:\n{_ttl_err}")
        raise

    # Phase 3 (2026-05-29): TTL auto-upload on startup.
    # Scan input/ for TTL files belonging to the active building(s), upload
    # any whose SHA-256 has changed since the last boot.  This eliminates the
    # manual `python scripts/onboard_building.py` step for new TTL files.
    # Non-fatal — orchestrator boots even if GraphDB is unreachable.
    try:
        # BUG-348: a building that has never been booted has an EMPTY GraphDB volume,
        # and an empty volume has no repository. The uploader then has nowhere to put
        # the ontology, ontology init fails its "GraphDB is not reachable" check, and
        # the orchestrator retries that forever while serving a building that can
        # answer nothing. Measured on bldg4's first boot.
        #
        # scripts/ensure_graphdb_repo.py was written for exactly this and had NO
        # CALLER — the seventh instance of that shape in this codebase. Creating the
        # repository belongs here, before the upload that needs it, because
        # `docker compose up -d` is the whole setup story (core contract #11) and a
        # brand-new building is precisely the case the GUI onboarding flow exercises.
        #
        # Idempotent: existing repositories are left alone, so this is a no-op on
        # every boot after the first.
        # Assigned BEFORE the try: if the bootstrap raises, the upload below still has
        # to run, and reading an unassigned name there would raise NameError into the
        # outer handler and silently skip every TTL — turning a repository hiccup into
        # a building with no ontology at all.
        created = False
        try:
            from orchestrator.services.ontology_manager import ensure_repository_exists

            created = await ensure_repository_exists()
            if created:
                logger.info(
                    "[graphdb] created repository %r on first boot", settings.GRAPHDB_REPOSITORY
                )
        except Exception as _repo_err:  # non-fatal: an existing repo is the normal case
            logger.warning(f"[graphdb] repository bootstrap skipped: {_repo_err}")

        from orchestrator.services.ttl_uploader import run_idempotent_uploads

        # Use the registered building IDs from the manager if available, else
        # fall back to the active BUILDING_ID from settings.
        # BUG-105: upload ONLY the ACTIVE building's TTLs. The registry may also know
        # parked/alias buildings, and uploading their files is how bldg3's ontology
        # ended up inside bldg2's repository (cross-building contamination, found and
        # cleaned 2026-07-30). v1 serves ONE building (core contract #1) — the active
        # id IS the whole list.
        _bldg_ids = [settings.BUILDING_ID]
        # A repository created a moment ago contains NOTHING, so nothing in it can be
        # "already uploaded". The SHA cache lives on a volume that outlives the
        # repository, and on the first run of this bootstrap it reported
        # `uploaded=0 skipped=8` into an empty graph -- the orchestrator booted
        # healthy, served bldg4, and answered nothing. Starting from an empty cache
        # makes the uploader re-ingest, which is what a new repository requires.
        summary = await run_idempotent_uploads(
            building_ids=_bldg_ids, cache={} if created else None
        )
        logger.info(
            f"[ttl_uploader] startup ingestion: uploaded={len(summary['uploaded'])} "
            f"skipped={len(summary['skipped'])} failed={len(summary['failed'])}"
        )
        # BUG-100: on a cold boot after a building swap, Phase 1 ran before this
        # ingestion loaded the graph (validation failed, init skipped). Re-run it now
        # that TTLs are in — forcing a sensor-map rebuild when new TTLs actually
        # landed. Nothing uploaded + already initialised → no-op (no restart needed).
        if (not _phase1_state["inited"]) or summary["uploaded"]:
            await _ontology_phase1(force_sensor_map=bool(summary["uploaded"]))
    except Exception as e:
        logger.warning(f"TTL auto-upload failed (non-fatal): {e}")

    # BUG-100 backstop: a warm GraphDB volume can take minutes to load its repository,
    # outlasting both Phase 1 and the post-ingestion retry above. If ontology init is
    # still pending, keep retrying in the background — a building swap must never
    # require a manual orchestrator restart.
    if not _phase1_state["inited"]:

        async def _phase1_retry() -> None:
            for _delay in (10, 20, 40, 60, 120, 180):
                await asyncio.sleep(_delay)
                await _ontology_phase1()
                if _phase1_state["inited"]:
                    logger.info("Ontology init recovered after GraphDB warm-up (BUG-100)")
                    return
            logger.warning("Ontology init still failing after ~4min of retries — check GraphDB")

        app.state.phase1_retry_task = asyncio.create_task(_phase1_retry())

    # Rebuild the GraphDB similarity index on startup so freshly-loaded TTLs (including any
    # GUI-registered sensors persisted to input/) become retrievable via semantic RAG — the index
    # does NOT auto-update on triple changes. Routed through the SAME debounced gateway that
    # registration and manual TTL upload use, so there is one similarity-rebuild path.
    try:
        from orchestrator.services.similarity_reindex import get_similarity_debouncer

        get_similarity_debouncer().request()
        logger.info("[reindex] startup similarity-index rebuild requested (debounced)")
    except Exception as e:  # pragma: no cover - defensive, non-fatal
        logger.warning(f"[reindex] startup similarity rebuild request failed (non-fatal): {e}")

    # LLM preflight (local Ollama): warn LOUDLY-but-non-fatally if the model server is
    # unreachable, and warm the model in the background so the first real request doesn't
    # time out and trip the circuit breaker (observed on a cold start with a large model).
    if settings.MODEL_PROVIDER == "local":

        async def _preflight_ollama() -> None:
            import httpx

            base = settings.OLLAMA_BASE_URL.rstrip("/")
            model = settings.OLLAMA_MODEL
            try:
                async with httpx.AsyncClient(timeout=8.0) as _c:
                    r = await _c.get(f"{base}/api/tags")
                tags = (
                    [m.get("name", "") for m in r.json().get("models", [])]
                    if r.status_code == 200
                    else []
                )
                if not tags:
                    logger.warning(
                        f"[llm-preflight] Ollama at {base} returned no models. "
                        f"Start it: `ollama serve`, then `ollama pull {model}`."
                    )
                    return
                if not any(t == model or t.startswith(model.split(":")[0]) for t in tags):
                    logger.warning(
                        f"[llm-preflight] Ollama is up but '{model}' is not pulled "
                        f"(available: {tags}). Run `ollama pull {model}`."
                    )
                    return
                logger.info(f"[llm-preflight] Ollama reachable; warming '{model}' in background…")
                async with httpx.AsyncClient(timeout=180.0) as _c:
                    await _c.post(
                        f"{base}/api/generate",
                        json={"model": model, "prompt": "OK", "stream": False},
                    )
                logger.info(f"[llm-preflight] '{model}' is warm.")
            except Exception as _pe:
                logger.warning(
                    f"[llm-preflight] Local LLM unreachable at {base} ({_pe}). Start Ollama on "
                    f"the host: `ollama serve` (+ `ollama pull {model}`). LLM-dependent answers "
                    f"will fail until it is up."
                )

        asyncio.create_task(_preflight_ollama())

    # Entity enrichment (Part D) — derive a Brick class + rdfs:label + relationships
    # for any time-series point that lacks them (from its URI tokens), so arbitrary
    # BMS/Haystack naming is queryable by class/label. Runs AFTER the TTL upload so
    # all points are present; idempotent (overwrites urn:ontosage:enrichment) and
    # non-fatal; a no-op when every point is already typed + labelled.
    if settings.ENTITY_ENRICHMENT_ENABLED:
        try:
            from orchestrator.services.entity_enricher import run_entity_enrichment

            await run_entity_enrichment()
        except Exception as e:
            logger.warning(f"Entity enrichment failed (non-fatal): {e}")

    # Embedding service — shared by document search and agent memory.
    #
    # This block used to also build a CapabilityIndexer and a stateful
    # SemanticRouter for the capability.yaml knowledge base. That KB was
    # replaced by ontosage:Amenity / ontosage:KnowledgeTopic TRIPLES answered by
    # CapabilityGraphResolver (TODO-012), so the indexer had no YAML to read and
    # the router's classify() had no caller. Both are gone (TODO-081); what is
    # kept is the embedding service they happened to create, which the document
    # KB and agent memory genuinely need — including its background pre-warm, so
    # the first user query does not pay the ~5-7s cold model load.
    try:
        from orchestrator.services.embedding_service import EmbeddingService

        _embedding_service = EmbeddingService(
            redis_manager=redis_manager,
            cache_ttl_seconds=settings.EMBEDDING_CACHE_TTL_SECONDS,
        )
        asyncio.get_event_loop().run_in_executor(None, _embedding_service.warm)
        app.state.embedding_service = _embedding_service
        logger.info(
            f"[embedding] service ready (provider={_embedding_service.provider}, "
            f"dim={_embedding_service.dimension}); pre-warm running in background"
        )
    except Exception as e:
        logger.warning(f"Embedding service init failed (non-fatal): {e}")

    # T08: Document KB indexing (per-building documents/ folder -> Qdrant documents_<bldg>)
    try:
        from orchestrator.agents.capability_agent import init_document_search
        from orchestrator.services.document_indexer import DocumentIndexer

        # Reuse embedding service stored on app.state (set by capability indexer above)
        _doc_embed_ref = getattr(app.state, "embedding_service", None)
        if _doc_embed_ref is None:
            from orchestrator.services.embedding_service import EmbeddingService

            _doc_embed_ref = EmbeddingService(
                redis_manager=redis_manager,
                cache_ttl_seconds=settings.EMBEDDING_CACHE_TTL_SECONDS,
            )
        from qdrant_client import AsyncQdrantClient

        _doc_qdrant_client_ref = AsyncQdrantClient(url=settings.QDRANT_URL)

        # Before any indexing: state the position for EVERY vector collection, not
        # just the one each indexer happens to touch. A collection left over from a
        # different embedding model is unusable — comparing vectors of different
        # widths returns nothing rather than raising — so without this a model swap
        # stays invisible until a user gets an empty answer. Enumerates whatever
        # exists, so a building onboarded tomorrow is covered too.
        try:
            from orchestrator.services.embedding_consistency import (
                check_embedding_consistency,
            )

            await check_embedding_consistency(
                _doc_qdrant_client_ref,
                expected_dim=_doc_embed_ref.dimension,
                model=settings.embedding_model,
            )
        except Exception as _ece:
            logger.warning(f"[embedding] consistency check skipped (non-fatal): {_ece}")

        doc_indexer = DocumentIndexer(
            qdrant_client=_doc_qdrant_client_ref,
            embedding_service=_doc_embed_ref,
            input_root="/app/input",
        )
        doc_index_results = await doc_indexer.index_all_buildings()
        for bldg, result in doc_index_results.items():
            logger.info(
                f"[document_indexer] {bldg}: status={result.status} "
                f"docs={result.documents} chunks={result.chunks}"
                + (f" reason={result.reason}" if result.reason else "")
            )
        # Wire into capability_agent so the document-search fallback is available
        init_document_search(_doc_qdrant_client_ref, _doc_embed_ref)
        app.state.doc_indexer = doc_indexer
        app.state.doc_index_results = doc_index_results
    except Exception as e:
        logger.warning(f"Document KB indexing init failed (non-fatal): {e}")

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

connection_manager = ConnectionManager()

# Ensure outputs directory exists
os.makedirs("/app/outputs", exist_ok=True)

# Mount static files for serving plots and data
app.mount("/static", StaticFiles(directory="/app/outputs"), name="static")

# E.1: CORS — use CORS_ORIGINS env var; '*' for dev, explicit origins for production
_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
# SECURITY: never combine a wildcard origin with credentials. Starlette would
# otherwise reflect the caller's Origin back and attach
# Access-Control-Allow-Credentials, letting ANY site issue credentialed
# (cookie-bearing) cross-origin requests. Credentials are enabled only when an
# explicit origin allowlist is configured (set CORS_ORIGINS in production).
_cors_allow_all = "*" in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _cors_allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(
    f"CORS origins: {_cors_origins} "
    f"(credentials={'off — wildcard' if _cors_allow_all else 'on'})"
)

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

# E.3: Per-IP rate limiting
_RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "60"))  # per window
_RATE_LIMIT_WINDOW_S = int(os.environ.get("RATE_LIMIT_WINDOW_S", "60"))  # seconds

# CIDRs of reverse proxies/load balancers trusted to set X-Forwarded-For.
# Empty (default) = never trust XFF; rate-limit on the direct TCP peer only.
# Without this, a deployment behind a proxy rate-limits ALL clients together
# under the proxy's one IP (or, with a spoofed header and no allow-list, lets
# an attacker pick any bucket) — see PRODUCTION_READINESS_AUDIT.md #3.
_TRUSTED_PROXY_NETS: List[Any] = []
for _cidr in settings.TRUSTED_PROXY_CIDRS.split(","):
    _cidr = _cidr.strip()
    if not _cidr:
        continue
    try:
        _TRUSTED_PROXY_NETS.append(ipaddress.ip_network(_cidr, strict=False))
    except ValueError:
        logger.warning(f"Ignoring invalid TRUSTED_PROXY_CIDRS entry: {_cidr!r}")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiter.

    Uses Redis INCR/EXPIRE (fixed window) when the Redis client is connected,
    so the limit is shared correctly across multiple orchestrator replicas.
    Falls back to an in-process token bucket when Redis isn't available yet
    (e.g. before the lifespan startup hook runs, or in unit tests) so rate
    limiting degrades gracefully rather than failing open or crashing.
    """

    def __init__(
        self,
        app,
        requests: int = _RATE_LIMIT_REQUESTS,
        window: int = _RATE_LIMIT_WINDOW_S,
    ):
        super().__init__(app)
        self._requests = requests
        self._window = window
        self._counts: dict = {}  # in-memory fallback: ip -> deque of timestamps

    _EXEMPT_PATHS = {"/ping", "/health"}

    @staticmethod
    def _client_ip(request: Request) -> str:
        """Resolve the client IP, honoring X-Forwarded-For only when the
        direct peer is a configured trusted proxy."""
        direct = request.client.host if request.client else "unknown"
        if not _TRUSTED_PROXY_NETS or direct == "unknown":
            return direct
        try:
            direct_addr = ipaddress.ip_address(direct)
        except ValueError:
            return direct
        if not any(direct_addr in net for net in _TRUSTED_PROXY_NETS):
            return direct
        xff = request.headers.get("x-forwarded-for")
        if not xff:
            return direct
        # Left-most entry is the original client in the de-facto XFF convention.
        return xff.split(",")[0].strip() or direct

    def _allow_memory(self, client_ip: str) -> bool:
        now = time.monotonic()
        window_start = now - self._window
        bucket = self._counts.setdefault(client_ip, collections.deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if not bucket:
            del self._counts[client_ip]
            bucket = self._counts.setdefault(client_ip, collections.deque())
        if len(bucket) >= self._requests:
            return False
        bucket.append(now)
        return True

    # Atomic fixed-window counter: INCR then EXPIRE-if-new in ONE round trip. Doing it in
    # two calls risks the process dying between them, leaving a key with no TTL that 429s
    # that IP forever. The TTL<0 guard also re-arms any key that somehow lost its expiry
    # (e.g. left over from the old two-call path) so no bucket can get permanently stuck.
    _RATE_LUA = (
        "local c = redis.call('INCR', KEYS[1]) "
        "if c == 1 or redis.call('TTL', KEYS[1]) < 0 then "
        "redis.call('EXPIRE', KEYS[1], ARGV[1]) end "
        "return c"
    )

    async def _allow_redis(self, client_ip: str) -> bool:
        """Fixed-window counter shared across replicas via an atomic Redis Lua script."""
        key = f"ratelimit:{client_ip}"
        count = await redis_manager.client.eval(self._RATE_LUA, 1, key, self._window)
        return int(count) <= self._requests

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)
        client_ip = self._client_ip(request)
        use_redis = redis_manager is not None and redis_manager.client is not None
        try:
            allowed = (
                await self._allow_redis(client_ip) if use_redis else self._allow_memory(client_ip)
            )
        except Exception as e:
            # A Redis hiccup must not block all traffic — degrade to the
            # in-memory bucket for this request instead of 500ing every call.
            logger.warning(
                f"[RateLimitMiddleware] Redis backend failed, using in-memory fallback: {e}"
            )
            allowed = self._allow_memory(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests. Please wait before retrying."},
                headers={"Retry-After": str(self._window)},
            )
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


# F2: Admin-action audit log. Records every MUTATING request to an admin-console
# path (who / what / when / outcome) to Postgres. Registered LAST so it is the
# OUTERMOST middleware — it therefore captures requests even when an inner
# middleware (rate-limit / RBAC) rejects them. Best-effort: never breaks a request.
_AUDIT_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


def _should_audit_request(request: Request) -> bool:
    """True for a mutating request to an admin-console path worth auditing."""
    if request.method not in _AUDIT_METHODS:
        return False
    path = request.url.path
    return path.startswith("/api/v1/admin/") or path.startswith("/api/v1/datasources")


async def _record_audit(request: Request, status: int) -> None:
    """Best-effort audit write; resolves the actor from the session token if present."""
    if postgres_manager is None:
        return
    username: Optional[str] = None
    role: Optional[str] = None
    try:
        token = _extract_session_token(
            request.cookies.get("session_token"), request.headers.get("authorization")
        )
        if token:
            ctx = await auth_manager.validate_session_context(token)
            if ctx:
                username = ctx.get("username")
                role = ctx.get("role")
    except Exception:
        pass  # unauthenticated / bad token — still record the attempt (anonymous)
    await postgres_manager.record_admin_action(
        username=username,
        role=role,
        method=request.method,
        path=request.url.path,
        status=status,
        trace_id=getattr(request.state, "trace_id", None),
    )


class AuditMiddleware(BaseHTTPMiddleware):
    """Persists mutating admin-console actions to the audit log (best-effort)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        try:
            if _should_audit_request(request):
                await _record_audit(request, response.status_code)
        except Exception as e:  # audit must never break the request
            logger.debug(f"[audit] skipped: {e}")
        return response


app.add_middleware(AuditMiddleware)


@app.get("/", response_model=APIResponse)
async def root():
    """Root endpoint"""
    return APIResponse(
        success=True,
        data={
            "service": "OntoSage 2.0 Orchestrator",
            "version": "2.0.0",
            "status": "running",
        },
    )


@app.get("/ping")
async def ping():
    """Lightweight liveness check — no downstream probes. Used by Docker health check."""
    return {"status": "ok"}


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
                    "backends": list(adapter_registry._adapters.keys()),
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

    # Self-heal a stale ontology_valid=false: the startup check may have run before GraphDB
    # accepted connections on a cold `docker-compose up`. Re-validate here (cooldown-bounded).
    try:
        ontology_ok = (await ontology_validator.revalidate_if_needed()).ok
    except Exception:
        ontology_ok = ontology_validator.last_result.ok

    return APIResponse(
        success=overall != "unhealthy",
        data={
            "status": overall,
            "duration_ms": duration_ms,
            "services": checks,
            "building": settings.BUILDING_NAME,
            "ontology_valid": ontology_ok,
            "introspector_ready": ontology_introspector.is_ready(),
            # Build provenance — which commit/time this image was built from (baked as ENV at build).
            # "unknown" means the image was built without GIT_SHA passed.
            "build": {
                "sha": os.environ.get("BUILD_SHA", "unknown"),
                "time": os.environ.get("BUILD_TIME", "unknown"),
            },
        },
    )


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


def _extract_session_token(
    session_token: Optional[str], authorization: Optional[str]
) -> Optional[str]:
    """Pull the session token from a cookie or Authorization header."""
    if session_token:
        return session_token
    if authorization and isinstance(authorization, str):
        if authorization.startswith("Bearer "):
            return authorization.replace("Bearer ", "").strip()
        return authorization.strip()
    return None


async def get_user_context(
    session_token: Optional[str] = Cookie(None, alias="session_token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> Optional[UserContext]:
    """Resolve the session into a UserContext with role + permissions.

    Bridges the session-based auth (Redis) onto the RBAC permission model.
    Returns None when there is no valid session.
    """
    token = _extract_session_token(session_token, authorization)
    if not token:
        return None
    ctx = await auth_manager.validate_session_context(token)
    if not ctx:
        return None
    role = ctx.get("role") or "readonly"
    return UserContext(
        user_id=ctx["username"],
        username=ctx["username"],
        role=role,
        tenant_id="default",
        allowed_buildings=[],  # empty = all buildings (single-tenant default)
        permissions=ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["readonly"]),
    )


def require_permission(permission: str):
    """FastAPI dependency factory enforcing a single RBAC permission.

    Raises 401 when unauthenticated, 403 when the authenticated user's role
    lacks `permission`. Drives off the session→UserContext bridge above.
    """

    async def _dependency(
        user: Optional[UserContext] = Depends(get_user_context),
    ) -> UserContext:
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Permission '{permission}' required; role " f"'{user.role}' is not authorized"
                ),
            )
        return user

    return _dependency


def _user_owns_conversation(user: UserContext, conversation_id: str) -> bool:
    """Conversation IDs are suffixed with `:{username}`. Owners and users with
    user:read (admin) may access; everyone else is denied."""
    if user.has_permission("user:read"):
        return True
    return conversation_id.endswith(f":{user.username}")


# ==================== Conversation History (auth + ownership enforced) =========


@app.get("/conversations/{user_id}", response_model=APIResponse)
async def get_conversations(
    user_id: str,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Get list of conversations for a user (own only, unless user:read)."""
    if user.username != user_id and not user.has_permission("user:read"):
        raise HTTPException(status_code=403, detail="Cannot access another user's conversations")
    try:
        conversations = []
        if postgres_manager and postgres_manager.pool:
            conversations = await postgres_manager.get_user_conversations(user_id)
        if not conversations and redis_manager:
            conversations = await redis_manager.get_user_conversations(user_id)
        return APIResponse(success=True, data={"conversations": conversations})
    except Exception as e:
        logger.error(f"Failed to get conversations: {e}")
        return APIResponse(success=False, error=str(e))


@app.get("/conversations/{conversation_id}/messages", response_model=APIResponse)
async def get_conversation_messages(
    conversation_id: str,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Get messages for a conversation (owner or admin only)."""
    if not _user_owns_conversation(user, conversation_id):
        raise HTTPException(status_code=403, detail="Cannot access this conversation")
    try:
        messages = []
        if postgres_manager and postgres_manager.pool:
            messages = await postgres_manager.get_conversation_messages(conversation_id)
        if not messages and redis_manager:
            messages = await redis_manager.get_messages(conversation_id)
        return APIResponse(success=True, data={"messages": messages})
    except Exception as e:
        logger.error(f"Failed to get messages for {conversation_id}: {e}")
        return APIResponse(success=False, error=str(e))


# ==================== Authentication Endpoints ====================


class LoginRequest(BaseModel):
    """Validated body for login endpoints."""

    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=1024)


class RegisterRequest(BaseModel):
    """Validated body for /auth/register. Role is NOT accepted from the client —
    new users receive the default role server-side to prevent privilege escalation."""

    username: str = Field(..., min_length=3, max_length=255, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=12, max_length=1024)
    email: Optional[str] = Field(default=None, max_length=320)


@app.post("/auth/register", response_model=APIResponse)
async def register_user(body: RegisterRequest):
    """
    Register a new user. New accounts receive the server-side default role
    (occupant — can chat and read sensor/metadata, no config/admin access) —
    the client cannot request a role. Use POST /api/v1/admin/users (system:admin)
    to create accounts with an elevated role.
    """
    try:
        result = await auth_manager.register_user(body.username, body.password, body.email)

        if not result["success"]:
            return APIResponse(success=False, error=result["error"])

        return APIResponse(success=True, data=result)

    except Exception as e:
        logger.error(f"Registration endpoint error: {e}", exc_info=True)
        return APIResponse(success=False, error="Registration failed")


@app.post("/auth/login", response_model=APIResponse)
async def login_user(body: LoginRequest):
    """
    Login user and create session.

    Request: {"username": "...", "password": "..."}
    Returns a session_token (also set as an httponly cookie).
    """
    try:
        result = await auth_manager.login_user(body.username, body.password)

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
            secure=settings.COOKIE_SECURE,
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
async def get_current_user_info(
    current_user: Optional[str] = Depends(get_current_user),
):
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


class SaveHistoryRequest(BaseModel):
    """Validated body for POST /history/{username}."""

    messages: List[Dict[str, str]] = Field(default_factory=list, max_length=500)


@app.post("/history/{username}", response_model=APIResponse)
async def save_user_history(
    username: str,
    request: SaveHistoryRequest,
    current_user: Optional[str] = Depends(get_current_user),
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

        messages = request.messages

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
            # Track this conversation under the user's set so delete_user()
            # can find it without a full KEYS/SCAN of the conversation space.
            await redis_manager.add_conversation_to_user(username, conv_id, "Imported Chat")

        return APIResponse(
            success=True,
            data={"conversation_id": conv_id, "message_count": len(messages)},
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


async def _run_workflow_as_job(
    job_id: str,
    state,
    conversation_id: str,
    username: str,
) -> None:
    """Background task: run orchestrator workflow and update job status in Redis."""
    try:
        await job_queue.update_job(job_id, _JobStatus.RUNNING)
        updated_state = await orchestrator.execute(state)
        await redis_manager.save_state(updated_state)

        response_text = updated_state.intermediate_results.get("response", "")
        intent = getattr(updated_state, "current_intent", "unknown")

        await job_queue.update_job(
            job_id,
            _JobStatus.DONE,
            result={
                "conversation_id": conversation_id,
                "response": response_text,
                "intent": intent,
                "username": username,
            },
        )
        logger.info(f"[job] job_id={job_id} completed intent={intent}")
    except Exception as e:
        logger.error(f"[job] job_id={job_id} failed: {e}", exc_info=True)
        await job_queue.update_job(job_id, _JobStatus.FAILED, error=str(e))


@app.post("/chat", response_model=APIResponse)
async def chat(
    request: ChatRequest,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """
    Synchronous chat endpoint (requires authentication)

    V5-T42: the gate is ``metadata:read`` (every role has it, including
    readonly) — the old ``sensor:read`` gate 403'd readonly users before the
    conversational layer could refuse GRACEFULLY. Data protection does not
    live at this door anymore: per-lane RBAC plus the PDP at every fetch
    chokepoint (V5-T39) decide what each role actually receives.

    Request body validated via ChatRequest Pydantic model.
    Max message length: 10 000 chars. Null bytes / control chars stripped.
    """
    try:
        # V5-BUG-177: see /v1/chat/completions — a turn must declare when the
        # LLM refused, so graders quarantine it instead of scoring the fallback.
        begin_llm_trace()

        username = user.username

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
        # Phase 14A — multi-persona support.  `personas` (list) takes precedence
        # over the legacy single-string `persona` field.  The PersonaRegistry
        # blends priors across the list at agent time.
        personas_list = list(getattr(req, "personas", []) or [])
        language = req.language or "en"
        building = req.building or settings.BUILDING_ID

        # Load or create conversation state
        state = await redis_manager.load_state(conversation_id)

        if not state:
            # New conversation
            # Phase 14A: persona is no longer Literal-constrained; the registry
            # resolves unknowns via alias map.  When personas list is provided,
            # back-fill persona with the first entry for legacy code paths.
            _primary_persona = personas_list[0] if personas_list else persona
            state = ConversationState(
                conversation_id=conversation_id,
                user_message=user_message,  # Add current message
                messages=[],
                building_id=building,
                persona=_primary_persona,
                personas=personas_list,
            )
            # Store user association
            state.user_id = username
        else:
            # Update existing conversation with new message
            state.user_message = user_message
            # Phase 14A: per-turn persona override.  A new turn can change the
            # active personas (e.g. the user becomes "facility_manager+student").
            if personas_list:
                state.personas = personas_list
                state.persona = personas_list[0]
            elif persona and persona != "general":
                state.persona = persona
                state.personas = []

        # RBAC context for workflow agents (fix 2026-06-12): control, alert and
        # preference nodes read user_role/user_id from intermediate_results, but
        # nothing ever wrote them — every authenticated user was treated as
        # guest/readonly, so actuation approval, alert creation and preference
        # storage were unconditionally declined on this endpoint.
        state.intermediate_results["user_id"] = username
        state.intermediate_results["user_role"] = user.role

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

        # Long-running report queries are offloaded to a background task so
        # the client does not time out. Response cache is checked first —
        # warm-cache hits still use the synchronous path.
        _REPORT_TRIGGER_PHRASES = (
            "generate report",
            "create report",
            "build report",
            "generate a report",
            "create a report",
            "energy report",
            "monthly report",
            "weekly report",
            "daily report",
            "annual report",
        )
        _is_report_query = any(ph in user_message.lower() for ph in _REPORT_TRIGGER_PHRASES)

        if _is_report_query and job_queue is not None:
            _job_id = await job_queue.create_job(conversation_id, user_message, intent="report")
            asyncio.create_task(_run_workflow_as_job(_job_id, state, conversation_id, username))
            logger.info(f"[async-job] report offloaded job_id={_job_id}")
            return APIResponse(
                success=True,
                data={
                    "job_id": _job_id,
                    "status": "queued",
                    "message": (
                        "Your report is being generated. "
                        f"Poll GET /jobs/{_job_id} for the result."
                    ),
                    "poll_url": f"/jobs/{_job_id}",
                    "conversation_id": conversation_id,
                    "intent": "report",
                    "username": username,
                },
            )

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

        # V4 (T24): persist the proof-of-analysis dossier with the transcript,
        # the same way media rides Message.metadata
        _dossier = updated_state.intermediate_results.get("evidence_dossier")
        if _dossier:
            assistant_metadata = {**(assistant_metadata or {}), "evidence": _dossier}

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
                "media": (assistant_metadata.get("media") if assistant_metadata else None),
                "sources": updated_state.intermediate_results.get("sources", []),
                # V4 ARBITER (T24/T22): the proof-of-analysis dossier and the
                # structured clarify payload ride the same wiring as `sources`
                "evidence": updated_state.intermediate_results.get("evidence_dossier"),
                # V6-T02: the universal evidence record, assembled at the chokepoint for
                # EVERY lane. Deliberately a separate key from `evidence`: that one is V4's
                # deliberate-lane dossier and only the ranking lane produces it, so merging
                # them would make an absent dossier indistinguishable from an absent record.
                "evidence_record": updated_state.intermediate_results.get("evidence_record"),
                "clarification": updated_state.intermediate_results.get(
                    "needs_clarification_payload"
                ),
                # V4-T33: unified plan trace (reflex 1-step or deliberative)
                "plan_trace": updated_state.intermediate_results.get("plan_trace"),
                # V5-BUG-177: None when the LLM behaved; a cause summary otherwise.
                "llm_degraded": llm_degradation(),
            },
        )

    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return APIResponse(success=False, error=str(e))


@app.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """
    Streaming chat endpoint (Server-Sent Events).
    Emits `progress` events per LangGraph node, then `token` with the final response.
    V5-T42: gate matches /chat — metadata:read; lane RBAC + PDP protect the data.
    """
    # Node → user-friendly label map shared between SSE generator and WS handler
    _NODE_LABELS: dict = {
        "dialogue": "🧠 Analyzing your question...",
        "sparql": "📡 Querying building ontology...",
        "sql": "📊 Fetching sensor data...",
        "analytics": "🔬 Running analytics...",
        "visualization": "📈 Creating visualization...",
        "report": "📋 Assembling report...",
        "anomaly": "🔍 Detecting anomalies...",
        "export": "💾 Exporting data...",
        "planner": "🗺️ Planning tasks...",
        "recommend": "💡 Building recommendations...",
        "response": "✍️ Composing response...",
    }

    try:
        username = user.username

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
        fresh_session = req.fresh_session

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

                # Propagate fresh_session flag into state so workflow skips memory injection
                if fresh_session:
                    state.intermediate_results["fresh_session"] = True

                # RBAC context for workflow agents (fix 2026-06-12, same as /chat)
                state.intermediate_results["user_id"] = username
                state.intermediate_results["user_role"] = user.role

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

                # Stream workflow execution — emit progress events per node, then final response
                updated_state = state
                async for step in orchestrator.stream_execute(state):
                    if isinstance(step, dict):
                        for node_name, node_state in step.items():
                            label = _NODE_LABELS.get(node_name)
                            if label:
                                yield (
                                    f"data: {json.dumps({'type': 'progress', 'node': node_name, 'label': label})}\n\n"
                                )
                            # LangGraph may yield ConversationState OR dict
                            if isinstance(node_state, ConversationState):
                                updated_state = node_state
                            elif isinstance(node_state, dict) and "messages" in node_state:
                                try:
                                    updated_state = ConversationState(**node_state)
                                except Exception:
                                    pass

                # Get last assistant message (not user's, which may also be last)
                assistant_entry = next(
                    (m for m in reversed(updated_state.messages) if m.role == "assistant"),
                    None,
                )
                full_response = (
                    assistant_entry.content
                    if assistant_entry
                    else updated_state.intermediate_results.get(
                        "dialogue_response", "No response generated"
                    )
                )
                assistant_metadata = assistant_entry.metadata if assistant_entry else None

                # Save assistant message
                await redis_manager.save_message(
                    conversation_id,
                    "assistant",
                    full_response,
                    metadata=assistant_metadata,
                )

                # Save to Postgres if available
                if postgres_manager and postgres_manager.pool:
                    await postgres_manager.save_message(
                        conversation_id, "assistant", full_response, username
                    )

                # Save updated state
                await redis_manager.save_state(updated_state)

                # Deliver final response as token event, then media (if any), then DONE
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


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-Compatible API  (/v1/*)
# Open WebUI is pointed at http://ontosage-orchestrator:8000/v1 via
# OPENAI_API_BASE_URL.  These two endpoints make OntoSage a drop-in
# OpenAI-compatible backend.  Progress steps are streamed inside
# <think>…</think> blocks so Open WebUI renders them as a collapsible
# "Thinking…" panel — identical to the Claude Code / ChatGPT o1 UX.
# ─────────────────────────────────────────────────────────────────────────────

_OAI_MODEL_ID = "ontosage"
# Bearer key(s) accepted on /v1/chat/completions. Sourced from settings
# (PIPELINE_API_KEY env var) — never hardcode in source. Open WebUI sends this
# as OPENAI_API_KEY. Multiple comma-separated keys are supported for rotation.
#
# The published default key is explicitly EXCLUDED so a stock deployment
# (STRICT_SECRETS=false) can never authenticate /v1/* or the WS proxy with the
# key that ships in the repo. Operators must set a real PIPELINE_API_KEY.
_DEFAULT_PIPELINE_KEY = "sk-ontobot-pipeline"
_OAI_AUTH_KEYS = {
    k.strip()
    for k in str(settings.PIPELINE_API_KEY).split(",")
    if k.strip() and k.strip() != _DEFAULT_PIPELINE_KEY
}
if not _OAI_AUTH_KEYS:
    logger.warning(
        "No non-default PIPELINE_API_KEY configured — /v1/* (OpenAI-compatible) "
        "and the WebSocket proxy will reject ALL keys. Set PIPELINE_API_KEY to a "
        "strong secret to enable them."
    )

_OAI_NODE_LABELS: dict = {
    "dialogue": "🧠 Analyzing your question",
    "sparql": "📡 Querying building ontology",
    "sql": "📊 Fetching sensor data",
    "analytics": "🔬 Running analytics",
    "visualization": "📈 Generating visualization",
    "report": "📋 Compiling report",
    "anomaly": "🔍 Checking for anomalies",
    "export": "💾 Preparing export",
    "planner": "🗺️ Planning multi-step task",
    "recommend": "💡 Generating recommendations",
    "response": "✍️ Composing response",
    "floor_plan": "🗺️ Resolving floor plan",  # ← added for OpenWebUI pipeline disclosure
}


def _oai_auth(authorization: Optional[str] = Header(None)) -> None:
    """Validate the Bearer token sent by Open WebUI."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    # Constant-time comparison against each accepted key to avoid leaking key
    # material via response-timing side channels.
    if not token or not any(hmac.compare_digest(token, k) for k in _OAI_AUTH_KEYS):
        raise HTTPException(status_code=401, detail="Invalid API key")


def _is_placeholder_account(row: Dict[str, Any]) -> bool:
    """True for the auto-created ``/v1`` conversation-owner stub (never a real account)."""
    meta = row.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            return False
    return isinstance(meta, dict) and meta.get("source") == "open_webui"


async def resolve_forwarded_user(request: Request) -> Tuple[str, str]:
    """Identify the END user behind a shared-pipeline-key request.

    Open WebUI authenticates to OntoSage with one shared key, so every chat request
    would otherwise arrive as the same least-privilege identity and no per-user RBAC
    could apply — an analyst and a visitor would get identical answers. With
    ``TRUST_FORWARDED_USER`` on, the proxy also forwards who is signed in
    (``X-OpenWebUI-User-Email`` by default) and that account's OntoSage role is used.

    Returns ``(username, role)``, defaulting to least privilege. Security: the header
    is only as trustworthy as the network holding the pipeline key, which is why this
    is opt-in and never inferred.
    """
    fallback = ("openwebui_user", "readonly")
    if not getattr(settings, "TRUST_FORWARDED_USER", False):
        return fallback

    header_name = getattr(settings, "FORWARDED_USER_HEADER", "X-OpenWebUI-User-Email")
    ident = (request.headers.get(header_name) or "").strip()
    if not ident or postgres_manager is None:
        return fallback

    # Match on username first, then email — Open WebUI forwards an email, while
    # OntoSage accounts are keyed by username (often the email's local part).
    candidates = [ident]
    if "@" in ident:
        candidates.append(ident.split("@", 1)[0])
    for name in candidates:
        try:
            row = await postgres_manager.get_user(name)
        except Exception as e:  # never let identity lookup break a chat turn
            logger.warning(f"[forwarded-user] lookup failed for {name!r}: {e}")
            return fallback
        if not row or not row.get("username"):
            continue
        # Chatting through /v1 auto-creates a placeholder row so conversations have a
        # valid owner. It is a foreign-key stub, not an identity decision — and it is
        # always readonly. Treating one as an account would let a stub created before
        # the admin provisioned someone permanently shadow their real (higher) role.
        if _is_placeholder_account(row):
            logger.debug(f"[forwarded-user] skipping placeholder row {row['username']!r}")
            continue
        role = row.get("role") or "readonly"
        logger.info(f"[forwarded-user] {ident!r} → {row['username']!r} (role={role})")
        return row["username"], role

    # A real person signed into the proxy with no OntoSage account: let them ask,
    # but at least privilege — silently granting more would be worse than a refusal.
    logger.info(f"[forwarded-user] {ident!r} has no OntoSage account — using readonly")
    return (ident, "readonly")


# NOTE: The GET /v1/models and POST /v1/chat/completions routes are defined
# in the 'OpenAI Compatibility Layer' section below.  Do not add duplicate
# route decorators here — FastAPI uses the FIRST matching route, and a
# duplicate silently shadows the better handler.


# (POST /v1/chat/completions moved to OpenAI Compatibility Layer ~line 2094
# to avoid FastAPI route shadowing — the handler there correctly
# reconstructs conversation history, detects personas, and
# includes floor_plan in the pipeline-step disclosure block.)


async def _unused_oai_chat_completions(
    request: Request,
    _: None = Depends(_oai_auth),
):
    """
    OpenAI-compatible streaming chat endpoint consumed by Open WebUI.

    Streaming format:
      1. <think> … progress steps … </think>   ← Open WebUI renders as collapsible panel
      2. Final response tokens                  ← streamed word-by-word

    Non-streaming: returns a full completion JSON object.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages_raw: List[Dict] = body.get("messages", [])
    stream: bool = body.get("stream", True)
    model: str = body.get("model", _OAI_MODEL_ID)

    # Extract user text from the last user message (handles str and list content)
    user_message = ""
    user_msg_obj = next((m for m in reversed(messages_raw) if m.get("role") == "user"), None)
    if user_msg_obj:
        raw_content = user_msg_obj.get("content", "")
        if isinstance(raw_content, str):
            user_message = raw_content
        elif isinstance(raw_content, list):
            user_message = " ".join(
                p.get("text", "")
                for p in raw_content
                if isinstance(p, dict) and p.get("type") == "text"
            )

    if not user_message.strip():
        raise HTTPException(status_code=400, detail="No user message found")

    # Use Open WebUI's X-Chat-Id header → body field → stable hash of first user message
    chat_id_header = request.headers.get("X-Chat-Id") or request.headers.get("x-chat-id")
    conversation_id = (
        chat_id_header
        or body.get("conversation_id")
        or f"owui_{abs(hash(messages_raw[0].get('content', '') if messages_raw else user_message))}"
    )
    user_id = body.get("user") or request.headers.get("X-User-Id", "openwebui-user")

    # ── Build ConversationState ───────────────────────────────────────────────
    state = ConversationState(
        conversation_id=conversation_id,
        user_id=user_id,
        user_message=user_message,
        building_id=os.environ.get("DEFAULT_BUILDING_ID") or settings.BUILDING_ID,
        messages=[Message(role="user", content=user_message)],
        intermediate_results={},
    )

    completion_id = f"chatcmpl-{_uuid_mod.uuid4().hex}"
    created_ts = int(datetime.utcnow().timestamp())

    def _chunk(content: str, finish_reason: Optional[str] = None) -> str:
        """Serialize one OpenAI SSE delta chunk."""
        delta = {"content": content} if content else {}
        choice: dict = {"index": 0, "delta": delta, "finish_reason": finish_reason}
        obj = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model,
            "choices": [choice],
        }
        return f"data: {json.dumps(obj)}\n\n"

    async def stream_generator():
        try:
            progress_lines: List[str] = []
            updated_state = state

            # ── 1. Collect progress events and final state ─────────────────
            async for step in orchestrator.stream_execute(state):
                if not isinstance(step, dict):
                    continue
                for node_name, node_state in step.items():
                    label = _OAI_NODE_LABELS.get(node_name)
                    if label:
                        progress_lines.append(f"{label}…")
                    if isinstance(node_state, ConversationState):
                        updated_state = node_state
                    elif isinstance(node_state, dict) and "messages" in node_state:
                        try:
                            updated_state = ConversationState(**node_state)
                        except Exception:
                            pass

            # ── 2. Stream the <think> block (progress steps) ───────────────
            if progress_lines:
                yield _chunk("<think>\n")
                for line in progress_lines:
                    yield _chunk(f"{line}\n")
                yield _chunk("</think>\n\n")

            # ── 3. Extract final assistant response ────────────────────────
            assistant_entry = next(
                (m for m in reversed(updated_state.messages) if m.role == "assistant"),
                None,
            )
            full_response = (
                assistant_entry.content
                if assistant_entry
                else updated_state.intermediate_results.get(
                    "dialogue_response", "I'm sorry, I couldn't generate a response."
                )
            )

            # ── 4. Stream response word-by-word ────────────────────────────
            words = full_response.split(" ")
            for i, word in enumerate(words):
                token = word if i == 0 else f" {word}"
                yield _chunk(token)
            yield _chunk("", finish_reason="stop")
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"[/v1/chat/completions] stream error: {e}", exc_info=True)
            err_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": f"\n\n❌ Error: {e}"},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(err_chunk)}\n\n"
            yield "data: [DONE]\n\n"

    if stream:
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Nginx: disable buffering so chunks flow live
            },
        )

    # ── Non-streaming fallback ────────────────────────────────────────────────
    updated_state = await orchestrator.execute(state)
    assistant_entry = next(
        (m for m in reversed(updated_state.messages) if m.role == "assistant"),
        None,
    )
    full_response = assistant_entry.content if assistant_entry else "No response generated."
    return JSONResponse(
        {
            "id": completion_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": full_response},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    )


async def _authenticate_websocket(websocket: WebSocket) -> Optional[Dict[str, Any]]:
    """Authenticate a /stream WebSocket handshake.

    Accepts EITHER:
      * the pipeline API key (PIPELINE_API_KEY) — "proxy" mode for a trusted
        front-end (Open WebUI, a custom chatbot UI) that authenticates its own
        users.  The user identity it forwards is treated as untrusted and is
        capped at the readonly role (parity with the /v1 path).
      * a valid user session token — "session" mode; the resolved username and
        role drive conversation ownership and in-pipeline RBAC.

    The token is read from the ``Authorization: Bearer <token>`` header
    (non-browser clients) or the ``?token=<token>`` query parameter (browser
    WebSocket clients cannot set custom headers).

    Returns an auth dict, or None to reject the handshake.
    """
    token: Optional[str] = None
    auth_header = websocket.headers.get("authorization")
    if auth_header:
        token = (
            auth_header[7:].strip()
            if auth_header.lower().startswith("bearer ")
            else auth_header.strip()
        )
    if not token:
        token = websocket.query_params.get("token")
    if not token:
        return None

    # Pipeline key → trusted proxy mode (constant-time compare).
    if any(hmac.compare_digest(token, k) for k in _OAI_AUTH_KEYS):
        return {
            "mode": "proxy",
            "username": "stream-proxy-user",
            "role": "readonly",
            "is_admin": False,
        }

    # Otherwise, treat the token as a user session token.
    if auth_manager is not None:
        ctx = await auth_manager.validate_session_context(token)
        if ctx and ctx.get("username"):
            role = ctx.get("role") or "facility_manager"
            perms = ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["readonly"])
            return {
                "mode": "session",
                "username": ctx["username"],
                "role": role,
                "is_admin": "user:read" in perms,
            }

    return None


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
    # ── Authenticate the handshake BEFORE accepting ──────────────────────────
    # An unauthenticated /stream would expose the full pipeline (incl. the
    # code-executor) and allow reading/injecting any conversation by id (IDOR).
    auth = await _authenticate_websocket(websocket)
    if auth is None:
        # 1008 = policy violation. Closing before accept() rejects the handshake.
        await websocket.close(code=1008)
        logger.warning("[/stream] rejected unauthenticated WebSocket handshake")
        return

    await websocket.accept()
    connection_manager.register(websocket)

    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            request = json.loads(data)

            user_message = request.get("message")
            if not user_message:
                await websocket.send_json({"type": "error", "data": "Message is required"})
                continue

            # ── Scope the conversation id to the authenticated identity ───────
            # Session users may only address conversations they own (suffixed
            # ":{username}") unless they hold an admin (user:read) role; an
            # unowned id is rejected rather than silently leaking another user's
            # history. Proxy-mode (trusted front-end) callers manage their own
            # namespacing.
            requested_cid = request.get("conversation_id")
            if auth["mode"] == "session":
                _uname = auth["username"]
                if requested_cid:
                    if not (requested_cid.endswith(f":{_uname}") or auth["is_admin"]):
                        await websocket.send_json(
                            {"type": "error", "data": "You do not own this conversation."}
                        )
                        continue
                    conversation_id = requested_cid
                else:
                    conversation_id = f"{generate_conversation_id()}:{_uname}"
            else:  # proxy mode
                conversation_id = requested_cid or generate_conversation_id()
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

            # RBAC context for in-pipeline nodes (control/alert/preference),
            # mirroring the /chat endpoint. Proxy-mode identity is untrusted →
            # readonly, so privileged actions are declined unless a real user
            # session authorizes them.
            state.user_id = auth["username"]
            state.intermediate_results["user_id"] = auth["username"]
            state.intermediate_results["user_role"] = auth["role"]

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
                    "sources": final_state.intermediate_results.get("sources", []),
                    "evidence": final_state.intermediate_results.get("evidence_dossier"),
                    "evidence_record": final_state.intermediate_results.get("evidence_record"),
                    "clarification": final_state.intermediate_results.get(
                        "needs_clarification_payload"
                    ),
                    "plan_trace": final_state.intermediate_results.get("plan_trace"),
                }
            )

            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except Exception:
            pass  # WebSocket may already be closed
    finally:
        connection_manager.unregister(websocket)


@app.get("/conversation/{conversation_id}", response_model=APIResponse)
async def get_conversation(
    conversation_id: str,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Get conversation history"""
    if not _user_owns_conversation(user, conversation_id):
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        messages = await redis_manager.get_messages(conversation_id)

        return APIResponse(
            success=True,
            data={
                "conversation_id": conversation_id,
                "messages": messages,
                "count": len(messages),
            },
        )

    except Exception as e:
        logger.error(f"Get conversation error: {e}")
        return APIResponse(success=False, error=str(e))


@app.delete("/conversation/{conversation_id}", response_model=APIResponse)
async def delete_conversation(
    conversation_id: str,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Delete conversation"""
    if not _user_owns_conversation(user, conversation_id):
        raise HTTPException(status_code=403, detail="Access denied")
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


@app.get("/jobs/{job_id}", response_model=APIResponse)
async def get_job_status(
    job_id: str,
    user: UserContext = Depends(require_permission("report:read")),
):
    """Poll the status of a background job (created when a long-running report is queued)."""
    if job_queue is None:
        return APIResponse(success=False, error="Job queue not initialised")
    job = await job_queue.get_job(job_id)
    if job is None:
        return APIResponse(
            success=False,
            error=f"Job {job_id!r} not found or expired (TTL: 1 hour)",
        )
    return APIResponse(success=True, data=job)


class PreferencesRequest(BaseModel):
    """Validated body for POST /preferences."""

    conversation_id: str = Field(..., min_length=1, max_length=200)
    persona: Optional[str] = Field(default=None, max_length=100)
    language: Optional[str] = Field(default=None, max_length=10)
    building: Optional[str] = Field(default=None, max_length=100)


@app.post("/preferences", response_model=APIResponse)
async def update_preferences(
    body: PreferencesRequest,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Update user preferences (auth required; owner-scoped conversation)."""
    try:
        conversation_id = body.conversation_id
        if not _user_owns_conversation(user, conversation_id):
            raise HTTPException(status_code=403, detail="Cannot modify another user's preferences")

        preferences = {
            "persona": body.persona,
            "language": body.language,
            "building": body.building,
        }
        preferences = {k: v for k, v in preferences.items() if v is not None}

        await redis_manager.save_user_preferences(conversation_id, preferences)

        return APIResponse(success=True, data={"preferences": preferences})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update preferences error: {e}")
        return APIResponse(success=False, error=str(e))


# ==================== Report Generation ====================


class ReportRequest(BaseModel):
    """Validated body for POST /api/v1/report."""

    report_type: str = Field(default="summary", max_length=50)
    output_format: str = Field(default="html", max_length=10)
    persona: str = Field(default="general", max_length=100)
    building_id: Optional[str] = Field(default=None, max_length=100)
    title: Optional[str] = Field(default=None, max_length=300)
    date_range: Dict[str, Any] = Field(default_factory=dict)


@app.post("/api/v1/report")
async def generate_report(
    body: ReportRequest,
    user: UserContext = Depends(require_permission("report:read")),
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
        username = user.username
        report_type = body.report_type
        output_format = body.output_format
        persona = body.persona
        building_id = body.building_id or settings.BUILDING_ID
        title = body.title
        date_range = body.date_range

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


async def _rehydrate_prior_messages(
    conversation_id: str,
    prior_messages: List["Message"],
    max_history: int,
) -> List["Message"]:
    """Rehydrate conversation history from server state when the client sent none.

    OpenWebUI echoes the full message array each turn, so `prior_messages`
    (reconstructed from the request) already carries history and is returned
    unchanged. But a custom chat UI, the /stream WebSocket, or a plain API
    caller may send ONLY the current message — leaving `prior_messages` empty
    and breaking follow-ups ("is that ok?", "humidity there?"). In that case we
    load the persisted conversation state so co-reference still resolves.

    Additive and side-effect-free: skipped whenever the client supplied
    history; `save_state` later re-persists the merged list so it accumulates
    across turns. Never raises — a memory miss degrades to no history.
    """
    if prior_messages:
        return prior_messages
    try:
        _prev_state = await redis_manager.load_state(conversation_id)
        if _prev_state and _prev_state.messages:
            rehydrated = list(_prev_state.messages)[-max_history:]
            logger.info(
                f"[/v1/chat/completions] rehydrated {len(rehydrated)} prior "
                "turn(s) from server memory (client sent no history)"
            )
            return rehydrated
    except Exception as _re:
        logger.debug(f"[/v1/chat/completions] server-memory rehydrate skipped: {_re}")
    return prior_messages


@app.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    _: None = Depends(_oai_auth),
):
    """
    OpenAI-compatible endpoint for Open WebUI integration.
    Allows Open WebUI to use the OntoSage pipeline as a backend.

    Requires a valid bearer key (PIPELINE_API_KEY) enforced via the
    `_oai_auth` dependency — Open WebUI sends it as OPENAI_API_KEY.
    """
    try:
        # V5-BUG-177: record LLM faults for THIS turn so the reply can declare
        # whether it is behaviour or the wreckage of an outage/quota refusal.
        begin_llm_trace()

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
                status_code=400,
                detail=f"Message too long (max {CHAT_MAX_MESSAGE_LENGTH} chars)",
            )
        if not user_message:
            raise HTTPException(status_code=400, detail="Message is empty after sanitization")

        # Use X-Chat-Id header (sent by Open WebUI) for a stable, session-scoped
        # conversation_id so turn_memory and Redis intermediate_results (e.g.
        # forecast_result) persist across turns.  Without this, a new UUID was
        # generated every request, preventing cross-turn carry-forward.
        chat_id_header = request.headers.get("X-Chat-Id") or request.headers.get("x-chat-id")
        if chat_id_header:
            conversation_id = f"owui_{chat_id_header}:{username}"
        else:
            # Stable fallback: SHA-256 of first user message content.
            # Python's builtin hash() is salted per process (PYTHONHASHSEED),
            # so the old abs(hash(...)) id changed on every orchestrator
            # restart and silently severed conversation memory (P1.10 fix).
            first_content = messages[0].get("content", "") if messages else user_message
            _digest = hashlib.sha256(first_content.encode("utf-8")).hexdigest()[:16]
            conversation_id = f"owui_{_digest}:{username}"

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
                    status_code=400,
                    detail="Message is empty after stripping persona prefix",
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
                prior_messages.append(Message(role=role, content=content, timestamp=datetime.now()))
        prior_messages = prior_messages[-max_history:]

        # Server-side history rehydration (robustness for minimal clients).
        prior_messages = await _rehydrate_prior_messages(
            conversation_id, prior_messages, max_history
        )

        # Carry-forward (forecast/analytics artifacts from the previous turn) is
        # loaded below via TurnMemoryService once `state` exists; start empty here.
        state = ConversationState(
            conversation_id=conversation_id,
            user_message=user_message,
            messages=prior_messages,
            building_id=data.get("building_id", settings.BUILDING_ID),
            persona=req_persona,
            user_id=username,
            intermediate_results={},
        )
        # RBAC context for workflow agents. /v1 callers share ONE pipeline key, so by
        # default they are pinned to least-privilege readonly (P0.7). When the proxy is
        # trusted (TRUST_FORWARDED_USER) it also forwards WHO is signed in, and that
        # account's real OntoSage role applies — so an analyst and a visitor asking the
        # same question get answers scoped to their own access, and control:write paths
        # open only for roles that actually hold the permission.
        _fwd_user, _fwd_role = await resolve_forwarded_user(request)
        if _fwd_role != "readonly" or _fwd_user != "openwebui_user":
            username = _fwd_user
            state.user_id = _fwd_user
        state.intermediate_results["user_id"] = username
        state.intermediate_results["user_role"] = _fwd_role

        logger.info(
            f"[persona-detect] explicit={explicit_persona!r} → resolved={req_persona!r}"
            + (" (prefix stripped)" if stripped_message else "")
        )
        logger.info(f"[/v1/chat/completions] loaded {len(prior_messages)} prior turns into state")

        # Turn memory service — wraps the Postgres pool for per-turn summaries
        from orchestrator.services.turn_memory import TurnMemoryService as _TMS

        _turn_memory = _TMS(pool=postgres_manager.pool if postgres_manager else None)

        # Carry forward forecast/analytics artifacts from the previous turn.
        # Primary source: Postgres turn_memory (persistent across Redis restarts).
        # Fallback: Redis hot-cache (same session, faster path).
        carry_forward: dict = {}
        try:
            carry_forward = await _turn_memory.get_carry_forward(conversation_id)
            if not carry_forward:
                _prev = await redis_manager.load_state(conversation_id)
                if _prev and _prev.intermediate_results:
                    _cf_keys = {"forecast_result", "analytics_result"}
                    carry_forward = {
                        k: v for k, v in _prev.intermediate_results.items() if k in _cf_keys
                    }
            if carry_forward:
                logger.info(
                    "[/v1/chat/completions] carry-forward loaded: " f"{list(carry_forward.keys())}"
                )
        except Exception as _ce:
            logger.debug(f"[/v1/chat/completions] carry-forward skipped: {_ce}")

        if carry_forward:
            state.intermediate_results.update(carry_forward)

        # Inject older turn summaries as system-context prefix for long-term memory
        older_context = ""
        try:
            older_context = await _turn_memory.get_older_context(
                conversation_id,
                skip_recent=settings.CONVERSATION_MAX_MESSAGES,
            )
        except Exception as _oe:
            logger.debug(f"[/v1/chat/completions] older_context skipped: {_oe}")

        # Prepend older turn summaries as system message for long-term memory
        if older_context:
            state.messages.insert(
                0,
                Message(role="system", content=older_context, timestamp=datetime.now()),
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

                # Stream pipeline progress LIVE inside a collapsible <details>
                # block as each node runs, so Open WebUI shows an updating panel
                # during processing instead of a blank screen until the pipeline
                # finishes.  The block is opened on the first step and closed
                # before the answer streams — matching ChatGPT / Claude UX.
                last_step = None
                details_open = False
                seen_status = set()
                # Immediate first-byte acknowledgment: the first pipeline node
                # (intent analysis) can take several seconds, so show activity
                # within ~1s instead of a blank panel until it completes.
                if show_status:
                    yield sse_chunk(content="<details>\n<summary>Pipeline steps</summary>\n\n")
                    yield sse_chunk(content="- Analyzing your question…\n")
                    details_open = True
                    seen_status.add("Analyzing intent")  # dialogue node won't re-add
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
                    elif "floor_plan" in step:
                        status = "🗺️ Resolving floor plan"
                    if status and status not in seen_status:
                        seen_status.add(status)
                        if not details_open:
                            yield sse_chunk(
                                content="<details>\n<summary>Pipeline steps</summary>\n\n"
                            )
                            details_open = True
                        yield sse_chunk(content=f"- {status}\n")

                # Close the live progress panel before the answer streams
                if details_open:
                    yield sse_chunk(content="\n</details>\n\n")

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

                # Persist state to Redis so the next turn can carry forward
                # intermediate_results (e.g. forecast_result for viz requests)
                try:
                    await redis_manager.save_state(final_state)
                except Exception as _rse:
                    logger.debug(f"[/v1/chat/completions] Redis save skipped: {_rse}")

                # Save to Postgres if available
                if postgres_manager and postgres_manager.pool:
                    if username not in _pipeline_users_created:
                        await postgres_manager.create_user(
                            username,
                            "placeholder_hash",
                            "placeholder_salt",
                            metadata={"source": "open_webui"},
                            role="readonly",  # external identity — cannot log in, least-privilege
                        )
                        _pipeline_users_created.add(username)
                    await postgres_manager.save_message(
                        conversation_id, "user", user_message, username
                    )
                    await postgres_manager.save_message(
                        conversation_id, "assistant", assistant_message, username
                    )

                # Persist structured turn summary to Postgres for long-term memory
                try:
                    await _turn_memory.save_turn(final_state)
                except Exception as _tse:
                    logger.debug(f"[/v1/chat/completions] turn_memory save skipped: {_tse}")

                # Stream final response in chunks (helps UI show gradual output)
                chunk_size = 200
                for i in range(0, len(assistant_message), chunk_size):
                    yield sse_chunk(content=assistant_message[i : i + chunk_size])

                # Finalize stream
                yield sse_chunk(finish_reason="stop")
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")

        # Non-streaming: Execute workflow (with per-request timeout to prevent cascade failures)
        try:
            updated_state = await asyncio.wait_for(
                orchestrator.execute(state), timeout=float(settings.REQUEST_TIMEOUT_SECS)
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"[/v1/chat/completions] Pipeline timed out after {settings.REQUEST_TIMEOUT_SECS}s: "
                f"{user_message[:80]!r}"
            )
            return {
                "id": f"chatcmpl-{conversation_id}",
                "object": "chat.completion",
                "created": int(datetime.now().timestamp()),
                "model": data.get("model", "ontobot-pipeline"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Your request took too long to process. "
                                "Please try a simpler question or try again later."
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                # This apology is not an answer — never let a grader score it.
                "ontosage_llm_degraded": {
                    "failed_calls": 1,
                    "causes": ["pipeline_timeout"],
                    "rate_limited": False,
                    "detail": f"pipeline exceeded {settings.REQUEST_TIMEOUT_SECS}s",
                },
            }

        assistant_message = (
            updated_state.messages[-1].content
            if updated_state.messages
            else "No response generated"
        )

        # Persist state to Redis (non-streaming path)
        try:
            await redis_manager.save_state(updated_state)
        except Exception as _rse:
            logger.debug(f"[/v1/chat/completions] Redis save skipped: {_rse}")

        if postgres_manager and postgres_manager.pool:
            if username not in _pipeline_users_created:
                await postgres_manager.create_user(
                    username,
                    "placeholder_hash",
                    "placeholder_salt",
                    metadata={"source": "open_webui"},
                    role="readonly",  # external identity — cannot log in, least-privilege
                )
                _pipeline_users_created.add(username)
            await postgres_manager.save_message(conversation_id, "user", user_message, username)
            await postgres_manager.save_message(
                conversation_id, "assistant", assistant_message, username
            )

        try:
            await _turn_memory.save_turn(updated_state)
        except Exception as _tse:
            logger.debug(f"[/v1/chat/completions] turn_memory save skipped: {_tse}")

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
            # None when the LLM behaved; a cause summary when it refused/timed out.
            # OpenAI clients ignore unknown fields; graders quarantine on it.
            "ontosage_llm_degraded": llm_degradation(),
            # V6-T02: the evidence record, on this endpoint too. It was on /chat and the
            # websocket but not here, and this is the endpoint Open WebUI and every
            # OpenAI-compatible client actually use -- so the answers most people see
            # carried no statement of what they rest on. Same extension-field convention as
            # ontosage_llm_degraded above: unknown fields are ignored by OpenAI clients, so
            # adding it cannot break a consumer.
            "ontosage_evidence_record": updated_state.intermediate_results.get("evidence_record"),
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
async def download_export(
    filename: str,
    user: UserContext = Depends(require_permission("export:read")),
):
    """D.2: Download a previously generated export file (CSV, JSON, HTML, Markdown)."""
    import re as _re

    from fastapi.responses import FileResponse

    # Sanitise: allow alphanum, dash, underscore, dot only (no spaces to block traversal)
    if not _re.match(r"^[\w\-.]+$", filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = os.path.join(settings.EXPORTS_DIR, filename)
    # Resolve symlinks/.. and confirm the result is still inside EXPORTS_DIR
    exports_root = os.path.realpath(settings.EXPORTS_DIR)
    if not os.path.realpath(file_path).startswith(exports_root + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"Export file '{filename}' not found")
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


# ── Floor Plan endpoints ───────────────────────────────────────────────────────


@app.get("/floor-plans/")
async def list_floor_plans(current_user: Optional[str] = Depends(get_current_user)):
    """List all available floor plan PDFs for the active building."""
    floors = floor_plan_service.get_available_floors()
    return {
        "floors": [
            {
                "floor": f,
                "pdf_url": floor_plan_service.get_pdf_url(f),
                "filename": (
                    floor_plan_service.get_pdf_path(f).name
                    if floor_plan_service.get_pdf_path(f)
                    else None
                ),
            }
            for f in floors
        ],
        "total": len(floors),
    }


@app.get("/floor-plans/floor-{floor_num}.pdf")
async def serve_floor_plan_pdf(
    floor_num: int,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Serve the floor plan PDF for a specific floor."""
    from fastapi.responses import FileResponse

    pdf_path = floor_plan_service.get_pdf_path(floor_num)
    if pdf_path is None or not pdf_path.exists():
        available = floor_plan_service.get_available_floors()
        raise HTTPException(
            status_code=404,
            detail=f"Floor plan for floor {floor_num} not found. Available: {available}",
        )
    return FileResponse(
        path=str(pdf_path),
        filename=pdf_path.name,
        media_type="application/pdf",
    )


# ── Phase 9: Floor Plan Standardization API (/api/v1/floor-plans/) ──────────────
#
# All endpoints below are manifest-aware and building-agnostic.
# The legacy /floor-plans/ endpoints above are kept as-is for backwards compat.


@app.get("/api/v1/floor-plans", response_model=APIResponse)
async def list_floor_plan_manifests(
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """List all buildings + floors with their manifest status."""
    try:
        from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline

        pipeline = get_floor_plan_pipeline()
        result = []
        for building_id, floor in pipeline.list_manifests():
            manifest = pipeline.load_manifest(building_id, floor)
            result.append(
                {
                    "building_id": building_id,
                    "building_name": manifest.building_name if manifest else building_id,
                    "floor": floor,
                    "floor_label": manifest.floor_label if manifest else f"Floor {floor}",
                    "manifest_url": f"/api/v1/floor-plans/{building_id}/{floor}/manifest",
                    "image_url": manifest.rendered_image.png_url if manifest else None,
                    "thumbnail_url": manifest.rendered_image.thumbnail_url if manifest else None,
                    "pdf_url": manifest.pdf_url if manifest else None,
                    "spaces_count": len(manifest.spaces) if manifest else 0,
                    "generated_at": manifest.generated_at.isoformat() if manifest else None,
                    "warnings_count": len(manifest.warnings) if manifest else 0,
                }
            )
        return APIResponse(success=True, data={"floors": result, "total": len(result)})
    except Exception as e:
        logger.error(f"list_floor_plan_manifests failed: {e}")
        return APIResponse(success=False, error=str(e), data={"floors": [], "total": 0})


@app.get("/api/v1/admin/index-status", response_model=APIResponse)
@app.get("/api/v1/admin/capability-indexer/status", response_model=APIResponse)
async def index_status(
    user: UserContext = Depends(require_permission("system:health")),
):
    """What the building currently has indexed, per subsystem.

    This used to report the capability.yaml Qdrant KB. That KB is gone
    (TODO-012/TODO-081) — structured capability facts are now
    ``ontosage:Amenity`` / ``ontosage:KnowledgeTopic`` triples in the ontology,
    and free prose lives in the document index. So the view reports the two
    things that actually exist, which is what an admin needs before asking why
    a question went unanswered:

    * **documents** — per-building result of the last document ingestion,
      the path behind a prose answer from an uploaded manual or policy.
    * **capabilities** — how many Amenity / KnowledgeTopic subjects the graph
      holds. Zero here with a capability question failing means the TTL was
      never loaded, not that the query was misunderstood.
    * **embedding** — provider and dimension. A collection written under a
      different model is unusable and returns nothing rather than raising, so
      the width belongs on the same screen as the counts.

    The legacy ``/capability-indexer/status`` path is kept as an alias so
    existing dashboards and integration tests keep working. Read-only.
    """
    try:
        embedder = getattr(app.state, "embedding_service", None)
        doc_indexer = getattr(app.state, "doc_indexer", None)
        doc_results = getattr(app.state, "doc_index_results", None) or {}

        documents = {}
        for bldg_id, result in doc_results.items():
            documents[bldg_id] = {
                "status": getattr(result, "status", None),
                "documents": getattr(result, "documents", None),
                "chunks": getattr(result, "chunks", None),
                "reason": getattr(result, "reason", None),
            }

        # Capability triples — counted live, never cached, so the number is the
        # graph's and not a boot-time snapshot that a later TTL upload invalidated.
        capabilities: Dict[str, Any] = {"available": False}
        try:
            # Import the resolver's OWN prefix rather than restating the IRI:
            # a count that silently disagrees with the resolver's namespace
            # would report 0 amenities for a building that has them.
            from orchestrator.services.capability_graph_resolver import (
                _ONTO,
                _default_sparql_exec,
            )

            data = await _default_sparql_exec(
                _ONTO + "SELECT ?kind (COUNT(DISTINCT ?s) AS ?n) WHERE { "
                "  { ?s a ontosage:Amenity . BIND('amenity' AS ?kind) } UNION "
                "  { ?s a ontosage:KnowledgeTopic . BIND('knowledge_topic' AS ?kind) } "
                "} GROUP BY ?kind"
            )
            counts = {
                b.get("kind", {}).get("value", ""): int(b.get("n", {}).get("value", 0))
                for b in (data.get("results", {}).get("bindings", []) or [])
            }
            capabilities = {
                "available": True,
                "amenities": counts.get("amenity", 0),
                "knowledge_topics": counts.get("knowledge_topic", 0),
            }
        except Exception as cap_err:  # graph unreachable — say so, do not report 0
            logger.warning(f"[index_status] capability triple count unavailable: {cap_err}")
            capabilities = {"available": False, "reason": str(cap_err)}

        return APIResponse(
            success=True,
            data={
                "documents_ready": doc_indexer is not None,
                "documents": documents,
                "capabilities": capabilities,
                "embedding_provider": embedder.provider if embedder else None,
                "embedding_dimension": embedder.dimension if embedder else None,
                # Retained so older dashboards reading these keys do not break;
                # the capability KB they described no longer exists.
                "indexer_ready": doc_indexer is not None,
                "router_ready": False,
                "router_intents": [],
                "buildings": documents,
            },
        )
    except Exception as e:
        logger.error(f"index_status failed: {e}")
        return APIResponse(success=False, error=str(e), data={})


# ---------------------------------------------------------------------------
# Admin — Ontology manager (named-graph CRUD + SPARQL browser) — Task 3
# ---------------------------------------------------------------------------


class TtlUpload(BaseModel):
    ttl: str = Field(..., min_length=1, description="Turtle text to upload")
    graph_uri: str = Field(
        ...,
        min_length=5,
        description="Named graph URI — e.g. urn:ontosage:ttl:my_extension.ttl",
    )
    replace: bool = Field(
        default=False,
        description=(
            "False (default) appends triples to the graph, preserving existing "
            "ones. True replaces the ENTIRE graph (deletes existing triples)."
        ),
    )


class SparqlBrowserQuery(BaseModel):
    query: str = Field(..., min_length=5, description="A SPARQL SELECT or ASK query")
    limit: int = Field(default=100, ge=1, le=500)


class TtlValidate(BaseModel):
    ttl: str = Field(..., min_length=1, description="Turtle text to validate (no network call)")


class ReindexRequest(BaseModel):
    targets: List[str] = Field(
        default=["capability"], description="capability | documents | floor_plans"
    )
    building_id: Optional[str] = Field(default=None)


class CapabilityCreate(BaseModel):
    """Guided capability-amenity form. Fields become a dual-typed ontosage:Amenity
    instance on the active building's namespace (no hand-written Turtle)."""

    id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Local name for the amenity, e.g. 'PrayerRoom_104' (letters/digits/_.-)",
    )
    type: str = Field(
        ..., description="Amenity class, e.g. PrayerRoom / Cafe / Lift (from the whitelist)"
    )
    label: str = Field(..., min_length=1, max_length=200, description="Human-readable name")
    location: str = Field(default="", max_length=300, description="Free-text location")
    floor: str = Field(default="", max_length=60, description="Floor label, e.g. '1' or 'Ground'")
    category: str = Field(default="", max_length=100, description="Capability category")
    lay_terms: str = Field(
        default="", max_length=300, description="Comma-separated lay terms, e.g. 'coffee, cafe'"
    )
    note: str = Field(default="", max_length=1000, description="Optional free-text note")
    # Knowledge-topic fields (used when type is a Procedure / InformationTopic / MaintenanceIssue).
    answer_text: str = Field(default="", max_length=1000, description="Canonical one-line answer")
    info_url: str = Field(default="", max_length=500, description="URL for more information")
    contact_email: str = Field(default="", max_length=200, description="Contact email")
    contact_phone: str = Field(default="", max_length=100, description="Contact phone")
    report_to: str = Field(default="", max_length=300, description="Where/whom to report to")
    steps: str = Field(
        default="", max_length=1000, description="How-to steps (semicolon-separated)"
    )
    opening_hours: str = Field(default="", max_length=200, description="Opening hours (free text)")
    priority: str = Field(default="", max_length=40, description="Default priority for an issue")
    building_id: Optional[str] = Field(default=None)


@app.get("/api/v1/admin/ontology/graphs", response_model=APIResponse)
async def list_ontology_graphs(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """List all named graphs in GraphDB with their triple counts."""
    from orchestrator.services.ontology_manager import list_named_graphs

    graphs = await list_named_graphs()
    return APIResponse(success=True, data={"graphs": graphs, "total": len(graphs)})


@app.get("/api/v1/admin/observability/matrix", response_model=APIResponse)
async def observability_matrix(
    modality: Optional[str] = None,
    floor: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 300,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """What this building can observe, cell by cell (V6-T11).

    The same coverage schema and the same ``Reach`` the conversational
    observability lane answers from — not a second computation of the same idea.
    Two copies of one measurement drift, and this codebase has paid for that
    (BUG-210); a portal that disagreed with the chat answer would be worse than no
    portal, because it would look authoritative while contradicting the system.

    Every negative carries the step that would change it, because that is what the
    lane's ``describe()`` was written to produce and it is the only part of a
    coverage matrix an operator can act on.

    Bounded on purpose: bldg1 is ~344 spaces by ~35 modalities, so the full cross
    product is twelve thousand cells. The summary is always complete and the cell
    list is truncated with the count said out loud — a list that silently stops
    reads as the whole picture.
    """
    from orchestrator.services.deliberation.capability_schema import build_schema
    from orchestrator.services.deliberation.coverage_audit import load_modalities
    from orchestrator.services.deliberation.live import sparql_exec
    from orchestrator.services.observability import (
        present_modalities,
        reach_from_coverage,
    )

    building_id = settings.BUILDING_ID
    namespace = settings.BUILDING_NAMESPACE
    specs = load_modalities(building_id)
    schema = await build_schema(building_id, namespace, sparql_exec, specs)

    by_status: Dict[str, int] = {}
    per_modality: Dict[str, Dict[str, int]] = {}
    cells: List[Dict[str, Any]] = []
    total = 0

    wanted_modality = (modality or "").strip().lower()
    wanted_floor = (floor or "").strip().lower()
    wanted_status = (status or "").strip().lower()

    for sc in schema.spaces:
        local = sc.space_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        space_floor = str(getattr(sc, "floor", "") or "")
        if wanted_floor and wanted_floor not in space_floor.lower():
            continue
        present = present_modalities(sc.modalities or {})
        for spec in specs:
            if wanted_modality and spec.name.lower() != wanted_modality:
                continue
            entry = (sc.modalities or {}).get(spec.name)
            reach = reach_from_coverage(spec.name, local, entry, present_modalities=present)
            total += 1
            by_status[reach.status] = by_status.get(reach.status, 0) + 1
            slot = per_modality.setdefault(spec.name, {})
            slot[reach.status] = slot.get(reach.status, 0) + 1
            if wanted_status and reach.status != wanted_status:
                continue
            if len(cells) < max(1, min(int(limit or 300), 2000)):
                cells.append(
                    {
                        "space": local,
                        "floor": space_floor,
                        "modality": spec.name,
                        "status": reach.status,
                        "sensor": reach.sensor,
                        "stored_at": reach.stored_at,
                        "fresh": reach.fresh,
                        # The unlock step, from the lane's own prose. An operator can
                        # act on "the wiring is already in place, check the feed";
                        # they cannot act on the word "stale".
                        "note": reach.describe(),
                    }
                )

    shown = len(cells)
    matched = total if not wanted_status else by_status.get(wanted_status, 0)
    return APIResponse(
        success=True,
        data={
            "building_id": building_id,
            "modalities": [s.name for s in specs],
            "spaces": len(schema.spaces),
            "cells_total": total,
            "cells_matching": matched,
            "cells_shown": shown,
            "truncated": max(0, matched - shown),
            "by_status": by_status,
            "per_modality": per_modality,
            "cells": cells,
        },
    )


@app.get("/api/v1/admin/observability/calibration", response_model=APIResponse)
async def observability_calibration(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Calibration state per point, and what the evidence gate makes of it.

    Read through ``assemble._calibration_state`` rather than re-deriving the
    comparison here: the gate that suppresses an answer and the panel that explains
    why must agree about what "expired" means, or the portal teaches an operator the
    wrong thing about their own building.

    A point with no calibration record is 'unknown', never an assumed-good default.
    """
    from datetime import datetime, timezone

    from orchestrator.services.evidence.assemble import _calibration_state

    query = (
        "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "SELECT ?p ?uuid ?on ?due ?method WHERE {\n"
        "  ?p ontosage:calibratedOn ?on .\n"
        "  OPTIONAL { ?p ontosage:calibrationDueOn ?due }\n"
        "  OPTIONAL { ?p ontosage:calibrationMethod ?method }\n"
        "  OPTIONAL { ?p ref:hasExternalReference/ref:hasTimeseriesId ?uuid }\n"
        "} LIMIT 2000"
    )
    try:
        from orchestrator.services.deliberation.live import sparql_exec

        res = await sparql_exec(query)
        rows = (res or {}).get("rows") or []
    except Exception as exc:
        logger.warning(f"[observability] calibration lookup failed: {exc}")
        return APIResponse(
            success=False,
            error=f"calibration records could not be read: {exc}",
            data={"records": [], "by_state": {}},
        )

    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    by_state: Dict[str, int] = {}
    for row in rows:
        get = row.get if isinstance(row, dict) else (lambda k: getattr(row, k, None))
        # The KEYS matter: _calibration_state reads "due_on", not
        # "calibration_due_on". Passing the wrong name would make every record read
        # as calibrated-or-unknown and never expired -- the panel would then show a
        # clean building while the gate suppressed answers, which is worse than no
        # panel. Same class of defect as the sparql_result/sparql_results drift.
        entry = {
            "calibrated_on": str(get("on") or ""),
            "due_on": str(get("due") or ""),
        }
        state = _calibration_state(entry, now)
        by_state[state] = by_state.get(state, 0) + 1
        out.append(
            {
                "point": str(get("p") or "").rsplit("#", 1)[-1],
                "uuid": str(get("uuid") or ""),
                "calibrated_on": entry["calibrated_on"][:10],
                "calibration_due_on": entry["due_on"][:10],
                "method": str(get("method") or ""),
                "state": state,
            }
        )
    out.sort(key=lambda r: (r["state"] != "expired", r["point"]))
    return APIResponse(
        success=True,
        data={
            "records": out,
            "by_state": by_state,
            "note": (
                "Points with no calibration record do not appear here and are treated as "
                "'unknown' by the gate, never as calibrated."
            ),
        },
    )


@app.get("/api/v1/admin/actuation/log", response_model=APIResponse)
async def read_actuation_audit_log(
    limit: int = 50,
    since_hours: Optional[float] = None,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """The record of control actions this system has taken.

    Every approved set_point writes an audit row, and nothing read one back until
    2026-08-27: "what did you change today?" and "who approved that?" were
    unanswerable about actions the system had itself recorded. bldg1 ships with
    actuation.driver: sim and three writable points, so the path is live.

    Admin-gated because an audit trail is accountability surface, and read-only —
    nothing in this path amends a row.
    """
    from orchestrator.services.actuation import format_actions, read_actuation_log

    result = await read_actuation_log(
        settings.BUILDING_ID,
        postgres_manager=postgres_manager,
        limit=limit,
        since_hours=since_hours,
    )
    result["summary"] = format_actions(result)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


@app.post("/api/v1/admin/ontology/validate", response_model=APIResponse)
async def validate_ttl_endpoint(
    body: TtlValidate,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Parse + validate Turtle text (no GraphDB write). Returns triple count + prefix list."""
    from orchestrator.services.ontology_manager import validate_ttl_text

    result = validate_ttl_text(body.ttl)
    return APIResponse(success=result["ok"], error=result.get("error"), data=result)


@app.post("/api/v1/admin/ontology/upload", response_model=APIResponse)
async def upload_ontology_ttl(
    body: TtlUpload,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Upload a Brick TTL into a named graph. Appends by default; set
    ``replace=true`` to overwrite the whole graph (deletes existing triples).

    When the target graph is a file graph (``urn:ontosage:ttl:<file>``) the TTL is also
    persisted to ``input/<file>`` (the source of truth) so it survives a GraphDB volume
    reset and reloads on restart. Non-file graphs (e.g. ``urn:ontosage:custom:*``) are
    written to GraphDB only and flagged as not-persisted in the response."""
    from orchestrator.services.input_ttl_store import (
        conflicting_input_file,
        filename_from_graph_uri,
        graph_uri_for_filename,
        persist_ttl_file,
    )
    from orchestrator.services.ontology_manager import upload_ttl, validate_ttl_text

    filename = filename_from_graph_uri(body.graph_uri)
    if filename:
        # File graph: validate first, then write the file + sync its graph.
        v = validate_ttl_text(body.ttl)
        if not v["ok"]:
            return APIResponse(success=False, error=v.get("error"), data=v)
        result = await persist_ttl_file(filename, body.ttl, merge=not body.replace)
        result["persisted"] = True
        if result.get("ok"):
            _enqueue_similarity_rebuild(result)  # new triples → refresh semantic RAG index
        return APIResponse(
            success=bool(result.get("ok")),
            error=None if result.get("ok") else "graph sync failed",
            data=result,
        )

    # A hand-named graph whose local name matches a file in input/ becomes a SECOND
    # copy of that file the next time the boot uploader discovers it (BUG-250), and
    # every joined point then comes back twice. Refuse, and name the graph to use.
    clash = conflicting_input_file(body.graph_uri)
    if clash:
        return APIResponse(
            success=False,
            error=(
                f"'{body.graph_uri}' would duplicate input/{clash}: the boot uploader "
                f"loads that file into its own graph, so the building would hold both "
                f"copies and every joined point would be returned twice. Upload into "
                f"'{graph_uri_for_filename(clash)}' instead — that graph IS the file, "
                f"so the upload updates it rather than shadowing it."
            ),
            data={"graph": body.graph_uri, "conflicts_with": clash, "persisted": False},
        )

    result = await upload_ttl(body.ttl, body.graph_uri, replace=body.replace)
    result["persisted"] = False
    result["note"] = (
        "Written to GraphDB only. Use a 'urn:ontosage:ttl:<filename>' graph to also "
        "persist it to input/ (survives volume reset + restart)."
    )
    if result.get("ok"):
        _enqueue_similarity_rebuild(result)  # new triples → refresh semantic RAG index
        # V5-T39: uploaded TTL may carry AccessPolicy triples — refresh the PDP
        if "AccessPolicy" in (body.ttl or ""):
            try:
                from orchestrator.services.privacy.enforcement import reload_policies

                n_policies = await reload_policies()
                result["policies_reloaded"] = n_policies
                logger.info(f"[protect] policies reloaded after TTL upload: {n_policies}")
            except Exception as _rp_err:
                logger.warning(f"[protect] policy reload after upload failed: {_rp_err}")
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


@app.delete("/api/v1/admin/ontology/graphs/{graph_id:path}", response_model=APIResponse)
async def drop_ontology_graph(
    graph_id: str,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Delete a named graph from GraphDB. For a file graph (``urn:ontosage:ttl:<file>``)
    the backing ``input/<file>`` is MOVED to input/.trash/ (reversible) so the drop stays
    applied after restart; otherwise only the GraphDB triples are removed."""
    from orchestrator.services.input_ttl_store import (
        filename_from_graph_uri,
        trash_ttl_file,
    )
    from orchestrator.services.ontology_manager import drop_named_graph

    filename = filename_from_graph_uri(graph_id)
    if filename:
        result = await trash_ttl_file(filename)
        return APIResponse(
            success=bool(result.get("dropped")),
            data={
                "graph": graph_id,
                "dropped": result.get("dropped"),
                "trashed_to": result.get("trashed_to"),
            },
        )

    ok = await drop_named_graph(graph_id)
    return APIResponse(success=ok, data={"graph": graph_id, "dropped": ok})


@app.post("/api/v1/admin/ontology/sparql", response_model=APIResponse)
async def admin_sparql_browser(
    body: SparqlBrowserQuery,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Execute a read-only SPARQL SELECT/ASK query (admin SPARQL browser)."""
    from orchestrator.services.ontology_manager import run_sparql_select

    result = await run_sparql_select(body.query, limit=body.limit)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


# ---------------------------------------------------------------------------
# Admin — Guided capability authoring (TODO-014)
#
# CRUD over ontosage:Amenity instances so an admin adds a building capability
# ("there is a prayer room on floor 1") as live triples, without hand-writing
# Turtle or touching capability.yaml. Writes persist to input/<bldg>_capabilities.ttl
# (source of truth) and re-sync its graph, so the CapabilityGraphResolver answers them
# immediately AND they survive a restart / GraphDB volume reset.
# ---------------------------------------------------------------------------


@app.get("/api/v1/admin/capabilities", response_model=APIResponse)
async def list_capabilities(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """List every ontosage:Amenity instance (file-loaded + GUI-authored). The ``types`` list that
    drives the guided dropdown is DERIVED FROM THE OCBV SCHEMA in GraphDB (subclasses of
    ontosage:Amenity / ontosage:KnowledgeTopic), so a class added to input/ontosage_schema.ttl
    appears in the dropdown with no code change (falls back to the built-in list if GraphDB is down).
    """
    from orchestrator.services.capability_admin import (
        get_capability_classes,
        get_capability_form_schema,
        list_amenities,
    )

    rows = await list_amenities()
    classes = await get_capability_classes()
    form_fields = await get_capability_form_schema()
    return APIResponse(
        success=True,
        data={
            "amenities": rows,
            "total": len(rows),
            "types": classes["all"],
            "types_by_kind": {"amenity": classes["amenity"], "knowledge": classes["knowledge"]},
            "types_source": classes["source"],
            # Schema-derived form fields (label/help/domain per ontosage: datatype property) — the
            # console renders only those whose domain applies to the selected type.
            "form_fields": form_fields,
        },
    )


@app.post("/api/v1/admin/capabilities", response_model=APIResponse)
async def create_capability(
    body: CapabilityCreate,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Create a capability amenity from guided form fields (built into Turtle, validated,
    persisted to input/<bldg>_capabilities.ttl + its graph re-synced). Flushes the response
    cache so the new capability is answerable on the next question."""
    from orchestrator.services.capability_admin import create_amenity

    bid = body.building_id or settings.BUILDING_ID
    fields = body.model_dump(exclude={"building_id"})
    result = await create_amenity(bid, fields)
    if result.get("ok"):
        await _flush_datasource_cache()
    return APIResponse(
        success=bool(result.get("ok")),
        error=result.get("error"),
        data={
            "subject": result.get("subject"),
            "ttl": result.get("ttl"),
            "file": result.get("file"),
        },
    )


@app.delete("/api/v1/admin/capabilities/{local_name}", response_model=APIResponse)
async def delete_capability(
    local_name: str,
    building_id: Optional[str] = None,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Delete an amenity by local name. GUI-authored amenities are removed permanently;
    file-loaded ones reload on the next restart (edit the TTL to remove those)."""
    from orchestrator.services.capability_admin import delete_amenity

    bid = building_id or settings.BUILDING_ID
    result = await delete_amenity(bid, local_name)
    if result.get("ok"):
        await _flush_datasource_cache()
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


# ---------------------------------------------------------------------------
# Admin — access policies (V5-T43): governance authored as versioned TTL
# ---------------------------------------------------------------------------


class PolicyCreate(BaseModel):
    """Guided AccessPolicy form. Becomes one ontosage:AccessPolicy instance on the
    active building's namespace, written to input/<id>_policies.ttl."""

    id: str = Field(
        ..., min_length=1, max_length=64, description="Local name, e.g. policy_occupant"
    )
    role: str = Field(..., description="An RBAC role, or '*' for every role")
    scope_spaces: str = Field(default="any", max_length=200)
    min_sensors: int = Field(default=1, ge=1, le=1000, description="k-anonymity floor (sensors)")
    min_spaces: int = Field(default=1, ge=1, le=1000, description="k-anonymity floor (spaces)")
    tiers: str = Field(default="0:1", max_length=200, description="'minutes:seconds' pairs")
    rate_max: int = Field(default=0, ge=0, le=100000, description="0 = unlimited")
    rate_window_min: int = Field(default=0, ge=0, le=100000, description="0 = unlimited")
    comment: str = Field(default="", max_length=1000)
    acknowledge_weakening: bool = Field(
        default=False,
        description="Required when the edit lowers a floor / relaxes a limit — never implicit",
    )
    building_id: Optional[str] = None


@app.get("/api/v1/admin/policies", response_model=APIResponse)
async def list_access_policies(
    building_id: Optional[str] = None,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """List every AccessPolicy the PDP would enforce, plus the guided-form schema.

    ``editable: false`` marks the individual-privacy rules, which the GUI must not
    offer to change — the system explains the building, it never tracks individuals.
    """
    from orchestrator.services.policy_admin import (
        POLICY_FORM_SCHEMA,
        known_roles,
        list_policies,
    )

    bid = building_id or settings.BUILDING_ID
    policies = await list_policies(bid)
    return APIResponse(
        success=True,
        data={
            "building_id": bid,
            "policies": policies,
            "roles": known_roles(),
            "form_schema": POLICY_FORM_SCHEMA,
            "enforcement_mode": _protect_enforcement_mode(),
        },
    )


@app.post("/api/v1/admin/policies", response_model=APIResponse)
async def create_access_policy(
    body: PolicyCreate,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Create/replace a policy, then reload the PDP and flush the response cache so the
    change binds on the NEXT question. A change that weakens a guarantee is rejected
    unless ``acknowledge_weakening`` is set, and is logged with the actor either way."""
    from orchestrator.services.policy_admin import create_policy

    bid = body.building_id or settings.BUILDING_ID
    fields = body.model_dump(exclude={"building_id", "acknowledge_weakening"})
    result = await create_policy(
        bid,
        fields,
        actor=user.username,
        acknowledge_weakening=body.acknowledge_weakening,
    )
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


@app.delete("/api/v1/admin/policies/{local_name}", response_model=APIResponse)
async def delete_access_policy(
    local_name: str,
    building_id: Optional[str] = None,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Delete a policy. Individual-privacy rules are refused here by design."""
    from orchestrator.services.policy_admin import delete_policy

    bid = building_id or settings.BUILDING_ID
    result = await delete_policy(bid, local_name, actor=user.username)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


def _protect_enforcement_mode() -> str:
    try:
        from orchestrator.services.privacy.enforcement import enforcement_mode

        return enforcement_mode()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Admin — Qdrant re-index job queue
# ---------------------------------------------------------------------------

_reindex_service_instance: Optional[Any] = None


def _get_reindex_service() -> Any:
    """Single indexing gateway. Creates the shared ReindexService once, then refreshes its indexer
    references from app.state on every call — so it works whether called early in startup (before
    the indexers exist) or at request time. NB the document indexer lives on ``app.state.doc_indexer``
    (not ``document_indexer``); reading the right attribute is what makes the 'documents' reindex
    target actually run instead of silently no-op'ing (CAVEAT-042)."""
    global _reindex_service_instance
    if _reindex_service_instance is None:
        from orchestrator.services.reindex_service import ReindexService

        _reindex_service_instance = ReindexService()
    _reindex_service_instance.set_indexers(
        document_indexer=getattr(app.state, "doc_indexer", None),
    )
    return _reindex_service_instance


def _enqueue_similarity_rebuild(result: dict) -> None:
    """Request a DEBOUNCED GraphDB similarity-index rebuild so newly-added triples become
    retrievable via semantic RAG, and stash the current rebuild status on ``result`` for the GUI.

    The debouncer collapses a burst of registrations into one eventual rebuild (and re-runs once if
    triples arrive mid-rebuild), so rapid edits don't queue many minutes-long full-graph rebuilds.
    Persistence (input/ + GraphDB) is already durable at this point; this only refreshes the
    fuzzy/semantic entity index. Non-fatal — a failed request never fails the registration.
    """
    try:
        from orchestrator.services.similarity_reindex import get_similarity_debouncer

        result["similarity"] = get_similarity_debouncer().request()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"[reindex] similarity rebuild request failed: {e}")


@app.post("/api/v1/admin/reindex", response_model=APIResponse)
async def trigger_reindex(
    body: ReindexRequest,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Trigger re-indexing. Qdrant targets run as a background job (poll by job_id); the
    ``ontology_similarity`` target goes through the debounced similarity gateway (poll
    ``/api/v1/admin/reindex/similarity-status``)."""
    bid = body.building_id or settings.BUILDING_ID
    valid = [
        t
        for t in body.targets
        if t in {"capability", "documents", "floor_plans", "ontology_similarity"}
    ]
    if not valid:
        return APIResponse(
            success=False,
            error="no valid targets (capability|documents|floor_plans|ontology_similarity)",
            data={},
        )
    data: Dict[str, Any] = {"building_id": bid}
    if "ontology_similarity" in valid:
        from orchestrator.services.similarity_reindex import get_similarity_debouncer

        data["similarity"] = get_similarity_debouncer().request()
    qdrant_targets = [t for t in valid if t != "ontology_similarity"]
    if qdrant_targets:
        data["job_id"] = _get_reindex_service().start(qdrant_targets, building_id=bid)
        data["targets"] = qdrant_targets
    return APIResponse(success=True, data=data)


@app.get("/api/v1/admin/reindex/similarity-status", response_model=APIResponse)
async def similarity_reindex_status(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Current state of the debounced similarity-index rebuild + a live GraphDB status read.

    Lets the admin console tell the user, honestly, when just-added data is searchable:
    ``ready`` (idle, index built) vs ``pending``/``rebuilding`` (wait a moment)."""
    from orchestrator.services.ontology_manager import get_similarity_index_status
    from orchestrator.services.similarity_reindex import get_similarity_debouncer

    data = get_similarity_debouncer().status()
    live = await get_similarity_index_status()
    if live.get("ok"):
        data["graphdb_status"] = live.get("status")
        data["graphdb_building"] = live.get("building")
        # If GraphDB itself still reports a build in progress, we are not truly ready yet.
        if live.get("building"):
            data["ready"] = False
    return APIResponse(success=True, data=data)


@app.get("/api/v1/admin/reindex/{job_id}", response_model=APIResponse)
async def reindex_job_status(
    job_id: str,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Poll re-index job status by job_id."""
    svc = _get_reindex_service()
    result = svc.status(job_id)
    return APIResponse(success=result.get("found", False), data=result)


@app.get("/api/v1/admin/reindex", response_model=APIResponse)
async def list_reindex_jobs(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """List all re-index jobs this session (newest first)."""
    svc = _get_reindex_service()
    return APIResponse(success=True, data={"jobs": svc.list_jobs()})


# ── Knowledge-file uploads: documents + floor plans (building-agnostic) ──────────
# These close the pure-GUI onboarding gap: an admin can add a building's policy/manual
# documents and floor-plan PDFs/DWGs from the Admin Console, with no host-side file
# editing. Files land in the ACTIVE building's mounted input/ (writable) and are
# re-indexed. Zero building literals — everything resolves from settings.BUILDING_ID.
_INPUT_ROOT = "/app/input"
_DOC_EXTS = frozenset({".md", ".txt", ".pdf"})
_FLOORPLAN_EXTS = frozenset({".pdf", ".dwg", ".dxf"})
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB guard


def _safe_upload_name(filename: Optional[str], allowed: frozenset) -> str:
    """Sanitize an uploaded filename to a safe bare basename; raise ValueError on a bad
    extension or path-traversal attempt."""
    base = os.path.basename((filename or "").replace("\\", "/")).strip()
    if not base or base.startswith("."):
        raise ValueError("invalid filename")
    ext = os.path.splitext(base)[1].lower()
    if ext not in allowed:
        raise ValueError(f"unsupported extension '{ext}' (allowed: {', '.join(sorted(allowed))})")
    safe = _re.sub(r"[^A-Za-z0-9 ._-]", "_", base)
    return safe


@app.post("/api/v1/admin/documents/upload", response_model=APIResponse)
async def upload_document(
    file: UploadFile = File(...),
    user: UserContext = Depends(require_permission("config:write")),
):
    """Upload a policy/manual document (.md/.txt/.pdf) into the ACTIVE building's
    input/documents/ and re-index the document KB (Qdrant ``documents_<bldg>``).
    Building-agnostic: writes to the active BUILDING_ID's documents folder."""
    from pathlib import Path

    try:
        safe = _safe_upload_name(file.filename, _DOC_EXTS)
    except ValueError as e:
        return APIResponse(success=False, error=str(e), data={})
    content = await file.read()
    if not content:
        return APIResponse(success=False, error="empty file", data={})
    if len(content) > _MAX_UPLOAD_BYTES:
        return APIResponse(success=False, error="file too large (max 25 MB)", data={})
    docs_dir = Path(_INPUT_ROOT) / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / safe).write_bytes(content)
    bid = settings.BUILDING_ID
    job_id = _get_reindex_service().start(["documents"], building_id=bid)
    logger.info(f"[documents] uploaded {safe} ({len(content)} B) → reindex job={job_id}")
    return APIResponse(
        success=True,
        data={
            "filename": safe,
            "bytes": len(content),
            "building_id": bid,
            "reindex_job_id": job_id,
        },
    )


@app.get("/api/v1/admin/documents", response_model=APIResponse)
async def list_documents(
    user: UserContext = Depends(require_permission("config:read")),
):
    """List documents currently in the active building's input/documents/."""
    from pathlib import Path

    docs_dir = Path(_INPUT_ROOT) / "documents"
    items = []
    if docs_dir.is_dir():
        for p in sorted(docs_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in _DOC_EXTS:
                items.append(
                    {"filename": p.name, "bytes": p.stat().st_size, "ext": p.suffix.lower()}
                )
    return APIResponse(
        success=True,
        data={"building_id": settings.BUILDING_ID, "documents": items, "count": len(items)},
    )


@app.delete("/api/v1/admin/documents/{name}", response_model=APIResponse)
async def delete_document(
    name: str,
    user: UserContext = Depends(require_permission("config:write")),
):
    """Delete a document from input/documents/ and re-index the document KB."""
    from pathlib import Path

    base = os.path.basename(name.replace("\\", "/"))
    if base != name or not base or base.startswith("."):
        return APIResponse(success=False, error="invalid filename", data={})
    dest = Path(_INPUT_ROOT) / "documents" / base
    if not dest.is_file():
        return APIResponse(success=False, error=f"not found: {base}", data={})
    dest.unlink()
    job_id = _get_reindex_service().start(["documents"], building_id=settings.BUILDING_ID)
    logger.info(f"[documents] deleted {base} → reindex job={job_id}")
    return APIResponse(success=True, data={"deleted": base, "reindex_job_id": job_id})


@app.post("/api/v1/admin/floor-plans/upload", response_model=APIResponse)
async def upload_floor_plan(
    floor: int = Form(...),
    file: UploadFile = File(...),
    label: Optional[str] = Form(None),
    user: UserContext = Depends(require_permission("config:write")),
):
    """Upload a floor-plan PDF/DWG for a floor and ingest it into the manifest registry.
    Stored as '<label> floor <N>.<ext>' in the active building's input/ (label defaults
    to BUILDING_ID, matching the reingest naming convention). Building-agnostic."""
    from pathlib import Path

    from orchestrator.services.dwg_pipeline import get_dwg_pipeline
    from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _FLOORPLAN_EXTS:
        return APIResponse(
            success=False,
            error=f"unsupported extension '{ext}' (allowed: .pdf, .dwg, .dxf)",
            data={},
        )
    if floor < 0:
        return APIResponse(success=False, error="floor must be >= 0", data={})
    content = await file.read()
    if not content:
        return APIResponse(success=False, error="empty file", data={})
    if len(content) > _MAX_UPLOAD_BYTES:
        return APIResponse(success=False, error="file too large (max 25 MB)", data={})
    lbl = _re.sub(r"[^A-Za-z0-9 _-]", "_", (label or settings.BUILDING_ID).strip()) or "building"
    fname = f"{lbl} floor {floor}{ext}"
    dest = Path(_INPUT_ROOT) / fname
    dest.write_bytes(content)
    try:
        if ext == ".pdf":
            manifest = await get_floor_plan_pipeline().ingest_file(dest)
        else:
            manifest = await get_dwg_pipeline().ingest_file(dest)
    except Exception as e:  # stored, but ingest failed → report honestly, keep the file
        logger.error(f"[floor-plans] ingest failed for {fname}: {e}", exc_info=True)
        return APIResponse(
            success=False,
            error=f"stored but ingest failed: {e}",
            data={"filename": fname, "bytes": len(content)},
        )
    summary = (
        {
            "building_id": manifest.building_id,
            "floor": manifest.floor,
            "spaces": len(manifest.spaces),
            "source": ext.lstrip("."),
        }
        if manifest
        else {}
    )
    logger.info(f"[floor-plans] uploaded {fname} ({len(content)} B) → manifest {summary}")
    return APIResponse(
        success=True, data={"filename": fname, "bytes": len(content), "manifest": summary}
    )


@app.get("/api/v1/admin/floor-plans/files", response_model=APIResponse)
async def list_floor_plan_files(
    user: UserContext = Depends(require_permission("config:read")),
):
    """List floor-plan PDF/DWG files currently present in the active building's input/."""
    from pathlib import Path

    items = []
    root = Path(_INPUT_ROOT)
    if root.is_dir():
        for p in sorted(root.glob("*")):
            if p.is_file() and p.suffix.lower() in _FLOORPLAN_EXTS:
                items.append(
                    {"filename": p.name, "bytes": p.stat().st_size, "ext": p.suffix.lower()}
                )
    return APIResponse(
        success=True,
        data={"building_id": settings.BUILDING_ID, "floor_plans": items, "count": len(items)},
    )


@app.get("/api/v1/datasources", response_model=APIResponse)
async def list_datasources():
    """List toggleable synthetic data sources with their current enabled state.

    Read-only, no auth (parity with the capability-indexer status endpoint) —
    exposes only operational state, no secrets.
    """
    mgr = getattr(app.state, "datasource_manager", None)
    if mgr is None:
        return APIResponse(
            success=True,
            data={"enabled": settings.DATASOURCE_TOGGLES_ENABLED, "sources": []},
        )
    return APIResponse(
        success=True,
        data={"enabled": settings.DATASOURCE_TOGGLES_ENABLED, "sources": mgr.status()},
    )


@app.post("/api/v1/datasources", response_model=APIResponse)
async def create_datasource(
    body: DataSourceSpec,
    user: UserContext = Depends(require_permission("config:write")),
):
    """Create a new synthetic data source from the GUI (persisted, starts disabled)."""
    mgr = getattr(app.state, "datasource_manager", None)
    if mgr is None:
        return APIResponse(success=False, error="datasource toggles disabled", data={})
    payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    result = mgr.create(payload)
    return APIResponse(success=bool(result.get("ok")), data=result)


@app.post("/api/v1/datasources/{source_id}/enable", response_model=APIResponse)
async def enable_datasource(
    source_id: str,
    user: UserContext = Depends(require_permission("config:write")),
):
    """Enable a data source: load its Brick triples into its named graph."""
    mgr = getattr(app.state, "datasource_manager", None)
    if mgr is None:
        return APIResponse(success=False, error="datasource toggles disabled", data={})
    result = await mgr.enable(source_id)
    await _flush_datasource_cache()
    return APIResponse(success=bool(result.get("ok")), data=result)


@app.post("/api/v1/datasources/{source_id}/disable", response_model=APIResponse)
async def disable_datasource(
    source_id: str,
    user: UserContext = Depends(require_permission("config:write")),
):
    """Disable a data source: clear its named graph (gates its questions)."""
    mgr = getattr(app.state, "datasource_manager", None)
    if mgr is None:
        return APIResponse(success=False, error="datasource toggles disabled", data={})
    result = await mgr.disable(source_id)
    await _flush_datasource_cache()
    return APIResponse(success=bool(result.get("ok")), data=result)


@app.get("/api/v1/datasources/{source_id}/preview", response_model=APIResponse)
async def preview_datasource(source_id: str, limit: int = 48):
    """Sample a source's synthetic series without writing to the DB. Read-only.

    Intentionally unauthenticated (parity with list_datasources) — it exposes only
    synthetic sample values, no secrets, and the SPA previews sources before sign-in.
    The ``limit`` is clamped, though: uncapped it would let an anonymous caller drive
    arbitrarily large synthetic generation (an unbounded-compute / DoS vector).
    """
    mgr = getattr(app.state, "datasource_manager", None)
    if mgr is None:
        return APIResponse(success=False, error="datasource toggles disabled", data={})
    limit = max(1, min(int(limit), 500))
    result = mgr.preview(source_id, limit=limit)
    return APIResponse(success=bool(result.get("ok")), data=result)


@app.post("/api/v1/datasources/{source_id}/regenerate", response_model=APIResponse)
async def regenerate_datasource(
    source_id: str,
    user: UserContext = Depends(require_permission("config:write")),
):
    """Generate + load a source's synthetic readings into its narrow table."""
    mgr = getattr(app.state, "datasource_manager", None)
    if mgr is None:
        return APIResponse(success=False, error="datasource toggles disabled", data={})
    # generation is CPU/DB-bound and blocking — run off the event loop
    result = await asyncio.get_event_loop().run_in_executor(None, mgr.regenerate, source_id)
    await _flush_datasource_cache()
    return APIResponse(success=bool(result.get("ok")), data=result)


async def _flush_datasource_cache() -> None:
    """Best-effort response-cache flush so a toggle takes effect immediately."""
    try:
        cache = getattr(app.state, "response_cache", None) or response_cache
        if cache is not None and hasattr(cache, "invalidate"):
            await cache.invalidate(building_id=settings.BUILDING_ID, flush_all=True)
    except Exception as e:
        logger.debug(f"[datasources] cache flush skipped: {e}")


@app.post("/api/v1/datasources/reset-demo", response_model=APIResponse)
async def reset_datasources_demo(
    user: UserContext = Depends(require_permission("config:write")),
):
    """Reset to a clean demo baseline: disable every enabled source, flush cache once.

    Deterministic, idempotent reset so a demo/QA run always starts from the same
    clean slate (every synthetic source off). The presenter then enables what the
    walkthrough needs. Mirrors the manual reset in scripts/test_datasource_capability_qa.py.
    """
    mgr = getattr(app.state, "datasource_manager", None)
    if mgr is None:
        return APIResponse(success=False, error="datasource toggles disabled", data={})
    disabled: List[str] = []
    for s in mgr.status():
        if s.get("enabled"):
            res = await mgr.disable(s["id"])
            if res.get("ok"):
                disabled.append(s["id"])
    await _flush_datasource_cache()
    return APIResponse(success=True, data={"disabled": disabled, "count": len(disabled)})


# ── Admin console: .env + database credentials (system:admin, localhost panel) ──


class EnvUpdate(BaseModel):
    changes: Dict[str, str] = Field(
        ..., description="KEY->value pairs to write to .env. MASK value = unchanged secret."
    )


class DatabaseCreate(BaseModel):
    key: str = Field(..., min_length=1, description="Registry key (ref:storedAt bldg:<key>)")
    type: str = Field(..., description="mysql | mysql_narrow | postgresql | timescaledb")
    host: str = Field(...)
    port: str = Field(default="3306")
    user: str = Field(default="")
    password: str = Field(default="")
    database: str = Field(default="")
    table: Optional[str] = Field(
        default=None,
        description="Narrow-table name (required for mysql_narrow; ignored for wide mysql)",
    )


@app.get("/api/v1/admin/env", response_model=APIResponse)
async def get_env(user: UserContext = Depends(require_permission("system:admin"))):
    """Read .env as editable rows (secret values masked)."""
    from orchestrator.services import admin_config

    return APIResponse(
        success=True, data={"env": admin_config.read_env(), "mask": admin_config.MASK}
    )


@app.put("/api/v1/admin/env", response_model=APIResponse)
async def put_env(body: EnvUpdate, user: UserContext = Depends(require_permission("system:admin"))):
    """Write changed keys to .env (masked = unchanged). Requires an orchestrator restart."""
    from orchestrator.services import admin_config

    summary = admin_config.apply_env(dict(body.changes))
    return APIResponse(
        success=True,
        data={**summary, "restart_required": True, "env_path": str(admin_config.env_path())},
    )


# ── Admin console: building identity (ontology namespace / prefix) ─────────────
# The per-building PREREQUISITE: the `bldg:` prefix is only a label; the namespace it binds to is
# per-building and lives in input/building.yaml. Editable here so onboarding a new building needs
# no hand-editing. Read at boot → takes effect after an orchestrator restart.


class BuildingConfigUpdate(BaseModel):
    ontology_namespace: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Absolute ABox URI for building instances; must end with '#' or '/'",
    )
    ontology_prefix: str = Field(
        default="bldg",
        min_length=1,
        max_length=64,
        description="Short SPARQL prefix label the namespace binds to (e.g. 'bldg')",
    )
    building_name: Optional[str] = Field(default=None, max_length=200)


@app.get("/api/v1/admin/building/config", response_model=APIResponse)
async def get_building_config(user: UserContext = Depends(require_permission("system:admin"))):
    """Current building identity (id, name, ontology namespace, prefix) from building.yaml."""
    from orchestrator.services import admin_config

    return APIResponse(success=True, data=admin_config.read_building_config())


@app.put("/api/v1/admin/building/config", response_model=APIResponse)
async def put_building_config(
    body: BuildingConfigUpdate, user: UserContext = Depends(require_permission("system:admin"))
):
    """Validate + persist the ontology namespace/prefix (+ name) to building.yaml. Restart to apply."""
    from orchestrator.services import admin_config

    result = admin_config.write_building_config(
        body.ontology_namespace, body.ontology_prefix, body.building_name
    )
    result["restart_required"] = bool(result.get("ok"))
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


# ── Admin console: AI provider / model configuration ───────────────────────────


class AIConfigTest(BaseModel):
    provider: str = Field(..., description="local | cloud | openai")
    base_url: Optional[str] = Field(
        default=None, description="override Ollama base URL for the probe"
    )
    api_key: Optional[str] = Field(
        default=None, description="override key for the probe (never stored or logged)"
    )


@app.get("/api/v1/admin/ai-config", response_model=APIResponse)
async def get_ai_config(user: UserContext = Depends(require_permission("system:admin"))):
    """Current AI provider/model/embedding config for the console.

    Returns key *presence* (booleans) only — never the key values.
    """
    return APIResponse(
        success=True,
        data={
            "model_provider": settings.MODEL_PROVIDER,
            "embedding_provider": settings.EMBEDDING_PROVIDER,
            "ollama_base_url": settings.OLLAMA_BASE_URL,
            "ollama_model": settings.OLLAMA_MODEL,
            "ollama_cloud_base_url": settings.OLLAMA_CLOUD_BASE_URL,
            "ollama_cloud_model": settings.OLLAMA_CLOUD_MODEL,
            "openai_model": settings.OPENAI_MODEL,
            "openai_model_fast": settings.OPENAI_MODEL_FAST,
            "openai_api_key_set": bool(settings.OPENAI_API_KEY),
            "ollama_cloud_api_key_set": bool(settings.OLLAMA_CLOUD_API_KEY),
            "providers": ["local", "cloud", "openai"],
            "embedding_providers": ["local", "openai"],
            # Actual embedding model + dimension per provider, so the console shows the
            # live values (e.g. bge-large-en-v1.5 @ 1024-d) instead of hardcoded labels.
            "embedding_model_local": settings.EMBEDDING_MODEL_LOCAL,
            "embedding_dimension_local": settings.EMBEDDING_DIMENSION_LOCAL,
            "embedding_model_openai": settings.EMBEDDING_MODEL_OPENAI,
            "embedding_dimension_openai": settings.EMBEDDING_DIMENSION_OPENAI,
        },
    )


@app.post("/api/v1/admin/ai-config/test", response_model=APIResponse)
async def test_ai_config(
    body: AIConfigTest, user: UserContext = Depends(require_permission("system:admin"))
):
    """Probe a provider for reachability. For local/cloud Ollama it also returns the
    installed model list (the GUI populates its model dropdown from it). Never echoes keys.
    """
    import httpx

    provider = (body.provider or "").lower()
    t0 = time.time()
    try:
        if provider in ("local", "cloud"):
            default_base = (
                settings.OLLAMA_BASE_URL if provider == "local" else settings.OLLAMA_CLOUD_BASE_URL
            )
            base = (body.base_url or default_base).rstrip("/")
            headers: Dict[str, str] = {}
            key = body.api_key or (settings.OLLAMA_CLOUD_API_KEY if provider == "cloud" else "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{base}/api/tags", headers=headers)
                r.raise_for_status()
                tags = r.json() or {}
            models = sorted(m.get("name", "") for m in tags.get("models", []) if m.get("name"))
            return APIResponse(
                success=True,
                data={
                    "ok": True,
                    "provider": provider,
                    "models": models,
                    "latency_ms": round((time.time() - t0) * 1000, 1),
                },
            )
        if provider == "openai":
            key = body.api_key or settings.OPENAI_API_KEY
            if not key:
                return APIResponse(
                    success=False, error="No OpenAI API key set or provided", data={"ok": False}
                )
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                )
                r.raise_for_status()
                payload = r.json() or {}
            ids = sorted(m.get("id", "") for m in payload.get("data", []) if m.get("id"))
            chat = [m for m in ids if m.startswith(("gpt-", "o1", "o3", "chatgpt"))]
            return APIResponse(
                success=True,
                data={
                    "ok": True,
                    "provider": "openai",
                    "models": chat or ids,
                    "latency_ms": round((time.time() - t0) * 1000, 1),
                },
            )
        return APIResponse(
            success=False, error=f"unknown provider '{body.provider}'", data={"ok": False}
        )
    except Exception as e:  # provider unreachable / bad key — structured, non-fatal
        return APIResponse(
            success=False,
            error=str(e)[:200],
            data={
                "ok": False,
                "provider": provider,
                "latency_ms": round((time.time() - t0) * 1000, 1),
            },
        )


# ── Admin console: integrations (live feeds + notification channels) ───────────


@app.get("/api/v1/admin/integrations", response_model=APIResponse)
async def get_integrations(user: UserContext = Depends(require_permission("system:admin"))):
    """Read-only view of live feeds (feeds.yaml) + notification channels (channels.yaml).

    Read-only by design: those YAML files carry curated comments a ``safe_dump`` rewrite
    would destroy, so editing stays in the files. This surfaces what's configured and
    powers the per-channel test-send below.
    """
    building_id = settings.BUILDING_ID
    feeds: List[Dict[str, Any]] = []
    try:
        from pathlib import Path

        import yaml as _yaml

        from shared.building_paths import resolve_building_file

        rel = resolve_building_file(building_id, "feeds.yaml")
        fp = Path(rel) if rel else None
        if fp and fp.is_file():
            doc = _yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
            for f in doc.get("feeds", []) or []:
                feeds.append(
                    {
                        "id": f.get("id"),
                        "type": f.get("type"),
                        "url": f.get("url", ""),
                        "interval_s": f.get("interval_s"),
                        "brick_class": f.get("brick_class", ""),
                        "storage": f.get("storage", ""),
                        "enabled": bool(f.get("enabled", True)),
                    }
                )
    except Exception as e:  # non-fatal: an unreadable feeds.yaml just yields an empty list
        logger.debug(f"[integrations] feeds read skipped: {e}")

    channels: List[Dict[str, Any]] = []
    try:
        from orchestrator.services.notification_service import get_notification_service

        svc = get_notification_service(building_id)
        for c in svc.channels:
            channels.append(
                {
                    "id": c.get("id"),
                    "type": c.get("type"),
                    "enabled": bool(c.get("enabled", True)),
                    "target": c.get("url") or c.get("to_addr") or "",
                }
            )
        # The built-in 'log' channel is always active but not listed in channels.yaml.
        if not any(c["type"] == "log" for c in channels):
            channels.insert(
                0, {"id": "log", "type": "log", "enabled": True, "target": "(server log)"}
            )
    except Exception as e:  # non-fatal
        logger.debug(f"[integrations] channels read skipped: {e}")

    return APIResponse(success=True, data={"feeds": feeds, "channels": channels})


@app.post("/api/v1/admin/channels/{channel_id}/test", response_model=APIResponse)
async def test_channel(
    channel_id: str, user: UserContext = Depends(require_permission("system:admin"))
):
    """Send one test notification through a single channel (does not mutate config)."""
    from orchestrator.services.notification_service import get_notification_service

    svc = get_notification_service(settings.BUILDING_ID)
    payload = {
        "title": "OntoSage test notification",
        "message": f"Test dispatch from the admin console at {datetime.utcnow().isoformat()}Z.",
        "severity": "info",
        "building_id": settings.BUILDING_ID,
        "source": "admin_console_test",
    }
    ch = (
        {"id": "log", "type": "log"}
        if channel_id == "log"
        else next((c for c in svc.channels if c.get("id") == channel_id), None)
    )
    if ch is None:
        return APIResponse(success=False, error=f"unknown channel '{channel_id}'", data={})
    try:
        sent = await svc._send(ch, payload)
        return APIResponse(
            success=bool(sent),
            data={"channel": channel_id, "type": ch.get("type"), "sent": bool(sent)},
        )
    except Exception as e:
        return APIResponse(success=False, error=str(e)[:200], data={"channel": channel_id})


@app.get("/api/v1/admin/audit", response_model=APIResponse)
async def get_admin_audit(
    limit: int = 100, user: UserContext = Depends(require_permission("system:admin"))
):
    """Recent mutating admin-console actions (newest first). Requires system:admin."""
    if postgres_manager is None:
        return APIResponse(success=True, data={"entries": []})
    entries = await postgres_manager.get_admin_audit(limit=limit)
    return APIResponse(success=True, data={"entries": entries})


class ConfigRestore(BaseModel):
    bundle: Dict[str, Any] = Field(..., description="A bundle produced by GET /config/backup")
    dry_run: bool = Field(default=False, description="Validate only; write nothing")


@app.get("/api/v1/admin/config/backup", response_model=APIResponse)
async def backup_config_endpoint(user: UserContext = Depends(require_permission("system:admin"))):
    """Portable bundle of console-managed config (data sources / DB registry / role
    access / toggle-state). Excludes .env secrets. Requires system:admin."""
    from orchestrator.services import admin_config

    return APIResponse(success=True, data=admin_config.backup_config())


@app.post("/api/v1/admin/config/restore", response_model=APIResponse)
async def restore_config_endpoint(
    body: ConfigRestore, user: UserContext = Depends(require_permission("system:admin"))
):
    """Validate + write a previously-downloaded config bundle (atomic — aborts if any
    file is malformed). Registries reload at boot, so a restart fully applies it."""
    from orchestrator.services import admin_config

    try:
        summary = admin_config.restore_config(body.bundle, dry_run=body.dry_run)
    except ValueError as e:
        return APIResponse(success=False, error=str(e), data={})
    if not body.dry_run:
        await _flush_datasource_cache()
    return APIResponse(success=True, data={**summary, "restart_required": not body.dry_run})


@app.get("/api/v1/admin/databases", response_model=APIResponse)
async def get_databases(user: UserContext = Depends(require_permission("system:admin"))):
    """List DB connections (curated + GUI overlay), passwords masked.

    Each item is annotated ``active`` — whether this building actually initializes
    it (building.yaml ``storage.databases``). The rest are dormant templates.
    """
    from orchestrator.services import admin_config

    dbs = admin_config.read_databases()
    active = admin_config.active_db_keys()
    for d in dbs:
        d["active"] = (active is None) or (d["key"] in active)
    return APIResponse(success=True, data={"databases": dbs, "filtered": active is not None})


@app.get("/api/v1/admin/databases/sensor-counts", response_model=APIResponse)
async def get_db_sensor_counts(user: UserContext = Depends(require_permission("system:admin"))):
    """Batch sensor-triple count per DB graph in ONE query (all connections at once).

    Replaces the per-card probe the console used to fire once per connection — which
    flooded the rate limiter when many databases were registered.
    """
    from orchestrator.services import db_ontology

    counts = await db_ontology.graph_triple_counts()
    return APIResponse(success=True, data={"counts": counts})


@app.get("/api/v1/admin/provenance", response_model=APIResponse)
async def get_provenance(user: UserContext = Depends(require_permission("system:admin"))):
    """Real vs simulated sensor coverage, computed LIVE from the active building.

    A per-source "synthetic" flag alone misleads: a modality can have hundreds of REAL
    sensors in the building's own historian *and* a handful of synthetic demo points in
    a separate table. Reading only the demo flag, an operator concludes the whole
    capability is fake. This counts each storage backend's sensors in the graph and
    labels them with that backend's declared `nature`, so the split is evidence, not a
    flag — and it is building-agnostic: both halves come from the ACTIVE building.
    """
    from orchestrator.agents.sparql_agent import _active_namespace
    from orchestrator.services import admin_config
    from orchestrator.services.building_metrics import _default_sparql_exec

    natures = {d["key"]: d for d in admin_config.read_databases()}
    ns = _active_namespace()

    query = (
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "SELECT ?storage (COUNT(DISTINCT ?s) AS ?n) WHERE {\n"
        "  ?s ref:hasExternalReference ?e . ?e ref:storedAt ?storage .\n"
        f'  FILTER(STRSTARTS(STR(?s), "{ns}"))\n'
        "} GROUP BY ?storage"
    )
    rows: List[Dict[str, Any]] = []
    try:
        data = await _default_sparql_exec(query)
        for b in (data or {}).get("results", {}).get("bindings", []):
            uri = b.get("storage", {}).get("value", "")
            key = uri.split("#")[-1].split("/")[-1]
            meta = natures.get(key, {})
            nature = meta.get("nature", "synthetic")
            rows.append(
                {
                    "key": key,
                    "nature": nature,
                    "note": meta.get("note", ""),
                    "type": meta.get("type", "?"),
                    "sensors": int(b.get("n", {}).get("value", 0)),
                }
            )
    except Exception as e:  # never break the console on a degraded graph
        logger.warning(f"[provenance] live count failed: {e}")
        return APIResponse(success=False, error=str(e), data={"backends": []})

    rows.sort(key=lambda r: (-r["sensors"], r["key"]))
    real = sum(r["sensors"] for r in rows if r["nature"] == "real")
    sim = sum(r["sensors"] for r in rows if r["nature"] != "real")

    # Building-level declaration from the ACTIVE building.yaml. Per-connection `nature`
    # describes READINGS; this describes the building itself — a portability fixture's
    # ontology and sensors are invented too, which per-source flags cannot express.
    # Read live and never inferred, so each building states its own answer.
    bnature, bnote = "", ""
    try:
        from orchestrator.services import admin_config

        prov = (admin_config.read_building_config() or {}).get("provenance") or {}
        bnature = str(prov.get("nature", "") or "")
        bnote = str(prov.get("note", "") or "")
    except Exception as e:
        logger.debug(f"[provenance] building-level declaration unavailable: {e}")

    return APIResponse(
        success=True,
        data={
            "backends": rows,
            "totals": {"real": real, "simulated": sim, "total": real + sim},
            "building": getattr(settings, "BUILDING_NAME", settings.BUILDING_ID),
            "building_nature": bnature,
            "building_note": bnote,
        },
    )


@app.post("/api/v1/admin/databases", response_model=APIResponse)
async def create_database(
    body: DatabaseCreate,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Add a DB connection (overlay entry + .env creds) and hot-apply it — no restart.

    ``add_database`` writes the overlay entry + .env values and injects the creds into
    ``os.environ`` (so ``resolve_connection`` resolves the new key immediately). We then
    reload the adapter pool so the query path routes to the new backend right away. If
    the reload fails, the connection is still persisted and a restart will pick it up.
    """
    from orchestrator.services import admin_config

    try:
        result = admin_config.add_database(
            body.key,
            body.type,
            body.host,
            body.port,
            body.user,
            body.password,
            body.database,
            table=body.table,
        )
    except ValueError as e:
        return APIResponse(success=False, error=str(e), data={})
    try:
        await adapter_registry.reload()
        result["restart_required"] = False
        result["hot_applied"] = True
    except Exception as e:  # persisted; a restart will still pick it up
        logger.warning(f"[create_database] adapter reload failed (restart needed): {e}")
        result["hot_applied"] = False
    return APIResponse(success=True, data=result)


# Fixed ids seeded by config-panel/demo-db/demo_seed.sql — must stay in lock-step
# with that file so the sensor registration references the exact rows in demo_readings.
_DEMO_DB_UUID_TEMP = "aaaaaaaa-0000-4000-8000-000000000001"
_DEMO_DB_UUID_HUMID = "aaaaaaaa-0000-4000-8000-000000000002"


@app.get("/api/v1/admin/databases/demo-template", response_model=APIResponse)
async def demo_database_template(user: UserContext = Depends(require_permission("system:admin"))):
    """Prefill payload for the console's "Load demo database" button.

    Returns the connection spec pointing at the profile-gated ``demo-mysql`` service
    plus a ready-to-paste sensor CSV whose UUIDs match ``demo_readings``. Lets an admin
    rehearse the full external-DB flow (connect → register → recreate → ask) in two
    clicks. Requires ``docker compose --profile demo up -d demo-mysql`` to be running.
    """
    sensors_csv = (
        "local,brick_class,location,uuid,unit,label\n"
        f"Demo_Temperature_Sensor,brick:Temperature_Sensor,bldg:Floor5,{_DEMO_DB_UUID_TEMP},"
        "unit:DEG_C,Demo Temperature Sensor\n"
        f"Demo_Humidity_Sensor,brick:Humidity_Sensor,bldg:Floor5,{_DEMO_DB_UUID_HUMID},"
        "unit:PERCENT,Demo Humidity Sensor\n"
    )
    return APIResponse(
        success=True,
        data={
            "connection": {
                "key": "demo_external",
                "type": "mysql_narrow",
                "table": "demo_readings",
                "host": "demo-mysql",
                "port": "3306",
                "user": "demo",
                "password": "demo",
                "database": "demodb",
            },
            "sensors_csv": sensors_csv,
            "note": (
                "Start the demo DB first: `docker compose --profile demo up -d demo-mysql`. "
                "Then: Add connection → Register sensors (CSV is prefilled) → recreate the "
                "orchestrator → ask about demo temperature/humidity on floor 5."
            ),
        },
    )


# ── External-DB sensor metadata (make a connected DB queryable) ────────────────


class SensorPoints(BaseModel):
    points: List[Dict[str, Any]] = Field(
        ..., description="[{local, brick_class, location, uuid, unit?, label?}, ...]"
    )


class SensorTtl(BaseModel):
    ttl: str = Field(..., min_length=1, description="Brick Turtle with ref:storedAt bldg:<key>")


@app.get("/api/v1/admin/databases/{db_key}/sensors", response_model=APIResponse)
async def get_db_sensors(
    db_key: str, user: UserContext = Depends(require_permission("system:admin"))
):
    """How many sensor triples are registered for this DB's named graph."""
    from orchestrator.services import db_ontology

    count = await db_ontology.graph_triple_count(db_key)
    return APIResponse(success=True, data={"db_key": db_key, "triples": count})


@app.post("/api/v1/admin/databases/{db_key}/sensors", response_model=APIResponse)
async def register_db_sensors(
    db_key: str, body: SensorPoints, user: UserContext = Depends(require_permission("system:admin"))
):
    """Register sensor points (with real UUIDs) so this DB is discoverable via SPARQL."""
    from orchestrator.services import db_ontology

    result = await db_ontology.register_points(db_key, body.points)
    if result.get("ok"):
        await _flush_datasource_cache()
        _enqueue_similarity_rebuild(result)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


@app.post("/api/v1/admin/databases/{db_key}/sensors/ttl", response_model=APIResponse)
async def register_db_sensors_ttl(
    db_key: str, body: SensorTtl, user: UserContext = Depends(require_permission("system:admin"))
):
    """Upload a Brick TTL of the DB's sensors (validated) into its named graph."""
    from orchestrator.services import db_ontology

    result = await db_ontology.register_ttl(db_key, body.ttl)
    if result.get("ok"):
        await _flush_datasource_cache()
        _enqueue_similarity_rebuild(result)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


class SensorCsv(BaseModel):
    csv: str = Field(
        ..., min_length=1, description="CSV: local,brick_class,location,uuid[,unit,label]"
    )


@app.post("/api/v1/admin/databases/{db_key}/sensors/csv", response_model=APIResponse)
async def register_db_sensors_csv(
    db_key: str, body: SensorCsv, user: UserContext = Depends(require_permission("system:admin"))
):
    """Register sensors from a pasted/imported CSV (no hand-typing each point)."""
    from orchestrator.services import admin_config, db_ontology

    points, issues = admin_config.parse_sensor_csv(body.csv)
    if not points:
        return APIResponse(success=False, error="; ".join(issues) or "no valid rows", data={})
    result = await db_ontology.register_points(db_key, points)
    result["parse_warnings"] = issues
    if result.get("ok"):
        await _flush_datasource_cache()
        _enqueue_similarity_rebuild(result)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


class ConnProbe(BaseModel):
    key: Optional[str] = Field(
        None, description="Existing connection key (creds resolved server-side)"
    )
    type: str = Field(default="mysql")
    host: str = Field(default="")
    port: str = Field(default="3306")
    user: str = Field(default="")
    password: str = Field(default="")
    database: str = Field(default="")


def _probe_creds(body: "ConnProbe") -> Dict[str, Any]:
    """Resolve a probe body to real creds — from an existing key, or the raw fields."""
    from orchestrator.services import admin_config

    if body.key:
        c = admin_config.resolve_connection(body.key)
        if c is None:
            raise ValueError(f"unknown connection '{body.key}'")
        return c
    return {
        "type": body.type,
        "host": body.host,
        "port": body.port,
        "user": body.user,
        "password": body.password,
        "database": body.database,
    }


@app.post("/api/v1/admin/databases/test", response_model=APIResponse)
async def test_database(
    body: ConnProbe, user: UserContext = Depends(require_permission("system:admin"))
):
    """Test a DB connection (by key or raw creds) — SELECT 1 + latency."""
    from orchestrator.services import admin_config

    try:
        c = _probe_creds(body)
    except ValueError as e:
        return APIResponse(success=False, error=str(e), data={})
    result = await admin_config.test_connection(
        c["type"], c["host"], c["port"], c["user"], c["password"], c["database"]
    )
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


@app.post("/api/v1/admin/databases/introspect", response_model=APIResponse)
async def introspect_database(
    body: ConnProbe, user: UserContext = Depends(require_permission("system:admin"))
):
    """List tables + columns of a connection (by key or raw creds)."""
    from orchestrator.services import admin_config

    try:
        c = _probe_creds(body)
    except ValueError as e:
        return APIResponse(success=False, error=str(e), data={})
    result = await admin_config.introspect(
        c["type"], c["host"], c["port"], c["user"], c["password"], c["database"]
    )
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


@app.get("/api/v1/admin/databases/{db_key}/data", response_model=APIResponse)
async def database_table_stats(
    db_key: str, table: str, user: UserContext = Depends(require_permission("system:admin"))
):
    """Row count + distinct-sensor count + recent sample for a table in a connection."""
    from orchestrator.services import admin_config

    c = admin_config.resolve_connection(db_key)
    if c is None:
        return APIResponse(success=False, error=f"unknown connection '{db_key}'", data={})
    result = await admin_config.table_stats(
        c["type"], c["host"], c["port"], c["user"], c["password"], c["database"], table
    )
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


# UUID *shape* (8-4-4-4-12), alphanumeric — matches real hex UUIDs AND the
# synthetic ontology ids like ``00000000-ac01-0000-0000-000000000001``. Specific
# enough that ordinary columns (``Datetime``, ``value``) never match.
#: Freshness window for "is this sensor still reporting?" (CAVEAT-233). 24 h is long enough
#: that an hourly or daily-rollup sensor is not called stale, and short enough that a dead
#: feed shows up within a day.
_FRESHNESS_WINDOW_H = 24

_UUID_RE = _re.compile(
    r"^[0-9A-Za-z]{8}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{12}$"
)


async def _resolve_datasource_uuids(db_key: str, table: Optional[str] = None) -> Dict[str, Any]:
    """Distinct timeseries UUIDs present in a connection, for BOTH table shapes:

    * **narrow** ``(uuid, datetime, value)`` — the UUIDs are values in a ``uuid`` column
      (``SELECT DISTINCT uuid``);
    * **wide** (e.g. ``sensor_data``) — each sensor is its own **column** named by its UUID,
      so the UUIDs are the uuid-shaped column names.

    Discovers the right table/shape by introspection when the configured name doesn't
    resolve. Returns ``{ok, uuids, table?, wide?, error?}``.
    """
    from orchestrator.services import admin_config

    c = admin_config.resolve_connection(db_key)
    if c is None:
        return {"ok": False, "error": f"unknown connection '{db_key}'"}
    creds = (c["type"], c["host"], c["port"], c["user"], c["password"], c["database"])
    tbl = table or c.get("table") or c.get("ts_table") or db_key
    # 1) narrow shape on the configured/guessed table (high limit so large datasources
    #    aren't undercounted by the default 500 cap — answerability needs the full set)
    result = await admin_config.distinct_uuids(*creds, tbl, limit=5000)
    if result.get("ok") and result.get("uuids"):
        return result
    # 2) introspect and pick the table with the most UUIDs — narrow (uuid column) OR
    #    wide (uuid-shaped column names). Auto-detects without a `table` in the registry.
    intro = await admin_config.introspect(*creds)
    best: Dict[str, Any] = {"ok": False}
    for t in intro.get("tables", []) if intro.get("ok") else []:
        names = [(col.get("name") or "") for col in t.get("columns", [])]
        if any(nm.lower() == "uuid" for nm in names):
            r2 = await admin_config.distinct_uuids(*creds, t["name"])
            cand = {**r2, "table": t["name"]} if r2.get("ok") else {"ok": False}
        else:
            uuid_cols = [nm for nm in names if _UUID_RE.match(nm)]
            cand = (
                {"ok": True, "uuids": uuid_cols, "table": t["name"], "wide": True}
                if uuid_cols
                else {"ok": False}
            )
        if cand.get("ok") and len(cand.get("uuids", [])) > len(best.get("uuids", [])):
            best = cand
    return best if best.get("ok") else result


async def _declared_uuids_for_datasource(db_key: str) -> set:
    """UUIDs the ontology declares as stored in this datasource (via ref:storedAt)."""
    from orchestrator.services.ontology_manager import run_sparql_select

    q = (
        "PREFIX ref:<https://brickschema.org/schema/Brick/ref#> "
        "SELECT DISTINCT ?uuid WHERE { ?r ref:hasTimeseriesId ?uuid ; ref:storedAt ?db . "
        f'FILTER(REPLACE(STR(?db), "^.*[#/]", "") = "{db_key}") }}'
    )
    res = await run_sparql_select(q, limit=5000)
    if not res.get("ok"):
        return set()
    return {r.get("uuid") for r in res.get("rows", []) if r.get("uuid")}


@app.get("/api/v1/admin/databases/{db_key}/uuids", response_model=APIResponse)
async def database_distinct_uuids(
    db_key: str,
    table: Optional[str] = None,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Distinct timeseries UUIDs already in a connection's table — so the guided sensor form
    maps sensors to REAL ids from the datasource (introspection-driven), not hand-typed UUIDs."""
    result = await _resolve_datasource_uuids(db_key, table)
    return APIResponse(success=bool(result.get("ok")), error=result.get("error"), data=result)


def _store_local_name(key: str) -> str:
    """Local name of a ``ref:storedAt`` IRI — the same rule the declared-UUID SPARQL uses."""
    return str(key).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


async def _reporting_by_local_name(window_hours: int = 24) -> Dict[str, set]:
    """Fresh declared UUIDs per datasource, keyed by the admin's connection key (CAVEAT-233).

    One measurement for the whole screen: the freshness probe walks each store once, and the
    per-datasource numbers are read out of that. Returns ``{}`` when the check can't run, which
    the callers report as "unknown" rather than as zero — an unavailable probe is not evidence
    that nothing is streaming.
    """
    try:
        from orchestrator.services.building_metrics import reporting_uuids_by_store

        by_store = await asyncio.wait_for(reporting_uuids_by_store(window_hours), timeout=20)
    except Exception as e:
        logger.debug(f"[answerability] freshness probe unavailable: {e}")
        return {}
    if not by_store:
        return {}
    out: Dict[str, set] = {}
    for k, uuids in by_store.items():
        out.setdefault(_store_local_name(k), set()).update(uuids)
    return out


async def _answerability_for(
    db_key: str, reporting: Optional[Dict[str, set]] = None
) -> Dict[str, Any]:
    """One datasource's {declared, with_data, reporting, level}.

    `with_data` is "has rows AT ALL"; `reporting` is "produced a reading inside the freshness
    window". Reporting coverage without freshness invites the reader to hear a claim of
    liveness it does not make (CAVEAT-233). `level` deliberately stays driven by coverage:
    a historical-only store is a legitimate configuration and must not be flagged as broken.
    """
    declared = await _declared_uuids_for_datasource(db_key)
    dec = len(declared)
    try:
        ures = await asyncio.wait_for(_resolve_datasource_uuids(db_key), timeout=12)
    except Exception:
        ures = {"ok": False}
    have = set(ures.get("uuids", [])) if ures.get("ok") else set()
    ans = len(declared & have)
    if not dec:
        level = "warn"  # nothing declared for this datasource yet
    elif ans == dec:
        level = "ok"
    elif ans == 0:
        level = "bad"
    else:
        level = "warn"
    # `db_key not in reporting` = this store was not measured (unreachable adapter, failed
    # query). That is not the same as nothing streaming, so it stays None.
    fresh = None
    if reporting is not None and db_key in reporting:
        fresh = len(declared & reporting[db_key])
    return {
        "declared": dec,
        "with_data": ans,
        "no_data": len(declared - have),
        "level": level,
        "reporting": fresh,  # None = freshness unknown, distinct from 0 = nothing streaming
        "reporting_window_h": _FRESHNESS_WINDOW_H,
    }


@app.get("/api/v1/admin/sensors/health", response_model=APIResponse)
async def sensors_health(
    window_hours: int = 24,
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Per-stream health over the narrow stores (V6-T08), assessed by the sensor_health
    module against the policy's per-modality age limits.

    One MAX(datetime) GROUP BY uuid query per store — never one per sensor. The wide store is
    reported as NOT PROBED per sensor rather than guessed: its per-column scan is a different
    cost class, and a wrong health verdict is worse than a declared gap. Drift needs
    co-located peer values and calibration needs TTL instances (T65); both are named in the
    payload as not-assessed rather than silently skipped.
    """
    from datetime import datetime, timezone

    from orchestrator.services.adapters.registry import adapter_registry
    from orchestrator.services.evidence.policy import load_policy
    from orchestrator.services.evidence.sensor_health import assess_sensor, summarise

    policy = load_policy()
    now = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        local_now = datetime.now(ZoneInfo(settings.BUILDING_TIMEZONE))
    except Exception:
        local_now = now

    declared: Dict[str, set] = {}
    try:
        import json as _json
        from pathlib import Path as _Path

        smap = _json.loads(_Path(settings.SENSOR_MAP_PATH).read_text(encoding="utf-8"))
        for v in smap.values():
            if isinstance(v, dict) and v.get("uuid") and v.get("storage"):
                declared.setdefault(str(v["storage"]), set()).add(str(v["uuid"]))
    except Exception as exc:
        return APIResponse(success=False, error=f"sensor map unavailable: {exc}", data={})

    healths = []
    not_probed: List[str] = []
    for storage_key, uuids in sorted(declared.items()):
        local = _store_local_name(storage_key)
        adapter = adapter_registry.get(storage_key)
        table = getattr(adapter, "table", None)
        if adapter is None or not hasattr(adapter, "execute_query"):
            not_probed.append(f"{local}: no adapter")
            continue
        if not table:
            # Wide shape — per-sensor MAX means scanning every uuid column.
            not_probed.append(f"{local}: wide shape, not probed per sensor")
            continue
        try:
            res = await adapter.execute_query(
                f"SELECT `uuid`, MAX(`datetime`) AS latest FROM `{table}` GROUP BY `uuid`"
            )
        except Exception as exc:
            not_probed.append(f"{local}: query failed ({type(exc).__name__})")
            continue
        if not res.success:
            not_probed.append(f"{local}: query failed")
            continue
        latest_by_uuid = {}
        for row in res.data:
            u, ts = row.get("uuid"), row.get("latest")
            if u is not None and ts is not None:
                latest_by_uuid[str(u)] = ts
        # The policy keys freshness by modality; the store's local name is the closest
        # per-building signal available here, and an unknown name falls to the default limit.
        modality = local.replace("_data", "")
        max_age = policy.max_age_minutes(modality)
        for u in sorted(uuids):
            ts = latest_by_uuid.get(u)
            stamps = []
            if ts is not None:
                if isinstance(ts, str):
                    try:
                        stamps = [datetime.fromisoformat(ts)]
                    except ValueError:
                        stamps = []
                else:
                    stamps = [ts]
            h = assess_sensor(u, stamps, local_now.replace(tzinfo=None), max_age)
            healths.append(
                {
                    "uuid": u,
                    "store": local,
                    "state": h.state.value,
                    "age_minutes": h.age_minutes,
                    "detail": h.detail,
                }
            )

    counts = summarise(
        [type("H", (), {"state": type("S", (), {"value": e["state"]})()})() for e in healths]
    )
    return APIResponse(
        success=True,
        data={
            "assessed": len(healths),
            "by_state": counts,
            "not_probed": not_probed,
            "not_assessed": {
                "drift": "needs co-located peer values; not computed by this endpoint yet",
                "calibration": "no calibration instances declared in any graph (T65)",
            },
            "sensors": healths,
        },
    )


@app.get("/api/v1/admin/databases/answerability", response_model=APIResponse)
async def databases_answerability_batch(
    user: UserContext = Depends(require_permission("system:admin")),
):
    """Answerability for every ACTIVE datasource in ONE request (computed concurrently, so the
    Databases tab shows ✓/◐/✗ per card without firing N probes), plus building-wide totals for
    the declared-vs-populated coverage badge."""
    from orchestrator.services import admin_config

    dbs = admin_config.read_databases()
    active = admin_config.active_db_keys()
    keys = [d["key"] for d in dbs if (active is None) or (d["key"] in active)]

    # One freshness pass for the whole screen, shared by every card (CAVEAT-233).
    reporting = await _reporting_by_local_name(_FRESHNESS_WINDOW_H) if keys else {}

    async def _one(k: str):
        try:
            return k, await _answerability_for(k, reporting=reporting or None)
        except Exception as e:
            logger.debug(f"[answerability-batch] {k}: {e}")
            return k, {"declared": 0, "with_data": 0, "no_data": 0, "level": "warn"}

    pairs = await asyncio.gather(*[_one(k) for k in keys]) if keys else []
    counts = {k: v for k, v in pairs}
    _fresh = [v.get("reporting") for v in counts.values() if v.get("reporting") is not None]
    return APIResponse(
        success=True,
        data={
            "counts": counts,
            "datasources": len(keys),
            "total_declared": sum(v["declared"] for v in counts.values()),
            "total_with_data": sum(v["with_data"] for v in counts.values()),
            # None (not 0) when the probe could not run anywhere: "unknown" and "nothing is
            # streaming" are different answers and only one of them is bad news.
            "total_reporting": sum(_fresh) if _fresh else None,
            "reporting_window_h": _FRESHNESS_WINDOW_H,
        },
    )


@app.get("/api/v1/admin/databases/{db_key}/answerability", response_model=APIResponse)
async def database_answerability(
    db_key: str, user: UserContext = Depends(require_permission("system:admin"))
):
    """Verify a datasource is actually answerable: does the ontology DECLARE sensors stored
    here (ref:storedAt), and do those UUIDs have real rows in the datasource? Closes the loop
    between the two halves — triples vs. data — so an admin sees ✓ answerable / ✗ declared-but-
    no-data at a glance (FIX-004 / CAVEAT-007 made visible)."""
    if not db_key or not all(ch.isalnum() or ch in "._-" for ch in db_key):
        return APIResponse(success=False, error="invalid connection key", data={})

    declared = await _declared_uuids_for_datasource(db_key)
    ures = await _resolve_datasource_uuids(db_key)
    if not ures.get("ok"):
        return APIResponse(
            success=False,
            error=ures.get("error"),
            data={"declared": len(declared), "reachable": False},
        )
    have = set(ures.get("uuids", []))
    answerable = declared & have
    no_data = declared - have

    if not declared:
        verdict, level = (
            "No sensors are declared for this datasource yet — use “Register sensors” to "
            "describe them, then they become answerable.",
            "warn",
        )
    elif not answerable:
        verdict, level = (
            f"{len(declared)} sensor(s) declared, but none of their UUIDs have data in the "
            "datasource yet.",
            "bad",
        )
    elif no_data:
        verdict, level = (
            f"{len(answerable)} of {len(declared)} declared sensor(s) are answerable; "
            f"{len(no_data)} declared UUID(s) have no data yet.",
            "warn",
        )
    else:
        verdict, level = f"All {len(declared)} declared sensor(s) are answerable.", "ok"

    # CAVEAT-233: say how many of those are CURRENT. "Answerable" means rows exist, which is
    # what a historical question needs; a real-time question needs a reading from the window,
    # and the gap between the two numbers is the whole point of reporting them together.
    _rep = await _reporting_by_local_name(_FRESHNESS_WINDOW_H)
    reporting = len(declared & _rep[db_key]) if db_key in _rep else None
    if answerable and reporting is not None:
        # Three distinct sentences: "0 of them reported ... the rest answer historical
        # questions only" reads as though some subset were still live when none is.
        if reporting == 0:
            verdict += (
                f" None of them reported in the last {_FRESHNESS_WINDOW_H} h — this "
                "datasource answers historical questions only."
            )
        elif reporting < len(answerable):
            verdict += (
                f" {reporting} of them reported in the last {_FRESHNESS_WINDOW_H} h; the rest "
                "answer historical questions only."
            )
        else:
            verdict += f" All of them reported in the last {_FRESHNESS_WINDOW_H} h."

    return APIResponse(
        success=True,
        data={
            "declared": len(declared),
            "with_data": len(answerable),
            "reporting": reporting,
            "reporting_window_h": _FRESHNESS_WINDOW_H,
            "no_data": len(no_data),
            "orphan_data": len(have - declared),
            "verdict": verdict,
            "level": level,
            "no_data_sample": list(no_data)[:5],
            "table": ures.get("table"),
        },
    )


# Common Brick sensor/point classes offered as suggestions even on a fresh building with no
# sensors yet; merged with the classes actually present in the active building's graph.
_COMMON_SENSOR_CLASSES = [
    "Air_Temperature_Sensor",
    "Temperature_Sensor",
    "CO2_Sensor",
    "CO2_Level_Sensor",
    "Humidity_Sensor",
    "Relative_Humidity_Sensor",
    "Occupancy_Sensor",
    "Occupancy_Count_Sensor",
    "Illuminance_Sensor",
    "Luminance_Sensor",
    "Noise_Sensor",
    "Sound_Level_Sensor",
    "PM2.5_Sensor",
    "PM10_Sensor",
    "TVOC_Sensor",
    "Air_Quality_Sensor",
    "Energy_Sensor",
    "Power_Sensor",
    "Water_Flow_Sensor",
    "Motion_Sensor",
    "Contact_Sensor",
    "Setpoint",
]


@app.get("/api/v1/admin/onboarding/status", response_model=APIResponse)
async def onboarding_status(user: UserContext = Depends(require_permission("system:admin"))):
    """Per-step readiness for the ACTIVE building (TODO-072).

    Every onboarding step already had an endpoint; what was missing was a way to
    ASK whether they had been done. Without it "is this building ready?" could
    only be answered by putting questions to it and reading the replies, which
    cannot tell a missing step apart from a bad answer.

    Each step reports from the LIVE SYSTEM, not from a checklist: the ontology
    step counts spaces in the graph, the time-series step compares sensors the
    graph DECLARES against UUIDs that actually have rows, and the floor-plan step
    reports how many spaces resolved to an ontology IRI. Identity and ontology
    are marked blocking — without them nothing can be answered at all; documents
    and floor plans narrow what can be answered rather than breaking it.
    """
    from orchestrator.services import admin_config
    from orchestrator.services import onboarding_status as _obs

    # Reuse the batch answerability the Databases tab computes, so opening this
    # screen does not fire a second round of probes at every datasource.
    answerability = None
    try:
        dbs = admin_config.read_databases()
        active = admin_config.active_db_keys()
        keys = [d["key"] for d in dbs if (active is None) or (d["key"] in active)]
        reporting = await _reporting_by_local_name(_FRESHNESS_WINDOW_H) if keys else {}
        pairs = (
            await asyncio.gather(
                *[_answerability_for(k, reporting=reporting or None) for k in keys]
            )
            if keys
            else []
        )
        _fresh = [p.get("reporting") for p in pairs if p.get("reporting") is not None]
        answerability = {
            "total_declared": sum(int(p.get("declared") or 0) for p in pairs),
            "total_with_data": sum(int(p.get("with_data") or 0) for p in pairs),
            "total_reporting": sum(_fresh) if _fresh else None,
            "reporting_window_h": _FRESHNESS_WINDOW_H,
        }
    except Exception as e:
        logger.debug(f"[onboarding-status] answerability unavailable: {e}")

    return APIResponse(success=True, data=await _obs.collect_status(answerability))


@app.get("/api/v1/admin/onboarding/vocab", response_model=APIResponse)
async def onboarding_vocab(user: UserContext = Depends(require_permission("system:admin"))):
    """Vocabulary for the guided sensor form: Brick sensor classes + brick:Location instances
    present in the active building's graph (merged with a common-class baseline), so an admin
    picks from suggestions instead of typing Brick strings / location URIs."""
    from orchestrator.services.ontology_manager import run_sparql_select

    def _locals(rows, key):
        out = []
        for r in rows:
            v = (r.get(key) or "").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            if v:
                out.append(v)
        return out

    classes = set(_COMMON_SENSOR_CLASSES)
    locations: List[str] = []
    try:
        cls_res = await run_sparql_select(
            "PREFIX brick:<https://brickschema.org/schema/Brick#> "
            "PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#> "
            "SELECT DISTINCT ?c WHERE { ?s a ?c . ?c rdfs:subClassOf* brick:Point "
            "FILTER(STRSTARTS(STR(?c), STR(brick:))) }",
            limit=400,
        )
        if cls_res.get("ok"):
            classes.update(_locals(cls_res.get("rows", []), "c"))
        loc_res = await run_sparql_select(
            "PREFIX brick:<https://brickschema.org/schema/Brick#> "
            "PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#> "
            "SELECT DISTINCT ?l WHERE { ?l a ?t . ?t rdfs:subClassOf* brick:Location }",
            limit=1000,
        )
        if loc_res.get("ok"):
            locations = sorted(set(_locals(loc_res.get("rows", []), "l")))
    except Exception as e:
        logger.debug(f"[onboarding_vocab] graph vocab unavailable: {e}")
    return APIResponse(
        success=True,
        data={"sensor_classes": sorted(classes), "locations": locations},
    )


@app.delete("/api/v1/admin/databases/{db_key}", response_model=APIResponse)
async def delete_database_conn(
    db_key: str, user: UserContext = Depends(require_permission("system:admin"))
):
    """Delete a GUI-added connection (curated entries are protected)."""
    from orchestrator.services import admin_config, db_ontology

    try:
        result = admin_config.delete_database(db_key)
    except ValueError as e:
        return APIResponse(success=False, error=str(e), data={})
    # best-effort: clear the connection's sensor named graph too
    try:
        await db_ontology.clear_graph(db_key)
    except Exception:
        pass
    # Drop the now-removed backend from the live pool so a deleted connection stops
    # serving immediately (mirror of create_database's hot-apply — no restart needed).
    try:
        await adapter_registry.reload()
    except Exception as e:
        logger.warning(f"[delete_database] adapter reload failed (restart to drop): {e}")
    return APIResponse(success=True, data=result)


@app.get("/api/v1/admin/services", response_model=APIResponse)
async def list_services(user: UserContext = Depends(require_permission("system:admin"))):
    """Attached-tool launcher: the catalog of admin-facing service UIs (GraphDB, Grafana,
    Adminer, …) with a LIVE online/offline/optional status probed from inside the network.
    The console renders one 'Open' card per service."""
    from orchestrator.services.service_catalog import probe_services

    try:
        services = await probe_services()
    except Exception as e:
        logger.error(f"[services] probe failed: {e}", exc_info=True)
        return APIResponse(success=False, error=str(e), data={"services": []})
    return APIResponse(success=True, data={"services": services})


@app.post("/api/v1/admin/restart", response_model=APIResponse)
async def restart_orchestrator(user: UserContext = Depends(require_permission("system:admin"))):
    """Restart the orchestrator process — Docker's ``restart: unless-stopped`` policy
    brings it back, reloading bind-mounted code and re-running startup.

    NOTE: values baked from ``.env`` at container-create do NOT change on a plain
    restart — use ``docker compose up -d orchestrator`` (recreate) to apply .env edits.
    """

    async def _terminate() -> None:
        # brief delay so the HTTP 200 is delivered before the process exits
        await asyncio.sleep(0.7)
        logger.warning("[admin/restart] console-triggered restart — SIGTERM to self")
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(_terminate())
    return APIResponse(success=True, data={"restarting": True})


# ── Admin console: user management + role→data-source access ──────────────────

_VALID_ROLES = {"admin", "facility_manager", "analyst", "operator", "occupant", "readonly"}


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=12)
    role: str = Field(default="readonly")
    email: Optional[str] = Field(default=None)


class RoleUpdate(BaseModel):
    role: str = Field(..., description="One of the 6 RBAC roles")


class PasswordReset(BaseModel):
    password: str = Field(
        ..., min_length=12, description="New password (12+ chars, same floor as registration)"
    )


class RoleAccessUpdate(BaseModel):
    role: str = Field(...)
    sources: Any = Field(..., description="'*' for all, or a list of data-source ids")


@app.get("/api/v1/admin/users", response_model=APIResponse)
async def list_users(user: UserContext = Depends(require_permission("user:read"))):
    """List all accounts (no secrets) + the valid roles."""
    users = await postgres_manager.list_users() if postgres_manager else []
    return APIResponse(success=True, data={"users": users, "roles": sorted(_VALID_ROLES)})


@app.post("/api/v1/admin/users", response_model=APIResponse)
async def create_user_account(
    body: UserCreate, user: UserContext = Depends(require_permission("user:write"))
):
    """Create a user with a specific role."""
    if body.role not in _VALID_ROLES:
        return APIResponse(success=False, error=f"invalid role '{body.role}'", data={})
    res = await auth_manager.register_user(body.username, body.password, body.email, role=body.role)
    return APIResponse(
        success=bool(res.get("success")),
        error=res.get("error"),
        data={"username": body.username, "role": body.role},
    )


@app.put("/api/v1/admin/users/{username}/role", response_model=APIResponse)
async def update_user_role(
    username: str, body: RoleUpdate, user: UserContext = Depends(require_permission("user:write"))
):
    """Change a user's role."""
    if body.role not in _VALID_ROLES:
        return APIResponse(success=False, error=f"invalid role '{body.role}'", data={})
    ok = await postgres_manager.update_user_role(username, body.role) if postgres_manager else False
    return APIResponse(success=ok, data={"username": username, "role": body.role})


@app.put("/api/v1/admin/users/{username}/password", response_model=APIResponse)
async def reset_user_password(
    username: str,
    body: PasswordReset,
    user: UserContext = Depends(require_permission("user:write")),
):
    """Set a user's password (admin reset) and revoke their live sessions.

    Passwords are stored as one-way Argon2id hashes, so an existing password can
    never be read back — an admin sets a new one instead. The reset takes effect
    immediately for every consumer (chat API, OpenWebUI, admin console): they all
    authenticate against the same Postgres row, so no restart is required.
    """
    res = await auth_manager.set_password(username, body.password)
    return APIResponse(
        success=bool(res.get("success")),
        error=res.get("error"),
        data={
            "username": username,
            "sessions_revoked": res.get("sessions_revoked", 0),
            "restart_required": False,
        },
    )


@app.delete("/api/v1/admin/users/{username}", response_model=APIResponse)
async def delete_user_account(
    username: str, user: UserContext = Depends(require_permission("user:delete"))
):
    """Delete a user (cannot delete your own account).

    Goes through AuthManager.delete_user rather than calling
    postgres_manager.delete_user directly — the Postgres row is only half the
    account; without this, a deleted user's existing Redis session tokens
    stayed valid for up to 7 days (the session TTL) after "deletion".
    AuthManager.delete_user revokes those sessions and the user's cached
    conversation state, then delegates to postgres_manager.delete_user for the
    durable (turn_memory + conversations) cascade.
    """
    if user and getattr(user, "username", None) == username:
        return APIResponse(success=False, error="cannot delete your own account", data={})
    result = await auth_manager.delete_user(username) if auth_manager else {"success": False}
    return APIResponse(success=result.get("success", False), data={"username": username})


@app.get("/api/v1/admin/role-access", response_model=APIResponse)
async def get_role_access(user: UserContext = Depends(require_permission("system:admin"))):
    """Return the role→allowed-sources map + all source ids to build the matrix."""
    from orchestrator.services import admin_config

    reg = getattr(app.state, "datasource_registry", None)
    sources = [s.id for s in reg.list()] if reg else []
    return APIResponse(
        success=True,
        data={
            "access": admin_config.read_role_access(),
            "sources": sources,
            "roles": sorted(_VALID_ROLES),
        },
    )


@app.put("/api/v1/admin/role-access", response_model=APIResponse)
async def put_role_access(
    body: RoleAccessUpdate, user: UserContext = Depends(require_permission("system:admin"))
):
    """Set which data sources a role may use ('*' or a list). Applies immediately."""
    from orchestrator.services import admin_config

    if body.role not in _VALID_ROLES:
        return APIResponse(success=False, error=f"invalid role '{body.role}'", data={})
    try:
        result = admin_config.set_role_access(body.role, body.sources)
    except ValueError as e:
        return APIResponse(success=False, error=str(e), data={})
    return APIResponse(success=True, data=result)


@app.get("/api/v1/floor-plans/{building_id}/{floor}/manifest", response_model=APIResponse)
async def get_floor_plan_manifest(
    building_id: str,
    floor: int,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Return the full FloorPlanManifest JSON for a specific building floor."""
    try:
        from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline

        manifest = get_floor_plan_pipeline().load_manifest(building_id, floor)
        if not manifest:
            raise HTTPException(
                status_code=404,
                detail=f"No manifest for building={building_id}, floor={floor}. "
                "Drop the PDF into /app/input/ and the pipeline will generate it.",
            )
        return APIResponse(success=True, data=manifest.model_dump())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_floor_plan_manifest failed: {e}")
        return APIResponse(success=False, error=str(e), data={})


@app.get("/api/v1/floor-plans/search", response_model=APIResponse)
async def search_floor_plan_spaces(
    q: str,
    building: Optional[str] = None,
    floor: Optional[int] = None,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Cross-floor semantic space search (by label, type, or zone_id)."""
    building = building or settings.BUILDING_ID
    try:
        results = floor_plan_service.search_spaces(q, building_id=building, floor=floor)
        return APIResponse(
            success=True,
            data={"results": results, "total": len(results), "query": q},
        )
    except Exception as e:
        logger.error(f"search_floor_plan_spaces failed: {e}")
        return APIResponse(success=False, error=str(e), data={"results": []})


@app.get("/api/v1/floor-plans/overview", response_model=APIResponse)
async def get_floor_plan_overview(
    building: Optional[str] = None,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Building-level overview: per-floor space counts, types, and plan links."""
    building = building or settings.BUILDING_ID
    try:
        from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline

        pipeline = get_floor_plan_pipeline()
        floors = []
        for bid, fl in pipeline.list_manifests():
            if bid != building:
                continue
            manifest = pipeline.load_manifest(bid, fl)
            if not manifest:
                continue
            type_counts: Dict[str, int] = {}
            for space in manifest.spaces:
                type_counts[space.type] = type_counts.get(space.type, 0) + 1
            floors.append(
                {
                    "floor": fl,
                    "floor_label": manifest.floor_label,
                    "spaces_by_type": type_counts,
                    "total_spaces": len(manifest.spaces),
                    "manifest_url": f"/api/v1/floor-plans/{bid}/{fl}/manifest",
                    "image_url": manifest.rendered_image.png_url,
                    "thumbnail_url": manifest.rendered_image.thumbnail_url,
                    "pdf_url": manifest.pdf_url,
                    "warnings": manifest.warnings,
                }
            )
        markdown = floor_plan_service.get_building_overview_markdown(building)
        return APIResponse(
            success=True,
            data={"building_id": building, "floors": floors, "markdown": markdown},
        )
    except Exception as e:
        logger.error(f"get_floor_plan_overview failed: {e}")
        return APIResponse(success=False, error=str(e), data={})


@app.get("/api/v1/floor-plans/facilities", response_model=APIResponse)
async def get_floor_plan_facilities(
    type: str,
    building: Optional[str] = None,
    user: UserContext = Depends(require_permission("metadata:read")),
):
    """Facility locator — find all spaces of a given type across all floors."""
    building = building or settings.BUILDING_ID
    try:
        results = floor_plan_service.get_facilities_by_type(type, building_id=building)
        return APIResponse(
            success=True,
            data={"facility_type": type, "results": results, "total": len(results)},
        )
    except Exception as e:
        logger.error(f"get_floor_plan_facilities failed: {e}")
        return APIResponse(success=False, error=str(e), data={"results": []})


@app.post("/api/v1/floor-plans/reingest", response_model=APIResponse)
async def reingest_floor_plans(
    building: Optional[str] = None,
    floor: Optional[int] = None,
    user: UserContext = Depends(require_permission("config:write")),
):
    """DW6: Force regeneration of floor plan manifests (PDF + DWG via registry)."""
    try:
        from pathlib import Path

        from orchestrator.services.dwg_pipeline import get_dwg_pipeline
        from orchestrator.services.floor_plan_pipeline import get_floor_plan_pipeline
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry

        registry = get_floor_plan_registry()
        input_dir = Path("/app/input")
        _file_re = _re.compile(
            r"^(?P<bldg>.+?)\s+floor\s+(?P<fl>\d+)\.(?:pdf|dwg|dxf)$", _re.IGNORECASE
        )

        # Collect files to reingest (.dxf routes to the DWG pipeline like .dwg)
        files_to_ingest = []
        for path in sorted(input_dir.glob("*")):
            if path.suffix.lower() not in {".pdf", ".dwg", ".dxf"}:
                continue
            m = _file_re.match(path.name)
            if not m:
                continue
            bid = _re.sub(r"[^a-z0-9]+", "_", m.group("bldg").lower()).strip("_")
            fl = int(m.group("fl"))
            if building and bid != building:
                continue
            if floor is not None and fl != floor:
                continue
            files_to_ingest.append(path)

        # Process each file and merge via registry
        pdf_pipeline = get_floor_plan_pipeline()
        dwg_pipeline = get_dwg_pipeline()
        results_map: dict = {}  # (building_id, floor) → result dict
        # Keep what each pipeline just produced. Re-reading the PDF manifest
        # from disk would return the previous MERGE, because the merged
        # manifest is written to the same path (BUG-198); ingest_all() merges
        # in-memory results for exactly this reason.
        fresh_pdf: dict = {}
        fresh_dwg: dict = {}

        for path in files_to_ingest:
            try:
                if path.suffix.lower() == ".pdf":
                    manifest = await pdf_pipeline.ingest_file(path)
                else:
                    manifest = await dwg_pipeline.ingest_file(path)

                if not manifest:
                    continue
                key = (manifest.building_id, manifest.floor)
                results_map[key] = results_map.get(key) or {
                    "building_id": manifest.building_id,
                    "floor": manifest.floor,
                    "data_sources": [],
                    "spaces": 0,
                    "warnings": 0,
                }
                if path.suffix.lower() == ".pdf":
                    fresh_pdf[key] = manifest
                    results_map[key]["data_sources"].append("pdf")
                    results_map[key]["warnings"] += len(manifest.warnings)
                else:
                    fresh_dwg[key] = manifest
                    results_map[key]["data_sources"].append("dwg")
            except Exception as file_err:
                logger.warning(f"[reingest] {path.name} failed: {file_err}")

        # Run final merge pass for all affected floors
        for bid, fl in list(results_map.keys()):
            try:
                dwg_m = fresh_dwg.get((bid, fl)) or dwg_pipeline.load_manifest(bid, fl)
                pdf_m = fresh_pdf.get((bid, fl)) or pdf_pipeline.load_manifest(bid, fl)
                merged = registry._merge(dwg_m, pdf_m)
                if merged:
                    # Link the MERGED space set — a floor whose PDF has no text
                    # layer has no linked PDF space for a DWG space to inherit an
                    # IRI from, so this is the only place those rooms get one.
                    # Shared with boot-time ingest deliberately: this block used
                    # to be a private copy, and the same inputs linked or did not
                    # depending on which path ran.
                    await registry.link_unlinked_spaces(merged)
                    await registry._write_manifest(merged)
                    await pdf_pipeline._embed_and_index(merged)
                    results_map[(bid, fl)]["schema_version"] = merged.schema_version
                    # Report the MERGED count — the pre-merge PDF count made a
                    # floor whose duplicates had just been collapsed look
                    # unchanged.
                    results_map[(bid, fl)]["spaces"] = len(merged.spaces)
                    results_map[(bid, fl)]["linked"] = sum(
                        1 for s in merged.spaces if s.ontology_iri
                    )
            except Exception as merge_err:
                logger.warning(f"[reingest] merge failed for {bid}/floor {fl}: {merge_err}")

        results = list(results_map.values())
        return APIResponse(
            success=True,
            data={"reingested": results, "total": len(results)},
        )
    except Exception as e:
        logger.error(f"reingest_floor_plans failed: {e}", exc_info=True)
        return APIResponse(success=False, error=str(e), data={})


@app.get("/api/v1/floor-plans/{building_id}/{floor}/polygons", response_model=APIResponse)
async def get_floor_plan_polygons(building_id: str, floor: int):
    """DW5: Return space polygons as JSON for frontend SVG overlay rendering."""
    try:
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry

        manifest = get_floor_plan_registry().load_manifest(building_id, floor)
        if not manifest:
            raise HTTPException(
                status_code=404,
                detail=f"No manifest for building={building_id}, floor={floor}.",
            )

        spaces_with_polygons = []
        for s in manifest.spaces:
            if not s.polygon:
                continue
            spaces_with_polygons.append(
                {
                    "zone_id": s.zone_id,
                    "label": s.label,
                    "type": s.type,
                    "area_m2": s.area_m2,
                    "centroid": s.centroid.model_dump() if s.centroid else None,
                    "polygon": [[p.x, p.y] for p in s.polygon],
                    "adjacent_spaces": s.adjacent_spaces,
                    "sensor_uuids": s.sensor_uuids,
                    "ontology_iri": s.ontology_iri,
                }
            )

        return APIResponse(
            success=True,
            data={
                "building_id": building_id,
                "floor": floor,
                "floor_label": manifest.floor_label,
                "schema_version": manifest.schema_version,
                "total_spaces": len(manifest.spaces),
                "spaces_with_polygons": len(spaces_with_polygons),
                "spaces": spaces_with_polygons,
                "blocks": [
                    {
                        "type": b.type,
                        "block_name": b.block_name,
                        "position": b.position.model_dump(),
                        "layer": b.layer,
                        "space_id": b.space_id,
                    }
                    for b in manifest.blocks
                ],
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_floor_plan_polygons failed: {e}")
        return APIResponse(success=False, error=str(e), data={})


@app.get("/api/v1/floor-plans/{building_id}/{floor}/svg")
async def get_floor_plan_svg(
    building_id: str,
    floor: int,
    width: int = 800,
    height: int = 600,
    show_labels: bool = True,
    show_blocks: bool = True,
):
    """DW5: Return an inline SVG with colour-coded room polygons overlaid on the floor plan."""
    from fastapi.responses import Response as FastAPIResponse

    _TYPE_COLOUR = {
        "office": "#93c5fd",
        "lab": "#86efac",
        "meeting_room": "#fde68a",
        "classroom": "#c4b5fd",
        "lecture": "#a5b4fc",
        "toilet": "#d1d5db",
        "kitchen": "#fdba74",
        "server_room": "#f87171",
        "storage": "#d1fae5",
        "staircase": "#e5e7eb",
        "lift": "#e5e7eb",
        "reception": "#fbcfe8",
        "corridor": "#f3f4f6",
        "utility": "#fef9c3",
        "zone": "#bfdbfe",
        "unknown": "#f9fafb",
    }
    _BLOCK_SYMBOL = {
        "door": "D",
        "window": "W",
        "fire_exit": "FE",
        "sensor": "S",
        "hvac_diffuser": "H",
        "fire_alarm": "FA",
        "light_fixture": "L",
        "power_outlet": "P",
        "equipment": "E",
        "unknown": "?",
    }

    try:
        from orchestrator.services.floor_plan_registry import get_floor_plan_registry

        manifest = get_floor_plan_registry().load_manifest(building_id, floor)
        if not manifest:
            raise HTTPException(
                status_code=404,
                detail=f"No manifest for building={building_id}, floor={floor}.",
            )

        vw, vh = width, height
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}" '
            f'width="{vw}" height="{vh}">',
            f"<title>{manifest.building_name} — {manifest.floor_label}</title>",
            '<rect width="100%" height="100%" fill="#f8fafc" stroke="#e2e8f0"/>',
        ]

        # Background PNG image if available
        if manifest.rendered_image and manifest.rendered_image.png_url:
            parts.append(
                f'<image href="{manifest.rendered_image.png_url}" '
                f'x="0" y="0" width="{vw}" height="{vh}" opacity="0.4"/>'
            )

        # Room polygons
        for s in manifest.spaces:
            if not s.polygon:
                continue
            fill = _TYPE_COLOUR.get(s.type, "#f9fafb")
            pts = " ".join(f"{p.x * vw:.1f},{p.y * vh:.1f}" for p in s.polygon)
            parts.append(
                f'<polygon points="{pts}" fill="{fill}" fill-opacity="0.6" '
                f'stroke="#475569" stroke-width="1">'
                f"<title>{s.label} ({s.zone_id})</title></polygon>"
            )
            # Label at centroid
            if show_labels and s.centroid:
                cx = s.centroid.x * vw
                cy = s.centroid.y * vh
                short = s.zone_id if len(s.zone_id) <= 6 else s.zone_id[:6]
                parts.append(
                    f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="9" '
                    f'text-anchor="middle" dominant-baseline="middle" '
                    f'fill="#1e293b" font-family="monospace">{short}</text>'
                )

        # Block markers
        if show_blocks:
            for b in manifest.blocks:
                bx = b.position.x * vw
                by = b.position.y * vh
                sym = _BLOCK_SYMBOL.get(b.type, "?")
                parts.append(
                    f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="5" '
                    f'fill="#1e40af" opacity="0.7">'
                    f"<title>{b.block_name} ({b.type})</title></circle>"
                )
                if show_labels:
                    parts.append(
                        f'<text x="{bx:.1f}" y="{by:.1f}" font-size="7" '
                        f'text-anchor="middle" dominant-baseline="middle" '
                        f'fill="white" font-family="monospace">{sym}</text>'
                    )

        # Legend
        legend_y = vh - 10
        legend_x = 8
        for stype, colour in list(_TYPE_COLOUR.items())[:6]:
            parts.append(
                f'<rect x="{legend_x}" y="{legend_y - 8}" width="10" height="8" fill="{colour}" stroke="#94a3b8"/>'
            )
            parts.append(
                f'<text x="{legend_x + 12}" y="{legend_y}" font-size="7" fill="#334155">{stype}</text>'
            )
            legend_x += 80

        parts.append("</svg>")
        svg_content = "\n".join(parts)

        return FastAPIResponse(
            content=svg_content,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=300"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_floor_plan_svg failed: {e}")
        return FastAPIResponse(
            content=f'<svg xmlns="http://www.w3.org/2000/svg"><text y="20">Error: {e}</text></svg>',
            media_type="image/svg+xml",
        )


@app.get("/buildings", response_model=APIResponse)
async def list_buildings(
    user: UserContext = Depends(require_permission("building:read")),
):
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

    # nosec B104 — binds inside the container; host exposure is controlled by
    # docker-compose port mapping (only 8000 is published to the host).
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")  # nosec B104
