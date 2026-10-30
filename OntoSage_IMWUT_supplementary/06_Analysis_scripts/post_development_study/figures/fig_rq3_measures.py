#!/usr/bin/env python3
"""RQ3 figures: subjective measures (companion to Table 5) and session behaviour. Need no answer labels.

    python figures/fig_rq3_measures.py

Writes figures/out/:
  fig10_sus_trust_effort     one dot per participant: SUS (0-100), trust (mean of TR1-TR3, 1-7), mental effort
                             (EF1, 1-9); bar = mean (SUS, trust) or median (effort) with its 95% bootstrap CI
  fig10alt_sus_vs_warranted  each participant's SUS against their share of warranted decisions (Spearman in text)
  fig11_behaviour            (a) seconds per task by situation; (b) questions asked per task; (c) answer latency
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fig_style as fs  # noqa: E402
from study_paths import DEID, RESULTS  # noqa: E402

OUT = HERE / "out"
R = RESULTS / "rq3"
SIT = ["S1", "S2", "S3", "S4"]


def strip(ax, vals, centre, lo, hi, ylim, ticks, label, centre_name):
    rng = np.random.default_rng(20261009)
    x = rng.uniform(-0.18, 0.18, len(vals))
    ax.scatter(x, vals, s=12, facecolor="white", edgecolor=fs.SINGLE, linewidth=0.8, zorder=3)
    ax.hlines(centre, -0.32, 0.32, color=fs.INK, linewidth=1.4, zorder=4)
    ax.vlines(0.42, lo, hi, color=fs.INK, linewidth=0.9)
    ax.hlines([lo, hi], 0.38, 0.46, color=fs.INK, linewidth=0.9)
    ax.text(0.5, centre, f"{centre_name}\n{centre:.1f}", va="center", fontsize=6.1, color=fs.INK2)
    ax.set_xlim(-0.5, 1.0)
    ax.set_xticks([])
    ax.set_ylim(*ylim)
    ax.set_yticks(ticks)
    ax.set_title(label, fontsize=7.2, color=fs.INK)
    ax.spines["bottom"].set_visible(False)
    fs.hgrid(ax)


def fig_measures() -> None:
    p = pd.read_csv(R / "per_participant_scores.csv")
    u = json.loads((R / "rq3_results.json").read_text(encoding="utf-8"))["usability"]
    fig, axs = fs.plt.subplots(1, 3, figsize=(fs.FULL, 2.2), gridspec_kw={"wspace": 0.55})
    strip(axs[0], p.sus_score, u["sus_mean"], u["sus_lo"], u["sus_hi"], (0, 102), [0, 25, 50, 75, 100], "SUS (0-100)", "mean")
    strip(axs[1], p.trust_mean, u["trust_mean"], u["trust_lo"], u["trust_hi"], (1, 7.2), [1, 2, 3, 4, 5, 6, 7], "trust (1-7)", "mean")
    strip(axs[2], p.EF1, u["effort_median"], u["effort_lo"], u["effort_hi"], (1, 9.3), [1, 3, 5, 7, 9], "mental effort (1-9)", "median")
    for a, t in zip(axs, ["(a)", "(b)", "(c)"]):
        fs.panel_label(a, t)
    fig.text(0.5, -0.04, f"n = {len(p)} participants; whiskers: 95% bootstrap interval. SUS Cronbach's alpha "
             f"{u['sus_alpha']:.2f}; trust alpha {u['trust_alpha']:.2f}.", ha="center", fontsize=6.2, color=fs.INK2)
    fs.save(fig, OUT, "fig10_sus_trust_effort")

    fig, ax = fs.plt.subplots(figsize=(fs.HALF, 2.2))
    ax.scatter(p.sus_score, p.warranted_share, s=16, color=fs.SINGLE, edgecolor="white", linewidth=0.8, zorder=3)
    ax.set_xlabel("SUS")
    ax.set_ylabel("the participant's 6 decisions\nthat were correct")
    ax.set_ylim(-0.03, 1.03)
    ax.set_yticks([0, 1 / 3, 2 / 3, 1])
    ax.set_yticklabels(["0", "2/6", "4/6", "6/6"])
    ax.set_xlim(40, 102)
    ax.text(0.02, 0.98, f"Spearman rho = {u['spearman_sus_vs_warranted_share']:.2f}\n"
            f"95% CI {u['spearman_lo']:.2f} to {u['spearman_hi']:.2f}", transform=ax.transAxes, va="top", fontsize=6.2,
            color=fs.INK2)
    fs.hgrid(ax)
    fs.save(fig, OUT, "fig10alt_sus_vs_warranted")


def fig_behaviour() -> None:
    d = pd.read_csv(DEID / "decisions.csv")
    t = pd.read_csv(DEID / "turns.csv")
    fig, axs = fs.plt.subplots(1, 3, figsize=(fs.FULL, 2.15), gridspec_kw={"wspace": 0.5, "width_ratios": [1.2, 1, 1]})
    a = axs[0]
    data = [d[d.situation == s].seconds.dropna() / 60 for s in SIT]
    bp = a.boxplot(data, widths=0.5, patch_artist=True, showfliers=False, medianprops={"color": fs.INK, "linewidth": 1.2},
                   whiskerprops={"color": fs.INK2, "linewidth": 0.8}, capprops={"color": fs.INK2, "linewidth": 0.8})
    for b in bp["boxes"]:
        b.set(facecolor="white", edgecolor=fs.SINGLE, linewidth=0.9)
    rng = np.random.default_rng(20261009)
    for i, v in enumerate(data, 1):
        a.scatter(i + rng.uniform(-0.15, 0.15, len(v)), v, s=5, color=fs.SINGLE, alpha=0.55, linewidth=0, zorder=3)
    a.axhline(9, color=fs.OKABE["vermillion"], linewidth=0.8)
    a.text(3.0, 9.25, "9-min guide", fontsize=5.6, color=fs.INK2, ha="center", va="bottom")  # S3 (x=3) has no points up here
    a.set_xticks(range(1, 5))
    a.set_xticklabels(SIT)
    a.set_ylabel("minutes, goal shown to decision")
    fs.hgrid(a)
    fs.panel_label(a, "(a)")
    b = axs[1]
    q = d.n_questions_task.clip(upper=4).value_counts().reindex(range(5), fill_value=0)
    b.bar(q.index, q.values, width=0.62, color=fs.SINGLE)
    for x, v in zip(q.index, q.values):
        b.text(x, v + 1.5, str(int(v)), ha="center", fontsize=6.1, color=fs.INK2)
    b.set_xticks(range(5))
    b.set_xticklabels(["0", "1", "2", "3", "4+"])
    b.set_xlabel("questions per task")
    b.set_ylabel("tasks")
    fs.hgrid(b)
    fs.panel_label(b, "(b)")
    c = axs[2]
    lat = pd.to_numeric(t[t.role == "task"].answer_seconds, errors="coerce").dropna()
    c.hist(lat.clip(upper=180), bins=np.arange(0, 190, 10), color=fs.SINGLE, edgecolor="white", linewidth=0.6)
    med = float(lat.median())
    c.axvline(med, color=fs.INK, linewidth=1.0)
    c.text(med + 4, c.get_ylim()[1] * 0.9, f"median\n{med:.0f} s", fontsize=6.0, color=fs.INK2, va="top")
    c.set_xlabel("seconds to answer")  # values over 180 s are pooled in the last bin (caption)
    c.set_ylabel("task answers")
    fs.hgrid(c)
    fs.panel_label(c, "(c)")
    fs.save(fig, OUT, "fig11_behaviour")


def main() -> int:
    fs.setup()
    fig_measures()
    fig_behaviour()
    print("written:", sorted(p.name for p in OUT.glob("fig1[01]*")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
