"""Combined, space-efficient figures for the IMWUT paper.

Reads the same Phase A-I output tables as the standalone figures and emits
merged multi-panel versions sized for a single-column acmsmall text block.
Does not modify any existing analysis output.

Output: paper/figures/fig_*.pdf
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator

BASE = Path(__file__).resolve().parents[1]
TABLES = BASE / "outputs" / "tables"
CORPUS = BASE / "corpus" / "classified_corpus.csv"
OUT = BASE.parent / "figures"
OUT.mkdir(exist_ok=True)

TEXTWIDTH = 5.5  # acmsmall single-column text width, inches

plt.rcParams.update({
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})

BLUE, ORANGE, GREEN, RED = "#3465a4", "#e07b39", "#4b9b6e", "#c0504d"


def save(fig, name):
    p = OUT / name
    fig.savefig(p)
    plt.close(fig)
    print(f"  wrote {p.relative_to(BASE.parent.parent)}")


# ---------------------------------------------------------------- Figure A
# Panel 1: participants per persona.  Panel 2: questions per domain.
def fig_persona_and_domain():
    dem = pd.read_csv(TABLES / "A2_demographics_table.csv")
    dem = dem.sort_values("users")
    stats = pd.read_csv(TABLES / "B4_corpus_statistics.csv")
    dom = stats[stats["dimension"] == "domain_l1"].sort_values("n").tail(14)

    fig, (a, b) = plt.subplots(1, 2, figsize=(TEXTWIDTH, 2.45))

    short = {
        "Health and Safety Officers": "H&S Officers",
        "Sustainability and Energy Management Teams": "Sustainability",
        "Student": "Students",
        "IT": "IT Professionals",
    }
    labels = [short.get(x, x) for x in dem["PrimaryPersona"]]
    a.barh(labels, dem["users"], height=0.62, color=BLUE)
    for y, (u, q) in enumerate(zip(dem["users"], dem["questions"])):
        a.text(u + 0.4, y, f"{u}", va="center", fontsize=6.5, color="black")
    a.set_xlabel("Participants")
    a.set_title("(a) Participants per persona ($N$=96)", loc="left")
    a.set_xlim(0, dem["users"].max() * 1.18)

    b.barh(dom["code"].str.replace("_", " ").str.title(), dom["n"],
           height=0.62, color=ORANGE)
    for y, n in enumerate(dom["n"]):
        b.text(n + 18, y, f"{n:,}", va="center", fontsize=6.5)
    b.set_xlabel("Questions")
    b.set_title("(b) Questions per domain ($N$=7,151)", loc="left")
    b.set_xlim(0, dom["n"].max() * 1.22)

    fig.tight_layout(w_pad=1.4)
    save(fig, "fig_persona_and_domain.pdf")


# ---------------------------------------------------------------- Figure B
# Panel 1: novelty decline.  Panel 2: complexity mix, both by stage.
def fig_novelty_and_complexity():
    nov = pd.read_csv(TABLES / "C3_novelty_analysis.csv")
    df = pd.read_csv(CORPUS)
    cx = (df.groupby(["Stage", "complexity"]).size()
            .unstack(fill_value=0))
    cx = cx.div(cx.sum(axis=1), axis=0) * 100

    fig, (a, b) = plt.subplots(1, 2, figsize=(TEXTWIDTH, 2.25))
    stages = ["S1", "S2", "S3", "S4"]

    a.plot(stages, nov["pct_novel"], marker="o", color=GREEN, lw=1.8, ms=5)
    for x, v in zip(stages, nov["pct_novel"]):
        a.annotate(f"{v:.1f}", (x, v), textcoords="offset points",
                   xytext=(0, 7), ha="center", fontsize=6.5)
    a.set_ylabel("Semantically novel (%)")
    a.set_ylim(nov["pct_novel"].min() - 6, nov["pct_novel"].max() + 7)
    a.set_title("(a) Question novelty declines with context", loc="left")
    a.grid(axis="y", alpha=0.25, lw=0.5)

    order = ["LOOKUP", "AGGREGATION", "MULTI_STEP"]
    cols = [BLUE, ORANGE, RED]
    bottom = [0.0] * len(cx)
    for col, c in zip(order, cols):
        if col not in cx:
            continue
        b.bar(stages, cx[col], bottom=bottom, color=c, width=0.6,
              label=col.replace("_", "-").title())
        bottom = [x + y for x, y in zip(bottom, cx[col])]
    b.set_ylabel("Share of stage (%)")
    b.set_ylim(0, 100)
    b.set_title("(b) Complexity mix by stage", loc="left")
    b.legend(frameon=False, loc="lower left", ncol=1, bbox_to_anchor=(0.02, 0.02))

    fig.tight_layout(w_pad=1.6)
    save(fig, "fig_novelty_and_complexity.pdf")


# ---------------------------------------------------------------- Figure C
# Borda priority vs L4 analytical demand — larger type, shorter.
def fig_borda_vs_l4():
    d = pd.read_csv(TABLES / "I1_borda_vs_l4_demand.csv")
    fig, ax = plt.subplots(figsize=(TEXTWIDTH, 2.7))
    ax.scatter(d["Borda"], d["PctL4First"], s=d["n_rankers"] * 3.2,
               c=d["Color"], alpha=0.75, edgecolors="white", linewidths=0.8,
               zorder=3)
    for _, r in d.iterrows():
        ax.annotate(r["ShortLabel"], (r["Borda"], r["PctL4First"]),
                    textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=6.4, color="black")
    med = d["Borda"].median()
    ax.axvline(med, color="black", lw=0.7, ls=":", alpha=0.5, zorder=1)
    ax.text(med, ax.get_ylim()[1], " median priority", fontsize=6.2,
            va="top", ha="left", color="black", alpha=0.7)
    ax.set_xlabel("Borda priority score")
    ax.set_ylabel("Rankers preferring L4 first (%)")
    ax.set_ylim(8, 62)
    ax.grid(alpha=0.22, lw=0.5, zorder=0)
    ax.set_title(r"Priority and analytical demand are unrelated "
                 r"(Spearman $\rho=-0.25$, $p=0.29$)", loc="left", fontsize=8)
    fig.tight_layout()
    save(fig, "fig_borda_vs_l4.pdf")


# ---------------------------------------------------------------- Figure D
# Panel 1: answer rate by stage.  Panel 2: domain x complexity coverage.
def fig_coverage():
    h5 = pd.read_csv(TABLES / "H5_answer_rate_by_stage.csv")
    h7 = pd.read_csv(TABLES / "H7_domain_complexity_heatmap.csv")
    h7 = h7.assign(total=h7[["LOOKUP_N", "AGGREGATION_N", "MULTI_STEP_N"]].sum(axis=1))
    h7 = h7.nlargest(13, "total").iloc[::-1]

    fig, (a, b) = plt.subplots(1, 2, figsize=(TEXTWIDTH, 2.9),
                               gridspec_kw={"width_ratios": [1.0, 1.15]})
    stages = ["S1", "S2", "S3", "S4"]
    x = range(4)
    lo = h5["Answer_rate_pct"] - h5["AR_CI_lo"]
    hi = h5["AR_CI_hi"] - h5["Answer_rate_pct"]
    a.errorbar(x, h5["Answer_rate_pct"], yerr=[lo, hi], marker="o", color=BLUE,
               lw=1.8, ms=5, capsize=3, label="Answered")
    a.plot(x, h5["Grounded_rate_pct"], marker="s", color=GREEN, lw=1.8, ms=4.5,
           ls="--", label="Data-grounded")
    a.set_xticks(list(x))
    a.set_xticklabels(stages)
    a.set_ylabel("Rate (%)")
    a.set_ylim(10, 82)
    a.grid(axis="y", alpha=0.25, lw=0.5)
    a.legend(frameon=False, loc="center left", fontsize=6.8)
    a.set_title("(a) Coverage by elicitation stage", loc="left")

    mat = h7[["LOOKUP_AR_pct", "AGGREGATION_AR_pct", "MULTI_STEP_AR_pct"]].values
    im = b.imshow(mat, cmap="RdYlGn", vmin=35, vmax=95, aspect="auto")
    b.set_xticks(range(3))
    b.set_xticklabels(["L1\nLookup", "L2\nAggreg.", "L3\nMulti"], fontsize=6.6)
    b.set_yticks(range(len(h7)))
    b.set_yticklabels([d.replace("_", " ").title() for d in h7["Domain"]],
                      fontsize=6.2)
    for i in range(len(h7)):
        for j in range(3):
            b.text(j, i, f"{mat[i, j]:.0f}", ha="center", va="center",
                   fontsize=5.8, color="black")
    b.set_title("(b) Answer rate by domain and complexity", loc="left")
    cb = fig.colorbar(im, ax=b, fraction=0.04, pad=0.03)
    cb.ax.tick_params(labelsize=6)
    cb.set_label("Answer rate (%)", fontsize=6.5)

    fig.tight_layout(w_pad=1.2)
    save(fig, "fig_coverage.pdf")


# ---------------------------------------------------------------- Figure E
# Intent x domain heatmap, shorter than the original.
def fig_intent_heatmap():
    df = pd.read_csv(CORPUS)
    t = pd.crosstab(df["domain_l1"], df["intent"])
    t = t.loc[t.sum(axis=1).nlargest(14).index]
    t = t.iloc[::-1]
    order = [c for c in ["INFORMATIONAL", "DIAGNOSTIC", "PRESCRIPTIVE",
                         "PREDICTIVE"] if c in t.columns]
    t = t[order]

    fig, ax = plt.subplots(figsize=(TEXTWIDTH, 2.85))
    pct = t.div(t.sum(axis=1), axis=0) * 100
    im = ax.imshow(pct.values, cmap="Blues", aspect="auto", vmin=0, vmax=100)
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([c.title() for c in order], fontsize=7)
    ax.set_yticks(range(len(t)))
    ax.set_yticklabels([d.replace("_", " ").title() for d in t.index], fontsize=6.4)
    for i in range(len(t)):
        for j in range(len(order)):
            v = t.values[i, j]
            if v:
                ax.text(j, i, f"{v:,}", ha="center", va="center", fontsize=5.8,
                        color="white" if pct.values[i, j] > 55 else "black")
    ax.set_title("Intent distribution within each domain (cell = question count)",
                 loc="left", fontsize=8)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.ax.tick_params(labelsize=6)
    cb.set_label("Row share (%)", fontsize=6.5)
    fig.tight_layout()
    save(fig, "fig_intent_heatmap.pdf")


if __name__ == "__main__":
    print("Generating combined paper figures ->", OUT)
    fig_persona_and_domain()
    fig_novelty_and_complexity()
    fig_borda_vs_l4()
    fig_coverage()
    fig_intent_heatmap()
    print("done.")
