"""
SQLiteAdapter
=============
DatabaseAdapter for SQLite using aiosqlite (fully async).

Standard SQL SELECT queries work exactly like MySQL/PostgreSQL.
Useful for:
  - Local development / testing without a running server
  - Lightweight building deployments where sensor data is stored in a .db file
  - Unit tests (in-memory ":memory:" database)

Install: pip install aiosqlite
"""
import sys
sys.path.append('/app')

import aiosqlite
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

from shared.utils import get_logger
from orchestrator.services.database_adapter import (
    DatabaseAdapter, AdapterType, QueryResult, SchemaInfo
)

logger = get_logger(__name__)

_FORBIDDEN_KEYWORDS = [
    "DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ",
    "TRUNCATE ", "ATTACH ", "DETACH ", "PRAGMA ",
]


class SQLiteAdapter(DatabaseAdapter):
    """
    SQLite adapter using aiosqlite.
    Supports both wide-format tables (UUIDs as columns) and narrow tables.
    """

    adapter_type = AdapterType.SQLITE

    def __init__(self, path: str = "/app/data/ontosage.db") -> None:
        self._path = path
        # aiosqlite manages one connection per call — no persistent pool needed
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Verify the SQLite file is accessible (or create it if new)."""
        try:
            async with aiosqlite.connect(self._path) as db:
                await db.execute("SELECT 1")
            logger.info(f"SQLiteAdapter: connected to {self._path}")
        except ImportError:
            raise RuntimeError("aiosqlite is not installed. Run: pip install aiosqlite")
        except Exception as e:
            logger.error(f"SQLiteAdapter: connect failed: {e}")
            raise

    async def close(self) -> None:
        """No persistent connection to close for SQLite."""
        pass

    async def get_schema(self) -> SchemaInfo:
        """Discover tables and columns via sqlite_master."""
        if self._schema_cache:
            return self._schema_cache

        tables:       List[str]              = []
        columns:      Dict[str, List[tuple]] = {}
        timestamp_col: Optional[str]         = None

        try:
            async with aiosqlite.connect(self._path) as db:
                db.row_factory = aiosqlite.Row
                # List all tables
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ) as cur:
                    for row in await cur.fetchall():
                        tables.append(row["name"])

                for table in tables:
                    async with db.execute(f"PRAGMA table_info({table})") as cur:
                        col_list: List[tuple] = []
                        for col in await cur.fetchall():
                            col_name = col["name"]
                            col_type = col["type"]
                            col_list.append((col_name, col_type))
                            if not timestamp_col and any(
                                kw in col_name.lower()
                                for kw in ("timestamp", "datetime", "time", "date")
                            ):
                                timestamp_col = col_name
                        columns[table] = col_list
        except Exception as e:
            logger.error(f"SQLiteAdapter.get_schema failed: {e}")

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col or "timestamp",
            adapter_type=AdapterType.SQLITE,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """Return all column names across all tables."""
        if self._columns_cache is not None:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            async with aiosqlite.connect(self._path) as db:
                async with db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ) as cur:
                    tables = [row[0] for row in await cur.fetchall()]
                for table in tables:
                    async with db.execute(f"PRAGMA table_info({table})") as cur:
                        for col in await cur.fetchall():
                            cols.add(col[1])  # col[1] = column name
        except Exception as e:
            logger.error(f"SQLiteAdapter.get_columns failed: {e}")

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
        if sql.count(";") > 1 or (
            sql.count(";") == 1 and not sql.strip().endswith(";")
        ):
            raise ValueError("Multiple SQL statements are not allowed.")
        return True

    async def execute_query(self, sql: str) -> QueryResult:
        """Execute a SQLite SELECT query."""
        try:
            self.validate_query(sql)
        except ValueError as e:
            return QueryResult.failure(str(e), query=sql)

        try:
            async with aiosqlite.connect(self._path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql) as cur:
                    rows = await cur.fetchall()

            clean_rows: List[Dict[str, Any]] = []
            for row in rows:
                clean: Dict[str, Any] = {}
                for k in row.keys():
                    v = row[k]
                    if isinstance(v, Decimal):
                        clean[k] = float(v)
                    elif isinstance(v, (datetime, date)):
                        clean[k] = v.isoformat()
                    else:
                        clean[k] = v
                clean_rows.append(clean)

            logger.info(f"SQLiteAdapter: query returned {len(clean_rows)} rows")
            return QueryResult(success=True, data=clean_rows,
                               row_count=len(clean_rows), query=sql)

        except Exception as e:
            logger.error(f"SQLiteAdapter.execute_query error: {e}")
            return QueryResult.failure(str(e), query=sql)

    def get_dialect_hints(self) -> str:
        return (
            "SQLite dialect rules:\n"
            "- Timestamp column: usually 'timestamp' or 'datetime' (TEXT or REAL).\n"
            "- Time functions: datetime('now'), datetime('now', '-1 day'),\n"
            "  strftime('%Y-%m-%dT%H:%M:%S', timestamp).\n"
            "- No backticks — use double-quotes for column names: \"timestamp\".\n"
            "- UNION ALL supported for unpivoting wide-format tables.\n"
            "- Default time window: timestamp >= datetime('now', '-1 day')\n"
            "- Return ONLY the SQL query, no markdown."
        )
