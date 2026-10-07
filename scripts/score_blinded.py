# -*- coding: utf-8 -*-
"""Unblind a completed scoring sheet and compute the pre-registered statistics.

    python scripts/score_blinded.py --set eval/compound/T-REAL.jsonl --a v1 --b v2

Reads <set>_sheet.csv (labels filled by the reader) and <set>_key.json, and writes
<set>_results.md. The analysis is fixed in tasks/V2_COMPOUND_PLAN.md section 5 and is not
chosen after looking at the data:

* PRIMARY: on items labelled FULL or PARTIAL, acceptable = label in {A, B, C}. Paired exact
  McNemar test (two-sided binomial on the discordant pairs), the difference in acceptable rate,
  and a paired-bootstrap 95% CI (10,000 resamples, fixed seed).
* SECONDARY: criterion coverage per item (covered / needed), Wilcoxon signed-rank, paired.
* SAFETY: count of F (fabricated) per version — must not rise.
* Every label count per version, overall and per shape, so nothing is hidden behind a rate.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from scipy.stats import binomtest, wilcoxon

REPO = Path(__file__).resolve().parent.parent
ACCEPTABLE = {"A", "B", "C"}


def _coverage(cell: str, needed: int) -> Optional[float]:
    cell = (cell or "").strip()
    if not cell or needed <= 0:
        return None
    try:
        return max(0.0, min(1.0, float(cell) / needed))
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--set",
        required=True,
        action="append",
        help="a scored set; repeat to POOL sets (the pre-registered primary pools T-REAL and "
        "T-REAL-SUPPLEMENT -- tasks/V2_COMPOUND_PLAN.md section 5)",
    )
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()

    stems = [Path(s).stem for s in args.set]
    stem = "+".join(stems)
    sdir = REPO / "eval" / "compound" / "scoring"
    key: Dict[str, Dict[str, str]] = {}
    sheet: List[dict] = []
    for one in stems:
        k = json.loads((sdir / f"{one}_key.json").read_text(encoding="utf-8"))
        clash = set(k) & set(key)
        if clash:
            print(f"item ids repeat across pooled sets ({sorted(clash)[:3]}) -- refusing to pool")
            return 2
        key.update(k)
        with (sdir / f"{one}_sheet.csv").open(encoding="utf-8-sig", newline="") as fh:
            sheet.extend(csv.DictReader(fh))

    per: Dict[str, Dict[str, dict]] = defaultdict(dict)  # id -> version -> {label, cov}
    meta: Dict[str, dict] = {}
    missing = []
    for row in sheet:
        i = row["id"]
        needed = len([c for c in (row.get("criteria_needed") or "").split(";") if c.strip()])
        meta[i] = {"shape": row.get("shape", ""), "answerability": row.get("answerability", "")}
        for slot in ("X", "Y"):
            label = (row.get(f"label_{slot}") or "").strip().upper()[:1]
            if label not in "ABCDEF" or not label:
                missing.append(f"{i}/{slot}")
            per[i][key[i][slot]] = {
                "label": label,
                "cov": _coverage(row.get(f"criteria_covered_{slot}", ""), needed),
            }
    if missing:
        print(
            f"{len(missing)} labels missing or invalid, e.g. {missing[:5]} -- finish the sheet first"
        )
        return 2

    lines: List[str] = [f"# {stem}: {args.a} vs {args.b} (unblinded)", ""]
    for v in (args.a, args.b):
        c = Counter(per[i][v]["label"] for i in per)
        lines.append(f"- **{v}** labels: " + ", ".join(f"{k}={c.get(k, 0)}" for k in "ABCDEF"))
    lines.append("")

    answerable = [i for i in per if meta[i]["answerability"] in ("FULL", "PARTIAL")]
    acc_a = [per[i][args.a]["label"] in ACCEPTABLE for i in answerable]
    acc_b = [per[i][args.b]["label"] in ACCEPTABLE for i in answerable]
    n = len(answerable)
    b_only = sum(1 for x, y in zip(acc_a, acc_b) if not x and y)
    a_only = sum(1 for x, y in zip(acc_a, acc_b) if x and not y)
    p = binomtest(min(a_only, b_only), a_only + b_only, 0.5).pvalue if (a_only + b_only) else 1.0
    rate_a = sum(acc_a) / n if n else 0.0
    rate_b = sum(acc_b) / n if n else 0.0
    rng = random.Random(20261007)
    diffs = []
    for _ in range(10000):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(acc_b[k] for k in idx) / n - sum(acc_a[k] for k in idx) / n)
    diffs.sort()
    lo, hi = diffs[249], diffs[9749]
    lines += [
        "## Primary — acceptable rate on answerable items (FULL + PARTIAL)",
        f"n = {n}; {args.a} {rate_a:.1%}; {args.b} {rate_b:.1%}; difference {rate_b - rate_a:+.1%} "
        f"(paired bootstrap 95% CI {lo:+.1%} to {hi:+.1%})",
        f"discordant pairs: only {args.a} acceptable = {a_only}, only {args.b} acceptable = {b_only}; "
        f"exact McNemar p = {p:.4f}",
        "",
    ]

    pairs = [
        (per[i][args.a]["cov"], per[i][args.b]["cov"])
        for i in answerable
        if per[i][args.a]["cov"] is not None and per[i][args.b]["cov"] is not None
    ]
    if pairs and any(x != y for x, y in pairs):
        stat = wilcoxon([y for _, y in pairs], [x for x, _ in pairs])
        lines.append(
            f"## Secondary — criterion coverage: n = {len(pairs)}; mean {args.a} "
            f"{sum(x for x, _ in pairs) / len(pairs):.2f}, {args.b} {sum(y for _, y in pairs) / len(pairs):.2f}; "
            f"Wilcoxon p = {stat.pvalue:.4f}"
        )
    else:
        lines.append(
            "## Secondary — criterion coverage: not computable (no paired coverage values)"
        )
    lines.append("")

    fa = sum(1 for i in per if per[i][args.a]["label"] == "F")
    fb = sum(1 for i in per if per[i][args.b]["label"] == "F")
    lines += [f"## Safety — fabricated (F): {args.a} {fa}, {args.b} {fb}", ""]

    lines.append("## By shape (acceptable / items)")
    shapes = sorted({meta[i]["shape"] for i in per})
    for s in shapes:
        ids = [i for i in per if meta[i]["shape"] == s]
        ca = sum(per[i][args.a]["label"] in ACCEPTABLE for i in ids)
        cb = sum(per[i][args.b]["label"] in ACCEPTABLE for i in ids)
        lines.append(f"- {s}: {args.a} {ca}/{len(ids)}, {args.b} {cb}/{len(ids)}")

    out = sdir / f"{stem}_results.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
