# -*- coding: utf-8 -*-
"""V12-13 — the same readings answer the same way through every backend (review A15/A16).

    A15  "Equivalent seeded data returns equivalent semantic results AND equivalent
          evidence through each supported wide/narrow adapter, against real servers."
    A16  "The defined snapshot policy prevents an unexplained mixed result when a mapping
          changes mid-turn."

WHY A MOCK WOULD NOT HAVE SETTLED THIS
---------------------------------------
The review is explicit that a mock alone does not establish adapter compatibility, and
TODO-143 is why: both adapters were implemented and dispatched by the registry, so the
capability looked defensible in code while nothing had ever run them — the Cassandra driver
was not even installed, so `connect()` could only have raised.

The live half of this file runs against real servers from
`docker-compose.timeseries-backends.yml`, seeded by `scripts/seed_timeseries_backends.py`.
It skips when they are down, and a skip is honest there; what it must never do is pass
because a fake returned what it was told to.

WHAT "PARITY" MEANS HERE, PRECISELY
------------------------------------
Two stores holding the SAME logical series — 25 sensors, 192 readings each at 15-minute
intervals — must produce the same answer through two very different adapters: a Timescale
HYPERTABLE queried with SQL, and a Cassandra table partitioned by sensor with a DESC
clustering order, queried with CQL. Parity is asserted on BOTH halves the review names:

  semantic result  count, min, max and mean over the window
  evidence         the newest timestamp and the value at it

Evidence matters separately because two stores can agree on statistics and disagree about
which reading is the latest — and "when was this true" is the half a recommendation rests on.

AND ONE DEFECT IN THE EXISTING TEST, FOUND BY RE-SEEDING
----------------------------------------------------------
`test_timescale_cassandra_adapters.py` hardcodes `UUID_A`, a uuid from an earlier seed run.
The seeder takes its sensors from the LIVE graph, so the moment the graph changed the
constant stopped matching and both live tests failed against perfectly healthy servers. A
test pinned to seed data it does not control passes exactly once. This file reads the
uuids back from the store instead.
"""

from __future__ import annotations

import asyncio
import os
import socket
import statistics
from typing import Any, Dict, List, Optional, Tuple

import pytest

from orchestrator.services.graph_snapshot import (
    GraphSnapshot,
    compare,
    mapping_snapshot,
)

TS_HOST, TS_PORT = os.environ.get("TIMESCALE_HOST", "127.0.0.1"), 5434
CS_HOST, CS_PORT = os.environ.get("CASSANDRA_HOST", "127.0.0.1"), 9042


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


both_up = pytest.mark.skipif(
    not (_reachable(TS_HOST, TS_PORT) and _reachable(CS_HOST, CS_PORT)),
    reason="TimescaleDB and Cassandra not both running "
    "(docker compose -f docker-compose.timeseries-backends.yml up -d)",
)


# ── A16: the snapshot policy, offline and exact ──────────────────────────────


@pytest.mark.unit
class TestSnapshotPolicy:
    def test_a_sensor_that_moved_store_is_named(self):
        before = mapping_snapshot({"u1": "bldg:database1", "u2": "bldg:iaq_data"}, 100)
        after = mapping_snapshot({"u1": "bldg:timescaledb", "u2": "bldg:iaq_data"}, 100)

        drift = compare(before, after)
        assert drift.mapping_changed is True
        assert drift.moved == {"u1": ("bldg:database1", "bldg:timescaledb")}
        assert "u1" in drift.note()

    def test_a_sensor_that_lost_its_store_is_named_separately(self):
        """Moved and gone are different facts: one says where to look instead, the other
        says there is nowhere."""
        drift = compare(
            mapping_snapshot({"u1": "bldg:database1"}, 100),
            mapping_snapshot({}, 100),
        )
        assert drift.lost == ["u1"]
        assert drift.moved == {}
        assert drift.mapping_changed is True

    def test_an_unchanged_mapping_says_nothing(self):
        """A caveat on every turn is read as boilerplate and then not read at all."""
        snap = mapping_snapshot({"u1": "bldg:database1"}, 100)
        drift = compare(snap, snap)
        assert drift.mapping_changed is False
        assert drift.note() == ""

    def test_a_graph_that_changed_without_touching_this_turn_says_so_quietly(self):
        """The honest middle case: something was written, none of it was ours."""
        drift = compare(
            mapping_snapshot({"u1": "bldg:database1"}, 100),
            mapping_snapshot({"u1": "bldg:database1"}, 105),
        )
        assert drift.statements_changed is True
        assert drift.mapping_changed is False
        assert drift.unexplained is True
        note = drift.note()
        assert "None of the sensors in this answer moved" in note

    def test_an_unreadable_count_is_not_reported_as_a_change(self):
        """None is not zero. Reporting drift because a health check failed would put a
        caveat on every turn during a GraphDB hiccup."""
        drift = compare(
            mapping_snapshot({"u1": "bldg:database1"}, None),
            mapping_snapshot({"u1": "bldg:database1"}, 105),
        )
        assert drift.statements_changed is False
        assert drift.note() == ""

    def test_the_note_never_says_the_answer_is_wrong(self):
        """A mapping that moved does not establish that the rows already fetched were the
        wrong ones. It establishes that two parts of the answer may describe different
        graph states — a narrower claim, and the true one."""
        drift = compare(
            mapping_snapshot({"u1": "a", "u2": "b"}, 100),
            mapping_snapshot({"u1": "z", "u2": "b"}, 100),
        )
        note = drift.note().lower()
        assert "may describe a different graph state" in note
        for overclaim in ("wrong", "incorrect", "invalid", "discard"):
            assert overclaim not in note

    def test_the_fingerprint_is_a_detector_and_says_so(self):
        """An equal-count replace is invisible to a statement count. A module claiming
        otherwise would be trusted for something it cannot do."""
        import inspect

        from orchestrator.services import graph_snapshot

        doc = inspect.getdoc(graph_snapshot) or ""
        assert "equal-count replace" in doc
        assert "never a proof" in doc or "detector" in doc

    def test_an_empty_mapping_is_survivable(self):
        assert compare(GraphSnapshot(), GraphSnapshot()).mapping_changed is False
        assert mapping_snapshot(None).mapping == {}
        assert mapping_snapshot({"": "x", "u": ""}).mapping == {}


@pytest.mark.unit
class TestThePolicyIsActuallyApplied:
    """A snapshot nothing takes, or takes and never compares, is the V6-T10 failure."""

    def _src(self) -> str:
        from pathlib import Path

        return (
            Path(__file__).resolve().parent.parent / "orchestrator/workflow/_orchestrator.py"
        ).read_text(encoding="utf-8")

    def test_the_snapshot_is_taken_at_discovery(self):
        src = self._src()
        assert "mapping_snapshot(" in src
        # It must be pinned BEFORE the fetch, or it records the mapping the fetch used and
        # can never disagree with it.
        assert src.index("mapping_snapshot(") < src.index("fetch_data_for_uuids")

    def test_the_drift_is_checked_before_the_answer_is_transcribed(self):
        src = self._src()
        assert "_snap_compare(" in src
        assert src.index("_snap_compare(") < src.index('role="assistant"')

    def test_the_snapshot_does_not_survive_into_the_next_turn(self):
        """Stale, the check compares THIS turn's mapping against the PREVIOUS question's
        and reports a move that never happened to anyone."""
        from orchestrator.workflow._orchestrator import _PER_TURN_LANE_KEYS

        assert "_graph_snapshot" in _PER_TURN_LANE_KEYS
        assert "graph_drift" in _PER_TURN_LANE_KEYS

    def test_it_reports_and_never_retries(self):
        """A retry would answer from the NEW mapping and say nothing about the old one —
        the same silent substitution, one layer up.

        Scoped to the drift block, and with COMMENTS STRIPPED. Two earlier versions of this
        assertion failed on prose rather than code: a ±2000-char window caught "retry"
        inside an unrelated comment about the publication gate, and narrowing to the block
        then caught it inside the block's OWN comment explaining why it does not retry. A
        guard that fires on its own rationale is the third instance of this shape today —
        scan code, never text.
        """
        src = self._src()
        start = src.index("# DID THE MAPPING MOVE WHILE WE WERE ANSWERING?")
        end = src.index("# A LANE THAT TIMED OUT AND A LANE THAT BROKE", start)
        code = "\n".join(
            line.split("#", 1)[0] for line in src[start:end].splitlines()
        )

        assert "_snap_compare(" in code, "the markers no longer bracket the drift check"
        for fetching in ("retry", "re-fetch", "refetch", "fetch_data_for_uuids("):
            assert fetching not in code, f"the drift check {fetching}s instead of reporting"


@pytest.mark.unit
class TestEveryAdapterRefusesAnUnbuiltQuery:
    """BUG-532: `build_timeseries_query` returns None when it cannot build one, and every
    `validate_query` then crashed on `.upper()` — inside the SAFETY CHECK, three layers from
    the actual mistake. A guard that fails by raising on its own first line reports a
    validation bug as an unrelated type error."""

    @pytest.mark.parametrize(
        "module_name, cls_name",
        [
            ("postgresql_adapter", "PostgreSQLAdapter"),
            ("cassandra_adapter", "CassandraAdapter"),
            ("mysql_adapter", "MySQLAdapter"),
            ("sqlite_adapter", "SQLiteAdapter"),
            ("influxdb_adapter", "InfluxDBAdapter"),
            ("mongodb_adapter", "MongoDBAdapter"),
            ("redis_timeseries_adapter", "RedisTimeSeriesAdapter"),
        ],
    )
    def test_a_none_query_is_a_value_error_not_an_attribute_error(self, module_name, cls_name):
        import importlib

        try:
            mod = importlib.import_module(f"orchestrator.services.adapters.{module_name}")
        except ModuleNotFoundError as exc:
            # An adapter whose driver is not installed cannot be exercised. A skip is
            # honest; importing it anyway would make this test about packaging.
            pytest.skip(f"{module_name} driver absent: {exc}")

        cls = getattr(mod, cls_name)
        inst = cls.__new__(cls)  # no connection needed: validation is pure

        # ONLY the unbuilt cases. `"   "` is a MALFORMED query, not an unbuilt one, and
        # every adapter is already right to refuse it with its own wording — demanding one
        # message for two different faults was this test over-reaching on its first run.
        for unbuilt in (None, ""):
            with pytest.raises(ValueError) as exc:
                cls.validate_query(inst, unbuilt)
            assert "get_columns" in str(exc.value), (
                "the refusal does not name the usual cause, so the reader has to guess"
            )

    @pytest.mark.parametrize(
        "module_name, cls_name",
        [
            ("postgresql_adapter", "PostgreSQLAdapter"),
            ("cassandra_adapter", "CassandraAdapter"),
            ("mysql_adapter", "MySQLAdapter"),
        ],
    )
    def test_a_whitespace_query_is_still_refused_however_it_is_worded(self, module_name, cls_name):
        """Different fault, same requirement: it must not reach the store."""
        import importlib

        mod = importlib.import_module(f"orchestrator.services.adapters.{module_name}")
        cls = getattr(mod, cls_name)
        with pytest.raises(ValueError):
            cls.validate_query(cls.__new__(cls), "   ")


# ── A15: parity, against real servers ────────────────────────────────────────


def _ts_adapter():
    from orchestrator.services.adapters.timescaledb_adapter import TimescaleDBAdapter

    return TimescaleDBAdapter(
        host=TS_HOST,
        port=TS_PORT,
        user=os.environ.get("TIMESCALE_USER", "ontosage"),
        password=os.environ.get("TIMESCALE_PASSWORD", "ontosage_ts_secret"),
        database=os.environ.get("TIMESCALE_DB", "sensordb"),
    )


def _cs_adapter():
    from orchestrator.services.adapters.cassandra_adapter import CassandraAdapter

    return CassandraAdapter(
        host=CS_HOST, port=CS_PORT, keyspace="ontosage", table="sensor_readings"
    )


async def _series(adapter, uuid: str, ts_col: str, limit: int = 500) -> List[Tuple[str, float]]:
    """[(timestamp, value)] newest-first, as the adapter returns them.

    `get_columns()` is called before building, and that is not ceremony: it populates the
    adapter's validated-uuid set, and `build_timeseries_query` returns **None** for a uuid
    it has not yet seen. Omitting it made the first run of this file fail with
    `AttributeError: 'NoneType' object has no attribute 'upper'` — raised inside the SAFETY
    CHECK, three layers from the actual mistake. Every adapter now refuses a None query with
    a message naming this exact cause (BUG-532).
    """
    await adapter.connect()
    try:
        await adapter.get_columns()
        sql = adapter.build_timeseries_query([uuid], ts_col, None, None, limit)
        assert sql, f"no query built for {uuid} — get_columns() did not validate it"
        result = await adapter.execute_query(sql)
        assert getattr(result, "success", False), f"query failed: {getattr(result, 'error', '?')}"
        out = []
        for row in result.data or []:
            stamp = row.get(ts_col) or row.get("timestamp") or row.get("time")
            out.append((str(stamp), float(row["value"])))
        return out
    finally:
        await adapter.close()


async def _shared_uuid() -> Optional[str]:
    """A uuid present in BOTH stores, read back from the stores themselves.

    Never a constant. The seeder chooses its sensors from the live graph, so a hardcoded
    uuid pins the test to one seed run — which is exactly how the two live tests in
    `test_timescale_cassandra_adapters.py` came to fail against healthy servers.
    """
    ts, cs = _ts_adapter(), _cs_adapter()
    await ts.connect()
    try:
        ts_ids = set(await ts.get_columns())
    finally:
        await ts.close()
    await cs.connect()
    try:
        cs_ids = set(await cs.get_columns())
    finally:
        await cs.close()
    shared = sorted(ts_ids & cs_ids)
    return shared[0] if shared else None


def _summary(series: List[Tuple[str, float]]) -> Dict[str, Any]:
    values = [v for _, v in series]
    newest = max(series, key=lambda p: p[0])
    return {
        "count": len(values),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "mean": round(statistics.fmean(values), 6),
        "latest_at": newest[0][:19],
        "latest_value": round(newest[1], 6),
    }


@pytest.mark.integration
@both_up
class TestAdapterParity:
    def test_both_stores_hold_the_same_sensors(self):
        uuid = asyncio.run(_shared_uuid())
        assert uuid, (
            "no uuid is present in both stores — re-run "
            "scripts/seed_timeseries_backends.py before this test means anything"
        )

    def test_the_same_series_gives_the_same_semantic_result(self):
        """Count, min, max and mean, through SQL on a hypertable and CQL on a partitioned
        table."""
        uuid = asyncio.run(_shared_uuid())
        if not uuid:
            pytest.skip("nothing seeded into both stores")

        ts = _summary(asyncio.run(_series(_ts_adapter(), uuid, "time")))
        cs = _summary(asyncio.run(_series(_cs_adapter(), uuid, "timestamp")))

        assert ts["count"] == cs["count"], f"row counts differ: {ts['count']} vs {cs['count']}"
        assert ts["min"] == cs["min"]
        assert ts["max"] == cs["max"]
        assert abs(ts["mean"] - cs["mean"]) < 1e-6

    def test_the_same_series_gives_the_same_evidence(self):
        """The half a recommendation rests on. Two stores can agree on every statistic and
        disagree about WHICH reading is the latest, and "when was this true" is not a
        detail — it is the claim's expiry date."""
        uuid = asyncio.run(_shared_uuid())
        if not uuid:
            pytest.skip("nothing seeded into both stores")

        ts = _summary(asyncio.run(_series(_ts_adapter(), uuid, "time")))
        cs = _summary(asyncio.run(_series(_cs_adapter(), uuid, "timestamp")))

        assert ts["latest_at"] == cs["latest_at"], (
            f"the stores disagree about the newest reading: {ts['latest_at']} vs "
            f"{cs['latest_at']}"
        )
        assert abs(ts["latest_value"] - cs["latest_value"]) < 1e-6

    def test_both_return_newest_first(self):
        """The ordering contract every caller assumes, asserted for both rather than one.
        A store that returned ascending would make `latest` the oldest reading — which is
        BUG-520, one layer down."""
        uuid = asyncio.run(_shared_uuid())
        if not uuid:
            pytest.skip("nothing seeded into both stores")

        for adapter, col in ((_ts_adapter(), "time"), (_cs_adapter(), "timestamp")):
            stamps = [t for t, _ in asyncio.run(_series(adapter, uuid, col))]
            assert stamps == sorted(stamps, reverse=True), f"{adapter} returned ascending"

    def test_a_row_limit_is_honoured_by_both(self):
        uuid = asyncio.run(_shared_uuid())
        if not uuid:
            pytest.skip("nothing seeded into both stores")

        assert len(asyncio.run(_series(_ts_adapter(), uuid, "time", limit=10))) == 10
        assert len(asyncio.run(_series(_cs_adapter(), uuid, "timestamp", limit=10))) == 10

    def test_the_timescale_table_really_is_a_hypertable(self):
        """A plain table inside Timescale exercises PostgreSQL, not TimescaleDB — so the
        paper's claim would rest on the wrong thing."""

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
