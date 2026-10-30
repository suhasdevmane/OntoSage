#!/usr/bin/env python3
"""RQ3, the live study: every pre-registered and exploratory analysis on the real data (Analysis_Specification §1-2).

    python rq3_live_analysis.py

Reads ONLY G_Study_Data/deidentified_v1/ (+ pass-1 labels in G_Study_Data/labels/ when present) and writes
F_Analysis/results/rq3/: one CSV per table, rq3_results.json, and rows for results/numbers.csv.

Reuses analysis_rq3.py (the pre-registered script) for the participant-cluster bootstrap (2,000 resamples,
percentile, seed 20261009), the bootstrap p-value, Holm, and the S3 option roles.

Labels. Analyses that need the label of the answer a participant received (E2, C2, reliance, recovery, over-reliance
after U) use labels/answer_labels_agreed.csv (human, adjudicated) if it exists; otherwise
labels/answer_labels_ai_prelabel.csv, and every such output is marked PROVISIONAL_AI_PRELABEL. Never report the
provisional numbers as final.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analysis_rq3 as base  # noqa: E402  (pre-registered helpers)
from study_paths import DEID, RESULTS, SEED, pass1_labels, sha256  # noqa: E402

OUT = RESULTS / "rq3"
SIT = ["S1", "S2", "S3", "S4"]
LAB = ["W", "WL", "FD", "U", "OT", "PF"]
WORST = {"U": 5, "FD": 4, "OT": 3, "WL": 2, "W": 1, "PF": 0}   # spec: U > FD > OT > WL > W
NUMBERS: list = []


def num(key: str, value, desc: str, fmt: str = "{}") -> None:
    NUMBERS.append({"key": key, "value": value, "formatted": (fmt.format(value) if value is not None and value == value else ""),
                    "description": desc, "script": "rq3_live_analysis.py"})


def ci_row(name: str, est, lo, hi, n=None, extra=None) -> dict:
    d = {"quantity": name, "estimate": est, "ci_lo": lo, "ci_hi": hi}
    if n is not None:
        d["n"] = n
    if extra:
        d.update(extra)
    return d


def boot(df, stat, seed=SEED):
    est, lo, hi, draws = base.cluster_boot(df, stat, seed=seed)
    return float(est), float(lo), float(hi), draws


def gee_marginal(df: pd.DataFrame, formula: str = "warranted ~ C(situation, Treatment('S1'))"):
    """GEE logistic (exchangeable within participant); marginal rate per situation with 95% CI (delta on logit)."""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    m = smf.gee(formula, "code", df, family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
    out = {}
    cov = m.cov_params()
    for s in sorted(df.situation.unique()):
        x = pd.Series(0.0, index=m.params.index)
        x["Intercept"] = 1.0
        key = f"C(situation, Treatment('S1'))[T.{s}]"
        if key in x.index:
            x[key] = 1.0
        eta = float(x @ m.params)
        se = float(np.sqrt(x @ cov @ x))
        inv = lambda z: 1 / (1 + np.exp(-z))  # noqa: E731
        out[s] = {"rate": inv(eta), "lo": inv(eta - 1.96 * se), "hi": inv(eta + 1.96 * se)}
    coefs = {k: {"coef": float(v), "se": float(m.bse[k]), "p": float(m.pvalues[k])} for k, v in m.params.items()}
    return out, coefs, m


def load():
    dec = pd.read_csv(DEID / "decisions.csv", dtype={"option": str, "first_option": str})
    par = pd.read_csv(DEID / "participants.csv")
    turns = pd.read_csv(DEID / "turns.csv", dtype=str).fillna("")
    own = pd.read_csv(DEID / "own_questions.csv", dtype=str).fillna("")
    dec["confidence"] = pd.to_numeric(dec.confidence, errors="coerce")
    dec["helpfulness"] = pd.to_numeric(dec.helpfulness, errors="coerce")
    dec["seconds"] = pd.to_numeric(dec.seconds, errors="coerce")
    f, label_source = pass1_labels()       # agreed by two coders, else the author's check, else AI pre-labels
    labels = pd.read_csv(f, dtype=str).fillna("") if f else None
    return dec, par, turns, own, labels, label_source


# ------------------------------------------------------------------ sections
def exclusions(dec, par, turns) -> pd.DataFrame:
    rows = []
    incomplete = par.loc[par.n_decisions < 6, "code"].tolist()
    rows.append({"rule": "1 session not completed (fewer than six decisions)", "pre_registered": 1, "applies": 1,
                 "n_excluded": len(incomplete), "codes": " ".join(incomplete)})
    pf_before = []
    for c, g in turns[turns.provider_failure == "1"].groupby("code"):
        first_goal = dec.loc[(dec.code == c) & (dec.position == 1), "goal_shown_utc"]
        if len(first_goal) and (g.asked_at_utc < first_goal.iloc[0]).any():
            pf_before.append(c)
    rows.append({"rule": "2 system failed before the first task", "pre_registered": 1, "applies": 1,
                 "n_excluded": len(pf_before), "codes": " ".join(pf_before)})
    icfail = par.loc[par.IC1_pass != 1, "code"].tolist()
    rows.append({"rule": "3 instruction check (IC1) failed", "pre_registered": 1, "applies": 1,
                 "n_excluded": len(icfail), "codes": " ".join(icfail)})
    rows.append({"rule": "4 total task time below pilot median x 0.3", "pre_registered": 1, "applies": 0,
                 "n_excluded": 0, "codes": "",
                 "note": "NOT APPLICABLE: no pilot was run (the third author's decision, 19 Oct), so the threshold was never fixed. "
                         "Deviation; a post-hoc sensitivity analysis is reported instead."})
    return pd.DataFrame(rows)


def e1_section(dec, res):
    rows = []
    for s in SIT:
        est, lo, hi, _ = boot(dec, base.rate(s))
        n = int((dec.situation == s).sum())
        k = int(dec.loc[dec.situation == s, "warranted"].sum())
        rows.append(ci_row(s, est, lo, hi, n, {"k_warranted": k, "method": "participant-cluster bootstrap (2,000)"}))
        num(f"E1_{s}_rate", round(100 * est, 1), f"E1 warranted rate {s} (%)", "{:.1f}")
        num(f"E1_{s}_ci", f"{100*lo:.1f}-{100*hi:.1f}", f"E1 {s} 95% bootstrap CI (%)")
        num(f"E1_{s}_k_n", f"{k}/{n}", f"E1 {s} warranted/total")
    est, lo, hi, _ = boot(dec, lambda d: d.warranted.mean())
    rows.append(ci_row("all", est, lo, hi, len(dec), {"k_warranted": int(dec.warranted.sum()),
                                                     "method": "participant-cluster bootstrap (2,000)"}))
    num("E1_all_rate", round(100 * est, 1), "warranted rate, all 180 decisions (%)", "{:.1f}")
    gm, coefs, _ = gee_marginal(dec)
    for s in SIT:
        rows.append(ci_row(s, gm[s]["rate"], gm[s]["lo"], gm[s]["hi"], int((dec.situation == s).sum()),
                           {"method": "GEE logistic, exchangeable within participant (marginal, delta 95% CI)"}))
    res["E1_gee_coefficients"] = coefs
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "e1_warranted_by_situation.csv", index=False)
    return t


def c1_c3(dec, res):
    pv = {}
    est, lo, hi, draws = boot(dec, lambda d: base.rate("S2")(d) - base.rate("S1")(d))
    pv["C1"] = base.boot_p(draws)
    res["C1_S2_minus_S1"] = {"diff": est, "lo": lo, "hi": hi, "p_boot": pv["C1"]}
    num("C1_diff_pp", round(100 * est, 1), "C1: S2 minus S1 warranted rate (percentage points)", "{:.1f}")
    num("C1_ci_pp", f"{100*lo:.1f} to {100*hi:.1f}", "C1 95% bootstrap CI (pp)")
    over = lambda d: d.confidence.mean() / 100 - d.warranted.mean()  # noqa: E731
    est, lo, hi, draws = boot(dec, over)
    pv["C3"] = base.boot_p(draws)
    b_est, b_lo, b_hi, _ = boot(dec, lambda d: ((d.confidence / 100 - d.warranted) ** 2).mean())
    rows = [{"situation": "all", "n": len(dec), "mean_confidence": dec.confidence.mean(), "warranted_rate": dec.warranted.mean(),
             "overconfidence": est, "oc_lo": lo, "oc_hi": hi, "brier": b_est, "brier_lo": b_lo, "brier_hi": b_hi}]
    for s in SIT:
        d = dec[dec.situation == s]
        e, l_, h, _ = boot(dec, lambda x, s=s: over(x[x.situation == s]))
        be, bl, bh, _ = boot(dec, lambda x, s=s: ((x[x.situation == s].confidence / 100 - x[x.situation == s].warranted) ** 2).mean())
        rows.append({"situation": s, "n": len(d), "mean_confidence": d.confidence.mean(), "warranted_rate": d.warranted.mean(),
                     "overconfidence": e, "oc_lo": l_, "oc_hi": h, "brier": be, "brier_lo": bl, "brier_hi": bh})
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "c3_calibration.csv", index=False)
    res["C3"] = {"overconfidence": est, "lo": lo, "hi": hi, "p_boot": pv["C3"], "brier": b_est, "brier_lo": b_lo, "brier_hi": b_hi}
    num("C3_overconfidence_pp", round(100 * est, 1), "C3 overconfidence: mean confidence minus warranted rate (pp)", "{:.1f}")
    num("C3_overconfidence_ci", f"{100*lo:.1f} to {100*hi:.1f}", "C3 overconfidence 95% CI (pp)")
    num("C3_brier", round(b_est, 3), "C3 Brier score (all decisions)", "{:.3f}")
    num("C3_brier_ci", f"{b_lo:.3f}-{b_hi:.3f}", "C3 Brier 95% CI")
    num("mean_confidence", round(dec.confidence.mean(), 1), "mean confidence (0-100), all decisions", "{:.1f}")
    # reliability bins
    bins = [0, 50, 70, 80, 90, 101]
    dec = dec.copy()
    dec["conf_bin"] = pd.cut(dec.confidence, bins=bins, right=False, labels=["0-49", "50-69", "70-79", "80-89", "90-100"])
    rel = dec.groupby("conf_bin", observed=False).agg(n=("warranted", "size"), mean_conf=("confidence", "mean"),
                                                      warranted_rate=("warranted", "mean")).reset_index()
    rel.to_csv(OUT / "c3_reliability_bins.csv", index=False)
    return pv


def s3_section(dec, res):
    roles = base.s3_option_roles()
    s3 = dec[dec.situation == "S3"].copy()
    s3["role"] = [roles.get(f, {}).get(str(o).strip().lower(), "unknown") for f, o in zip(s3.form, s3.option)]
    t = s3.groupby(["form", "role"]).size().unstack(fill_value=0)
    for c in ("absence_understood", "no_conclusion", "accepted_value"):
        if c not in t.columns:
            t[c] = 0
    t = t[["absence_understood", "no_conclusion", "accepted_value"]]
    t.loc["all"] = t.sum()
    t.to_csv(OUT / "s3_option_split.csv")
    res["S3"] = t.loc["all"].to_dict()
    for c, v in t.loc["all"].items():
        num(f"S3_{c}", int(v), f"S3 decisions: {c} (of {int(t.loc['all'].sum())})")
    return t


def per_form(dec):
    rows = []
    for f, g in dec.groupby("form"):
        opts = g.option.value_counts().to_dict()
        rows.append({"form": f, "situation": f[:2], "n": len(g), "k_warranted": int(g.warranted.sum()),
                     "warranted_rate": g.warranted.mean(), "warranted_options": g.warranted_options.iloc[0],
                     **{f"opt_{k}": int(opts.get(k, 0)) for k in "abcdef"},
                     "median_seconds": g.seconds.median(), "mean_confidence": g.confidence.mean(),
                     "n_timed_out": int(g.timed_out.sum())})
    t = pd.DataFrame(rows).sort_values("form")
    t.to_csv(OUT / "per_form.csv", index=False)
    return t


def sensitivity(dec, par):
    sets = {
        "primary (all 180)": dec,
        "excl. decisions with no answer before deciding": dec[dec.answer_timing.isin(["answered", "answered_earlier_question"])],
        "excl. P04 and P12 (>=2 tasks without an answer)": dec[~dec.code.isin(["P04", "P12"])],
        "excl. timed-out tasks (>9 min)": dec[dec.timed_out == 0],
        "first question asked with options hidden (goal page)": dec[dec.first_question_on == "goal"],
        "first question asked with options visible (decision page)": dec[dec.first_question_on == "decision"],
    }
    rows = []
    for name, d in sets.items():
        for s in SIT + ["all"]:
            stat = (lambda x: x.warranted.mean()) if s == "all" else base.rate(s)
            if s != "all" and (d.situation == s).sum() == 0:
                continue
            est, lo, hi, _ = boot(d, stat)
            rows.append({"set": name, "situation": s, "n": int(len(d) if s == "all" else (d.situation == s).sum()),
                         "rate": est, "lo": lo, "hi": hi, "exploratory": int(name != "primary (all 180)")})
    t = pd.DataFrame(rows)
    t.to_csv(OUT / "sensitivity_e1.csv", index=False)
    return t


def exploratory(dec, res):
    # evidence use
    rows = []
    for e, g in dec.groupby("evidence_opened"):
        est, lo, hi, _ = boot(dec, lambda d, e=e: d.loc[d.evidence_opened == e, "warranted"].mean())
        rows.append({"evidence_opened": e, "n": len(g), "warranted_rate": est, "lo": lo, "hi": hi})
    pd.DataFrame(rows).to_csv(OUT / "evidence_use.csv", index=False)
    num("evidence_opened_yes_n", int((dec.evidence_opened == "yes").sum()), "decisions after opening the Evidence section (of 180)")
    # task position
    rows = []
    for p, g in dec.groupby("position"):
        rows.append({"position": p, "n": len(g), "warranted_rate": g.warranted.mean(), "median_seconds": g.seconds.median()})
    pd.DataFrame(rows).to_csv(OUT / "task_position.csv", index=False)
    try:
        # every S3 decision was warranted (complete separation): with S3 in, the model diverges and returns NaN
        _, coefs, _ = gee_marginal(dec[dec.situation != "S3"], "warranted ~ C(situation, Treatment('S1')) + position")
        res["E1_gee_with_position"] = {"note": "exploratory; fitted without S3 (all 30 S3 decisions warranted)", **coefs}
        num("position_coef_logodds", f"{coefs['position']['coef']:.3f} (SE {coefs['position']['se']:.3f}, p={coefs['position']['p']:.3f})",
            "task position (1-6) in the E1 GEE without S3, log-odds per position (exploratory)")
    except Exception as exc:  # noqa: BLE001
        res["E1_gee_with_position"] = {"error": str(exc)}
    # answer timing x warranted
    t = dec.groupby("answer_timing").agg(n=("warranted", "size"), warranted_rate=("warranted", "mean")).reset_index()
    t.to_csv(OUT / "answer_timing.csv", index=False)
    # where the first question was asked
    t = dec.groupby("first_question_on").agg(n=("warranted", "size"), warranted_rate=("warranted", "mean")).reset_index()
    t.to_csv(OUT / "first_question_page.csv", index=False)
    num("first_q_options_visible_n", int((dec.first_question_on == "decision").sum()),
        "tasks whose first question was asked on the decision page (options visible)")
    num("first_q_goal_n", int((dec.first_question_on == "goal").sum()), "tasks whose first question was asked on the goal page")
    # helpfulness / would act x warranted (decision-based)
    hw = dec.groupby("warranted").agg(n=("helpfulness", "size"), mean_help=("helpfulness", "mean"),
                                       would_act_rate=("would_act", "mean")).reset_index()
    hw.to_csv(OUT / "helpfulness_would_act_by_warranted.csv", index=False)
    ct = pd.crosstab(dec.would_act, dec.warranted).rename(index={0: "would check", 1: "would act"},
                                                         columns={0: "unwarranted", 1: "warranted"})
    ct.to_csv(OUT / "would_act_x_warranted.csv")
    num("would_act_unwarranted_n", int(((dec.would_act == 1) & (dec.warranted == 0)).sum()),
        "decisions that were unwarranted AND the participant would act without checking")
    num("would_act_rate", round(100 * dec.would_act.mean(), 1), "share of decisions the participant would act on without checking (%)", "{:.1f}")


def usability(par, dec, res):
    p = par.copy()
    items = pd.DataFrame({f"SUS{i}": pd.to_numeric(p[f"SUS{i}"], errors="coerce") for i in range(1, 11)})
    rec = pd.DataFrame({c: (items[c] - 1) if int(c[3:]) % 2 == 1 else (5 - items[c]) for c in items})

    def alpha(m: pd.DataFrame) -> float:
        k = m.shape[1]
        return float(k / (k - 1) * (1 - m.var(ddof=1).sum() / m.sum(axis=1).var(ddof=1)))

    rng = np.random.default_rng(SEED)
    sus = p.sus_score.astype(float).values
    bs = np.array([rng.choice(sus, len(sus)).mean() for _ in range(base.B)])
    tr = p.trust_mean.astype(float).values
    bt = np.array([rng.choice(tr, len(tr)).mean() for _ in range(base.B)])
    ef = pd.to_numeric(p.EF1, errors="coerce").values
    be = np.array([np.median(rng.choice(ef, len(ef))) for _ in range(base.B)])
    trust_items = pd.DataFrame({f"TR{i}": pd.to_numeric(p[f"TR{i}"], errors="coerce") for i in (1, 2, 3)})
    mean_sus = float(sus.mean())
    adj = {"Worst imaginable": 12.5, "Awful": 20.3, "Poor": 35.7, "OK": 50.9, "Good": 71.4, "Excellent": 85.5, "Best imaginable": 90.9}
    # position between the adjectives' MEAN scores (Bangor et al. 2009, Table 3), not the nearest adjective: nearest
    # would call 79.2 "Excellent", which is a claim the scale does not make
    below = max((k for k in adj if adj[k] <= mean_sus), key=lambda k: adj[k], default=None)
    above = min((k for k in adj if adj[k] > mean_sus), key=lambda k: adj[k], default=None)
    label = (f"between the mean scores for '{below}' ({adj[below]}) and '{above}' ({adj[above]})" if below and above
             else f"at or beyond '{below or above}'")
    accept = "acceptable" if mean_sus >= 70 else ("marginal" if mean_sus >= 50 else "not acceptable")
    share = dec.groupby("code").warranted.mean().reindex(p.code).values
    from scipy.stats import spearmanr
    rho = float(spearmanr(sus, share).statistic)
    br = []
    for _ in range(base.B):
        i = rng.integers(0, len(sus), len(sus))
        r_ = spearmanr(sus[i], share[i]).statistic
        br.append(r_)
    br = np.array(br, dtype=float)
    u = {"sus_mean": mean_sus, "sus_lo": float(np.percentile(bs, 2.5)), "sus_hi": float(np.percentile(bs, 97.5)),
         "sus_median": float(np.median(sus)), "sus_min": float(sus.min()), "sus_max": float(sus.max()),
         "sus_sd": float(sus.std(ddof=1)), "sus_alpha": alpha(rec), "sus_bangor_nearest_adjective": label,
         "sus_acceptability_range": accept, "trust_mean": float(tr.mean()), "trust_lo": float(np.percentile(bt, 2.5)),
         "trust_hi": float(np.percentile(bt, 97.5)), "trust_alpha": alpha(trust_items), "effort_median": float(np.median(ef)),
         "effort_lo": float(np.percentile(be, 2.5)), "effort_hi": float(np.percentile(be, 97.5)), "effort_mean": float(ef.mean()),
         "spearman_sus_vs_warranted_share": rho, "spearman_lo": float(np.nanpercentile(br, 2.5)),
         "spearman_hi": float(np.nanpercentile(br, 97.5)), "n": int(len(p))}
    pd.DataFrame([u]).to_csv(OUT / "usability_trust_effort.csv", index=False)
    p[["code", "sus_score", "trust_mean", "EF1"]].assign(warranted_share=share).to_csv(OUT / "per_participant_scores.csv", index=False)
    pd.DataFrame({"item": [f"SUS{i}" for i in range(1, 11)], "mean_raw": items.mean().values, "mean_contribution": rec.mean().values}
                 ).to_csv(OUT / "sus_items.csv", index=False)
    res["usability"] = u
    num("SUS_mean", round(mean_sus, 1), "SUS mean (0-100)", "{:.1f}")
    num("SUS_ci", f"{u['sus_lo']:.1f}-{u['sus_hi']:.1f}", "SUS 95% bootstrap CI")
    num("SUS_median", round(u["sus_median"], 1), "SUS median", "{:.1f}")
    num("SUS_range", f"{u['sus_min']:.1f}-{u['sus_max']:.1f}", "SUS range")
    num("SUS_alpha", round(u["sus_alpha"], 2), "SUS Cronbach's alpha (10 items)", "{:.2f}")
    num("SUS_adjective", label, "SUS position on the Bangor et al. (2009) adjective means (context only)")
    num("trust_mean", round(u["trust_mean"], 2), "trust mean (TR1-TR3, 1-7)", "{:.2f}")
    num("trust_ci", f"{u['trust_lo']:.2f}-{u['trust_hi']:.2f}", "trust 95% bootstrap CI")
    num("trust_alpha", round(u["trust_alpha"], 2), "trust Cronbach's alpha (3 items)", "{:.2f}")
    num("effort_median", u["effort_median"], "mental effort median (EF1, 1-9)")
    num("effort_ci", f"{u['effort_lo']:.1f}-{u['effort_hi']:.1f}", "mental effort median 95% bootstrap CI")
    num("spearman_sus_warranted", round(rho, 2), "Spearman rho: SUS vs share of warranted decisions (exploratory)", "{:.2f}")
    num("spearman_sus_warranted_ci", f"{u['spearman_lo']:.2f} to {u['spearman_hi']:.2f}", "Spearman rho 95% bootstrap CI")


def behaviour(dec, par, turns, own, res):
    tq = turns[turns.role == "task"]
    rows = {"participants": len(par), "decisions": len(dec), "questions_total": len(turns),
            "task_questions": len(tq), "own_question_turns": int((turns.role == "own_question").sum()),
            "practice_turns": int((turns.role == "practice").sum()),
            "tasks_with_question": int((dec.n_questions_task > 0).sum()),
            "median_questions_per_task": float(dec.n_questions_task.median()),
            "mean_questions_per_task": float(dec.n_questions_task.mean()),
            "median_chats_per_participant": float(par.n_chats.median()),
            "participants_one_or_two_chats": int((par.n_chats <= 2).sum()),
            "session_minutes_median": float(par.session_minutes.median()),
            "session_minutes_min": float(par.session_minutes.min()), "session_minutes_max": float(par.session_minutes.max()),
            "task_seconds_median": float(dec.seconds.median()), "task_seconds_q1": float(dec.seconds.quantile(.25)),
            "task_seconds_q3": float(dec.seconds.quantile(.75)), "timed_out_tasks": int(dec.timed_out.sum()),
            "own_questions_written": len(own), "own_questions_added_with_button": int(own.added_with_button.astype(int).sum()),
            "own_questions_asked_live": int((own.asked_live_order != "").sum()),
            "answer_seconds_median": float(pd.to_numeric(turns.answer_seconds, errors="coerce").median()),
            "answer_seconds_p90": float(pd.to_numeric(turns.answer_seconds, errors="coerce").quantile(.9)),
            "provider_failures": int((turns.provider_failure == "1").sum()),
            "answers_with_evidence_panel": int((turns.evidence_panel_present == "1").sum())}
    by_sit = dec.groupby("situation").agg(n=("seconds", "size"), median_seconds=("seconds", "median"),
                                          mean_questions=("n_questions_task", "mean"),
                                          share_no_question=("n_questions_task", lambda x: (x == 0).mean())).reset_index()
    by_sit.to_csv(OUT / "behaviour_by_situation.csv", index=False)
    pd.DataFrame([rows]).to_csv(OUT / "behaviour_summary.csv", index=False)
    res["behaviour"] = rows
    for k, v in rows.items():
        num(f"beh_{k}", round(v, 1) if isinstance(v, float) else v, f"behaviour: {k.replace('_', ' ')}")
    # own-question live answers
    ol = own[own.asked_live_order != ""]
    t = pd.crosstab(ol.answered, ol.would_rely)
    t.to_csv(OUT / "own_questions_live_answers.csv")


def background(par):
    rows = []
    roles = par.BG1.fillna("").str.split(";").explode()
    for k, v in roles[roles != ""].value_counts().items():
        rows.append({"item": "BG1 relationship (multi)", "value": k, "n": int(v)})
    for c, name in (("BG2", "building data use"), ("BG3", "AI chat use"), ("BG4", "Building A familiarity"),
                    ("BG5", "charts comfort (1-5)"), ("BG6", "age band")):
        for k, v in par[c].astype(str).value_counts().items():
            rows.append({"item": f"{c} {name}", "value": k, "n": int(v)})
    for k, v in par.version.value_counts().sort_index().items():
        rows.append({"item": "form version", "value": k, "n": int(v)})
    for k, v in par["mode"].value_counts().items():
        rows.append({"item": "mode", "value": k, "n": int(v)})
    pd.DataFrame(rows).to_csv(OUT / "table1_sample.csv", index=False)


def failure_kind(warranted: int, failure: str) -> str:
    """The decision in three kinds plus warranted, from the key's failure text for the option chosen."""
    if warranted:
        return "warranted"
    f = failure.lower()
    if f.startswith("under-reliance"):
        return "under-reliance (could not find out)"
    if "false absence" in f or "false limit" in f:
        return "false absence or limit"
    return "accepted an unsupported claim"


def e2_sensitivity(d: pd.DataFrame, labels: pd.DataFrame, source: str) -> None:
    """E2 under three label variants: as labelled; contested classes flipped to their alternative; high confidence only."""
    lab = labels.set_index("turn_id")
    variants = {"as labelled": lab["label"].to_dict()}
    if "alt_label" in lab.columns:
        flip = lab["label"].copy()
        m = (lab["contested_class"] != "") & (lab["alt_label"] != "")
        flip[m] = lab.loc[m, "alt_label"]
        variants["contested classes flipped (S2-1 headline -> WL, S2-2 generic decline -> WL)"] = flip.to_dict()
        m2 = lab["alt_label"] != ""
        flip2 = lab["label"].copy()
        flip2[m2] = lab.loc[m2, "alt_label"]
        variants["every answer with a noted alternative flipped"] = flip2.to_dict()
    conf = lab["confidence"].to_dict() if "confidence" in lab.columns else {}
    rows = []
    for name, mp in variants.items():
        x = d.copy()
        x["recv"] = x.received_turn.map(mp).fillna("none")
        for L in LAB + ["none"]:
            sub = x[x.recv == L]
            if len(sub):
                rows.append({"variant": name, "label": L, "n": len(sub), "k_warranted": int(sub.warranted.sum()),
                             "rate": sub.warranted.mean()})
    x = d.copy()
    x["recv"] = x.received_turn.map(variants["as labelled"]).fillna("none")
    x = x[x.received_turn.map(conf).fillna("") == "high"]
    for L in LAB:
        sub = x[x.recv == L]
        if len(sub):
            rows.append({"variant": "received answer labelled with high confidence only", "label": L, "n": len(sub),
                         "k_warranted": int(sub.warranted.sum()), "rate": sub.warranted.mean()})
    t = pd.DataFrame(rows)
    t["label_source"] = source
    t.to_csv(OUT / "e2_sensitivity.csv", index=False)


def own_questions_vs_labels(own: pd.DataFrame, turns: pd.DataFrame, labels: pd.DataFrame, source: str, res: dict) -> None:
    """Each own question asked live, linked to the answers it received; the participant's OL1a (answered?) and
    OL1b (would rely?) against the label of the LAST answer to it. Linking: every own-question turn goes to the
    participant's own question it is most similar to (difflib ratio >= 0.45); unmatched turns are counted."""
    import difflib
    lab = labels.set_index("turn_id")["label"].to_dict()
    t = turns[turns.role == "own_question"].copy()
    t["label"] = t.turn_id.map(lab).fillna("")
    asked = own[own.asked_live_order != ""].copy()
    link, unmatched = {}, 0
    for c, g in t.groupby("code"):
        oq = asked[asked.code == c]
        for r in g.itertuples():
            best, score = None, 0.0
            for o in oq.itertuples():
                s = difflib.SequenceMatcher(None, r.question.lower(), o.question.lower()).ratio()
                if s > score:
                    best, score = o.slot, s
            if best and score >= 0.45:
                link.setdefault((c, best), []).append((r.asked_at_utc, r.label))
            else:
                unmatched += 1
    rows = []
    for o in asked.itertuples():
        got = sorted(link.get((o.code, o.slot), []))
        last = got[-1][1] if got else "not linked"
        worst = max((x[1] for x in got), key=lambda x: WORST.get(x, -1)) if got else "not linked"
        rows.append({"code": o.code, "slot": o.slot, "answered": o.answered, "would_rely": o.would_rely,
                     "n_turns_linked": len(got), "label_last": last, "label_worst": worst})
    d = pd.DataFrame(rows)
    d.to_csv(OUT / "own_questions_with_labels.csv", index=False)
    ct1 = pd.crosstab(d.label_last, d.answered)
    ct2 = pd.crosstab(d.label_last, d.would_rely)
    ct1.to_csv(OUT / "own_questions_answered_x_label.csv")
    ct2.to_csv(OUT / "own_questions_would_rely_x_label.csv")
    pd.crosstab(t.label, t.code.map(lambda _: "own-question answers")).to_csv(OUT / "own_question_answer_labels.csv")
    bad = d.label_last.isin(["FD", "U", "OT"])
    res["own_questions"] = {
        "asked_live": len(d), "own_question_turns": len(t), "turns_not_linked": unmatched,
        "linked": int((d.n_turns_linked > 0).sum()), "labels_of_all_own_question_answers": t.label.value_counts().to_dict(),
        "said_answered_yes_when_last_answer_unwarranted": int((bad & (d.answered == "Yes")).sum()),
        "would_rely_yes_when_last_answer_unwarranted": int((bad & (d.would_rely == "Yes")).sum()),
        "last_answer_unwarranted": int(bad.sum()), "label_source": source}
    num("own_asked_live", len(d), "own questions asked live (with OL1 ratings)")
    num("own_unwarranted_but_answered_yes", res["own_questions"]["said_answered_yes_when_last_answer_unwarranted"],
        "own questions whose last answer was FD/U/OT but which the participant rated 'answered: Yes'")
    num("own_unwarranted_but_rely_yes", res["own_questions"]["would_rely_yes_when_last_answer_unwarranted"],
        "own questions whose last answer was FD/U/OT but which the participant would rely on")


def label_based(dec, turns, labels, source, res, pv):
    """E2, C2, reliance matrix, over-reliance after U, recovery, helpfulness x label. Needs pass-1 labels."""
    if labels is None:
        res["label_based"] = {"status": "no labels yet"}
        return pv
    lab = labels.set_index("turn_id")["label"].to_dict()
    tlab = turns.assign(label=turns.turn_id.map(lab).fillna(""))
    d = dec.copy()
    d["answer_received"] = d.received_turn.map(lab).fillna("")
    d.loc[d.received_turn.isna() | (d.received_turn == ""), "answer_received"] = "none"
    worst = {}
    for (c, pos), g in tlab[tlab.role == "task"].groupby(["code", "task_position"]):
        ls = [x for x in g.label if x]
        worst[(c, int(pos))] = max(ls, key=lambda x: WORST.get(x, -1)) if ls else "none"
    d["answer_worst"] = [worst.get((c, int(p)), "none") for c, p in zip(d.code, d.position)]
    first = tlab.set_index("turn_id")["label"].to_dict()
    d["answer_first"] = d.first_question_turn.map(first).fillna("none")
    d.to_csv(OUT / "decisions_with_labels.csv", index=False)
    # E2
    rows = []
    for which in ("answer_received", "answer_worst"):
        for L in LAB + ["none"]:
            sub = d[d[which] == L]
            if len(sub) == 0:
                continue
            if len(sub) < 10:
                rows.append({"basis": which, "label": L, "n": len(sub), "k_warranted": int(sub.warranted.sum()),
                             "rate": None, "lo": None, "hi": None, "note": "n<10: count only"})
                continue
            est, lo, hi, _ = boot(d, lambda x, L=L, w=which: x.loc[x[w] == L, "warranted"].mean())
            rows.append({"basis": which, "label": L, "n": len(sub), "k_warranted": int(sub.warranted.sum()),
                         "rate": est, "lo": lo, "hi": hi, "note": ""})
    e2 = pd.DataFrame(rows)
    e2["label_source"] = source
    e2.to_csv(OUT / "e2_by_answer_received.csv", index=False)
    e2_sensitivity(d, labels, source)
    # what participants chose, by the answer they received: warranted, or which kind of failure (the key's own words)
    d["decision_kind"] = [failure_kind(w, f) for w, f in zip(d.warranted, d.failure.fillna(""))]
    ct = pd.crosstab(d.answer_received, d.decision_kind)
    ct.to_csv(OUT / "decision_kind_by_answer_received.csv")
    pd.crosstab([d.situation, d.answer_received], d.decision_kind).to_csv(OUT / "decision_kind_by_situation_and_answer.csv")
    res["decision_kind_by_answer_received"] = {str(k): v for k, v in ct.to_dict(orient="index").items()}
    # C2 helpfulness WL - FD
    def hd(x):
        return x.loc[x.answer_received == "WL", "helpfulness"].mean() - x.loc[x.answer_received == "FD", "helpfulness"].mean()
    if (d.answer_received == "WL").sum() and (d.answer_received == "FD").sum():
        est, lo, hi, draws = boot(d, hd)
        pv["C2"] = base.boot_p(draws)
        res["C2_helpfulness_WL_minus_FD"] = {"diff": est, "lo": lo, "hi": hi, "p_boot": pv["C2"],
                                              "n_WL": int((d.answer_received == "WL").sum()), "n_FD": int((d.answer_received == "FD").sum()),
                                              "label_source": source}
    hl = d.groupby("answer_received").helpfulness.describe()
    hl["label_source"] = source
    hl.to_csv(OUT / "c2_helpfulness_by_answer_received.csv")
    dist = pd.crosstab(d.answer_received, d.helpfulness)
    dist.to_csv(OUT / "c2_helpfulness_distribution.csv")
    # reliance matrix: answer received warranted (W/WL) vs unwarranted (U/FD/OT), x would act
    d["answer_ok"] = d.answer_received.map(lambda x: "warranted answer (W/WL)" if x in ("W", "WL")
                                           else ("unwarranted answer (U/FD/OT)" if x in ("U", "FD", "OT") else "no answer / PF"))
    rm = pd.crosstab(d.answer_ok, d.would_act.map({1: "would act", 0: "would check"}))
    rm.to_csv(OUT / "reliance_matrix.csv")
    after_u = d[d.answer_received == "U"]
    k_u, n_u = int((after_u.would_act == 1).sum()), len(after_u)
    # specification: a count with an exact interval (Clopper-Pearson), never a rate when n < 10
    from scipy.stats import beta
    lo_u = float(beta.ppf(0.025, k_u, n_u - k_u + 1)) if k_u > 0 else 0.0
    hi_u = float(beta.ppf(0.975, k_u + 1, n_u - k_u)) if k_u < n_u else 1.0
    res["over_reliance_after_U"] = {"n_U_received": n_u, "would_act_yes": k_u,
                                    "exact_95ci": [lo_u, hi_u] if n_u >= 10 else None,
                                    "warranted_anyway": int(after_u.warranted.sum()), "label_source": source}
    num("rel_would_act_after_U", f"{k_u} of {n_u}" + (f" [{100 * lo_u:.0f}%, {100 * hi_u:.0f}%]" if n_u >= 10 else ""),
        "would act without checking after an answer labelled U (count, exact Clopper-Pearson 95% interval)")
    # recovery: first answer FD/WL/U -> follow-up asked? final decision warranted?
    rec = d[d.answer_first.isin(["FD", "WL", "U"])]
    rows = []
    for L, g in rec.groupby("answer_first"):
        rows.append({"first_answer": L, "n_tasks": len(g), "asked_follow_up": int((g.n_questions_task > 1).sum()),
                     "final_warranted": int(g.warranted.sum()), "follow_up_and_warranted": int(((g.n_questions_task > 1) & (g.warranted == 1)).sum())})
    rt = pd.DataFrame(rows)
    rt["label_source"] = source
    rt.to_csv(OUT / "recovery.csv", index=False)
    # label distribution of all task answers
    ldist = tlab[tlab.role == "task"].groupby(["situation", "label"]).size().unstack(fill_value=0)
    ldist.to_csv(OUT / "task_answer_label_distribution.csv")
    res["label_source"] = source
    return pv


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    dec, par, turns, own, labels, label_source = load()
    res = {"input_sha256": {f: sha256(DEID / f) for f in ("decisions.csv", "participants.csv", "turns.csv", "own_questions.csv")},
           "n_participants": int(dec.code.nunique()), "n_decisions": len(dec)}
    exclusions(dec, par, turns).to_csv(OUT / "exclusions.csv", index=False)
    e1_section(dec, res)
    pv = c1_c3(dec, res)
    s3_section(dec, res)
    per_form(dec)
    sensitivity(dec, par)
    exploratory(dec, res)
    usability(par, dec, res)
    behaviour(dec, par, turns, own, res)
    background(par)
    pv = label_based(dec, turns, labels, label_source, res, pv)
    if labels is not None:
        own_questions_vs_labels(own, turns, labels, label_source, res)
    res["raw_p"] = pv
    res["holm_p"] = base.holm(pv)
    res["holm_note"] = ("Holm across C1, C2, C3, as in the study plan (written before the first session, not filed)"
                        if "C2" in pv else
                        "C2 needs pass-1 labels: Holm here is across C1 and C3 only (PROVISIONAL)")
    if "C2" in pv:
        res["holm_note"] += f"; C2 label source: {label_source}"
    for k, v in res["holm_p"].items():
        num(f"holm_p_{k}", round(v, 4), f"Holm-adjusted p for {k}", "{:.4f}")
    (OUT / "rq3_results.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    nums = pd.DataFrame(NUMBERS)
    nums["label_source"] = [label_source if k.startswith(("E2", "C2", "rel", "rec")) else "" for k in nums.key]
    nums.to_csv(OUT / "numbers_rq3.csv", index=False)
    print(f"RQ3 done: {len(NUMBERS)} numbers; label source: {label_source}")
    e1 = pd.read_csv(OUT / "e1_warranted_by_situation.csv")
    print(e1[e1.method.str.startswith("participant")][["quantity", "estimate", "ci_lo", "ci_hi", "n", "k_warranted"]].round(3).to_string(index=False))
    print("C1:", {k: round(v, 3) for k, v in res["C1_S2_minus_S1"].items()}, "| C3:", {k: round(v, 3) for k, v in res["C3"].items()})
    print("Holm:", res["holm_p"], "|", res["holm_note"])
    print("SUS:", round(res["usability"]["sus_mean"], 1), [round(res["usability"]["sus_lo"], 1), round(res["usability"]["sus_hi"], 1)],
          "alpha", round(res["usability"]["sus_alpha"], 2), res["usability"]["sus_bangor_nearest_adjective"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
