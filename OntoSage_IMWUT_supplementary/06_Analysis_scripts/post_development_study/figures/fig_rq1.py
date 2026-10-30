#!/usr/bin/env python3
"""RQ1 figure: participants' own questions against corpus questions, Part A codes (what the answer needs, whether the
building's data could establish it, whether it is answerable in principle).

    python figures/fig_rq1.py

Reads results/rq1/fresh_vs_corpus.csv (the table twin) and rq1_results.json. Writes figures/out/:
  fig14_fresh_vs_corpus        two panels sharing the rows: (a) share of each source's questions, (b) own minus
                               corpus, percentage points, with the 95% interval that resamples contributors
  fig14alt_fresh_vs_corpus     the shares only, three small panels side by side
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fig_style as fs  # noqa: E402
from study_paths import FIGS, RESULTS  # noqa: E402

OUT = FIGS / "out"
FIELD_NAME = {"F2_evidence_source": "What a complete answer needs",
              "F4_evidence_relation": "Could the building's data establish it?",
              "F5_answerable": "Answerable in principle?"}
VALUE_NAME = {
    ("F2_evidence_source", "measurement"): "sensor readings",
    ("F2_evidence_source", "description"): "the building's description",
    ("F2_evidence_source", "record"): "dated records",
    ("F2_evidence_source", "document"): "policies and manuals",
    ("F2_evidence_source", "external"): "outside knowledge",
    ("F2_evidence_source", "none"): "no evidence, or cannot tell",
    ("F4_evidence_relation", "direct"): "yes, directly",
    ("F4_evidence_relation", "proxy"): "only through a related quantity",
    ("F4_evidence_relation", "not_establishable"): "no building data could",
    ("F4_evidence_relation", "unclear"): "cannot tell",
    ("F5_answerable", "yes"): "yes",
    ("F5_answerable", "partly"): "partly",
    ("F5_answerable", "no"): "no",
}
OWN, CORPUS = fs.OKABE["blue"], fs.OKABE["grey"]


def stamp(fig, src: str) -> None:
    if src != "HUMAN_AGREED":
        text = ("PROVISIONAL: codes checked by the first author only; agreement with a second coder pending"
                if src == "AUTHOR_CHECKED" else "PROVISIONAL: AI pre-codes (Part A codebook v1), not yet checked by a person")
        fig.text(0.995, 0.998, text, ha="right", va="top", fontsize=5.8, color=fs.OKABE["vermillion"], style="italic")


def layout(t: pd.DataFrame) -> tuple:
    """Rows top to bottom: a heading row per field, then its values. Returns (rows, headings)."""
    rows, heads, y = [], [], 0.0
    for f in FIELD_NAME:
        heads.append((y, FIELD_NAME[f]))
        y += 1.0
        for r in t[t.field == f].itertuples():
            rows.append((y, r))
            y += 1.0
        y += 0.35
    return rows, heads


def main() -> int:
    fs.setup()
    t = pd.read_csv(RESULTS / "rq1" / "fresh_vs_corpus.csv")
    res = json.loads((RESULTS / "rq1" / "rq1_results.json").read_text(encoding="utf-8"))
    src = res["label_source"]
    n_own, n_cor = int(t.fresh_items.iloc[0]), int(t.corpus_items.iloc[0])
    rows, heads = layout(t)
    top = max(y for y, _ in rows) + 0.7

    fig, (a, b) = fs.plt.subplots(1, 2, figsize=(fs.FULL, 3.55), sharey=True,
                                  gridspec_kw={"width_ratios": [1.15, 1.0], "wspace": 0.08})
    # the row labels sit inside a fixed left margin and the group headings start at the figure's edge, so the whole
    # figure is the text width and prints at 100% (a tight box around wider labels made LaTeX shrink it to 79%)
    fig.subplots_adjust(left=0.31, right=0.985, top=0.89, bottom=0.215)
    from matplotlib import transforms
    head_tf = transforms.blended_transform_factory(fig.transFigure, a.transData)
    for y, r in rows:
        for dy, share, col in ((-0.19, r.fresh_share, OWN), (0.19, r.corpus_share, CORPUS)):
            a.barh(y + dy, share, height=0.34, color=col, edgecolor="white", linewidth=0.6)
            a.text(share + 0.012, y + dy, f"{100 * share:.0f}%", va="center", fontsize=5.6, color=fs.INK2)
        b.errorbar(r.diff_fresh_minus_corpus, y, xerr=[[r.diff_fresh_minus_corpus - r.ci_lo],
                                                      [r.ci_hi - r.diff_fresh_minus_corpus]],
                   fmt="o", color=fs.SINGLE, ecolor=fs.SINGLE, elinewidth=0.9, capsize=2, markersize=3.8,
                   markeredgecolor="white", markeredgewidth=0.5)
    a.set_yticks([y for y, _ in rows])
    a.set_yticklabels([VALUE_NAME[(r.field, r.value)] for _, r in rows])
    for y, text in heads:
        fig.text(0.005, y, text, transform=head_tf, ha="left", va="center", fontsize=7, fontweight="bold",
                 color=fs.INK)
    a.set_ylim(top, -0.7)
    a.set_xlim(0, 1.05)
    a.set_xticks([0, .25, .5, .75, 1])
    a.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    a.set_xlabel("share of each source's\nquestions")
    fs.vgrid(a)
    a.tick_params(axis="y", length=0)
    from matplotlib.patches import Patch
    # below both panels: inside panel (a) it covered the last rows' bars and labels
    fig.legend(handles=[Patch(color=OWN, label=f"participants' own questions (n = {n_own})"),
                        Patch(color=CORPUS, label=f"corpus questions (n = {n_cor})")],
               loc="lower center", bbox_to_anchor=(0.5, 0.0), ncol=2, fontsize=6.2, handlelength=1.0)
    fs.panel_label(a, "(a)")

    b.axvline(0, color=fs.INK2, linewidth=0.6)
    b.set_xlim(-0.5, 0.5)
    b.set_xticks([-0.4, -0.2, 0, 0.2, 0.4])
    b.set_xticklabels(["−40", "−20", "0", "+20", "+40"])
    b.set_xlabel("own minus corpus, percentage\npoints (95% interval)")
    fs.vgrid(b)
    b.tick_params(axis="y", length=0)
    fs.panel_label(b, "(b)")
    stamp(fig, src)
    fs.save(fig, OUT, "fig14_fresh_vs_corpus")

    # alternative, one compact panel: each row's two shares as dots joined by a line (no interval panel)
    fig, ax = fs.plt.subplots(figsize=(fs.FULL * 0.78, 3.3))
    for y, r in rows:
        ax.plot([r.fresh_share, r.corpus_share], [y, y], color=fs.GRID, linewidth=2.2, zorder=1,
                solid_capstyle="round")
        ax.scatter([r.corpus_share], [y], s=22, color=CORPUS, edgecolor="white", linewidth=0.6, zorder=2)
        ax.scatter([r.fresh_share], [y], s=22, color=OWN, edgecolor="white", linewidth=0.6, zorder=3)
    ax.set_yticks([y for y, _ in rows])
    ax.set_yticklabels([VALUE_NAME[(r.field, r.value)] for _, r in rows])
    for y, text in heads:
        ax.text(-0.012, y, text, transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=7,
                fontweight="bold", color=fs.INK)
    ax.set_ylim(top, -0.7)
    ax.set_xlim(-0.02, 1.0)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("share of each source's questions")
    fs.vgrid(ax)
    ax.tick_params(axis="y", length=0)
    from matplotlib.lines import Line2D
    fig.legend(handles=[Line2D([], [], marker="o", linestyle="", color=OWN, markersize=4.5,
                               label=f"participants' own questions (n = {n_own})"),
                        Line2D([], [], marker="o", linestyle="", color=CORPUS, markersize=4.5,
                               label=f"corpus questions (n = {n_cor})")],
               loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=2, fontsize=6.2, handlelength=0.8)
    stamp(fig, src)
    fs.save(fig, OUT, "fig14alt_fresh_vs_corpus")
    print("written: fig14_fresh_vs_corpus, fig14alt_fresh_vs_corpus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
