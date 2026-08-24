"""MySQLNarrowAdapter — narrow (uuid, datetime, value) per-modality tables.

The default :class:`MySQLAdapter` assumes the WIDE ``sensor_data`` table where each
UUID is a COLUMN. Sensor modalities standardized out of ``input/data`` (energy,
occupancy, water, noise, IAQ, light, equipment) instead live in NARROW tables
``(uuid, datetime, value)`` — one table per modality, each registered as its own
storage backend and reached from the ontology via ``ref:storedAt bldg:<table>``.

This subclass reuses the pool/exec machinery of MySQLAdapter but scopes schema,
UUID validation, and the deterministic timeseries query to a SINGLE narrow table.
It returns rows in the same ``(timestamp, uuid, value)`` shape the wide UNION path
produces, so ``sql_agent`` / analytics need no changes — ``build_timeseries_query``
short-circuits the wide builder with a native narrow SELECT.
"""

from __future__ import annotations

import re
from typing import List, Optional, Set

from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
from orchestrator.services.database_adapter import AdapterType, SchemaInfo
from shared.utils import get_logger

logger = get_logger(__name__)

# Sensor identifiers from SPARQL (ref:hasTimeseriesId). These are NOT always hex
# UUIDs — bldg1's synthetic ids use mnemonic segments (e.g. "...-oc01-..." for
# occupancy, "...-nz01-..." for noise) whose letters are outside [a-f], so a
# hex-only class silently rejects whole modalities and the adapter returns no
# data for them. Accept [alnum + hyphen], 8–64 chars: still injection-safe (no
# quote / backslash / whitespace / semicolon can appear) — guard before
# interpolating into SQL.
_UUID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,63}$")
_TABLE_RE = re.compile(r"^[A-Za-z0-9_]+$")


class MySQLNarrowAdapter(MySQLAdapter):
    """MySQL adapter scoped to one narrow (uuid, datetime, value) modality table."""

    adapter_type = AdapterType.MYSQL

    def __init__(self, table: str, **kwargs):
        super().__init__(**kwargs)
        if not _TABLE_RE.match(table or ""):
            raise ValueError(f"unsafe narrow table name: {table!r}")
        self._table = table

    @property
    def table(self) -> str:
        """The one table this adapter is scoped to.

        Public because callers legitimately need it — a freshness or cadence probe has to know
        whether it is looking at a narrow ``(uuid, datetime, value)`` table or a wide one, and
        the presence of a table name is how they tell. While this was private,
        ``getattr(adapter, "table", None)`` returned None and every narrow store was queried as
        though it were the wide table, whose uuid-shaped COLUMN names share nothing with a
        narrow store's uuid VALUES — so the probes returned a confident zero.
        """
        return self._table

    async def get_schema(self) -> SchemaInfo:
        """Describe only this narrow table (timestamp column = 'datetime')."""
        if self._schema_cache:
            return self._schema_cache
        columns = {
            self._table: [
                ("uuid", "char(36)"),
                ("datetime", "datetime"),
                ("value", "double"),
            ]
        }
        self._schema_cache = SchemaInfo(
            tables=[self._table],
            columns=columns,
            timestamp_column="datetime",
            adapter_type=AdapterType.MYSQL,
        )
        return self._schema_cache

    async def get_columns(self) -> Set[str]:
        """For narrow tables UUIDs are ROW values, not columns. Return the DISTINCT
        uuids present so the registry's column-based UUID validation works unchanged."""
        if self._columns_cache is not None:
            return self._columns_cache
        cols: Set[str] = set()
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(f"SELECT DISTINCT `uuid` FROM `{self._table}`")
                    rows = await cursor.fetchall()
                    cols = {r[0] for r in rows if r and r[0]}
        except Exception as e:
            logger.error(f"MySQLNarrowAdapter[{self._table}].get_columns failed: {e}")
        self._columns_cache = cols
        return cols

    def get_dialect_hints(self) -> str:
        return (
            f"MySQL narrow table `{self._table}` (uuid, datetime, value):\n"
            "- One row per (uuid, datetime); filter sensors with `uuid` IN (...).\n"
            "- Timestamp column: 'datetime', alias as 'timestamp'.\n"
            "- Default time window: datetime >= NOW() - INTERVAL 30 DAY.\n"
        )

    def build_timeseries_query(
        self,
        uuids: List[str],
        ts_col: str,
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int = 1000,
    ) -> Optional[str]:
        """Native narrow SELECT, returning (timestamp, uuid, value) like the wide path.

        ``limit`` is applied PER uuid via ``ROW_NUMBER()``, not across the whole
        result set. A flat ``LIMIT`` on a multi-sensor query returns the N newest
        rows *combined*, silently dropping every reading — up to all of them — for
        sensors whose data sorts after a chattier sensor's. Per-uuid limiting
        matches the wide table's per-timestamp semantics (N readings per sensor).
        Requires MySQL 8.0+ (window functions); the narrow tables ship on
        InnoDB / MySQL 8.
        """
        safe = [u for u in uuids if _UUID_RE.match(str(u))]
        if not safe:
            return None
        in_list = ", ".join(f"'{u}'" for u in safe)
        clauses = [f"`uuid` IN ({in_list})"]
        start = self._sanitize_dt(start_date)
        end = self._sanitize_dt(end_date)
        if start:
            clauses.append(f"`datetime` >= '{start}'")
        elif not end:
            clauses.append("`datetime` >= DATE_SUB(NOW(), INTERVAL 30 DAY)")
        if end:
            clauses.append(f"`datetime` <= '{end}'")
        where = " AND ".join(clauses)
        per_uuid = int(limit)
        # Safety cap on the flattened result so a large uuid-set can't explode.
        outer_cap = per_uuid * max(1, len(safe))
        return (
            "SELECT `timestamp`, `uuid`, `value` FROM ("
            "SELECT `datetime` AS timestamp, `uuid` AS uuid, `value` AS value, "
            "ROW_NUMBER() OVER (PARTITION BY `uuid` ORDER BY `datetime` DESC) AS rn "
            f"FROM `{self._table}` WHERE {where} AND `value` IS NOT NULL"
            ") ranked "
            f"WHERE rn <= {per_uuid} "
            f"ORDER BY `uuid`, `timestamp` DESC LIMIT {outer_cap};"
        )

    @staticmethod
    def _sanitize_dt(dt: Optional[str]) -> Optional[str]:
        """Accept only a full calendar date (optionally with a time), else None.

        A character-class filter is too permissive: the remains of a relative
        phrase ("-24 hours" → "-2400") can satisfy it and then be spliced into
        the WHERE clause as a bogus bound. Anything not an unambiguous
        timestamp is treated as absent so the default window applies.
        """
        if not dt:
            return None
        s = str(dt).strip().replace("T", " ")
        if re.match(r"^\d{4}-\d{2}-\d{2}([ ]\d{2}:\d{2}(:\d{2})?)?$", s):
            return s[:19]
        return None
