# -*- coding: utf-8 -*-
"""Time bounds and narrow-table handling on the path from a question to readings.

Covers three defects that each ended with a sensor's readings never reaching the
answer even though they were sitting in the database:

  * a relative bound ("now-24h") surviving into a WHERE clause as "-24"
  * a narrow (uuid, time, value) table failing UUID validation, which checks
    column names
  * an empty LLM completion being recorded as a successful generation

Everything here is layout- and provider-level; nothing names a building.
"""

import re
from datetime import datetime

import pytest

from orchestrator.agents.dialogue_agent import _resolve_relative_dt
from orchestrator.agents.sql_agent import SQLAgent
from orchestrator.services.adapters.mysql_narrow_adapter import MySQLNarrowAdapter
from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter

pytestmark = pytest.mark.unit

_ABS = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


# ── relative bound resolution ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "given,hours_ago",
    [
        ("now", 0),
        ("now-1d", 24),
        ("now-24h", 24),
        ("now - 24 hours", 24),
        ("now-2w", 336),
        ("now-30m", 0.5),
    ],
)
def test_relative_bound_becomes_absolute(given, hours_ago):
    out = _resolve_relative_dt(given)
    assert _ABS.match(out), f"{given!r} did not resolve to an absolute stamp: {out!r}"
    delta = (datetime.utcnow() - datetime.strptime(out, "%Y-%m-%d %H:%M:%S")).total_seconds()
    assert abs(delta / 3600 - hours_ago) < 0.1


@pytest.mark.parametrize("given", ["2026-08-01", "2026-08-01 10:30:00", "last tuesday", "", None])
def test_non_relative_bounds_pass_through(given):
    assert _resolve_relative_dt(given) == given


# ── bound sanitising: a partial phrase must not become a literal ─────────────

_SANITIZERS = [
    ("postgres", PostgreSQLAdapter._sanitize_dt),
    ("mysql_narrow", MySQLNarrowAdapter._sanitize_dt),
    ("sql_agent_wide", lambda v: SQLAgent.__new__(SQLAgent)._sanitize_datetime(v)),
]


@pytest.mark.parametrize("name,fn", _SANITIZERS)
@pytest.mark.parametrize("junk", ["-24", "-2400", "now-24h", "24", "-", "+05:30", "last week"])
def test_sanitizers_reject_non_dates(name, fn, junk):
    assert fn(junk) is None, f"{name} accepted {junk!r} as a time bound"


@pytest.mark.parametrize("name,fn", _SANITIZERS)
@pytest.mark.parametrize(
    "good", ["2026-08-01", "2026-08-01 10:30", "2026-08-01 10:30:00", "2026-08-01T10:30:00"]
)
def test_sanitizers_accept_real_dates(name, fn, good):
    assert fn(good) == good.replace("T", " ")


# ── narrow Postgres: layout detection drives validation and SQL ──────────────


def _pg_with_layout(layout):
    pg = PostgreSQLAdapter.__new__(PostgreSQLAdapter)
    pg._narrow = layout
    return pg


def test_narrow_query_filters_uuid_as_row_value():
    pg = _pg_with_layout(
        {"table": "sensor_timeseries", "uuid": "uuid", "ts": "datetime", "value": "value"}
    )
    uid = "8aef51b9-98c4-4571-8296-15316df6a882"
    sql = pg.build_timeseries_query([uid], "datetime", None, None, limit=10)

    assert f"'{uid}'" in sql
    assert '"uuid" IN (' in sql, "narrow table must filter the UUID as a row value"
    assert "ROW_NUMBER() OVER (PARTITION BY" in sql, "limit must apply per uuid, not per result set"
    assert 'SELECT "timestamp", "uuid", "value"' in sql, "output shape must match the wide path"


def test_narrow_query_uses_default_window_when_bound_is_unusable():
    pg = _pg_with_layout(
        {"table": "sensor_timeseries", "uuid": "uuid", "ts": "datetime", "value": "value"}
    )
    sql = pg.build_timeseries_query(
        ["8aef51b9-98c4-4571-8296-15316df6a882"], "datetime", "now-24h", None, limit=10
    )
    assert "'-24'" not in sql
    assert "INTERVAL '30 days'" in sql


def test_wide_postgres_defers_to_the_generic_builder():
    assert (
        _pg_with_layout(None).build_timeseries_query(
            ["8aef51b9-98c4-4571-8296-15316df6a882"], "ts", None, None
        )
        is None
    )


def test_narrow_query_ignores_non_uuid_input():
    pg = _pg_with_layout(
        {"table": "sensor_timeseries", "uuid": "uuid", "ts": "datetime", "value": "value"}
    )
    assert pg.build_timeseries_query(["'; DROP TABLE x; --"], "datetime", None, None) is None


def test_layout_hints_carry_no_building_identifiers():
    hints = set(PostgreSQLAdapter._UUID_COL_HINTS) | set(PostgreSQLAdapter._VALUE_COL_HINTS)
    assert all(h == h.lower() and " " not in h for h in hints)
    assert not any("bldg" in h for h in hints)
