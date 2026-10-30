#!/usr/bin/env python3
"""RQ3 figures on the answers participants received (plan 04 section 3, Fig 5 and the answer-label context).

    python figures/fig_rq3_answers.py

Reads results/rq3/ (rq3_live_analysis.py) and G_Study_Data/labels/. Writes figures/out/:
  fig5_e2                       (a) correct decisions by the label of the last answer before deciding, 95% bootstrap
                                CI; (b) what was decided after each label (100% bars)
  fig5alt_e2_worst              the same, by the WORST answer in the task (pre-registered sensitivity)
  fig5alt_e2_sensitivity        E2 under four label variants (as labelled, contested classes flipped, every noted
                                alternative flipped, high-confidence labels only)
  figA_answer_labels_by_form    the label of every task answer, per form
Every figure that rests on labels carries a PROVISIONAL stamp while the labels are the AI pre-labels; the stamp
disappears by itself once results were computed from labels/answer_labels_agreed.csv.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import analysis_rq3 as base  # noqa: E402
import fig_style as fs  # noqa: E402
from rq3_live_analysis import failure_kind  # noqa: E402
from study_paths import RESULTS, pass1_labels  # noqa: E402

OUT = HERE / "out"
R = RESULTS / "rq3"
ORDER = ["W", "WL", "FD", "U", "OT", "none"]


def stamp(fig, source: str) -> None:
    if source != "HUMAN_AGREED":
        fig.text(0.995, 0.998, "PROVISIONAL: labels checked by the first author only; agreement with a second coder "
                 "pending" if source == "AUTHOR_CHECKED" else
                 "PROVISIONAL: answer labels are AI pre-labels (pass 1), not yet human-coded",
                 ha="right", va="top", fontsize=5.8, color=fs.OKABE["vermillion"], style="italic")


def decisions() -> tuple:
    d = pd.read_csv(R / "decisions_with_labels.csv", dtype={"option": str})
    d["kind"] = [failure_kind(w, f) for w, f in zip(d.warranted, d.failure.fillna(""))]
    roles = base.s3_option_roles()
    nc = [(s == "S3" and roles.get(f, {}).get(str(o).strip().lower()) == "no_conclusion")
          for s, f, o in zip(d.situation, d.form, d.option)]
    d.loc[nc, "kind"] = "warranted, no conclusion"
    e2 = pd.read_csv(R / "e2_by_answer_received.csv")
    return d, e2, (e2.label_source.iloc[0] if len(e2) else "none")


def panel_rate(ax, e2: pd.DataFrame, basis: str) -> None:
    t = e2[e2.basis == basis].set_index("label").reindex(ORDER).dropna(subset=["n"])
    x = np.arange(len(t))
    for i, (lab, r) in enumerate(t.iterrows()):
        n, k = int(r.n), int(r.k_warranted)
        rate = k / n
        if pd.isna(r.rate):        # n < 10: the plan reports a count only, so no interval and a hollow bar
            ax.bar(i, rate, width=0.6, facecolor="white", edgecolor=fs.SINGLE, linewidth=1.0, zorder=2)
        else:
            ax.bar(i, rate, width=0.6, color=fs.SINGLE, zorder=2)
            ax.errorbar(i, rate, yerr=[[rate - r.lo], [r.hi - rate]], fmt="none", ecolor=fs.INK, elinewidth=0.9,
                        capsize=2.5, zorder=3)
        ax.text(i, 1.03, f"{k}/{n}", ha="center", va="bottom", fontsize=5.7, color=fs.INK2)
    ax.set_xticks(x)
    ax.set_xticklabels([fs.LABEL_SHORT[lab] for lab in t.index])
    ax.set_ylim(0, 1.1)
    ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_ylabel(fs.CORRECT)
    ax.set_xlabel("last answer before deciding" if basis == "answer_received" else "worst answer in the task")
    fs.hgrid(ax)


def panel_kinds(ax, d: pd.DataFrame, col: str) -> None:
    labs = [lab for lab in ORDER if (d[col] == lab).any()]
    ct = pd.crosstab(d[col], d.kind).reindex(labs).fillna(0)
    tot = ct.sum(axis=1).values
    y = np.arange(len(labs))
    left = np.zeros(len(labs))
    for k in fs.DECISION_ORDER:
        v = ct[k].values if k in ct else np.zeros(len(labs))
        w = v / tot
        ax.barh(y, w, left=left, height=0.7, color=fs.DECISION_COL[k], edgecolor="white", linewidth=0.8,
                label=fs.DECISION_NAME[k])
        for yi, li, wi, vi in zip(y, left, w, v):
            if vi >= 2 and wi >= 0.1:
                ax.text(li + wi / 2, yi, f"{int(vi)}", ha="center", va="center", fontsize=6.2,
                        color="white" if k in ("warranted", "accepted an unsupported claim") else fs.INK)
        left += w
    ax.set_yticks(y)
    ax.set_yticklabels([fs.LABEL_SHORT[lab] for lab in labs])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, .5, 1])
    ax.set_xticklabels(["0", "50%", "100%"])
    ax.set_xlabel("share of those decisions")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    for yi, n in zip(y, tot):
        ax.text(1.02, yi, f"n={int(n)}", va="center", fontsize=6.2, color=fs.INK2)


def fig_e2(d, e2, src, basis: str, name: str) -> None:
    col = "answer_received" if basis == "answer_received" else "answer_worst"
    fig, (a, b) = fs.plt.subplots(1, 2, figsize=(fs.FULL, 2.55), gridspec_kw={"width_ratios": [1.15, 1.05], "wspace": 0.36})
    panel_rate(a, e2, basis)
    fs.panel_label(a, "(a)")
    panel_kinds(b, d, col)
    fs.panel_label(b, "(b)")
    h, lab = b.get_legend_handles_labels()
    fig.subplots_adjust(bottom=0.27)
    fig.legend(h, lab, loc="upper center", bbox_to_anchor=(0.52, 0.075), ncol=2, handlelength=1.0, columnspacing=1.2)
    stamp(fig, src)
    fs.save(fig, OUT, name)


def fig_sensitivity(src) -> None:
    s = pd.read_csv(R / "e2_sensitivity.csv")
    variants = list(dict.fromkeys(s.variant))
    short = {v: v.split(" (")[0] for v in variants}
    labs = [lab for lab in ORDER if lab in set(s.label)]
    fig, ax = fs.plt.subplots(figsize=(fs.HALF * 1.25, 2.3))
    marks = ["o", "s", "D", "^"]
    for j, v in enumerate(variants):
        t = s[s.variant == v].set_index("label").reindex(labs)
        xs = np.arange(len(labs)) + (j - 1.5) * 0.15
        ax.scatter(xs, t.rate, marker=marks[j % 4], s=16, facecolor="white" if j else fs.SINGLE, edgecolor=fs.SINGLE,
                   linewidth=0.9, label=short[v], zorder=3)
    ax.set_xticks(np.arange(len(labs)))
    ax.set_xticklabels([fs.LABEL_SHORT[lab] for lab in labs])
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_ylabel(fs.CORRECT)
    ax.set_xlabel("last answer before deciding")
    fs.hgrid(ax)
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), handletextpad=0.3, fontsize=6.2)
    stamp(fig, src)
    fs.save(fig, OUT, "fig5alt_e2_sensitivity")


def fig_labels_by_form(src) -> None:
    lab = pd.read_csv(pass1_labels()[0], dtype=str).fillna("")
    lab = lab[lab.role == "task"]
    forms = sorted(lab.form.unique(), key=lambda x: (x[:2], x))
    ct = pd.crosstab(lab.form, lab.label).reindex(forms).fillna(0)
    tot = ct.sum(axis=1).values
    gap = {fm for i, fm in enumerate(forms) if i and fm[:2] != forms[i - 1][:2]}
    ys, y = [], 0.0
    for fm in forms:
        y += 0.45 if fm in gap else 0
        ys.append(y)
        y += 1
    ys = np.array(ys)
    fig, ax = fs.plt.subplots(figsize=(fs.FULL, 3.0))
    left = np.zeros(len(forms))
    for L in fs.LABEL_ORDER:
        v = ct[L].values if L in ct else np.zeros(len(forms))
        w = v / tot
        ax.barh(ys, w, left=left, height=0.72, color=fs.LABEL_COL[L], edgecolor="white", linewidth=0.8, label=fs.LABEL_NAME[L])
        for yi, li, wi, vi in zip(ys, left, w, v):
            if vi >= 2 and wi >= 0.08:
                ax.text(li + wi / 2, yi, f"{int(vi)}", ha="center", va="center", fontsize=6.2,
                        color="white" if L in ("W", "U") else fs.INK)
        left += w
    ax.set_yticks(ys)
    ax.set_yticklabels(forms)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("share of the answers participants received on the form")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    for yi, n in zip(ys, tot):
        ax.text(1.015, yi, f"{int(n)}", va="center", fontsize=6.5, color=fs.INK2)
    ax.text(1.015, -0.9, "answers", fontsize=6.5, color=fs.INK2, va="center")
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.17), ncol=3, handlelength=1.0, columnspacing=1.0)
    stamp(fig, src)
    fs.save(fig, OUT, "figA_answer_labels_by_form")


def fig_own_questions(src) -> None:
    """Own questions asked live: how participants rated the answer (OL1 'answered?', OL2 'would rely?') by the
    label of the last answer to it. Diverging ends (no = warm, yes = cool) with a grey 'partly' midpoint."""
    o = pd.read_csv(R / "own_questions_with_labels.csv", dtype=str).fillna("")
    o = o[o.label_last.isin(fs.LABEL_ORDER)]
    labs = [lab for lab in fs.LABEL_ORDER if (o.label_last == lab).any()]
    fig, (a, b) = fs.plt.subplots(1, 2, figsize=(fs.FULL, 2.2), gridspec_kw={"wspace": 0.35})
    for ax, col, cats, title in ((a, "answered", ["No", "Partly", "Yes"], "did the answer answer it?"),
                                 (b, "would_rely", ["No", "Yes"], "would you rely on it?")):
        colours = {"No": fs.DIVERGING5[0], "Partly": fs.DIVERGING5[2], "Yes": fs.DIVERGING5[4]}
        ct = pd.crosstab(o.label_last, o[col]).reindex(labs).fillna(0)
        tot = ct.sum(axis=1).values
        y = np.arange(len(labs))
        left = np.zeros(len(labs))
        for c in cats:
            v = ct[c].values if c in ct else np.zeros(len(labs))
            w = np.where(tot > 0, v / tot, 0)
            ax.barh(y, w, left=left, height=0.66, color=colours[c], edgecolor="white", linewidth=0.8, label=c.lower())
            for yi, li, wi, vi in zip(y, left, w, v):
                if vi >= 2 and wi >= 0.1:
                    ax.text(li + wi / 2, yi, f"{int(vi)}", ha="center", va="center", fontsize=6.2,
                            color="white" if c in ("No", "Yes") else fs.INK)
            left += w
        ax.set_yticks(y)
        ax.set_yticklabels(labs)
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.set_xticks([0, .5, 1])
        ax.set_xticklabels(["0", "50%", "100%"])
        ax.set_xlabel(f"participant's rating: {title}")
        ax.tick_params(axis="y", length=0)
        ax.spines["left"].set_visible(False)
        for yi, n in zip(y, tot):
            ax.text(1.02, yi, f"n={int(n)}", va="center", fontsize=6.0, color=fs.INK2)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=len(cats), handlelength=1.0, columnspacing=1.0)
    a.set_ylabel("last answer to the question")
    fs.panel_label(a, "(a)")
    fs.panel_label(b, "(b)")
    stamp(fig, src)
    fs.save(fig, OUT, "fig13_own_questions")


def main() -> int:
    fs.setup()
    d, e2, src = decisions()
    fig_own_questions(src)
    fig_e2(d, e2, src, "answer_received", "fig5_e2")
    fig_e2(d, e2, src, "answer_worst", "fig5alt_e2_worst")
    fig_sensitivity(src)
    fig_labels_by_form(src)
    print("label source:", src, "| written:", sorted(p.name for p in OUT.glob("fig5*")) + sorted(p.name for p in OUT.glob("figA*")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
