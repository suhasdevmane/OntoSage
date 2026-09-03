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
from types import SimpleNamespace

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
    outages_for_day,
    to_row,
)
from shared.db_clock import UTC_SESSION_INIT

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
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )


async def _discover_assets(namespace):
    """(local, kind) for every service asset this building types.

    By CLASS, never by name: the building's own ontology says what is a lift, and a
    building that types none simply gets no outages rather than invented ones.
    """
    kinds = (("Lift", "lift"), ("AVEquipment", "av"), ("NetworkService", "network"))
    out = []
    for class_local, kind in kinds:
        q = (
            "PREFIX ontosage: <http://ontosage.org/capabilities#> "
            f"SELECT DISTINCT ?s WHERE {{ ?s a ontosage:{class_local} . "
            f'FILTER(STRSTARTS(STR(?s), "{namespace}")) }}'
        )
        try:
            res = await sparql_exec(q)
        except Exception:
            continue
        for b in res.get("results", {}).get("bindings", []):
            iri = b["s"]["value"]
            out.append((iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1], kind))
    return out


def _ingest_institutional(building_id, rooms, cur):
    """Ingest every institutional source this building DECLARES in feeds.yaml.

    V6-T25 built the adapter and the registry maps its source kinds, but NOTHING EVER
    CALLED IT: the polling loop cannot, because these are one-shot file reads with a
    read() interface rather than pollers, and no other caller existed. A building could
    therefore declare a timetable, have the file sitting on disk, and still answer "no
    data" - the described-but-unconnected failure, one level up from the sensor case.

    Space resolution stays strict: the adapter SKIPS rows naming a room the building
    does not have and reports them, rather than binding them to the nearest match.
    """
    from orchestrator.services.feeds.institutional import (
        SOURCE_KINDS,
        InstitutionalFeedAdapter,
    )

    out = []
    feeds_path = _REPO_ROOT / "input" / "feeds.yaml"
    try:
        import yaml

        specs = (yaml.safe_load(feeds_path.read_text(encoding="utf-8")) or {}).get("feeds") or []
    except Exception as exc:
        return [f"no institutional sources read ({exc})"]

    for entry in specs:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type", "")
        if kind not in SOURCE_KINDS or not entry.get("enabled", True):
            continue
        spec = SimpleNamespace(**entry)
        adapter = InstitutionalFeedAdapter(spec, input_root=str(_REPO_ROOT / "input"))
        records, report = adapter.read(rooms)
        rows = []
        for rec in records:
            e = rec.as_event(building_id, adapter.event_type)
            rows.append(
                (
                    e["event_id"],
                    e["event_type"],
                    e["subject_uuid"],
                    e["start_dt"].strftime("%Y-%m-%d %H:%M:%S"),
                    e["end_dt"].strftime("%Y-%m-%d %H:%M:%S") if e["end_dt"] else None,
                    e["status"],
                    e["attrs"],
                )
            )
        if rows:
            cur.executemany(_INSERT, rows)
        out.append(f"{entry.get('id', '?')}: {report.describe()}")
    return out or ["no institutional sources declared"]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=5)
    ap.add_argument(
        "--skip-institutional",
        action="store_true",
        help="do not ingest institutional sources declared in feeds.yaml. They are "
        "ingested by default because a declared timetable that nothing reads is the "
        "described-but-unconnected half of design contract 8 - and the feed registry "
        "cannot poll them: they are one-shot file reads, not pollers.",
    )
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
    assets = await _discover_assets(namespace)
    print(f"[events] service assets discovered: {len(assets)}")

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

        # Asset outage EPISODES. A status is not a fact but the current value of
        # something that changes, and it had been provisioned as a fact: one status per
        # asset, stamped once, never updated. Nothing had ever broken and nothing had
        # ever been fixed.
        if assets:
            aday = start_day
            while aday <= now:
                events = outages_for_day(building_id, assets, aday, now)
                if events:
                    cur.executemany(_INSERT, [to_row(e) for e in events])
                    for e in events:
                        generated[f"asset_outage ({e['status']})"] += 1
                aday += timedelta(days=1)

        if not args.skip_institutional:
            for line in _ingest_institutional(building_id, rooms, cur):
                print(f"[events] {line}")

        conn.commit()
        cur.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type")
        totals = dict(cur.fetchall())
    conn.close()

    print(f"[events] generated this run: {dict(generated)}")
    print(f"[events] table totals now:   {totals}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
