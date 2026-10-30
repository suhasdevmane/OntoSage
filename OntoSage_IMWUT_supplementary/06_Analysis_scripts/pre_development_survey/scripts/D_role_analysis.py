"""Phase D — Role-Based Analysis (RQ3).

Outputs:
  outputs/tables/D1_role_domain_counts.csv
  outputs/tables/D1_role_domain_pct.csv
  outputs/tables/D1_chi_squared_results.md
  outputs/figures/D1_role_domain_heatmap.{png,pdf}
  outputs/tables/D2_concordance_table.csv
  outputs/tables/D2_role_topic_rank.csv
  outputs/figures/D2_rank_by_role.{png,pdf}
  outputs/tables/D3_user_personas.md

Methods:
  D1 — Chi-squared independence (role x domain), Cramer's V
  D2 — Per-role mean rank for each of 20 topics; Kendall's W (overall and per-role);
       Spearman correlation matrix between role rank-vectors
  D3 — Persona synthesis derived from role aggregates (top domains, complexity mix,
       priority topics, exemplar questions)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CORPUS = ROOT / "corpus"
INPUTS = ROOT / "inputs"
INTERMEDIATE = OUT / "intermediate"


# ---------------------------------------------------------------------------
# D1 — Role x Domain
# ---------------------------------------------------------------------------


def role_domain_tables(corpus: pd.DataFrame, user_summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = corpus.merge(user_summary[["PID", "PrimaryRole"]], on="PID", how="left")
    counts = pd.crosstab(df["PrimaryRole"], df["domain_l1"])
    pct = counts.div(counts.sum(axis=1), axis=0).mul(100).round(2)
    return counts, pct


def chi_squared_role_domain(counts: pd.DataFrame) -> str:
    chi2, p, dof, _ = stats.chi2_contingency(counts.values)
    n = int(counts.values.sum())
    r, c = counts.shape
    cramers_v = float(np.sqrt(chi2 / (n * (min(r, c) - 1))))
    lines = [
        "# Phase D1 — Chi-squared independence: role x domain",
        "",
        f"- Chi^2({dof}) = {chi2:.3f}",
        f"- p = {p:.4g}",
        f"- N = {n} questions",
        f"- Roles (rows) = {r}, Domains (cols) = {c}",
        f"- Cramer's V = {cramers_v:.4f}",
        "",
        "Interpretation: Cramer's V scale (Cohen 1988) — 0.10 small, 0.30 medium, 0.50 large.",
        "Significant chi-squared (p < 0.05) confirms that question-domain distribution depends on user role.",
        "",
    ]
    return "\n".join(lines) + "\n"


def plot_role_domain_heatmap(pct: pd.DataFrame) -> None:
    pct = pct.copy()
    if "OTHER" in pct.columns:
        pct = pct.drop(columns=["OTHER"])
    top_domains = pct.sum(axis=0).sort_values(ascending=False).head(12).index
    pct = pct[top_domains]
    pct = pct.loc[pct.sum(axis=1).sort_values(ascending=False).index]
    plt.figure(figsize=(11, 6.5))
    sns.heatmap(
        pct,
        annot=True,
        fmt=".1f",
        cmap="Blues",
        cbar_kws={"label": "% of role's questions"},
    )
    plt.title("Question domain mix by user role (top-12 domains, OTHER excluded)")
    plt.xlabel("Domain")
    plt.ylabel("Primary role")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "D1_role_domain_heatmap.png", dpi=300)
    plt.savefig(OUT / "figures" / "D1_role_domain_heatmap.pdf")
    plt.close()


# ---------------------------------------------------------------------------
# D2 — Role x Topic Ranking
# ---------------------------------------------------------------------------


def long_topic_rankings(topic_df: pd.DataFrame, user_pid: pd.DataFrame, user_summary: pd.DataFrame) -> pd.DataFrame:
    """Reshape wide Rank_K_ID columns into (PID, Role, TopicID, TopicLabel, Rank)."""
    rows = []
    df = topic_df.merge(user_pid, on="Username", how="left")
    df = df.merge(user_summary[["PID", "PrimaryRole"]], on="PID", how="left")
    for _, r in df.iterrows():
        for k in range(1, 21):
            tid = r.get(f"Rank_{k}_ID")
            tlabel = r.get(f"Rank_{k}_Label")
            if pd.isna(tid):
                continue
            rows.append(
                {
                    "PID": r["PID"],
                    "PrimaryRole": r["PrimaryRole"],
                    "TopicID": int(tid),
                    "TopicLabel": str(tlabel),
                    "Rank": k,
                }
            )
    return pd.DataFrame(rows)


def kendalls_w(matrix: np.ndarray) -> float:
    """Kendall's coefficient of concordance.

    matrix: shape (n_judges, n_items) of integer ranks.
    """
    n, k = matrix.shape
    if n <= 1 or k <= 1:
        return float("nan")
    rank_sums = matrix.sum(axis=0)
    s = float(((rank_sums - rank_sums.mean()) ** 2).sum())
    denom = (n * n) * (k * (k * k - 1)) / 12.0
    if denom == 0:
        return float("nan")
    return s / denom


def role_topic_table(long_df: pd.DataFrame) -> pd.DataFrame:
    return (
        long_df.groupby(["PrimaryRole", "TopicLabel"])["Rank"]
        .mean()
        .unstack(fill_value=np.nan)
        .round(2)
    )


def role_concordance(long_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for role, sub in long_df.groupby("PrimaryRole"):
        wide = sub.pivot_table(index="PID", columns="TopicLabel", values="Rank")
        wide = wide.dropna(axis=1, how="any")
        if wide.shape[0] < 2 or wide.shape[1] < 2:
            w = float("nan")
        else:
            w = kendalls_w(wide.to_numpy())
        rows.append(
            {
                "role": role,
                "n_users": int(sub["PID"].nunique()),
                "n_topics_complete": int(wide.shape[1]) if wide.size else 0,
                "kendalls_w": round(w, 4) if not np.isnan(w) else np.nan,
            }
        )
    out = pd.DataFrame(rows).sort_values("n_users", ascending=False)
    return out


def plot_rank_by_role(role_topic: pd.DataFrame) -> None:
    keep_roles = role_topic.dropna(thresh=10).index.tolist()
    if not keep_roles:
        return
    sub = role_topic.loc[keep_roles].copy()
    sub = sub[sub.mean(axis=0).sort_values().index]
    plt.figure(figsize=(13, 6.5))
    sns.heatmap(
        sub,
        annot=True,
        fmt=".1f",
        cmap="RdYlBu_r",
        cbar_kws={"label": "Mean rank (1 = most important)"},
    )
    plt.title("Mean topic rank by primary role (lower = higher priority)")
    plt.xlabel("Topic")
    plt.ylabel("Primary role")
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "D2_rank_by_role.png", dpi=300)
    plt.savefig(OUT / "figures" / "D2_rank_by_role.pdf")
    plt.close()


# ---------------------------------------------------------------------------
# D3 — Personas
# ---------------------------------------------------------------------------


def synthesize_personas(
    corpus: pd.DataFrame,
    user_summary: pd.DataFrame,
    role_topic: pd.DataFrame,
    concordance: pd.DataFrame,
) -> str:
    df = corpus.merge(user_summary[["PID", "PrimaryRole"]], on="PID", how="left")
    on_topic = df[df["domain_l1"] != "OTHER"]
    eligible = (
        df.groupby("PrimaryRole")["PID"].nunique().sort_values(ascending=False).head(6)
    )
    blocks = ["# Phase D3 — User Personas (synthesised from corpus + topic rankings)\n"]
    for role, n_users in eligible.items():
        sub = df[df["PrimaryRole"] == role]
        sub_on = on_topic[on_topic["PrimaryRole"] == role]
        top_domains = (
            sub_on["domain_l1"].value_counts().head(3) if len(sub_on) else pd.Series(dtype=int)
        )
        complexity_mix = sub["complexity"].value_counts(normalize=True).mul(100).round(1)
        intent_mix = sub["intent"].value_counts(normalize=True).mul(100).round(1).head(3)
        if role in role_topic.index:
            ranks = role_topic.loc[role].dropna().sort_values()
            top_topics = ranks.head(3)
        else:
            top_topics = pd.Series(dtype=float)
        exemplars = sub.sample(min(3, len(sub)), random_state=42)["Question"].tolist()
        kw = concordance[concordance["role"] == role]
        kw_val = float(kw["kendalls_w"].iloc[0]) if not kw.empty else float("nan")
        block = [
            f"## Persona: {role}",
            "",
            f"- **Coverage:** {int(n_users)} users, {len(sub)} questions ({100*len(sub)/len(df):.1f}% of corpus)",
            f"- **Top on-topic domains:** "
            + (
                ", ".join(f"{d} ({n})" for d, n in top_domains.items()) if len(top_domains) else "n/a"
            ),
            f"- **Complexity mix:** "
            + ", ".join(f"{c} {p:.0f}%" for c, p in complexity_mix.items()),
            f"- **Top intents:** "
            + ", ".join(f"{i} {p:.0f}%" for i, p in intent_mix.items()),
            f"- **Top priority topics (mean rank):** "
            + (
                ", ".join(f"{t} ({r:.1f})" for t, r in top_topics.items())
                if len(top_topics)
                else "n/a (no ranking data for this role)"
            ),
            f"- **Within-role agreement (Kendall's W):** "
            + (f"{kw_val:.3f}" if not np.isnan(kw_val) else "n/a"),
            "- **Representative questions:**",
        ]
        for q in exemplars:
            block.append(f"    - \"{q}\"")
        block.append("")
        blocks.append("\n".join(block))
    return "\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def append_summary(pct: pd.DataFrame, concordance: pd.DataFrame) -> None:
    path = ROOT / "corpus" / "corpus_summary_stats.md"
    top_role = pct.sum(axis=1).sort_values(ascending=False).index[0] if len(pct) else "?"
    role_count = len(pct)
    avg_w = concordance["kendalls_w"].dropna().mean()
    line = (
        f"- Phase D: {role_count} role categories analysed; "
        f"largest role = {top_role}; "
        f"mean within-role Kendall's W = {avg_w:.3f}.\n"
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "Phase D:" in existing:
            new = []
            for ln in existing.splitlines(keepends=True):
                new.append(line if ln.lstrip().startswith("- Phase D:") else ln)
            path.write_text("".join(new), encoding="utf-8")
        else:
            path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    else:
        path.write_text(line, encoding="utf-8")


def main() -> None:
    corpus = pd.read_csv(CORPUS / "classified_corpus.csv")
    user_summary = pd.read_csv(OUT / "tables" / "A3_user_summary.csv")
    user_pid = pd.read_csv(INTERMEDIATE / "username_to_pid.csv")
    topic_df = pd.read_csv(INPUTS / "topic_rankings.csv")

    counts, pct = role_domain_tables(corpus, user_summary)
    counts.to_csv(OUT / "tables" / "D1_role_domain_counts.csv")
    pct.to_csv(OUT / "tables" / "D1_role_domain_pct.csv")
    md = chi_squared_role_domain(counts)
    (OUT / "tables" / "D1_chi_squared_results.md").write_text(md, encoding="utf-8")
    plot_role_domain_heatmap(pct)

    long_df = long_topic_rankings(topic_df, user_pid, user_summary)
    role_topic = role_topic_table(long_df)
    role_topic.to_csv(OUT / "tables" / "D2_role_topic_rank.csv")
    concordance = role_concordance(long_df)
    concordance.to_csv(OUT / "tables" / "D2_concordance_table.csv", index=False)
    plot_rank_by_role(role_topic)

    personas_md = synthesize_personas(corpus, user_summary, role_topic, concordance)
    (OUT / "tables" / "D3_user_personas.md").write_text(personas_md, encoding="utf-8")

    append_summary(pct, concordance)

    print("Phase D done.")
    print("Role x domain (top-3 domains per role):")
    for role in pct.index:
        top = pct.loc[role].sort_values(ascending=False).head(3)
        print(f"  {role}: " + ", ".join(f"{d} {v:.1f}%" for d, v in top.items()))
    print()
    print("Concordance:")
    print(concordance.to_string(index=False))


if __name__ == "__main__":
    main()
