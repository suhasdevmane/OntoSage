#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill the hole between a narrow table's last real row and now (BUG-390).

WHY THERE IS A HOLE
-------------------
bldg1's narrow tables hold months of history and then stop: noise_data runs from 2026-06-02
to 2026-08-25, temperature_data from 2026-07-08 to 2026-08-26, and nothing was written until
the publisher was widened on 2026-09-02. The publisher now tops up all 1,528 registered
points every 30 seconds, but that leaves an eight-day gap in the middle.

The gap is not cosmetic. Anything that asks for a window ending "now" and needs history to
compare against lands in it: the anomaly grader skipped five of its eight injections with
"no sensor with enough rows", because a stuck-value or drift injection needs rows in the
window it is perturbing. A detector cannot find a fault in data that is not there, and an
injection that touched nothing is not ground truth.

WHAT THIS WRITES
----------------
One row per sensor per interval across the gap only — never before a sensor's existing
newest row, and never after now. Existing rows are left alone: this closes a hole, it does
not rewrite history.

Values follow a daily cycle rather than being flat noise, because the things that read this
data look for shape. A drift detector comparing a sensor against its peers, or a residual
detector fitting a daily profile, learns nothing from uniform random numbers and would report
whatever it found as an anomaly.

DEV-MODE ONLY. Generated readings for a development stack, so questions about the recent past
are answerable while the real feed is absent. The synthetic points are already marked
``ontosage:isSimulated true`` in the ontology and the evidence record carries that into the
answer. Before production the publisher is switched off and the registry repointed.

    python scripts/backfill_narrow_gap.py --dry-run
    python scripts/backfill_narrow_gap.py --interval-min 15
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent

#: (low, high, decimals) per value_col — the same ranges the live publisher uses, so a
#: backfilled row is indistinguishable in kind from one written a minute ago.
_RANGES = {
    "kwh": (1.0, 6.0, 2),
    "occupancy": (0, 30, 0),
    "flow_lpm": (0.0, 2.0, 3),
    "noise_db": (30.0, 70.0, 1),
    "pm25": (5.0, 35.0, 1),
    "voc": (50.0, 350.0, 0),
    "lux": (0.0, 600.0, 0),
    "vib_mm_s": (0.1, 1.2, 2),
    "runtime_h": (0.0, 1.0, 3),
    "temp_c": (18.0, 26.0, 1),
    "rh_pct": (30.0, 65.0, 1),
    "co2_ppm": (400, 1200, 0),
    "contact": (0, 1, 0),
    "generic": (0.0, 100.0, 2),
}

#: How strongly each modality follows the working day. 0 = flat, 1 = full swing across the
#: range. Occupancy and CO2 track people; temperature drifts mildly; a door contact does not
#: follow a sine wave at all and is left to its own coin-flip.
_DIURNAL = {
    "occupancy": 0.9,
    "co2_ppm": 0.7,
    "lux": 0.8,
    "noise_db": 0.5,
    "kwh": 0.5,
    "voc": 0.4,
    "temp_c": 0.3,
    "rh_pct": 0.3,
    "contact": 0.0,
}


def _value(value_col: str, when: datetime, phase: float) -> float:
    lo, hi, dec = _RANGES.get(value_col, _RANGES["generic"])
    swing = _DIURNAL.get(value_col, 0.2)
    # Daytime peak around 13:00, trough overnight.
    hours = when.hour + when.minute / 60.0
    cycle = (math.sin((hours - 7.0) / 24.0 * 2 * math.pi) + 1) / 2  # 0..1
    centre = lo + (hi - lo) * (0.5 * (1 - swing) + swing * cycle)
    jitter = (hi - lo) * 0.06
    val = random.uniform(centre - jitter, centre + jitter)  # nosec B311 - dev data only
    val = max(lo, min(hi, val + phase * jitter))
    return int(round(val)) if dec == 0 else round(val, dec)


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", default=str(REPO / "input" / "bldg1_narrow_publish_map.json"))
    ap.add_argument("--interval-min", type=int, default=15)
    ap.add_argument("--max-days", type=int, default=30, help="never backfill further than this")
    ap.add_argument(
        "--live-since-hours",
        type=float,
        default=2.0,
        help="when the live publisher took over. The gap ENDS here, it does not end at now: "
        "the publisher is already writing, so a sensor's newest row is seconds old and "
        "filling forward from it writes nothing. The hole sits between the last historical "
        "row and the moment the publisher was widened.",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    import pymysql

    entries = json.loads(Path(args.map).read_text(encoding="utf-8"))
    points = list(entries.values() if isinstance(entries, dict) else entries)
    by_table: Dict[str, List[dict]] = {}
    for p in points:
        by_table.setdefault(p["table"], []).append(p)

    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DB"],
    )
    now = datetime.now().replace(second=0, microsecond=0)
    step = timedelta(minutes=max(1, args.interval_min))
    # The gap ENDS where the live publisher took over, not at `now`.
    gap_end = now - timedelta(hours=args.live_since_hours)
    floor = gap_end - timedelta(days=args.max_days)
    total = 0

    with conn.cursor() as cur:
        for table, pts in sorted(by_table.items()):
            uuids = [p["uuid"] for p in pts]
            placeholders = ", ".join(["%s"] * len(uuids))
            # The gap is judged PER SENSOR, not per table: one live writer keeps a table's
            # MAX(datetime) at today while every other sensor in it is a week behind, which
            # is exactly the trap that made the store-level freshness check useless.
            cur.execute(
                f"SELECT `uuid`, MAX(`datetime`) FROM `{table}` "
                f"WHERE `uuid` IN ({placeholders}) AND `datetime` < %s GROUP BY `uuid`",
                uuids + [gap_end],
            )
            newest = {str(u): t for u, t in cur.fetchall()}

            rows = []
            for i, p in enumerate(pts):
                last = newest.get(p["uuid"])
                start = max(last + step, floor) if last else floor
                if start >= gap_end:
                    continue  # no hole for this sensor
                phase = (i % 7) / 7.0 - 0.5  # a stable per-sensor offset, so peers differ
                when = start
                while when < gap_end:
                    rows.append((p["uuid"], when, _value(p["value_col"], when, phase)))
                    when += step

            if not rows:
                print(f"  {table:20} already current")
                continue
            print(f"  {table:20} {len(rows):>8} row(s) across {len(pts)} sensor(s)")
            total += len(rows)
            if args.dry_run:
                continue
            for chunk in range(0, len(rows), 5000):
                cur.executemany(
                    f"INSERT INTO `{table}` (`uuid`, `datetime`, `value`) VALUES (%s, %s, %s) "
                    f"ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
                    rows[chunk : chunk + 5000],
                )
                conn.commit()

    print(f"\n{'would write' if args.dry_run else 'wrote'} {total} row(s)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
