# -*- coding: utf-8 -*-
"""TODO-143: the two backends the paper's building table names, actually exercised.

Both adapters were implemented and dispatched by the registry, so the capability
looked defensible in code. Nothing ever ran them: no test referenced either, no
building pointed a ``ref:storedAt`` key at one, and the Cassandra driver was not
even installed — ``CassandraAdapter.connect()`` could only have raised. A reader
cloning the artifact to reproduce that table found neither backend.

The offline tests below pin the query construction and the safety checks. The
live ones run only when the servers from
``docker-compose.timeseries-backends.yml`` are up, and are the ones that actually
prove the claim: schema read, UUID validation, query build and execute against a
real hypertable and a real CQL table, using sensor UUIDs taken from the graph.
"""

from __future__ import annotations

import asyncio
import os
import socket

import pytest

from orchestrator.services.adapters.cassandra_adapter import CassandraAdapter
from orchestrator.services.adapters.timescaledb_adapter import TimescaleDBAdapter
from orchestrator.services.database_adapter import AdapterType

UUID_A = "b1aca4d6-715e-5189-aec1-afe52c426813"
UUID_B = "7523e124-9695-5f5d-952d-cb523a1718bd"

TS_HOST, TS_PORT = os.environ.get("TIMESCALE_HOST", "127.0.0.1"), 5434
CS_HOST, CS_PORT = os.environ.get("CASSANDRA_HOST", "127.0.0.1"), 9042


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


timescale_up = pytest.mark.skipif(
    not _reachable(TS_HOST, TS_PORT),
    reason="TimescaleDB not running (docker-compose.timeseries-backends.yml)",
)
cassandra_up = pytest.mark.skipif(
    not _reachable(CS_HOST, CS_PORT),
    reason="Cassandra not running (docker-compose.timeseries-backends.yml)",
)


# ── offline: construction and safety ──────────────────────────────────────────


@pytest.mark.unit
class TestTheyAreDistinctBackends:
    def test_each_declares_its_own_type(self):
        """The registry dispatches on this; a wrong value routes silently."""
        assert TimescaleDBAdapter.adapter_type == AdapterType.TIMESCALEDB
        assert CassandraAdapter.adapter_type == AdapterType.CASSANDRA

    def test_timescale_is_postgres_underneath(self):
        """Same wire protocol and driver — the difference is schema and dialect."""
        from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter

        assert issubclass(TimescaleDBAdapter, PostgreSQLAdapter)

    def test_the_registry_dispatches_both(self):
        import inspect

        from orchestrator.services.adapters import registry

        src = inspect.getsource(registry)
        assert 'db_type == "timescaledb"' in src
        assert 'db_type == "cassandra"' in src


@pytest.mark.unit
class TestDialectHintsDescribeTheRealBackend:
    def test_timescale_offers_hypertable_functions(self):
        """A hint set that omits time_bucket describes PostgreSQL, not Timescale."""
        hints = TimescaleDBAdapter(host="h", database="d").get_dialect_hints()
        assert "time_bucket" in hints
        assert "hypertable" in hints.lower()

    def test_cassandra_warns_off_sql_only_constructs(self):
        """CQL has no JOIN; a hint that stays silent invites a query that cannot run."""
        hints = CassandraAdapter(host="h").get_dialect_hints()
        assert "CQL" in hints
        assert "JOIN" in hints.upper()
        assert "partition key" in hints.lower()


@pytest.mark.unit
class TestCqlConstruction:
    def _a(self):
        return CassandraAdapter(host="h", keyspace="ks", table="readings")

    def test_it_targets_the_configured_keyspace_and_table(self):
        cql = self._a().build_timeseries_query([UUID_A], "timestamp", None, None, 10)
        assert "FROM ks.readings" in cql

    def test_the_partition_key_is_always_constrained(self):
        """An unconstrained scan across partitions is the classic Cassandra mistake."""
        cql = self._a().build_timeseries_query([UUID_A, UUID_B], "timestamp", None, None, 10)
        assert f"WHERE uuid IN ('{UUID_A}', '{UUID_B}')" in cql

    def test_newest_first_and_bounded(self):
        cql = self._a().build_timeseries_query([UUID_A], "timestamp", None, None, 7)
        assert "ORDER BY timestamp DESC" in cql
        assert "LIMIT 7" in cql

    def test_a_time_window_is_applied_when_given(self):
        cql = self._a().build_timeseries_query(
            [UUID_A], "timestamp", "2026-01-01", "2026-01-07", 10
        )
        assert "timestamp >= '2026-01-01'" in cql
        assert "timestamp <= '2026-01-07'" in cql

    def test_no_uuids_builds_nothing(self):
        """Better no query than one that scans every partition in the cluster."""
        assert self._a().build_timeseries_query([], "timestamp", None, None, 10) is None


@pytest.mark.unit
class TestCqlSafety:
    @pytest.mark.parametrize(
        "cql",
        [
            "DROP TABLE readings",
            "DELETE FROM readings WHERE uuid='x'",
            "INSERT INTO readings (uuid) VALUES ('x')",
            "TRUNCATE readings",
            "UPDATE readings SET value=1",
        ],
    )
    def test_writes_are_refused(self, cql):
        with pytest.raises(ValueError):
            CassandraAdapter(host="h").validate_query(cql)

    def test_a_select_is_allowed(self):
        assert CassandraAdapter(host="h").validate_query("SELECT * FROM ks.readings LIMIT 1")

    def test_a_write_hidden_after_a_select_is_still_refused(self):
        with pytest.raises(ValueError):
            CassandraAdapter(host="h").validate_query("SELECT 1; DROP TABLE readings")


# ── live: the part that actually proves the paper's claim ─────────────────────


def _ts_adapter():
    return TimescaleDBAdapter(
        host=TS_HOST,
        port=TS_PORT,
        user=os.environ.get("TIMESCALE_USER", "ontosage"),
        password=os.environ.get("TIMESCALE_PASSWORD", "ontosage_ts_secret"),
        database=os.environ.get("TIMESCALE_DB", "sensordb"),
    )


def _cs_adapter():
    return CassandraAdapter(
        host=CS_HOST, port=CS_PORT, keyspace="ontosage", table="sensor_readings"
    )


async def _roundtrip(adapter, ts_col):
    await adapter.connect()
    try:
        cols = await adapter.get_columns()
        query = adapter.build_timeseries_query([UUID_A], ts_col, None, None, 5)
        result = await adapter.execute_query(query)
        return cols, result
    finally:
        await adapter.close()


@pytest.mark.integration
@timescale_up
class TestTimescaleLive:
    def test_a_real_hypertable_answers_a_real_uuid(self):
        cols, result = asyncio.run(_roundtrip(_ts_adapter(), "time"))
        assert UUID_A in cols, "the seeded sensor is not visible for UUID validation"
        assert result.success and result.data, "no rows came back from the hypertable"
        row = result.data[0]
        assert row["uuid"] == UUID_A
        assert isinstance(row["value"], (int, float))

    def test_the_table_really_is_a_hypertable(self):
        """A plain table inside Timescale exercises PostgreSQL, not TimescaleDB."""

        async def _check():
            a = _ts_adapter()
            await a.connect()
            try:
                r = await a.execute_query(
                    "SELECT hypertable_name FROM timescaledb_information.hypertables"
                )
                return [x["hypertable_name"] for x in (r.data or [])]
            finally:
                await a.close()

        assert "sensor_readings" in asyncio.run(_check())


@pytest.mark.integration
@cassandra_up
class TestCassandraLive:
    def test_a_real_cql_table_answers_a_real_uuid(self):
        cols, result = asyncio.run(_roundtrip(_cs_adapter(), "timestamp"))
        assert UUID_A in cols, "the seeded sensor is not visible for UUID validation"
        assert result.success and result.data, "no rows came back from Cassandra"
        row = result.data[0]
        assert row["uuid"] == UUID_A
        assert isinstance(row["value"], (int, float))

    def test_rows_come_back_newest_first(self):
        _, result = asyncio.run(_roundtrip(_cs_adapter(), "timestamp"))
        stamps = [r["timestamp"] for r in result.data]
        assert stamps == sorted(stamps, reverse=True)

    def test_the_driver_is_installed(self):
        """Without it connect() can only raise — which is where TODO-143 started."""
        import cassandra  # noqa: F401


@pytest.mark.unit
class TestTheDsnFallback:
    """Found by the first test that ever constructed these without a full config.

    _build_dsn fell back to settings.PG_HOST / PG_PORT / PG_USER / PG_PASSWORD /
    PG_DATABASE — none of which exist; the settings are named POSTGRES_USER_*.
    Any caller omitting one field got an AttributeError on a phantom attribute.
    The registry always passes all five, so the path was never taken until now.
    """

    def test_omitted_fields_are_filled_from_settings(self):
        from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter

        dsn = PostgreSQLAdapter._build_dsn(None, None, None, None, "sensordb")
        assert dsn.startswith("postgresql://")
        assert dsn.endswith("/sensordb")

    def test_a_missing_database_is_refused_not_guessed(self):
        """The only Postgres this deployment knows holds users, not readings —
        connecting there would succeed and return nothing."""
        from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter

        with pytest.raises(ValueError, match="database name"):
            PostgreSQLAdapter._build_dsn("h", 5432, "u", "p", None)

    def test_explicit_values_always_win(self):
        from orchestrator.services.adapters.postgresql_adapter import PostgreSQLAdapter

        dsn = PostgreSQLAdapter._build_dsn("tsdb", 5434, "me", "secret", "sensordb")
        assert dsn == "postgresql://me:secret@tsdb:5434/sensordb"

    def test_a_timescale_adapter_builds_with_only_a_database(self):
        """The construction that crashed before the fix."""
        assert TimescaleDBAdapter(database="sensordb").get_dialect_hints()
