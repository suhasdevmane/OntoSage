"""Seeded subsample of ids for second-coder double coding (pass 1 answers, Part C reasons).

Reads one id column from a CSV and writes the sampled ids. Stratifies by an optional column (e.g.
'situation') so each stratum is sampled at the same fraction. Run once per material, after the
author's sheet is complete and BEFORE the second coder sees anything; record the seed.

Usage:
    python draw_double_coding_sample.py --in answer_labels_author.csv --id answer_id --strata situation --fraction 0.3
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--strata", default="")
    ap.add_argument("--fraction", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    groups = defaultdict(list)
    for r in rows:
        groups[r.get(args.strata, "") if args.strata else ""].append(r[args.id])
    rng = random.Random(f"{args.seed}:{Path(args.inp).name}")
    picked = []
    for key in sorted(groups):
        ids = sorted(set(groups[key]))
        picked += rng.sample(ids, math.ceil(len(ids) * args.fraction))
    out = Path(args.out or Path(args.inp).with_name(Path(args.inp).stem + "_double_coding_ids.csv"))
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writerow([args.id])
        w.writerows([[i] for i in sorted(picked)])
    print(f"{len(picked)} of {len(rows)} ids -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
