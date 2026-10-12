#!/usr/bin/env python3
"""Bring GENERATED occupancy history written before the occupancy model into line with it.

BUG-1544 (2026-10-10). The occupancy model (BUG-1506, scripts/derive_occupancy_model.py) went live
at a known moment; every room count written before it was drawn in a 0-30 band, so "this week" an
academic office "peaked at 30 people" and the floor counters had nothing to do with the rooms under
them. This rewrites the development history in a window the caller names:

  * each modelled room count is RESCALED by (its ceiling / the band it was drawn in), which keeps
    the diurnal shape and lands it inside the ceiling;
  * each floor counter becomes the SUM of its rooms' as-of values at each of its own timestamps.

Presence flags are left as they were. Generated development data only: it never touches a point the
model does not shape, and the window must be named explicitly. Every row it changes is written to a
gzip CSV first, so the change can be undone.

    python scripts/rescale_occupancy_history.py --since "2026-10-03 00:00:00" --until "2026-10-10 09:52:09"
    python scripts/rescale_occupancy_history.py ... --apply
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from derive_occupancy_model import BASIS  # noqa: E402


def _env() -> Dict[str, str]:
    out = {}
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", default=str(REPO / "input" / "bldg1_narrow_publish_map.json"))
    ap.add_argument(
        "--before-map", required=True, help="the map as it was BEFORE the model (old bands)"
    )
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True, help="when the model went live (UTC)")
    ap.add_argument("--table", default="occupancy_data")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import pymysql

    now_map = json.loads(Path(args.map).read_text(encoding="utf-8"))
    old_map = json.loads(Path(args.before_map).read_text(encoding="utf-8"))
    rooms = {
        u: (float(e["hi"]), float((old_map.get(u) or {}).get("hi") or 0))
        for u, e in now_map.items()
        if e.get("hi_basis") == BASIS and e.get("table") == args.table
    }
    rooms = {u: (c, old) for u, (c, old) in rooms.items() if old > c > 0}
    floors = {
        u: list((e.get("derive") or {}).get("of") or [])
        for u, e in now_map.items()
        if (e.get("derive") or {}).get("op") == "sum" and e.get("table") == args.table
    }
    print(f"rooms to rescale: {len(rooms)}; floor counters to recompute: {len(floors)}")
    env = _env()
    conn = pymysql.connect(
        host="127.0.0.1",
        port=int(env.get("MYSQL_PORT", "3306") or 3306),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env.get("MYSQL_DATABASE", "sensordb"),
        init_command="SET time_zone='+00:00'",
        autocommit=False,
    )
    window = (args.since, args.until)
    table = args.table
    with conn.cursor() as cur:
        ids = list(rooms) + list(floors)
        ph = ",".join(["%s"] * len(ids))
        cur.execute(
            f"SELECT uuid, datetime, value FROM {table} WHERE uuid IN ({ph}) AND datetime >= %s AND datetime < %s",
            (*ids, *window),
        )
        backup_rows = cur.fetchall()
        print(f"rows in the window: {len(backup_rows)}")
        if not args.apply:
            print("--apply not given: nothing changed")
            return 0
        bdir = REPO / "outputs" / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        bpath = bdir / f"occupancy_before_rescale_{datetime.utcnow():%Y%m%dT%H%M%SZ}.csv.gz"
        with gzip.open(bpath, "wt", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["uuid", "datetime", "value"])
            w.writerows((u, d.strftime("%Y-%m-%d %H:%M:%S"), v) for u, d, v in backup_rows)
        print(f"backup: {bpath}")

        for i, (u, (c, old)) in enumerate(rooms.items(), 1):
            cur.execute(
                f"UPDATE {table} SET value = ROUND(value * %s) WHERE uuid=%s AND datetime >= %s AND datetime < %s",
                (c / old, u, *window),
            )
            if i % 50 == 0:
                conn.commit()
                print(f"  rescaled {i}/{len(rooms)} rooms")
        conn.commit()

        for fu, members in floors.items():
            series: Dict[str, Tuple[List[datetime], List[float]]] = {}
            for m in members:
                cur.execute(
                    f"SELECT datetime, value FROM {table} WHERE uuid=%s AND datetime < %s "
                    f"AND datetime >= DATE_SUB(%s, INTERVAL 1 DAY) ORDER BY datetime",
                    (m, args.until, args.since),
                )
                rows = cur.fetchall()
                series[m] = ([r[0] for r in rows], [float(r[1]) for r in rows])
            cur.execute(
                f"SELECT datetime FROM {table} WHERE uuid=%s AND datetime >= %s AND datetime < %s",
                (fu, *window),
            )
            stamps = [r[0] for r in cur.fetchall()]
            updates = []
            for t in stamps:
                total = 0.0
                for ts, vals in series.values():
                    k = bisect.bisect_right(ts, t) - 1
                    if k >= 0:
                        total += vals[k]
                updates.append((round(total), fu, t))
            cur.executemany(f"UPDATE {table} SET value=%s WHERE uuid=%s AND datetime=%s", updates)
            conn.commit()
            print(f"  floor counter {fu[:8]}: {len(updates)} rows = sum of {len(members)} rooms")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
