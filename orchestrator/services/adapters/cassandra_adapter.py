"""
CassandraAdapter
================
DatabaseAdapter for Apache Cassandra using cassandra-driver.

Cassandra Query Language (CQL) is SQL-like, so the LLM-generated queries
need only minor adjustments (no JOINs, no UNION ALL between tables, ALLOW
FILTERING is sometimes needed, primary key restrictions apply).

The deterministic sql_agent query builder produces CQL-compatible SELECT
statements for narrow-format tables (uuid, timestamp, value columns).

Expected Cassandra table schema (example):
    CREATE TABLE sensor_data (
        uuid      text,
        timestamp timestamp,
        value     double,
        unit      text,
        PRIMARY KEY (uuid, timestamp)
    ) WITH CLUSTERING ORDER BY (timestamp DESC);

Install: pip install cassandra-driver
"""
import sys
sys.path.append('/app')

import asyncio
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Set

from shared.utils import get_logger
from orchestrator.services.database_adapter import (
    DatabaseAdapter, AdapterType, QueryResult, SchemaInfo
)

logger = get_logger(__name__)

_FORBIDDEN_KEYWORDS = [
    "DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ",
    "TRUNCATE ", "GRANT ", "REVOKE ", "CREATE ",
]


class CassandraAdapter(DatabaseAdapter):
    """
    Apache Cassandra adapter using cassandra-driver.
    Executes CQL queries via a synchronous Session wrapped in run_in_executor
    (cassandra-driver does not yet have a native asyncio API).
    """

    adapter_type = AdapterType.CASSANDRA

    def __init__(
        self,
        host: str = "cassandra",
        port: int = 9042,
        keyspace: str = "bldg",
        user: Optional[str] = None,
        password: Optional[str] = None,
        table: str = "sensor_data",
    ) -> None:
        self._host     = host
        self._port     = port
        self._keyspace = keyspace
        self._user     = user
        self._password = password
        self._default_table = table
        self._cluster  = None
        self._session  = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to Cassandra and set the keyspace."""
        try:
            from cassandra.cluster import Cluster
            from cassandra.auth import PlainTextAuthProvider

            loop = asyncio.get_event_loop()

            def _connect():
                auth = None
                if self._user and self._password:
                    auth = PlainTextAuthProvider(
                        username=self._user, password=self._password
                    )
                cluster = Cluster(
                    [self._host],
                    port=self._port,
                    auth_provider=auth,
                    connect_timeout=10,
                )
                session = cluster.connect(self._keyspace)
                return cluster, session

            self._cluster, self._session = await loop.run_in_executor(None, _connect)
            logger.info(
                f"CassandraAdapter: connected to {self._host}:{self._port} "
                f"keyspace={self._keyspace}"
            )
        except ImportError:
            raise RuntimeError(
                "cassandra-driver is not installed. Run: pip install cassandra-driver"
            )
        except Exception as e:
            logger.error(f"CassandraAdapter: connect failed: {e}")
            raise

    async def close(self) -> None:
        loop = asyncio.get_event_loop()
        if self._cluster:
            await loop.run_in_executor(None, self._cluster.shutdown)
            self._cluster = None
            self._session = None

    async def get_schema(self) -> SchemaInfo:
        """Discover tables and columns from system schema."""
        if self._schema_cache:
            return self._schema_cache

        tables:        List[str]             = []
        columns:       Dict[str, List[tuple]] = {}
        timestamp_col: Optional[str]         = None

        try:
            loop = asyncio.get_event_loop()

            def _fetch_schema():
                rows = self._session.execute(
                    "SELECT table_name FROM system_schema.tables WHERE keyspace_name = %s",
                    (self._keyspace,)
                )
                return [r.table_name for r in rows]

            tables = await loop.run_in_executor(None, _fetch_schema)

            for table in tables:
                def _fetch_cols(t=table):
                    rows = self._session.execute(
                        "SELECT column_name, type FROM system_schema.columns "
                        "WHERE keyspace_name = %s AND table_name = %s",
                        (self._keyspace, t)
                    )
                    return [(r.column_name, r.type) for r in rows]

                col_list = await loop.run_in_executor(None, _fetch_cols)
                columns[table] = col_list
                for col_name, _ in col_list:
                    if not timestamp_col and any(
                        kw in col_name.lower()
                        for kw in ("timestamp", "time", "datetime")
                    ):
                        timestamp_col = col_name
        except Exception as e:
            logger.error(f"CassandraAdapter.get_schema failed: {e}")
            tables  = [self._default_table]
            columns = {self._default_table: [
                ("uuid", "text"), ("timestamp", "timestamp"), ("value", "double")
            ]}
            timestamp_col = "timestamp"

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col or "timestamp",
            adapter_type=AdapterType.CASSANDRA,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """Return all column names (for UUID validation, Cassandra uses uuid column)."""
        if self._columns_cache is not None:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            loop = asyncio.get_event_loop()

            def _fetch():
                rows = self._session.execute(
                    f"SELECT DISTINCT uuid FROM {self._keyspace}.{self._default_table} LIMIT 2000"
                )
                return {r.uuid for r in rows if hasattr(r, "uuid")}

            cols = await loop.run_in_executor(None, _fetch)
        except Exception as e:
            logger.warning(f"CassandraAdapter.get_columns: {e}")

        self._columns_cache = cols
        return cols

    def validate_query(self, cql: str) -> bool:
        """SELECT-only safety check for CQL."""
        cql_upper = cql.upper().strip()
        if not (
            cql_upper.startswith("SELECT")
            or cql_upper.startswith("WITH")
        ):
            raise ValueError("Only SELECT queries are allowed.")
        for kw in _FORBIDDEN_KEYWORDS:
            if kw in cql_upper:
                raise ValueError(f"Forbidden keyword: {kw.strip()}")
        return True

    async def execute_query(self, cql: str) -> QueryResult:
        """Execute a CQL SELECT query."""
        try:
            self.validate_query(cql)
        except ValueError as e:
            return QueryResult.failure(str(e), query=cql)

        try:
            loop = asyncio.get_event_loop()

            def _run():
                rows = self._session.execute(cql)
                result: List[Dict[str, Any]] = []
                for row in rows:
                    clean: Dict[str, Any] = {}
                    for col in rows.column_names:
                        v = getattr(row, col, None)
                        if isinstance(v, (datetime, date)):
                            clean[col] = v.isoformat()
                        else:
                            clean[col] = v
                    result.append(clean)
                return result

            rows = await loop.run_in_executor(None, _run)
            logger.info(f"CassandraAdapter: query returned {len(rows)} rows")
            return QueryResult(success=True, data=rows, row_count=len(rows), query=cql)

        except Exception as e:
            logger.error(f"CassandraAdapter.execute_query error: {e}")
            return QueryResult.failure(str(e), query=cql)

    def build_timeseries_query(
        self,
        uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> Optional[str]:
        """
        Build a CQL SELECT for time-series data.
        Cassandra partitions by uuid, so we query each UUID separately;
        for multiple UUIDs we query the first one (narrow partition model).
        The caller loops per-UUID if needed, but this covers the common case.
        """
        if not uuids:
            return None

        uuid_list = ", ".join(f"'{u}'" for u in uuids)
        time_filter = ""
        if start_date:
            time_filter += f" AND {ts_col} >= '{start_date}'"
        if end_date:
            time_filter += f" AND {ts_col} <= '{end_date}'"

        cql = (
            f"SELECT uuid, {ts_col} AS timestamp, value, unit "
            f"FROM {self._keyspace}.{self._default_table} "
            f"WHERE uuid IN ({uuid_list})"
            f"{time_filter} "
            f"ORDER BY {ts_col} DESC "
            f"LIMIT {limit} ALLOW FILTERING;"
        )
        return cql

    def get_dialect_hints(self) -> str:
        return (
            "Apache Cassandra — use CQL (Cassandra Query Language), not SQL.\n"
            f"Keyspace: {self._keyspace!r}   Default table: {self._default_table!r}\n"
            "Schema (narrow format):\n"
            "  uuid text, timestamp timestamp, value double, unit text\n"
            "  PRIMARY KEY (uuid, timestamp) CLUSTERING ORDER BY (timestamp DESC)\n"
            "CQL rules:\n"
            "  - No JOINs, no subqueries, no UNION ALL.\n"
            "  - Filter on partition key (uuid) is required for efficiency.\n"
            "  - Add ALLOW FILTERING only if non-partition-key filtering needed.\n"
            "  - Time filter: timestamp >= '2024-01-01' AND timestamp <= '2024-01-07'\n"
            "  - Use IN for multiple UUIDs: WHERE uuid IN ('id1', 'id2')\n"
            "CQL template:\n"
            f"  SELECT uuid, timestamp, value, unit\n"
            f"  FROM {self._keyspace}.{self._default_table}\n"
            "  WHERE uuid IN ('<uuid1>','<uuid2>')\n"
            "    AND timestamp >= '<start>'\n"
            "    AND timestamp <= '<end>'\n"
            "  ORDER BY timestamp DESC LIMIT 1000 ALLOW FILTERING;\n"
            "Return ONLY the CQL query, no markdown."
        )
