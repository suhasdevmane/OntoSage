"""
InfluxDBAdapter — InfluxDB 2.x
================================
DatabaseAdapter for InfluxDB 2.x using the official influxdb-client-python.
Uses Flux query language (not SQL).

Query format accepted by execute_query():
    A Flux query string.  Example:
        from(bucket: "sensors")
          |> range(start: -1d)
          |> filter(fn: (r) => r["uuid"] == "abc123")
          |> yield(name: "mean")

    build_timeseries_query() produces Flux automatically from UUIDs + date range.

The get_dialect_hints() method tells the LLM to generate Flux, not SQL.

Install: pip install influxdb-client
"""

import sys

sys.path.append("/app")

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from orchestrator.services.database_adapter import (
    AdapterType,
    DatabaseAdapter,
    QueryResult,
    SchemaInfo,
)
from shared.utils import get_logger

logger = get_logger(__name__)


class InfluxDBAdapter(DatabaseAdapter):
    """
    InfluxDB 2.x adapter using influxdb-client (async WriteAPI / QueryAPI).

    Data model assumed:
        - Each sensor reading is a measurement row.
        - The "uuid" tag or field identifies the sensor.
        - The "_time" column is the timestamp (InfluxDB native).
        - The "_value" column is the sensor reading.
        - The "_measurement" column is the measurement name (e.g. "sensor_data").
    """

    adapter_type = AdapterType.INFLUXDB

    def __init__(
        self,
        url: str = "http://influxdb:8086",
        token: str = "",
        org: str = "ontosage",
        bucket: str = "sensors",
    ) -> None:
        self._url = url
        self._token = token
        self._org = org
        self._bucket = bucket
        self._client = None
        self._query_api = None
        self._schema_cache: Optional[SchemaInfo] = None
        self._columns_cache: Optional[Set[str]] = None

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Create the InfluxDB client and verify connectivity."""
        try:
            from influxdb_client import InfluxDBClient
            from influxdb_client.client.exceptions import InfluxDBError

            self._client = InfluxDBClient(url=self._url, token=self._token, org=self._org)
            self._query_api = self._client.query_api()
            # Ping to verify
            ping = self._client.ping()
            if not ping:
                raise ConnectionError("InfluxDB ping returned False")
            logger.info(
                f"InfluxDBAdapter: connected to {self._url} org={self._org} bucket={self._bucket}"
            )
        except ImportError:
            raise RuntimeError("influxdb-client is not installed. Run: pip install influxdb-client")
        except Exception as e:
            logger.error(f"InfluxDBAdapter: connect failed: {e}")
            raise

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._query_api = None

    async def get_schema(self) -> SchemaInfo:
        """Discover measurements in the bucket and their field keys."""
        if self._schema_cache:
            return self._schema_cache

        tables: List[str] = []
        columns: Dict[str, List[tuple]] = {}
        timestamp_col: Optional[str] = "_time"

        try:
            # List measurements
            flux = (
                f'import "influxdata/influxdb/schema"\n'
                f'schema.measurements(bucket: "{self._bucket}")'
            )
            result = self._query_api.query(flux, org=self._org)
            for table in result:
                for record in table.records:
                    measurement = str(record.get_value())
                    tables.append(measurement)

            # For each measurement get field keys
            for measurement in tables:
                flux_fields = (
                    f'import "influxdata/influxdb/schema"\n'
                    f'schema.fieldKeys(bucket: "{self._bucket}", '
                    f'predicate: (r) => r._measurement == "{measurement}")'
                )
                field_result = self._query_api.query(flux_fields, org=self._org)
                field_list: List[tuple] = [
                    ("_time", "timestamp"),
                    ("_value", "float"),
                    ("uuid", "string"),
                ]
                for t in field_result:
                    for rec in t.records:
                        field_name = str(rec.get_value())
                        field_list.append((field_name, "any"))
                columns[measurement] = field_list

        except Exception as e:
            logger.error(f"InfluxDBAdapter.get_schema failed: {e}")
            # Minimal fallback schema
            tables = ["sensor_data"]
            columns = {
                "sensor_data": [("_time", "timestamp"), ("_value", "float"), ("uuid", "string")]
            }

        self._schema_cache = SchemaInfo(
            tables=tables,
            columns=columns,
            timestamp_column=timestamp_col,
            adapter_type=AdapterType.INFLUXDB,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """
        Return distinct UUID values stored in the bucket
        (used by the registry for UUID validation).
        """
        if self._columns_cache is not None:
            return self._columns_cache

        cols: Set[str] = set()
        try:
            flux = (
                f'from(bucket: "{self._bucket}")\n'
                f"  |> range(start: -90d)\n"
                f'  |> keep(columns: ["uuid"])\n'
                f'  |> distinct(column: "uuid")\n'
                f"  |> limit(n: 2000)"
            )
            result = self._query_api.query(flux, org=self._org)
            for table in result:
                for record in table.records:
                    val = record.get_value()
                    if val:
                        cols.add(str(val))
        except Exception as e:
            logger.warning(f"InfluxDBAdapter.get_columns: {e}")

        self._columns_cache = cols
        return cols

    def validate_query(self, flux: str) -> bool:
        """Reject obviously dangerous Flux expressions."""
        forbidden = ["to(", "experimental.to(", "delete(", "buckets.delete("]
        for kw in forbidden:
            if kw in flux:
                raise ValueError(f"Forbidden Flux operation: {kw}")
        return True

    async def execute_query(self, flux: str) -> QueryResult:
        """Execute a Flux query string and return a standardised QueryResult."""
        try:
            self.validate_query(flux)
        except ValueError as e:
            return QueryResult.failure(str(e), query=flux)

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: self._query_api.query(flux, org=self._org)
            )
            rows: List[Dict[str, Any]] = []
            for table in result:
                for record in table.records:
                    row: Dict[str, Any] = dict(record.values)
                    # Convert InfluxDB datetime objects to ISO strings
                    for k, v in row.items():
                        if isinstance(v, datetime):
                            row[k] = v.isoformat()
                    rows.append(row)

            logger.info(f"InfluxDBAdapter: query returned {len(rows)} records")
            return QueryResult(success=True, data=rows, row_count=len(rows), query=flux)

        except Exception as e:
            logger.error(f"InfluxDBAdapter.execute_query error: {e}")
            return QueryResult.failure(str(e), query=flux)

    def build_timeseries_query(
        self,
        uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> Optional[str]:
        """Build a Flux query for the given UUIDs and time range."""
        start = start_date or "-1d"
        # Flux range needs RFC3339 or duration string
        range_clause = f"range(start: {start}"
        if end_date:
            range_clause += f", stop: {end_date}"
        range_clause += ")"

        uuid_filter = " or ".join(f'r["uuid"] == "{u}"' for u in uuids)

        flux = (
            f'from(bucket: "{self._bucket}")\n'
            f"  |> {range_clause}\n"
            f"  |> filter(fn: (r) => {uuid_filter})\n"
            f'  |> sort(columns: ["_time"], desc: true)\n'
            f"  |> limit(n: {limit})"
        )
        return flux

    def get_dialect_hints(self) -> str:
        return (
            "InfluxDB 2.x — use Flux query language, NOT SQL.\n"
            f"Bucket: {self._bucket!r}   Org: {self._org!r}\n"
            "Flux template:\n"
            f'  from(bucket: "{self._bucket}")\n'
            "    |> range(start: -1d)          // or: start: 2024-01-01T00:00:00Z\n"
            '    |> filter(fn: (r) => r["uuid"] == "<sensor_uuid>")\n'
            '    |> sort(columns: ["_time"], desc: true)\n'
            "    |> limit(n: 1000)\n"
            "Time column: _time  Value column: _value  Tag: uuid\n"
            "Return ONLY the Flux query, no markdown."
        )
