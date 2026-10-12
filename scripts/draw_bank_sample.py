#!/usr/bin/env python3
"""Draw a seeded, stratified sample from the 4,060-question stakeholder bank for a hand read.

The bank is a DEVELOPMENT set (docs/smart_building_questions.csv: 37-role catalogue + v5 synthetic
bank). A sample from it measures the system on questions it was not tuned on in this session; it
is not evidence about unseen survey questions. The gate's own 51 questions are excluded, as is any
question listed in --exclude files (JSONL with a "question" field), so a re-draw can stay fresh.

    python scripts/draw_bank_sample.py --seed 20261010 --catalogue 26 --synthetic 14 \
        --out outputs/qa_readiness/bank_sample_v1.jsonl
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import random
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def gate_questions() -> set:
    out = set()
    for f in sorted(
        glob.glob(str(REPO / "scripts" / "outputs" / "regression_answerability_*.json"))
    )[-1:]:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        out |= {r["question"].strip() for r in d.get("results", [])}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=20261010)
    ap.add_argument("--catalogue", type=int, default=26)
    ap.add_argument("--synthetic", type=int, default=14)
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument(
        "--out", default=str(REPO / "outputs" / "qa_readiness" / "bank_sample_v1.jsonl")
    )
    args = ap.parse_args()

    rows = list(
        csv.DictReader(open(REPO / "docs" / "smart_building_questions.csv", encoding="utf-8-sig"))
    )
    skip = gate_questions()
    for f in args.exclude:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                skip.add(json.loads(line)["question"].strip())
    rows = [r for r in rows if r["Question"].strip() and r["Question"].strip() not in skip]
    rng = random.Random(args.seed)

    by_role = defaultdict(list)
    for r in rows:
        if r["Source"] == "stakeholder_catalogue_37":
            by_role[r["Stakeholder_Role"] or "(none)"].append(r)
    roles = sorted(by_role)
    rng.shuffle(roles)
    picked = [
        rng.choice(sorted(by_role[role], key=lambda r: r["ID"])) for role in roles[: args.catalogue]
    ]

    # The synthetic bank carries roles but no complexity level, so it is stratified by role too.
    by_role_v5 = defaultdict(list)
    for r in rows:
        if r["Source"] == "v5_synthetic_bank":
            by_role_v5[r["Stakeholder_Role"] or "(none)"].append(r)
    roles_v5 = sorted(by_role_v5)
    rng.shuffle(roles_v5)
    for role in roles_v5[: args.synthetic]:
        picked.append(rng.choice(sorted(by_role_v5[role], key=lambda r: r["ID"])))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in picked:
            fh.write(
                json.dumps(
                    {
                        "qid": r["ID"],
                        "question": r["Question"].strip(),
                        "role": r["Stakeholder_Role"],
                        "level": r["Complexity_L"],
                        "source": r["Source"],
                        "category": r["Category"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"{len(picked)} questions -> {out} (seed {args.seed}; {len(skip)} excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
