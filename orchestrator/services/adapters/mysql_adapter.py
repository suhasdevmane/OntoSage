"""
MySQLAdapter — Phase 2.2
==========================
Implements DatabaseAdapter for MySQL / MariaDB backends using aiomysql.
Encapsulates all MySQL-specific connection, schema introspection, and
query execution logic previously scattered in sql_agent.py.
"""
import sys
sys.path.append('/app')

import aiomysql
from decimal import Decimal
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from shared.config import settings
from shared.utils import get_logger
from orchestrator.services.database_adapter import (
    DatabaseAdapter, AdapterType, QueryResult, SchemaInfo
)
from orchestrator.services.circuit_breaker import circuit_breaker_for

logger = get_logger(__name__)

# SQL keywords that are forbidden for safety
_FORBIDDEN_KEYWORDS = [
    "DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ",
    "TRUNCATE ", "GRANT ", "REVOKE ", "CREATE ", "REPLACE ",
]


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

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None,
                 user: Optional[str] = None, password: Optional[str] = None,
                 database: Optional[str] = None):
        self._config = {
            "host":     host     or settings.MYSQL_HOST,
            "port":     port     or settings.MYSQL_PORT,
            "user":     user     or settings.MYSQL_USER,
            "password": password or settings.MYSQL_PASSWORD,
            "db":       database or settings.MYSQL_DATABASE,
        }
        self._pool: Optional[aiomysql.Pool] = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None

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

    async def get_schema(self) -> SchemaInfo:
        """Fetch table/column schema, with caching."""
        if self._schema_cache:
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
                        await cursor.execute(f"DESCRIBE {table_name}")
                        col_rows = await cursor.fetchall()
                        col_list = []
                        for col in col_rows:
                            col_name = col[0]
                            col_type = (
                                col[1].decode("utf-8")
                                if isinstance(col[1], bytes)
                                else str(col[1])
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

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col,
            adapter_type=AdapterType.MYSQL,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """Return all column names across all tables (for UUID validation)."""
        if self._columns_cache is not None:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SHOW TABLES")
                    tables = await cursor.fetchall()
                    for (table_name,) in tables:
                        await cursor.execute(f"DESCRIBE {table_name}")
                        col_rows = await cursor.fetchall()
                        for col in col_rows:
                            cols.add(col[0])
        except Exception as e:
            logger.error(f"MySQLAdapter.get_columns failed: {e}")

        self._columns_cache = cols
        return cols

    def validate_query(self, sql: str) -> bool:
        """Ensure query is SELECT-only and contains no dangerous keywords."""
        sql_upper = sql.upper().strip()
        if not (
            sql_upper.startswith("SELECT")
            or sql_upper.startswith("WITH")
            or sql_upper.startswith("(")
        ):
            raise ValueError("Only SELECT queries are allowed.")
        for kw in _FORBIDDEN_KEYWORDS:
            if kw in sql_upper:
                raise ValueError(f"Forbidden keyword detected: {kw.strip()}")
        if sql.count(";") > 1 or (
            sql.count(";") == 1 and not sql.strip().endswith(";")
        ):
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
            return QueryResult(success=True, data=clean_rows,
                               row_count=len(clean_rows), query=sql)

        except Exception as e:
            logger.error(f"MySQLAdapter.execute_query error: {e}")
            breaker.record_failure()
            return QueryResult.failure(str(e), query=sql)

    def get_dialect_hints(self) -> str:
        return (
            "MySQL dialect rules:\n"
            "- Timestamp column: 'Datetime' (capital D), alias as 'timestamp'\n"
            "- Time functions: NOW(), CURDATE(), INTERVAL syntax\n"
            "- Column names are backtick-quoted: `column_name`\n"
            "- Wide format: each UUID is a COLUMN, use UNION ALL to unpivot\n"
            "- Default time window: Datetime >= NOW() - INTERVAL 1 DAY\n"
        )
