"""Export the aggregates the paper cites that no earlier phase script wrote.

WHY: `verify_claims.py` traces every table cell back to the file that produced
it. Three sets of numbers in the paper had no such file -- they had been
computed once, pasted in, and never regenerated. Two of them (the intent counts
and domain shares of `tab:stage-stats` panels B and C) had silently gone stale
against a superseded corpus and were wrong in every cell: the paper's own panel
B did not even sum to its stage totals. A number with no generating artefact is
a number nobody can check.

Writes:
    outputs/tables/Z_intent_by_stage.csv   -- panel B of tab:stage-stats
    outputs/tables/Z_domain_by_stage.csv   -- panel C, with the named domains
    outputs/tables/Z_paper_constants.csv   -- corpus totals quoted in captions

Run:  python scripts/Z_paper_derived_tables.py
"""
import csv
import io
import os
from collections import Counter

import numpy as np
from scipy.stats import chi2_contingency

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS = os.path.join(ROOT, "corpus", "classified_corpus.csv")
OUT = os.path.join(ROOT, "outputs", "tables")


def main():
    rows = list(csv.DictReader(io.open(CORPUS, encoding="utf-8-sig")))
    os.makedirs(OUT, exist_ok=True)

    def stage(r):
        return str(r["Stage"]).replace("Stage_", "").replace("S", "").strip()

    stages = sorted({stage(r) for r in rows})
    intents = sorted({r["intent"].strip() for r in rows if r["intent"].strip()})

    # --- panel B --------------------------------------------------------
    obs = []
    with io.open(os.path.join(OUT, "Z_intent_by_stage.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stage", "n"] + intents)
        for s in stages:
            sub = [r for r in rows if stage(r) == s]
            c = Counter(r["intent"].strip() for r in sub)
            counts = [c.get(i, 0) for i in intents]
            assert sum(counts) == len(sub), f"stage {s} intents do not sum to n"
            obs.append(counts)
            w.writerow([s, len(sub)] + counts)

    chi2, p, dof, _ = chi2_contingency(np.array(obs))
    nn = int(np.array(obs).sum())
    v = float(np.sqrt(chi2 / (nn * (min(np.array(obs).shape) - 1))))
    print(f"intent x stage: chi2({dof})={chi2:.1f}, p={p:.3e}, Cramer V={v:.3f}, N={nn}")

    # --- panel C --------------------------------------------------------
    NAMED = ["OTHER", "ENERGY", "AIR_QUALITY"]
    with io.open(os.path.join(OUT, "Z_domain_by_stage.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stage", "n"] + [f"pct_{d}" for d in NAMED])
        for s in stages:
            sub = [r for r in rows if stage(r) == s]
            c = Counter(r["domain_l1"].strip() for r in sub)
            w.writerow([s, len(sub)] +
                       [round(c.get(d, 0) / len(sub) * 100, 2) for d in NAMED])

    # --- constants quoted in captions and prose -------------------------
    consts = {
        "n_questions": len(rows),
        "n_participants": len({r["PID"] for r in rows}),
        "chi2_intent_by_stage": round(chi2, 1),
        "chi2_intent_dof": dof,
        "chi2_intent_p": f"{p:.3e}",
        "cramers_v_intent": round(v, 3),
    }
    for s in stages:
        consts[f"n_stage_{s}"] = sum(1 for r in rows if stage(r) == s)

    # Derived sums the paper states in prose but no phase script emitted.
    g2 = os.path.join(OUT, "G2_capability_matrix.csv")
    if os.path.exists(g2):
        g = list(csv.DictReader(io.open(g2, encoding="utf-8-sig")))
        wholly = [x for x in g if float(x["analytical_share_pct"]) >= 99]
        top2 = sorted(g, key=lambda x: -float(x["share_pct"]))[:2]
        consts["pct_volume_wholly_analytical_types"] = round(
            sum(float(x["share_pct"]) for x in wholly), 2)
        consts["pct_volume_top2_nonanalytical_types"] = round(
            sum(float(x["share_pct"]) for x in top2), 2)
    with io.open(os.path.join(OUT, "Z_paper_constants.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["constant", "value"])
        for k, val in consts.items():
            w.writerow([k, val])
            print(f"  {k:<26} {val}")


if __name__ == "__main__":
    main()
