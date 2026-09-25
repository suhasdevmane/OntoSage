"""Phase C — Stage Comparison.

Tests whether the four elicitation stages produce statistically different
question populations on three measurable axes:

  - question length (word count)
  - complexity tier (LOOKUP / AGGREGATION / MULTI_STEP)
  - intent type proportions

Methods (per ANALYSIS_METHODOLOGY.md):
  - Kruskal-Wallis across 4 stages on continuous metrics
  - Inline Dunn's post-hoc with Bonferroni correction
  - Chi-squared independence on intent proportions, with Cramer's V
  - Effect sizes alongside every p-value (epsilon-squared, Cramer's V)
  - TF-IDF top terms per stage (4 panels)
  - Novelty: cosine similarity in TF-IDF space, threshold 0.75

Outputs:
  outputs/tables/C1_stage_stats.csv
  outputs/tables/C1_stage_tests.md
  outputs/tables/C2_stage_evolution_table.md
  outputs/tables/C3_novelty_analysis.csv
  outputs/figures/C2_stage_tfidf_comparison.{png,pdf}
  outputs/figures/C3_novelty_by_stage.{png,pdf}
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CORPUS = ROOT / "corpus"

COMPLEXITY_RANK = {"LOOKUP": 1, "AGGREGATION": 2, "MULTI_STEP": 3}


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def epsilon_squared(h: float, n: int) -> float:
    """Effect size for Kruskal-Wallis (Tomczak & Tomczak 2014)."""
    if n <= 1:
        return 0.0
    return float(h / ((n * n - 1) / (n + 1)))


def dunn_posthoc(groups: dict[int, np.ndarray]) -> pd.DataFrame:
    """Inline Dunn's all-pairs post-hoc with Bonferroni correction."""
    keys = sorted(groups.keys())
    all_vals = np.concatenate([groups[k] for k in keys])
    ranks = stats.rankdata(all_vals)
    rank_groups: dict[int, np.ndarray] = {}
    cursor = 0
    for k in keys:
        n = len(groups[k])
        rank_groups[k] = ranks[cursor : cursor + n]
        cursor += n
    n_total = len(all_vals)
    mean_rank = {k: rank_groups[k].mean() for k in keys}
    sizes = {k: len(rank_groups[k]) for k in keys}

    rows = []
    n_pairs = len(keys) * (len(keys) - 1) / 2
    for a, b in combinations(keys, 2):
        diff = mean_rank[a] - mean_rank[b]
        se = np.sqrt((n_total * (n_total + 1) / 12) * (1 / sizes[a] + 1 / sizes[b]))
        z = diff / se
        p_two = 2 * (1 - stats.norm.cdf(abs(z)))
        p_bonf = min(1.0, p_two * n_pairs)
        rows.append(
            {
                "group_a": f"S{a}",
                "group_b": f"S{b}",
                "z": round(z, 3),
                "p_raw": round(p_two, 5),
                "p_bonferroni": round(p_bonf, 5),
                "significant_05": p_bonf < 0.05,
            }
        )
    return pd.DataFrame(rows)


def cramers_v(chi2: float, n: int, r: int, c: int) -> float:
    denom = n * (min(r, c) - 1)
    if denom <= 0:
        return 0.0
    return float(np.sqrt(chi2 / denom))


def df_to_markdown(df: pd.DataFrame) -> str:
    """Manual GitHub-flavoured markdown table (avoids 'tabulate' dependency)."""
    cols = list(df.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = [
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in df.itertuples(index=False, name=None)
    ]
    return "\n".join([head, sep, *rows])


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def stage_descriptives(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["word_count"] = df["Question"].str.split().str.len()
    df["complexity_rank"] = df["complexity"].map(COMPLEXITY_RANK)
    rows = []
    for s in sorted(df["Stage"].unique()):
        sub = df[df["Stage"] == s]
        rows.append(
            {
                "stage": int(s),
                "n": len(sub),
                "mean_word_count": round(sub["word_count"].mean(), 2),
                "median_word_count": int(sub["word_count"].median()),
                "mean_complexity_rank": round(sub["complexity_rank"].mean(), 3),
                "pct_lookup": round(100 * (sub["complexity"] == "LOOKUP").mean(), 1),
                "pct_aggregation": round(
                    100 * (sub["complexity"] == "AGGREGATION").mean(), 1
                ),
                "pct_multistep": round(
                    100 * (sub["complexity"] == "MULTI_STEP").mean(), 1
                ),
                "diversity_index": float(
                    -(
                        sub["domain_l1"].value_counts(normalize=True)
                        * np.log(
                            sub["domain_l1"].value_counts(normalize=True)
                        )
                    ).sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def run_kw_tests(df: pd.DataFrame) -> str:
    df = df.copy()
    df["word_count"] = df["Question"].str.split().str.len()
    df["complexity_rank"] = df["complexity"].map(COMPLEXITY_RANK)

    lines: list[str] = []
    lines.append("# Phase C — Stage comparison statistical tests\n")
    lines.append(
        "All tests are non-parametric. Effect sizes accompany every p-value.\n"
    )

    # Kruskal-Wallis on word count
    groups_wc = {
        int(s): df[df["Stage"] == s]["word_count"].dropna().to_numpy()
        for s in sorted(df["Stage"].unique())
    }
    h_wc, p_wc = stats.kruskal(*[g for g in groups_wc.values()])
    eps2_wc = epsilon_squared(h_wc, len(df))
    lines.append("## Question word count")
    lines.append(
        f"- Kruskal-Wallis H = {h_wc:.3f}, p = {p_wc:.4g}, "
        f"epsilon^2 = {eps2_wc:.4f} (n = {len(df)})"
    )
    lines.append("- Per-stage means:")
    for k in sorted(groups_wc.keys()):
        lines.append(
            f"  - Stage {k}: mean = {groups_wc[k].mean():.2f}, "
            f"median = {int(np.median(groups_wc[k]))}, n = {len(groups_wc[k])}"
        )
    lines.append("\n### Dunn's post-hoc (Bonferroni)\n")
    dunn_wc = dunn_posthoc(groups_wc)
    lines.append(df_to_markdown(dunn_wc))
    lines.append("")

    # Kruskal-Wallis on complexity rank
    groups_cr = {
        int(s): df[df["Stage"] == s]["complexity_rank"].dropna().to_numpy()
        for s in sorted(df["Stage"].unique())
    }
    h_cr, p_cr = stats.kruskal(*[g for g in groups_cr.values()])
    eps2_cr = epsilon_squared(h_cr, len(df))
    lines.append("## Complexity rank (1=Lookup, 2=Aggregation, 3=Multi-step)")
    lines.append(
        f"- Kruskal-Wallis H = {h_cr:.3f}, p = {p_cr:.4g}, "
        f"epsilon^2 = {eps2_cr:.4f}"
    )
    lines.append("\n### Dunn's post-hoc (Bonferroni)\n")
    dunn_cr = dunn_posthoc(groups_cr)
    lines.append(df_to_markdown(dunn_cr))
    lines.append("")

    # Chi^2 on intent x stage
    intent_table = pd.crosstab(df["Stage"], df["intent"])
    chi2, p_chi, dof, _ = stats.chi2_contingency(intent_table)
    v = cramers_v(chi2, len(df), *intent_table.shape)
    lines.append("## Intent proportions across stages (Chi-squared)")
    lines.append(
        f"- Chi^2({dof}) = {chi2:.3f}, p = {p_chi:.4g}, "
        f"Cramer's V = {v:.4f}"
    )
    lines.append("- Contingency (counts):\n")
    intent_reset = intent_table.reset_index()
    lines.append(df_to_markdown(intent_reset))
    lines.append("")

    return "\n".join(lines) + "\n"


def stage_tfidf_top_terms(df: pd.DataFrame) -> dict[int, list[tuple[str, float]]]:
    docs = []
    stage_labels = []
    for s in sorted(df["Stage"].unique()):
        sub = df[df["Stage"] == s]
        docs.append(" ".join(sub["Question"].astype(str).tolist()))
        stage_labels.append(int(s))
    vec = TfidfVectorizer(
        stop_words="english", min_df=2, max_df=0.9, ngram_range=(1, 2)
    )
    matrix = vec.fit_transform(docs)
    feature_names = np.array(vec.get_feature_names_out())
    out: dict[int, list[tuple[str, float]]] = {}
    for i, s in enumerate(stage_labels):
        row = matrix[i].toarray().ravel()
        top = row.argsort()[-15:][::-1]
        out[s] = [(feature_names[j], float(row[j])) for j in top]
    return out


def plot_tfidf(top_terms: dict[int, list[tuple[str, float]]]) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(15, 5), sharey=False)
    for i, (s, terms) in enumerate(sorted(top_terms.items())):
        labels = [t for t, _ in terms]
        scores = [v for _, v in terms]
        axes[i].barh(range(len(labels)), scores, color="steelblue")
        axes[i].set_yticks(range(len(labels)))
        axes[i].set_yticklabels(labels, fontsize=8)
        axes[i].invert_yaxis()
        axes[i].set_title(f"Stage {s}")
        axes[i].set_xlabel("TF-IDF")
    fig.suptitle("Top distinguishing terms per elicitation stage", y=1.02)
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "C2_stage_tfidf_comparison.png", dpi=300, bbox_inches="tight")
    plt.savefig(OUT / "figures" / "C2_stage_tfidf_comparison.pdf", bbox_inches="tight")
    plt.close()


def novelty_analysis(df: pd.DataFrame, sim_threshold: float = 0.75) -> pd.DataFrame:
    """Per stage, fraction of questions whose max cosine similarity to ALL prior
    questions (any stage) is below sim_threshold (= novel)."""
    df = df.sort_values(["Stage", "Timestamp"]).reset_index(drop=True)
    vec = TfidfVectorizer(stop_words="english", min_df=2, max_df=0.95)
    matrix = vec.fit_transform(df["Question"].astype(str))

    novelty_flags = np.zeros(len(df), dtype=bool)
    block = 500
    for start in range(0, len(df), block):
        end = min(len(df), start + block)
        if start == 0:
            novelty_flags[start:end] = True
            continue
        sims = cosine_similarity(matrix[start:end], matrix[:start])
        max_sim = sims.max(axis=1)
        novelty_flags[start:end] = max_sim < sim_threshold

    df["is_novel"] = novelty_flags
    rows = []
    for s in sorted(df["Stage"].unique()):
        sub = df[df["Stage"] == s]
        rows.append(
            {
                "stage": int(s),
                "n": len(sub),
                "n_novel": int(sub["is_novel"].sum()),
                "pct_novel": round(100 * sub["is_novel"].mean(), 2),
                "sim_threshold": sim_threshold,
            }
        )
    return pd.DataFrame(rows)


def plot_novelty(novelty_df: pd.DataFrame) -> None:
    plt.figure(figsize=(7, 4.5))
    sns.barplot(
        data=novelty_df, x="stage", y="pct_novel", color="steelblue"
    )
    plt.xlabel("Elicitation stage")
    plt.ylabel(f"Novel questions (%) — cosine sim < {novelty_df['sim_threshold'].iloc[0]}")
    plt.title("Question novelty by elicitation stage")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "C3_novelty_by_stage.png", dpi=300)
    plt.savefig(OUT / "figures" / "C3_novelty_by_stage.pdf")
    plt.close()


def append_summary(stage_stats: pd.DataFrame, novelty: pd.DataFrame) -> None:
    path = ROOT / "corpus" / "corpus_summary_stats.md"
    line = (
        f"- Phase C: stage means - "
        + ", ".join(
            f"S{r.stage}={r.mean_word_count:.1f}w/{r.pct_multistep:.0f}%multi"
            for _, r in stage_stats.iterrows()
        )
        + f"; novelty - "
        + ", ".join(f"S{r.stage}={r.pct_novel}%" for _, r in novelty.iterrows())
        + ".\n"
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "Phase C:" in existing:
            new = []
            for ln in existing.splitlines(keepends=True):
                new.append(line if ln.lstrip().startswith("- Phase C:") else ln)
            path.write_text("".join(new), encoding="utf-8")
        else:
            path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    else:
        path.write_text(line, encoding="utf-8")


def main() -> None:
    df = pd.read_csv(CORPUS / "classified_corpus.csv")

    stage_stats = stage_descriptives(df)
    stage_stats.to_csv(OUT / "tables" / "C1_stage_stats.csv", index=False)

    md = run_kw_tests(df)
    (OUT / "tables" / "C1_stage_tests.md").write_text(md, encoding="utf-8")

    top_terms = stage_tfidf_top_terms(df)
    plot_tfidf(top_terms)

    rows = []
    for s, terms in sorted(top_terms.items()):
        rows.append(
            f"## Stage {s}\n\n"
            + "\n".join(f"- {t} ({v:.3f})" for t, v in terms)
        )
    (OUT / "tables" / "C2_stage_evolution_table.md").write_text(
        "# Phase C2 — Top TF-IDF terms per stage\n\n" + "\n\n".join(rows) + "\n",
        encoding="utf-8",
    )

    novelty = novelty_analysis(df)
    novelty.to_csv(OUT / "tables" / "C3_novelty_analysis.csv", index=False)
    plot_novelty(novelty)

    append_summary(stage_stats, novelty)

    print("Phase C done.")
    print(stage_stats.to_string(index=False))
    print()
    print("Novelty:")
    print(novelty.to_string(index=False))


if __name__ == "__main__":
    main()
