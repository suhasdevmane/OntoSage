# -*- coding: utf-8 -*-
"""Adapters must be able to say how fresh their store is (BUG-378 / CAVEAT-361).

`store_coverage` can only stop the lane reading a provably-dead store if something can tell
it when that store last received a row. No adapter exposed such a probe, so the module was
inert by construction: every store read as UNKNOWN and nothing was ever skipped.

Two properties matter more than the happy path:

* **UNKNOWN is not stale.** An empty table, a failed query and an open circuit breaker all
  return None, and None must never be read as "this store is old" — skipping a sensor because
  a health probe failed turns a transient database error into a wrong answer.
* **The narrow adapter needs its own column.** It inherits discovery from the wide adapter,
  whose `get_columns()` returns column names — but a narrow table's `get_columns()` returns
  the DISTINCT uuids, because its sensors are rows. Without the override, discovery finds
  nothing and every narrow store reports UNKNOWN, disabling the check on exactly the eight
  frozen tables it exists for.
"""

from datetime import datetime

import pytest

from orchestrator.services.adapters.mysql_adapter import MySQLAdapter
from orchestrator.services.adapters.mysql_narrow_adapter import MySQLNarrowAdapter

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, success, data):
        self.success, self.data = success, data


def _wide(monkeypatch, *, columns, result):
    ad = MySQLAdapter.__new__(MySQLAdapter)
    ad._table = "sensor_data"

    async def _cols():
        return columns

    async def _exec(sql):
        _exec.sql = sql
        return result

    monkeypatch.setattr(ad, "get_columns", _cols, raising=False)
    monkeypatch.setattr(ad, "execute_query", _exec, raising=False)
    return ad, _exec


@pytest.mark.asyncio
async def test_the_newest_timestamp_is_returned(monkeypatch):
    ad, _ = _wide(
        monkeypatch,
        columns={"Datetime", "uuid-a", "uuid-b"},
        result=_Result(True, [{"latest": datetime(2026, 8, 31, 17, 45)}]),
    )
    assert await ad.latest_timestamp() == datetime(2026, 8, 31, 17, 45)


@pytest.mark.asyncio
async def test_an_iso_string_is_parsed(monkeypatch):
    """execute_query serialises datetimes to ISO strings on the way out."""
    ad, _ = _wide(
        monkeypatch,
        columns={"Datetime"},
        result=_Result(True, [{"latest": "2026-08-26T13:36:00"}]),
    )
    assert await ad.latest_timestamp() == datetime(2026, 8, 26, 13, 36)


@pytest.mark.asyncio
async def test_the_time_column_is_discovered_not_assumed(monkeypatch):
    """A building may spell it `timestamp`; the query must use the real name."""
    ad, ex = _wide(
        monkeypatch,
        columns={"timestamp"},
        result=_Result(True, [{"latest": "2026-01-01T00:00:00"}]),
    )
    await ad.latest_timestamp()
    assert "`timestamp`" in ex.sql


@pytest.mark.asyncio
async def test_the_configured_table_is_queried(monkeypatch):
    ad, ex = _wide(
        monkeypatch, columns={"Datetime"}, result=_Result(True, [{"latest": "2026-01-01T00:00:00"}])
    )
    await ad.latest_timestamp()
    assert "`sensor_data`" in ex.sql


# ── unknown is not stale ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_failed_query_is_unknown_not_stale(monkeypatch):
    ad, _ = _wide(monkeypatch, columns={"Datetime"}, result=_Result(False, None))
    assert await ad.latest_timestamp() is None


@pytest.mark.asyncio
async def test_an_empty_table_is_unknown(monkeypatch):
    ad, _ = _wide(monkeypatch, columns={"Datetime"}, result=_Result(True, [{"latest": None}]))
    assert await ad.latest_timestamp() is None


@pytest.mark.asyncio
async def test_no_recognisable_time_column_is_unknown_and_runs_no_query(monkeypatch):
    ad, ex = _wide(monkeypatch, columns={"uuid", "value"}, result=_Result(True, []))
    assert await ad.latest_timestamp() is None
    assert not hasattr(ex, "sql"), "a query was built against a table with no time column"


@pytest.mark.asyncio
async def test_a_schema_probe_that_raises_is_unknown(monkeypatch):
    ad = MySQLAdapter.__new__(MySQLAdapter)
    ad._table = "sensor_data"

    async def _boom():
        raise RuntimeError("connection reset")

    monkeypatch.setattr(ad, "get_columns", _boom, raising=False)
    assert await ad.latest_timestamp() is None


# ── the narrow override ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_narrow_adapter_does_not_discover_its_column_from_uuids(monkeypatch):
    """Its get_columns() returns uuids; inherited discovery would find no time column."""
    ad = MySQLNarrowAdapter.__new__(MySQLNarrowAdapter)
    ad._table = "temperature_data"

    async def _uuids():
        return {"aa1c2b1f-c59d-44bf-af24-08ced2ff7ffb", "another-uuid"}

    async def _exec(sql):
        _exec.sql = sql
        return _Result(True, [{"latest": "2026-08-26T13:36:00"}])

    monkeypatch.setattr(ad, "get_columns", _uuids, raising=False)
    monkeypatch.setattr(ad, "execute_query", _exec, raising=False)

    assert await ad.latest_timestamp() == datetime(2026, 8, 26, 13, 36)
    assert "`datetime`" in _exec.sql
    assert "`temperature_data`" in _exec.sql
