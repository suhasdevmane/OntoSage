"""Phase A — Data Preparation for the OntoSage++ corpus study.

Reads `inputs/{questions_by_user, topic_rankings, question_rankings}.csv`,
cleans them, anonymises usernames to stable PIDs (P01..PNN), and writes:

  outputs/intermediate/username_to_pid.csv
  outputs/tables/A2_demographics_table.csv
  outputs/tables/A3_user_summary.csv
  outputs/figures/A2_role_distribution.{png,pdf}

Reproducibility: np.random.seed(42). The script is idempotent — re-running
it overwrites prior outputs deterministically.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

np.random.seed(42)

ROOT = Path(__file__).resolve().parents[1]
INP = ROOT / "inputs"
OUT = ROOT / "outputs"
(OUT / "tables").mkdir(parents=True, exist_ok=True)
(OUT / "figures").mkdir(parents=True, exist_ok=True)
(OUT / "intermediate").mkdir(parents=True, exist_ok=True)
(ROOT / "corpus").mkdir(parents=True, exist_ok=True)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    qbu = pd.read_csv(INP / "questions_by_user.csv")
    tr = pd.read_csv(INP / "topic_rankings.csv")
    qr = pd.read_csv(INP / "question_rankings.csv")
    return qbu, tr, qr


def clean_questions(qbu: pd.DataFrame) -> pd.DataFrame:
    qbu = qbu.copy()
    qbu["Username"] = qbu["Username"].astype(str).str.strip().str.lower()
    qbu["Timestamp"] = pd.to_datetime(qbu["Timestamp"], errors="coerce")
    qbu["Question"] = qbu["Question"].astype(str).str.strip()
    qbu = qbu.dropna(subset=["Question"])
    qbu = qbu[qbu["Question"].str.len() > 0]
    qbu["Stage"] = pd.to_numeric(qbu["Stage"], errors="coerce").astype("Int64")
    qbu = qbu.dropna(subset=["Stage"])
    qbu["Stage"] = qbu["Stage"].astype(int)
    qbu["Roles"] = qbu["Roles"].fillna("Unknown").astype(str)
    return qbu


def assign_pids(qbu: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stable PID per username, ordered by first-seen Timestamp."""
    first_seen = (
        qbu.sort_values("Timestamp", na_position="last")
        .groupby("Username", as_index=False)["Timestamp"]
        .min()
        .sort_values(["Timestamp", "Username"], na_position="last")
        .reset_index(drop=True)
    )
    first_seen["PID"] = [f"P{i + 1:02d}" for i in range(len(first_seen))]
    pid_map = first_seen[["Username", "PID"]]
    qbu = qbu.merge(pid_map, on="Username", how="left")
    return qbu, pid_map


def build_demographics(qbu: pd.DataFrame) -> pd.DataFrame:
    qbu = qbu.copy()
    qbu["PrimaryRole"] = (
        qbu["Roles"].str.split(";|,|/").str[0].str.strip().replace("", "Unknown")
    )
    demog = (
        qbu.groupby("PrimaryRole")
        .agg(users=("PID", "nunique"), questions=("Question", "count"))
        .reset_index()
        .sort_values("users", ascending=False)
        .reset_index(drop=True)
    )
    return demog


def plot_role_distribution(demog: pd.DataFrame) -> None:
    plt.figure(figsize=(8, 5))
    sns.barplot(data=demog, y="PrimaryRole", x="users", color="steelblue")
    plt.xlabel("Participants")
    plt.ylabel("Primary role")
    plt.title("OntoSage++ pre-design survey: participants by primary role")
    plt.tight_layout()
    plt.savefig(OUT / "figures" / "A2_role_distribution.png", dpi=300)
    plt.savefig(OUT / "figures" / "A2_role_distribution.pdf")
    plt.close()


def build_user_summary(qbu: pd.DataFrame) -> pd.DataFrame:
    qbu = qbu.copy()
    qbu["PrimaryRole"] = (
        qbu["Roles"].str.split(";|,|/").str[0].str.strip().replace("", "Unknown")
    )
    summary = (
        qbu.groupby(["PID", "PrimaryRole"])
        .agg(
            total_q=("Question", "count"),
            s1_q=("Stage", lambda s: int((s == 1).sum())),
            s2_q=("Stage", lambda s: int((s == 2).sum())),
            s3_q=("Stage", lambda s: int((s == 3).sum())),
            s4_q=("Stage", lambda s: int((s == 4).sum())),
            first_ts=("Timestamp", "min"),
            last_ts=("Timestamp", "max"),
        )
        .reset_index()
        .sort_values("PID")
    )
    return summary


def append_summary_md(n_users: int, n_questions: int, demog: pd.DataFrame) -> None:
    path = ROOT / "corpus" / "corpus_summary_stats.md"
    line = (
        f"- Phase A: {n_users} unique participants across "
        f"{demog['PrimaryRole'].nunique()} primary roles, {n_questions} total questions.\n"
    )
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if "Phase A:" in existing:
            new = []
            for ln in existing.splitlines(keepends=True):
                if ln.lstrip().startswith("- Phase A:"):
                    new.append(line)
                else:
                    new.append(ln)
            path.write_text("".join(new), encoding="utf-8")
            return
        path.write_text(existing.rstrip() + "\n" + line, encoding="utf-8")
    else:
        header = "# Corpus Summary Statistics\n\nKey numbers cited by the paper.\n\n"
        path.write_text(header + line, encoding="utf-8")


def main() -> None:
    qbu_raw, _tr, _qr = load_inputs()
    qbu = clean_questions(qbu_raw)
    qbu, pid_map = assign_pids(qbu)
    pid_map.to_csv(OUT / "intermediate" / "username_to_pid.csv", index=False)

    demog = build_demographics(qbu)
    demog.to_csv(OUT / "tables" / "A2_demographics_table.csv", index=False)
    plot_role_distribution(demog)

    user_summary = build_user_summary(qbu)
    user_summary.to_csv(OUT / "tables" / "A3_user_summary.csv", index=False)

    n_users = qbu["PID"].nunique()
    n_questions = len(qbu)
    append_summary_md(n_users, n_questions, demog)
    print(f"Phase A done. {n_users} users, {n_questions} questions.")
    print(f"  Roles: {demog['PrimaryRole'].nunique()}")
    print(f"  Stage counts: " + ", ".join(
        f"S{s}={int((qbu['Stage'] == s).sum())}" for s in sorted(qbu['Stage'].unique())
    ))


if __name__ == "__main__":
    main()
