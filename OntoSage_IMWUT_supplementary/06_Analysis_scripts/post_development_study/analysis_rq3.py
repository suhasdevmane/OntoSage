"""RQ3 primary and secondary analyses (Analysis_Specification.md §2), runnable on synthetic data.

Computes, with participant-cluster bootstrap intervals (2,000 resamples, percentile):
  E1  warranted-decision rate by situation (+ GEE logistic, exchangeable within participant)
  E2  warranted rate by the answer received (label of the last OntoSage answer in the task)
  C1  S2 - S1 difference
  C2  mean helpfulness, WL minus FD answers
  C3  Brier score and overconfidence, overall and by situation
and applies Holm across C1, C2, C3. S3 is described, not contrasted: both "not recorded" and
"could not find out" are warranted there, so its rate sits near the ceiling; the script counts
which kind of option S3 decisions took (read from task_bank.csv). The mixed model for E1 is
fitted separately in R (rq3_mixed_model.R); this script is its robustness check and the source
of every other RQ3 number.

Usage:
    python analysis_rq3.py --synthetic                 # test run on generated data (outputs/synthetic/)
    python analysis_rq3.py --decisions decisions.csv   # real run: decisions.csv carries answer_received
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Callable, Dict, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BANK = HERE.parent / "C_Task_Bank_and_Keys" / "task_bank.csv"
SITUATIONS = ["S1", "S2", "S3", "S4"]
LABELS = ["W", "WL", "FD", "U", "OT"]
B = 2000


# ------------------------------------------------------------------ synthetic data (tests only)
def synthetic(seed: int = 7, n: int = 30) -> pd.DataFrame:
    """Decisions for n participants with known structure, so the analysis can be checked."""
    rng = np.random.default_rng(seed)
    sched = pd.read_csv(HERE / "outputs" / "assignment_schedule.csv").head(n)
    base = {"S1": 1.6, "S2": 0.1, "S3": 1.0, "S4": 0.4}  # logits
    label_p = {"S1": [0.7, 0.1, 0.15, 0.03, 0.02], "S2": [0.2, 0.5, 0.15, 0.1, 0.05],
               "S3": [0.0, 0.8, 0.05, 0.1, 0.05], "S4": [0.4, 0.3, 0.15, 0.1, 0.05]}
    effect = {"W": 0.6, "WL": 0.2, "FD": -0.9, "U": -1.5, "OT": -0.5}
    rows = []
    for _, p in sched.iterrows():
        u = rng.normal(0, 0.8)
        for pos in range(1, 7):
            form = p[f"task_{pos}"]
            s = form[:2]
            lab = rng.choice(LABELS, p=label_p[s])
            logit = base[s] + effect[lab] + u
            w = rng.random() < 1 / (1 + np.exp(-logit))
            conf = float(np.clip(rng.normal(75 if w else 65, 15), 0, 100))
            helpf = int(np.clip(round(rng.normal({"W": 4.2, "WL": 3.6, "FD": 2.4, "U": 3.9, "OT": 2.6}[lab], 0.8)), 1, 5))
            # Only S3 needs the chosen option (its two warranted options are reported separately).
            option = (rng.choice(["b", "d"]) if w else rng.choice(["a", "c"])) if s == "S3" else ""
            rows.append({"code": p["participant_code"], "position": pos, "form": form, "situation": s,
                         "option": option, "answer_received": lab, "warranted": int(w), "confidence": conf,
                         "would_act": int(rng.random() < (0.7 if w else 0.5)), "helpfulness": helpf})
    return pd.DataFrame(rows)


def s3_option_roles() -> Dict[str, Dict[str, str]]:
    """Map each S3 form's option letters to absence_understood / no_conclusion / accepted_value."""
    bank = pd.read_csv(BANK, dtype=str).fillna("")
    roles: Dict[str, Dict[str, str]] = {}
    for _, r in bank[bank.situation == "S3"].iterrows():
        warranted = set(r.warranted_options.replace(",", " ").split())
        roles[r.form] = {}
        for k in "abcdef":
            text = r.get(f"option_{k}", "").strip()
            if not text:
                continue
            if k not in warranted:
                roles[r.form][k] = "accepted_value"
            elif text.lower().startswith("i could not find out"):
                roles[r.form][k] = "no_conclusion"
            else:
                roles[r.form][k] = "absence_understood"
    return roles


# ------------------------------------------------------------------ helpers
def cluster_boot(df: pd.DataFrame, stat: Callable[[pd.DataFrame], float], seed: int = 20261009) -> Tuple[float, float, float, np.ndarray]:
    """Point estimate, 95% percentile interval and the bootstrap draws, resampling participants."""
    rng = np.random.default_rng(seed)
    groups = {c: g for c, g in df.groupby("code")}
    codes = np.array(sorted(groups))
    draws = np.empty(B)
    for i in range(B):
        pick = rng.choice(codes, size=len(codes), replace=True)
        draws[i] = stat(pd.concat([groups[c] for c in pick], ignore_index=True))
    est = stat(df)
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return est, lo, hi, draws


def boot_p(draws: np.ndarray, null: float = 0.0) -> float:
    """Two-sided bootstrap p-value for H0: statistic == null."""
    d = draws[~np.isnan(draws)]
    tail = min((d <= null).mean(), (d >= null).mean())
    return float(min(1.0, max(2 * tail, 1 / B)))  # never 0: the floor is 1/B


def holm(pvals: Dict[str, float]) -> Dict[str, float]:
    """Holm-adjusted p-values."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def rate(s: str) -> Callable[[pd.DataFrame], float]:
    return lambda d: d.loc[d.situation == s, "warranted"].mean()


# ------------------------------------------------------------------ analyses
def analyse(df: pd.DataFrame) -> Dict[str, object]:
    res: Dict[str, object] = {"n_participants": int(df.code.nunique()), "n_decisions": int(len(df))}

    e1 = {}
    for s in SITUATIONS:
        est, lo, hi, _ = cluster_boot(df, rate(s))
        e1[s] = {"rate": est, "lo": lo, "hi": hi, "n": int((df.situation == s).sum())}
    res["E1_bootstrap"] = e1

    try:
        import statsmodels.api as sm
        import statsmodels.formula.api as smf

        m = smf.gee("warranted ~ C(situation, Treatment('S1'))", "code", df,
                    family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
        res["E1_gee"] = {k: {"coef": float(v), "p": float(m.pvalues[k])} for k, v in m.params.items()}
    except Exception as exc:  # noqa: BLE001
        res["E1_gee"] = {"error": f"{type(exc).__name__}: {exc}"}

    e2 = {}
    for lab in LABELS:
        sub = df[df.answer_received == lab]
        if len(sub) < 10:
            e2[lab] = {"n": int(len(sub)), "warranted": int(sub.warranted.sum()), "rate": None}
            continue
        est, lo, hi, _ = cluster_boot(df, lambda d, lab=lab: d.loc[d.answer_received == lab, "warranted"].mean())
        e2[lab] = {"n": int(len(sub)), "rate": est, "lo": lo, "hi": hi}
    res["E2"] = e2

    pv = {}
    est, lo, hi, draws = cluster_boot(df, lambda d: rate("S2")(d) - rate("S1")(d))
    res["C1_S2_minus_S1"] = {"diff": est, "lo": lo, "hi": hi}
    pv["C1"] = boot_p(draws)

    s3 = df[df.situation == "S3"]
    if "option" in df.columns and len(s3):
        roles = s3_option_roles()
        kinds = [roles.get(f, {}).get(str(o).strip().lower(), "unknown") for f, o in zip(s3.form, s3.option)]
        res["S3_descriptive"] = {"n": int(len(s3)),
                                 **{k: int(v) for k, v in pd.Series(kinds).value_counts().items()}}
    else:
        res["S3_descriptive"] = {"n": int(len(s3)), "note": "no option column, so the options are not counted"}

    def help_diff(d: pd.DataFrame) -> float:
        return d.loc[d.answer_received == "WL", "helpfulness"].mean() - d.loc[d.answer_received == "FD", "helpfulness"].mean()

    est, lo, hi, draws = cluster_boot(df, help_diff)
    res["C2_helpfulness_WL_minus_FD"] = {"diff": est, "lo": lo, "hi": hi,
                                          "n_WL": int((df.answer_received == "WL").sum()), "n_FD": int((df.answer_received == "FD").sum())}
    pv["C2"] = boot_p(draws)

    def overconf(d: pd.DataFrame) -> float:
        return d.confidence.mean() / 100 - d.warranted.mean()

    est, lo, hi, draws = cluster_boot(df, overconf)
    brier = cluster_boot(df, lambda d: ((d.confidence / 100 - d.warranted) ** 2).mean())
    res["C3_calibration"] = {"overconfidence": est, "lo": lo, "hi": hi,
                             "brier": brier[0], "brier_lo": brier[1], "brier_hi": brier[2],
                             "by_situation": {s: overconf(df[df.situation == s]) for s in SITUATIONS}}
    pv["C3"] = boot_p(draws)

    res["raw_p"] = pv
    res["holm_p"] = holm(pv)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--decisions", default="")
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    if args.synthetic:
        df = synthetic()
        out = Path(args.out_dir or HERE / "outputs" / "synthetic")
        src = "synthetic (seed 7)"
    else:
        df = pd.read_csv(args.decisions)
        out = Path(args.out_dir or HERE / "outputs")
        src = hashlib.sha256(Path(args.decisions).read_bytes()).hexdigest()
    res = analyse(df)
    res["input"] = src
    out.mkdir(parents=True, exist_ok=True)
    (out / "rq3_results.json").write_text(json.dumps(res, indent=2, default=float) + "\n", encoding="utf-8")
    df.to_csv(out / "rq3_input_used.csv", index=False)
    e1 = res["E1_bootstrap"]
    print("E1 warranted rate by situation (cluster bootstrap 95%):")
    for s in SITUATIONS:
        print(f"  {s}: {e1[s]['rate']:.2f} [{e1[s]['lo']:.2f}, {e1[s]['hi']:.2f}]  n={e1[s]['n']}")
    print("Holm-adjusted:", {k: round(v, 4) for k, v in res["holm_p"].items()})
    print("written:", out / "rq3_results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
