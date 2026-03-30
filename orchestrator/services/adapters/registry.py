"""
AdapterRegistry — Phase 2.5
============================
Singleton registry that maps storage location URIs (ref:storedAt values)
to concrete DatabaseAdapter instances.  Allows sql_agent.py to route
queries to the correct backend without any hardcoded connection strings.

Usage:
    from orchestrator.services.adapters.registry import adapter_registry
    await adapter_registry.initialize()
    adapter = adapter_registry.get(storage_uri)          # defaults to mysql
    result  = await adapter.execute_query(sql)
    schema  = adapter_registry.get_schema_text(storage_uri)
"""
import sys
sys.path.append('/app')

from typing import Dict, Optional
from shared.config import settings
from shared.utils import get_logger
from orchestrator.services.database_adapter import (
    AdapterType, DatabaseAdapter, get_adapter_from_storage_uri
)
from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter
from orchestrator.services.database_schema_discovery import DatabaseSchemaDiscovery

logger = get_logger(__name__)


class AdapterRegistry:
    """
    Maintains a pool of DatabaseAdapter instances keyed by AdapterType.
    Provides get() to route a ref:storedAt URI to the right adapter.
    """

    def __init__(self) -> None:
        self._adapters: Dict[AdapterType, DatabaseAdapter] = {}
        self._discoveries: Dict[AdapterType, DatabaseSchemaDiscovery] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Build adapter pool and run schema discovery for each backend."""
        if self._initialized:
            return

        # Always create MySQL adapter (it is the default backend)
        try:
            mysql = MySQLAdapter()
            await mysql.connect()
            self._adapters[AdapterType.MYSQL] = mysql
            disc_mysql = DatabaseSchemaDiscovery(mysql)
            await disc_mysql.run()
            self._discoveries[AdapterType.MYSQL] = disc_mysql
            logger.info("AdapterRegistry: MySQLAdapter ready")
        except Exception as e:
            logger.warning(f"AdapterRegistry: MySQLAdapter initialization failed: {e}")

        # Create PostgreSQL adapter only if PG_HOST is configured
        pg_host = getattr(settings, "PG_HOST", None)
        if pg_host and pg_host not in ("", "localhost", "postgres"):
            try:
                pg = PostgreSQLAdapter()
                await pg.connect()
                self._adapters[AdapterType.POSTGRESQL] = pg
                disc_pg = DatabaseSchemaDiscovery(pg)
                await disc_pg.run()
                self._discoveries[AdapterType.POSTGRESQL] = disc_pg
                logger.info("AdapterRegistry: PostgreSQLAdapter ready")
            except Exception as e:
                logger.warning(f"AdapterRegistry: PostgreSQLAdapter initialization failed: {e}")

        self._initialized = True
        logger.info(
            f"AdapterRegistry: initialized with backends: "
            f"{[t.value for t in self._adapters]}"
        )

    def get(self, storage_uri: Optional[str] = None) -> Optional[DatabaseAdapter]:
        """
        Return the best-matching adapter for a storage URI.
        Falls back to MySQL if no specific match is found.
        Returns None only when no adapters at all are available.
        """
        adapter_type = get_adapter_from_storage_uri(storage_uri or "")
        adapter = self._adapters.get(adapter_type)
        if adapter is None:
            # Graceful fallback to any available adapter
            adapter = self._adapters.get(AdapterType.MYSQL)
        if adapter is None and self._adapters:
            # Last resort: return any available adapter
            adapter = next(iter(self._adapters.values()))
        return adapter

    @property
    def is_available(self) -> bool:
        """True if at least one database adapter is connected."""
        return bool(self._adapters)

    def get_schema_text(self, storage_uri: Optional[str] = None) -> str:
        """Return schema prompt text for the adapter matched to storage_uri."""
        adapter_type = get_adapter_from_storage_uri(storage_uri or "")
        disc = self._discoveries.get(adapter_type) or self._discoveries.get(AdapterType.MYSQL)
        return disc.schema_prompt_text if disc else "Schema unavailable"

    def get_timestamp_column(self, storage_uri: Optional[str] = None) -> str:
        """Return the auto-detected timestamp column for the matched adapter."""
        adapter_type = get_adapter_from_storage_uri(storage_uri or "")
        disc = self._discoveries.get(adapter_type) or self._discoveries.get(AdapterType.MYSQL)
        return (disc.timestamp_column if disc else None) or "Datetime"

    async def get_valid_uuids(self, candidates, storage_uri: Optional[str] = None):
        """Validate UUIDs against the matched adapter's columns."""
        adapter_type = get_adapter_from_storage_uri(storage_uri or "")
        disc = self._discoveries.get(adapter_type) or self._discoveries.get(AdapterType.MYSQL)
        if disc:
            return await disc.get_valid_uuids(candidates)
        return candidates  # pass-through if discovery unavailable

    async def close_all(self) -> None:
        for adapter in self._adapters.values():
            try:
                await adapter.close()
            except Exception:
                pass


# Module-level singleton
adapter_registry = AdapterRegistry()
