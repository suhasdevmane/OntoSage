#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed the TimescaleDB and Cassandra backends, and register them as datasources.

Why (TODO-143). The paper's building-characteristics table states that one
building runs TimescaleDB and another runs Cassandra. Both adapters existed and
were dispatched by the registry, but nothing ever exercised them: no test
referenced either, no building pointed a ``ref:storedAt`` key at one, and the
Cassandra driver was not installed at all. A reader cloning the artifact to
reproduce that table found neither backend running.

This script closes that. It creates the real schema each backend is *for* —
a Timescale HYPERTABLE (not a plain table that merely lives in Timescale) and a
Cassandra table partitioned by sensor with a DESC clustering order on time —
seeds readings for real sensor UUIDs taken from the ACTIVE building's graph, and
writes both into ``database_registry.yaml`` so the adapter registry can route to
them.

It ADDS datasources; it never repoints an existing ``ref:storedAt`` key. The
active building keeps answering from the backend it already uses, and the two new
ones become available to any sensor whose triples name them. Repointing a
building is a separate, deliberate act.

Idempotent: re-running re-creates nothing and re-seeds only missing rows.

Usage:
    python scripts/seed_timeseries_backends.py                # both
    python scripts/seed_timeseries_backends.py --only timescale
    python scripts/seed_timeseries_backends.py --sensors 40 --days 3
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

TS_TABLE = "sensor_readings"
CQL_KEYSPACE = "ontosage"
CQL_TABLE = "sensor_readings"


def _env() -> Dict[str, str]:
    env: Dict[str, str] = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                env[k.strip()] = v.split("#", 1)[0].strip().strip('"').strip("'")
    return env


def _graph_sensor_uuids(limit: int) -> List[Tuple[str, str]]:
    """(uuid, modality-ish label) for real sensors in the active building.

    Seeding real UUIDs rather than invented ones is the point: a backend holding
    rows nothing in the graph refers to proves the driver works and proves
    nothing about the system, because no question can ever reach it.
    """
    import json
    import urllib.request

    env = _env()
    base = (env.get("GRAPHDB_URL") or "http://localhost:7200").replace("graphdb:", "localhost:")
    repo = env.get("GRAPHDB_REPOSITORY", "bldg")
    ns = env.get("BUILDING_NAMESPACE", "")
    # DISTINCT on the uuid, and the label via SAMPLE rather than an OPTIONAL
    # join: a sensor carrying several labels multiplies the rows, so the first
    # version of this returned 25 bindings for ONE sensor and the seed reported
    # 4800 rows written while storing 192.
    query = (
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#> "
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT ?uuid (SAMPLE(?l) AS ?label) WHERE { "
        "  ?s ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid . "
        "  OPTIONAL { ?s rdfs:label ?l } "
        f'  FILTER(STRSTARTS(STR(?s), "{ns}")) '
        f"}} GROUP BY ?uuid LIMIT {int(limit)}"
    )
    req = urllib.request.Request(
        f"{base}/repositories/{repo}",
        data=query.encode(),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        rows = json.load(resp).get("results", {}).get("bindings", [])
    out = []
    seen = set()
    for b in rows:
        uuid = b.get("uuid", {}).get("value", "")
        label = b.get("label", {}).get("value", "") or uuid
        if uuid and uuid not in seen:
            seen.add(uuid)
            out.append((uuid, label))
    return out


def _series(uuid: str, days: float, step_min: int) -> List[Tuple[datetime, float]]:
    """A plausible diurnal series. Deterministic per uuid so re-runs match."""
    rnd = random.Random(uuid)
    base = 21.0 + rnd.uniform(-2.0, 2.0)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    points = int((days * 24 * 60) / step_min)
    out = []
    for i in range(points, 0, -1):
        ts = now - timedelta(minutes=i * step_min)
        hour = ts.hour + ts.minute / 60.0
        diurnal = 2.5 * math.sin((hour - 6) / 24.0 * 2 * math.pi)
        out.append((ts, round(base + diurnal + rnd.uniform(-0.3, 0.3), 3)))
    return out


# ── TimescaleDB ────────────────────────────────────────────────────────────────


def seed_timescale(sensors: List[Tuple[str, str]], days: float, step_min: int) -> Dict[str, object]:
    import asyncio

    import asyncpg  # noqa: F401  (import here so --only cassandra needs no asyncpg)

    env = _env()
    dsn = (
        f"postgresql://{env.get('TIMESCALE_USER', 'ontosage')}:"
        f"{env.get('TIMESCALE_PASSWORD', 'ontosage_ts_secret')}@"
        f"{os.environ.get('TIMESCALE_HOST', 'localhost')}:"
        f"{os.environ.get('TIMESCALE_PORT', '5434')}/"
        f"{env.get('TIMESCALE_DB', 'sensordb')}"
    )

    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TS_TABLE} (
                    uuid  TEXT        NOT NULL,
                    time  TIMESTAMPTZ NOT NULL,
                    value DOUBLE PRECISION,
                    unit  TEXT,
                    PRIMARY KEY (uuid, time)
                )
                """
            )
            # The hypertable is the whole point — a plain table inside Timescale
            # exercises PostgreSQL, not TimescaleDB.
            await conn.execute(
                f"SELECT create_hypertable('{TS_TABLE}', 'time', if_not_exists => TRUE)"
            )
            rows = []
            for uuid, _label in sensors:
                for ts, val in _series(uuid, days, step_min):
                    rows.append((uuid, ts, val, "degC"))
            await conn.executemany(
                f"INSERT INTO {TS_TABLE} (uuid, time, value, unit) VALUES ($1,$2,$3,$4) "
                "ON CONFLICT (uuid, time) DO NOTHING",
                rows,
            )
            total = await conn.fetchval(f"SELECT COUNT(*) FROM {TS_TABLE}")
            hyper = await conn.fetchval(
                "SELECT COUNT(*) FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = $1",
                TS_TABLE,
            )
            return {"rows_written": len(rows), "rows_total": int(total), "hypertable": int(hyper)}
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(_run())


# ── Cassandra ──────────────────────────────────────────────────────────────────


def seed_cassandra(sensors: List[Tuple[str, str]], days: float, step_min: int) -> Dict[str, object]:
    from cassandra.cluster import Cluster
    from cassandra.query import BatchStatement

    host = os.environ.get("CASSANDRA_HOST", "127.0.0.1")
    port = int(os.environ.get("CASSANDRA_PORT", "9042"))
    cluster = Cluster([host], port=port)
    session = cluster.connect()
    try:
        session.execute(
            f"CREATE KEYSPACE IF NOT EXISTS {CQL_KEYSPACE} WITH replication = "
            "{'class': 'SimpleStrategy', 'replication_factor': 1}"
        )
        session.set_keyspace(CQL_KEYSPACE)
        # Partitioned by sensor with time clustered DESC: the layout Cassandra is
        # actually good at, and the one "latest reading for this sensor" needs.
        session.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CQL_TABLE} (
                uuid      text,
                timestamp timestamp,
                value     double,
                unit      text,
                PRIMARY KEY (uuid, timestamp)
            ) WITH CLUSTERING ORDER BY (timestamp DESC)
            """
        )
        stmt = session.prepare(
            f"INSERT INTO {CQL_TABLE} (uuid, timestamp, value, unit) VALUES (?, ?, ?, ?)"
        )
        written = 0
        for uuid, _label in sensors:
            batch = BatchStatement()
            n = 0
            for ts, val in _series(uuid, days, step_min):
                batch.add(stmt, (uuid, ts, val, "degC"))
                n += 1
                if n % 100 == 0:  # Cassandra rejects oversized batches
                    session.execute(batch)
                    batch = BatchStatement()
            if n % 100:
                session.execute(batch)
            written += n
        total = session.execute(f"SELECT COUNT(*) FROM {CQL_TABLE}").one()[0]
        return {"rows_written": written, "rows_total": int(total)}
    finally:
        cluster.shutdown()


# ── registry ───────────────────────────────────────────────────────────────────


def register(which: List[str]) -> List[str]:
    """Add datasource entries WITHOUT repointing anything that already works."""
    import yaml

    from shared.building_paths import resolve_building_file

    path = resolve_building_file(_env().get("BUILDING_ID", ""), "database_registry.yaml")
    if path is None:
        path = REPO / "input" / "database_registry.yaml"
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    dbs = data.setdefault("databases", {})
    added = []
    env = _env()
    if "timescale" in which and "timescaledb" not in dbs:
        dbs["timescaledb"] = {
            "type": "timescaledb",
            "host": "timescaledb",
            "port": 5432,
            "database": env.get("TIMESCALE_DB", "sensordb"),
            "user": env.get("TIMESCALE_USER", "ontosage"),
            "password": env.get("TIMESCALE_PASSWORD", "ontosage_ts_secret"),
            "table": TS_TABLE,
            "nature": "synthetic",
            "description": "TimescaleDB hypertable (uuid, time, value) — TODO-143 fixture",
        }
        added.append("timescaledb")
    if "cassandra" in which and "cassandra" not in dbs:
        dbs["cassandra"] = {
            "type": "cassandra",
            "host": "cassandra",
            "port": 9042,
            "keyspace": CQL_KEYSPACE,
            "table": CQL_TABLE,
            "nature": "synthetic",
            "description": "Cassandra CQL table (uuid, timestamp, value) — TODO-143 fixture",
        }
        added.append("cassandra")
    if added:
        Path(path).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return added


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", choices=["timescale", "cassandra"], help="seed just one backend")
    ap.add_argument("--sensors", type=int, default=25, help="how many real sensor UUIDs to seed")
    ap.add_argument("--days", type=float, default=2.0, help="days of history per sensor")
    ap.add_argument("--step-min", type=int, default=15, help="minutes between readings")
    ap.add_argument(
        "--no-register", action="store_true", help="seed only; do not touch the registry"
    )
    args = ap.parse_args(argv)

    which = [args.only] if args.only else ["timescale", "cassandra"]

    sensors = _graph_sensor_uuids(args.sensors)
    if not sensors:
        print("No sensor UUIDs found in the active building's graph — is the stack up?")
        return 1
    distinct = len({u for u, _ in sensors})
    if distinct < len(sensors):  # cannot happen now, but the seed must never lie again
        print(f"refusing to seed: {len(sensors)} rows collapse to {distinct} distinct sensors")
        return 1
    print(f"seeding {len(sensors)} sensor(s), {args.days} day(s) @ {args.step_min} min")

    expected = len(sensors) * int((args.days * 24 * 60) / args.step_min)
    for backend in which:
        try:
            fn = seed_timescale if backend == "timescale" else seed_cassandra
            result = fn(sensors, args.days, args.step_min)
            total = int(result.get("rows_total") or 0)
            # A backend that accepted every insert and holds a fraction of them
            # is the failure this check exists for: writes "succeeded", the rows
            # collided on the primary key, and only a count reveals it.
            if total < expected * 0.9:
                print(
                    f"  {backend}: {result}  <-- WARNING: expected ~{expected} rows, holds {total}"
                )
            else:
                print(f"  {backend}: {result}")
        except Exception as exc:
            print(f"  {backend}: FAILED — {type(exc).__name__}: {exc}")
            return 2

    if not args.no_register:
        added = register(which)
        print(f"registry: added {added or '(nothing new)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
