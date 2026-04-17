"""Phase B4 — Corpus statistics from the classified corpus.

Inputs:  corpus/classified_corpus.csv (Phase B2 output)
Outputs:
  outputs/tables/B4_corpus_statistics.csv     — long-form (dimension, code, n, pct)
  outputs/tables/B4_domain_by_stage.csv       — Stage × Domain percentages
  outputs/tables/B4_intent_by_complexity.csv  — Intent × Complexity counts
  outputs/figures/B4_domain_distribution.{png,pdf}
  outputs/figures/B4_intent_heatmap.{png,pdf}
  outputs/figures/B4_complexity_by_stage.{png,pdf}
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CORPUS = ROOT / "corpus"

DIMENSIONS = [
    "domain_l1",
    "query_type_l2",
    "intent",
    "temporal",
    "spatial",
    "complexity",
]


def long_form_stats(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    n_total = len(df)
    for dim in DIMENSIONS:
        counts = df[dim].value_counts(dropna=False)
        for code, n in counts.items():
            rows.append(
                {
                    "dimension": dim,
                    "code": code,
                    "n": int(n),
                    "pct": round(100 * n / n_total, 2),
                }
            )
    return pd.DataFrame(rows)


def stage_domain_table(df: pd.DataFrame) -> pd.DataFrame:
    tbl = (
        df.groupby(["Stage", "domain_l1"]).size().unstack(fill_value=0)
    )
    tbl_pct = tbl.div(tbl.sum(axis=1), axis=0).mul(100).round(2)
    tbl_pct.index = [f"Stage_{int(s)}" for s in tbl_pct.index]
    return tbl_pct


def intent_complexity_table(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["intent", "complexity"]).size().unstack(fill_value=0)


def plot_domain_distribution(df: pd.DataFrame) -> None:
    counts = (
        df["domain_l1"].value_counts().sort_values(ascending=True)
    )
    plt.figure(figsize=(9, 7))
    sns.barplot(
        x=counts.values, y=counts.index, color="steelblue", orient="h"
    )
    plt.xlabel("Questions")
    plt.ylabel("Domain (Level 1)")
    plt.title("OntoSage++ corpus: question count by domain (n=5,127)")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "B4_domain_distribution.png", dpi=300)
    plt.savefig(OUT / "figures" / "B4_domain_distribution.pdf")
    plt.close()


def plot_intent_heatmap(df: pd.DataFrame) -> None:
    tbl = pd.crosstab(df["domain_l1"], df["intent"])
    tbl = tbl.loc[tbl.sum(axis=1).sort_values(ascending=False).index]
    tbl = tbl.head(12)
    plt.figure(figsize=(8, 7))
    sns.heatmap(
        tbl,
        annot=True,
        fmt="d",
        cmap="Blues",
        cbar_kws={"label": "Question count"},
    )
    plt.title("Top-12 domains × intent")
    plt.xlabel("Intent")
    plt.ylabel("Domain")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "B4_intent_heatmap.png", dpi=300)
    plt.savefig(OUT / "figures" / "B4_intent_heatmap.pdf")
    plt.close()


def plot_complexity_by_stage(df: pd.DataFrame) -> None:
    tbl = (
        df.groupby(["Stage", "complexity"]).size().unstack(fill_value=0)
    )
    tbl_pct = tbl.div(tbl.sum(axis=1), axis=0).mul(100)
    tbl_pct.index = [f"Stage {int(s)}" for s in tbl_pct.index]
    ax = tbl_pct.plot(
        kind="bar",
        stacked=True,
        figsize=(7, 5),
        colormap="Set2",
        edgecolor="white",
    )
    ax.set_ylabel("Percentage of questions")
    ax.set_xlabel("Elicitation stage")
    ax.set_title("Question complexity distribution by stage")
    ax.legend(title="Complexity", loc="upper right")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "B4_complexity_by_stage.png", dpi=300)
    plt.savefig(OUT / "figures" / "B4_complexity_by_stage.pdf")
    plt.close()


def append_summary_md(df: pd.DataFrame, stage_dom: pd.DataFrame) -> None:
    path = ROOT / "corpus" / "corpus_summary_stats.md"
    on_topic = df[df["domain_l1"] != "OTHER"]
    top3 = on_topic["domain_l1"].value_counts().head(3)
    top3_str = ", ".join(
        f"{d} {pct:.1f}%"
        for d, pct in (top3 / len(on_topic) * 100).items()
    )
    line = (
        f"- Phase B4: {len(df)} questions classified into "
        f"{df['domain_l1'].nunique()} domains and "
        f"{df['query_type_l2'].nunique()} query types; "
        f"{(df['domain_l1']!='OTHER').sum()} on-topic; "
        f"top-3 on-topic domains: {top3_str}.\n"
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "Phase B4:" in existing:
            new = []
            for ln in existing.splitlines(keepends=True):
                new.append(line if ln.lstrip().startswith("- Phase B4:") else ln)
            path.write_text("".join(new), encoding="utf-8")
        else:
            path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    else:
        path.write_text(line, encoding="utf-8")


def main() -> None:
    df = pd.read_csv(CORPUS / "classified_corpus.csv")

    stats = long_form_stats(df)
    stats.to_csv(OUT / "tables" / "B4_corpus_statistics.csv", index=False)

    stage_dom = stage_domain_table(df)
    stage_dom.to_csv(OUT / "tables" / "B4_domain_by_stage.csv")

    intcomp = intent_complexity_table(df)
    intcomp.to_csv(OUT / "tables" / "B4_intent_by_complexity.csv")

    plot_domain_distribution(df)
    plot_intent_heatmap(df)
    plot_complexity_by_stage(df)

    append_summary_md(df, stage_dom)

    print(f"Phase B4 done. {len(df)} rows, "
          f"{df['domain_l1'].nunique()} domains, "
          f"{df['query_type_l2'].nunique()} query types.")
    print("Top-5 domain shares (on-topic):")
    on_topic = df[df["domain_l1"] != "OTHER"]
    top5 = on_topic["domain_l1"].value_counts().head(5)
    for d, n in top5.items():
        print(f"  {d}: {n} ({100*n/len(on_topic):.1f}%)")
    print(f"Stage 1 top domain (excluding OTHER): "
          f"{stage_dom.drop(columns=['OTHER'], errors='ignore').loc['Stage_1'].idxmax()}")


if __name__ == "__main__":
    main()
