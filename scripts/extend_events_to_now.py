# -*- coding: utf-8 -*-
"""
extend_events_to_now.py — bring the events store's time-based kinds up to now (CAVEAT-672).

The events store's access, booking, work-order and asset-outage rows were seeded once by
scripts/backfill_events.py and never continued, so they stopped on 2026-09-04 while every
sensor store stayed current. The data-publisher now keeps them live, but only over a short
window; this script closes the gap from each kind's last written row to now, refreshes the
lifecycle of rows whose status was stamped at generation time and never revisited, and
writes the events map the publisher reads.

REUSE, NOT A SECOND GENERATOR. Rows come from the orchestrator's own synthetic_events.py,
loaded through the SAME loader and windowing the publisher uses, so what this script writes
and what the container writes afterwards cannot drift apart. Rooms and service assets are
discovered from the building graph exactly as the backfill discovered them (its own
functions are imported), which is what makes the generated ids equal to the stored ones.

NEVER WRITES `anomaly:*`. The orchestrator's scanner owns those rows (BUG-666).

WRITES NOTHING WITHOUT --apply: no rows, no map file. A dry run prints, per kind, the last
stored row, how many rows would be inserted, and how many lifecycles would change.

RUN (host-side, stack up; GraphDB and MySQL reachable):
  MYSQL_HOST=127.0.0.1 python -X utf8 scripts/extend_events_to_now.py            # dry run
  MYSQL_HOST=127.0.0.1 python -X utf8 scripts/extend_events_to_now.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PUBLISHER_DIR = _REPO_ROOT / "mysql-dummy-publish-dev"
GENERATOR_DIR = _REPO_ROOT / "orchestrator" / "services" / "deliberation"

for _p in (str(_REPO_ROOT), str(_PUBLISHER_DIR), str(_REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mysql_dummy_publisher as publisher  # noqa: E402

#: Statuses that are still waiting on something. A row in one of these whose moment has
#: passed may be stale, so its day is re-derived even if it lies before the last row.
_UNFINISHED = {
    "booking": ("confirmed",),
    "workorder": ("open", "assigned"),
    "asset_outage": ("open",),
}

_TS = "%Y-%m-%d %H:%M:%S"


def build_events_spec(
    building_id: str,
    rooms: Sequence[str],
    assets: Sequence[Tuple[str, str]],
    subject_uuid_namespace: str,
    forward_days: int = 14,
) -> Dict[str, object]:
    """The events map the publisher reads. Discovered values only; no building literal."""
    kinds = {k: dict(v) for k, v in publisher._EVENT_KIND_DEFAULTS.items()}
    kinds["booking"]["forward_days"] = max(0, int(forward_days))
    return {
        "building_id": building_id,
        "table": "events",
        "rooms": sorted(str(r) for r in rooms),
        "assets": [[str(a), str(k)] for a, k in assets],
        "subject_uuid_namespace": str(subject_uuid_namespace),
        "kinds": kinds,
        # Internal provenance, never shown to a user: these records are generated placeholders
        # standing in for the building's real booking, access and maintenance feeds.
        "nature": "synthetic",
        "generated_by": "scripts/extend_events_to_now.py",
        "generated_at": datetime.utcnow().strftime(_TS),
    }


def _fmt(v) -> Optional[str]:
    if v is None:
        return None
    return v.strftime(_TS) if isinstance(v, datetime) else str(v)


def _parse(v) -> Optional[datetime]:
    if v is None:
        return None
    return v if isinstance(v, datetime) else datetime.strptime(str(v)[:19], _TS)


def plan_kind(
    cur,
    spec: Dict[str, object],
    kind: str,
    now: datetime,
    max_days_back: int,
) -> Dict[str, object]:
    """Read-only: what extending `kind` to now would insert and refresh."""
    if publisher._is_foreign_kind(kind) or kind not in publisher.EVENT_KINDS:
        raise ValueError(f"not a publishable event kind: {kind}")
    table = str(spec.get("table") or "events")
    cur.execute(
        f"SELECT MIN(start_dt), MAX(start_dt), COUNT(*) FROM `{table}` WHERE event_type=%s",
        (kind,),
    )
    first_row, last_row, n_rows = cur.fetchone()
    stale_from = None
    if kind in _UNFINISHED:
        marks = ", ".join(["%s"] * len(_UNFINISHED[kind]))
        cur.execute(
            f"SELECT MIN(start_dt) FROM `{table}` WHERE event_type=%s "
            f"AND status IN ({marks}) AND start_dt <= %s",
            (kind, *_UNFINISHED[kind], now.strftime(_TS)),
        )
        stale_from = cur.fetchone()[0]

    today = publisher._day0(now)
    floor_day = today - timedelta(days=max_days_back)
    last_row_dt = _parse(last_row)
    candidates = [d for d in (_parse(last_row), _parse(stale_from)) if d is not None]
    first_day = publisher._day0(min(candidates)) if candidates else today
    first_day = max(first_day, floor_day)
    forward = int(dict(spec["kinds"])[kind].get("forward_days", 0))
    last_day = today + timedelta(days=forward)

    rows = publisher.event_rows_for_window(
        publisher.EVENTS_GEN, spec, kind, first_day, last_day, now
    )
    cur.execute(
        f"SELECT event_id, status, end_dt FROM `{table}` WHERE event_type=%s "
        f"AND start_dt >= %s AND start_dt < %s",
        (kind, first_day.strftime(_TS), (last_day + timedelta(days=1)).strftime(_TS)),
    )
    stored = {r[0]: (r[1], _fmt(r[2])) for r in cur.fetchall()}

    # New rows only from the day of the last stored row onwards. Before it, the period was
    # written by an earlier run, possibly over a different room list; adding this list's
    # buckets there would inflate footfall that is already on record.
    insert_from = publisher._day0(last_row_dt) if last_row_dt is not None else floor_day
    to_insert, to_refresh, skipped_old = [], [], 0
    for r in rows:
        if r[0] in stored:
            if stored[r[0]] != (r[5], r[4]):
                to_refresh.append(r)
        elif _parse(r[3]) >= insert_from:
            to_insert.append(r)
        else:
            skipped_old += 1
    return {
        "kind": kind,
        "rows_stored": int(n_rows or 0),
        "first_row": _fmt(first_row),
        "last_row": _fmt(last_row),
        "stale_from": _fmt(stale_from),
        "window": (first_day.strftime("%Y-%m-%d"), last_day.strftime("%Y-%m-%d")),
        "insert": to_insert,
        "refresh": to_refresh,
        "skipped_in_written_period": skipped_old,
    }


def run(
    argv: Optional[Sequence[str]],
    *,
    connect: Callable[[], object],
    discover: Callable[[], Tuple[str, List[str], List[Tuple[str, str]], str]],
    now: Optional[datetime] = None,
    generator_dir: Optional[Path] = None,
    input_dir: Optional[Path] = None,
) -> int:
    """Plan (and with --apply, write) the extension. Injected I/O keeps it testable."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write rows and the events map")
    ap.add_argument("--forward-days", type=int, default=14, help="booking calendar horizon")
    ap.add_argument("--max-days-back", type=int, default=60, help="oldest day re-derived")
    ap.add_argument("--map-out", default=None, help="events map path (default input/<id>_...)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    now = now or datetime.utcnow()
    building_id, rooms, assets, namespace = discover()
    spec = build_events_spec(building_id, rooms, assets, namespace, args.forward_days)
    if not publisher.configure_events(spec, str(generator_dir or GENERATOR_DIR)):
        print("[events] the generator could not be configured; nothing planned", flush=True)
        return 2

    conn = connect()
    plans = []
    try:
        cur = conn.cursor()
        for kind in spec["kinds"]:
            plans.append(plan_kind(cur, publisher.EVENTS_SPEC, kind, now, args.max_days_back))

        print(f"[events] building={building_id} rooms={len(rooms)} assets={len(assets)} now={now}")
        for p in plans:
            print(
                f"[events] {p['kind']:<13} stored={p['rows_stored']:>6} last={p['last_row']} "
                f"stale_from={p['stale_from']} window={p['window'][0]}..{p['window'][1]} "
                f"insert={len(p['insert'])} refresh={len(p['refresh'])} "
                f"skipped_in_written_period={p['skipped_in_written_period']}"
            )

        if not args.apply:
            print("[events] DRY RUN — nothing written. Re-run with --apply to write.", flush=True)
            return 0

        map_out = (
            Path(args.map_out)
            if args.map_out
            else ((input_dir or _REPO_ROOT / "input") / f"{building_id}_events_publish_map.json")
        )
        map_out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        print(f"[events] wrote events map {map_out}")

        sql = publisher._EVENTS_UPSERT.format(table=publisher.EVENTS_TABLE)
        for p in plans:
            rows = [r for r in p["insert"] + p["refresh"] if not publisher._is_foreign_kind(r[1])]
            for i in range(0, len(rows), 500):
                cur.executemany(sql, rows[i : i + 500])
        conn.commit()
        for p in plans:
            cur.execute(
                f"SELECT COUNT(*), MAX(start_dt) FROM `{publisher.EVENTS_TABLE}` "
                f"WHERE event_type=%s AND start_dt <= %s",
                (p["kind"], now.strftime(_TS)),
            )
            n, last = cur.fetchone()
            print(f"[events] {p['kind']:<13} now stored={n} last_at_or_before_now={_fmt(last)}")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _real_discover() -> Tuple[str, List[str], List[Tuple[str, str]], str]:
    """Rooms and service assets exactly as scripts/backfill_events.py discovered them."""
    from backfill_events import _discover_assets

    from orchestrator.services import datasource_registry
    from orchestrator.services.deliberation.coverage_audit import (
        CoverageAuditor,
        load_modalities,
    )
    from orchestrator.services.deliberation.live import active_identity, sparql_exec

    identity = active_identity()
    building_id, namespace = identity["BUILDING_ID"], identity["BUILDING_NAMESPACE"]

    async def _go():
        auditor = CoverageAuditor(sparql_exec, load_modalities(building_id))
        spaces = await auditor.discover_spaces(namespace)
        rooms = sorted(s.space_iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] for s in spaces)
        return rooms, await _discover_assets(namespace)

    rooms, assets = asyncio.run(_go())
    return building_id, rooms, assets, str(datasource_registry._UUID_NS)


def _real_connect():
    from backfill_events import _mysql

    return _mysql()


if __name__ == "__main__":
    sys.exit(run(None, connect=_real_connect, discover=_real_discover))
