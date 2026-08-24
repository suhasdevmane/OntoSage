#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Update a V6 tracker row, and show what is workable next.

Workflow rule: a task is not done when the code lands, it is done when the tracker row
carries the EVIDENCE. Doing that by hand across 64 tasks invites the drift this project has
been bitten by before, so it gets a command.

    python scripts/v6_task.py --status                 # progress + what is unblocked now
    python scripts/v6_task.py V6-T01 --done "evidence" # close a task
    python scripts/v6_task.py V6-T63 --progress "..."  # mark in_progress with a note
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent
TRACKER = REPO / "tasks" / "V6_TRACKER.csv"
EFFORT = {"S": 1, "M": 2, "L": 4}


def _load() -> List[Dict[str, str]]:
    return list(csv.DictReader(TRACKER.read_text(encoding="utf-8-sig").splitlines()))


def _save(rows: List[Dict[str, str]]) -> None:
    with TRACKER.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _deps(row: Dict[str, str]) -> List[str]:
    return [d.strip() for d in (row.get("depends_on") or "").split(",") if d.strip()]


def show_status(rows: List[Dict[str, str]]) -> None:
    by = {r["turn"]: r for r in rows}
    done = {t for t, r in by.items() if r["status"] in ("done", "skipped")}
    units_all = sum(EFFORT[r["effort"]] for r in rows)
    units_done = sum(EFFORT[r["effort"]] for r in rows if r["status"] in ("done", "skipped"))
    print(
        f"V6: {len(done)}/{len(rows)} tasks  ({units_done}/{units_all} effort units, "
        f"{units_done / units_all * 100:.0f}%)"
    )

    from collections import Counter

    ph: Dict[str, Counter] = {}
    for r in rows:
        ph.setdefault(r["phase"], Counter())[r["status"]] += 1
    for phase in sorted(ph):
        c = ph[phase]
        n_done = c.get("done", 0) + c.get("skipped", 0)
        bar = "#" * n_done + "." * (sum(c.values()) - n_done)
        print(f"  {phase:<22} {n_done}/{sum(c.values()):<3} {bar}")

    ready = [r for r in rows if r["status"] == "todo" and all(d in done for d in _deps(r))]
    print(f"\nWORKABLE NOW ({len(ready)}) - every dependency satisfied:")
    for r in sorted(ready, key=lambda x: (-EFFORT[x["effort"]], x["turn"])):
        print(f"  {r['turn']:<8} [{r['effort']}] {r['title'][:66]}")

    blocked = [r for r in rows if r["status"] == "todo" and r not in ready]
    if blocked:
        print(f"\n({len(blocked)} blocked on dependencies)")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("task", nargs="?", help="e.g. V6-T01")
    ap.add_argument("--done", metavar="EVIDENCE", help="mark done, appending evidence to notes")
    ap.add_argument("--progress", metavar="NOTE", help="mark in_progress with a note")
    ap.add_argument("--status", action="store_true", help="show progress and what is workable")
    args = ap.parse_args(argv)

    rows = _load()
    if args.status or not args.task:
        show_status(rows)
        return 0

    by = {r["turn"]: r for r in rows}
    if args.task not in by:
        print(f"unknown task {args.task}")
        return 1
    row = by[args.task]

    if args.done:
        unmet = [d for d in _deps(row) if by[d]["status"] not in ("done", "skipped")]
        if unmet:
            # A warning rather than a refusal: a task can legitimately land ahead of an
            # unrelated dependency. Silence would be worse than either.
            print(f"WARNING: {args.task} has unmet dependencies {unmet}")
        row["status"] = "done"
        row["notes"] = f"{row['notes']} [DONE {date.today().isoformat()}] {args.done}".strip()
        print(f"{args.task} -> done")
    elif args.progress:
        row["status"] = "in_progress"
        row["notes"] = f"{row['notes']} [{date.today().isoformat()}] {args.progress}".strip()
        print(f"{args.task} -> in_progress")
    else:
        for k in (
            "phase",
            "status",
            "effort",
            "depends_on",
            "objective",
            "why",
            "building_agnostic_how",
            "acceptance_criteria",
            "verify",
            "notes",
        ):
            v = (row.get(k) or "").strip()
            if v:
                print(f"  {k}: {v[:300]}")
        return 0

    _save(rows)
    print()
    show_status(_load())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
