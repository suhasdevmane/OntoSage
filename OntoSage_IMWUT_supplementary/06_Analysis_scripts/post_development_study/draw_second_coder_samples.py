#!/usr/bin/env python3
"""Draw the second coder's seeded samples, as fixed in Agreement_and_Adjudication_Procedure.md (TODO 3.4).

    python draw_second_coder_samples.py            # run ONCE, after the author's own labels are complete

Writes G_Study_Data/labels/second_coder/:
  pass1_ids.csv     30 task answers participants saw, stratified by situation (proportional, largest remainder)
  pass2_ids.csv     50 offline questions with BOTH systems' answers (100 blind ids), stratified by question set,
                    plus 30 of the A-minus answers (blind ids only: the coder never sees which system wrote what)
  qual_ids.csv      20% of the per-task reasons (36), stratified by situation
  rq1_ids.csv       60 items of the RQ1 sheet (participants' own questions mixed with corpus questions), stratified
                    by source (Part A codebook, procedure step 3); the coder sees only the item ids and texts
  README.md         the seed, the counts and when this was run
Seed 20261009 (the project's pre-declared seed). Refuses to overwrite an existing draw.
"""

from __future__ import annotations

import csv
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study_paths import LABELS, SEED  # noqa: E402

OUT = LABELS / "second_coder"


def stratified(ids_by: dict, total: int, tag: str) -> list:
    """Proportional allocation with the largest remainder, then a seeded draw inside each stratum."""
    n = sum(len(v) for v in ids_by.values())
    quota = {k: total * len(v) / n for k, v in ids_by.items()}
    alloc = {k: int(q) for k, q in quota.items()}
    for k in sorted(quota, key=lambda k: quota[k] - alloc[k], reverse=True)[: total - sum(alloc.values())]:
        alloc[k] += 1
    picked = []
    for k in sorted(ids_by):
        rng = random.Random(f"{SEED}:{tag}:{k}")
        picked += sorted(rng.sample(sorted(ids_by[k]), alloc[k]))
    return picked


def read(p: Path) -> list:
    with p.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(p: Path, header: list, rows: list) -> None:
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main() -> int:
    if (OUT / "README.md").exists():
        print(f"already drawn ({OUT / 'README.md'}); delete the folder only if the procedure allows a re-draw")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = [r for r in read(LABELS / "labelling_sheet_pass1.csv") if r["role"] == "task"]
    by = defaultdict(list)
    for r in sheet:
        by[r["situation"]].append(r["answer_id"])
    p1 = stratified(by, 30, "pass1")
    write(OUT / "pass1_ids.csv", ["answer_id"], [[i] for i in p1])
    key = read(LABELS / "rq2" / "_unblinding_key_comparison.csv")
    sheet2 = {r["blind_id"] for r in read(LABELS / "rq2" / "blind_sheet_comparison.csv")}
    key = [k for k in key if k["blind_id"] in sheet2]
    sys_of = defaultdict(dict)
    for k in key:
        sys_of[k["qid"]][k["system"]] = k["blind_id"]
    both = defaultdict(list)
    for q, d in sys_of.items():
        if "A" in d and "B" in d:
            both[next(k["set"] for k in key if k["qid"] == q)].append(q)
    qs = stratified(both, 50, "pass2")
    p2 = [(sys_of[q]["A"], "pair") for q in qs] + [(sys_of[q]["B"], "pair") for q in qs]
    am = sorted(d["A-minus"] for d in sys_of.values() if "A-minus" in d)
    if am:
        rng = random.Random(f"{SEED}:pass2:A-minus")
        p2 += [(b, "A-minus sample") for b in sorted(rng.sample(am, min(30, len(am))))]
    random.Random(f"{SEED}:pass2:order").shuffle(p2)     # mixed order, so the coder cannot tell pairs from A-minus
    write(OUT / "pass2_ids.csv", ["blind_id"], [[b] for b, _ in p2])
    write(OUT / "_pass2_sample_kind_KEEP_CLOSED.csv", ["blind_id", "kind"], p2)
    q = [r for r in read(LABELS / "qual" / "qual_coding_sheet.csv") if r["unit"] == "task_reason"]
    byq = defaultdict(list)
    for r in q:
        byq[r["situation"]].append(r["unit_id"])
    pq = stratified(byq, round(0.2 * len(q)), "qual")
    write(OUT / "qual_ids.csv", ["unit_id"], [[i] for i in pq])
    r1 = []
    rq1_key = LABELS / "rq1" / "_source_key_KEEP_CLOSED.csv"
    if rq1_key.exists():
        byr = defaultdict(list)
        for k in read(rq1_key):
            byr[k["source"]].append(k["item_id"])
        r1 = stratified(byr, 60, "rq1")
        random.Random(f"{SEED}:rq1:order").shuffle(r1)     # mixed order: the coder cannot tell the sources apart
        write(OUT / "rq1_ids.csv", ["item_id"], [[i] for i in r1])
    (OUT / "README.md").write_text(
        f"# Second-coder samples\n\nDrawn {time.strftime('%Y-%m-%d %H:%M')} with seed {SEED} by "
        f"draw_second_coder_samples.py (Agreement_and_Adjudication_Procedure.md).\n\n"
        f"- pass 1: {len(p1)} task answers, stratified by situation\n"
        f"- pass 2: {2 * len(qs)} answers to {len(qs)} questions (both systems) + {len(p2) - 2 * len(qs)} A-minus answers, "
        f"in one mixed order (`_pass2_sample_kind_KEEP_CLOSED.csv` says which is which; do not show it to the coder)\n"
        f"- reasons: {len(pq)} of {len(q)} per-task reasons (20%), stratified by situation\n"
        f"- RQ1: {len(r1)} items of the own-questions-and-corpus sheet, stratified by source, in mixed order\n",
        encoding="utf-8")
    print(f"pass1 {len(p1)}, pass2 {len(p2)}, reasons {len(pq)}, rq1 {len(r1)} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
