#!/usr/bin/env python3
"""RQ2 figures (plan 04 section 3: Figure 2 frontier, Figure 3 anatomy of unsupported claims).

    python figures/fig_rq2.py

Reads results/rq2/rq2_results.json and labels/rq2/rq2_labels_*.csv. Writes figures/out/:
  fig2_frontier                share unsupported (U) against share warranted (W + WL), per system, 95%
                               participant-cluster bootstrap intervals; direct labels, so no legend
  fig2alt_labels_by_system     every label per system and question set (100% bars, the answer-label colours)
  fig3_u_anatomy               the unsupported answers by sub-type, per system
  fig3alt_ttask_by_form        T-TASK (12 canonical questions x 3 runs): labels per form, A beside B
All rest on labels; each figure's stamp follows the source of the label set it draws on (the T-TASK figure's
labels are the AI's by design and say so).
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
from study_paths import LABELS, RESULTS  # noqa: E402

OUT = HERE / "out"
R = RESULTS / "rq2"
L = LABELS / "rq2"
NAME = fs.SYSTEM_NAME                    # plain names (plan 08 B.4): "Assistant B" is defined once in the text
MARK = {"A": ("o", fs.OKABE["blue"]), "B": ("s", fs.MUTED), "A-minus": ("D", fs.OKABE["sky"])}
SUB_ORDER = ["fabricated", "wrong_source", "wrong_value", "scope", "temporal", "criterion_drop", "proxy", "causal"]
SUB_NAME = {"fabricated": "a value or place the data do not hold", "wrong_source": "read from a record about something else",
            "wrong_value": "a figure or order the data contradict", "scope": "more of the building than was measured",
            "temporal": "readings from the wrong time", "criterion_drop": "dropped a condition without saying",
            "proxy": "a related reading for the thing asked", "causal": "a cause the data cannot show"}


def stamp(fig, short: bool = False, label_set: str = "comparison") -> None:
    # the source of the label set the figure draws on: the overall label_source reads "MIXED: ..." whenever the
    # repeated runs (AI labels by design) sit beside the reviewed comparison set, and would stamp every figure
    src = json.loads((R / "rq2_results.json").read_text(encoding="utf-8")).get("label_source_by_set", {}).get(label_set, "")
    if src == "HUMAN_AGREED":
        return
    if src == "AUTHOR_CHECKED":
        text = ("PROVISIONAL: labels checked by one coder" if short else
                "PROVISIONAL: labels checked by the first author only; agreement with a second coder pending")
    elif src == "AUTHOR_CHECKED_SINGLE_CODER":  # the repeated runs, reviewed 28 Oct by the first author; no second coder
        text = "Labels reviewed by the first author only (no second coder)"
    elif label_set in ("ttask", "stability"):
        text = "Labels: the AI's (the repeated runs' labels were not reviewed)"
    else:
        text = ("PROVISIONAL: AI pre-labels, not human-coded" if short else
                "PROVISIONAL: answer labels are AI pre-labels on the blind sheet, not yet human-coded")
    fig.text(0.995, 0.998, text, ha="right", va="top", fontsize=5.8, color=fs.OKABE["vermillion"], style="italic")


def merged_ci(res: dict, tags: list) -> dict:
    """Per-system rates from several paired comparisons on the same questions (first tag that has a system wins)."""
    ci = {}
    for t in tags:
        for s, v in (res.get(t) or {}).get("rate_ci", {}).items():
            ci.setdefault(s, v)
    return {s: ci[s] for s in ("A", "A-minus", "B") if s in ci}


def frontier(res: dict, tag: str, name: str, extra: tuple = ()) -> None:
    r = res[tag]
    ci = merged_ci(res, [tag, *extra])
    fig, ax = fs.plt.subplots(figsize=(fs.HALF * 1.15, 2.45))
    panel_frontier(ax, ci, f"n = {r['n_questions']} questions, {r['n_participants']} participants")
    stamp(fig, short=True)
    fs.save(fig, OUT, name)


def frontier_by_set(res: dict, name: str) -> None:
    """Two panels: the participants' task questions (T-LIVE) and their own new questions (T-FRESH)."""
    sets = [qs for qs in ("T-LIVE", "T-FRESH") if f"{qs}_A_vs_B" in res]
    if len(sets) < 2:
        return
    fig, axes = fs.plt.subplots(1, 2, figsize=(fs.FULL, 2.6), gridspec_kw={"wspace": 0.32})
    for i, (ax, qs) in enumerate(zip(axes, sets)):
        r = res[f"{qs}_A_vs_B"]
        what = "task questions" if qs == "T-LIVE" else "own new questions"
        panel_frontier(ax, merged_ci(res, [f"{qs}_A_vs_B", f"{qs}_A_vs_Aminus"]),
                       f"{qs}: {r['n_questions']} {what}", legend_fs=5.6, two_line=True)
        fs.panel_label(ax, f"({'ab'[i]})")
        ax.set_xlabel("")
        if i:
            ax.set_ylabel("")
    fig.supxlabel("answers not supported by the data (U)  ← better", fontsize=7.5, y=-0.02)
    stamp(fig)
    fs.save(fig, OUT, name)


def panel_frontier(ax, ci: dict, note: str, legend_fs: float = 6.0, two_line: bool = False) -> None:
    for s, v in ci.items():
        m, c = MARK.get(s, ("o", fs.INK))
        u, g = v["U"], v["W+WL"]
        # identity by marker shape + colour and a legend that carries the two rates: the points sit close together, so
        # labels beside them land on the other system's error bars. In a half-width panel the rates go on a second line,
        # or the legend runs into the axis
        sep = "\n" if two_line else ": "
        ax.errorbar(u["rate"], g["rate"], xerr=[[u["rate"] - u["lo"]], [u["hi"] - u["rate"]]],
                    yerr=[[g["rate"] - g["lo"]], [g["hi"] - g["rate"]]], fmt=m, color=c, ecolor=c, elinewidth=0.9,
                    capsize=2, markersize=6, markeredgecolor="white", markeredgewidth=0.8, zorder=3,
                    label=f"{NAME.get(s, s).replace(chr(10), ' ')}{sep}U {100 * u['rate']:.0f}%, W+WL {100 * g['rate']:.0f}%")
    ax.legend(loc="upper right", fontsize=legend_fs, handletextpad=0.4, borderaxespad=0.3)
    ax.set_xlim(0, 0.5)
    ax.set_ylim(0, 1)
    ax.set_xticks([0, .1, .2, .3, .4, .5])
    ax.set_xticklabels(["0", "10%", "20%", "30%", "40%", "50%"])
    ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("answers not supported by the data (U)  ← better")
    ax.set_ylabel("supported or stating\nlimits (W + WL)  → better")
    ax.text(0.98, 0.03, note, transform=ax.transAxes, ha="right", fontsize=6.0, color=fs.INK2)
    fs.hgrid(ax)
    fs.vgrid(ax)


def labels_by_system(d: pd.DataFrame, name: str) -> None:
    groups = [(qs, s) for qs in ("T-LIVE", "T-FRESH") for s in ("A", "A-minus", "B") if ((d.question_set == qs) & (d.system == s)).any()]
    fig, ax = fs.plt.subplots(figsize=(fs.FULL, 0.42 * len(groups) + 0.9))
    y = np.arange(len(groups))
    left = np.zeros(len(groups))
    for L_ in fs.LABEL_ORDER + ["PF"]:
        v = np.array([((d.question_set == qs) & (d.system == s) & (d.label == L_)).sum() for qs, s in groups], dtype=float)
        tot = np.array([((d.question_set == qs) & (d.system == s)).sum() for qs, s in groups], dtype=float)
        w = v / tot
        if v.sum() == 0:
            continue
        ax.barh(y, w, left=left, height=0.66, color=fs.LABEL_COL[L_], edgecolor="white", linewidth=0.8, label=fs.LABEL_NAME[L_])
        for yi, li, wi, vi in zip(y, left, w, v):
            if vi >= 2 and wi >= 0.06:
                ax.text(li + wi / 2, yi, f"{int(vi)}", ha="center", va="center", fontsize=6.0,
                        color="white" if L_ in ("W", "U", "PF") else fs.INK)
        left += w
    ax.set_yticks(y)
    ax.set_yticklabels([f"{qs}  {NAME.get(s, s).replace(chr(10), ' ')}" for qs, s in groups])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("share of answers")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.4, -0.32 if len(groups) < 5 else -0.2), ncol=3, handlelength=1.0)
    stamp(fig)
    fs.save(fig, OUT, name)


def anatomy(d: pd.DataFrame, name: str) -> None:
    u = d[d.label == "U"].copy()
    u["st"] = u.u_subtypes.fillna("").str.split()
    u = u.explode("st")
    systems = [s for s in ("A", "A-minus", "B") if (d.system == s).any()]
    subs = [s for s in SUB_ORDER if (u.st == s).any()]
    if not subs:
        return
    fig, ax = fs.plt.subplots(figsize=(fs.HALF * 1.3, 0.36 * len(subs) + 0.9))
    y = np.arange(len(subs))
    h = 0.8 / len(systems)
    for j, s in enumerate(systems):
        v = np.array([((u.system == s) & (u.st == st)).sum() for st in subs])
        m, c = MARK.get(s, ("o", fs.INK))
        ax.barh(y - 0.4 + h * (j + 0.5), v, height=h * 0.9, color=c, label=NAME.get(s, s).replace("\n", " "))
        for yi, vi in zip(y - 0.4 + h * (j + 0.5), v):
            if vi:
                ax.text(vi + 0.15, yi, str(int(vi)), va="center", fontsize=6.0, color=fs.INK2)
    ax.set_yticks(y)
    ax.set_yticklabels([SUB_NAME[s] for s in subs])
    ax.invert_yaxis()
    ax.set_xlabel("U answers with this kind of error")
    ax.tick_params(axis="y", length=0)
    from matplotlib.ticker import MaxNLocator
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlim(0, max(1, ax.get_xlim()[1]) * 1.12)
    fs.vgrid(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(0.3, -0.22), ncol=len(systems), fontsize=6.0)
    stamp(fig)
    fs.save(fig, OUT, name)


def ttask_by_form(t: pd.DataFrame) -> None:
    forms = sorted(t.form.unique(), key=lambda f: (f[:2], f))
    rows = [(f, s) for f in forms for s in ("A", "B")]
    fig, ax = fs.plt.subplots(figsize=(fs.FULL, 0.2 * len(rows) + 0.9))
    y = np.arange(len(rows)) + np.repeat(np.arange(len(forms)) * 0.5, 2)
    left = np.zeros(len(rows))
    for L_ in fs.LABEL_ORDER + ["PF"]:
        v = np.array([((t.form == f) & (t.system == s) & (t.label == L_)).sum() for f, s in rows], dtype=float)
        tot = np.array([((t.form == f) & (t.system == s)).sum() for f, s in rows], dtype=float)
        if v.sum() == 0:
            continue
        ax.barh(y, v / tot, left=left, height=0.85, color=fs.LABEL_COL[L_], edgecolor="white", linewidth=0.8,
                label=fs.LABEL_NAME[L_])
        left += v / tot
    ax.set_yticks(y)
    ax.set_yticklabels([f"{f}  {NAME.get(s, s).replace(chr(10), ' ')}" for f, s in rows], fontsize=6.2)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 1 / 3, 2 / 3, 1])
    ax.set_xticklabels(["0", "1/3", "2/3", "3/3"])
    ax.set_xlabel("share of the three runs")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.4, -0.11), ncol=5, handlelength=1.0, fontsize=6.0)
    stamp(fig, label_set="ttask")
    fs.save(fig, OUT, "fig3alt_ttask_by_form")


def main() -> int:
    fs.setup()
    res = json.loads((R / "rq2_results.json").read_text(encoding="utf-8")) if (R / "rq2_results.json").exists() else {}
    if "comparison_A_vs_B" in res:
        d = pd.read_csv(L / "rq2_labels_comparison.csv", dtype=str).fillna("")
        frontier(res, "comparison_A_vs_B", "fig2_frontier", extra=("comparison_A_vs_Aminus",))
        frontier_by_set(res, "fig2alt_frontier_by_set")
        labels_by_system(d, "fig2alt_labels_by_system")
        anatomy(d, "fig3_u_anatomy")
    if (L / "rq2_labels_ttask.csv").exists():
        t = pd.read_csv(L / "rq2_labels_ttask.csv", dtype=str).fillna("")
        ttask_by_form(t)
        if "comparison_A_vs_B" not in res:
            t2 = t.copy()
            t2["question_set"] = "T-LIVE"
            anatomy(t2, "fig3_u_anatomy_ttask_preview")
    print("written:", sorted(p.name for p in OUT.glob("fig[23]*")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
