#!/usr/bin/env python3
"""RQ3 figures: calibration (Fig 7), helpfulness by answer (Fig 8), reliance and recovery (Fig 6, Fig 9).

    python figures/fig_rq3_calibration_reliance.py

Reads results/rq3/. Writes figures/out/:
  fig7_calibration            (a) reliability: confidence bin vs share warranted (point size = n); (b) overconfidence
                              (mean confidence minus share warranted) by situation, 95% bootstrap CI
  fig8_helpfulness            helpfulness (1-5) by the label of the answer received, diverging at the midpoint
  fig8alt_helpfulness_by_decision   the same by whether the decision was warranted (needs no labels)
  fig6_reliance               would act without checking, by the label of the answer received
  fig9_recovery               after a first answer labelled FD / WL / U: asked a follow-up? final decision warranted?
  fig6_fig9_combined          the two side by side
Label-based figures carry the PROVISIONAL stamp while the labels are AI pre-labels. Display words are plain words
(plan 08 section B.4): 'correct' = the option the building's data support; 'calibration' is not used on the figure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fig_style as fs  # noqa: E402
from fig_rq3_answers import stamp  # noqa: E402
from study_paths import RESULTS  # noqa: E402

OUT = HERE / "out"
R = RESULTS / "rq3"
SIT = ["S1", "S2", "S3", "S4"]
ORDER = ["W", "WL", "FD", "U", "OT", "none"]


def pct_axis(ax, which="y", top=1.0):
    t = [0, .25, .5, .75, 1.0]
    lab = ["0", "25%", "50%", "75%", "100%"]
    (ax.set_yticks if which == "y" else ax.set_xticks)(t)
    (ax.set_yticklabels if which == "y" else ax.set_xticklabels)(lab)


def fig_calibration() -> None:
    rel = pd.read_csv(R / "c3_reliability_bins.csv").dropna(subset=["mean_conf"])
    cal = pd.read_csv(R / "c3_calibration.csv").set_index("situation")
    fig, (a, b) = fs.plt.subplots(1, 2, figsize=(fs.FULL, 2.45), gridspec_kw={"wspace": 0.30, "width_ratios": [1, 0.9]})
    a.plot([0, 1], [0, 1], color=fs.MUTED, linewidth=0.8, zorder=1)
    a.text(0.62, 0.66, "confidence = share correct", rotation=38, fontsize=6, color=fs.MUTED, ha="center")
    x, y, n = rel.mean_conf.values / 100, rel.warranted_rate.values, rel.n.values
    a.plot(x, y, color=fs.SINGLE, linewidth=1.2, zorder=2)
    a.scatter(x, y, s=8 + 0.9 * n, color=fs.SINGLE, edgecolor="white", linewidth=1.0, zorder=3)
    for xi, yi, ni, b_ in zip(x, y, n, rel.conf_bin):
        off = {"90-100": (-24, 3), "70-79": (-12, -17), "80-89": (13, -17), "50-69": (17, 2)}.get(str(b_), (0, -16 if yi > 0.2 else 8))
        a.annotate(f"{b_}\nn={ni}", (xi, yi), xytext=off, textcoords="offset points",
                   ha="center", fontsize=5.6, color=fs.INK2)
    a.set_xlim(0, 1.06)
    a.set_ylim(0, 1.02)
    pct_axis(a, "x")
    pct_axis(a, "y")
    a.set_xlabel("mean confidence in the bin")
    a.set_ylabel("decisions that were correct")
    fs.hgrid(a)
    fs.panel_label(a, "(a)")
    rows = ["all"] + SIT
    yy = np.arange(len(rows))
    oc, lo, hi = cal.loc[rows, "overconfidence"], cal.loc[rows, "oc_lo"], cal.loc[rows, "oc_hi"]
    b.axvline(0, color=fs.MUTED, linewidth=0.8)
    b.errorbar(oc, yy, xerr=[oc - lo, hi - oc], fmt="o", color=fs.SINGLE, ecolor=fs.INK, elinewidth=0.9, capsize=2.5,
               markersize=4.5, markeredgecolor="white", markeredgewidth=0.8)
    for yi, r in zip(yy, rows):
        c = cal.loc[r]
        b.text(1.02, yi, f"{c.mean_confidence:.0f} vs {100 * c.warranted_rate:.0f}%", transform=b.get_yaxis_transform(),
               va="center", fontsize=6.0, color=fs.INK2)
    b.text(1.02, -0.75, "confidence vs\ncorrect", transform=b.get_yaxis_transform(), va="center", fontsize=5.8, color=fs.INK2)
    b.set_yticks(yy)
    b.set_yticklabels(["all 180"] + SIT)
    b.invert_yaxis()
    b.set_xlim(-0.4, 0.9)
    b.set_xticks([-0.25, 0, 0.25, 0.5, 0.75])
    b.set_xticklabels(["-25", "0", "+25", "+50", "+75"])
    b.set_xlabel("confidence minus share correct (points)")
    b.tick_params(axis="y", length=0)
    b.spines["left"].set_visible(False)
    fs.vgrid(b)
    fs.panel_label(b, "(b)")
    fs.save(fig, OUT, "fig7_calibration")


def likert_rows(ax, groups: list, names: list, data: dict, points: int = 5, mid: int = 3) -> None:
    """Diverging stacked bars centred on the midpoint category (half of it each side)."""
    cols = fs.DIVERGING5
    y = np.arange(len(groups))
    for i, g in enumerate(groups):
        v = np.array([data[g].get(k, 0) for k in range(1, points + 1)], dtype=float)
        n = v.sum()
        if n == 0:
            continue
        p = v / n
        left = -(p[: mid - 1].sum() + p[mid - 1] / 2)
        for k in range(points):
            ax.barh(i, p[k], left=left, height=0.68, color=cols[k], edgecolor="white", linewidth=0.8)
            if p[k] >= 0.1:
                ax.text(left + p[k] / 2, i, f"{int(v[k])}", ha="center", va="center", fontsize=6.0,
                        color="white" if k in (0, points - 1) else fs.INK)
            left += p[k]
        ax.text(1.0, i, f"n={int(n)}", va="center", ha="left", fontsize=6.1, color=fs.INK2,
                transform=ax.get_yaxis_transform())
    ax.axvline(0, color=fs.INK2, linewidth=0.6, zorder=0)
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlim(-1, 1)
    ax.set_xticks([-1, -0.5, 0, 0.5, 1])
    ax.set_xticklabels(["100%", "50%", "0", "50%", "100%"])
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)


def legend_likert(fig, labels: list, y: float = 0.02) -> None:
    from matplotlib.patches import Patch
    h = [Patch(facecolor=c, edgecolor="white") for c in fs.DIVERGING5]
    fig.legend(h, labels, loc="upper center", bbox_to_anchor=(0.5, y), ncol=5, handlelength=1.0, columnspacing=1.0)


def fig_helpfulness() -> None:
    d = pd.read_csv(R / "decisions_with_labels.csv")
    src = pd.read_csv(R / "e2_by_answer_received.csv").label_source.iloc[0]
    labs = [lab for lab in ORDER if (d.answer_received == lab).any()]
    data = {lab: d[d.answer_received == lab].helpfulness.value_counts().to_dict() for lab in labs}
    fig, ax = fs.plt.subplots(figsize=(fs.HALF * 1.3, 2.25))
    likert_rows(ax, labs, [fs.LABEL_SHORT[lab] for lab in labs], data)
    ax.set_xlabel("helpfulness of the assistant's answer: share of ratings")
    ax.set_ylabel("last answer before deciding")
    fig.subplots_adjust(bottom=0.3)
    legend_likert(fig, ["1 not at all", "2", "3", "4", "5 very helpful"], 0.08)
    stamp(fig, src)
    fs.save(fig, OUT, "fig8_helpfulness")

    groups = [1, 0]
    data = {g: d[d.warranted == g].helpfulness.value_counts().to_dict() for g in groups}
    fig, ax = fs.plt.subplots(figsize=(fs.HALF * 1.3, 1.35))
    likert_rows(ax, groups, ["correct decision", "other decision"], data)
    ax.set_xlabel("helpfulness: share of ratings")
    fig.subplots_adjust(bottom=0.42)
    legend_likert(fig, ["1 not at all", "2", "3", "4", "5 very helpful"], 0.1)
    fs.save(fig, OUT, "fig8alt_helpfulness_by_decision")


def panel_reliance(ax, d: pd.DataFrame) -> None:
    labs = [lab for lab in ORDER if (d.answer_received == lab).any()]
    y = np.arange(len(labs))
    act = np.array([d[(d.answer_received == lab)].would_act.mean() for lab in labs])
    n = np.array([(d.answer_received == lab).sum() for lab in labs])
    k = np.array([int(d[(d.answer_received == lab)].would_act.sum()) for lab in labs])
    ax.barh(y, act, height=0.62, color=fs.SINGLE)
    for yi, a_, kk, nn in zip(y, act, k, n):
        ax.text(a_ + 0.02, yi, f"{kk}/{nn}", va="center", fontsize=6.1, color=fs.INK2)
    ax.set_yticks(y)
    ax.set_yticklabels([fs.LABEL_SHORT[lab] for lab in labs])
    ax.invert_yaxis()
    ax.set_xlim(0, 1.12)
    pct_axis(ax, "x")
    ax.set_xlabel("would act without checking")
    ax.set_ylabel("last answer before deciding")
    ax.tick_params(axis="y", length=0)
    fs.vgrid(ax)


def panel_recovery(ax, rec: pd.DataFrame) -> None:
    rec = rec.set_index("first_answer").reindex(["FD", "WL", "U"]).dropna(subset=["n_tasks"])
    y = np.arange(len(rec))
    w1 = rec.asked_follow_up / rec.n_tasks
    w2 = rec.final_warranted / rec.n_tasks
    ax.barh(y - 0.17, w1, height=0.32, color=fs.OKABE["sky"], label="asked a follow-up question")
    ax.barh(y + 0.17, w2, height=0.32, color=fs.SINGLE, label="final decision correct")
    for yi, a_, b_, r in zip(y, w1, w2, rec.itertuples()):
        ax.text(a_ + 0.02, yi - 0.17, f"{int(r.asked_follow_up)}/{int(r.n_tasks)}", va="center", fontsize=6.0, color=fs.INK2)
        ax.text(b_ + 0.02, yi + 0.17, f"{int(r.final_warranted)}/{int(r.n_tasks)}", va="center", fontsize=6.0, color=fs.INK2)
    ax.set_yticks(y)
    ax.set_yticklabels([f"first answer {lab}" for lab in rec.index])
    ax.invert_yaxis()
    ax.set_xlim(0, 1.15)
    pct_axis(ax, "x")
    ax.set_xlabel("share of tasks")
    ax.tick_params(axis="y", length=0)
    fs.vgrid(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, -0.25), ncol=1, handlelength=1.0)


def fig_reliance_recovery() -> None:
    d = pd.read_csv(R / "decisions_with_labels.csv")
    rec = pd.read_csv(R / "recovery.csv")
    src = pd.read_csv(R / "e2_by_answer_received.csv").label_source.iloc[0]
    fig, ax = fs.plt.subplots(figsize=(fs.HALF, 2.2))
    panel_reliance(ax, d)
    stamp(fig, src)
    fs.save(fig, OUT, "fig6_reliance")
    fig, ax = fs.plt.subplots(figsize=(fs.HALF, 2.0))
    panel_recovery(ax, rec)
    stamp(fig, src)
    fs.save(fig, OUT, "fig9_recovery")
    fig, (a, b) = fs.plt.subplots(1, 2, figsize=(fs.FULL, 2.3), gridspec_kw={"wspace": 0.6})
    panel_reliance(a, d)
    fs.panel_label(a, "(a)")
    panel_recovery(b, rec)
    fs.panel_label(b, "(b)")
    stamp(fig, src)
    fs.save(fig, OUT, "fig6_fig9_combined")


def main() -> int:
    fs.setup()
    fig_calibration()
    fig_helpfulness()
    fig_reliance_recovery()
    print("written:", sorted(p.name for p in OUT.glob("fig[6789]*")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
