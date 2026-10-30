#!/usr/bin/env python3
"""Qualitative figures from the Part C codebook codes (plan 04 section 3 themes).

    python figures/fig_qual.py

Reads results/qual/ (qual_analysis.py). Writes figures/out/:
  fig12_reason_codes        (a) people (of 30) per code in the per-task reasons, then the closing-answer codes and the
                            inductive tags held by five or more people; one series, counts at the bar ends.
                            (b) reasons that took a refusal as the answer, after a wrong refusal (FD) and after a
                            correct one (WL), split by whether the decision was then correct.
  fig12alt_refusal_accepted  panel (b) alone (half width)
PROVISIONAL stamp while the codes are AI pre-codes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fig_style as fs  # noqa: E402
from study_paths import RESULTS  # noqa: E402

OUT = HERE / "out"
Q = RESULTS / "qual"
REASONS = ["LIMIT_RECOGNISED", "VERIFY_INTENDED", "EVIDENCE_CITED", "DECLINE_ACCEPTED", "FLUENCY_CUE", "REPHRASED",
           "DECLINE_FRUSTRATION", "PRIOR_KNOWLEDGE", "PROXY_ACCEPTED"]
CLOSING = ["USEFUL_EVIDENCE", "USEFUL_EASE", "FRUST_DECLINES", "FRUST_NEEDED_REPHRASING"]
TAGS = ["believed_the_absence", "blamed_missing_data", "chose_b_without_people_fact"]
NAMES = {"LIMIT_RECOGNISED": "named a limit of the answer", "VERIFY_INTENDED": "would check elsewhere",
         "EVIDENCE_CITED": "cited what the answer showed", "DECLINE_ACCEPTED": "took a refusal as the answer",
         "FLUENCY_CUE": "trusted detail or a confident tone", "REPHRASED": "asked again in other words",
         "DECLINE_FRUSTRATION": "frustrated by a refusal", "PRIOR_KNOWLEDGE": "went on prior expectations",
         "PROXY_ACCEPTED": "accepted a related reading",
         "USEFUL_EVIDENCE": "useful: the evidence and sources", "USEFUL_EASE": "useful: clear, well written",
         "FRUST_DECLINES": "frustrating: refusals, no data", "FRUST_NEEDED_REPHRASING": "frustrating: had to rephrase",
         "believed_the_absence": "took 'no data' at face value",
         "blamed_missing_data": "blamed refusals on missing data",
         "chose_b_without_people_fact": "S4-3 (b): 'no people count'"}


def stamp(fig, src: str) -> None:
    if src != "HUMAN_AGREED":
        text = ("PROVISIONAL: codes checked by the first author only; agreement with a second coder pending"
                if src == "AUTHOR_CHECKED" else "PROVISIONAL: codes are AI pre-codes, not yet human-coded")
        fig.text(0.995, 0.998, text, ha="right", va="top", fontsize=5.8, color=fs.OKABE["vermillion"], style="italic")


def people(c: pd.DataFrame, code: str, material: str) -> int:
    r = c[(c.code == code) & (c.material == material)]
    return int(r.people.max()) if len(r) else 0


def panel_codes(ax, c: pd.DataFrame) -> None:
    groups = [("per-task reasons", [(k, people(c, k, "task reasons")) for k in REASONS]),
              ("closing answers", [(k, max(people(c, k, m) for m in ("CL1", "CL2", "CL3"))) for k in CLOSING]),
              ("tags", [(k, people(c, k, "all")) for k in TAGS])]
    y, ys, labs, vals, heads = 0.0, [], [], [], []
    for gi, (head, items) in enumerate(groups):
        if gi:
            y += 1.4            # room for the group heading
        heads.append((y, head))
        for k, v in items:
            ys.append(y)
            labs.append(NAMES.get(k, k))
            vals.append(v)
            y += 1
    ax.barh(ys, [v / 30 for v in vals], height=0.62, color=fs.SINGLE)
    for yi, v in zip(ys, vals):
        ax.text(v / 30 + 0.012, yi, f"{v}/30", va="center", fontsize=6.1, color=fs.INK2)
    ax.set_yticks(ys)
    ax.set_yticklabels(labs)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.12)
    ax.set_xticks([0, .5, 1])
    ax.set_xticklabels(["0", "50%", "100%"])
    ax.set_xlabel("participants with the code")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    fs.vgrid(ax)
    for yh, head in heads:
        ax.text(-0.01, yh - 1.05, head, transform=ax.get_yaxis_transform(), ha="right", fontsize=6.2, color=fs.INK2,
                style="italic")


def panel_refusal(ax) -> None:
    t = pd.read_csv(Q / "decline_accepted.csv").set_index("answer_received")
    rows = [("FD", "after a wrong\nrefusal (FD)"), ("WL", "after a correct\nrefusal or limit (WL)")]
    y = np.arange(len(rows))
    for yi, (lab, name) in zip(y, rows):
        n = int(t.loc[lab, "n"])
        acc, ok = int(t.loc[lab, "decline_accepted"]), int(t.loc[lab, "decline_accepted_and_correct"])
        parts = [(ok, fs.DECISION_COL["warranted"], "took it as the answer, decision correct"),
                 (acc - ok, fs.DECISION_COL["under-reliance (could not find out)"], "took it as the answer, decision wrong"),
                 (n - acc, "#d9d9d9", "did not take it as the answer")]
        left = 0
        for v, col, lbl in parts:
            ax.barh(yi, v / n, left=left, height=0.5, color=col, edgecolor="white", linewidth=0.8,
                    label=lbl if yi == 0 else None)
            if v >= 3:
                ax.text(left + v / n / 2, yi, str(v), ha="center", va="center", fontsize=6.2,
                        color="white" if col == fs.DECISION_COL["warranted"] else fs.INK)
            left += v / n
        ax.text(1.02, yi, f"n={n}", va="center", fontsize=6.1, color=fs.INK2)
    ax.set_yticks(y)
    ax.set_yticklabels([r[1] for r in rows])
    ax.set_ylim(len(rows) - 0.4, -0.6)          # inverted, with the two bars kept close together
    ax.set_xlim(0, 1)
    ax.set_xticks([0, .5, 1])
    ax.set_xticklabels(["0", "50%", "100%"])
    ax.set_xlabel("reasons written after that answer")
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.3, -0.5), ncol=1, handlelength=1.0, fontsize=6.0)


def main() -> int:
    fs.setup()
    c = pd.read_csv(Q / "code_counts.csv")
    src = c.label_source.iloc[0]
    fig = fs.plt.figure(figsize=(fs.FULL, 3.3))
    # fixed margins keep the whole figure at the text width, so it prints at 100% (a tight box around the long
    # labels made it 7.3 in, which LaTeX shrank to 75%)
    gs = fig.add_gridspec(2, 2, width_ratios=[1.3, 1], height_ratios=[1, 1.35], wspace=0.85, hspace=0.6,
                          left=0.31, right=0.935, top=0.9, bottom=0.13)
    a = fig.add_subplot(gs[:, 0])
    b = fig.add_subplot(gs[0, 1])               # (b) takes the top half; its legend fills the space below
    panel_codes(a, c)
    fs.panel_label(a, "(a)")
    panel_refusal(b)
    fs.panel_label(b, "(b)")
    stamp(fig, src)
    fs.save(fig, OUT, "fig12_reason_codes")
    fig, ax = fs.plt.subplots(figsize=(fs.HALF, 1.6))
    panel_refusal(ax)
    stamp(fig, src)
    fs.save(fig, OUT, "fig12alt_refusal_accepted")
    print("written: fig12_reason_codes, fig12alt_refusal_accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
