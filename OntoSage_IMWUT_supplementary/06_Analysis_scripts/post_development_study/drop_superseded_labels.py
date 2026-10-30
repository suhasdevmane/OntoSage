#!/usr/bin/env python3
"""Move labels whose answer is no longer scored out of labels/rq2/_ai_parts/ (TODO 5.1).

    python drop_superseded_labels.py comparison [stability ...]

A provider or harness failure is re-run once and the re-run replaces it on the blind sheet (make_blind_sheet.py), so
the failed attempt's blind id leaves the sheet. Its label, made before the re-run existed, is moved (not deleted) to
labels/rq2/_superseded_<set>.csv with the reason, and the part files are rewritten without it. Run after
make_blind_sheet.py and before merge_rq2_labels.py.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS  # noqa: E402

RQ2 = LABELS / "rq2"


def run(name: str) -> int:
    on_sheet = {r["blind_id"] for r in csv.DictReader((RQ2 / f"blind_sheet_{name}.csv").open(encoding="utf-8"))}
    moved = []
    for p in sorted((RQ2 / "_ai_parts").glob(f"{name}_*.csv")):
        with p.open(encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            fields, rows = rd.fieldnames, list(rd)
        keep = [r for r in rows if r["blind_id"].strip() in on_sheet]
        gone = [r for r in rows if r["blind_id"].strip() not in on_sheet]
        if gone:
            with p.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
                w.writeheader()
                w.writerows(keep)
            moved += [{**r, "from_file": p.name, "reason": "attempt replaced by its re-run on the blind sheet"} for r in gone]
    if moved:
        out = RQ2 / f"_superseded_{name}.csv"
        new = not out.exists()
        with out.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(moved[0].keys()), lineterminator="\n")
            if new:
                w.writeheader()
            w.writerows(moved)
    print(f"{name}: {len(moved)} labels moved to _superseded_{name}.csv: {[m['blind_id'] for m in moved]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(max(run(n) for n in sys.argv[1:]))
