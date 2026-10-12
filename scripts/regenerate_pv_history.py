#!/usr/bin/env python3
"""Re-derive GENERATED PV generation history with the solar shape (BUG-1580).

Until 2026-10-10 the PV arrays' power points were generated like energy meters (never zero, 1.4 kW
at 02:00), because the publish map takes a point's shape from its table. The publisher now gives
every `ontosage:PV_Generation_Power_Sensor` the solar shape (`sensor_signal.solar_fraction`); this
rewrites the development history of those points in a window the caller names, with the SAME
function the live publisher uses, so a stored row and a live row come from one model.

Generated development data only: the points are read from the graph by class, nothing else is
touched, the window must be named, and every row changed is written to a gzip CSV first so the
change can be undone.

    python scripts/regenerate_pv_history.py --since "2026-10-03 00:00:00" --until "2026-10-10 16:00:00"
    python scripts/regenerate_pv_history.py ... --apply
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mysql-dummy-publish-dev"))
import sensor_signal  # noqa: E402

QUERY = """
PREFIX ontosage: <http://ontosage.org/capabilities#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?uuid ?store WHERE {
  ?p a ontosage:PV_Generation_Power_Sensor ;
     ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid ; ref:storedAt ?store .
}
"""


def _env() -> Dict[str, str]:
    out = {}
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--endpoint", default="http://127.0.0.1:7200/repositories/bldg")
    ap.add_argument("--map", default=str(REPO / "input" / "bldg1_narrow_publish_map.json"))
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    r = requests.post(
        args.endpoint,
        data={"query": QUERY},
        headers={"Accept": "application/sparql-results+json"},
        timeout=60,
    )
    r.raise_for_status()
    pts = {b["uuid"]["value"] for b in r.json()["results"]["bindings"]}
    pmap = json.loads(Path(args.map).read_text(encoding="utf-8"))
    by_table: Dict[str, List[str]] = {}
    hi: Dict[str, float] = {}
    dec: Dict[str, int] = {}
    for u in sorted(pts):
        e = pmap.get(u) or {}
        if not e.get("table") or e.get("hi") is None:
            print(f"skip {u}: not in the publish map with a band")
            continue
        by_table.setdefault(e["table"], []).append(u)
        hi[u] = float(e["hi"])
        dec[u] = int(e.get("dec", 2))
    print(f"PV points: {sum(len(v) for v in by_table.values())} in {sorted(by_table)}")

    import pymysql

    env = _env()
    conn = pymysql.connect(
        host="127.0.0.1",
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", "sensordb"),
        init_command="SET time_zone='+00:00'",
        autocommit=False,
    )
    rnd = random.Random(1580)
    with conn.cursor() as cur:
        for table, uuids in by_table.items():
            marks = ",".join(["%s"] * len(uuids))
            cur.execute(
                f"SELECT uuid, datetime, value FROM `{table}` WHERE uuid IN ({marks}) "  # nosec B608
                "AND datetime >= %s AND datetime < %s ORDER BY uuid, datetime",
                (*uuids, args.since, args.until),
            )
            rows = cur.fetchall()
            print(f"{table}: {len(rows)} row(s) in the window")
            if not rows:
                continue
            bdir = REPO / "outputs" / "backups"
            bdir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            bpath = bdir / f"pv_before_regenerate_{table}_{stamp}.csv.gz"
            with gzip.open(bpath, "wt", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["uuid", "datetime", "value"])
                w.writerows((u, d.strftime("%Y-%m-%d %H:%M:%S"), v) for u, d, v in rows)
            print(f"backup: {bpath}")
            updates = []
            for u, d, _v in rows:
                frac = sensor_signal.solar_fraction(d)
                val = 0.0
                if frac > 0:
                    val = max(0.0, min(hi[u], hi[u] * frac * (1.0 + rnd.gauss(0, 0.03))))
                updates.append((round(val, dec[u]), u, d))
            zero = sum(1 for v, _u, _d in updates if v == 0)
            print(f"{table}: {len(updates)} row(s) re-derived, {zero} at night (0 kW)")
            if args.apply:
                cur.executemany(
                    f"UPDATE `{table}` SET value=%s WHERE uuid=%s AND datetime=%s",  # nosec B608
                    updates,
                )
    if args.apply:
        conn.commit()
        print("applied")
    else:
        print("dry run: nothing written (pass --apply)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
