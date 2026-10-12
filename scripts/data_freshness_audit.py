#!/usr/bin/env python3
"""Is every point the graph links to a time series actually fed, and how current is it?

For each point that carries `<p> …hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid ;
ref:storedAt ?store`, read the newest stored row from the store the registry names, and report
per store: points declared, points with any row, points fresh within --fresh-min, points with a
row in the last 24 h, and the oldest "newest row". The per-point detail goes to a CSV.

Read-only. Clocks: every store is UTC and the session is pinned to +00:00 (BUG-403).

    python scripts/data_freshness_audit.py                       # summary + CSV in outputs/
    python scripts/data_freshness_audit.py --fresh-min 15 --gaps # also the largest gap per narrow series (7 days)

Exit code 0 always (it is an instrument, not a gate); the summary says what is stale.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUERY = """PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?p ?uuid ?store WHERE {
  ?p ?hx ?r . FILTER(STRENDS(STR(?hx), "hasExternalReference"))
  ?r ?hid ?uuid . FILTER(STRENDS(STR(?hid), "hasTimeseriesId"))
  ?r ?sat ?store . FILTER(STRENDS(STR(?sat), "storedAt"))
}"""


def env(name: str, default: str = "") -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def local(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def graph_points(repo: str) -> List[Tuple[str, str, str]]:
    req = urllib.request.Request(
        f"http://127.0.0.1:7200/repositories/{repo}",
        data=QUERY.encode(),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    rows = json.load(urllib.request.urlopen(req, timeout=120))["results"]["bindings"]
    return [(b["p"]["value"], b["uuid"]["value"], local(b["store"]["value"])) for b in rows]


def registry() -> Dict[str, Dict]:
    d = yaml.safe_load((REPO / "input" / "database_registry.yaml").read_text(encoding="utf-8"))
    return {k: v for k, v in (d.get("databases") or {}).items() if isinstance(v, dict)}


def connect():
    import pymysql

    return pymysql.connect(
        host="127.0.0.1",
        port=int(env("MYSQL_PORT", "3306") or 3306),
        user=env("MYSQL_USER", "root"),
        password=env("MYSQL_PASSWORD"),
        database=env("MYSQL_DATABASE", "sensordb"),
        init_command="SET time_zone='+00:00'",
        connect_timeout=20,
    )


def newest_narrow(cur, table: str, uuids: List[str]) -> Dict[str, dt.datetime]:
    out: Dict[str, dt.datetime] = {}
    for i in range(0, len(uuids), 200):
        part = uuids[i : i + 200]
        marks = ",".join(["%s"] * len(part))
        cur.execute(
            f"SELECT `uuid`, MAX(`datetime`) FROM `{table}` WHERE `uuid` IN ({marks}) GROUP BY `uuid`",
            part,
        )
        out.update({u: t for u, t in cur.fetchall() if t})
    return out


def newest_wide(
    cur, table: str, ts: str, uuids: List[str], since: dt.datetime
) -> Dict[str, dt.datetime]:
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    cols = {r[0] for r in cur.fetchall()}
    present = [u for u in uuids if u in cols]
    out: Dict[str, dt.datetime] = {}
    for i in range(0, len(present), 60):
        part = present[i : i + 60]
        picks = ", ".join(f"MAX(CASE WHEN `{u}` IS NOT NULL THEN `{ts}` END)" for u in part)
        cur.execute(f"SELECT {picks} FROM `{table}` WHERE `{ts}` >= %s", (since,))
        row = cur.fetchone() or ()
        out.update({u: t for u, t in zip(part, row) if t})
    missing = [u for u in present if u not in out]
    for i in range(0, len(missing), 60):  # older than the recent window: one full scan per chunk
        part = missing[i : i + 60]
        picks = ", ".join(f"MAX(CASE WHEN `{u}` IS NOT NULL THEN `{ts}` END)" for u in part)
        cur.execute(f"SELECT {picks} FROM `{table}`")
        row = cur.fetchone() or ()
        out.update({u: t for u, t in zip(part, row) if t})
    return out


def largest_gap_h(cur, table: str, uuid: str, since: dt.datetime) -> float:
    cur.execute(
        f"SELECT MAX(TIMESTAMPDIFF(SECOND, prev, `datetime`)) FROM (SELECT `datetime`, "
        f"LAG(`datetime`) OVER (ORDER BY `datetime`) AS prev FROM `{table}` WHERE `uuid`=%s AND `datetime`>=%s) x",
        (uuid, since),
    )
    v = (cur.fetchone() or [None])[0]
    return round((v or 0) / 3600, 2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default="bldg")
    ap.add_argument(
        "--fresh-min",
        type=float,
        default=15.0,
        help="a point is fresh if its newest row is this recent",
    )
    ap.add_argument(
        "--gaps", action="store_true", help="largest gap per narrow series over the last 7 days"
    )
    ap.add_argument("--out", default=str(REPO / "outputs" / "data_freshness_audit.csv"))
    args = ap.parse_args()

    now = dt.datetime.utcnow()
    points = graph_points(args.repo)
    reg = registry()
    by_store: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for p, u, s in points:
        by_store[s].append((p, u))

    conn = connect()
    cur = conn.cursor()
    rows_out = []
    summary = []
    for store, pts in sorted(by_store.items()):
        spec = reg.get(store, {})
        kind = spec.get("type", "?")
        uuids = sorted({u for _, u in pts})
        newest: Dict[str, dt.datetime] = {}
        table = spec.get("table") or ""
        try:
            if kind == "mysql_narrow" and table:
                newest = newest_narrow(cur, table, uuids)
            elif kind == "mysql" and store.startswith("database"):
                table = env("MYSQL_TABLE", "sensor_data") or "sensor_data"
                newest = newest_wide(cur, table, "Datetime", uuids, now - dt.timedelta(days=2))
            elif kind == "mysql_events":
                table = table or "events"
                cur.execute("SHOW COLUMNS FROM `events`")
                cols = [r[0] for r in cur.fetchall()]
                ucol = next((c for c in ("subject_uuid", "uuid") if c in cols), None)
                tcol = next(
                    (c for c in ("start_dt", "datetime", "event_time", "ts") if c in cols), None
                )
                if ucol and tcol:
                    for i in range(0, len(uuids), 200):
                        part = uuids[i : i + 200]
                        cur.execute(
                            f"SELECT `{ucol}`, MAX(`{tcol}`) FROM `events` WHERE `{ucol}` IN ({','.join(['%s'] * len(part))}) GROUP BY `{ucol}`",
                            part,
                        )
                        newest.update({u: t for u, t in cur.fetchall() if t})
        except Exception as exc:  # one unreadable store must not hide the others
            print(f"[warn] {store}: {type(exc).__name__}: {str(exc)[:160]}")
        ages = {
            u: (now - t).total_seconds() / 60
            for u, t in newest.items()
            if isinstance(t, dt.datetime)
        }
        fresh = sum(1 for a in ages.values() if a <= args.fresh_min)
        day = sum(1 for a in ages.values() if a <= 1440)
        oldest = max(ages.values()) if ages else None
        summary.append((store, kind, table, len(uuids), len(newest), fresh, day, oldest))
        for p, u in pts:
            t = newest.get(u)
            gap = ""
            if args.gaps and kind == "mysql_narrow" and table and t:
                gap = largest_gap_h(cur, table, u, now - dt.timedelta(days=7))
            rows_out.append(
                [
                    store,
                    table,
                    local(p),
                    u,
                    t.isoformat() if t else "",
                    round(ages[u], 1) if u in ages else "",
                    gap,
                ]
            )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["store", "table", "point", "uuid", "newest_utc", "age_min", "largest_gap_7d_h"])
        w.writerows(rows_out)

    print(
        f"now (UTC) {now:%Y-%m-%d %H:%M}; fresh = newest row within {args.fresh_min:g} min; {len(points)} graph point-series"
    )
    print(
        f"{'store':22s} {'type':13s} {'points':>6s} {'any row':>7s} {'fresh':>6s} {'<24h':>6s} {'oldest newest (h)':>17s}"
    )
    tot = [0, 0, 0, 0]
    for store, kind, table, n, anyr, fresh, day, oldest in summary:
        tot = [tot[0] + n, tot[1] + anyr, tot[2] + fresh, tot[3] + day]
        o = f"{oldest / 60:.1f}" if oldest is not None else "-"
        print(f"{store:22s} {kind:13s} {n:6d} {anyr:7d} {fresh:6d} {day:6d} {o:>17s}")
    print(f"{'TOTAL':22s} {'':13s} {tot[0]:6d} {tot[1]:7d} {tot[2]:6d} {tot[3]:6d}")
    print(f"[detail] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
