# OntoSage++ Paper Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a journal-grade IMWUT submission for OntoSage++ by (a) running the survey analysis pipeline end-to-end, (b) replacing every fabricated stat in the .tex draft with real values, (c) restructuring the paper to mirror the Guo et al. sample, (d) integrating the 15-person post-deployment evaluation already stored in `paper/post_design_survey/`.

**Architecture:** Two parallel tracks. Track 1 (analysis) writes Python scripts implementing Phases A-G of `ANALYSIS_METHODOLOGY.md`, producing CSV tables and figures. Track 2 (paper) revises `paper/research paper.tex` section by section against the IMWUT sample structure, citing Track 1 outputs and `paper/post_design_survey/summary_stats.csv` as evidence. Both tracks use the scoped sub-agents and skills set up in 2026-04-11-paper-writing-design.md.

**Tech Stack:** Python (pandas, scipy, scikit-learn, scikit-posthocs, sentence-transformers, matplotlib, seaborn), Anthropic SDK for LLM classification, LaTeX (`acmsmall` template).

---

## Track 1: Survey Analysis (Phases A-G)

### Task 1: Phase A — Data Preparation

**Files:**
- Create: `paper/Survey analysis and results/scripts/A_data_preparation.py`
- Read: `paper/Survey analysis and results/inputs/{questions_by_user,topic_rankings,question_rankings}.csv`
- Output: `outputs/tables/A2_demographics_table.csv`, `outputs/figures/A2_role_distribution.{png,pdf}`, `outputs/tables/A3_user_summary.csv`, `outputs/intermediate/username_to_pid.csv`

- [ ] **Step 1: Install dependencies**

```bash
pip install pandas numpy scipy scikit-learn scikit-posthocs matplotlib seaborn sentence-transformers anthropic
```

- [ ] **Step 2: Write `A_data_preparation.py`**

Use the template in `.claude/skills/survey-analysis.md` "Phase A" section. Key requirements:
- `np.random.seed(42)`
- Anonymise usernames → `P01..P60` via stable hash
- Save mapping to `intermediate/username_to_pid.csv`
- Demographics by primary role (first listed)
- Per-user summary with stage counts and timestamps

- [ ] **Step 3: Run the script**

```bash
cd "c:/Users/suhas/Documents/GitHub/OntoSage"
python "paper/Survey analysis and results/scripts/A_data_preparation.py"
```

Expected output: `Phase A done. NN users, 5127 questions.`

- [ ] **Step 4: Verify outputs exist**

```bash
ls "paper/Survey analysis and results/outputs/tables/A"*
ls "paper/Survey analysis and results/outputs/figures/A"*
```

- [ ] **Step 5: Update `paper/PROGRESS.md`**

Mark A1, A2, A3 ✅. Append to `corpus/corpus_summary_stats.md`:
```
- Phase A: NN unique participants across MM roles, 5127 total questions.
```

- [ ] **Step 6: Refresh paper participant counts immediately**

Run `/paper-stats` to replace `42 participants` in the abstract with the real value from `A2_demographics_table.csv`. Log replacement in `PROGRESS.md` "Stat refresh log".

- [ ] **Step 7: Commit**

```bash
git add "paper/Survey analysis and results/scripts/A_data_preparation.py" "paper/Survey analysis and results/outputs/" "paper/PROGRESS.md" "paper/research paper.tex"
git commit -m "feat(paper): Phase A data preparation + refresh participant counts"
```

---

### Task 2: Phase B1 — Taxonomy Draft

**Files:**
- Create: `paper/Survey analysis and results/taxonomy/taxonomy_v1.md`
- Create: `paper/Survey analysis and results/taxonomy/coding_guide.md`
- Read: 200 random questions from `questions_by_user.csv`

- [ ] **Step 1: Sample 200 questions**

```python
# inline script
import pandas as pd, numpy as np
np.random.seed(42)
df = pd.read_csv("paper/Survey analysis and results/inputs/questions_by_user.csv")
sample = df.sample(200, random_state=42)
sample[["Stage","Question"]].to_csv(
    "paper/Survey analysis and results/taxonomy/sample_200.csv", index=False)
```

- [ ] **Step 2: Read the 200 questions and draft taxonomy_v1.md**

Two-level structure:
```
Level 1 (Domain): one of the 20 survey topics
Level 2 (Query Type): Current Status / Historical Trend / Comparison / Anomaly Detection / Recommendation / Setpoint / Diagnostic
```
Plus cross-cutting dimensions: Intent (Informational/Diagnostic/Prescriptive/Predictive), Temporal (Real-time/Historical/Predictive), Spatial (Room/Floor/Building/Zone), Complexity (Lookup/Aggregation/Multi-step).

- [ ] **Step 3: Draft `coding_guide.md`** with one example per Level 2 category and clear inclusion/exclusion rules.

- [ ] **Step 4: Commit**

```bash
git add "paper/Survey analysis and results/taxonomy/"
git commit -m "feat(paper): Phase B1 taxonomy v1 + coding guide"
```

---

### Task 3: Phase B2 — LLM Classification

**Files:**
- Create: `paper/Survey analysis and results/scripts/B_corpus_classification.py`
- Output: `corpus/classified_corpus.csv`

- [ ] **Step 1: Set ANTHROPIC_API_KEY env var**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 2: Write `B_corpus_classification.py`**

Use Anthropic Batch API for cost efficiency (5,127 calls). Prompt template:
```
You are classifying smart-building natural language queries against a fixed taxonomy.

TAXONOMY:
{paste taxonomy_v1.md}

QUESTION: "{question}"

Respond with JSON only:
{"domain_l1": "...", "query_type_l2": "...", "intent": "...", "temporal": "...", "spatial": "...", "complexity": "..."}
```

- [ ] **Step 3: Run classification (long-running, use background)**

```bash
python "paper/Survey analysis and results/scripts/B_corpus_classification.py"
```

- [ ] **Step 4: Verify** `corpus/classified_corpus.csv` has 5,127 rows and no missing dimensions.

- [ ] **Step 5: Commit**

```bash
git add "paper/Survey analysis and results/scripts/B_corpus_classification.py" "paper/Survey analysis and results/corpus/classified_corpus.csv"
git commit -m "feat(paper): Phase B2 LLM corpus classification"
```

---

### Task 4: Phase B3 — Inter-Rater Reliability

**Files:**
- Create: `paper/Survey analysis and results/taxonomy/irr_samples.csv`
- Create: `paper/Survey analysis and results/outputs/tables/B3_irr_report.md`

- [ ] **Step 1: Sample 300 questions for two human coders**

```python
import pandas as pd, numpy as np
np.random.seed(43)
df = pd.read_csv("paper/Survey analysis and results/corpus/classified_corpus.csv")
irr = df.sample(300, random_state=43)
irr.to_csv("paper/Survey analysis and results/taxonomy/irr_samples.csv", index=False)
```

- [ ] **Step 2: Coordinate two human coders** to annotate `irr_samples.csv` independently using `coding_guide.md`. Save as `irr_samples_coderA.csv` and `irr_samples_coderB.csv`.

- [ ] **Step 3: Compute Cohen's Kappa**

```python
from sklearn.metrics import cohen_kappa_score
# per dimension
for dim in ["domain_l1","query_type_l2","intent","temporal","spatial","complexity"]:
    k = cohen_kappa_score(coderA[dim], coderB[dim])
    print(f"{dim}: kappa={k:.3f}")
```

- [ ] **Step 4: Write `B3_irr_report.md`** with kappa per dimension, target ≥ 0.70. If any dimension fails, hold a discussion round and re-annotate disagreements.

- [ ] **Step 5: Commit**

```bash
git add "paper/Survey analysis and results/taxonomy/" "paper/Survey analysis and results/outputs/tables/B3_irr_report.md"
git commit -m "feat(paper): Phase B3 inter-rater reliability"
```

---

### Task 5: Phase B4 — Corpus Statistics

**Files:**
- Append to: `B_corpus_classification.py` (or create `B4_stats.py`)
- Output: `outputs/tables/B4_corpus_statistics.csv`, `outputs/figures/B4_domain_distribution.{png,pdf}`, `outputs/figures/B4_intent_heatmap.{png,pdf}`

- [ ] **Step 1: Frequency tables** for each taxonomy dimension
- [ ] **Step 2: Cross-tabs** Domain × Intent, Domain × Complexity
- [ ] **Step 3: Question length analysis** (word count, char count distributions)
- [ ] **Step 4: Generate figures** (300 dpi PNG + PDF)
- [ ] **Step 5: Update `PROGRESS.md`** ✅ B1-B4
- [ ] **Step 6: Run `/paper-stats`** to replace 68%/80% Stage 1/2 fabricated cluster split with real numbers from `B4_corpus_statistics.csv`
- [ ] **Step 7: Commit**

---

### Task 6: Phase C — Stage Comparison

**Files:**
- Create: `paper/Survey analysis and results/scripts/C_stage_comparison.py`
- Output: `outputs/tables/C1_stage_stats.csv`, `outputs/figures/C2_stage_tfidf_comparison.{png,pdf}`, `outputs/tables/C2_stage_evolution_table.md`, `outputs/tables/C3_novelty_analysis.csv`, `outputs/figures/C3_novelty_by_stage.{png,pdf}`

- [ ] **Step 1: Quantitative stage comparison** — diversity index, complexity score, mean question length, intent type proportions per stage
- [ ] **Step 2: Statistical tests** — Kruskal-Wallis + Dunn's post-hoc (Bonferroni), Chi² + Cramer's V, epsilon-squared
- [ ] **Step 3: TF-IDF top terms** per stage (4 panels)
- [ ] **Step 4: Novelty analysis** — SBERT `all-MiniLM-L6-v2`, cosine similarity, threshold 0.75
- [ ] **Step 5: Run + verify outputs**
- [ ] **Step 6: Update PROGRESS.md** ✅ C1-C3
- [ ] **Step 7: Commit**

---

### Task 7: Phase D — Role Analysis

**Files:**
- Create: `paper/Survey analysis and results/scripts/D_role_analysis.py`
- Output: `outputs/figures/D1_role_domain_heatmap.{png,pdf}`, `outputs/tables/D1_chi_squared_results.md`, `outputs/figures/D2_rank_by_role.{png,pdf}`, `outputs/tables/D2_concordance_table.csv`, `outputs/tables/D3_user_personas.md`

- [ ] **Step 1: Role × domain contingency table + Chi² independence test** (Cramer's V)
- [ ] **Step 2: Heatmap** (row-normalised)
- [ ] **Step 3: Topic ranking by role** — Kendall's W within roles, Spearman between roles
- [ ] **Step 4: Synthesise 4-5 personas** in `D3_user_personas.md` (typical domains, complexity, priority topics, sample questions per persona)
- [ ] **Step 5: Update PROGRESS.md** ✅ D1-D3
- [ ] **Step 6: Commit**

---

### Task 8: Phase E — Topic Priorities

**Files:**
- Create: `paper/Survey analysis and results/scripts/E_topic_rankings.py`
- Output: `outputs/tables/E1_topic_priority_table.csv`, `outputs/figures/E1_borda_scores.{png,pdf}`, `outputs/figures/E2_topic_dendrogram.{png,pdf}`, `outputs/tables/E2_topic_clusters.md`, `outputs/figures/E3_priority_vs_volume_scatter.{png,pdf}`

- [ ] **Step 1: Borda count** + bootstrap 95% CI on mean ranks
- [ ] **Step 2: Kendall's W** for overall inter-user agreement
- [ ] **Step 3: Hierarchical clustering** on co-ranking correlation matrix → dendrogram
- [ ] **Step 4: Top vs bottom topics** — cross-reference with question volume from Phase B
- [ ] **Step 5: Update PROGRESS.md** ✅ E1-E3
- [ ] **Step 6: Commit**

---

### Task 9: Phase F — Question Preferences

**Files:**
- Create: `paper/Survey analysis and results/scripts/F_question_rankings.py`
- Output: `outputs/tables/F1_question_preferences_by_topic.csv`, `outputs/figures/F2_complexity_preference.{png,pdf}`

- [ ] **Step 1: Within-topic preference frequency** (rank 1-4)
- [ ] **Step 2: Map question levels to complexity** + compare across roles
- [ ] **Step 3: Update PROGRESS.md** ✅ F1-F2
- [ ] **Step 4: Commit**

---

### Task 10: Phase G — Framework Synthesis

**Files:**
- Create: `paper/Survey analysis and results/scripts/G_framework_synthesis.py`
- Output: `outputs/tables/G3_capability_matrix.csv`, `outputs/tables/G4_gap_analysis.md`

- [ ] **Step 1: Classification framework spec** — formalise the validated taxonomy from Phase B
- [ ] **Step 2: Capability matrix** — rows = query types, columns = priority level (from Phase E)
- [ ] **Step 3: Gap analysis** — identify query types existing systems can't answer; classify (data gap / reasoning gap / integration gap)
- [ ] **Step 4: Update PROGRESS.md** ✅ G1-G4
- [ ] **Step 5: Commit**

---

## Track 2: Paper Restructure + Stat Refresh

### Task 11: Verify post-deployment evaluation artefacts

**Files:**
- Verify: `paper/post_design_survey/responses.csv` (15 rows, anonymised P_pd_01..P_pd_15)
- Verify: `paper/post_design_survey/summary_stats.csv` (mean SUS 84.5, NASA-TLX, task completion, adoption intent)
- Verify: `paper/post_design_survey/README.md` (study summary, instruments, 8 task descriptions)

- [ ] **Step 1: Confirm responses.csv** has 15 rows with role mix 6 Student/Researcher + 4 IT/Operator + 5 Visitor/Guest
- [ ] **Step 2: Recompute SUS** from raw items per row, ensure each matches the recorded SUS_Score column
- [ ] **Step 3: Recompute summary_stats.csv** aggregates from responses.csv (mean SUS, by-role means, completion rate, adoption %)
- [ ] **Step 4: Confirm README.md** matches actual file contents
- [ ] **Step 5: Commit any corrections**

---

### Task 12: Restructure abstract to mirror sample

- [ ] **Step 1: Read** `paper/CLAUDE.md` "Sample paper structure" + abstract guidance
- [ ] **Step 2: Read** `paper/research paper.tex` lines 200-209 only
- [ ] **Step 3: Rewrite abstract** as 2 paragraphs (problem + contribution), 250-300 words, citing real Phase A demographics and the post-deployment SUS/adoption results from `summary_stats.csv`
- [ ] **Step 4: Update PROGRESS.md** Section history
- [ ] **Step 5: Compile + commit**

---

### Task 13: Restructure introduction

- [ ] Match Guo et al. flow: trend → gap → 4 RQs → system name → contributions → roadmap
- [ ] Lines 223-262
- [ ] Reuse existing RQ block (it's already 4 RQs)
- [ ] Add explicit paper roadmap paragraph at end
- [ ] Compile + commit

---

### Task 14: Update Related Work to 3 sub-streams

- [ ] Lines 263-290
- [ ] Three sub-streams already present (HBI, Semantic Conv AI, Heterogeneity)
- [ ] Add 2-3 most recent (2025-2026) citations; verify each in `references.bib` first
- [ ] Compile + commit

---

### Task 15: Restructure Phase 1 / Methodology section to cite real data

- [ ] Lines 291-374
- [ ] Replace `68%`/`80%` Cluster split with real Phase B4 numbers
- [ ] Add ethics statement: SREC COMSC/Ethics/2025/044b, Amazon MTurk HIT, paid participation
- [ ] Reference `A2_role_distribution.png` and `B4_domain_distribution.png` figures
- [ ] Compile + commit

---

### Task 16: Trim System Design section

- [ ] Lines 375-510
- [ ] Currently ~135 lines — sample equivalent is similar, may need trimming if total page count exceeds 22
- [ ] Verify Algorithm 1 matches actual workflow
- [ ] Compile + commit

---

### Task 17: Restructure Phase 2 / Deployment section with post-deployment evaluation

- [ ] Lines 511-762
- [ ] Replace `42 participants` with `15 participants` (6 Student/Researcher + 4 IT/Operator + 5 Visitor/Guest)
- [ ] Cite SUS mean (84.5), task completion (98.3%), adoption intent (93.3%) from `paper/post_design_survey/summary_stats.csv`
- [ ] Add NASA-TLX summary table (mean per dimension) referencing the same CSV
- [ ] Compile + commit

---

### Task 18: Restructure Results & Discussion (RQ subsections)

- [ ] Lines 763-892
- [ ] One subsection per RQ, each with: numerical claim → figure → example → interpretation
- [ ] RQ1 cites Phase B + C
- [ ] RQ2 cites worked examples (already present)
- [ ] RQ3 cites Phase G capability matrix + T0-T3 effort table (real numbers from author's notebook)
- [ ] RQ4 cites the 15-person post-deployment evaluation (SUS, NASA-TLX, task completion, adoption)
- [ ] Replace `87.3%` with real `98.3%` task completion; replace `90%` with real T0-T3 effort comparison; recast `66.4%` time reduction as a qualitative claim or remove until a baseline study runs
- [ ] Compile + commit

---

### Task 19: Tighten Implications + Limitations + Conclusion

- [ ] Lines 893-988
- [ ] Limitations: explicit mention of (a) single-language, (b) MTurk demographic skew in pre-design corpus, (c) 3 buildings only, (d) small post-deployment sample (n=15) drawn from a single university site
- [ ] Conclusion: 200-400 words wrap
- [ ] Compile + commit

---

### Task 20: Final stat sweep + submission checklist

- [ ] **Step 1: Run `/paper-stats`** one final time
- [ ] **Step 2: Verify zero placeholders**
  ```bash
  grep -c "TBD-from\|87\.3\|66\.4\|42 participants" "paper/research paper.tex"
  ```
  Must return `0`.
- [ ] **Step 3: Verify zero usernames**
  ```bash
  grep -if <(cut -d, -f1 "paper/Survey analysis and results/inputs/questions_by_user.csv" | tail -n +2) "paper/research paper.tex"
  ```
  Must return empty.
- [ ] **Step 4: Verify all bib keys**
  ```bash
  pdflatex "research paper.tex" && bibtex "research paper" 2>&1 | grep -i "warning"
  ```
- [ ] **Step 5: Page count check**
  ```bash
  pdfinfo "paper/research paper.pdf" | grep Pages
  ```
  Target ≤22.
- [ ] **Step 6: Walk through `paper/PROGRESS.md` submission checklist** — every box checked
- [ ] **Step 7: Commit final** + tag `v1.0-submission`

---

## Self-review checklist

- [ ] Every spec section has at least one task
- [ ] No `TBD` / `TODO` / `implement later` placeholders in this plan
- [ ] Every task lists exact file paths
- [ ] Every task ends with a commit step
- [ ] Phase B depends on A; C-F depend on B; G depends on B-F (dependency order respected)
- [ ] Track 2 task ordering allows incremental compilation (each section can compile after each commit)
- [ ] No task assumes a CSV exists before its producing task has run
