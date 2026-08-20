"""
AdapterRegistry — config-driven multi-database routing
=======================================================
Singleton registry that maps storage location URIs (ref:storedAt values from
TTL files) to concrete DatabaseAdapter instances.

Configuration is driven by  config/database_registry.yaml  which maps
TTL identifiers such as "database1" to real adapter configs.

Usage:
    from orchestrator.services.adapters.registry import adapter_registry
    await adapter_registry.initialize()

    # Route a query using the storedAt URI from the SPARQL result
    adapter = adapter_registry.get("bldg:database1")     # → MySQLAdapter
    adapter = adapter_registry.get("bldg:database4")     # → MongoDBAdapter
    adapter = adapter_registry.get("http://...#database5")  # → InfluxDBAdapter

    result  = await adapter.execute_query(query)
    schema  = adapter_registry.get_schema_text("bldg:database1")
"""

import asyncio
import os
import re
import sys

sys.path.append("/app")

from pathlib import Path
from typing import Any, Dict, Optional

from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter
from orchestrator.services.database_adapter import (
    AdapterType,
    DatabaseAdapter,
    get_adapter_from_storage_uri,
)
from orchestrator.services.database_schema_discovery import DatabaseSchemaDiscovery
from shared.utils import get_logger

logger = get_logger(__name__)

# Paths where database_registry.yaml can live (Docker vs local dev).  Phase 9
# moved the canonical home under `input/` so all mutable config sits in one
# place; the legacy `config/` paths are still searched for backward compat.
_REGISTRY_SEARCH_PATHS = [
    Path("/app/input/database_registry.yaml"),
    Path("input/database_registry.yaml"),
    Path("/app/config/database_registry.yaml"),
    Path("config/database_registry.yaml"),
]


# ---------------------------------------------------------------------------
# Environment-variable substitution for YAML values
# ---------------------------------------------------------------------------

_ENV_PATTERN = re.compile(r"\$\{([^}:]+?)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    """
    Resolve  ${VAR_NAME}  and  ${VAR_NAME:-default}  in string values.
    Non-string values are returned unchanged.
    """
    if not isinstance(value, str):
        return value

    def _replace(m: re.Match) -> str:
        var_name = m.group(1)
        default = m.group(2) if m.group(2) is not None else ""
        return os.environ.get(var_name, default)

    return _ENV_PATTERN.sub(_replace, value)


def _expand_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively expand env-var references in all string values of a dict."""
    return {k: _expand_env(v) for k, v in d.items()}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AdapterRegistry:
    """
    Maintains a pool of DatabaseAdapter instances keyed by the TTL
    storedAt identifier (e.g. "database1", "database4").

    Initialization order:
      1. Load config/database_registry.yaml (if present).
      2. For each database entry, create and connect the appropriate adapter.
      3. Fall back to legacy hardcoded MySQL (and optional PostgreSQL) if the
         YAML file is missing, so existing deployments keep working.
    """

    def __init__(self) -> None:
        # key → adapter instance  (e.g. "database1" → MySQLAdapter)
        self._adapters: Dict[str, DatabaseAdapter] = {}
        # key → schema-discovery helper
        self._discoveries: Dict[str, DatabaseSchemaDiscovery] = {}
        self._initialized = False
        self._reload_lock = asyncio.Lock()  # serialises reload() vs itself
        self._custom_keys: set = set()  # GUI-added (custom-overlay) keys — always active

    # ------------------------------------------------------------------
    # Storage-key resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_storage_key(storage_uri: str) -> str:
        """
        Extract the meaningful identifier from a storedAt value.

        Examples
        --------
        "bldg:database1"                          → "database1"
        "http://example.org/bldg#database1"       → "database1"
        "http://example.org/bldg/database1"       → "database1"
        "database1"                               → "database1"
        ""  / None                                → "default"
        """
        if not storage_uri:
            return "default"
        s = storage_uri.strip()
        # Prefixed form: bldg:database1  →  take after ":"
        if ":" in s and not s.startswith("http"):
            return s.split(":", 1)[-1]
        # Full URI: take fragment after "#", or last path segment
        if "#" in s:
            return s.split("#")[-1]
        if "/" in s:
            return s.rstrip("/").split("/")[-1]
        return s

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """
        Build the adapter pool.  Safe to call multiple times (idempotent).
        """
        if self._initialized:
            return

        yaml_config = self._load_yaml_config()
        if yaml_config:
            await self._initialize_from_yaml(yaml_config)
        else:
            logger.warning(
                "AdapterRegistry: database_registry.yaml not found — "
                "falling back to legacy MySQL/PostgreSQL initialization."
            )
            await self._initialize_legacy()

        self._initialized = True
        if self._adapters:
            logger.info(f"AdapterRegistry: ready — backends: " f"{list(self._adapters.keys())}")
        else:
            logger.warning("AdapterRegistry: no database adapters available.")

    async def reload(self) -> None:
        """Rebuild the adapter pool from the current registry + env — no process restart.

        Lets a GUI-added connection become routable immediately: closes the existing
        pools, clears the cache, and re-runs ``initialize()`` against the (just-updated)
        ``database_registry.custom.yaml`` + ``os.environ``. Serialised by a lock; a query
        landing in the brief rebuild window falls back to the default adapter (same
        transient a restart would cause, but far shorter and without dropping the process).
        """
        async with self._reload_lock:
            await self.close_all()
            self._adapters = {}
            self._discoveries = {}
            self._initialized = False
            await self.initialize()
            logger.info("AdapterRegistry: reloaded — %s backend(s)", len(self._adapters))

    # ------------------------------------------------------------------
    # YAML-driven initialization
    # ------------------------------------------------------------------

    def _load_yaml_config(self) -> Optional[Dict[str, Any]]:
        """Try each search path in order and return the parsed YAML, or None."""
        try:
            import yaml
        except ImportError:
            logger.warning("AdapterRegistry: PyYAML not installed — cannot load YAML config.")
            return None

        for path in _REGISTRY_SEARCH_PATHS:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = yaml.safe_load(fh)
                    logger.info(f"AdapterRegistry: loaded config from {path}")
                    # Merge GUI-added connections from a sibling custom overlay so
                    # the curated (heavily-documented) registry is never rewritten.
                    self._merge_custom_databases(path, data, yaml)
                    return data
                except Exception as e:
                    logger.error(f"AdapterRegistry: failed to parse {path}: {e}")
        return None

    def _merge_custom_databases(self, primary: Path, data: Dict[str, Any], yaml_mod) -> None:
        """Merge database_registry.custom.yaml (GUI-added) into the loaded config.

        Curated entries win on a key clash. Non-fatal on any error.
        """
        self._custom_keys = set()  # recomputed each load so a deleted overlay clears it
        try:
            custom = primary.parent / "database_registry.custom.yaml"
            if not custom.is_file() or not isinstance(data, dict):
                return
            overlay = yaml_mod.safe_load(custom.read_text(encoding="utf-8")) or {}
            extra = overlay.get("databases", {})
            if not isinstance(extra, dict):
                return
            # GUI-added keys are an explicit admin opt-in — never filtered by the
            # building.yaml storage filter (which only exists to skip unrelated
            # *curated* backends at startup).
            self._custom_keys = set(extra.keys())
            dbs = data.setdefault("databases", {})
            added = [k for k in extra if k not in dbs]
            for k in added:
                dbs[k] = extra[k]
            if added:
                logger.info(f"AdapterRegistry: merged {len(added)} custom DB(s): {added}")
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"AdapterRegistry: custom DB overlay merge skipped: {e}")

    def _get_active_keys_for_current_building(self) -> Optional[set]:
        """Return the subset of database_registry keys this building actually uses.

        Reads input/<BUILDING_ID>/building.yaml.  If a `storage.databases:`
        block is present, return its contents as a set.  Otherwise return
        None, signalling "initialise every key" (legacy behaviour).

        Failures are non-fatal — any error returns None to preserve legacy
        behaviour rather than blocking startup.
        """
        try:
            from shared.building_paths import resolve_building_file
            from shared.config import settings
            from shared.floor_plan_config import BuildingConfig

            # building.yaml lives flat (input/building.yaml) or nested
            # (input/<id>/building.yaml). Without the flat form the storage filter
            # never activated → every configured adapter was probed at startup.
            yaml_path = resolve_building_file(settings.BUILDING_ID, "building.yaml")
            if yaml_path is not None:
                cfg = BuildingConfig.from_yaml(yaml_path)
                if cfg.storage and cfg.storage.databases:
                    active = set(cfg.storage.databases)
                    logger.info(
                        f"AdapterRegistry: building.yaml storage filter "
                        f"active — using {sorted(active)}"
                    )
                    return active
        except Exception as e:
            logger.debug(f"AdapterRegistry: no per-building storage filter — {e}")
        return None

    async def _initialize_from_yaml(self, config: Dict[str, Any]) -> None:
        """Create and connect one adapter per entry in the databases section.

        When a per-building `storage.databases:` filter exists in
        input/<BUILDING_ID>/building.yaml, only adapters matching that set are
        initialised.  This eliminates startup noise from failed connections to
        unrelated backends.
        """
        databases: Dict[str, Any] = config.get("databases", {})
        if not databases:
            logger.warning("AdapterRegistry: YAML config has no 'databases' section.")
            return

        active_keys = self._get_active_keys_for_current_building()
        if active_keys is not None:
            # GUI-added connections are always active, regardless of the storage filter.
            active_keys = active_keys | self._custom_keys
            skipped = [k for k in databases.keys() if k not in active_keys]
            if skipped:
                logger.info(
                    f"AdapterRegistry: skipping {len(skipped)} unused backends "
                    f"per building.yaml filter"
                )

        for db_key, raw_cfg in databases.items():
            if active_keys is not None and db_key not in active_keys:
                continue
            cfg = _expand_dict(raw_cfg)
            db_type = cfg.get("type", "mysql").lower()
            try:
                adapter = self._build_adapter(db_type, cfg)
                await adapter.connect()
                discovery = DatabaseSchemaDiscovery(adapter)
                await discovery.run()
                self._adapters[db_key] = adapter
                self._discoveries[db_key] = discovery
                logger.info(f"AdapterRegistry: [{db_key}] {db_type} adapter ready")
            except Exception as e:
                logger.warning(f"AdapterRegistry: [{db_key}] {db_type} init failed — {e}")

    def _build_adapter(self, db_type: str, cfg: Dict[str, Any]) -> DatabaseAdapter:
        """Instantiate the correct DatabaseAdapter subclass for db_type."""
        if db_type == "mysql":
            from orchestrator.services.adapters.mysql_adapter import MySQLAdapter

            return MySQLAdapter(
                host=cfg.get("host") or None,
                port=int(cfg.get("port", 3306)) or None,
                user=cfg.get("user") or None,
                password=cfg.get("password") or None,
                database=cfg.get("database") or None,
            )

        if db_type == "mysql_narrow":
            # Narrow (uuid, datetime, value) per-modality table; one backend per table.
            from orchestrator.services.adapters.mysql_narrow_adapter import (
                MySQLNarrowAdapter,
            )

            return MySQLNarrowAdapter(
                table=cfg["table"],
                host=cfg.get("host") or None,
                port=int(cfg.get("port", 3306)) or None,
                user=cfg.get("user") or None,
                password=cfg.get("password") or None,
                database=cfg.get("database") or None,
            )

        if db_type == "mysql_events":
            # V5-T07: generic interval/event store (bookings, work orders,
            # access, alarms, compliance, anomaly episodes) — one per building.
            from orchestrator.services.adapters.mysql_events_adapter import (
                MySQLEventsAdapter,
            )

            return MySQLEventsAdapter(
                host=cfg.get("host") or None,
                port=int(cfg.get("port", 3306)) or None,
                user=cfg.get("user") or None,
                password=cfg.get("password") or None,
                database=cfg.get("database") or None,
            )

        if db_type == "postgresql":
            from orchestrator.services.adapters.postgresql_adapter import (
                PostgreSQLAdapter,
            )

            return PostgreSQLAdapter(
                host=cfg.get("host") or None,
                port=int(cfg.get("port", 5432)) or None,
                user=cfg.get("user") or None,
                password=cfg.get("password") or None,
                database=cfg.get("database") or None,
                # Narrow vs wide layout is detected from this table's schema;
                # omitting it falls back to scanning the whole public schema.
                table=cfg.get("table") or None,
            )

        if db_type == "timescaledb":
            from orchestrator.services.adapters.timescaledb_adapter import (
                TimescaleDBAdapter,
            )

            return TimescaleDBAdapter(
                host=cfg.get("host") or None,
                port=int(cfg.get("port", 5432)) or None,
                user=cfg.get("user") or None,
                password=cfg.get("password") or None,
                database=cfg.get("database") or None,
            )

        if db_type == "mongodb":
            from orchestrator.services.adapters.mongodb_adapter import MongoDBAdapter

            return MongoDBAdapter(
                host=cfg.get("host") or "mongodb",
                port=int(cfg.get("port", 27017)),
                user=cfg.get("user") or None,
                password=cfg.get("password") or None,
                database=cfg.get("database") or "bldg",
                collection=cfg.get("collection") or "sensor_data",
            )

        if db_type == "influxdb":
            from orchestrator.services.adapters.influxdb_adapter import InfluxDBAdapter

            return InfluxDBAdapter(
                url=cfg.get("url") or "http://influxdb:8086",
                token=cfg.get("token") or "",
                org=cfg.get("org") or "ontosage",
                bucket=cfg.get("bucket") or "sensors",
            )

        if db_type == "sqlite":
            from orchestrator.services.adapters.sqlite_adapter import SQLiteAdapter

            return SQLiteAdapter(path=cfg.get("path") or "/app/data/ontosage.db")

        if db_type == "cassandra":
            from orchestrator.services.adapters.cassandra_adapter import (
                CassandraAdapter,
            )

            return CassandraAdapter(
                host=cfg.get("host") or "cassandra",
                port=int(cfg.get("port", 9042)),
                keyspace=cfg.get("keyspace") or "bldg",
                user=cfg.get("user") or None,
                password=cfg.get("password") or None,
                table=cfg.get("table") or "sensor_data",
            )

        if db_type == "redis_timeseries":
            from orchestrator.services.adapters.redis_timeseries_adapter import (
                RedisTimeSeriesAdapter,
            )

            return RedisTimeSeriesAdapter(
                url=cfg.get("url") or "redis://redis:6379/1",
                password=cfg.get("password") or None,
                key_prefix=cfg.get("key_prefix") or "sensor",
            )

        raise ValueError(f"Unknown adapter type: {db_type!r}")

    # ------------------------------------------------------------------
    # Legacy fallback (no YAML)
    # ------------------------------------------------------------------

    async def _initialize_legacy(self) -> None:
        """Mirror the original registry behaviour when no YAML config exists."""
        from shared.config import settings

        try:
            mysql = MySQLAdapter()
            await mysql.connect()
            disc_mysql = DatabaseSchemaDiscovery(mysql)
            await disc_mysql.run()
            self._adapters["database1"] = mysql
            self._adapters["default"] = mysql  # backwards-compat alias
            self._discoveries["database1"] = disc_mysql
            self._discoveries["default"] = disc_mysql
            logger.info("AdapterRegistry(legacy): MySQLAdapter ready as 'database1'/'default'")
        except Exception as e:
            logger.warning(f"AdapterRegistry(legacy): MySQLAdapter failed — {e}")

        pg_host = getattr(settings, "PG_HOST", None)
        if pg_host and pg_host not in ("", "localhost", "postgres"):
            try:
                pg = PostgreSQLAdapter()
                await pg.connect()
                disc_pg = DatabaseSchemaDiscovery(pg)
                await disc_pg.run()
                self._adapters["database2"] = pg
                self._discoveries["database2"] = disc_pg
                logger.info("AdapterRegistry(legacy): PostgreSQLAdapter ready as 'database2'")
            except Exception as e:
                logger.warning(f"AdapterRegistry(legacy): PostgreSQLAdapter failed — {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, storage_uri: Optional[str] = None) -> Optional[DatabaseAdapter]:
        """
        Resolve a storedAt URI to the best-matching adapter.

        1. Extract the key fragment from the URI (e.g. "database4").
        2. Look it up in the adapter pool.
        3. If not found, fall back to "default" → then any available adapter.
        """
        key = self._resolve_storage_key(storage_uri or "")
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = self._adapters.get("default")
        if adapter is None and self._adapters:
            adapter = next(iter(self._adapters.values()))
        return adapter

    @property
    def is_available(self) -> bool:
        """True if at least one database adapter is connected."""
        return bool(self._adapters)

    def get_schema_text(self, storage_uri: Optional[str] = None) -> str:
        """Return schema prompt text for the adapter matched to storage_uri."""
        key = self._resolve_storage_key(storage_uri or "")
        disc = (
            self._discoveries.get(key)
            or self._discoveries.get("default")
            or (next(iter(self._discoveries.values())) if self._discoveries else None)
        )
        return disc.schema_prompt_text if disc else "Schema unavailable"

    def get_timestamp_column(self, storage_uri: Optional[str] = None) -> str:
        """Return the auto-detected timestamp column for the matched adapter."""
        key = self._resolve_storage_key(storage_uri or "")
        disc = (
            self._discoveries.get(key)
            or self._discoveries.get("default")
            or (next(iter(self._discoveries.values())) if self._discoveries else None)
        )
        return (disc.timestamp_column if disc else None) or "Datetime"

    async def get_valid_uuids(self, candidates: list, storage_uri: Optional[str] = None) -> list:
        """Validate UUIDs against the matched adapter's column/field list."""
        key = self._resolve_storage_key(storage_uri or "")
        disc = (
            self._discoveries.get(key)
            or self._discoveries.get("default")
            or (next(iter(self._discoveries.values())) if self._discoveries else None)
        )
        if disc:
            return await disc.get_valid_uuids(candidates)
        return candidates  # pass-through if discovery unavailable

    async def close_all(self) -> None:
        """Gracefully close all adapter connections."""
        seen = set()
        for adapter in self._adapters.values():
            adapter_id = id(adapter)
            if adapter_id in seen:
                continue
            seen.add(adapter_id)
            try:
                await adapter.close()
            except Exception:
                pass


# Module-level singleton — import this everywhere
adapter_registry = AdapterRegistry()
