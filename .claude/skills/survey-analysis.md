---
name: survey-analysis
description: Use when running any phase (A-G) of the OntoSage++ survey corpus analysis defined in ANALYSIS_METHODOLOGY.md, or when adding/refreshing a statistical claim that the paper will cite.
---

# Survey Analysis Runbook — OntoSage++ Corpus Study

## Always Start Here

1. Read `paper/PROGRESS.md` — find the next pending phase
2. Read the relevant phase from `paper/Survey analysis and results/ANALYSIS_METHODOLOGY.md`
3. Check `paper/Survey analysis and results/outputs/tables/` for prior outputs you depend on
4. Activate Python env: `pip install pandas numpy scipy scikit-learn scikit-posthocs matplotlib seaborn sentence-transformers anthropic`

## Folder Convention

```
paper/Survey analysis and results/
├── ANALYSIS_METHODOLOGY.md     <- contract; do not modify
├── inputs/                     <- raw CSVs; READ-ONLY
│   ├── questions_by_user.csv
│   ├── topic_rankings.csv
│   └── question_rankings.csv
├── scripts/                    <- one .py per phase
│   ├── A_data_preparation.py
│   ├── B_corpus_classification.py
│   ├── C_stage_comparison.py
│   ├── D_role_analysis.py
│   ├── E_topic_rankings.py
│   ├── F_question_rankings.py
│   └── G_framework_synthesis.py
├── taxonomy/
│   ├── taxonomy_v1.md          <- written during Phase B1
│   ├── coding_guide.md         <- coder instructions
│   └── irr_samples.csv         <- 300 questions for IRR
├── corpus/
│   ├── classified_corpus.csv   <- final B2 output (the deliverable)
│   └── corpus_summary_stats.md <- key numbers for the paper
└── outputs/
    ├── tables/                 <- CSVs cited by the paper
    ├── figures/                <- PNG (300dpi) + PDF for paper
    └── intermediate/           <- working files, NOT for paper
```

## Phase A: Data Preparation (~1 hour)

```python
# A_data_preparation.py
import pandas as pd, numpy as np, matplotlib.pyplot as plt, seaborn as sns
from pathlib import Path
import hashlib

np.random.seed(42)
ROOT = Path("paper/Survey analysis and results")
INP, OUT = ROOT/"inputs", ROOT/"outputs"
(OUT/"tables").mkdir(parents=True, exist_ok=True)
(OUT/"figures").mkdir(parents=True, exist_ok=True)
(OUT/"intermediate").mkdir(parents=True, exist_ok=True)

# Load
qbu = pd.read_csv(INP/"questions_by_user.csv")
tr  = pd.read_csv(INP/"topic_rankings.csv")
qr  = pd.read_csv(INP/"question_rankings.csv")

# A1: clean
qbu["Username"] = qbu["Username"].str.strip().str.lower()
qbu["Timestamp"] = pd.to_datetime(qbu["Timestamp"], errors="coerce")
qbu["Question"]  = qbu["Question"].str.strip()
qbu = qbu.dropna(subset=["Question"])
qbu = qbu[qbu["Question"].str.len() > 0]

# Anonymise (stable hash → P01..PNN)
def pid(name, idx_map):
    if name not in idx_map:
        idx_map[name] = f"P{len(idx_map)+1:02d}"
    return idx_map[name]
idx_map = {}
qbu["PID"] = qbu["Username"].apply(lambda n: pid(n, idx_map))
pd.DataFrame(list(idx_map.items()), columns=["Username", "PID"]).to_csv(
    OUT/"intermediate"/"username_to_pid.csv", index=False)

# A2: demographics
qbu["PrimaryRole"] = qbu["Roles"].fillna("Unknown").str.split(";").str[0].str.strip()
demog = qbu.groupby("PrimaryRole").agg(
    users=("PID","nunique"), questions=("Question","count")
).reset_index().sort_values("users", ascending=False)
demog.to_csv(OUT/"tables"/"A2_demographics_table.csv", index=False)

plt.figure(figsize=(8,5))
sns.barplot(data=demog, y="PrimaryRole", x="users", color="steelblue")
plt.title("Participants by Primary Role")
plt.tight_layout()
plt.savefig(OUT/"figures"/"A2_role_distribution.png", dpi=300)
plt.savefig(OUT/"figures"/"A2_role_distribution.pdf")
plt.close()

# A3: per-user summary
user_summary = qbu.groupby(["PID","PrimaryRole"]).agg(
    total_q=("Question","count"),
    s1_q=("Stage", lambda s: (s==1).sum()),
    s2_q=("Stage", lambda s: (s==2).sum()),
    s3_q=("Stage", lambda s: (s==3).sum()),
    s4_q=("Stage", lambda s: (s==4).sum()),
    first_ts=("Timestamp","min"),
    last_ts=("Timestamp","max"),
).reset_index()
user_summary.to_csv(OUT/"tables"/"A3_user_summary.csv", index=False)

print(f"Phase A done. {qbu['PID'].nunique()} users, {len(qbu)} questions.")
```

## Phase B: Taxonomy + Classification (~2 sessions)

**B1 (manual + LLM-assisted):** Sample 200 random questions, draft `taxonomy/taxonomy_v1.md` with two levels (Domain × Query Type) + cross-cutting (Intent, Temporal, Spatial, Complexity).

**B2 (LLM batch):** Use Claude API to classify all 5,127. Prompt template lives in `scripts/B_corpus_classification.py`. Output: `corpus/classified_corpus.csv`.

**B3 (IRR):** Random 300 sample → 2 human coders → Cohen's Kappa per dimension. Target ≥ 0.70.

**B4 (stats):** Frequency tables + cross-tabs.

## Phase C: Stage Comparison (~1 session)

Kruskal-Wallis across 4 stages on: diversity index, complexity score, question length. Post-hoc Dunn's with Bonferroni. Chi² on intent type proportions. Effect sizes mandatory (epsilon-squared, Cramer's V).

Novelty: SBERT embeddings, cosine similarity, threshold 0.75.

## Phase D: Role Analysis (~1 session)

Chi² independence (role × domain). Kendall's W for within-role rank concordance. Spearman for between-role rank correlation. Synthesise 4-5 personas in `D3_user_personas.md`.

## Phase E: Topic Priorities (~1 session)

Borda count (rank-1 → 20 points, rank-20 → 1 point). Bootstrap 95% CI on mean ranks. Hierarchical clustering on co-ranking correlation matrix → dendrogram.

## Phase F: Question Preferences (~0.5 session)

Per topic: how often each question level (1-4) is ranked 1st/2nd/3rd/4th. Bradley-Terry or simple frequency.

## Phase G: Framework Synthesis (~1 session)

Cross-reference taxonomy × topic priorities × question preferences → capability matrix. Identify gap types (data gap, reasoning gap, integration gap). This becomes the bridge to OntoSage++ system design and the future-work section.

## Hard Rules

- `np.random.seed(42)` and `random.seed(42)` in every script
- Never modify files in `inputs/`
- Every figure must have a corresponding CSV in `outputs/tables/` (so paper can quote exact numbers)
- Anonymise: never write usernames into `outputs/tables/`; map to PID via `intermediate/username_to_pid.csv`
- Effect sizes alongside p-values, always
- Append a 1-line "key finding" to `corpus/corpus_summary_stats.md` after every phase
- Update `paper/PROGRESS.md` after every phase

## Expected Runtime

| Phase | Wall time | Notes |
|-------|-----------|-------|
| A | ~5 min | Pure pandas |
| B1 | manual | Read 200 questions, draft taxonomy |
| B2 | ~30 min | Claude API: 5,127 calls × ~3 sec ≈ 4 hours unless batched. Use batch API. |
| B3 | manual | 2 coders × 300 questions ≈ 2 hours each |
| B4 | ~5 min | Pandas |
| C | ~20 min | SBERT embeddings dominate |
| D | ~5 min | Pure scipy |
| E | ~5 min | Bootstrap is the slowest part |
| F | ~2 min | — |
| G | manual + ~10 min | Synthesis |

## Handoff to paper-writing Skill

After completing a phase, the paper-writing skill consumes the outputs. Update `paper/PROGRESS.md` with the new artifact paths so the paper-agent can find them without grepping.
