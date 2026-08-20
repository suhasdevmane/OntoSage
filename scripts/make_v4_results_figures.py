# -*- coding: utf-8 -*-
"""make_v4_results_figures.py — V4-T36: thesis-chapter figures from archived CSVs.

Generates into tasks/figures/:
  v4_coverage_before_after.png   3 buildings x 8 modalities, pre vs post SATURATE
  v4_fabrication_ablation.png    invented values + top-1 by architecture arm

Reproducible: reads only archived run artifacts (scripts/outputs/*).
"""

from __future__ import annotations

import csv
import glob
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

_REPO = Path(__file__).resolve().parents[1]
_COV = _REPO / "scripts" / "outputs" / "coverage"
_L7 = _REPO / "scripts" / "outputs" / "l7"
_FIG = _REPO / "tasks" / "figures"

# before/after audit CSV per building (first pre-saturation, last post-saturation)
_PAIRS = {
    "bldg1": ("coverage_bldg1_20260814_044200.csv", "coverage_bldg1_20260814_045340.csv"),
    # 200023 was an empty-graph audit (mid-swap); 200222 is the true pre state
    "bldg2": ("coverage_bldg2_20260813_200222.csv", "coverage_bldg2_20260813_204536.csv"),
    "bldg3": ("coverage_bldg3_20260814_035556.csv", "coverage_bldg3_20260814_040045.csv"),
}

MODALITIES = [
    "temperature",
    "humidity",
    "co2",
    "occupancy",
    "noise",
    "illuminance",
    "door_contact",
    "window_contact",
]


def _coverage(path: Path):
    """modality -> present-fraction from a coverage audit CSV."""
    present = defaultdict(int)
    total = defaultdict(int)
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        m = r["modality"]
        total[m] += 1
        if r["status"] == "present":
            present[m] += 1
    return {m: (present[m] / total[m] if total[m] else 0.0) for m in total}


def fig_coverage():
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), sharey=True)
    for ax, (bid, (pre_f, post_f)) in zip(axes, _PAIRS.items()):
        pre = _coverage(_COV / pre_f)
        post = _coverage(_COV / post_f)
        xs = range(len(MODALITIES))
        ax.bar(
            [x - 0.2 for x in xs],
            [100 * pre.get(m, 0) for m in MODALITIES],
            width=0.4,
            label="before",
            color="#C4CBD4",
        )
        ax.bar(
            [x + 0.2 for x in xs],
            [100 * post.get(m, 0) for m in MODALITIES],
            width=0.4,
            label="after SATURATE",
            color="#0E7C7B",
        )
        ax.set_title(bid, fontweight="bold")
        ax.set_xticks(list(xs))
        ax.set_xticklabels([m.replace("_", "\n") for m in MODALITIES], fontsize=7.5)
        ax.set_ylim(0, 105)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("rooms covered (%)")
    axes[0].legend(loc="upper left", fontsize=9)
    fig.suptitle(
        "Per-room sensor coverage before vs after SATURATE (same scripts, all buildings)",
        fontweight="bold",
    )
    fig.tight_layout()
    out = _FIG / "v4_coverage_before_after.png"
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"[figure] -> {out}")


def _arm(pattern, top1_key="top1_match"):
    hits = sorted(glob.glob(str(_L7 / pattern)))
    if not hits:
        return None
    rows = list(csv.DictReader(open(hits[-1], encoding="utf-8-sig")))
    return {
        "n": len(rows),
        "top1": sum(1 for r in rows if r.get(top1_key) == "True"),
        "invented": sum(int(r.get("invented_values", 0) or 0) for r in rows),
    }


def fig_ablation():
    llm = _arm("ablation_llm_ranked_*.csv")
    loop = _arm("ablation_agent_loop_*.csv")
    # ARBITER: newest bldg3 generated bank (all fixes active)
    gen = sorted(glob.glob(str(_L7 / "l7_graded_bldg3_*.csv")))
    arb = None
    for p in reversed(gen):
        rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
        if len(rows) <= 50:
            arb = {
                "n": len(rows),
                "top1": sum(1 for r in rows if r.get("top1_match") == "True"),
                "invented": sum(1 for r in rows if r.get("grade") == "fabricated"),
            }
            break
    arms = [
        ("LLM ranks\nhanded rows", llm),
        ("Generic ReAct\nagent + tools", loop),
        ("ARBITER\n(system)", arb),
    ]
    arms = [(label, a) for label, a in arms if a]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2))
    labels = [label for label, _ in arms]
    top1_pct = [100 * a["top1"] / a["n"] for _, a in arms]
    invented = [a["invented"] for _, a in arms]
    colors = ["#C4CBD4", "#C4CBD4", "#0E7C7B"]
    ax1.bar(labels, top1_pct, color=colors[: len(arms)])
    ax1.set_title("top-1 agreement with independent\nground truth (%)", fontsize=10)
    ax1.set_ylim(0, 100)
    ax1.grid(axis="y", alpha=0.3)
    for i, v in enumerate(top1_pct):
        ax1.text(i, v + 2, f"{v:.0f}%", ha="center", fontweight="bold")
    ax2.bar(labels, invented, color=["#B91C1C", "#B91C1C", "#15803D"][: len(arms)])
    ax2.set_title("invented (fabricated) values\nacross the run", fontsize=10)
    ax2.grid(axis="y", alpha=0.3)
    for i, v in enumerate(invented):
        ax2.text(i, v + 0.15, str(v), ha="center", fontweight="bold")
    fig.suptitle(
        "Same model, same tasks, same ground truth — the architecture does the work",
        fontweight="bold",
    )
    fig.tight_layout()
    out = _FIG / "v4_fabrication_ablation.png"
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"[figure] -> {out}")


def main() -> int:
    _FIG.mkdir(parents=True, exist_ok=True)
    fig_coverage()
    fig_ablation()
    return 0


if __name__ == "__main__":
    sys.exit(main())
