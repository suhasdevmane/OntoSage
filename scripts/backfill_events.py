# -*- coding: utf-8 -*-
"""
backfill_events.py — V5-T08: seed the events store with N weeks of history.

Discovers the active building's rooms via the coverage auditor, generates
deterministic bookings / work orders / access events per day, and inserts them
with INSERT IGNORE (event_id is a deterministic uuid5, so re-runs are no-ops).

RUN (host-side, stack up):
  MYSQL_HOST=localhost MYSQL_USER=ontosage MYSQL_DATABASE=<db> MYSQL_PASSWORD=... \
    python -X utf8 scripts/backfill_events.py --weeks 5
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import pymysql  # noqa: E402

from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    CoverageAuditor,
    load_modalities,
)
from orchestrator.services.deliberation.live import (  # noqa: E402
    active_identity,
    sparql_exec,
)
from orchestrator.services.deliberation.synthetic_events import (  # noqa: E402
    bookings_for_building_day,
    generate_building_day,
    to_row,
)

_INSERT = (
    "INSERT IGNORE INTO events "
    "(event_id, event_type, subject_uuid, start_dt, end_dt, status, attrs) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s)"
)


def _mysql():
    env = {}
    for line in (_REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", env.get("MYSQL_USER", "root")),
        password=os.environ.get("MYSQL_PASSWORD", env.get("MYSQL_PASSWORD", "")),
        database=os.environ.get("MYSQL_DATABASE", env.get("MYSQL_DATABASE", "sensordb")),
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=5)
    ap.add_argument(
        "--forward-weeks",
        type=int,
        default=2,
        help="weeks of FUTURE bookings to generate (default 2). A room calendar with "
        "no future entries cannot answer 'is this room free tomorrow?', which is most "
        "of what a booking system is asked. Only bookings are generated ahead of now: "
        "nobody has walked through a door tomorrow.",
    )
    args = ap.parse_args()

    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]
    auditor = CoverageAuditor(sparql_exec, load_modalities(building_id))
    spaces = await auditor.discover_spaces(namespace)
    rooms = sorted(s.space_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] for s in spaces)
    print(f"[events] building={building_id} rooms={len(rooms)} weeks={args.weeks}")

    now = datetime.utcnow()
    start_day = (now - timedelta(weeks=args.weeks)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    conn = _mysql()
    inserted = Counter()
    generated = Counter()
    day = start_day
    with conn.cursor() as cur:
        while day <= now:
            events = generate_building_day(building_id, rooms, day, now)
            if events:
                rows = [to_row(e) for e in events]
                cur.executemany(_INSERT, rows)
                for e in events:
                    generated[e["event_type"]] += 1
                inserted["rows"] += cur.rowcount if cur.rowcount > 0 else 0
            day += timedelta(days=1)
        # forward calendar: bookings only, from tomorrow to the horizon
        if args.forward_weeks > 0:
            fday = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            fend = now + timedelta(weeks=args.forward_weeks)
            while fday <= fend:
                events = bookings_for_building_day(building_id, rooms, fday, now)
                if events:
                    cur.executemany(_INSERT, [to_row(e) for e in events])
                    for e in events:
                        generated[f"{e['event_type']} (future)"] += 1
                fday += timedelta(days=1)

        conn.commit()
        cur.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type")
        totals = dict(cur.fetchall())
    conn.close()

    print(f"[events] generated this run: {dict(generated)}")
    print(f"[events] table totals now:   {totals}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
