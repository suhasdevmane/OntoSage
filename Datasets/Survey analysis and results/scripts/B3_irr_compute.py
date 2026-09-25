#!/usr/bin/env python3
"""
B3_irr_compute.py
=================
Compute Cohen's Kappa (and % agreement) between:
  Coder A = deterministic machine classifier  (machine_* columns in irr_samples.csv)
  Coder B = LLM classifier                   (taxonomy/irr_samples_coderB_llm.csv)

Writes:
  outputs/tables/B3_irr_report.md   — final IRR report with real kappa values

Usage:
  python scripts/B3_irr_compute.py
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

from sklearn.metrics import cohen_kappa_score

HERE = Path(__file__).resolve().parent
SURVEY_ROOT = HERE.parent
IRR_SAMPLE = SURVEY_ROOT / "taxonomy" / "irr_samples.csv"
CODER_B = SURVEY_ROOT / "taxonomy" / "irr_samples_coderB_llm.csv"
REPORT_OUT = SURVEY_ROOT / "outputs" / "tables" / "B3_irr_report.md"

DIMS = ["domain_l1", "query_type_l2", "intent", "temporal", "spatial", "complexity"]
# machine_* column prefix
MACHINE_PREFIX = "machine_"


def load_coderA(path: Path) -> dict[str, dict]:
    """Load machine labels keyed by (PID, Stage, Question)."""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["PID"], row["Stage"], row["Question"].strip())
            out[key] = {d: row.get(f"{MACHINE_PREFIX}{d}", "").strip().upper() for d in DIMS}
    return out


def load_coderB(path: Path) -> dict[str, dict]:
    """Load LLM labels keyed by (PID, Stage, Question)."""
    out = {}
    if not path.exists():
        sys.exit(f"Coder B file not found: {path}\nRun B3_irr_llm_coder.py first.")
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["PID"], row["Stage"], row["Question"].strip())
            out[key] = {d: row.get(d, "").strip().upper() for d in DIMS}
    return out


def compute_kappa(a_labels: list[str], b_labels: list[str]) -> tuple[float, float]:
    """Return (kappa, pct_agreement)."""
    agree = sum(x == y for x, y in zip(a_labels, b_labels))
    pct = 100.0 * agree / len(a_labels) if a_labels else 0.0
    try:
        kappa = float(cohen_kappa_score(a_labels, b_labels))
    except ValueError:
        kappa = float("nan")
    return kappa, pct


def kappa_interp(k: float) -> str:
    if k >= 0.80:
        return "almost perfect"
    elif k >= 0.70:
        return "substantial"
    elif k >= 0.60:
        return "moderate"
    elif k >= 0.50:
        return "moderate (borderline)"
    else:
        return "fair / poor — needs reconciliation"


def find_disagreements(
    coderA: dict, coderB: dict, common_keys: list, dim: str, n: int = 5
) -> list[tuple[str, str, str]]:
    """Return up to n (question, A_label, B_label) disagreement examples."""
    out = []
    for key in common_keys:
        va = coderA[key][dim]
        vb = coderB[key][dim]
        if va != vb:
            q = key[2][:90]
            out.append((q, va, vb))
        if len(out) >= n:
            break
    return out


def main() -> None:
    coder_a = load_coderA(IRR_SAMPLE)
    coder_b = load_coderB(CODER_B)

    common = sorted(set(coder_a) & set(coder_b))
    only_a = len(coder_a) - len(common)
    only_b = len(coder_b) - len(common)
    n = len(common)
    print(f"Matched rows: {n}  (Coder A only: {only_a}, Coder B only: {only_b})")

    if n == 0:
        sys.exit("No matched rows — check PID/Stage/Question keys align between files.")

    results = {}
    for dim in DIMS:
        a_vals = [coder_a[k][dim] for k in common]
        b_vals = [coder_b[k][dim] for k in common]
        kappa, pct = compute_kappa(a_vals, b_vals)
        disagrees = find_disagreements(coder_a, coder_b, common, dim)
        results[dim] = (kappa, pct, disagrees)
        interp = kappa_interp(kappa)
        print(f"  {dim:<18} k={kappa:+.3f}  agree={pct:.1f}%  [{interp}]")

    # Write report
    lines = [
        f"# Phase B3 — Inter-Rater Reliability Report",
        f"",
        f"**Date:** {date.today().isoformat()}  ",
        f"**Sample:** `taxonomy/irr_samples.csv` (300 questions, seed 43)  ",
        f"**Coder A:** Deterministic lexicon classifier (`B_corpus_classification.py` — `machine_*` columns)  ",
        f"**Coder B:** LLM classifier (OpenAI gpt-4o, independent run, `B3_irr_llm_coder.py`)  ",
        f"**Matched rows:** {n} / 300  ",
        f"**Target Cohen's Kappa per dimension:** ≥ 0.70 (substantial agreement)",
        f"",
        f"## Results",
        f"",
        f"| Dimension | Cohen's κ | Agreement % | Interpretation |",
        f"|-----------|-----------|-------------|----------------|",
    ]
    targets_met = 0
    for dim in DIMS:
        k, pct, _ = results[dim]
        interp = kappa_interp(k)
        flag = "✓" if k >= 0.70 else "⚠"
        if k >= 0.70:
            targets_met += 1
        lines.append(f"| {dim} | {k:+.3f} | {pct:.1f}% | {flag} {interp} |")

    lines += [
        f"",
        f"**Dimensions meeting κ ≥ 0.70 target:** {targets_met} / {len(DIMS)}",
        f"",
        f"## Disagreement examples (top 5 per dimension)",
        f"",
    ]
    for dim in DIMS:
        k, pct, disagrees = results[dim]
        lines.append(f"### {dim}  (κ={k:+.3f}, agreement={pct:.1f}%)")
        lines.append("")
        if not disagrees:
            lines.append("_No disagreements — perfect agreement on this dimension._")
        else:
            lines.append("| Question (truncated) | Coder A | Coder B |")
            lines.append("|----------------------|---------|---------|")
            for q, va, vb in disagrees:
                lines.append(f"| {q} | {va} | {vb} |")
        lines.append("")

    lines += [
        f"## Open questions for reconciliation round",
        f"",
        f"1. **DIAGNOSTIC vs ANOMALY** — when 'is X too high?' should be coded ANOMALY vs DIAGNOSTIC.",
        f"2. **CAPABILITY scope** — 'can the building do X' vs 'can the system do X'.",
        f"3. **INFO_REQUEST vs WAYFINDING** — overlap for amenity-hours queries.",
        f"",
        f"## Notes",
        f"",
        f"- Coder A is deterministic (keyword lexicon, no LLM calls). "
        f"Coder B is an independent LLM pass with temperature=0.",
        f"- Agreement between two independent computational approaches validates the "
        f"coding scheme's objectivity and reproducibility.",
        f"- Rows where only one coder has a label ({only_a + only_b} total) are excluded from kappa.",
        f"",
    ]

    REPORT_OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written -> {REPORT_OUT}")
    print(f"Dimensions meeting k >= 0.70: {targets_met}/{len(DIMS)}")


if __name__ == "__main__":
    main()
