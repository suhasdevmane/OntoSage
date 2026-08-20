# -*- coding: utf-8 -*-
"""
MySQLEventsAdapter — the S2 interval/event store (V5-T07, Event Framework).

One generic table per building holds EVERY IntervalRecord subtype (bookings,
work orders, access events, alarms, compliance checks, anomaly episodes):

    events(event_id, event_type, subject_uuid, start_dt, end_dt, status, attrs)

- ``event_type`` is namespaced lowercase (e.g. 'booking', 'workorder',
  'anomaly:seasonal_residual') — the OCBV-2 class vocabulary maps onto it.
- ``subject_uuid`` joins the record to a space/equipment/point exactly like a
  sensor's ref:hasTimeseriesId — derived via derive_point_uuid, so the same
  UUID discipline covers rows and triples.
- ``end_dt`` NULL means open-ended/ongoing (an unresolved work order, an
  anomaly episode still active).
- ``attrs`` is a JSON blob whose keys per type are documented in
  tasks/V5_OCBV2_DELTA_SPEC.md and treated as opaque here.

The adapter is read-focused (query builders + execute); writers (synthetic
generators, the anomaly scanner) insert directly with parameterized SQL.
All builder inputs are validated (regex whitelists / datetime parsing) before
interpolation — same discipline as MySQLNarrowAdapter.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
from orchestrator.services.database_adapter import AdapterType, SchemaInfo
from shared.utils import get_logger

logger = get_logger(__name__)

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")
_TYPE_RE = re.compile(r"^[a-z0-9_]+(:[a-z0-9_]+)?$")
_STATUS_RE = re.compile(r"^[a-z_]+$")
_TABLE = "events"

#: lifecycle states the store recognises (documented, not enforced by DDL)
KNOWN_STATUSES = ("open", "assigned", "done", "cancelled", "detected", "resolved")


def _dt(value: Optional[str]) -> Optional[str]:
    """Parse-and-reformat a datetime string; None if absent or unparseable."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value)[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    logger.debug(f"[events] unparseable datetime dropped: {value!r}")
    return None


class MySQLEventsAdapter(MySQLAdapter):
    """MySQL adapter scoped to the generic per-building `events` table."""

    adapter_type = AdapterType.MYSQL

    async def get_schema(self) -> SchemaInfo:
        if self._schema_cache:
            return self._schema_cache
        columns = {
            _TABLE: [
                ("event_id", "char(36)"),
                ("event_type", "varchar(64)"),
                ("subject_uuid", "char(36)"),
                ("start_dt", "datetime"),
                ("end_dt", "datetime"),
                ("status", "varchar(32)"),
                ("attrs", "json"),
            ]
        }
        self._schema_cache = SchemaInfo(
            tables=[_TABLE],
            columns=columns,
            timestamp_column="start_dt",
            adapter_type=AdapterType.MYSQL,
        )
        return self._schema_cache

    async def get_columns(self):
        """Fixed schema — no discovery round-trip needed for the events table."""
        return {"event_id", "event_type", "subject_uuid", "start_dt", "end_dt", "status", "attrs"}

    def get_dialect_hints(self) -> str:
        return (
            "MySQL generic `events` table (interval records):\n"
            "- Columns: event_id, event_type, subject_uuid, start_dt, end_dt (NULL=ongoing), "
            "status, attrs(JSON).\n"
            "- Types: booking | workorder | access | alarm | compliance | anomaly:<detector>.\n"
            "- Overlap test: start_dt < :window_end AND (end_dt IS NULL OR end_dt > :window_start).\n"
        )

    # ── Query builders (validated inputs -> SQL string, executed via execute_query) ──

    def build_active_now(
        self,
        event_type: str,
        subject_uuids: Optional[List[str]] = None,
        at: Optional[str] = None,
        limit: int = 500,
    ) -> Optional[str]:
        """Records in progress at instant `at` (default NOW())."""
        if not _TYPE_RE.match(event_type or ""):
            return None
        instant = f"'{_dt(at)}'" if _dt(at) else "NOW()"
        clauses = [
            f"`event_type` = '{event_type}'",
            f"`start_dt` <= {instant}",
            f"(`end_dt` IS NULL OR `end_dt` > {instant})",
        ]
        subj = self._subject_clause(subject_uuids)
        if subj:
            clauses.append(subj)
        return (
            "SELECT `event_id`, `event_type`, `subject_uuid`, `start_dt`, `end_dt`, "
            f"`status`, `attrs` FROM `{_TABLE}` WHERE {' AND '.join(clauses)} "
            f"ORDER BY `start_dt` DESC LIMIT {int(limit)}"
        )

    def build_overlap_window(
        self,
        event_type: str,
        window_start: str,
        window_end: str,
        subject_uuids: Optional[List[str]] = None,
        limit: int = 1000,
    ) -> Optional[str]:
        """Records overlapping [window_start, window_end) — the availability primitive."""
        start, end = _dt(window_start), _dt(window_end)
        if not (_TYPE_RE.match(event_type or "") and start and end):
            return None
        clauses = [
            f"`event_type` = '{event_type}'",
            f"`start_dt` < '{end}'",
            f"(`end_dt` IS NULL OR `end_dt` > '{start}')",
        ]
        subj = self._subject_clause(subject_uuids)
        if subj:
            clauses.append(subj)
        return (
            "SELECT `event_id`, `event_type`, `subject_uuid`, `start_dt`, `end_dt`, "
            f"`status`, `attrs` FROM `{_TABLE}` WHERE {' AND '.join(clauses)} "
            f"ORDER BY `start_dt` ASC LIMIT {int(limit)}"
        )

    def build_count_by_status(
        self,
        event_type: str,
        since: Optional[str] = None,
        open_older_than: Optional[str] = None,
    ) -> Optional[str]:
        """Counts grouped by lifecycle status; optional aging filter for backlogs."""
        if not _TYPE_RE.match(event_type or ""):
            return None
        clauses = [f"`event_type` = '{event_type}'"]
        s = _dt(since)
        if s:
            clauses.append(f"`start_dt` >= '{s}'")
        aged = _dt(open_older_than)
        if aged:
            clauses.append(f"`start_dt` < '{aged}' AND `end_dt` IS NULL")
        return (
            f"SELECT `status`, COUNT(*) AS n FROM `{_TABLE}` "
            f"WHERE {' AND '.join(clauses)} GROUP BY `status` ORDER BY n DESC"
        )

    def build_latest_per_subject(
        self, event_type: str, subject_uuids: Optional[List[str]] = None, limit: int = 500
    ) -> Optional[str]:
        """Newest record per subject (e.g. each room's latest booking/anomaly)."""
        if not _TYPE_RE.match(event_type or ""):
            return None
        clauses = [f"`event_type` = '{event_type}'"]
        subj = self._subject_clause(subject_uuids)
        if subj:
            clauses.append(subj)
        where = " AND ".join(clauses)
        return (
            "SELECT `event_id`, `event_type`, `subject_uuid`, `start_dt`, `end_dt`, "
            "`status`, `attrs` FROM ("
            "SELECT *, ROW_NUMBER() OVER (PARTITION BY `subject_uuid` "
            "ORDER BY `start_dt` DESC) AS rn "
            f"FROM `{_TABLE}` WHERE {where}"
            f") ranked WHERE rn = 1 ORDER BY `start_dt` DESC LIMIT {int(limit)}"
        )

    def build_history(
        self,
        subject_uuid: str,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 200,
    ) -> Optional[str]:
        """Full record history for one subject, newest first."""
        if not _UUID_RE.match(subject_uuid or ""):
            return None
        clauses = [f"`subject_uuid` = '{subject_uuid}'"]
        if event_type:
            if not _TYPE_RE.match(event_type):
                return None
            clauses.append(f"`event_type` = '{event_type}'")
        s = _dt(since)
        if s:
            clauses.append(f"`start_dt` >= '{s}'")
        return (
            "SELECT `event_id`, `event_type`, `subject_uuid`, `start_dt`, `end_dt`, "
            f"`status`, `attrs` FROM `{_TABLE}` WHERE {' AND '.join(clauses)} "
            f"ORDER BY `start_dt` DESC LIMIT {int(limit)}"
        )

    def build_anomaly_episodes(
        self,
        window_start: str,
        window_end: str,
        limit: int = 500,
    ) -> Optional[str]:
        """Anomaly episodes overlapping a window (V5-T21).

        The 'anomaly:%' prefix is a FIXED literal (scanner-owned namespace,
        T19) — never caller text, so the LIKE is injection-safe by
        construction.
        """
        start, end = _dt(window_start), _dt(window_end)
        if not (start and end):
            return None
        return (
            "SELECT `event_id`, `event_type`, `subject_uuid`, `start_dt`, `end_dt`, "
            f"`status`, `attrs` FROM `{_TABLE}` "
            "WHERE `event_type` LIKE 'anomaly:%' "
            f"AND `start_dt` <= '{end}' AND `end_dt` >= '{start}' "
            f"ORDER BY `start_dt` DESC LIMIT {int(limit)}"
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _subject_clause(subject_uuids: Optional[List[str]]) -> Optional[str]:
        if not subject_uuids:
            return None
        safe = [u for u in subject_uuids if _UUID_RE.match(str(u))]
        if not safe:
            return "1=0"  # explicit empty match — never silently widen scope
        return "`subject_uuid` IN (" + ", ".join(f"'{u}'" for u in safe) + ")"
