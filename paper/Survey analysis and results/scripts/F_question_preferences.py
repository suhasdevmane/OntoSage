"""Phase F — Question Ranking Analysis (RQ5).

Inputs: inputs/question_rankings.csv
Each row gives one user's ranking of 4 questions within one topic.
QIDs are formatted "<topic_id>-<level>", where level 1..4 corresponds to
the four candidate phrasings shown to the user (treated as ordinal levels
of analytical complexity: L1 = lookup-style, L4 = analytical/forecast).

Outputs:
  outputs/tables/F1_question_preferences_by_topic.csv
  outputs/tables/F1_overall_level_preference.csv
  outputs/figures/F2_complexity_preference.{png,pdf}
  outputs/tables/F2_complexity_preference_by_role.csv
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
INPUTS = ROOT / "inputs"
INTERMEDIATE = OUT / "intermediate"


def parse_level(qid: str) -> int:
    try:
        return int(str(qid).split("-")[-1])
    except (ValueError, AttributeError):
        return -1


def long_form(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        for k in (1, 2, 3, 4):
            qid = r.get(f"Rank_{k}_QID")
            if pd.isna(qid):
                continue
            level = parse_level(qid)
            if level < 1:
                continue
            rows.append(
                {
                    "Username": r["Username"],
                    "TopicID": int(r["Topic_ID"]),
                    "TopicLabel": r["Topic_Label"],
                    "Rank": k,
                    "Level": level,
                }
            )
    return pd.DataFrame(rows)


def per_topic_table(long_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (tid, label), sub in long_df.groupby(["TopicID", "TopicLabel"]):
        n_users = sub["Username"].nunique()
        for level in (1, 2, 3, 4):
            lsub = sub[sub["Level"] == level]
            if lsub.empty:
                continue
            rank_counts = lsub["Rank"].value_counts().to_dict()
            rows.append(
                {
                    "TopicID": int(tid),
                    "TopicLabel": label,
                    "Level": level,
                    "n_users": n_users,
                    "rank1_count": int(rank_counts.get(1, 0)),
                    "rank2_count": int(rank_counts.get(2, 0)),
                    "rank3_count": int(rank_counts.get(3, 0)),
                    "rank4_count": int(rank_counts.get(4, 0)),
                    "mean_rank": round(float(lsub["Rank"].mean()), 3),
                }
            )
    return pd.DataFrame(rows).sort_values(["TopicID", "Level"])


def overall_level_table(long_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for level in (1, 2, 3, 4):
        sub = long_df[long_df["Level"] == level]
        rank_dist = sub["Rank"].value_counts(normalize=True).mul(100).round(2).to_dict()
        rows.append(
            {
                "Level": level,
                "n_observations": len(sub),
                "pct_rank1": round(rank_dist.get(1, 0.0), 2),
                "pct_rank2": round(rank_dist.get(2, 0.0), 2),
                "pct_rank3": round(rank_dist.get(3, 0.0), 2),
                "pct_rank4": round(rank_dist.get(4, 0.0), 2),
                "mean_rank": round(float(sub["Rank"].mean()), 3),
            }
        )
    return pd.DataFrame(rows)


def role_level_table(long_df: pd.DataFrame, user_pid: pd.DataFrame, user_summary: pd.DataFrame) -> pd.DataFrame:
    df = long_df.merge(user_pid, on="Username", how="left")
    df = df.merge(user_summary[["PID", "PrimaryRole"]], on="PID", how="left")
    rows = []
    for role, sub in df.groupby("PrimaryRole"):
        for level in (1, 2, 3, 4):
            lsub = sub[sub["Level"] == level]
            if lsub.empty:
                continue
            rows.append(
                {
                    "PrimaryRole": role,
                    "Level": level,
                    "n": len(lsub),
                    "mean_rank": round(float(lsub["Rank"].mean()), 3),
                    "pct_rank1": round(100 * (lsub["Rank"] == 1).mean(), 2),
                }
            )
    return pd.DataFrame(rows)


def plot_complexity_preference(overall: pd.DataFrame, role_level: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    sub = overall.melt(
        id_vars="Level",
        value_vars=["pct_rank1", "pct_rank2", "pct_rank3", "pct_rank4"],
        var_name="rank_bucket",
        value_name="pct",
    )
    sub["Rank"] = sub["rank_bucket"].str.replace("pct_rank", "").astype(int)
    pivot = sub.pivot(index="Level", columns="Rank", values="pct")
    pivot.plot(
        kind="bar",
        stacked=True,
        ax=axes[0],
        colormap="RdYlBu_r",
        edgecolor="white",
    )
    axes[0].set_title("Within-topic rank distribution by question level")
    axes[0].set_xlabel("Question level (1 = lookup, 4 = analytical)")
    axes[0].set_ylabel("% of observations")
    axes[0].legend(title="Rank assigned", bbox_to_anchor=(1.0, 1.0))

    rl = role_level.pivot(index="PrimaryRole", columns="Level", values="mean_rank")
    rl = rl.dropna(thresh=3).sort_index()
    sns.heatmap(rl, annot=True, fmt=".2f", cmap="RdYlBu_r", ax=axes[1],
                cbar_kws={"label": "Mean rank (lower = preferred)"})
    axes[1].set_title("Mean rank by role x level")
    axes[1].set_xlabel("Question level")
    axes[1].set_ylabel("Primary role")

    plt.tight_layout()
    plt.savefig(OUT / "figures" / "F2_complexity_preference.png", dpi=300)
    plt.savefig(OUT / "figures" / "F2_complexity_preference.pdf")
    plt.close()


def append_summary(overall: pd.DataFrame) -> None:
    path = ROOT / "corpus" / "corpus_summary_stats.md"
    best = overall.sort_values("mean_rank").iloc[0]
    line = (
        f"- Phase F: most preferred question level = L{int(best['Level'])} "
        f"(mean rank {best['mean_rank']:.2f}); "
        f"L1 vs L4 mean ranks = "
        + " / ".join(
            f"L{int(r.Level)}={r.mean_rank:.2f}" for _, r in overall.iterrows()
        )
        + ".\n"
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "Phase F:" in existing:
            new = []
            for ln in existing.splitlines(keepends=True):
                new.append(line if ln.lstrip().startswith("- Phase F:") else ln)
            path.write_text("".join(new), encoding="utf-8")
        else:
            path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    else:
        path.write_text(line, encoding="utf-8")


def main() -> None:
    df = pd.read_csv(INPUTS / "question_rankings.csv")
    long_df = long_form(df)

    per_topic = per_topic_table(long_df)
    per_topic.to_csv(OUT / "tables" / "F1_question_preferences_by_topic.csv", index=False)

    overall = overall_level_table(long_df)
    overall.to_csv(OUT / "tables" / "F1_overall_level_preference.csv", index=False)

    user_pid = pd.read_csv(INTERMEDIATE / "username_to_pid.csv")
    user_summary = pd.read_csv(OUT / "tables" / "A3_user_summary.csv")
    role_level = role_level_table(long_df, user_pid, user_summary)
    role_level.to_csv(OUT / "tables" / "F2_complexity_preference_by_role.csv", index=False)

    plot_complexity_preference(overall, role_level)
    append_summary(overall)

    print("Phase F done.")
    print("Overall level preference:")
    print(overall.to_string(index=False))


if __name__ == "__main__":
    main()
