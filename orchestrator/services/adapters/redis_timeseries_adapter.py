"""
RedisTimeSeriesAdapter
======================
DatabaseAdapter for Redis with the RedisTimeSeries module (redis-stack).

RedisTimeSeries stores sensor readings as named time-series keys:
    key pattern:  {key_prefix}:{uuid}
    e.g.          sensor:a8df8757-009a-4997-881b-ba8763219d6e

Query format accepted by execute_query():
    A JSON string describing the TS.MRANGE / TS.RANGE command to run:
    {
        "command":    "TS.MRANGE",   // or "TS.RANGE" for a single series
        "from_ts":    "-",           // "-" = earliest available
        "to_ts":      "+",           // "+" = latest available
        "filters":    ["sensor=true", "uuid=<uuid>"],   // for TS.MRANGE
        "key":        "sensor:abc",  // for TS.RANGE (single key)
        "count":      1000           // max samples per series
    }

    build_timeseries_query() produces this JSON automatically.

Install: pip install redis[hiredis]
         (Redis Stack with RedisTimeSeries module must be running)
"""

import sys

sys.path.append("/app")

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from orchestrator.services.database_adapter import (
    AdapterType,
    DatabaseAdapter,
    QueryResult,
    SchemaInfo,
)
from shared.utils import get_logger

logger = get_logger(__name__)


class RedisTimeSeriesAdapter(DatabaseAdapter):
    """
    Redis TimeSeries adapter using redis.asyncio.

    Each sensor UUID maps to a Redis key:  {key_prefix}:{uuid}
    e.g. sensor:a8df8757-009a-4997-881b-ba8763219d6e

    The adapter uses the RedisTimeSeries module commands:
      TS.RANGE  — single time-series key
      TS.MRANGE — multiple time-series keys by label filter
    """

    adapter_type = AdapterType.REDIS_TIMESERIES

    def __init__(
        self,
        url: str = "redis://redis:6379/1",
        password: Optional[str] = None,
        key_prefix: str = "sensor",
    ) -> None:
        self._url = url
        self._password = password
        self._key_prefix = key_prefix
        self._redis = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create an async Redis connection and verify with PING."""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._url,
                password=self._password or None,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info(f"RedisTimeSeriesAdapter: connected to {self._url}")
        except ImportError:
            raise RuntimeError("redis[hiredis] is not installed. Run: pip install redis[hiredis]")
        except Exception as e:
            logger.error(f"RedisTimeSeriesAdapter: connect failed: {e}")
            raise

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def get_schema(self) -> SchemaInfo:
        """Discover time-series keys matching the key prefix."""
        if self._schema_cache:
            return self._schema_cache

        tables: List[str] = [self._key_prefix]
        columns: Dict[str, List[tuple]] = {}
        timestamp_col: Optional[str] = "timestamp"

        try:
            # Scan for keys matching the prefix
            pattern = f"{self._key_prefix}:*"
            keys: List[str] = []
            async for key in self._redis.scan_iter(pattern, count=200):
                keys.append(key)

            # Extract UUID names as "columns"
            col_list = [(k.split(":", 1)[-1], "timeseries") for k in keys[:500]]
            columns[self._key_prefix] = col_list
        except Exception as e:
            logger.error(f"RedisTimeSeriesAdapter.get_schema failed: {e}")
            columns = {self._key_prefix: []}

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col,
            adapter_type=AdapterType.REDIS_TIMESERIES,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """Return UUID suffixes of all time-series keys (for UUID validation)."""
        if self._columns_cache is not None:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            pattern = f"{self._key_prefix}:*"
            async for key in self._redis.scan_iter(pattern, count=500):
                uuid_part = key.split(":", 1)[-1]
                cols.add(uuid_part)
        except Exception as e:
            logger.warning(f"RedisTimeSeriesAdapter.get_columns: {e}")

        self._columns_cache = cols
        return cols

    def validate_query(self, query: str) -> bool:
        """Accept only TS.RANGE / TS.MRANGE commands (via JSON wrapper)."""
        try:
            if query.strip().startswith("{"):
                params = json.loads(query)
                cmd = params.get("command", "").upper()
            else:
                cmd = query.strip().upper().split()[0]

            allowed = {"TS.RANGE", "TS.MRANGE", "TS.GET", "TS.MGET"}
            if cmd not in allowed:
                raise ValueError(f"Command {cmd!r} not allowed. Use one of: {allowed}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON query: {e}")
        return True

    async def execute_query(self, query: str) -> QueryResult:
        """
        Execute a Redis TimeSeries query described by a JSON string.

        JSON keys:
            command   str   — "TS.RANGE" or "TS.MRANGE"
            key       str   — Redis key for TS.RANGE (single series)
            filters   list  — label filters for TS.MRANGE  e.g. ["uuid=abc"]
            from_ts   str   — start timestamp (epoch ms, "-", or ISO string)
            to_ts     str   — end timestamp (epoch ms, "+", or ISO string)
            count     int   — max samples (default 1000)
        """
        try:
            self.validate_query(query)
        except ValueError as e:
            return QueryResult.failure(str(e), query=query)

        try:
            params: Dict[str, Any] = json.loads(query) if query.strip().startswith("{") else {}
            command = params.get("command", "TS.RANGE").upper()
            from_ts = str(params.get("from_ts", "-"))
            to_ts = str(params.get("to_ts", "+"))
            count = int(params.get("count", 1000))

            rows: List[Dict[str, Any]] = []

            if command == "TS.RANGE":
                key = params.get("key", "")
                raw = await self._redis.execute_command(
                    "TS.RANGE", key, from_ts, to_ts, "COUNT", count
                )
                uuid = key.split(":", 1)[-1]
                for ts_ms, value in raw:
                    rows.append(
                        {
                            "uuid": uuid,
                            "timestamp": datetime.fromtimestamp(int(ts_ms) / 1000).isoformat(),
                            "value": float(value),
                        }
                    )

            elif command == "TS.MRANGE":
                filters = params.get("filters", [])
                filter_args = ["FILTER"] + filters if filters else []
                raw = await self._redis.execute_command(
                    "TS.MRANGE",
                    from_ts,
                    to_ts,
                    "COUNT",
                    count,
                    *filter_args,
                )
                # TS.MRANGE returns [[key, labels, [[ts, val], ...]], ...]
                for entry in raw:
                    key = entry[0] if isinstance(entry[0], str) else entry[0].decode()
                    uuid = key.split(":", 1)[-1]
                    points = entry[2]
                    for ts_ms, value in points:
                        rows.append(
                            {
                                "uuid": uuid,
                                "timestamp": datetime.fromtimestamp(int(ts_ms) / 1000).isoformat(),
                                "value": float(value),
                            }
                        )

            logger.info(f"RedisTimeSeriesAdapter: returned {len(rows)} samples")
            return QueryResult(success=True, data=rows, row_count=len(rows), query=query)

        except Exception as e:
            logger.error(f"RedisTimeSeriesAdapter.execute_query error: {e}")
            return QueryResult.failure(str(e), query=query)

    def build_timeseries_query(
        self,
        uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> Optional[str]:
        """Build a TS.MRANGE JSON query for the given UUID list."""
        from_ts = "-"
        to_ts = "+"
        if start_date and start_date not in ("-", "none", "null", ""):
            from_ts = start_date
        if end_date and end_date not in ("+", "none", "null", ""):
            to_ts = end_date

        # Build label filters — requires sensors to be labelled uuid=<value>
        # on insert.  Fallback: query each key directly if no labels.
        if len(uuids) == 1:
            command = "TS.RANGE"
            query_doc = {
                "command": command,
                "key": f"{self._key_prefix}:{uuids[0]}",
                "from_ts": from_ts,
                "to_ts": to_ts,
                "count": limit,
            }
        else:
            # TS.MRANGE with a filter that matches all requested UUIDs
            # Relies on sensors having a "uuid" label set at TS.CREATE time.
            filters = [f"uuid=({','.join(uuids)})"]
            query_doc = {
                "command": "TS.MRANGE",
                "filters": filters,
                "from_ts": from_ts,
                "to_ts": to_ts,
                "count": limit,
            }
        return json.dumps(query_doc)

    def get_dialect_hints(self) -> str:
        return (
            "Redis TimeSeries — use TS commands via JSON format.\n"
            f"Key pattern: {self._key_prefix}:<uuid>\n"
            "Query format (JSON string):\n"
            '  Single series:  {"command":"TS.RANGE","key":"sensor:<uuid>","from_ts":"-","to_ts":"+","count":1000}\n'
            '  Multi series:   {"command":"TS.MRANGE","filters":["uuid=(<uuid1>,<uuid2>)"],"from_ts":"<start>","to_ts":"<end>","count":1000}\n'
            "Timestamps: epoch milliseconds, RFC3339, or '-'/'+' for open range.\n"
            "Output columns: uuid, timestamp (ISO string), value (float).\n"
            "Return ONLY the JSON string, no markdown."
        )
