# -*- coding: utf-8 -*-
"""make_v4_pipeline_figure.py — V4-T36 figure: OntoSage pipeline before vs after.

Renders tasks/figures/v4_pipeline_before_after.png for the progress-meeting
brief. Pure matplotlib, no stack dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "tasks" / "figures"

GREY = "#9AA3AE"
DARK = "#3B4552"
TEAL = "#0E7C7B"
BLUE = "#2563EB"
ORANGE = "#D97706"
GREEN = "#15803D"
RED = "#B91C1C"
LIGHT = "#F3F4F6"


def box(ax, x, y, w, h, text, fc=LIGHT, ec=DARK, fontsize=8.3, bold=False, tc=None):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.012",
            linewidth=1.4,
            edgecolor=ec,
            facecolor=fc,
            zorder=2,
        )
    )
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        zorder=3,
        color=tc or DARK,
        fontweight="bold" if bold else "normal",
        wrap=True,
    )


def arrow(ax, x1, y1, x2, y2, color=DARK, style="-|>", lw=1.6, ls="-"):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle=style,
            mutation_scale=13,
            linewidth=lw,
            color=color,
            linestyle=ls,
            zorder=1,
        )
    )


def main() -> int:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13.5, 11.5), height_ratios=[1, 1.5])
    for ax in (ax1, ax2):
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")

    # ── BEFORE ────────────────────────────────────────────────────────────────
    ax1.set_title(
        "BEFORE V4 — reflex pipelines only (2026-08-12)",
        fontsize=13,
        fontweight="bold",
        color=DARK,
        loc="left",
    )
    box(ax1, 2, 62, 13, 16, "User\nquestion", fc="#E8EEF7", bold=True)
    box(ax1, 20, 62, 16, 16, "Dialogue\n(LLM intent +\nentities)")
    box(ax1, 41, 62, 10, 16, "Router")
    box(ax1, 56, 74, 30, 11, "DATA lane:\nSPARQL → SQL → Analytics → Viz")
    box(ax1, 56, 58, 30, 11, "STANDALONE lane:\ncapability / floor-plan / spatial / reports")
    box(ax1, 90, 64, 8.5, 16, "Answer", fc="#E8EEF7", bold=True)
    arrow(ax1, 15, 70, 20, 70)
    arrow(ax1, 36, 70, 41, 70)
    arrow(ax1, 51, 72, 56, 79)
    arrow(ax1, 51, 68, 56, 64)
    arrow(ax1, 86, 79, 90, 74)
    arrow(ax1, 86, 63, 90, 69)

    box(
        ax1,
        4,
        8,
        92,
        40,
        "What could NOT happen:\n"
        '• Multi-constraint ranking ("quiet + good air + near water") had NO route → '
        'deflected to capability: "I don\'t have that information on record"\n'
        "• Per-room coverage: most modalities 0% (bldg1: 5 of 8 at 0%; bldg2/bldg3: 7 of 8 at 0%)\n"
        '• No amenity locations, no room-geometry bridge → "near X" unanswerable\n'
        "• No proof: answers carried no evidence trail; LLM prose could carry unverified numbers",
        fc="#FDF2F2",
        ec=RED,
        fontsize=9.2,
        tc=RED,
    )

    # ── AFTER ─────────────────────────────────────────────────────────────────
    ax2.set_title(
        "AFTER V4 — reflex lanes kept + ARBITER deliberative brain + SATURATE (2026-08-14)",
        fontsize=13,
        fontweight="bold",
        color=DARK,
        loc="left",
    )
    box(ax2, 1, 74, 11, 12, "User\nquestion", fc="#E8EEF7", bold=True)
    box(ax2, 15, 74, 13, 12, "Dialogue\n(LLM intent)")
    box(ax2, 31, 74, 12, 12, "Routing\ncontract\n(pinned rules)")
    box(ax2, 47, 84, 25, 8, "Reflex lanes (unchanged)", fc="#EFEFEF")
    box(ax2, 90, 74, 9, 12, "Answer\n+ proof", fc="#E6F4EA", ec=GREEN, bold=True)
    arrow(ax2, 12, 80, 15, 80)
    arrow(ax2, 28, 80, 31, 80)
    arrow(ax2, 43, 82, 47, 87)
    arrow(ax2, 72, 88, 94, 86, color=GREY)

    # deliberative lane
    box(
        ax2,
        2,
        56,
        14,
        12,
        "CQ-IR compiler\n(ONE temp-0 LLM call\n→ typed constraints)",
        fc="#E7F6F6",
        ec=TEAL,
    )
    box(ax2, 19, 56, 15, 12, "Admission gate\nvs LIVE capability\nschema", fc="#E7F6F6", ec=TEAL)
    box(
        ax2,
        37,
        56,
        15,
        12,
        "Candidates +\ncoverage ledger\n(excluded + why)",
        fc="#E7F6F6",
        ec=TEAL,
    )
    box(
        ax2,
        55,
        56,
        14,
        12,
        "Fetch + aggregate\n(per-UUID, narrow\ntables, forecast)",
        fc="#E7F6F6",
        ec=TEAL,
    )
    box(
        ax2,
        72,
        56,
        13,
        12,
        "Deterministic scorer\nWHO / ASHRAE bands\n(LLM: no numbers)",
        fc="#E7F6F6",
        ec=TEAL,
    )
    box(
        ax2,
        88,
        54,
        11,
        16,
        "Evidence dossier\n+ NUMERIC GUARD\n(every number must\nexist in evidence)",
        fc="#E6F4EA",
        ec=GREEN,
        fontsize=7.6,
    )
    arrow(ax2, 37, 74, 9, 68, color=TEAL)  # router -> deliberate
    arrow(ax2, 16, 62, 19, 62, color=TEAL)
    arrow(ax2, 34, 62, 37, 62, color=TEAL)
    arrow(ax2, 52, 62, 55, 62, color=TEAL)
    arrow(ax2, 69, 62, 72, 62, color=TEAL)
    arrow(ax2, 85, 62, 88, 62, color=TEAL)
    arrow(ax2, 94, 70, 94, 74, color=GREEN)

    # ask / decline offshoots
    box(
        ax2,
        19,
        40,
        15,
        10,
        "ASK one question\n(concrete options,\nplan parks + resumes)",
        fc="#FFF7E6",
        ec=ORANGE,
        fontsize=7.8,
    )
    box(
        ax2,
        2,
        40,
        14,
        10,
        "HONEST DECLINE\n(names what the\nbuilding DOES sense)",
        fc="#FFF7E6",
        ec=ORANGE,
        fontsize=7.8,
    )
    arrow(ax2, 26, 56, 26, 50, color=ORANGE)
    arrow(ax2, 20, 56, 10, 50, color=ORANGE)

    # saturate + stores
    box(
        ax2,
        38,
        34,
        47,
        14,
        "SATURATE (offline, per building, same scripts):\n"
        "coverage audit → provision simulated sensors (isSimulated)\n"
        "→ narrow-table backfill + live publisher\n"
        "→ amenity locations + room-geometry bridge",
        fc="#FFF3E6",
        ec=ORANGE,
        fontsize=7.8,
    )
    box(
        ax2,
        38,
        18,
        22,
        11,
        "GraphDB (Brick TTL)\n3 buildings: 100% × 8 modalities",
        fc="#EEF2FF",
        ec=BLUE,
        fontsize=8.0,
    )
    box(
        ax2,
        63,
        18,
        22,
        11,
        "MySQL narrow tables\n366 / 927 / 1,363 sat sensors\n1.84M / 4.67M / 6.87M rows",
        fc="#EEF2FF",
        ec=BLUE,
        fontsize=8.0,
    )
    arrow(ax2, 52, 34, 48, 29, color=ORANGE)
    arrow(ax2, 70, 34, 74, 29, color=ORANGE)
    arrow(ax2, 48, 29, 44, 56, color=BLUE, ls=":")  # graph feeds candidates
    arrow(ax2, 74, 29, 62, 56, color=BLUE, ls=":")  # rows feed fetch

    box(
        ax2,
        2,
        1,
        97,
        13,
        "Measured: flagship multi-constraint question answered on ALL 3 buildings with dossier\n"
        "FABRICATED = 0 in every benchmark run\n"
        "Ablations: LLM-ranks-rows 6/15 top-1 + 9 invented values · generic ReAct agent 0/15 + 6 invented · "
        "ARBITER: 0 invented, every answer guarded",
        fc="#E6F4EA",
        ec=GREEN,
        fontsize=8.4,
        tc=GREEN,
    )

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "v4_pipeline_before_after.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"[figure] -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
