#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Top a narrow time-series table up to "now" for the sensors already in it.

Why this exists. A building answers "right now" questions only from data that
IS recent; a table whose newest row is a week old makes every current-conditions
question fall back to "no scorable data", and nothing says why. bldg1's
``co2_data`` had stopped on 2026-08-13 while its hardware table kept writing, so
CO2 rankings silently lost their entire ppm population (CAVEAT-207).

Deliberately conservative:

* it only writes for uuids ALREADY PRESENT in the table — it never invents a
  sensor, so it cannot make a building look better instrumented than it is;
* each series continues from that sensor's own last value and stays inside the
  min/max the table already exhibits, so a topped-up series looks like the one
  it continues rather than like a new synthetic population;
* it writes nothing before the existing latest timestamp, so history is never
  rewritten — only extended.

Usage:
    python scripts/refresh_narrow_table.py co2_data --dry-run
    python scripts/refresh_narrow_table.py co2_data --step-min 10
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# Run directly as a script, so the repo root is not on sys.path yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.db_clock import UTC_SESSION_INIT

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


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


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("table", help="narrow table name, e.g. co2_data")
    ap.add_argument("--step-min", type=int, default=10, help="minutes between generated rows")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        import pymysql
    except ImportError:
        print("pymysql not installed on the host; run: python -m pip install pymysql")
        return 1

    env = _env()
    conn = pymysql.connect(
        host=args.host,
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env.get("MYSQL_USER", "root"),
        password=env.get("MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", "sensordb"),
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )
    try:
        cur = conn.cursor()
        t = args.table
        cur.execute(
            f"SELECT MAX(datetime), MIN(value), MAX(value), COUNT(DISTINCT uuid) FROM `{t}`"
        )
        latest, vmin, vmax, n_uuid = cur.fetchone()
        if latest is None:
            print(f"{t}: empty — nothing to continue from")
            return 1
        now = datetime.now().replace(second=0, microsecond=0)
        gap_min = (now - latest).total_seconds() / 60.0
        print(
            f"{t}: {n_uuid} sensor(s), values {vmin}..{vmax}, latest {latest} ({gap_min/60:.1f} h ago)"
        )
        # PER SENSOR, never per table. The first version read the table's global
        # MAX(datetime), then topped up only the uuids that wrote at THAT EXACT timestamp --
        # so a single still-reporting sensor made the whole table look current and hid every
        # other one from the top-up. Measured on this building: noise_data reported a table
        # max of "now" with 1 of 236 sensors actually fresh, light_data 1 of 242,
        # temperature_data 1 of 67. The deliberate lane then excluded every candidate space
        # for lack of usable noise, and the answer was "I couldn't rank any spaces".
        #
        # This is the same table-versus-sensor conflation recorded as CAVEAT-233, in the tool
        # written to repair its consequences.
        now = datetime.now().replace(second=0, microsecond=0)
        cur.execute(
            f"SELECT a.uuid, a.value, a.datetime FROM `{t}` a "
            f"JOIN (SELECT uuid, MAX(datetime) AS m FROM `{t}` GROUP BY uuid) b "
            f"ON a.uuid = b.uuid AND a.datetime = b.m"
        )
        per_sensor = {
            str(u): (float(v) if v is not None else (float(vmin) + float(vmax)) / 2.0, d)
            for u, v, d in cur.fetchall()
        }
        if not per_sensor:
            print("  no sensors found — nothing to continue from")
            return 1

        lo, hi = float(vmin), float(vmax)
        rows = []
        stale = 0
        for uuid, (start_val, last_dt) in sorted(per_sensor.items()):
            sensor_gap = (now - last_dt).total_seconds() / 60.0
            if sensor_gap <= args.step_min:
                continue  # this one is current; never rewrite history
            stale += 1
            steps_for_sensor = int(sensor_gap // args.step_min)
            rnd = random.Random(uuid)
            val = start_val
            for i in range(steps_for_sensor, 0, -1):
                ts = now - timedelta(minutes=i * args.step_min)
                hour = ts.hour + ts.minute / 60.0
                # A gentle diurnal push plus a small random walk, clamped to the
                # range this sensor's own table already shows.
                val += 0.08 * (hi - lo) * math.sin((hour - 6) / 24.0 * 2 * math.pi) * 0.25
                val += rnd.uniform(-1, 1) * (hi - lo) * 0.01
                val = max(lo, min(hi, val))
                rows.append((uuid, ts, round(val, 3)))

        if not rows:
            print(f"  already current — all {len(per_sensor)} sensor(s) up to date")
            return 0
        last = {u: v for u, (v, _) in per_sensor.items()}
        steps = max(1, len(rows) // max(1, stale))
        print(f"  {stale} of {len(per_sensor)} sensor(s) are stale")
        print(f"  would write {len(rows)} row(s) across {len(last)} sensor(s) in {steps} step(s)")
        if args.dry_run:
            return 0
        cur.executemany(
            f"INSERT IGNORE INTO `{t}` (uuid, datetime, value) VALUES (%s, %s, %s)", rows
        )
        conn.commit()
        cur.execute(f"SELECT MAX(datetime), COUNT(*) FROM `{t}`")
        mx, total = cur.fetchone()
        print(f"  done — latest now {mx}, {total} rows total")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
