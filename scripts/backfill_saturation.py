# -*- coding: utf-8 -*-
"""
backfill_saturation.py — write correlated history for SATURATE sensors (V4-T10).

Discovers the active building's simulated sensors from the graph (the ones the
provisioner marked `synthetic-saturation-v4`), generates N weeks of correlated
10-minute history per room (one shared occupancy driver per room-day), and
INSERT IGNOREs the rows into each modality's narrow table. Deterministic seeds
make re-runs converge to the identical dataset — and give the L7 grader exact
ground truth.

RUN (inside the data-publisher container, which has graph + MySQL access):
  docker exec data-publisher python /app/scripts/backfill_saturation.py --weeks 5
Host-side works too when localhost MySQL/GraphDB are reachable.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))

import pymysql  # noqa: E402

from orchestrator.services.deliberation.live import active_identity, sparql_exec  # noqa: E402
from orchestrator.services.deliberation.synthetic_signals import (  # noqa: E402
    day_timestamps,
    generate_room_day,
)

_MARKER = "synthetic-saturation-v4"
_BATCH = 5000


def _mysql():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "mysql"),
        database=os.environ.get("MYSQL_DATABASE", "sensordb"),
        autocommit=False,
    )


async def _discover(namespace: str) -> List[Dict[str, str]]:
    """(sensor, uuid, table, space_local, modality) for every saturation sensor."""
    q = (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
        "PREFIX ref: <https://brickschema.org/schema/Brick/ref#>\n"
        "SELECT ?s ?uuid ?st ?space WHERE {\n"
        f'  ?s rdfs:comment "{_MARKER}" ;\n'
        "     brick:hasLocation ?space ;\n"
        "     ref:hasExternalReference [ ref:hasTimeseriesId ?uuid ; ref:storedAt ?st ] .\n"
        f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
        "}"
    )
    result = await sparql_exec(q)
    sensors = []
    for b in result.get("results", {}).get("bindings", []):
        sensor = b["s"]["value"]
        local = sensor.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        # provisioner convention: <spaceLocal>_sat_<modality>
        if "_sat_" not in local:
            continue
        space_local, modality = local.rsplit("_sat_", 1)
        sensors.append(
            {
                "uuid": b["uuid"]["value"],
                "table": b["st"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1],
                "space_local": space_local,
                "modality": modality,
            }
        )
    return sensors


def _backfill(building_id: str, sensors: List[Dict[str, str]], weeks: int) -> Dict[str, int]:
    by_room: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for s in sensors:
        by_room[s["space_local"]].append(s)

    end_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    days = [end_day - timedelta(days=d) for d in range(weeks * 7, 0, -1)]

    conn = _mysql()
    written: Dict[str, int] = defaultdict(int)
    pending: Dict[str, List[Tuple[str, datetime, float]]] = defaultdict(list)

    def _flush(table: str) -> None:
        rows = pending[table]
        if not rows:
            return
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT IGNORE INTO {table} (uuid, datetime, value) VALUES (%s, %s, %s)",
                rows,
            )
        conn.commit()
        written[table] += len(rows)
        pending[table] = []

    for di, day in enumerate(days, 1):
        stamps = day_timestamps(day)
        for space_local, room_sensors in by_room.items():
            modalities = [s["modality"] for s in room_sensors]
            series = generate_room_day(building_id, space_local, modalities, day)
            for s in room_sensors:
                values = series[s["modality"]]
                pending[s["table"]].extend((s["uuid"], ts, v) for ts, v in zip(stamps, values))
                if len(pending[s["table"]]) >= _BATCH:
                    _flush(s["table"])
        if di % 7 == 0:
            print(f"[backfill] {di}/{len(days)} days generated", flush=True)
    for table in list(pending):
        _flush(table)
    conn.close()
    return dict(written)


async def _run(weeks: int) -> int:
    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]
    print(f"[backfill] building={building_id} weeks={weeks}")
    sensors = await _discover(namespace)
    if not sensors:
        print("[backfill] ERROR: no saturation sensors found — run saturate_building.py first")
        return 1
    rooms = len({s["space_local"] for s in sensors})
    print(f"[backfill] {len(sensors)} sensors across {rooms} rooms")
    written = _backfill(building_id, sensors, weeks)
    total = sum(written.values())
    print(f"[backfill] wrote {total:,} rows:")
    for table, n in sorted(written.items()):
        print(f"  {table:<20} {n:>10,}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SATURATE correlated backfill (V4-T10)")
    parser.add_argument("--weeks", type=int, default=5, help="Weeks of history (default 5)")
    args = parser.parse_args()
    return asyncio.run(_run(args.weeks))


if __name__ == "__main__":
    sys.exit(main())
