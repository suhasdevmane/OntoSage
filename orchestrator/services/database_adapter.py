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

sys.path.append("/app")

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class AdapterType(str, Enum):
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    TIMESCALEDB = "timescaledb"  # PostgreSQL + hypertable extension
    MONGODB = "mongodb"
    INFLUXDB = "influxdb"  # InfluxDB 2.x (Flux queries)
    SQLITE = "sqlite"
    CASSANDRA = "cassandra"  # Apache Cassandra (CQL)
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

    #: How many columns of one table are worth naming in a prompt.
    #:
    #: A WIDE time-series table has one column per sensor, so its schema grows with the
    #: building. Naming all of them cost 45,573 characters on a 704-column table against a
    #: 16,384-token context: the model returned an EMPTY COMPLETION, SQL generation failed,
    #: and the report lane produced a report with no data in it rather than an error
    #: (BUG-474). Nothing about that is specific to one building — the next building is
    #: worse, and this one stops at 704 only because InnoDB stops at 1,017.
    PROMPT_COLUMN_BUDGET = 60

    def as_prompt_text(self, keep_columns: Optional[Set[str]] = None) -> str:
        """Format schema for use in LLM prompts, naming only the columns that matter.

        `keep_columns` is the set the caller actually intends to query. A table within
        budget is listed in full, as before. A table over budget is reduced to those
        columns plus the timestamp column, and the omission is STATED with a count — so
        the model is never left to infer that a column it cannot see does not exist.
        """
        keep = {str(c) for c in (keep_columns or set())}
        lines = ["Database Schema:"]
        for table in self.tables:
            cols = self.columns.get(table, [])
            lines.append(f"\nTable: {table}")
            if len(cols) <= self.PROMPT_COLUMN_BUDGET:
                for col_name, col_type in cols:
                    lines.append(f"  - {col_name} ({col_type})")
                continue

            shown: List[str] = []
            omitted = 0
            for col_name, col_type in cols:
                wanted = col_name in keep or col_name == self.timestamp_column
                # With no caller preference, keep a few anyway: a wide table is only
                # usable if the model can see what its column names LOOK like.
                sample = not keep and len(shown) < 8
                if wanted or sample:
                    shown.append(f"  - {col_name} ({col_type})")
                else:
                    omitted += 1
            lines.extend(shown)
            if omitted:
                lines.append(
                    f"  ... and {omitted} further columns of the same shape, not listed "
                    "here. Their absence is a limit of this prompt, NOT evidence that "
                    "the data is missing."
                )
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
