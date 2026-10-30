#!/usr/bin/env python3
"""RQ2, the offline comparison on the study's own questions (Analysis_Specification §3; plan 03 section 7).

    python rq2_live_analysis.py

Reads labels/rq2/rq2_labels_{comparison,ttask,stability}.csv (merge_rq2_labels.py) and writes results/rq2/.
Reuses analysis_rq2.py (the pre-registered script) unchanged: analyse() for rates, paired A-B differences with the
participant-cluster bootstrap (2,000, seed 20261009), Holm across U and W+WL, exact McNemar on U, the frontier and the
U anatomy; stability() for label-category changes across runs.

Scored answer per (question, system): a provider failure's re-run where one exists (both stay in the run files).
Labels are PROVISIONAL AI pre-labels made on the blind sheet unless merge_rq2_labels.py found human-agreed labels
(finalise_agreed_labels.py pass2); every output says which in label_source.
Sensitivity variants (exploratory): contested classes flipped; the baseline's '(empty answer)' rows dropped
pairwise; high-confidence labels only; T-LIVE and T-FRESH separately.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analysis_rq2 as pre  # noqa: E402
from study_paths import LABELS, RESULTS, pass1_labels  # noqa: E402

RQ2L = LABELS / "rq2"
OUT = RESULTS / "rq2"
NUMBERS: list = []


def norm_source(k: str) -> str:
    """merge_rq2_labels.py's labeller kind, in the same spelling the rest of the pipeline already uses."""
    return "PROVISIONAL_AI_PRELABEL_BLIND_SHEET" if k == "PROVISIONAL_AI_PRELABEL" else k


def num(key, value, desc, source: str):
    """Every number carries the label source of the ONE dataset it was actually computed from (A4, 28 Oct) --
    never a blanket source for the whole script. A number from the comparison set must not print orange just
    because the unrelated ttask or stability sets are still AI-only, and vice versa."""
    NUMBERS.append({"key": key, "value": value, "description": desc, "script": "rq2_live_analysis.py", "label_source": source})


def participant(qid: str) -> str:
    """Bootstrap cluster: the participant who typed the question; for the 12 canonical T-TASK questions (no
    participant) the question itself, so its three runs stay in one cluster ('TT-S4-3-r2' -> 'TT-S4-3')."""
    parts = qid.split("-")
    if qid.startswith("TT-"):
        return "-".join(parts[:3])
    return parts[1] if len(parts) > 1 and parts[1].startswith("P") else qid


def to_rows(d: pd.DataFrame, label_col: str = "label", cluster: str = "participant") -> list:
    """Rows for analysis_rq2.analyse; its bootstrap resamples the 'participant' field, which holds the cluster:
    the participant by default, or the study form (the specification's per-form sensitivity for T-LIVE)."""
    return [{"question_id": r.qid, "system": r.system, "label": getattr(r, label_col),
             "participant": r.form if cluster == "form" else participant(r.qid),
             "u_subtypes": ";".join(str(r.u_subtypes).split()) if isinstance(r.u_subtypes, str) else ""}
            for r in d.itertuples()]


def mcnemar_good(d: pd.DataFrame, a: str, b: str) -> dict:
    w = d.pivot_table(index="qid", columns="system", values="label", aggfunc="first")
    missing = [s for s in (a, b) if s not in w.columns]
    if missing:
        return {"A_only_good": 0, "B_only_good": 0, "p_exact": 1.0, "note": f"no paired rows for {missing}"}
    w = w.dropna(subset=[a, b])
    good = w.isin(["W", "WL"])
    x = int((good[a] & ~good[b]).sum())
    y = int((~good[a] & good[b]).sum())
    return {"A_only_good": x, "B_only_good": y, "p_exact": pre.mcnemar_exact(x, y)}


def rate_ci(d: pd.DataFrame, system: str, labels: tuple, seed: int = 20261009) -> dict:
    """One system's rate of the given labels with a participant-cluster bootstrap 95% CI (2,000 resamples)."""
    import numpy as np
    s = d[d.system == system].copy()
    s["p"] = s.qid.map(participant)
    s["hit"] = s.label.isin(labels).astype(float)
    groups = {p: g.hit.values for p, g in s.groupby("p")}
    ps = sorted(groups)
    if not ps:
        return {"rate": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0, "note": "no data"}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(pre.B):
        pick = rng.choice(ps, size=len(ps), replace=True)
        v = np.concatenate([groups[p] for p in pick])
        draws.append(v.mean())
    return {"rate": float(s.hit.mean()), "lo": float(np.percentile(draws, 2.5)), "hi": float(np.percentile(draws, 97.5)),
            "n": int(len(s))}


def compare(d: pd.DataFrame, a: str, b: str, tag: str, res: dict, source: str, cluster: str = "participant") -> None:
    sub = d[d.system.isin([a, b])]
    r = pre.analyse(to_rows(sub, cluster=cluster), systems=(a, b))
    r["cluster"] = cluster
    r["mcnemar_W+WL"] = mcnemar_good(sub, a, b)
    paired = sub[sub.qid.isin(set(sub[sub.system == a].qid) & set(sub[sub.system == b].qid))]
    r["rate_ci"] = {s: {"U": rate_ci(paired, s, ("U",)), "W+WL": rate_ci(paired, s, ("W", "WL")),
                        "FD": rate_ci(paired, s, ("FD",))} for s in (a, b)}
    res[tag] = r
    for s in (a, b):
        num(f"{tag}_{s}_U", round(100 * r["rates"][s]["U"], 1), f"{tag}: U rate, system {s} (%)", source)
        num(f"{tag}_{s}_WWL", round(100 * r["rates"][s]["W+WL"], 1), f"{tag}: W+WL rate, system {s} (%)", source)
        num(f"{tag}_{s}_FD", round(100 * r["rates"][s]["FD"], 1), f"{tag}: FD rate, system {s} (%)", source)
    for m in ("U", "W+WL", "FD"):
        dd = r[f"diff_{m}"]
        num(f"{tag}_diff_{m}", f"{100 * dd['A_minus_B']:+.1f} [{100 * dd['lo']:+.1f}, {100 * dd['hi']:+.1f}]",
            f"{tag}: {a} minus {b}, {m} (pp, 95% participant-cluster bootstrap CI)", source)
    num(f"{tag}_mcnemar_U", f"{r['mcnemar_U']['A_only_U']} vs {r['mcnemar_U']['B_only_U']}, p={r['mcnemar_U']['p_exact']:.4f}",
        f"{tag}: exact McNemar on U (discordant {a}-only vs {b}-only)", source)
    num(f"{tag}_holm", json.dumps({k: round(v, 4) for k, v in r["holm_primary"].items()}), f"{tag}: Holm-adjusted bootstrap p (U, W+WL)", source)
    unit = "forms" if cluster == "form" else "participants"
    num(f"{tag}_n", f"{r['n_questions']} questions, {r['n_participants']} {unit}",
        f"{tag}: paired questions and bootstrap clusters ({unit})", source)


def live_vs_offline(d: pd.DataFrame, res: dict, source: str) -> None:
    """Exploratory: OntoSage's live answer (pass-1 label of the source turn) against its offline answer to the same
    typed question (pass-2 label, system A). This measures how often the answer's category reproduces, not which
    is right (the live turn also had the session's chat history). `source` should reflect pass-1's own label
    source (the weaker of the two, pass-1 and pass-2, since both are mixed into this one number)."""
    import numpy as np
    from study_paths import E6
    src = {}
    for line in (E6 / "inputs" / "comparison_sample.jsonl").open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("source_turn"):
                src[r["qid"]] = r["source_turn"]
    f, live_src = pass1_labels()
    rank = {"HUMAN_AGREED": 3, "AUTHOR_CHECKED": 2, "PROVISIONAL_AI_PRELABEL_BLIND_SHEET": 1}
    source = min((source, norm_source(live_src)), key=lambda s: rank.get(s, 0))
    live = pd.read_csv(f, dtype=str).fillna("").set_index("turn_id")["label"]
    a = d[d.system == "A"].copy()
    a["live"] = a.qid.map(src).map(live)
    a = a.dropna(subset=["live"])
    a = a[a.live != ""]
    if a.empty:
        return
    x, y = a.live.values, a.label.values
    po = float(np.mean(x == y))
    cats = sorted(set(x) | set(y))
    pe = sum(float(np.mean(x == c)) * float(np.mean(y == c)) for c in cats)
    kap = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    good = lambda s: np.isin(s, ["W", "WL"])  # noqa: E731
    pd.crosstab(a.live.rename("live (pass 1)"), a.label.rename("offline (pass 2)")).to_csv(OUT / "live_vs_offline_A.csv")
    res["live_vs_offline_A"] = {"n": int(len(a)), "agreement": po, "kappa": kap,
                                "agreement_good_vs_not": float(np.mean(good(x) == good(y))),
                                "by_set": {qs: float(np.mean(g.live.values == g.label.values))
                                           for qs, g in a.groupby("question_set")},
                                "by_form": {fm: float(np.mean(g.live.values == g.label.values))
                                            for fm, g in a.groupby("form")}}
    num("live_vs_offline_A_agreement", f"{100 * po:.0f}% of {len(a)} (kappa {kap:.2f})",
        "exploratory: OntoSage+'s live answer label vs its offline answer label for the same typed question", source)


def label_table(d: pd.DataFrame, by: list) -> pd.DataFrame:
    t = pd.crosstab([d[c] for c in by], d.label)
    for c in ("W", "WL", "FD", "U", "OT", "PF"):
        if c not in t:
            t[c] = 0
    return t[["W", "WL", "FD", "U", "OT", "PF"]]


CLIENT_TIMEOUT_S = 420      # e6_run.py --timeout default: an answer that took this long was cut off


def timing(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["seconds"] = pd.to_numeric(d.seconds, errors="coerce")
    out = d.groupby("system").seconds.describe(percentiles=[.25, .5, .75, .9]).round(1)
    timed_out = (d.seconds >= CLIENT_TIMEOUT_S) | d.error.astype(str).str.contains("timed out|timeout", case=False)
    out["timeouts"] = timed_out.groupby(d.system).sum().astype(int)
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {n: RQ2L / f"rq2_labels_{n}.csv" for n in ("comparison", "ttask", "stability")}
    have = {n: pd.read_csv(f, dtype={"u_subtypes": str, "alt_label": str, "contested_class": str}).fillna("")
            for n, f in files.items() if f.exists()}
    # ttask and stability have no second-coder sample at all (design: optional author-only review, decision E3,
    # 28 Oct) -- AUTHOR_CHECKED is their permanent ceiling, never a step en route to HUMAN_AGREED, so once every row
    # is author-checked it is as settled as this material will ever be: AUTHOR_CHECKED_SINGLE_CODER (whitelisted,
    # not orange), matching stage5_analysis.py's naming for the same situation. comparison DOES still go through a
    # second-coder merge to HUMAN_AGREED, so its own AUTHOR_CHECKED stays the real, still-provisional label.
    TERMINAL_SINGLE_CODER = {"ttask", "stability"}

    def kind(name, d):                # merge_rq2_labels.py writes the labeller of every row
        for k in ("HUMAN_AGREED", "AUTHOR_CHECKED"):
            if bool(len(d)) and d.labeller.str.startswith(k).all():
                return "AUTHOR_CHECKED_SINGLE_CODER" if k == "AUTHOR_CHECKED" and name in TERMINAL_SINGLE_CODER else k
        return "PROVISIONAL_AI_PRELABEL"
    by_set = {n: kind(n, d) for n, d in have.items()}
    src_comparison, src_ttask, src_stability = (norm_source(by_set.get(n, "PROVISIONAL_AI_PRELABEL"))
                                                 for n in ("comparison", "ttask", "stability"))
    # overall summary only (A4, 28 Oct): no number is ever tagged with this blanket string any more; each one
    # carries the label source of the one set it actually came from (src_comparison / src_ttask / src_stability)
    overall = next(iter(set(by_set.values()))) if by_set and len(set(by_set.values())) == 1 else \
        "MIXED: " + ", ".join(f"{n} {k}" for n, k in by_set.items())
    res = {"label_source": norm_source(overall), "label_source_by_set": by_set}
    if "comparison" in have:
        d = have["comparison"]
        systems = sorted(d.system.unique())
        res["systems_present"] = systems
        compare(d, "A", "B", "comparison_A_vs_B", res, src_comparison)
        for qs in ("T-LIVE", "T-FRESH"):
            compare(d[d.question_set == qs], "A", "B", f"{qs}_A_vs_B", res, src_comparison)
        # specification, per-form results: T-LIVE questions reword 12 task needs, so the two primary differences are
        # re-estimated with intervals that resample the forms instead of the participants
        compare(d[d.question_set == "T-LIVE"], "A", "B", "T-LIVE_A_vs_B_form_clustered", res, src_comparison, cluster="form")
        if "A-minus" in systems:
            compare(d, "A", "A-minus", "comparison_A_vs_Aminus", res, src_comparison)
            compare(d, "A-minus", "B", "comparison_Aminus_vs_B", res, src_comparison)
            for qs in ("T-LIVE", "T-FRESH"):
                compare(d[d.question_set == qs], "A", "A-minus", f"{qs}_A_vs_Aminus", res, src_comparison)
        flip = d.copy()
        m = (flip.contested_class != "") & (flip.alt_label != "")
        flip.loc[m, "label"] = flip.loc[m, "alt_label"]
        compare(flip, "A", "B", "sens_contested_flipped", res, src_comparison)
        if "A-minus" in systems:
            compare(flip, "A", "A-minus", "sens_contested_flipped_A_vs_Aminus", res, src_comparison)
        empty_q = set(d.loc[d.empty_answer == 1, "qid"])
        compare(d[~d.qid.isin(empty_q)], "A", "B", "sens_without_empty_answer_questions", res, src_comparison)
        pf_q = set(d.loc[d.label == "PF", "qid"])        # provider failures that failed again on their one re-run
        if pf_q:
            compare(d[~d.qid.isin(pf_q)], "A", "B", "sens_without_pf_questions", res, src_comparison)
        hi = d.groupby("qid").confidence.apply(lambda s: (s == "high").all())
        compare(d[d.qid.isin(hi[hi].index)], "A", "B", "sens_high_confidence_pairs", res, src_comparison)
        live_vs_offline(d, res, src_comparison)
        label_table(d, ["question_set", "system"]).to_csv(OUT / "comparison_labels_by_set_system.csv")
        label_table(d[d.question_set == "T-LIVE"], ["form", "system"]).to_csv(OUT / "comparison_tlive_labels_by_form.csv")
        timing(d).to_csv(OUT / "comparison_timing_by_system.csv")
        res["empty_answers"] = d.groupby("system").empty_answer.sum().to_dict()
        res["u_subtypes_all"] = {s: d[(d.system == s) & (d.label == "U")].u_subtypes.str.split().explode().value_counts().to_dict()
                                 for s in systems}
    if "ttask" in have:
        t = have["ttask"]
        label_table(t, ["system"]).to_csv(OUT / "ttask_labels_by_system.csv")
        label_table(t, ["form", "system"]).to_csv(OUT / "ttask_labels_by_form.csv")
        t2 = t.copy()
        t2["qid"] = t2.qid + "-r" + t2.run.astype(str)
        res["ttask_pooled_runs"] = pre.analyse(to_rows(t2), systems=("A", "B"))
        res["ttask_stability_label_change"] = pre.stability(to_rows(t))
        timing(t).to_csv(OUT / "ttask_timing_by_system.csv")
        for s in ("A", "B"):
            r = res["ttask_pooled_runs"]["rates"][s]
            num(f"ttask_{s}_U", round(100 * r["U"], 1), f"T-TASK (12 questions x 3 runs): U rate, system {s} (%)", src_ttask)
            num(f"ttask_{s}_WWL", round(100 * r["W+WL"], 1), f"T-TASK: W+WL rate, system {s} (%)", src_ttask)
            num(f"ttask_{s}_stability", round(100 * res["ttask_stability_label_change"].get(s, float("nan")), 1),
                f"T-TASK: share of the 12 questions whose label category changed across 3 runs, system {s} (%)", src_ttask)
    if "stability" in have:
        st = have["stability"]
        res["stability_label_change"] = pre.stability(to_rows(st))
        label_table(st, ["system"]).to_csv(OUT / "stability_labels_by_system.csv")
        for s, v in res["stability_label_change"].items():
            num(f"stability_{s}", round(100 * v, 1), f"stability (30 T-LIVE x 3 runs): share whose label category changed, system {s} (%)", src_stability)
    (OUT / "rq2_results.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    pd.DataFrame(NUMBERS).to_csv(OUT / "numbers_rq2.csv", index=False)
    print(f"RQ2: sets {sorted(have)}; {len(NUMBERS)} numbers")
    for n in NUMBERS:
        print(" ", n["key"], "=", n["value"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
