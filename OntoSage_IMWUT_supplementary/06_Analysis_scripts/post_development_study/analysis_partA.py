"""RQ1 / Part A analyses (Analysis_Specification.md §4), runnable on synthetic labels.

  * Stratified weighted proportion of each label of a field, W_s = N_s / N, with the finite-population
    variance sum W_s^2 p_s (1 - p_s) / n_s * (1 - n_s / N_s) and a 95% Wald interval.
  * Equal-contributor summary (each row weighted by 1 / that contributor's eligible submissions).
  * Contributor-clustered bootstrap interval (rows kept together, 2,000 resamples).
  * Sensitivity: unique texts only; top-decile contributors (by corpus volume) excluded.
  * Agreement between two coders: Cohen's kappa (single-label), per-label kappa and mean Jaccard
    (multi-label), raw agreement.

Never an ordinary chi-square treating questions as independent people.

    python analysis_partA.py --synthetic
    python analysis_partA.py --coded partA_agreed.csv [--coder1 a.csv --coder2 b.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SOURCE = REPO / "paper" / "Survey analysis and results" / "inputs" / "questions_by_user.csv"
MULTI = {"F1_request_type", "F2_evidence_source"}
SINGLE = ["F3a_place", "F3b_time", "F3c_criterion", "F4_evidence_relation", "F5_answerable", "F6_purpose"]
# F3a-F3c joined 27 Oct 2026: the RQ1 text reports their shares, so it must report their agreement (G14)
B = 2000


def labels(cell: str) -> List[str]:
    return [x.strip() for x in re.split(r"[;,|]", cell or "") if x.strip()]


def corpus_counts() -> Dict[str, int]:
    """Eligible submissions per contributor code (C001.., the same mapping as make_partA_samples.py)."""
    with SOURCE.open(encoding="utf-8-sig", newline="") as fh:
        raw = list(csv.DictReader(fh))
    codes = {u: f"C{i + 1:03d}" for i, u in enumerate(sorted({r["Username"] for r in raw}))}
    return dict(Counter(codes[r["Username"]] for r in raw))


def stratified(rows: List[dict], has: Sequence[bool], N: Dict[str, int]) -> Dict[str, float]:
    by = defaultdict(list)
    for r, h in zip(rows, has):
        by[r["stage"]].append(h)
    Ntot = sum(N[s] for s in by)
    p = var = 0.0
    for s, hs in by.items():
        n, ps, w = len(hs), float(np.mean(hs)), N[s] / Ntot
        p += w * ps
        var += w * w * ps * (1 - ps) / n * (1 - n / N[s])
    se = var ** 0.5
    return {"p": p, "lo": max(0.0, p - 1.96 * se), "hi": min(1.0, p + 1.96 * se)}


def equal_contributor(rows: List[dict], has: Sequence[bool], counts: Dict[str, int]) -> float:
    w = np.array([1.0 / counts.get(r["contributor"], 1) for r in rows])
    return float((w * np.array(has, dtype=float)).sum() / w.sum())


def cluster_boot(rows: List[dict], has: Sequence[bool], N: Dict[str, int], seed: int = 20261009) -> List[float]:
    rng = np.random.default_rng(seed)
    by_c = defaultdict(list)
    for i, r in enumerate(rows):
        by_c[r["contributor"]].append(i)
    cs = sorted(by_c)
    draws = []
    for _ in range(B):
        pick = [i for c in rng.choice(cs, size=len(cs), replace=True) for i in by_c[c]]
        sub = [rows[i] for i in pick]
        if len({r["stage"] for r in sub}) < len({r["stage"] for r in rows}):
            continue
        draws.append(stratified(sub, [has[i] for i in pick], N)["p"])
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return [float(lo), float(hi)]


def estimates(rows: List[dict], field: str, N: Dict[str, int], counts: Dict[str, int]) -> Dict[str, dict]:
    vals = sorted({lab for r in rows for lab in labels(r[field])})
    norm = lambda t: re.sub(r"\s+", " ", t.strip().lower()).rstrip(" ?.!")  # noqa: E731
    first_text, unique_idx = set(), []
    for i, r in enumerate(rows):
        k = norm(r.get("question_text", ""))
        if k not in first_text:
            first_text.add(k)
            unique_idx.append(i)
    top = set(sorted(counts, key=counts.get, reverse=True)[: max(1, len(counts) // 10)])
    keep_idx = [i for i, r in enumerate(rows) if r["contributor"] not in top]
    out = {}
    for v in vals:
        has = [v in labels(r[field]) for r in rows]
        est = stratified(rows, has, N)
        out[v] = {
            **est, "n_rows_with_label": int(sum(has)),
            "cluster_boot_95": cluster_boot(rows, has, N),
            "equal_contributor": equal_contributor(rows, has, counts),
            "unique_texts_only": stratified([rows[i] for i in unique_idx], [has[i] for i in unique_idx], N)["p"],
            "top_decile_excluded": stratified([rows[i] for i in keep_idx], [has[i] for i in keep_idx], N)["p"],
        }
    return out


def kappa(a: Sequence[str], b: Sequence[str]) -> float:
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((list(a).count(c) / n) * (list(b).count(c) / n) for c in cats)
    return float((po - pe) / (1 - pe)) if pe < 1 else 1.0


def agreement(c1: List[dict], c2: List[dict]) -> Dict[str, dict]:
    m2 = {r["row_id"]: r for r in c2}
    pairs = [(r, m2[r["row_id"]]) for r in c1 if r["row_id"] in m2]
    out = {"n_pairs": len(pairs)}
    for f in SINGLE:
        a, b = [p[0][f] for p in pairs], [p[1][f] for p in pairs]
        out[f] = {"kappa": kappa(a, b), "raw": float(np.mean([x == y for x, y in zip(a, b)]))}
    for f in MULTI:
        sets = [(set(labels(p[0][f])), set(labels(p[1][f]))) for p in pairs]
        jac = [len(x & y) / len(x | y) if (x | y) else 1.0 for x, y in sets]
        per = {}
        for lab in sorted({lab for x, y in sets for lab in x | y}):
            per[lab] = kappa([str(lab in x) for x, _ in sets], [str(lab in y) for _, y in sets])
        out[f] = {"mean_jaccard": float(np.mean(jac)), "per_label_kappa": per}
    return out


def synthetic(seed: int = 3) -> tuple:
    rng = np.random.default_rng(seed)
    with (HERE / "outputs" / "partA_validation_rows.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    f2_opts = ["measurement", "description", "record", "document", "external"]
    f4_opts = ["direct", "proxy", "not_establishable", "unclear"]
    c1, c2 = [], []
    for r in rows:
        f2 = list(rng.choice(f2_opts, size=rng.integers(1, 3), replace=False, p=[.45, .25, .15, .1, .05]))
        f4 = str(rng.choice(f4_opts, p=[.55, .25, .15, .05]))
        base = {**r, "F1_request_type": "fact", "F2_evidence_source": ";".join(f2), "F4_evidence_relation": f4,
                "F5_answerable": str(rng.choice(["yes", "partly", "no"])), "F6_purpose": str(rng.choice(["yes", "no"], p=[.2, .8]))}
        c1.append(base)
        other = dict(base)
        if rng.random() < 0.2:
            other["F4_evidence_relation"] = str(rng.choice(f4_opts))
        c2.append(other)
    return c1, c2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--coded", default="")
    ap.add_argument("--coder1", default="")
    ap.add_argument("--coder2", default="")
    ap.add_argument("--manifest", default=str(HERE / "outputs" / "partA_sample_manifest.json"))
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()
    N = {k: int(v) for k, v in json.loads(Path(args.manifest).read_text(encoding="utf-8"))["stage_sizes_N"].items()}
    counts = corpus_counts()
    if args.synthetic:
        coded, c2 = synthetic()
        c1 = coded
        out = Path(args.out_dir or HERE / "outputs" / "synthetic")
    else:
        coded = list(csv.DictReader(open(args.coded, encoding="utf-8")))
        c1 = list(csv.DictReader(open(args.coder1, encoding="utf-8"))) if args.coder1 else []
        c2 = list(csv.DictReader(open(args.coder2, encoding="utf-8"))) if args.coder2 else []
        out = Path(args.out_dir or HERE / "outputs")
    res = {"n_rows": len(coded), "stage_N": N,
           "F2_evidence_source": estimates(coded, "F2_evidence_source", N, counts),
           "F4_evidence_relation": estimates(coded, "F4_evidence_relation", N, counts)}
    if c1 and c2:
        res["agreement"] = agreement(c1, c2)
    out.mkdir(parents=True, exist_ok=True)
    (out / "partA_results.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    for lab, e in res["F4_evidence_relation"].items():
        print(f"F4 {lab:18s} {e['p']:.3f} [{e['lo']:.3f}, {e['hi']:.3f}]  boot {e['cluster_boot_95'][0]:.3f}-{e['cluster_boot_95'][1]:.3f}"
              f"  equal-contrib {e['equal_contributor']:.3f}")
    if "agreement" in res:
        print("kappa F4:", round(res["agreement"]["F4_evidence_relation"]["kappa"], 3))
    print("written:", out / "partA_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
