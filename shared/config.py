"""
Shared configuration for OntoSage 2.0
Supports both local (Ollama) and cloud (OpenAI) model providers
"""

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


class Settings(BaseSettings):
    """
    Central configuration for all OntoSage services
    """

    # ==================== Model Provider ====================
    MODEL_PROVIDER: Literal["local", "cloud", "openai"] = Field(
        default="local",
        description="Choose 'local' for local Ollama, 'cloud' for cloud Ollama, or 'openai' for OpenAI API",
    )

    # ==================== LLM Configuration ====================
    # Local (Ollama)
    OLLAMA_BASE_URL: str = Field(default="http://ollama:11434", description="Ollama API endpoint")
    OLLAMA_MODEL: str = Field(default="deepseek-r1:32b", description="Ollama model name")

    # Cloud (Ollama Cloud)
    OLLAMA_CLOUD_API_KEY: str = Field(
        default="", description="Ollama Cloud API key", repr=False
    )
    OLLAMA_CLOUD_BASE_URL: str = Field(
        default="https://api.ollama.ai/v1", description="Ollama Cloud API endpoint"
    )
    OLLAMA_CLOUD_MODEL: str = Field(
        default="gpt-oss:120b-cloud", description="Ollama Cloud model name"
    )

    # Cloud (OpenAI)
    OPENAI_API_KEY: str = Field(
        default="",
        description="OpenAI API key (required if MODEL_PROVIDER=openai)",
        repr=False,
    )
    OPENAI_MODEL: str = Field(default="o3-mini", description="OpenAI model for complex tasks (analytics, reports, compliance)")
    OPENAI_MODEL_FAST: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model for fast tasks (intent classification, SPARQL gen, rewrites)",
    )
    OPENAI_TEMPERATURE: float = Field(default=0.1, description="LLM temperature for generation")

    # ==================== Embedding Configuration ====================
    EMBEDDING_PROVIDER: Literal["local", "openai"] = Field(
        default="local",
        description="Choose 'local' for sentence-transformers or 'openai' for OpenAI embeddings",
    )

    # Local embeddings
    EMBEDDING_MODEL_LOCAL: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace model for local embeddings (384 dims)",
    )
    EMBEDDING_DIMENSION_LOCAL: int = Field(
        default=384, description="Embedding dimensions for local model"
    )

    # OpenAI embeddings
    EMBEDDING_MODEL_OPENAI: str = Field(
        default="text-embedding-3-small", description="OpenAI embedding model (1536 dims)"
    )
    EMBEDDING_DIMENSION_OPENAI: int = Field(
        default=1536, description="Embedding dimensions for OpenAI"
    )

    @property
    def embedding_dimension(self) -> int:
        """Get current embedding dimension based on provider"""
        return (
            self.EMBEDDING_DIMENSION_OPENAI
            if self.EMBEDDING_PROVIDER == "openai"
            else self.EMBEDDING_DIMENSION_LOCAL
        )

    @property
    def embedding_model(self) -> str:
        """Get current embedding model based on provider"""
        return (
            self.EMBEDDING_MODEL_OPENAI
            if self.EMBEDDING_PROVIDER == "openai"
            else self.EMBEDDING_MODEL_LOCAL
        )

    # ==================== STT Configuration ====================
    STT_PROVIDER: Literal["local", "openai"] = Field(
        default="openai",  # default switched due to PyAV/FFmpeg build incompatibility
        description="Choose 'local' for faster-whisper or 'openai' for Whisper API",
    )

    WHISPER_MODEL_LOCAL: str = Field(
        default="base", description="Local Whisper model size: tiny, base, small, medium, large"
    )

    # ==================== Service URLs ====================
    QDRANT_URL: str = Field(default="http://qdrant:6333", description="Qdrant vector DB URL")
    REDIS_URL: str = Field(
        default="redis://redis:6379/0", description="Redis URL for state management"
    )

    # Service hosts/ports (for constructing URLs in services)
    REDIS_HOST: str = Field(default="redis", description="Redis hostname")
    REDIS_PORT: int = Field(default=6379, description="Redis port")

    FUSEKI_HOST: str = Field(default="jena-fuseki", description="Fuseki hostname")
    FUSEKI_PORT: int = Field(default=3030, description="Fuseki port")
    FUSEKI_URL: str = Field(
        default="http://fuseki:3030/abacws",
        description="Jena Fuseki SPARQL endpoint for Building 1",
    )

    # GraphDB Configuration (new architecture)
    GRAPHDB_URL: str = Field(default="http://graphdb:7200", description="GraphDB REST API URL")
    GRAPHDB_HOST: str = Field(default="graphdb", description="GraphDB hostname")
    GRAPHDB_PORT: int = Field(default=7200, description="GraphDB port")
    GRAPHDB_REPOSITORY: str = Field(default="bldg", description="GraphDB repository name")
    GRAPHDB_USER: str = Field(default="admin", description="GraphDB username")
    GRAPHDB_PASSWORD: str = Field(
        default="Admin@GraphDB2024", description="GraphDB password", repr=False
    )
    GRAPHDB_SIMILARITY_INDEX: str = Field(
        default="bldg_index", description="GraphDB similarity index name"
    )
    GRAPHDB_USE_SIMILARITY: bool = Field(
        default=True, description="Use GraphDB similarity indexing for entity retrieval"
    )

    # ==================== Postgres User Data Configuration ====================
    POSTGRES_USER_USER: str = Field(
        default="ontobot", description="Postgres username for user data"
    )
    POSTGRES_USER_PASSWORD: str = Field(
        default="ontobot_secret",
        description="Postgres password for user data",
        repr=False,
    )
    POSTGRES_USER_DB: str = Field(
        default="ontobot", description="Postgres database name for user data"
    )
    POSTGRES_USER_HOST: str = Field(
        default="postgres-user-data", description="Postgres hostname for user data"
    )
    POSTGRES_USER_PORT: int = Field(default=5432, description="Postgres port for user data")

    MYSQL_HOST: str = Field(default="mysql", description="MySQL host (Building 1)")
    MYSQL_PORT: int = Field(default=3306, description="MySQL port")
    MYSQL_USER: str = Field(default="root", description="MySQL username")
    MYSQL_PASSWORD: str = Field(
        default="mysql", description="MySQL password", repr=False
    )
    MYSQL_DATABASE: str = Field(default="sensordb", description="MySQL database name")

    RAG_SERVICE_URL: str = Field(default="http://rag-service:8001", description="RAG service URL")
    CODE_EXECUTOR_URL: str = Field(
        default="http://code-executor:8002", description="Code executor URL"
    )
    WHISPER_STT_URL: str = Field(
        default="http://whisper-stt:8003", description="Whisper STT service URL"
    )

    # ==================== BMS (Building Management System) ====================
    BMS_ENDPOINT: str = Field(
        default="",
        description="BMS API endpoint for device control. Empty = simulation mode.",
    )

    # ==================== Alert Monitor ====================
    ALERT_POLL_INTERVAL_SECS: int = Field(
        default=60,
        description="How often AlertMonitor polls sensor data for threshold breaches.",
    )
    ALERT_THRESHOLDS_PATH: str = Field(
        default="/app/config/alert_thresholds.yaml",
        description="Path to YAML file defining sensor alert thresholds.",
    )

    RAG_SERVICE_HOST: str = Field(default="rag-service", description="RAG service hostname")
    RAG_SERVICE_PORT: int = Field(default=8001, description="RAG service port")

    CODE_EXECUTOR_HOST: str = Field(default="code-executor", description="Code executor hostname")
    CODE_EXECUTOR_PORT: int = Field(default=8002, description="Code executor port")

    # ==================== Public URLs ====================
    STATIC_BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Base URL (including protocol) for serving static artifacts such as plots",
    )

    # ==================== Building Configuration ====================
    BUILDING_CONFIG_FILE: str = Field(
        default="config/building_config.yaml",
        description="Path to building-specific YAML config (relative to /app or absolute)",
    )
    BUILDING_ID: str = Field(
        default="bldg1", description="Building identifier (bldg1, bldg2, bldg3)"
    )
    BUILDING_NAME: str = Field(
        default="Abacws Building", description="Human-readable building name"
    )
    BUILDING_NAMESPACE: str = Field(
        default="http://abacwsbuilding.cardiff.ac.uk/abacws#",
        description="Base URI for building ontology instances (ABox namespace). Must end with '#'.",
    )
    BUILDING_PREFIX: str = Field(
        default="bldg", description="Short SPARQL prefix for BUILDING_NAMESPACE (e.g. 'bldg')"
    )
    BUILDING_TIMEZONE: str = Field(
        default="Europe/London",
        description="IANA timezone for the building (e.g. 'Europe/London', 'America/New_York')",
    )

    # Phase 12B — TTL validation at startup.
    # When True, run SHACL conformance check against Brick reference shapes.
    # Requires the optional `brickschema` package; if it's not installed the
    # validator silently skips SHACL even when this is True.
    TTL_VALIDATION_SHACL: bool = Field(
        default=False,
        description=(
            "Run SHACL Brick conformance check on each TTL at startup. "
            "Off by default — adds 5-30s per file and requires brickschema."
        ),
    )

    # Ontology Files
    BRICK_TBOX_FILE: str = Field(
        default="trial/dataset/Brick.ttl",
        description="Brick Schema TBox file (vocabulary definitions)",
    )
    # BUILDING_ABOX_FILE — the per-building ontology ABox.
    # Legacy alias: BLDG1_ABOX_FILE (still honoured via env-var compat shim).
    BUILDING_ABOX_FILE: str = Field(
        default="trial/dataset/bldg1_protege.ttl",
        description=(
            "Per-building ABox file (sensor instances). Renamed from "
            "BLDG1_ABOX_FILE; the old env var is still honoured."
        ),
        validation_alias="BLDG1_ABOX_FILE",
    )

    # RAG Collections
    TBOX_COLLECTION: str = Field(default="brick_schema", description="Qdrant collection for TBox")
    ABOX_COLLECTION: str = Field(
        default="building_instances", description="Qdrant collection for ABox"
    )
    ONTOLOGY_COLLECTION: str = Field(default="ontology", description="Legacy collection name")

    # ==================== Security & Limits ====================
    SECRET_KEY: str = Field(
        default="change-me-in-production-use-32-random-bytes",
        description="JWT signing secret for RBAC tokens. Override via SECRET_KEY env var.",
        repr=False,
    )
    RBAC_ENABLED: bool = Field(
        default=True,
        description="Enable RBAC middleware. Enabled by default for production safety. Set False only for local dev.",
    )
    STRICT_SECRETS: bool = Field(
        default=False,
        description=(
            "When True, refuses to start if any service password equals its "
            "insecure default value. Set to True in all production deployments."
        ),
    )
    RESPONSE_CACHE_ENABLED: bool = Field(
        default=True,
        description="Enable Redis-backed response cache for identical/similar queries.",
    )
    EMBEDDING_CACHE_TTL_SECONDS: int = Field(
        default=86400,
        description="TTL for Redis-cached embeddings (cache:embed:*). Default 24h.",
    )
    WORKFLOW_TIMEOUT_S: int = Field(
        default=120, description="Max seconds for entire workflow execution"
    )
    CODE_EXECUTOR_TIMEOUT: int = Field(default=30, description="Code execution timeout in seconds")
    CODE_EXECUTOR_MEMORY_LIMIT: str = Field(
        default="1g", description="Memory limit for code execution"
    )
    CODE_EXECUTOR_CPU_LIMIT: float = Field(default=1.0, description="CPU limit for code execution")

    MAX_RETRY_ATTEMPTS: int = Field(default=3, description="Max retry attempts for error recovery")
    PLANNER_MAX_STEPS: int = Field(
        default=6, description="Maximum steps for multi-step planner agent"
    )
    MULTI_INTENT_ENABLED: bool = Field(
        default=True,
        description="Enable multi-intent decomposition for compound queries",
    )
    MULTI_INTENT_MIN_LENGTH: int = Field(
        default=50,
        description=(
            "Phase 16A — minimum query length (chars) before multi-intent "
            "decomposition triggers.  Lowered from 80→50 (2026-05-29) after "
            "audit found common compound patterns ('show temp in 5.28 and "
            "tell me where lift is' = 57 chars; 'show floor 3 and how many "
            "rooms' = 55 chars) were missed at the old threshold.  The "
            "explicit-connective gate AND the 2-domain-keyword gate still "
            "guard against false positives; length just skips obviously "
            "short queries from paying the LLM decomposition cost."
        ),
    )

    # ── Phase 19 — Unified user-report / complaint intake ─────────────────────
    REPORT_INTAKE_ENABLED: bool = Field(
        default=True,
        description=(
            "Enable the unified user-report intake (maintenance / complaint / "
            "feedback / safety / suggestion).  Reports are stored in the "
            "`user_reports` Postgres table and viewable in pgAdmin."
        ),
    )
    ADMIN_USERNAMES: str = Field(
        default="admin",
        description=(
            "Comma-separated usernames allowed to call /admin/reports endpoints. "
            "Interim gate until per-user RBAC role assignment is wired into "
            "auth_manager; pgAdmin remains the primary admin surface regardless."
        ),
    )

    SENSOR_MAP_PATH: str = Field(
        default="data/sensor_map.json", description="Path to sensor map cache JSON file"
    )
    OUTPUT_DATA_DIR: str = Field(
        default="outputs/data", description="Directory for analytics data output files"
    )
    QUERY_RESULTS_DIR: str = Field(
        default="/app/outputs/query_results", description="Directory for SPARQL query result files"
    )
    EXPORTS_DIR: str = Field(
        default="/app/outputs/exports",
        description="Directory where DataExportAgent saves downloadable files",
    )
    CORS_ORIGINS: str = Field(
        default="*",
        description="Comma-separated allowed CORS origins. Use '*' for development, explicit URLs for production.",
    )

    REQUEST_TIMEOUT_SECS: int = Field(
        default=150, description="Max seconds for a single pipeline execution before timeout response"
    )

    # ==================== Conversation Settings ====================
    CONVERSATION_TTL: int = Field(
        default=0,
        description=(
            "Conversation state TTL in Redis seconds. "
            "0 = no expiry (count-based eviction via CONVERSATION_MAX_MESSAGES). "
            "Set to e.g. 86400 to re-enable time-based expiry."
        ),
    )
    CONVERSATION_MAX_MESSAGES: int = Field(
        default=20,
        description="Max verbatim messages kept per conversation in Redis hot cache.",
    )
    MAX_CONVERSATION_HISTORY: int = Field(
        default=20, description="Max prior turns injected into LLM context from Redis."
    )

    # ==================== RAG System Selection ====================
    RAG_SYSTEM: Literal["graphdbRAG", "GraphRAG", "RAG_system", "RAG_system_advance"] = Field(
        default="graphdbRAG",
        description="Select RAG system: 'graphdbRAG' (GraphDB similarity), 'GraphRAG' (Microsoft), 'RAG_system', 'RAG_system_advance'",
    )

    # ==================== Ontology Query Mode ====================
    ONTOLOGY_QUERY_MODE: Literal["semantic", "sparql", "hybrid"] = Field(
        default="semantic",
        description="Ontology query strategy: 'semantic' (RAG+LLM only), 'sparql' (traditional), 'hybrid' (semantic with SPARQL fallback)",
    )
    USE_SEMANTIC_ONTOLOGY: bool = Field(
        default=True,
        description="Enable semantic RAG-based ontology querying (bypasses SPARQL generation)",
    )

    # ==================== Logging ====================
    LOG_LEVEL: str = Field(default="INFO", description="Logging level: DEBUG, INFO, WARNING, ERROR")

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"
        populate_by_name = True

    @model_validator(mode="after")
    def _check_strict_secrets(self) -> "Settings":
        """Refuse startup when STRICT_SECRETS=True and any password is the default."""
        if not self.STRICT_SECRETS:
            return self
        _DEFAULT_PASSWORDS = {
            "GRAPHDB_PASSWORD": "Admin@GraphDB2024",
            "POSTGRES_USER_PASSWORD": "ontobot_secret",
            "MYSQL_PASSWORD": "mysql",
        }
        offenders = [
            name
            for name, default in _DEFAULT_PASSWORDS.items()
            if getattr(self, name, None) == default
        ]
        if offenders:
            raise ValueError(
                f"STRICT_SECRETS=true but the following passwords equal their "
                f"insecure defaults — set them via environment variables before "
                f"starting: {', '.join(offenders)}"
            )
        return self

    # ── Backward-compat property for BLDG1_ABOX_FILE → BUILDING_ABOX_FILE ─────
    @property
    def BLDG1_ABOX_FILE(self) -> str:
        """Deprecated alias for BUILDING_ABOX_FILE. Kept for backward compatibility."""
        return self.BUILDING_ABOX_FILE

    @BLDG1_ABOX_FILE.setter
    def BLDG1_ABOX_FILE(self, value: str) -> None:
        self.BUILDING_ABOX_FILE = value

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Load OpenAI credentials from orchestrator/agents/.env if available
        agents_env_path = Path("/app/agents/.env")
        if agents_env_path.exists():
            from dotenv import load_dotenv

            load_dotenv(agents_env_path, override=True)  # Override existing env vars
            # Override with values from agents/.env if present
            if os.getenv("OPENAI_API_KEY"):
                self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
            if os.getenv("OPENAI_MODEL"):
                self.OPENAI_MODEL = os.getenv("OPENAI_MODEL")


# Global settings instance
settings = Settings()


def _load_building_yaml(s: "Settings") -> None:
    """
    Load building-specific values from YAML config file.
    Values from the YAML file are applied ONLY if the corresponding env var
    has not been explicitly set (i.e., still has its default value).
    """
    if not _YAML_AVAILABLE:
        return
    # Resolve config file path
    config_path = Path(s.BUILDING_CONFIG_FILE)
    if not config_path.is_absolute():
        # Try relative to /app (Docker) first, then cwd
        app_path = Path("/app") / config_path
        cwd_path = Path.cwd() / config_path
        if app_path.exists():
            config_path = app_path
        elif cwd_path.exists():
            config_path = cwd_path
        else:
            return  # No YAML file found, use defaults/env vars
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        building = data.get("building", {})
        # Only apply YAML value if env var not explicitly set
        env = os.environ
        if "BUILDING_ID" not in env and building.get("id"):
            s.BUILDING_ID = building["id"]
        if "BUILDING_NAME" not in env and building.get("name"):
            s.BUILDING_NAME = building["name"]
        if "BUILDING_NAMESPACE" not in env and building.get("namespace"):
            s.BUILDING_NAMESPACE = building["namespace"]
        if "BUILDING_PREFIX" not in env and building.get("prefix"):
            s.BUILDING_PREFIX = building["prefix"]
        if "BUILDING_TIMEZONE" not in env and building.get("timezone"):
            s.BUILDING_TIMEZONE = building["timezone"]
        # Ontology files
        if "BRICK_TBOX_FILE" not in env and data.get("building", {}).get("tbox_file"):
            s.BRICK_TBOX_FILE = data["building"]["tbox_file"]
        # BUILDING_ABOX_FILE (formerly BLDG1_ABOX_FILE — alias retained)
        if (
            "BUILDING_ABOX_FILE" not in env
            and "BLDG1_ABOX_FILE" not in env
            and data.get("building", {}).get("abox_file")
        ):
            s.BUILDING_ABOX_FILE = data["building"]["abox_file"]
    except Exception:
        pass  # YAML errors are non-fatal — defaults/env vars remain


def _load_per_building_yaml(s: "Settings") -> None:
    """Phase 9 — also read `input/<BUILDING_ID>/building.yaml` so that the
    same file driving per-building floor plans / storage / aliases can also
    set BUILDING_NAME and BUILDING_NAMESPACE.

    Field mapping in input/<bldg>/building.yaml (FLAT layout):
      building_id:        → settings.BUILDING_ID
      building_name:      → settings.BUILDING_NAME
      ontology_namespace: → settings.BUILDING_NAMESPACE

    Env vars always win over YAML; YAML always wins over hardcoded defaults.
    Non-fatal on any error.
    """
    try:
        import yaml as _yaml
        for base in (Path("/app/input"), Path("input")):
            yaml_path = base / s.BUILDING_ID / "building.yaml"
            if not yaml_path.exists():
                continue
            with open(yaml_path, "r", encoding="utf-8") as fh:
                data = _yaml.safe_load(fh) or {}
            env = os.environ
            if "BUILDING_NAME" not in env and data.get("building_name"):
                s.BUILDING_NAME = data["building_name"]
            if "BUILDING_NAMESPACE" not in env and data.get("ontology_namespace"):
                # input/<bldg>/building.yaml uses `ontology_namespace`; keep
                # the settings field name unchanged for compat.
                s.BUILDING_NAMESPACE = data["ontology_namespace"]
            break
    except Exception:
        pass


# Apply YAML overrides after env-based init
_load_building_yaml(settings)
_load_per_building_yaml(settings)


def _warn_if_building_id_default(s: Settings) -> None:
    """Soft validation: warn (don't fail) when BUILDING_ID is a generic default.

    Production deployments for new buildings should set BUILDING_ID explicitly
    via env var or building.yaml.  Generic defaults like 'bldg1' are reserved
    for the legacy Abacws development environment.
    """
    env_set = "BUILDING_ID" in os.environ
    is_legacy_default = s.BUILDING_ID in ("bldg1", "bldg2", "bldg3")
    if is_legacy_default and not env_set:
        import logging
        _log = logging.getLogger("shared.config")
        _log.warning(
            "BUILDING_ID is at legacy default '%s'. For production deployments "
            "of new buildings, set BUILDING_ID explicitly via env var or "
            "config/building_config.yaml.",
            s.BUILDING_ID,
        )


_warn_if_building_id_default(settings)


def get_llm_config() -> dict:
    """
    Get LLM configuration based on provider.
    Returns dict with model params; 'model_fast' is the lightweight model for
    intent classification, SPARQL generation, and rewrites.
    """
    if settings.MODEL_PROVIDER == "openai":
        return {
            "provider": "openai",
            "model": settings.OPENAI_MODEL,
            "model_fast": settings.OPENAI_MODEL_FAST,
            "api_key": settings.OPENAI_API_KEY,
            "temperature": settings.OPENAI_TEMPERATURE,
        }
    elif settings.MODEL_PROVIDER == "cloud":
        return {
            "provider": "ollama_cloud",
            "base_url": settings.OLLAMA_CLOUD_BASE_URL,
            "model": settings.OLLAMA_CLOUD_MODEL,
            "model_fast": settings.OLLAMA_CLOUD_MODEL,  # same model for cloud Ollama
            "api_key": settings.OLLAMA_CLOUD_API_KEY,
            "temperature": settings.OPENAI_TEMPERATURE,
        }
    else:  # local (Ollama)
        return {
            "provider": "ollama",
            "base_url": settings.OLLAMA_BASE_URL,
            "model": settings.OLLAMA_MODEL,
            "model_fast": settings.OLLAMA_MODEL,  # same model for local Ollama
            "temperature": settings.OPENAI_TEMPERATURE,
        }


def get_embedding_config() -> dict:
    """
    Get embedding configuration based on provider
    """
    if settings.EMBEDDING_PROVIDER == "openai":
        return {
            "provider": "openai",
            "model": settings.EMBEDDING_MODEL_OPENAI,
            "api_key": settings.OPENAI_API_KEY,
            "dimensions": settings.EMBEDDING_DIMENSION_OPENAI,
        }
    else:  # local
        return {
            "provider": "local",
            "model": settings.EMBEDDING_MODEL_LOCAL,
            "dimensions": settings.EMBEDDING_DIMENSION_LOCAL,
        }


def validate_config():
    """
    Validate configuration based on chosen providers.
    Raises ValueError if required settings are missing or semantically invalid.
    Returns True on success.
    """
    # ── API key checks ────────────────────────────────────────────────────────
    if settings.MODEL_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when MODEL_PROVIDER=openai")

    if settings.MODEL_PROVIDER == "cloud" and not settings.OLLAMA_CLOUD_API_KEY:
        raise ValueError("OLLAMA_CLOUD_API_KEY is required when MODEL_PROVIDER=cloud")

    if settings.EMBEDDING_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")

    if settings.STT_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when STT_PROVIDER=openai")

    # ── C.4: Semantic correctness checks ─────────────────────────────────────

    # BUILDING_NAMESPACE must end with '#' or '/'
    ns = settings.BUILDING_NAMESPACE
    if ns and not (ns.endswith("#") or ns.endswith("/")):
        raise ValueError(
            f"BUILDING_NAMESPACE must end with '#' or '/' (got: {ns!r}). "
            "Example: 'http://example.com/building#'"
        )

    # SECRET_KEY must not be the default placeholder in production-like envs
    _is_default_key = settings.SECRET_KEY == "change-me-in-production-use-32-random-bytes"
    if settings.RBAC_ENABLED and _is_default_key:
        raise ValueError(
            "SECRET_KEY must be changed from the default value when RBAC_ENABLED=true. "
            "Generate a strong random key (e.g. `openssl rand -hex 32`)."
        )
    elif _is_default_key:
        import logging as _logging

        _logging.getLogger("shared.config").warning(
            "SECRET_KEY is still the default placeholder. "
            "Set a strong random key before deploying to production."
        )

    return True


async def validate_config_async():
    """
    Async version — performs lightweight connectivity probes in addition to
    the synchronous checks.  Non-fatal: logs warnings rather than raising for
    network checks so that offline/CI environments still start up.

    Returns a dict {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list = []
    warnings: list = []

    # Run synchronous checks first
    try:
        validate_config()
    except ValueError as e:
        errors.append(str(e))

    # ── GraphDB reachability ──────────────────────────────────────────────────
    try:
        import httpx

        url = f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}/rest/info"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code >= 500:
                warnings.append(f"GraphDB returned {resp.status_code} at {url}")
    except Exception as e:
        warnings.append(
            f"GraphDB unreachable at {settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT} — {e}"
        )

    # ── Code executor health ──────────────────────────────────────────────────
    try:
        import httpx

        url = f"http://{settings.CODE_EXECUTOR_HOST}:{settings.CODE_EXECUTOR_PORT}/health"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if not resp.is_success:
                warnings.append(f"Code executor unhealthy: {resp.status_code}")
    except Exception as e:
        warnings.append(
            f"Code executor unreachable at {settings.CODE_EXECUTOR_HOST}:{settings.CODE_EXECUTOR_PORT} — {e}"
        )

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}
