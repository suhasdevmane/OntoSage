"""One figure style for every Paper 3 figure (ACM acmsmall, IMWUT).

Sizes follow acmsmall's text width (about 5.48 in): FULL for a full-width figure, HALF for one of two figures side
by side (\\begin{subfigure}{0.49\\linewidth}), THIRD for three across. Fonts are embedded (TrueType, fonttype 42) so
the PDF passes ACM's checks. Edit the constants here to restyle every figure at once.

Colour. Every palette below was run through the dataviz validator (validate_palette.js, light mode, white surface)
on 24 Oct 2026; results are recorded beside each one. Rules kept: a single series gets one colour (slot 1) and the
axis names its categories; colours follow the category, never its rank; text is never drawn in a series colour;
every figure has a table twin (the CSV in results/), which is the relief the validator asks for where a hue is
under 3:1 against white.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

FULL, HALF, THIRD = 5.48, 2.68, 1.76      # inches
OKABE = {"blue": "#0072B2", "orange": "#E69F00", "green": "#009E73", "vermillion": "#D55E00",
         "sky": "#56B4E9", "purple": "#CC79A7", "yellow": "#F0E442", "black": "#000000", "grey": "#7F7F7F"}
INK, INK2, MUTED, GRID = "#1a1a1a", "#4d4d4d", "#808080", "#e6e6e6"   # text tokens + hairline grid
SINGLE = OKABE["blue"]                     # one-series figures (slot 1)

# answer labels, in this order. Validator: all PASS; worst adjacent CVD dE 13.1 (deutan), normal-vision 15.6;
# contrast WARN for WL (2.31:1) and FD (2.25:1) -> every figure using them carries labels + a table twin.
LABEL_ORDER = ["W", "WL", "FD", "U", "OT"]
LABEL_COL = {"W": OKABE["blue"], "WL": OKABE["sky"], "FD": OKABE["orange"], "U": OKABE["vermillion"],
             "OT": OKABE["purple"], "PF": "#000000", "none": "#bdbdbd"}
# Words a reader sees are plain words (plan 08 section B.4, the third author 13 Oct): the data and the codebook keep their own
# terms (W, WL, warranted, ...), and only the display text below changes, so every figure changes together.
CORRECT = "decisions the data support"            # value-axis name; captions define it once
LABEL_NAME = {"W": "W  supported by the data", "WL": "WL states its limits", "FD": "FD wrong refusal",
              "U": "U  not supported by the data", "OT": "OT answers something else", "PF": "PF system failure",
              "none": "no answer before deciding"}
LABEL_SHORT = {"W": "W", "WL": "WL", "FD": "FD", "U": "U", "OT": "OT", "none": "none"}

# what a participant decided. "warranted, no conclusion" is S3's "I could not find out", which the key counts as
# warranted (the pre-registered S3 split). Validator (5 slots, this order): all PASS; worst adjacent CVD dE 15.8,
# normal-vision 16.4; contrast WARN for sky (2.31:1) and orange (2.25:1) -> labelled + table twin. A lighter blue
# step (#9CCBE8) was tried first and FAILED lightness and chroma.
DECISION_ORDER = ["warranted", "warranted, no conclusion", "under-reliance (could not find out)",
                  "false absence or limit", "accepted an unsupported claim"]
DECISION_COL = {"warranted": OKABE["blue"], "warranted, no conclusion": OKABE["sky"],
                "under-reliance (could not find out)": OKABE["orange"], "false absence or limit": OKABE["purple"],
                "accepted an unsupported claim": OKABE["vermillion"]}
DECISION_NAME = {"warranted": "the decision the data support",
                 "warranted, no conclusion": "S3: 'could not find out' (also correct)",
                 "under-reliance (could not find out)": "'could not find out', though the data held it",
                 "false absence or limit": "'not recorded', though it is",
                 "accepted an unsupported claim": "a statement the data do not support"}

# 5-point agree/helpful scales: a diverging pair (warm low, cool high) with a neutral grey midpoint
DIVERGING5 = ["#D55E00", "#F0B090", "#D0D0D0", "#9CCBE8", "#0072B2"]

SIT_NAME = {"S1": "S1 data hold the answer", "S2": "S2 data hold part of it", "S3": "S3 data do not hold it",
            "S4": "S4 two facts to combine"}
SIT_SHORT = {"S1": "S1\nall held", "S2": "S2\npart held", "S3": "S3\nnot held", "S4": "S4\ntwo facts"}
SIT_STACK = {"S1": "S1\ndata hold\nthe answer", "S2": "S2\ndata hold\npart of it", "S3": "S3\ndata do not\nhold it",
             "S4": "S4\ntwo facts\nto combine"}
SYSTEM_NAME = {"A": "OntoSage+", "B": "Assistant B", "A-minus": "OntoSage+,\ntwo checks off"}


def setup() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 7.5, "axes.titlesize": 8, "axes.labelsize": 7.5,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.8, "legend.frameon": False,
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
        "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5,
        "ytick.major.size": 2.5, "lines.linewidth": 1.2, "errorbar.capsize": 2.0, "pdf.fonttype": 42,
        "ps.fonttype": 42, "savefig.bbox": "tight", "savefig.pad_inches": 0.03, "figure.dpi": 150,
        "axes.grid": False, "grid.color": GRID, "grid.linewidth": 0.5, "grid.linestyle": "-",
    })


def hgrid(ax) -> None:
    """Recessive solid hairline grid on the value axis only."""
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, linewidth=0.5)


def vgrid(ax) -> None:
    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color=GRID, linewidth=0.5)


def save(fig, folder: Path, name: str) -> list:
    """Write <name>.pdf (vector, for the paper) and <name>.png (300 dpi, for review); returns the paths."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / f"{name}.pdf", folder / f"{name}.png"]
    fig.savefig(paths[0])
    fig.savefig(paths[1], dpi=300)
    plt.close(fig)
    return paths


def panel_label(ax, text: str) -> None:
    """(a), (b) ... in the top-left corner, for combined figures."""
    ax.text(-0.02, 1.04, text, transform=ax.transAxes, fontsize=8, fontweight="bold", va="bottom", ha="right")


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"
