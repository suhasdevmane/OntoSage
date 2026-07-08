"""
MySQLAdapter — Phase 2.2
==========================
Implements DatabaseAdapter for MySQL / MariaDB backends using aiomysql.
Encapsulates all MySQL-specific connection, schema introspection, and
query execution logic previously scattered in sql_agent.py.
"""

import sys

sys.path.append("/app")

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

import aiomysql

from orchestrator.services.circuit_breaker import circuit_breaker_for
from orchestrator.services.database_adapter import (
    AdapterType,
    DatabaseAdapter,
    QueryResult,
    SchemaInfo,
)
from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

import re as _re

# SQL keywords that are forbidden for safety.
# Word-boundary regex matches regardless of trailing whitespace/newline variant.
_FORBIDDEN_KEYWORD_RE = _re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|TRUNCATE|GRANT|REVOKE|CREATE|REPLACE)\b",
    _re.IGNORECASE,
)


class MySQLAdapter(DatabaseAdapter):
    """
    MySQL / MariaDB adapter.
    Uses wide-format sensor_data table where each UUID is a COLUMN.
    E.4: Uses aiomysql connection pool to reuse connections across queries.
    """

    adapter_type = AdapterType.MYSQL

    # Pool sizing constants
    _POOL_MIN = 2
    _POOL_MAX = 10

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self._config = {
            "host": host or settings.MYSQL_HOST,
            "port": port or settings.MYSQL_PORT,
            "user": user or settings.MYSQL_USER,
            "password": password or settings.MYSQL_PASSWORD,
            "db": database or settings.MYSQL_DATABASE,
        }
        self._pool: Optional[aiomysql.Pool] = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None
        self._schema_cache_ts: float = 0.0
        self._columns_cache_ts: float = 0.0

    # ------------------------------------------------------------------
    # Pool helpers
    # ------------------------------------------------------------------

    async def _ensure_pool(self) -> aiomysql.Pool:
        """Return the shared pool, creating it on first call."""
        if self._pool is None or self._pool.closed:
            self._pool = await aiomysql.create_pool(
                **self._config,
                minsize=self._POOL_MIN,
                maxsize=self._POOL_MAX,
                autocommit=True,
            )
            logger.info(f"MySQLAdapter: pool created (min={self._POOL_MIN}, max={self._POOL_MAX})")
        return self._pool

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create the connection pool and verify connectivity."""
        try:
            await self._ensure_pool()
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            logger.info("MySQLAdapter: pool ready and connection test passed")
        except Exception as e:
            logger.error(f"MySQLAdapter: pool creation / connection test failed: {e}")
            raise

    async def close(self) -> None:
        """Close the connection pool gracefully."""
        if self._pool and not self._pool.closed:
            self._pool.close()
            await self._pool.wait_closed()
            logger.info("MySQLAdapter: pool closed")

    _CACHE_TTL = 300  # seconds; re-discover schema after 5 minutes

    async def get_schema(self) -> SchemaInfo:
        """Fetch table/column schema, with TTL-bounded caching."""
        import time as _time

        if self._schema_cache and (_time.monotonic() - self._schema_cache_ts) < self._CACHE_TTL:
            return self._schema_cache

        tables = []
        columns: Dict[str, List[tuple]] = {}
        timestamp_col = None

        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SHOW TABLES")
                    rows = await cursor.fetchall()
                    for (table_name,) in rows:
                        tables.append(table_name)
                        safe_name = table_name.replace("`", "")
                        await cursor.execute(f"DESCRIBE `{safe_name}`")
                        col_rows = await cursor.fetchall()
                        col_list = []
                        for col in col_rows:
                            col_name = col[0]
                            col_type = (
                                col[1].decode("utf-8") if isinstance(col[1], bytes) else str(col[1])
                            )
                            col_list.append((col_name, col_type))
                            # Auto-detect timestamp column
                            if not timestamp_col and (
                                "datetime" in col_name.lower()
                                or "timestamp" in col_name.lower()
                                or "date" in col_type.lower()
                                or "time" in col_type.lower()
                            ):
                                timestamp_col = col_name
                        columns[table_name] = col_list
        except Exception as e:
            logger.error(f"MySQLAdapter.get_schema failed: {e}")

        import time as _time

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col,
            adapter_type=AdapterType.MYSQL,
        )
        self._schema_cache_ts = _time.monotonic()
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """Return all column names across all tables (for UUID validation)."""
        import time as _time

        if self._columns_cache is not None and (
            _time.monotonic() - self._columns_cache_ts
        ) < self._CACHE_TTL:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SHOW TABLES")
                    tables = await cursor.fetchall()
                    for (table_name,) in tables:
                        safe_name = table_name.replace("`", "")
                        await cursor.execute(f"DESCRIBE `{safe_name}`")
                        col_rows = await cursor.fetchall()
                        for col in col_rows:
                            cols.add(col[0])
        except Exception as e:
            logger.error(f"MySQLAdapter.get_columns failed: {e}")

        self._columns_cache = cols
        self._columns_cache_ts = _time.monotonic()
        return cols

    def validate_query(self, sql: str) -> bool:
        """Ensure query is SELECT-only and contains no dangerous keywords."""
        sql_stripped = sql.strip()
        first_word = sql_stripped.split()[0].upper() if sql_stripped else ""
        if first_word not in ("SELECT", "WITH", "("):
            raise ValueError("Only SELECT queries are allowed.")
        match = _FORBIDDEN_KEYWORD_RE.search(sql_stripped)
        if match:
            raise ValueError(f"Forbidden keyword detected: {match.group(1)}")
        if sql.count(";") > 1 or (sql.count(";") == 1 and not sql.strip().endswith(";")):
            raise ValueError("Multiple SQL statements are not allowed.")
        return True

    async def execute_query(self, sql: str) -> QueryResult:
        """Validate and execute SQL. Returns a standardized QueryResult."""
        breaker = circuit_breaker_for("mysql")

        try:
            self.validate_query(sql)
        except ValueError as e:
            return QueryResult.failure(str(e), query=sql)

        if not breaker.allow_request():
            return QueryResult.failure(
                "MySQL circuit breaker is OPEN — database unreachable, will retry shortly.",
                query=sql,
            )

        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(sql)
                    rows = await cursor.fetchall()

            # Serialize Decimal / datetime values
            clean_rows = []
            for row in rows:
                clean_row = {}
                for k, v in row.items():
                    if isinstance(v, Decimal):
                        clean_row[k] = float(v)
                    elif isinstance(v, datetime):
                        clean_row[k] = v.isoformat()
                    else:
                        clean_row[k] = v
                clean_rows.append(clean_row)

            logger.info(f"MySQLAdapter: query returned {len(clean_rows)} rows")
            breaker.record_success()
            return QueryResult(success=True, data=clean_rows, row_count=len(clean_rows), query=sql)

        except Exception as e:
            logger.error(f"MySQLAdapter.execute_query error: {e}")
            breaker.record_failure()
            return QueryResult.failure(str(e), query=sql)

    async def write_records(self, records: List[Any]) -> int:
        """Persist feed records (uuid, timestamp, value) into wide sensor_data.

        Each record's ``uuid`` must be an existing column (skipped with a
        warning otherwise — run the matching data/mysql-init/add_*.sql first).
        Upserts on the Datetime primary key so multiple feeds writing the same
        timestamp merge into one row.  Returns the number of records written.
        """
        if not records:
            return 0

        valid_cols = await self.get_columns()
        written = 0
        skipped_cols: Set[str] = set()
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    for rec in records:
                        uuid = getattr(rec, "uuid", None)
                        ts = getattr(rec, "timestamp", None)
                        value = getattr(rec, "value", None)
                        if not uuid or ts is None or value is None:
                            continue
                        if uuid not in valid_cols:
                            skipped_cols.add(uuid)
                            continue
                        await cursor.execute(
                            f"INSERT INTO sensor_data (`Datetime`, `{uuid}`) "
                            f"VALUES (%s, %s) "
                            f"ON DUPLICATE KEY UPDATE `{uuid}` = VALUES(`{uuid}`)",
                            (ts, value),
                        )
                        written += 1
        except Exception as e:
            logger.error(f"MySQLAdapter.write_records error: {e}", exc_info=True)
            return written

        for col in skipped_cols:
            logger.warning(
                f"MySQLAdapter.write_records: no column `{col}` in sensor_data — "
                f"records skipped (apply the feed's ALTER TABLE migration)"
            )
        if written:
            logger.info(f"MySQLAdapter.write_records: wrote {written} record(s)")
        return written

    def get_dialect_hints(self) -> str:
        return (
            "MySQL dialect rules:\n"
            "- Timestamp column: 'Datetime' (capital D), alias as 'timestamp'\n"
            "- Time functions: NOW(), CURDATE(), INTERVAL syntax\n"
            "- Column names are backtick-quoted: `column_name`\n"
            "- Wide format: each UUID is a COLUMN, use UNION ALL to unpivot\n"
            "- Default time window: Datetime >= NOW() - INTERVAL 1 DAY\n"
        )
