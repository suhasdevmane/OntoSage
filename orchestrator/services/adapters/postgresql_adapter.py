"""
PostgreSQLAdapter — Phase 2.3
================================
Implements DatabaseAdapter for PostgreSQL / TimescaleDB using asyncpg.
Supports both wide-column format (like MySQL) and narrow/time-series table format.
"""

import sys

sys.path.append("/app")

import uuid as uuid_mod
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

import asyncpg

from orchestrator.services.database_adapter import (
    AdapterType,
    DatabaseAdapter,
    QueryResult,
    SchemaInfo,
)
from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

_FORBIDDEN_KEYWORDS = [
    "DROP ",
    "DELETE ",
    "INSERT ",
    "UPDATE ",
    "ALTER ",
    "TRUNCATE ",
    "GRANT ",
    "REVOKE ",
    "CREATE ",
    "REPLACE ",
]


class PostgreSQLAdapter(DatabaseAdapter):
    """
    PostgreSQL / TimescaleDB adapter using asyncpg.
    Supports both wide-format (UUID columns) and narrow/hypertable format.
    """

    adapter_type = AdapterType.POSTGRESQL

    def __init__(
        self,
        dsn: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self._dsn = dsn or self._build_dsn(host, port, user, password, database)
        self._pool: Optional[asyncpg.Pool] = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None

    @staticmethod
    def _build_dsn(host, port, user, password, database) -> str:
        h = host or settings.PG_HOST
        p = port or settings.PG_PORT
        u = user or settings.PG_USER
        pw = password or settings.PG_PASSWORD
        db = database or settings.PG_DATABASE
        return f"postgresql://{u}:{pw}@{h}:{p}/{db}"

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create asyncpg connection pool."""
        try:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            logger.info("PostgreSQLAdapter: connection pool created")
        except Exception as e:
            logger.error(f"PostgreSQLAdapter: connect failed: {e}")
            raise

    async def close(self) -> None:
        """Close the asyncpg connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def get_schema(self) -> SchemaInfo:
        """Fetch table/column schema from information_schema."""
        if self._schema_cache:
            return self._schema_cache

        tables = []
        columns: Dict[str, List[tuple]] = {}
        timestamp_col = None

        try:
            conn = await asyncpg.connect(self._dsn)
            # Get tables in public schema
            table_rows = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            for row in table_rows:
                table_name = row["table_name"]
                tables.append(table_name)
                col_rows = await conn.fetch(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1 "
                    "ORDER BY ordinal_position",
                    table_name,
                )
                col_list = []
                for col in col_rows:
                    col_name, col_type = col["column_name"], col["data_type"]
                    col_list.append((col_name, col_type))
                    if not timestamp_col and (
                        "timestamp" in col_name.lower()
                        or "datetime" in col_name.lower()
                        or "timestamp" in col_type.lower()
                    ):
                        timestamp_col = col_name
                columns[table_name] = col_list
            await conn.close()
        except Exception as e:
            logger.error(f"PostgreSQLAdapter.get_schema failed: {e}")

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col,
            adapter_type=AdapterType.POSTGRESQL,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """Return all column names across all public tables."""
        if self._columns_cache is not None:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            conn = await asyncpg.connect(self._dsn)
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            )
            for row in rows:
                cols.add(row["column_name"])
            await conn.close()
        except Exception as e:
            logger.error(f"PostgreSQLAdapter.get_columns failed: {e}")

        self._columns_cache = cols
        return cols

    def validate_query(self, sql: str) -> bool:
        """SELECT-only safety check."""
        sql_upper = sql.upper().strip()
        if not (
            sql_upper.startswith("SELECT")
            or sql_upper.startswith("WITH")
            or sql_upper.startswith("(")
        ):
            raise ValueError("Only SELECT queries are allowed.")
        for kw in _FORBIDDEN_KEYWORDS:
            if kw in sql_upper:
                raise ValueError(f"Forbidden keyword: {kw.strip()}")
        return True

    async def execute_query(self, sql: str) -> QueryResult:
        """Execute query via asyncpg. Returns standardized QueryResult."""
        try:
            self.validate_query(sql)
        except ValueError as e:
            return QueryResult.failure(str(e), query=sql)

        try:
            conn = await asyncpg.connect(self._dsn)
            rows = await conn.fetch(sql)
            await conn.close()

            clean_rows = []
            for row in rows:
                clean_row = {}
                for k in row.keys():
                    v = row[k]
                    if isinstance(v, Decimal):
                        clean_row[k] = float(v)
                    elif isinstance(v, (datetime, date)):
                        clean_row[k] = v.isoformat()
                    elif isinstance(v, uuid_mod.UUID):
                        clean_row[k] = str(v)
                    else:
                        clean_row[k] = v
                clean_rows.append(clean_row)

            logger.info(f"PostgreSQLAdapter: query returned {len(clean_rows)} rows")
            return QueryResult(success=True, data=clean_rows, row_count=len(clean_rows), query=sql)

        except Exception as e:
            logger.error(f"PostgreSQLAdapter.execute_query error: {e}")
            return QueryResult.failure(str(e), query=sql)

    def get_dialect_hints(self) -> str:
        return (
            "PostgreSQL dialect rules:\n"
            "- Timestamp column: usually 'time' or 'timestamp'\n"
            "- Time functions: NOW(), CURRENT_DATE, interval syntax e.g. NOW() - INTERVAL '1 day'\n"
            '- Column names use double-quotes for reserved words: "timestamp"\n'
            "- For TimescaleDB hypertables, use time_bucket() for aggregations\n"
            "- Default time window: timestamp >= NOW() - INTERVAL '1 day'\n"
        )
