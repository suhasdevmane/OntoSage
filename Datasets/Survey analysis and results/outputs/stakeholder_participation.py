"""
Stakeholder participation analysis.

Counts how many UNIQUE participants took part in the survey per stakeholder
persona (PrimaryPersona), alongside the volume of questions they contributed. This is
used to:
  1. See which stakeholder groups are under-represented (lowest participant count).
  2. Normalise question volume by number of participants (questions / participant).
  3. Decide which low-count categories to top up or merge.

Source of truth: outputs/tables/A3_user_summary.csv  (one row per participant)

Outputs:
  outputs/tables/A4_stakeholder_participation.csv          (detailed table)
  outputs/tables/A4_stakeholder_participation_grouped.csv  (with low-count personas merged)
  outputs/figures/A4_stakeholder_participation.png/.pdf     (bar chart)
"""

from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless backend (no GUI / Qt) for batch image export
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Paths (resolved relative to this file so it runs from anywhere)
# ---------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent          # .../Survey analysis and results/outputs
USER_SUMMARY = BASE / "tables" / "A3_user_summary.csv"
TABLES_DIR = BASE / "tables"
FIG_DIR = BASE / "figures"

# Personas considered specialist / domain-expert stakeholders. These are the
# groups the study cares about recruiting more of. The general public personas
# (Guests, Occupants, Student) are the "lay" comparison groups.
SPECIALIST_PERSONAS = {
    "Building Owners",
    "Facility Managers",
    "IT",
    "Health and Safety Officers",
    "Sustainability and Energy Management Teams",
}


def stakeholder_participation(user_summary_path: Path = USER_SUMMARY) -> pd.DataFrame:
    """Build the stakeholder participation table from the per-participant summary.

    Returns one row per PrimaryPersona with:
      participants            unique participants in that persona
      questions               total questions contributed
      pct_participants        share of all participants (%)
      pct_questions           share of all questions (%)
      questions_per_participant  mean questions per participant (normalisation)
      is_specialist           True for domain-expert stakeholder groups
    """
    df = pd.read_csv(user_summary_path)

    # Each PID appears exactly once in A3, so a simple group-by counts unique
    # participants. We still guard against accidental duplicate PIDs.
    df = df.drop_duplicates(subset="PID")

    grp = (
        df.groupby("PrimaryPersona")
        .agg(participants=("PID", "nunique"), questions=("total_q", "sum"))
        .reset_index()
    )

    total_participants = grp["participants"].sum()
    total_questions = grp["questions"].sum()

    grp["pct_participants"] = (grp["participants"] / total_participants * 100).round(1)
    grp["pct_questions"] = (grp["questions"] / total_questions * 100).round(1)
    grp["questions_per_participant"] = (grp["questions"] / grp["participants"]).round(1)
    grp["is_specialist"] = grp["PrimaryPersona"].isin(SPECIALIST_PERSONAS)

    # Sort fewest participants first so the under-represented groups are obvious.
    grp = grp.sort_values(["participants", "questions"], ascending=[True, True]).reset_index(drop=True)
    return grp


def merge_low_count_personas(table: pd.DataFrame, threshold: int = 3) -> pd.DataFrame:
    """Collapse specialist personas with <= `threshold` participants into a single
    'Other Domain Experts (combined)' row, so the lowest categories can be
    analysed together.
    """
    low = table["is_specialist"] & (table["participants"] <= threshold)

    kept = table.loc[~low].copy()
    if low.any():
        combined = table.loc[low]
        merged_row = {
            "PrimaryPersona": "Other Domain Experts (combined)",
            "participants": int(combined["participants"].sum()),
            "questions": int(combined["questions"].sum()),
            "is_specialist": True,
        }
        kept = pd.concat([kept, pd.DataFrame([merged_row])], ignore_index=True)

    total_p = kept["participants"].sum()
    total_q = kept["questions"].sum()
    kept["pct_participants"] = (kept["participants"] / total_p * 100).round(1)
    kept["pct_questions"] = (kept["questions"] / total_q * 100).round(1)
    kept["questions_per_participant"] = (kept["questions"] / kept["participants"]).round(1)
    kept = kept.sort_values("participants").reset_index(drop=True)
    return kept


def plot_participation(table: pd.DataFrame, out_png: Path, out_pdf: Path) -> None:
    """Horizontal bar chart: participants per persona, coloured by specialist vs lay,
    annotated with question counts."""
    t = table.sort_values("participants")
    colors = ["#2a7fb8" if s else "#9aa7b1" for s in t["is_specialist"]]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.barh(t["PrimaryPersona"], t["participants"], color=colors)

    for bar, (_, row) in zip(bars, t.iterrows()):
        ax.text(
            bar.get_width() + 0.2,
            bar.get_y() + bar.get_height() / 2,
            f"{int(row['participants'])}p · {int(row['questions'])}q",
            va="center",
            fontsize=8.5,
        )

    ax.set_xlabel("Number of unique participants")
    ax.set_title("Survey participation by stakeholder persona\n(blue = specialist stakeholder, grey = lay group)")
    ax.set_xlim(0, t["participants"].max() * 1.18)
    ax.margins(y=0.01)
    fig.tight_layout()
    fig.savefig(out_png, dpi=200)
    fig.savefig(out_pdf)
    plt.close(fig)


def main() -> None:
    table = stakeholder_participation()
    grouped = merge_low_count_personas(table, threshold=3)

    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    detailed_csv = TABLES_DIR / "A4_stakeholder_participation.csv"
    grouped_csv = TABLES_DIR / "A4_stakeholder_participation_grouped.csv"
    table.to_csv(detailed_csv, index=False)
    grouped.to_csv(grouped_csv, index=False)

    plot_participation(
        table,
        FIG_DIR / "A4_stakeholder_participation.png",
        FIG_DIR / "A4_stakeholder_participation.pdf",
    )

    # Console report -------------------------------------------------------
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", None)
    print("=== Stakeholder participation (detailed) ===")
    print(table.to_string(index=False))
    print(f"\nTotal: {table['participants'].sum()} participants, {table['questions'].sum()} questions, "
          f"{len(table)} distinct personas")

    print("\n=== Lowest-count specialist personas (<=3 participants) ===")
    low = table[(table['is_specialist']) & (table['participants'] <= 3)]
    print(low[["PrimaryPersona", "participants", "questions"]].to_string(index=False))

    print("\n=== With low-count specialist personas merged ===")
    print(grouped.to_string(index=False))

    print(f"\nWrote:\n  {detailed_csv}\n  {grouped_csv}\n  {FIG_DIR / 'A4_stakeholder_participation.png'}")


if __name__ == "__main__":
    main()
