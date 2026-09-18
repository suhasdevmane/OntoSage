#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebase interval energy reads that were generated from a register-sized band (BUG-756).

WHAT WENT WRONG
---------------
`ontosage:ElectricalEnergy` carried a typical band of 0-100 kWh — the range of a CUMULATIVE
meter register, not of one 15-minute INTERVAL read. The floor submeters joined the publish map
at 2026-09-16 18:00 and from that moment were generated inside that band: 30-75 kWh per sample,
where the preceding fortnight of the same meters averaged 3.4 kWh and never exceeded 4.9.

Nothing about the readings was wrong in itself. The damage is that the series changed SCALE
half way through, so every question that spans the break compares two different units of
generation: "compare this week's electricity use with last week" answered "+160.9%", which is
the scale change and nothing else. On a demo where "yesterday" falls inside the break, deleting
the rows is worse than repairing them — it would leave the day empty.

WHAT THIS DOES
--------------
Rescales the affected rows by a single constant per meter, chosen so the post-break mean equals
that meter's own pre-break mean. A constant factor keeps the diurnal shape the generator
produced (night trough, daytime peak) and the relative order of the meters; only the scale
moves, which is the only thing that broke.

It is idempotent in the sense that it only touches rows in the window given, and it refuses to
run when the pre-break history it needs is missing. Run the band fix first
(ontology/measurand_kinds.ttl) and refresh the publish map, or new rows arrive out of band again.

    python scripts/rebase_energy_interval_reads.py                 # report only
    python scripts/rebase_energy_interval_reads.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pymysql  # noqa: E402

from shared.config import settings  # noqa: E402

#: When the meters joined the publish map and the scale changed (UTC, stores are UTC).
BREAK = "2026-09-16 18:00:00"
#: The window used to learn each meter's own scale, ending at the break.
BASELINE_DAYS = 13
TABLE = "energy_data"


def _connect():
    return pymysql.connect(
        host="127.0.0.1",
        port=3306,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        init_command="SET time_zone='+00:00'",
    )


def factors(cur) -> List[Tuple[str, float, float, float, int]]:
    """(uuid, pre-break mean, post-break mean, factor, rows) for each affected meter."""
    cur.execute(
        f"SELECT uuid, AVG(value) FROM {TABLE} "
        f"WHERE datetime < %s AND datetime >= DATE_SUB(%s, INTERVAL %s DAY) GROUP BY uuid",
        (BREAK, BREAK, BASELINE_DAYS),
    )
    before: Dict[str, float] = {u: float(v) for u, v in cur.fetchall() if v is not None}
    cur.execute(
        f"SELECT uuid, AVG(value), COUNT(*) FROM {TABLE} WHERE datetime >= %s GROUP BY uuid",
        (BREAK,),
    )
    rows = []
    for uuid, mean_after, n in cur.fetchall():
        if uuid not in before or not mean_after:
            continue
        rows.append((uuid, before[uuid], float(mean_after), before[uuid] / float(mean_after), n))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the rescaled values")
    args = ap.parse_args()

    conn = _connect()
    try:
        cur = conn.cursor()
        rows = factors(cur)
        if not rows:
            print("nothing to rebase: no meter has history on both sides of the break")
            return 1
        print(f"break at {BREAK} UTC · baseline {BASELINE_DAYS} days before it\n")
        print(f"{'meter':38}{'before':>9}{'after':>9}{'factor':>9}{'rows':>8}")
        for uuid, b, a, f, n in rows:
            print(f"{uuid:38}{b:9.2f}{a:9.2f}{f:9.4f}{n:8d}")
        if not args.apply:
            print("\n--dry run-- pass --apply to write")
            return 0
        written = 0
        for uuid, _b, _a, f, _n in rows:
            cur.execute(
                f"UPDATE {TABLE} SET value = ROUND(value * %s, 2) "
                f"WHERE uuid = %s AND datetime >= %s",
                (f, uuid, BREAK),
            )
            written += cur.rowcount
        conn.commit()
        print(f"\nrebased {written} row(s)")
        cur.execute(
            f"SELECT DATE(datetime), ROUND(AVG(value), 2), COUNT(*) FROM {TABLE} "
            f"WHERE datetime >= DATE_SUB(%s, INTERVAL 3 DAY) GROUP BY DATE(datetime) "
            f"ORDER BY DATE(datetime)",
            (BREAK,),
        )
        print("\nday means after the rebase:")
        for d, mean, n in cur.fetchall():
            print(f"  {d}  mean {mean:6.2f} kWh  ({n} rows)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
