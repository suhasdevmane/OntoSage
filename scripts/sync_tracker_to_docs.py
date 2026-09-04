#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mirror a live tracker's progress into its tracked twin (CAVEAT-409).

WHY
---
`tasks/` is gitignored by the user's decision, so the only record of V7 progress a clone or a
supervisor ever sees is `docs/V7_TRACKER.csv`. That copy is written by
`build_v7_tracker.py` — and only when the GENERATOR RUNS. The session protocol flips
`status` and `notes` in `tasks/V7_TRACKER.csv` directly, so the tracked copy drifts by
design: measured 2026-09-03, five rows behind, the committed file reporting 16 done against
a real 17 with three in-progress tasks shown as untouched.

Regenerating is the wrong remedy: it rebuilds every column from the TASKS definitions in the
generator and preserves only `status` and `notes`, so any hand-edit elsewhere in the live
file would be silently reverted. This copies exactly the two columns that record progress
and touches nothing else.

    python scripts/sync_tracker_to_docs.py                 # V7 by default
    python scripts/sync_tracker_to_docs.py --check         # non-zero if they disagree
    python scripts/sync_tracker_to_docs.py --live tasks/V6_TRACKER.csv --tracked docs/V6_TRACKER.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent

#: The columns that record progress. Everything else in a tracker is task DEFINITION, which
#: belongs to the generator; copying it here would let a hand-edit in a gitignored file
#: become the committed truth without review.
PROGRESS_COLUMNS = ("status", "notes")

#: Row identity. Both trackers key on the task turn.
KEY = "turn"


def _load(path: Path) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return {row[KEY]: row for row in reader}, list(reader.fieldnames or [])


def sync(live: Path, tracked: Path, check_only: bool = False) -> int:
    if not live.is_file():
        print(f"no live tracker at {live} — nothing to mirror")
        return 0
    if not tracked.is_file():
        raise SystemExit(f"tracked tracker missing: {tracked}")

    live_rows, _ = _load(live)
    tracked_rows, fieldnames = _load(tracked)

    only_live = sorted(set(live_rows) - set(tracked_rows))
    only_tracked = sorted(set(tracked_rows) - set(live_rows))
    if only_live or only_tracked:
        # A task added or removed is a DEFINITION change and belongs to the generator.
        print(
            f"the two trackers hold different tasks — run build_v7_tracker.py, not this.\n"
            f"  only in {live.name}: {only_live}\n  only in {tracked.name}: {only_tracked}"
        )
        return 2

    changed: List[str] = []
    for turn, row in live_rows.items():
        for column in PROGRESS_COLUMNS:
            if column not in row:
                continue
            if (row.get(column) or "").strip() != (tracked_rows[turn].get(column) or "").strip():
                tracked_rows[turn][column] = row.get(column) or ""
                if turn not in changed:
                    changed.append(turn)

    if not changed:
        print(f"{tracked.name} already matches {live.name} on {', '.join(PROGRESS_COLUMNS)}")
        return 0

    if check_only:
        print(
            f"OUT OF DATE: {len(changed)} row(s) differ between {live.name} and "
            f"{tracked.name}: {', '.join(changed)}\n"
            f"Run: python scripts/sync_tracker_to_docs.py"
        )
        return 1

    with tracked.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(tracked_rows[t] for t in tracked_rows)
    print(f"[written] {tracked}  ({len(changed)} row(s) updated: {', '.join(changed)})")
    for turn in changed:
        print(f"  {turn:<10} status={live_rows[turn].get('status','')}")
    return 0


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", default=str(REPO / "tasks" / "V7_TRACKER.csv"))
    ap.add_argument("--tracked", default=str(REPO / "docs" / "V7_TRACKER.csv"))
    ap.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit non-zero without writing",
    )
    args = ap.parse_args(argv)
    return sync(Path(args.live), Path(args.tracked), check_only=args.check)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
