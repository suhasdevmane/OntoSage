"""
DatabaseSchemaDiscovery — Phase 2.4
======================================
Discovers schema metadata from any attached database at startup.
Works with any DatabaseAdapter subclass.

Usage:
    from orchestrator.services.database_schema_discovery import DatabaseSchemaDiscovery
    discovery = DatabaseSchemaDiscovery(adapter)
    await discovery.run()
    schema_text = discovery.schema_prompt_text   # ready for LLM prompts
    valid_uuids = await discovery.get_valid_uuids(candidate_list)
"""
import sys
sys.path.append('/app')

from typing import List, Optional, Set
from shared.utils import get_logger
from orchestrator.services.database_adapter import DatabaseAdapter, SchemaInfo

logger = get_logger(__name__)


class DatabaseSchemaDiscovery:
    """
    Runs on startup (or on demand) to capture the full schema of the
    attached time-series database and expose it for:
      - LLM prompt injection (via schema_prompt_text)
      - UUID validation (via get_valid_uuids)
      - Timestamp column auto-detection (via timestamp_column)
    """

    def __init__(self, adapter: DatabaseAdapter) -> None:
        self._adapter = adapter
        self._schema: Optional[SchemaInfo] = None
        self._columns: Optional[Set[str]] = None
        self._ready = False

    async def run(self) -> None:
        """Discover schema and column list. Call once at startup."""
        logger.info(f"DatabaseSchemaDiscovery: running for {self._adapter.adapter_type.value}...")
        try:
            self._schema = await self._adapter.get_schema()
            self._columns = await self._adapter.get_columns()
            self._ready = True
            logger.info(
                f"DatabaseSchemaDiscovery: found {len(self._schema.tables)} tables, "
                f"{len(self._columns)} columns. "
                f"Timestamp column: {self._schema.timestamp_column}"
            )
        except Exception as e:
            logger.error(f"DatabaseSchemaDiscovery failed: {e}")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def schema(self) -> Optional[SchemaInfo]:
        return self._schema

    @property
    def schema_prompt_text(self) -> str:
        """Return schema formatted for injection into LLM SQL generation prompts."""
        if not self._schema:
            return "Schema unavailable"
        base = self._schema.as_prompt_text()
        dialect = self._adapter.get_dialect_hints()
        return base + ("\n\n" + dialect if dialect else "")

    @property
    def timestamp_column(self) -> Optional[str]:
        return self._schema.timestamp_column if self._schema else None

    @property
    def all_columns(self) -> Set[str]:
        return self._columns or set()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def get_valid_uuids(self, candidates: List[str]) -> List[str]:
        """
        Filter a list of UUID strings to those that actually exist
        as columns in the database.  Refreshes columns if needed.
        """
        if self._columns is None:
            self._columns = await self._adapter.get_columns()
        return [u for u in candidates if u in self._columns]

    async def refresh(self) -> None:
        """Force a fresh schema discovery (e.g., after table additions)."""
        self._schema = None
        self._columns = None
        self._ready = False
        await self.run()
