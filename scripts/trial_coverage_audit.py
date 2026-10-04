#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""I3 (QA-trial plan, 2026-10-04): derive the open set instead of maintaining one.

Every hand-maintained status list in this repository has gone stale within days,
several provably so -- CAVEAT-844 claimed a feed was absent after it had been added;
TODO-789 was a freeze that had expired eleven days earlier and still read as a live
prohibition. A derived list can only ever disagree with the trackers by being
re-run; a written one can disagree silently for weeks.

This prints, from the trackers themselves, every run:

  * every tasks/TRIAL_TRACKER.csv row whose Status is not DONE, grouped by status
  * of those, which ones carry a non-empty Owner_decision (blocked on a choice only
    the owner can make, not on more engineering)
  * every tasks/FIX_TRACKER.csv row whose Status is OPEN and whose ID is not
    mentioned anywhere in TRIAL_TRACKER.csv's own text -- a weak but real proxy for
    "no plan row claims this bug", since this project's own convention is to cite a
    BUG-/CAVEAT-/TODO- id by name wherever a row addresses it

Exit 0 always -- this is a report, not a gate. Building-agnostic: reads two CSV
paths and nothing else.

Usage:
    python scripts/trial_coverage_audit.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
TRIAL_TRACKER = REPO / "tasks" / "TRIAL_TRACKER.csv"
FIX_TRACKER = REPO / "tasks" / "FIX_TRACKER.csv"

_ID_RE = re.compile(r"\b(?:BUG|CAVEAT|TODO)-\d+\b")


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    trial_rows = _read_csv(TRIAL_TRACKER)
    fix_rows = _read_csv(FIX_TRACKER)

    open_trial = [r for r in trial_rows if r["Status"] != "DONE"]
    by_status: Dict[str, List[Dict[str, str]]] = {}
    for r in open_trial:
        by_status.setdefault(r["Status"], []).append(r)

    print(f"TRIAL_TRACKER.csv: {len(trial_rows)} rows, {len(open_trial)} not DONE.\n")
    for status in sorted(by_status):
        rows = by_status[status]
        print(f"  {status} ({len(rows)}):")
        for r in rows:
            print(f"    {r['ID']:4s} {r['Title'][:90]}")
    print()

    owner_blocked = [r for r in open_trial if (r.get("Owner_decision") or "").strip()]
    print(f"Blocked on an owner decision ({len(owner_blocked)}):")
    for r in owner_blocked:
        print(f"    {r['ID']:4s} [{r['Owner_decision']}] {r['Title'][:80]}")
    print()

    trial_text = " ".join(" ".join(str(v) for v in r.values()) for r in trial_rows)
    mentioned_ids = set(_ID_RE.findall(trial_text))
    open_fix = [r for r in fix_rows if r["Status"] == "OPEN"]
    unclaimed = [r for r in open_fix if r["ID"] not in mentioned_ids]
    print(
        f"FIX_TRACKER.csv: {len(fix_rows)} rows, {len(open_fix)} OPEN, "
        f"{len(unclaimed)} not mentioned anywhere in TRIAL_TRACKER.csv:"
    )
    for r in unclaimed:
        print(f"    {r['ID']:12s} [{r.get('Severity', '?')}] {r['Title'][:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
