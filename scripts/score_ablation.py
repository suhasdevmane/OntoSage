# -*- coding: utf-8 -*-
"""Attribute the v1 -> v2 difference: incidental fixes vs the compound architecture.

    python scripts/score_ablation.py --set eval/compound/T-REAL.jsonl \
        --set eval/compound/T-REAL-SUPPLEMENT.jsonl

tasks/V2_COMPOUND_PLAN.md section 5: the ablation arm is the v2 build with
ARBITER_FACETS_ENABLED=false and ARBITER_V2_ROUTING=off, captured on the primary set in the same
session as v2. v1 -> ablated isolates the fixes v2 carries for v1 defects; ablated -> v2 isolates
the compound architecture. Both comparisons use exactly the primary analysis of
scripts/score_blinded.py -- acceptable = {A, B, C} on FULL/PARTIAL items, exact McNemar on the
discordant pairs, paired bootstrap 95% CI with the same seed -- so the three numbers are
comparable.

Reads <set>_sheet.csv + <set>_key.json (v1 and v2 labels) and <set>_ablation_labels.json (the
ablation arm's labels, scored in the same blinded read). Refuses an unfinished sheet.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from scipy.stats import binomtest

REPO = Path(__file__).resolve().parent.parent
ACCEPTABLE = {"A", "B", "C"}
ARMS = ("v1", "v2-ablation", "v2")


def _compare(a: List[bool], b: List[bool]) -> Tuple[str, float]:
    n = len(a)
    a_only = sum(1 for x, y in zip(a, b) if x and not y)
    b_only = sum(1 for x, y in zip(a, b) if y and not x)
    p = binomtest(min(a_only, b_only), a_only + b_only, 0.5).pvalue if (a_only + b_only) else 1.0
    rng = random.Random(20261007)
    diffs = []
    for _ in range(10000):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(b[k] for k in idx) / n - sum(a[k] for k in idx) / n)
    diffs.sort()
    ra, rb = sum(a) / n, sum(b) / n
    return (
        f"{ra:.1%} -> {rb:.1%}, difference {rb - ra:+.1%} (95% CI {diffs[249]:+.1%} to "
        f"{diffs[9749]:+.1%}); discordant: lost {a_only}, gained {b_only}; exact McNemar p = {p:.4f}",
        p,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True, action="append")
    args = ap.parse_args()

    sdir = REPO / "eval" / "compound" / "scoring"
    labels: Dict[str, Dict[str, str]] = {}
    meta: Dict[str, str] = {}
    for one in (Path(s).stem for s in args.set):
        key = json.loads((sdir / f"{one}_key.json").read_text(encoding="utf-8"))
        abl = json.loads((sdir / f"{one}_ablation_labels.json").read_text(encoding="utf-8"))
        with (sdir / f"{one}_sheet.csv").open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                i = row["id"]
                got = {key[i][s]: (row.get(f"label_{s}") or "").strip().upper()[:1] for s in "XY"}
                got["v2-ablation"] = (abl.get(i, {}).get("label") or "").strip().upper()[:1]
                bad = [arm for arm in ARMS if got.get(arm, "") not in list("ABCDEF")]
                if bad:
                    print(f"{one}/{i}: no valid label for {bad} -- finish the read first")
                    return 2
                labels[i] = got
                meta[i] = row.get("answerability", "")

    answerable = [i for i in labels if meta[i] in ("FULL", "PARTIAL")]
    acc = {arm: [labels[i][arm] in ACCEPTABLE for i in answerable] for arm in ARMS}
    lines = [f"# Ablation attribution — {' + '.join(Path(s).stem for s in args.set)}", ""]
    for arm in ARMS:
        c = Counter(labels[i][arm] for i in labels)
        lines.append(f"- **{arm}** labels: " + ", ".join(f"{k}={c.get(k, 0)}" for k in "ABCDEF"))
    lines += ["", f"Acceptable rate on answerable items (n = {len(answerable)}):", ""]
    for a, b, what in (
        ("v1", "v2-ablation", "incidental fixes (v1 -> v2 with the architecture switched off)"),
        ("v2-ablation", "v2", "the compound architecture (same build, flags on vs off)"),
        ("v1", "v2", "total (the pre-registered primary comparison)"),
    ):
        text, _ = _compare(acc[a], acc[b])
        lines.append(f"- **{what}:** {text}")
    out = sdir / ("+".join(Path(s).stem for s in args.set) + "_ablation_results.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
