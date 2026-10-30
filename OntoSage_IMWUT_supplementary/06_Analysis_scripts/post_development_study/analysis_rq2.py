"""RQ2 offline comparison (Analysis_Specification.md §3), runnable on synthetic labels.

Input: one row per (question, system) with the adjudicated label; questions carry the participant
who typed them, so intervals resample PARTICIPANTS (each contributes several questions).

  * Rates per system: U (safety), W + WL (usefulness), FD (cost), OT, PF.
  * Paired differences A - B on the same questions, participant-cluster bootstrap 95% interval;
    Holm across the two primary metrics (U, W+WL); exact McNemar on U as the secondary test.
  * Frontier table: U rate vs W + WL rate per configuration (feeds Figure 2).
  * Error anatomy: U sub-types per system (Figure 3).
  * Stability: share of items whose label category changes across repeated runs, per system.

    python analysis_rq2.py --synthetic
    python analysis_rq2.py --labels comparison_labels_agreed.csv [--runs stability_labels.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path
from typing import Dict, List

import numpy as np

HERE = Path(__file__).resolve().parent
B = 2000


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p from the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return float(min(1.0, 2 * p))


def holm(p: Dict[str, float]) -> Dict[str, float]:
    items = sorted(p.items(), key=lambda kv: kv[1])
    out, run = {}, 0.0
    for i, (k, v) in enumerate(items):
        run = max(run, min(1.0, (len(items) - i) * v))
        out[k] = run
    return out


def analyse(rows: List[dict], systems=("A", "B")) -> Dict[str, object]:
    by_q: Dict[str, Dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_q[r["question_id"]][r["system"]] = r
    qs = sorted(q for q, d in by_q.items() if all(s in d for s in systems))
    part = {q: by_q[q][systems[0]]["participant"] for q in qs}

    def is_u(r): return r["label"] == "U"
    def is_good(r): return r["label"] in ("W", "WL")
    def is_fd(r): return r["label"] == "FD"

    def rate(qset, sysname, fn):
        return float(np.mean([fn(by_q[q][sysname]) for q in qset])) if qset else float("nan")

    res: Dict[str, object] = {"n_questions": len(qs), "n_participants": len(set(part.values()))}
    res["rates"] = {s: {"U": rate(qs, s, is_u), "W+WL": rate(qs, s, is_good), "FD": rate(qs, s, is_fd),
                        "labels": dict(Counter(by_q[q][s]["label"] for q in qs))} for s in systems}
    rng = np.random.default_rng(20261009)
    groups = defaultdict(list)
    for q in qs:
        groups[part[q]].append(q)
    ps = sorted(groups)
    pvals = {}
    for name, fn in (("U", is_u), ("W+WL", is_good), ("FD", is_fd)):
        est = rate(qs, systems[0], fn) - rate(qs, systems[1], fn)
        draws = []
        for _ in range(B):
            sample = [q for p in rng.choice(ps, size=len(ps), replace=True) for q in groups[p]]
            draws.append(rate(sample, systems[0], fn) - rate(sample, systems[1], fn))
        d = np.array(draws)
        lo, hi = np.percentile(d, [2.5, 97.5])
        p = float(min(1.0, max(2 * min((d <= 0).mean(), (d >= 0).mean()), 1 / B)))
        res[f"diff_{name}"] = {"A_minus_B": est, "lo": float(lo), "hi": float(hi), "boot_p": p}
        if name in ("U", "W+WL"):
            pvals[name] = p
    b_ = sum(1 for q in qs if is_u(by_q[q][systems[0]]) and not is_u(by_q[q][systems[1]]))
    c_ = sum(1 for q in qs if not is_u(by_q[q][systems[0]]) and is_u(by_q[q][systems[1]]))
    res["mcnemar_U"] = {"A_only_U": b_, "B_only_U": c_, "p_exact": mcnemar_exact(b_, c_)}
    res["holm_primary"] = holm(pvals)
    res["frontier"] = [{"system": s, "U_rate": res["rates"][s]["U"], "W_WL_rate": res["rates"][s]["W+WL"]} for s in systems]
    res["u_anatomy"] = {s: dict(Counter(st for q in qs for st in (by_q[q][s].get("u_subtypes") or "").split(";")
                                        if by_q[q][s]["label"] == "U" and st)) for s in systems}
    return res


def stability(runs: List[dict]) -> Dict[str, float]:
    """Share of (system, question) items whose label category changed across runs."""
    cat = {"W": "good", "WL": "good", "U": "U", "FD": "FD", "OT": "OT", "PF": "PF"}
    labs = defaultdict(set)
    for r in runs:
        labs[(r["system"], r["question_id"])].add(cat.get(r["label"], r["label"]))
    by_sys = defaultdict(list)
    for (s, _), v in labs.items():
        by_sys[s].append(len(v) > 1)
    return {s: float(np.mean(v)) for s, v in by_sys.items()}


def synthetic(seed: int = 5) -> List[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(100):
        p = f"P{rng.integers(1, 31):02d}"
        a = rng.choice(["W", "WL", "U", "FD", "OT"], p=[.35, .3, .07, .2, .08])
        bb = rng.choice(["W", "WL", "U", "FD", "OT"], p=[.4, .15, .25, .1, .1])
        for sysname, lab in (("A", a), ("B", bb)):
            rows.append({"question_id": f"Q{i:03d}", "participant": p, "system": sysname, "label": str(lab),
                         "u_subtypes": str(rng.choice(["scope", "proxy", "temporal", "fabricated"])) if lab == "U" else ""})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--labels", default="")
    ap.add_argument("--runs", default="")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()
    if args.synthetic:
        rows, out = synthetic(), Path(args.out_dir or HERE / "outputs" / "synthetic")
    else:
        rows, out = list(csv.DictReader(open(args.labels, encoding="utf-8"))), Path(args.out_dir or HERE / "outputs")
    res = analyse(rows)
    if args.runs:
        res["stability"] = stability(list(csv.DictReader(open(args.runs, encoding="utf-8"))))
    out.mkdir(parents=True, exist_ok=True)
    (out / "rq2_results.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    for k in ("diff_U", "diff_W+WL", "diff_FD"):
        d = res[k]
        print(f"{k:10s} A-B {d['A_minus_B']:+.3f} [{d['lo']:+.3f}, {d['hi']:+.3f}]")
    print("McNemar U:", res["mcnemar_U"], " Holm:", {k: round(v, 4) for k, v in res["holm_primary"].items()})
    print("written:", out / "rq2_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
