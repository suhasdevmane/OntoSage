#!/usr/bin/env python3
"""RQ3 figures on what participants decided (plan 04 section 3, Fig 4). Reads results/rq3/ (rq3_live_analysis.py).

    python figures/fig_rq3_decisions.py

Writes figures/out/:
  fig4_decisions_by_form               main: each of the 12 forms, decisions split by kind (100% bars), k/n correct
Display words are plain words (fig_style.py); 'correct' = the option the building's data support (the frozen key).
  fig4alt_e1_by_situation              E1 by situation (bootstrap 95% CI) with each form's own rate as a dot
  fig4alt_decisions_by_situation       the same split by kind, per situation
  fig4_combined                        the two alternatives side by side, for the page limit
Decision kinds come from the frozen key's failure text for the option chosen (no answer labels needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fig_style as fs  # noqa: E402
import analysis_rq3 as base  # noqa: E402
from rq3_live_analysis import failure_kind  # noqa: E402
from study_paths import DEID, RESULTS  # noqa: E402

OUT = HERE / "out"
R = RESULTS / "rq3"
SIT = ["S1", "S2", "S3", "S4"]


def load() -> pd.DataFrame:
    d = pd.read_csv(DEID / "decisions.csv", dtype={"option": str})
    d["kind"] = [failure_kind(w, f) for w, f in zip(d.warranted, d.failure.fillna(""))]
    roles = base.s3_option_roles()
    s3_nc = [(s == "S3" and roles.get(f, {}).get(str(o).strip().lower()) == "no_conclusion")
             for s, f, o in zip(d.situation, d.form, d.option)]
    d.loc[s3_nc, "kind"] = "warranted, no conclusion"
    return d


def stacked_rows(ax, rows: list, labels: list, counts: pd.DataFrame, gap_rows: set, annotate_right: dict) -> None:
    """Horizontal 100% stacked bars, one per row, surface gaps between segments, counts inside when they fit."""
    y = 0.0
    ys = []
    for r in rows:
        if r in gap_rows:
            y += 0.45
        ys.append(y)
        y += 1.0
    ys = np.array(ys)
    tot = counts.sum(axis=1).values
    left = np.zeros(len(rows))
    for k in fs.DECISION_ORDER:
        v = counts[k].values if k in counts else np.zeros(len(rows))
        w = np.where(tot > 0, v / tot, 0)
        ax.barh(ys, w, left=left, height=0.72, color=fs.DECISION_COL[k], edgecolor="white", linewidth=0.8, label=fs.DECISION_NAME[k])
        for yi, li, wi, vi in zip(ys, left, w, v):
            if vi >= 2 and wi >= 0.09:
                lum_dark = k in ("warranted", "accepted an unsupported claim")
                ax.text(li + wi / 2, yi, f"{int(vi)}", ha="center", va="center", fontsize=6.3, color="white" if lum_dark else fs.INK)
        left += w
    ax.set_yticks(ys)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.tick_params(axis="y", length=0)
    for yi, r in zip(ys, rows):
        if r in annotate_right:
            ax.text(1.015, yi, annotate_right[r], va="center", ha="left", fontsize=6.5, color=fs.INK2)
    ax.spines["left"].set_visible(False)


def fig_by_form(d: pd.DataFrame) -> None:
    forms = sorted(d.form.unique(), key=lambda f: (f[:2], f))
    counts = pd.crosstab(d.form, d.kind).reindex(forms).fillna(0)
    labels = [f"{f}" for f in forms]
    gap = {f for i, f in enumerate(forms) if i and f[:2] != forms[i - 1][:2]}
    right = {f: f"{int(d[d.form == f].warranted.sum())}/{int((d.form == f).sum())}" for f in forms}
    fig, ax = fs.plt.subplots(figsize=(fs.FULL, 3.15))
    stacked_rows(ax, forms, labels, counts, gap, right)
    ax.set_xlabel("share of decisions on the form")
    ax.text(1.015, -0.9, "correct", fontsize=6.5, color=fs.INK2, ha="left", va="center")
    # situation group names, left of the form names
    for s in SIT:
        fl = [f for f in forms if f.startswith(s)]
        idx = [forms.index(f) for f in fl]
        yy = np.mean([i + 0.45 * sum(1 for g in forms[: i + 1] if g in gap) for i in idx])
        ax.text(-0.115, yy, fs.SIT_STACK[s], transform=ax.get_yaxis_transform(), ha="right",
                va="center", fontsize=6.3, color=fs.INK2, linespacing=1.05)
    ax.legend(loc="upper center", bbox_to_anchor=(0.42, -0.17), ncol=2, handlelength=1.0, columnspacing=1.0)
    fs.save(fig, OUT, "fig4_decisions_by_form")


def panel_e1(ax, d: pd.DataFrame) -> None:
    e1 = pd.read_csv(R / "e1_warranted_by_situation.csv")
    e1 = e1[e1.method.str.startswith("participant") & e1.quantity.isin(SIT)].set_index("quantity").reindex(SIT)
    x = np.arange(len(SIT))
    ax.bar(x, e1.estimate, width=0.55, color=fs.SINGLE, alpha=0.9, zorder=2)
    ax.errorbar(x, e1.estimate, yerr=[e1.estimate - e1.ci_lo, e1.ci_hi - e1.estimate], fmt="none", ecolor=fs.INK,
                elinewidth=0.9, capsize=2.5, zorder=3)
    pf = d.groupby(["situation", "form"]).warranted.mean().reset_index()
    for i, s in enumerate(SIT):
        vals = pf[pf.situation == s].warranted.values
        jit = np.linspace(-0.16, 0.16, len(vals)) if len(vals) > 1 else [0]
        ax.scatter(i + np.array(jit), vals, s=14, facecolor="white", edgecolor=fs.INK, linewidth=0.8, zorder=4)
    for i, s in enumerate(SIT):
        k, n = int(e1.loc[s, "k_warranted"]), int(e1.loc[s, "n"])
        ax.text(i, 1.035, f"{k}/{n}", ha="center", va="bottom", fontsize=6.5, color=fs.INK2)
    ax.set_xticks(x)
    ax.set_xticklabels(SIT)  # the names are on the paired panel and in the caption; two-line names collide here
    ax.set_ylim(0, 1.1)
    ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_ylabel(fs.CORRECT)
    fs.hgrid(ax)


def fig_alternatives(d: pd.DataFrame) -> None:
    fig, ax = fs.plt.subplots(figsize=(fs.HALF, 2.35))
    panel_e1(ax, d)
    ax.scatter([], [], s=14, facecolor="white", edgecolor=fs.INK, label="one form (10 or 20 decisions)")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.2), handletextpad=0.3)
    fs.save(fig, OUT, "fig4alt_e1_by_situation")

    counts = pd.crosstab(d.situation, d.kind).reindex(SIT).fillna(0)
    fig, ax = fs.plt.subplots(figsize=(fs.HALF, 2.0))
    right = {s: f"{int(d[d.situation == s].warranted.sum())}/{int((d.situation == s).sum())}" for s in SIT}
    stacked_rows(ax, SIT, [fs.SIT_SHORT[s].replace("\n", " ") for s in SIT], counts, set(), right)
    ax.set_xlabel("share of decisions")
    ax.legend(loc="upper left", bbox_to_anchor=(-0.45, -0.22), ncol=2, handlelength=1.0, fontsize=6.3)
    fs.save(fig, OUT, "fig4alt_decisions_by_situation")

    fig, (a, b) = fs.plt.subplots(1, 2, figsize=(fs.FULL, 2.45), gridspec_kw={"width_ratios": [1, 1.35], "wspace": 0.55})
    panel_e1(a, d)
    fs.panel_label(a, "(a)")
    stacked_rows(b, SIT, [fs.SIT_SHORT[s].replace("\n", " ") for s in SIT], counts, set(), right)
    b.set_xlabel("share of decisions")
    fs.panel_label(b, "(b)")
    h, lab = b.get_legend_handles_labels()
    fig.subplots_adjust(bottom=0.25)
    fig.legend(h, lab, loc="upper center", bbox_to_anchor=(0.52, 0.075), ncol=2, handlelength=1.0, columnspacing=1.2)
    a.scatter([], [], s=14, facecolor="white", edgecolor=fs.INK)
    fs.save(fig, OUT, "fig4_combined")


def main() -> int:
    fs.setup()
    d = load()
    fig_by_form(d)
    fig_alternatives(d)
    print("written:", sorted(p.name for p in OUT.glob("fig4*")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
