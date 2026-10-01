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

ONE VALUE MODEL, NOT TWO (BUG-1139)
-----------------------------------
This module used to carry its own ``_shape`` -- a diurnal sine with a small jitter, applied to
every point and then rounded. For a 0/1 flag with a swing of 0.9 the jitter is far too small to
move ``int(round())`` except at the crossing, so the value was 0 whenever the centre sat below
0.5 and 1 whenever it sat above: a perfect square wave, switching at exactly 07:00 and 19:00,
IDENTICAL for all 234 presence flags. Measured in the store over 2026-09-25..28 the hourly mean
of those flags was 0.00 from 20:00 to 05:00 and 1.00 from 08:00 to 17:00, pooled range 1.000 --
while the live days either side sat at 0.45..0.56. The same series therefore answered "was room
X occupied last Friday" from a tidy working day and "is room X occupied now" from a coin.

The live publisher's generator already had the branch this one lacked. Rather than add a second
copy of it here -- two near-identical range and diurnal tables are how the two came to disagree
in the first place -- this module now imports ``sensor_signal`` and calls the SAME function the
publisher calls. A backfilled row and a live row are produced by one model, which is the only
way the two can be kept from drifting apart again.

The rows already written are NOT repaired: they are dev-mode data, the owner has ruled generated
data a deliberate development input, and rewriting history to match a later model destroys the
evidence that the disagreement existed (CAVEAT-1131). What is fixed here is what a FUTURE
backfill writes.

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
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# Run directly as a script, so the repo root is not on sys.path yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.db_clock import UTC_SESSION_INIT

REPO = Path(__file__).resolve().parent.parent

#: The LIVE publisher's generator, imported rather than reimplemented (BUG-1139). This is a
#: hard dependency on purpose: falling back to a local copy of the value model is exactly the
#: arrangement that produced two contradictory models for one series, and a silent fallback
#: would restore it the moment the path moved.
_PUBLISHER_DIR = REPO / "mysql-dummy-publish-dev"
if str(_PUBLISHER_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISHER_DIR))
try:
    import sensor_signal  # noqa: E402
except ImportError as exc:  # pragma: no cover - a moved directory, not a code path
    raise ImportError(
        f"backfill_narrow_gap needs the publisher's value model at {_PUBLISHER_DIR}. "
        f"Re-implementing it here is what BUG-1139 was; fix the path instead. ({exc})"
    ) from exc

#: (low, high, decimals) per value_col — a BAND table, not a value model. Used only for points
#: whose publish-map entry carries no lo/hi of its own; the shape of the series comes from
#: sensor_signal, the same place the live publisher gets it.
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

# A `_DIURNAL` table used to sit here, duplicating `sensor_signal.DIURNAL`. It is gone
# deliberately: the duplication is what let the two writers disagree (BUG-1139). The single
# copy is `sensor_signal.DIURNAL`, and `tests/test_backfill_uses_one_value_model.py` fails if
# a second one reappears in this file.


def _point_range(point: dict) -> tuple:
    """(lo, hi, dec, swing_key) for a point from EITHER publisher map shape.

    The narrow map names a `value_col` this module already has a range for; the extended map
    carries `lo`/`hi`/`dec` typed per Brick class, which is strictly better information. This
    read only the first shape and raised KeyError on the second, so the 628 points in the
    extended stores could not be backfilled at all — and those are 509 of the scanner's
    candidates, the ones a stuck or dropout injection needs contiguous history for.
    """
    col = str(point.get("value_col") or "")
    if "lo" in point and "hi" in point:
        return float(point["lo"]), float(point["hi"]), int(point.get("dec", 2)), col
    lo, hi, dec = _RANGES.get(col, _RANGES["generic"])
    return lo, hi, dec, col


def _value_from(point: dict, when: datetime, step_s: float) -> float:
    """One reading, from the publisher's generator (BUG-1139).

    The per-sensor offset is NOT passed in any more: `sensor_signal` derives a stable one from
    the uuid, which gives every sensor its own phase instead of the seven this module used to
    share out by list position. State is held per uuid inside that module, so a sensor's gap
    must be walked in time order -- which is what `main` does.

    `step_s` is this backfill's interval, which is NOT the modality's live cadence. A binary
    point's hold-and-flip rate is a probability per write, so it has to be told how far apart
    the writes are or the day it draws comes out flattened.
    """
    lo, hi, dec, col = _point_range(point)
    return sensor_signal.next_value(str(point["uuid"]), col, lo, hi, dec, when, step_s=step_s)[0]


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
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )
    # UTC, like every row this writes into and every reader that will window them
    # (BUG-403). datetime.now() on a BST host put the whole backfill an hour ahead.
    now = datetime.utcnow().replace(second=0, microsecond=0)
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
            for p in pts:
                last = newest.get(p["uuid"])
                start = max(last + step, floor) if last else floor
                if start >= gap_end:
                    continue  # no hole for this sensor
                # sensor_signal holds per-uuid state, so start each sensor from a clean slate
                # and walk its gap forward in time. A binary point is a held state, not a
                # function of the timestamp, and out-of-order calls would make it meaningless.
                sensor_signal.reset_state()
                when = start
                while when < gap_end:
                    rows.append((p["uuid"], when, _value_from(p, when, step.total_seconds())))
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
