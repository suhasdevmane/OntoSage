# Analysis Methodology: Smart Building NL Query Corpus

## A Journal-Grade Data Analysis Plan

**Study:** A Survey-Based Study to Develop a Corpus of Natural Language Queries for Smart Building Interaction  
**Dataset Snapshot (Canonical Master Corpus, 96 Participants):**

| Metric                                           | Value                                                                                                                                           |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Total participants                               | **96** unique participants                                                                                                                      |
| User personas represented                        | **8** primary personas (Students, Facility Managers, Sustainability/Energy, Building Owners, IT/Data Science, H&S Officers, Occupants, Guests) |
| Total question records (`classified_corpus.csv`) | **7,151** questions                                                                                                                             |
| Unique questions (`questions_by_user_unique.csv`) | **6,117** questions (deduplicated via NFKC, lowercase, punctuation-stripped)                                                                   |
| Stage 1 questions (Open-Minded, zero context)    | **1,904** (26.6%)                                                                                                                               |
| Stage 2 questions (Sensing & Semantics)          | **2,003** (28.0%)                                                                                                                               |
| Stage 3 questions (Scenario-Based / 3D Live)     | **1,705** (23.8%)                                                                                                                               |
| Stage 4 questions (Goal-Oriented)                | **1,539** (21.5%)                                                                                                                               |
| Topic rankers / rankings (Stage 5 Task 1)        | **91** participants / **1,820** rank entries across 20 domains                                                                                  |
| Question rankers / rankings (Stage 5 Task 2)     | **760** within-topic 4-level rankings (L1–L4)                                                                                                   |
| Vision responses (Stage 5 Task 3)                | **59** participants / **295** responses (9,396 words across 5 prompts)                                                                           |
| Mean questions per user (Stages 1–4)             | **74.5** (median 74.0; min 60, max 94)                                                                                                          |
| Master Corpus File                               | [`corpus/classified_corpus.csv`](corpus/classified_corpus.csv) (anonymised PIDs P01–P96)                                                        |

---

## Part 1: Research Questions

This analysis addresses six primary research questions (RQs), each mapping to empirical findings (`SF1`–`SF24`) and direct system design specifications:

| RQ      | Question                                                                                                                                                       | Primary Data Source                                                      | Key Analytical Methods                                       |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------ |
| **RQ1** | What types of natural language queries do building occupants ask for smart building interaction, and how can they be systematically categorised?               | `corpus/classified_corpus.csv`                                           | 6-tuple taxonomy coding, frequency profiling, cross-tab      |
| **RQ2** | How does the elicitation method (open-ended vs. sensor-prompted vs. scenario-based vs. goal-oriented) affect the nature, diversity, and complexity of queries? | `corpus/classified_corpus.csv` (Stage column)                            | Kruskal-Wallis, Dunn's post-hoc, Chi-squared, TF-IDF, cosine |
| **RQ3** | How does user persona (e.g., facility manager vs. student vs. visitor) influence query focus and priority?                                                     | `corpus/classified_corpus.csv` (Personas) + `inputs/topic_rankings.csv`  | Chi-squared independence, Cramer's V, Kendall's W concordance|
| **RQ4** | Which smart building domains do users prioritise, and what is the consensus ranking?                                                                           | `inputs/topic_rankings.csv`                                              | Borda count, Kendall's W, hierarchical clustering, bootstrap |
| **RQ5** | Within prioritised domains, which sub-question complexity levels (Basic to Expert) are most valued?                                                            | `inputs/question_rankings.csv`                                           | Preference frequency, Bradley-Terry modeling, persona cross   |
| **RQ6** | Can the resulting corpus inform the design and architectural requirements of an agentic smart building conversational system?                                  | Synthesis of RQ1–RQ5, `complexity_master_table.csv`, `recommendations.csv` | Two-axis cognitive/latent complexity, gap analysis, coverage |

---

## Part 2: Analysis Pipeline (Step-by-Step)

The analysis is organized into sequential phases (A through L, plus Stage 5 qualitative and paper synthesis scripts). The pipeline is deterministic and reproducible without external APIs for Phases A–I, while Phase J uses frozen-prompt LLM evaluation.

### Phase A: Data Preparation & Demographics Profiling

**Step A1 — Master Ingestion & Anonymisation**
- Ingest `corpus/classified_corpus.csv` (or `inputs/questions_by_user.csv`).
- Establish stable participant identifiers (`P01`..`P96`) ordered by initial timestamp, anonymising raw participant identity.
- Verify referential integrity across questions, topic rankings, and question rankings.
- Script: [`scripts/A_data_preparation.py`](scripts/A_data_preparation.py)
- Outputs: `outputs/intermediate/username_to_pid.csv`, `outputs/tables/A2_demographics_table.csv`, `outputs/tables/A3_user_summary.csv`, `outputs/figures/A2_persona_distribution.png`.

**Step A2 — Persona Harmonisation**
- Resolve multi-persona labels into primary personas (8 standardized categories).
- Profile participation balance and completion rates across occupant vs. operational personas.
- Standalone verification: [`outputs/stakeholder_participation.py`](outputs/stakeholder_participation.py) (`outputs/tables/A4_stakeholder_participation*.csv`).

---

### Phase B: Corpus Construction, Taxonomy & Statistics (RQ1)

**Step B1 — Six-Tuple Taxonomy Definition**
Every question in `corpus/classified_corpus.csv` is characterized across six formal dimensions:
1. **Domain (L1, 20 categories)**: `TEMPERATURE`, `AIR_QUALITY`, `LIGHTING`, `NOISE`, `ENERGY`, `SECURITY`, `OCCUPANCY`, `FIRE_SAFETY`, `WATER`, `WASTE`, `SOLAR`, `GREEN_SPACES`, `HEALTH_WELLBEING`, `IOT_ANALYTICS`, `INTERNAL_TRANSPORT`, `PARKING_EV`, `AUTOMATION_AI`, `DIGITAL_INTERACTION`, `MAINTENANCE_FAULTS`, `NET_ZERO`.
2. **Query Type (L2, 10 categories)**: `STATUS`, `CAPABILITY`, `HISTORY`, `COMPARISON`, `ANOMALY`, `CAUSE`, `FORECAST`, `OPTIMIZATION`, `CONTROL`, `POLICY`.
3. **Intent (4 categories)**: `INFORMATIONAL`, `DIAGNOSTIC`, `PRESCRIPTIVE`, `PREDICTIVE`.
4. **Temporal Scope (3 categories)**: `REAL_TIME`, `HISTORICAL`, `PREDICTIVE` (also `STATIC`).
5. **Spatial Scope (4 categories)**: `ROOM`, `FLOOR`, `BUILDING`, `CAMPUS/UNSPECIFIED`.
6. **Surface Complexity (3 categories)**: `LOOKUP`, `AGGREGATION`, `REASONING`.

**Step B2 — Corpus Classification & Verification**
- Classification source of truth: [`corpus/classified_corpus.csv`](corpus/classified_corpus.csv).
- Deterministic regex/lexicon classifier backup: [`scripts/B_corpus_classification.py`](scripts/B_corpus_classification.py).
- Inter-rater reliability (IRR) on 300 sampled questions (`taxonomy/irr_samples.csv`): [`scripts/B3_irr_llm_coder.py`](scripts/B3_irr_llm_coder.py), [`scripts/B3_irr_compute.py`](scripts/B3_irr_compute.py) yielding Cohen's Kappa $\kappa \ge 0.70$.

**Step B3 — Corpus Statistics & Distribution Profiling**
- Compute unigram/bigram distributions, token lengths, domain proportions, intent cross-tabulations.
- Script: [`scripts/B4_corpus_statistics.py`](scripts/B4_corpus_statistics.py).
- Outputs: `outputs/tables/B4_corpus_statistics.csv`, figures `B4_domain_distribution.png`, `B4_intent_distribution.png`, `B4_complexity_distribution.png`, `B4_domain_intent_heatmap.png`, `B4_domain_complexity_heatmap.png`.

---

### Phase C: Stage Comparison & Elicitation Effects (RQ2)

Evaluates how progressive disclosure across Stages 1–4 affects query formulation:
- **Stage 1 (Open-Minded)**: Zero context, pure unprompted intuition.
- **Stage 2 (Sensing & Semantics)**: 43 sensors and operational terms disclosed.
- **Stage 3 (Scenario-Based)**: 8 spatial cards + interactive 3D digital twin with live Floor 5 sensor telemetry.
- **Stage 4 (Goal-Oriented)**: 10 sustainability/well-being themes.

**Statistical Procedures:**
- Non-parametric Kruskal-Wallis $H$-tests for continuous metrics (word length, domain diversity, complexity index).
- Post-hoc Dunn's pairwise tests with Bonferroni adjustment.
- $\chi^2$ test of independence for intent shifts across stages with Cramér's $V$ effect size.
- TF-IDF distinctive n-gram analysis per stage.
- Semantic novelty decay: Sentence-transformer (`all-MiniLM-L6-v2`) embeddings measuring cosine distance of each user's subsequent questions against all their earlier submissions (threshold $< 0.75$).
- Script: [`scripts/C_stage_comparison.py`](scripts/C_stage_comparison.py).
- Outputs: `outputs/tables/C1_stage_comparison.csv`, `outputs/tables/C2_dunn_tests.csv`, `outputs/tables/C3_novelty_analysis.csv`, figures `C1_stage_comparison.png`, `C2_stage_tfidf.png`, `C3_novelty_by_stage.png`.

---

### Phase D: Persona Divergence & Concordance (RQ3)

Investigates role-specific interaction patterns:
- Persona $\times$ Domain contingency tables normalized by row and column.
- $\chi^2$ test of independence (Persona vs. Domain, Cramér's $V = 0.28$).
- Intra-persona ranking consensus using Kendall's coefficient of concordance ($W$).
- Inter-persona Spearman rank correlations ($\rho$).
- Script: [`scripts/D_persona_analysis.py`](scripts/D_persona_analysis.py).
- Outputs: `outputs/tables/D1_persona_domain_contingency.csv`, `outputs/tables/D2_concordance_table.csv`, figures `D1_persona_domain_heatmap.png`, `D2_rank_by_persona.png`, `outputs/reports/D3_user_personas.md`.

---

### Phase E: Topic Prioritisation & Consensus (RQ4)

Analyses Stage 5 Task 1 (91 participants ranking all 20 smart building domains):
- **Borda Count**: Linear position-weighted aggregation ($20$ points for rank 1, descending to $1$ point for rank 20).
- Bootstrap 95% confidence intervals (1,000 iterations) on mean ranks.
- Overall inter-user agreement via Kendall's $W$.
- Hierarchical agglomerative clustering (Ward's linkage on Spearman distance matrix) discovering domain bundles (Comfort, Utilities, Infrastructure).
- Script: [`scripts/E_topic_priorities.py`](scripts/E_topic_priorities.py).
- Outputs: `outputs/tables/E1_topic_priority_table.csv`, figures `E1_borda_scores.png`, `E2_topic_dendrogram.png`, `E3_priority_vs_volume.png`.

---

### Phase F: Question Depth & Complexity Preferences (RQ5)

Analyses Stage 5 Task 2 (within-topic ranking of 4 complexity levels across 10 top topics):
- Evaluation of four participant-facing depth levels: **Basic (L1)**, **Intermediate (L2)**, **Advanced (L3)**, **Expert (L4)**.
- First-choice vs. last-choice win ratios, Bradley-Terry preference modeling.
- Persona-stratified demand for analytical depth (e.g., Facility Managers preferring L3/L4 vs. Occupants preferring L1).
- Script: [`scripts/F_question_preferences.py`](scripts/F_question_preferences.py).
- Outputs: `outputs/tables/F1_question_preferences_by_topic.csv`, `outputs/tables/F1_overall_level_preference.csv`, figures `F1_question_preference_by_topic.png`, `F2_complexity_preference.png`.

---

### Phase G & I: Framework Synthesis & Demand Crosswalk (RQ6)

- Cross-tabulates Borda priority (importance) against analytical depth (L4 preference) to discover high-priority/high-complexity focal targets.
- Formalises the priority-weighted system capability matrix.
- Scripts: [`scripts/G_framework_synthesis.py`](scripts/G_framework_synthesis.py), [`scripts/I_borda_vs_analytical_demand.py`](scripts/I_borda_vs_analytical_demand.py).
- Outputs: `outputs/tables/G2_capability_matrix.csv`, `outputs/tables/G4_gap_analysis.csv`, `outputs/tables/I1_borda_vs_l4_demand.csv`, figures `G3_framework_architecture.png`, `I1_borda_vs_l4_scatter.png`.

---

### Phase H: System Replay Evaluation

- Evaluates OntoSage replay execution on real smart building test instances (`outputs/survey_evaluation_results.csv`).
- Assesses answer accuracy, query execution latency, SPARQL translation success, semantic fallback rates.
- Script: [`scripts/H_evaluation_analysis.py`](scripts/H_evaluation_analysis.py) $\to$ `outputs/tables/H_evaluation_summary.csv`.

---

### Phase J, K, L: Two-Axis Complexity & Architectural Traceability

**Two-Axis Rubric:**
1. **Surface Axis (Human Cognitive Load, L1–L6)**: Factual Recall $\to$ Comparative $\to$ Inferential $\to$ Causal Diagnosis $\to$ Systemic Synthesis $\to$ Meta/Strategic.
2. **Latent Axis (System Architectural Effort, L1–L6)**: Single SPARQL lookup $\to$ multi-read aggregation $\to$ multi-hop KG traversal $\to$ time-series analytics/correlation $\to$ multi-system data fusion/modelling $\to$ closed-loop planning/actuation.

- **Deduplication**: [`scripts/clean_duplicate_questions.py`](scripts/clean_duplicate_questions.py) produces `inputs/questions_by_user_unique.csv` (6,117 questions) from `corpus/classified_corpus.csv`.
- **Classification Engine**: [`scripts/J_complexity_master_table.py`](scripts/J_complexity_master_table.py) (GPT-5.5 / LLM, temperature 1, resumable via key index).
- **Iceberg & Gap Analytics**: [`scripts/K_master_table_analysis.py`](scripts/K_master_table_analysis.py) detects questions where Surface Level is low (e.g. L1 "can it measure X?") but Latent Level is high (L4/L5 requiring sensor fusion and new telemetry pipelines).
- **Engineering Crosswalk**: [`scripts/L_architecture_coverage.py`](scripts/L_architecture_coverage.py) maps corpus intents to the system intent registry and module backlog in `<repo-root>/tasks/`.

---

### Phase Z: Qualitative Vision & Paper Syntheses

- **Stage 5 Task 3 Qualitative Analysis**: [`scripts/Z_stage5_vision_analysis.py`](scripts/Z_stage5_vision_analysis.py) analyses 295 open-ended responses (9,396 words) across 5 vision prompts from `inputs/recommendations.csv`. Addresses response bias (Fisher's exact $p < 0.0001$) and student trust cluster filtering. Output: `outputs/tables/Z_stage5_vision_themes.csv`.
- **Publication Tables & Figures**: [`scripts/Z_paper_combined_figures.py`](scripts/Z_paper_combined_figures.py), [`scripts/Z_paper_derived_tables.py`](scripts/Z_paper_derived_tables.py) generating LaTeX-ready tables (`Z_paper_constants.csv`, `Z_intent_by_stage.csv`, `Z_domain_by_stage.csv`).

---

## Part 3: Statistical Methods Summary

| Analysis Area                        | Statistical Method                | Implementation Package           | Exact Function / Purpose                                      |
| ------------------------------------ | --------------------------------- | -------------------------------- | ------------------------------------------------------------- |
| Stage Differences (Continuous)       | Kruskal-Wallis $H$-test           | `scipy.stats.kruskal`            | Omnibus non-parametric test of word length / diversity across |
| Stage Post-Hoc Pairwise              | Dunn's test (Bonferroni)          | `scikit-posthocs.posthoc_dunn`   | Pairwise contrast between S1, S2, S3, S4                      |
| Stage / Persona Categorical Shifts   | Chi-squared ($\chi^2$)            | `scipy.stats.chi2_contingency`   | Independence tests for Intent, Domain across stages/personas  |
| Effect Sizes (Categorical)           | Cramér's $V$                      | Custom (`sqrt(chi2 / (n * k))`)  | Quantify strength of association (e.g. $V = 0.28$)            |
| Intra-Persona Consensus              | Kendall's $W$ (Concordance)       | Custom from Friedman chi-square  | Quantifies agreement within persona on 20 topic rankings      |
| Inter-Persona Correlation            | Spearman's rank correlation $\rho$| `scipy.stats.spearmanr`          | Pairwise ranking alignment between stakeholder roles          |
| Text Semantic Novelty                | Cosine similarity on embeddings   | `sentence-transformers`          | Distance to prior user questions ($<0.75$ novel)              |
| Human Coding Validation              | Cohen's Kappa ($\kappa$)          | `sklearn.metrics.cohen_kappa_score` | Inter-rater agreement on 300 questions ($\ge 0.70$ target)   |
| Topic Clustering                     | Hierarchical (Ward's linkage)     | `scipy.cluster.hierarchy`        | Dendrogram discovery of functional domain bundles             |
| Priority Aggregation                 | Borda count + Bootstrap 95% CI    | `numpy`                          | Positional scoring across 91 rankers                          |
| Response Bias (Vision Task 3)        | Fisher's exact test               | `scipy.stats.fisher_exact`       | Completion rate differences (Occupant vs. Operational)        |
| Question Deduplication               | NFKC Unicode + regex canonical    | Standard library (`re`, `unicodedata`) | Lossless collapse of trivial variants (case/punct/quotes)     |

---

## Part 4: Complete Inventory of Required Visualisations

| #   | File Name                                      | Figure Type                         | Generating Script                |
| --- | ---------------------------------------------- | ----------------------------------- | -------------------------------- |
| 1   | `outputs/figures/A2_persona_distribution.png`  | Horizontal bar chart                | `scripts/A_data_preparation.py`  |
| 2   | `outputs/figures/B4_domain_distribution.png`   | Horizontal bar chart (20 domains)   | `scripts/B4_corpus_statistics.py`|
| 3   | `outputs/figures/B4_intent_distribution.png`   | Bar chart                           | `scripts/B4_corpus_statistics.py`|
| 4   | `outputs/figures/B4_complexity_distribution.png`| Bar chart                          | `scripts/B4_corpus_statistics.py`|
| 5   | `outputs/figures/B4_temporal_spatial_distribution.png`| Dual grouped bar chart       | `scripts/B4_corpus_statistics.py`|
| 6   | `outputs/figures/B4_domain_intent_heatmap.png` | Annotated 2D heatmap                | `scripts/B4_corpus_statistics.py`|
| 7   | `outputs/figures/B4_domain_complexity_heatmap.png` | Annotated 2D heatmap            | `scripts/B4_corpus_statistics.py`|
| 8   | `outputs/figures/C1_stage_comparison.png`      | Multi-panel boxplots (metrics by stage)| `scripts/C_stage_comparison.py`|
| 9   | `outputs/figures/C2_stage_tfidf.png`           | 4-panel horizontal bar charts       | `scripts/C_stage_comparison.py`  |
| 10  | `outputs/figures/C3_novelty_by_stage.png`      | Line chart with confidence intervals| `scripts/C_stage_comparison.py`  |
| 11  | `outputs/figures/D1_persona_domain_heatmap.png`| Annotated percentage heatmap        | `scripts/D_persona_analysis.py`  |
| 12  | `outputs/figures/D2_rank_by_persona.png`       | Small-multiples ranking comparison  | `scripts/D_persona_analysis.py`  |
| 13  | `outputs/figures/E1_borda_scores.png`          | Lollipop ranking chart with CIs     | `scripts/E_topic_priorities.py`  |
| 14  | `outputs/figures/E2_topic_dendrogram.png`      | Hierarchical clustering dendrogram  | `scripts/E_topic_priorities.py`  |
| 15  | `outputs/figures/E3_priority_vs_volume.png`    | Scatter plot with regression line   | `scripts/E_topic_priorities.py`  |
| 16  | `outputs/figures/F1_question_preference_by_topic.png` | Grouped bar chart (L1–L4)    | `scripts/F_question_preferences.py`|
| 17  | `outputs/figures/F2_complexity_preference.png` | Persona $\times$ Depth stacked bar  | `scripts/F_question_preferences.py`|
| 18  | `outputs/figures/G3_framework_architecture.png`| High-resolution system schematic    | `scripts/G_framework_synthesis.py`|
| 19  | `outputs/figures/I1_borda_vs_l4_scatter.png`   | Priority vs. Advanced demand quadrant| `scripts/I_borda_vs_analytical_demand.py`|
| 20  | `outputs/master table analysis/F1_surface_vs_latent.png` | Two-axis scatter / bubble | `scripts/K_master_table_analysis.py`|
| 21  | `outputs/master table analysis/F2_iceberg_distribution.png` | Iceberg disparity histogram| `scripts/K_master_table_analysis.py`|
| 22  | `outputs/master table analysis/F3_capability_gaps.png` | Horizontal bar of missing feeds| `scripts/K_master_table_analysis.py`|
| 23  | `outputs/master table analysis/F4_answerability.png` | Donut / pie chart              | `scripts/K_master_table_analysis.py`|
| 24  | `outputs/master table analysis/F5_persona_difficulty.png` | Grouped bar by persona   | `scripts/K_master_table_analysis.py`|
| 25  | `outputs/master table analysis/F6_architecture_components.png` | Architectural dependency count | `scripts/K_master_table_analysis.py`|

---

## Part 5: Master File Dependencies & Reproduction Guide

### Input Files Required to Run All Scripts

| File Path                                          | Role                                                                                 |
| -------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `corpus/classified_corpus.csv`                     | **Master Corpus Source of Record** (7,151 rows, P01–P96, 6-tuple annotations)        |
| `inputs/questions_by_user_unique.csv`              | Deduplicated question corpus (6,117 rows; generated via `clean_duplicate_questions.py`) |
| `inputs/topic_rankings.csv` (and `.json`)          | Stage 5 Task 1 domain rankings (91 users $\times$ 20 topics)                         |
| `inputs/question_rankings.csv` (and `.json`)       | Stage 5 Task 2 depth-level rankings (760 topic-level ranking sets)                   |
| `inputs/recommendations.csv` (and `.json`)         | Stage 5 Task 3 vision reflections (59 users $\times$ 5 prompts)                      |
| `inputs/topics_reference.csv`                      | Topic catalog (20 Topic IDs and definitions)                                         |
| `inputs/questions_reference.csv`                   | 4 question templates (L1–L4) per topic                                               |
| `outputs/survey_evaluation_results.csv`            | OntoSage replay query-answering test results (for Phase H)                           |
| `outputs/tables/complexity_master_table.csv`       | Pre-computed LLM two-axis complexity classifications (for Phase K & L)               |

### Full Execution Sequence

```bash
# 1. Regenerate unique questions corpus from master classified_corpus.csv
python scripts/clean_duplicate_questions.py --input corpus/classified_corpus.csv --output inputs/questions_by_user_unique.csv --report

# 2. Run deterministic statistical pipeline (Phases A–I)
python scripts/A_data_preparation.py
python scripts/B4_corpus_statistics.py
python scripts/C_stage_comparison.py
python scripts/D_persona_analysis.py
python scripts/E_topic_priorities.py
python scripts/F_question_preferences.py
python scripts/G_framework_synthesis.py
python scripts/H_evaluation_analysis.py
python scripts/I_borda_vs_analytical_demand.py

# 3. Stakeholder participation & Stage 5 vision analysis
python outputs/stakeholder_participation.py
python scripts/Z_stage5_vision_analysis.py

# 4. Paper figures & derived constants
python scripts/Z_paper_combined_figures.py
python scripts/Z_paper_derived_tables.py

# 5. Master table analysis & architectural crosswalk (consumes pre-computed or freshly run complexity table)
python scripts/K_master_table_analysis.py
python scripts/L_architecture_coverage.py

# 6. Report generation (Markdown to PDF)
python scripts/_md_to_pdf.py "outputs/SURVEY_ANALYSIS_REPORT.md"
python scripts/_md_to_pdf.py "outputs/SURVEY_TO_SYSTEM_TRACEABILITY.md"
python scripts/_md_to_pdf.py "outputs/master table analysis/MASTER_ANALYSIS_REPORT.md"
```
