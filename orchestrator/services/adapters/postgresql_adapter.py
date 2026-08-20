"""
PostgreSQLAdapter — Phase 2.3
================================
Implements DatabaseAdapter for PostgreSQL / TimescaleDB using asyncpg.
Supports both wide-column format (like MySQL) and narrow/time-series table format.
"""

import sys

sys.path.append("/app")

import re
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

_UUID_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.IGNORECASE
)

# A usable bound is a full calendar date, optionally with a time.
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ ]\d{2}:\d{2}(:\d{2})?)?$")

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
        table: Optional[str] = None,
    ):
        self._dsn = dsn or self._build_dsn(host, port, user, password, database)
        self._table = table
        self._pool: Optional[asyncpg.Pool] = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None
        self._narrow: Optional[Dict[str, str]] = None
        self._narrow_checked = False

    @staticmethod
    def _build_dsn(host, port, user, password, database) -> str:
        """Fill in whatever the caller left out from the deployment's settings.

        This used to read ``settings.PG_HOST`` / ``PG_PORT`` / ``PG_USER`` /
        ``PG_PASSWORD`` / ``PG_DATABASE``. None of those exist — the settings are
        named ``POSTGRES_USER_*`` — so ANY caller that omitted a single field got
        an ``AttributeError`` on a phantom attribute rather than a connection or
        a usable error (TODO-143). It went unnoticed because the registry always
        passes all five from the datasource entry, so the fallback was never
        taken until a test constructed the adapter directly.

        ``database`` has no safe default and is therefore required: the only
        Postgres this deployment knows about holds users and conversation
        memory, and silently pointing a SENSOR adapter at it would connect fine
        and return nothing, which is the worst of the three outcomes.
        """
        h = host or settings.POSTGRES_USER_HOST
        p = port or settings.POSTGRES_USER_PORT
        u = user or settings.POSTGRES_USER_USER
        pw = password or settings.POSTGRES_USER_PASSWORD
        db = database
        if not db:
            raise ValueError(
                "PostgreSQLAdapter needs a database name: pass database=... or set it "
                "on the datasource entry in database_registry.yaml. There is no safe "
                "default — the deployment's own Postgres holds users, not readings."
            )
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

    # Column-name hints used to recognise a narrow (uuid, time, value) table.
    # These are layout conventions, not building facts — nothing here names a
    # site, sensor or namespace, so any building's narrow table matches.
    _UUID_COL_HINTS = ("uuid", "sensor_id", "sensor_uuid", "point_id", "series_id")
    _VALUE_COL_HINTS = ("value", "reading", "measurement")

    async def _detect_narrow(self) -> Optional[Dict[str, str]]:
        """Identify a narrow time-series layout: one row per (sensor, timestamp).

        Wide tables carry one column per sensor UUID; narrow tables carry the
        UUID as a row value. The two need different validation and different
        SQL, so the layout is discovered from the live schema rather than
        assumed or configured per building.
        """
        if self._narrow_checked:
            return self._narrow
        self._narrow_checked = True
        try:
            conn = await asyncpg.connect(self._dsn)
            if self._table:
                rows = await conn.fetch(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1",
                    self._table,
                )
            else:
                rows = await conn.fetch(
                    "SELECT table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            await conn.close()
        except Exception as e:
            logger.error(f"PostgreSQLAdapter._detect_narrow failed: {e}")
            return None

        by_table: Dict[str, List[tuple]] = {}
        for r in rows:
            by_table.setdefault(r["table_name"], []).append((r["column_name"], r["data_type"]))

        for table, cols in by_table.items():
            names = {c.lower(): c for c, _ in cols}
            uuid_col = next((names[h] for h in self._UUID_COL_HINTS if h in names), None)
            value_col = next((names[h] for h in self._VALUE_COL_HINTS if h in names), None)
            ts_col = next(
                (c for c, t in cols if "timestamp" in t.lower() or "date" in t.lower()),
                None,
            )
            if uuid_col and value_col and ts_col:
                layout = {"table": table, "uuid": uuid_col, "ts": ts_col, "value": value_col}
                self._narrow = layout
                logger.info(
                    f"PostgreSQLAdapter: narrow layout detected — {table}"
                    f"({uuid_col}, {ts_col}, {value_col})"
                )
                return layout
        return None

    async def get_columns(self) -> Set[str]:
        """Return the identifiers a UUID can validly match.

        For a wide table that is the column names. For a narrow table the UUIDs
        live in rows, so the distinct row values are returned instead —
        otherwise every narrow-backed sensor is reported as missing from the
        database even when its readings are present.
        """
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

        narrow = await self._detect_narrow()
        if narrow:
            try:
                conn = await asyncpg.connect(self._dsn)
                vals = await conn.fetch(
                    f'SELECT DISTINCT "{narrow["uuid"]}" AS u FROM "{narrow["table"]}"'
                )
                await conn.close()
                cols |= {str(v["u"]) for v in vals if v["u"]}
            except Exception as e:
                logger.error(f"PostgreSQLAdapter.get_columns (narrow uuids) failed: {e}")

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

    def build_timeseries_query(
        self,
        uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> Optional[str]:
        """Native narrow SELECT returning (timestamp, uuid, value), like the wide path.

        Returns None for a wide table so sql_agent keeps using its own builder.
        ``limit`` applies per uuid via ROW_NUMBER(): a flat LIMIT across a
        multi-sensor result returns the newest rows *combined*, which silently
        drops whole sensors whose readings sort behind a chattier one.
        """
        narrow = self._narrow
        if not narrow:
            return None
        safe = [u for u in uuids if _UUID_RE.match(str(u))]
        if not safe:
            return None

        tbl, ucol, tcol, vcol = (
            narrow["table"],
            narrow["uuid"],
            narrow["ts"],
            narrow["value"],
        )
        in_list = ", ".join(f"'{u}'" for u in safe)
        clauses = [f'"{ucol}" IN ({in_list})']
        start = self._sanitize_dt(start_date)
        end = self._sanitize_dt(end_date)
        if start:
            clauses.append(f"\"{tcol}\" >= '{start}'")
        elif not end:
            clauses.append(f"\"{tcol}\" >= NOW() - INTERVAL '30 days'")
        if end:
            clauses.append(f"\"{tcol}\" <= '{end}'")
        where = " AND ".join(clauses)
        per_uuid = int(limit)
        outer_cap = per_uuid * max(1, len(safe))
        return (
            'SELECT "timestamp", "uuid", "value" FROM ('
            f'SELECT "{tcol}" AS timestamp, "{ucol}" AS uuid, "{vcol}" AS value, '
            f'ROW_NUMBER() OVER (PARTITION BY "{ucol}" ORDER BY "{tcol}" DESC) AS rn '
            f'FROM "{tbl}" WHERE {where} AND "{vcol}" IS NOT NULL'
            ") ranked "
            f"WHERE rn <= {per_uuid} "
            f'ORDER BY "uuid", "timestamp" DESC LIMIT {outer_cap};'
        )

    @staticmethod
    def _sanitize_dt(dt: Optional[str]) -> Optional[str]:
        """Accept only a full calendar date (optionally with a time), else None.

        Stripping non-date characters is not enough: a relative phrase like
        "-24 hours" reduces to "-24", which Postgres reads as a timezone
        displacement and rejects the whole query. Anything that is not an
        unambiguous timestamp is treated as absent so the default window applies.
        """
        if not dt:
            return None
        s = str(dt).strip().replace("T", " ")
        if _DT_RE.match(s):
            return s[:19]
        return None

    def get_dialect_hints(self) -> str:
        return (
            "PostgreSQL dialect rules:\n"
            "- Timestamp column: usually 'time' or 'timestamp'\n"
            "- Time functions: NOW(), CURRENT_DATE, interval syntax e.g. NOW() - INTERVAL '1 day'\n"
            '- Column names use double-quotes for reserved words: "timestamp"\n'
            "- For TimescaleDB hypertables, use time_bucket() for aggregations\n"
            "- Default time window: timestamp >= NOW() - INTERVAL '1 day'\n"
        )
