"""
DatabaseAdapter — Phase 2.1
==============================
Abstract base class for all time-series database adapters.
Concrete implementations (MySQL, PostgreSQL, InfluxDB…) subclass this.

Usage:
    from orchestrator.services.database_adapter import DatabaseAdapter, AdapterType
    adapter = MySQLAdapter(config)          # in MySQLAdapter
    schema = await adapter.get_schema()
    columns = await adapter.get_columns()
    results = await adapter.execute_query(sql)
"""
import sys
sys.path.append('/app')

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class AdapterType(str, Enum):
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    TIMESCALEDB = "timescaledb"     # PostgreSQL + hypertable extension
    MONGODB = "mongodb"
    INFLUXDB = "influxdb"           # InfluxDB 2.x (Flux queries)
    SQLITE = "sqlite"
    CASSANDRA = "cassandra"         # Apache Cassandra (CQL)
    REDIS_TIMESERIES = "redis_timeseries"  # Redis with RedisTimeSeries module


@dataclass
class QueryResult:
    """Standardized result container for any database query."""
    success: bool
    data: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    query: str = ""
    error: Optional[str] = None
    schema: Optional[str] = None

    @classmethod
    def failure(cls, error: str, query: str = "") -> "QueryResult":
        return cls(success=False, error=error, query=query)


@dataclass
class SchemaInfo:
    """Database schema metadata."""
    tables: List[str] = field(default_factory=list)
    # table_name → list of (column_name, column_type)
    columns: Dict[str, List[tuple]] = field(default_factory=dict)
    timestamp_column: Optional[str] = None
    adapter_type: AdapterType = AdapterType.MYSQL

    def as_prompt_text(self) -> str:
        """Format schema for use in LLM prompts."""
        lines = ["Database Schema:"]
        for table in self.tables:
            lines.append(f"\nTable: {table}")
            for col_name, col_type in self.columns.get(table, []):
                lines.append(f"  - {col_name} ({col_type})")
        if self.timestamp_column:
            lines.append(
                f"\n⚠️  CRITICAL: The timestamp column is named '{self.timestamp_column}' "
                "(case-sensitive). Always use this name in SELECT/WHERE/ORDER BY."
            )
        lines.append(f"\nDialect: {self.adapter_type.value}")
        return "\n".join(lines)


class DatabaseAdapter(ABC):
    """
    Abstract base class for time-series database adapters.
    All adapters must implement this interface so that sql_agent.py
    can work with any backend without modification.
    """

    adapter_type: AdapterType

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the database."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the database connection."""
        ...

    @abstractmethod
    async def get_schema(self) -> SchemaInfo:
        """Return schema metadata (tables and columns)."""
        ...

    @abstractmethod
    async def get_columns(self) -> set:
        """Return set of all column names across all tables (for UUID validation)."""
        ...

    @abstractmethod
    async def execute_query(self, sql: str) -> QueryResult:
        """Validate and execute a SQL/query string. Returns a standardized QueryResult."""
        ...

    @abstractmethod
    def validate_query(self, sql: str) -> bool:
        """
        Validate query for safety (SELECT-only, no DML/DDL).
        Raise ValueError if unsafe.  Return True if safe.
        """
        ...

    def get_dialect_hints(self) -> str:
        """
        Return query language / dialect-specific prompt hints for the LLM.
        Subclasses override to provide backend-specific rules.
        """
        return ""

    def build_timeseries_query(
        self,
        uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> Optional[str]:
        """
        Build a native query string to fetch time-series rows for the given UUIDs.

        Returns None for SQL-based adapters — sql_agent will fall back to its
        own _build_uuid_union_query() SQL builder.

        Non-SQL adapters (MongoDB, InfluxDB, Redis TS) MUST override this and
        return a native query string that their execute_query() understands.
        """
        return None


def get_adapter_from_storage_uri(storage_uri: str) -> AdapterType:
    """
    Infer adapter type from a ref:storedAt URI or storage key fragment.
    Used as a fallback when the database_registry.yaml key is not found.

    Examples:
        "postgres://..."    → POSTGRESQL
        "timescale"         → TIMESCALEDB
        "influx://..."      → INFLUXDB
        "mongodb://..."     → MONGODB
        "cassandra://..."   → CASSANDRA
        "redis://..."       → REDIS_TIMESERIES
        "sqlite:/..."       → SQLITE
        anything else       → MYSQL (default)
    """
    s = (storage_uri or "").lower()
    if "timescale" in s:
        return AdapterType.TIMESCALEDB
    if "postgres" in s or "pg:" in s or "pghost" in s:
        return AdapterType.POSTGRESQL
    if "influx" in s:
        return AdapterType.INFLUXDB
    if "mongo" in s:
        return AdapterType.MONGODB
    if "cassandra" in s or "cql" in s:
        return AdapterType.CASSANDRA
    if "redis" in s:
        return AdapterType.REDIS_TIMESERIES
    if "sqlite" in s:
        return AdapterType.SQLITE
    # Default: MySQL
    return AdapterType.MYSQL
