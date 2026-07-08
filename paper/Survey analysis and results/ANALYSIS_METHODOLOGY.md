# Analysis Methodology: Smart Building NL Query Corpus
## A Journal-Grade Data Analysis Plan

**Study:** A Survey-Based Study to Develop a Corpus of Natural Language Queries for Smart Building Interaction
**SREC Reference:** COMSC/Ethics/2025/044b
**Dataset Snapshot (as of April 2026):**

| Metric | Value |
|--------|-------|
| Total participants | ~60 unique users |
| Total questions collected | 5,127 |
| Questions per stage | S1: 1,502 / S2: 1,472 / S3: 1,146 / S4: 1,007 |
| Topic rankings (Stage 5) | 50 users (all ranked 20/20 topics) |
| Question rankings (Stage 5) | 412 rows across users/topics |
| User personas represented | 10+ categories (Guests, Students, Facility Managers, IT, Owners, H&S, etc.) |
| Avg questions per user | ~85 |

---

## Part 1: Research Questions

This analysis must answer the following research questions (RQs), each mapping to a publishable finding:

| RQ | Question | Data Source |
|----|----------|-------------|
| **RQ1** | What types of natural language queries do building occupants generate for smart building interaction, and how can they be systematically categorised? | `questions_by_user.csv` |
| **RQ2** | How does the elicitation method (open-ended vs. sensor-prompted vs. scenario-based vs. goal-oriented) affect the nature, diversity, and complexity of queries? | `questions_by_user.csv` (Stage column) |
| **RQ3** | How does user persona (e.g., facility manager vs. student vs. visitor) influence query focus and priority? | `questions_by_user.csv` (Personas column) + `topic_rankings.csv` |
| **RQ4** | Which smart building domains do users prioritise, and what is the consensus ranking? | `topic_rankings.csv` |
| **RQ5** | Within prioritised domains, which sub-question types are most valued? | `question_rankings.csv` |
| **RQ6** | Can the resulting corpus inform the design of a smart building NL query-answering framework? | Synthesis of RQ1-RQ5 |

---

## Part 2: Analysis Pipeline (Step-by-Step)

### Phase A: Data Preparation & Quality Assurance

**Step A1 — Data Loading & Cleaning**
- Load all three CSV files into pandas DataFrames
- Normalise usernames (lowercase, strip whitespace)
- Parse timestamps into datetime objects
- Verify referential integrity (all users in questions exist in rankings)
- Report: missing values, duplicate entries, empty questions

**Step A2 — Demographic Profiling**
- Parse the Personas column (multi-persona users have semicolon-separated values)
- Create a primary persona assignment (first listed persona) and a full persona set
- Build a participant demographics table: user count, question count, completion rate per persona
- Output: `A2_demographics_table.csv`, `A2_persona_distribution.png`

**Step A3 — Per-User Summary Statistics**
- Questions per user (total, per stage)
- Time-on-task estimates (first to last timestamp per user per stage)
- Identify outliers (very low or very high contributors)
- Output: `A3_user_summary.csv`

---

### Phase B: Corpus Construction & Annotation (RQ1)

This is the core contribution — building a categorised NL query corpus.

**Step B1 — Taxonomy Development (Grounded in Data)**

Use a two-pass approach:
1. **Deductive seed categories** from the 20 topic labels already in the survey (Indoor Temperature, Air Quality, Lighting, etc.)
2. **Inductive refinement** via open coding of 200 randomly sampled questions to discover sub-categories and cross-cutting themes

Produce a **two-level taxonomy**:
```
Level 1 (Domain):     e.g., "Energy Consumption"
Level 2 (Query Type): e.g., "Current Status" / "Historical Trend" / "Comparison" / "Anomaly Detection" / "Recommendation"
```

Additional cross-cutting dimensions to annotate:
- **Intent type**: Informational / Diagnostic / Prescriptive / Predictive
- **Temporal scope**: Real-time / Historical / Predictive
- **Spatial scope**: Room-level / Floor-level / Building-wide / Zone-specific
- **Complexity**: Simple lookup / Aggregation / Multi-step reasoning

**Step B2 — Automated Pre-Classification**
- Use an LLM (Claude API) to pre-classify all 5,127 questions against the taxonomy
- Prompt template: provide the taxonomy, provide the question, ask for Level-1 domain, Level-2 query type, intent, temporal scope, spatial scope, complexity
- Output: `B2_classified_corpus.csv` with columns: Username, Stage, Question, Domain_L1, QueryType_L2, Intent, Temporal, Spatial, Complexity

**Step B3 — Inter-Rater Reliability**
- Randomly sample 300 questions (~6% of corpus)
- Two human coders independently annotate using the taxonomy
- Compute Cohen's Kappa for each dimension
- Resolve disagreements through discussion
- Target: Kappa >= 0.70 (substantial agreement)
- Output: `B3_irr_report.md`, `B3_confusion_matrices.png`

**Step B4 — Corpus Statistics**
- Frequency distribution of each taxonomy dimension
- Cross-tabulation: Domain x Intent, Domain x Complexity
- Question length analysis (word count, character count distributions)
- Output: `B4_corpus_statistics.csv`, `B4_domain_distribution.png`, `B4_intent_heatmap.png`

---

### Phase C: Stage Comparison Analysis (RQ2)

**Step C1 — Quantitative Stage Comparison**

For each of the four stages, compute:
- Number of unique domains covered per user (diversity index)
- Mean question complexity score
- Mean question length (word count)
- Proportion of intent types (informational vs. diagnostic vs. prescriptive vs. predictive)

Statistical tests:
- **Kruskal-Wallis H-test** (non-parametric ANOVA) for continuous measures across 4 stages
- **Post-hoc Dunn's test** with Bonferroni correction for pairwise comparisons
- **Chi-squared test** for intent-type proportions across stages
- Effect sizes: Epsilon-squared for Kruskal-Wallis, Cramer's V for chi-squared

**Step C2 — Qualitative Stage Comparison**
- Thematic analysis of how question style evolves across stages
- Stage 1 (open-ended) vs. Stage 2 (sensor-prompted): do sensor terms appear?
- Stage 3 (scenario-based): do spatial references increase?
- Stage 4 (goal-oriented): do sustainability/goal terms increase?
- Word frequency comparison across stages using TF-IDF
- Output: `C2_stage_tfidf_comparison.png`, `C2_stage_evolution_table.md`

**Step C3 — Novelty and Overlap Analysis**
- For each user: what proportion of their Stage 2/3/4 questions are genuinely new vs. rephrased from Stage 1?
- Use sentence embeddings (e.g., `all-MiniLM-L6-v2`) to compute semantic similarity
- Define "novel" as cosine similarity < 0.75 to all prior questions by same user
- Report: novelty rate per stage, per user
- Output: `C3_novelty_analysis.csv`, `C3_novelty_by_stage.png`

---

### Phase D: Persona-Based Analysis (RQ3)

**Step D1 — Persona x Domain Cross-Tabulation**
- Build a contingency table: rows = persona categories, columns = Level-1 domains
- Normalise by row (percentage of each persona's questions per domain)
- Heatmap visualisation
- Chi-squared test of independence (persona vs. domain)
- Output: `D1_persona_domain_heatmap.png`, `D1_chi_squared_results.md`

**Step D2 — Persona x Topic Ranking Comparison**
- From `topic_rankings.csv`: compute mean rank per topic, broken down by persona
- Use **Kendall's W** (coefficient of concordance) to measure agreement within personas
- Use **Spearman rank correlation** to compare ranking patterns between personas
- Output: `D2_rank_by_persona.png`, `D2_concordance_table.csv`

**Step D3 — Persona Personas**
- Synthesise findings into 4-5 "user personas" based on persona clusters
- Each persona includes: typical query domains, preferred complexity, priority topics, representative sample questions
- Output: `D3_user_personas.md`

---

### Phase E: Topic Prioritisation Analysis (RQ4)

**Step E1 — Aggregate Topic Rankings**
- From `topic_rankings.csv`: compute mean rank, median rank, mode rank for each of the 20 topics
- Compute **Borda count** (assign 20 points to rank-1, 19 to rank-2, etc.) for a composite score
- Kendall's W for overall inter-user agreement
- Bootstrap 95% confidence intervals on mean ranks
- Output: `E1_topic_priority_table.csv`, `E1_borda_scores.png`

**Step E2 — Topic Clustering**
- Cluster the 20 topics based on how similarly users rank them
- Use a co-ranking correlation matrix (Spearman between topic pairs across users)
- Hierarchical clustering + dendrogram
- Identify topic "bundles" (e.g., comfort bundle = temperature + air quality + lighting)
- Output: `E2_topic_dendrogram.png`, `E2_topic_clusters.md`

**Step E3 — Top vs. Bottom Topics**
- Identify consistently top-5 and bottom-5 topics
- Analyse what distinguishes high-priority from low-priority topics
- Cross-reference with question volume from Phase B
- Output: `E3_priority_vs_volume_scatter.png`

---

### Phase F: Question Ranking Analysis (RQ5)

**Step F1 — Within-Topic Question Preferences**
- From `question_rankings.csv`: for each topic, compute how often each question level (L1-L4) is ranked 1st, 2nd, 3rd, 4th
- Bradley-Terry model or simple frequency analysis for preference ordering
- Output: `F1_question_preferences_by_topic.csv`

**Step F2 — Complexity Preference Patterns**
- Map question levels to complexity dimensions
- Are simpler (lookup) questions preferred, or do users want complex (analytical) queries?
- Compare preference patterns across personas
- Output: `F2_complexity_preference.png`

---

### Phase G: Framework Design (RQ6)

This phase synthesises all findings into a practical contribution.

**Step G1 — Query Classification Framework**
- Using the validated taxonomy from Phase B, define a formal classification model
- Specify the input (raw NL text) and output (Domain, Intent, Temporal, Spatial, Complexity)
- Report classification accuracy from Step B2 and inter-rater agreement from Step B3

**Step G2 — Priority-Weighted Capability Matrix**
- Cross-reference the taxonomy with topic priorities (Phase E) and question preferences (Phase F)
- Build a matrix: rows = query types the system must handle, columns = priority level based on user data
- This becomes the requirements specification for a smart building NL interface

**Step G3 — Framework Architecture Diagram**
- Propose a high-level system architecture for answering the queries in the corpus
- Components: NL parser -> Intent classifier -> Domain router -> Data source selector -> Response generator
- Map each component to the evidence from the data analysis
- Output: `G3_framework_architecture.png`, `G3_capability_matrix.csv`

**Step G4 — Gap Analysis**
- Identify query types in the corpus that existing smart building systems cannot answer
- Classify gaps: data availability gap, reasoning gap, integration gap
- This becomes the "future work" section of the paper
- Output: `G4_gap_analysis.md`

---

## Part 3: Statistical Methods Summary

| Analysis | Method | Package | Purpose |
|----------|--------|---------|---------|
| Cross-stage comparison (continuous) | Kruskal-Wallis + Dunn's post-hoc | `scipy.stats`, `scikit-posthocs` | Compare question attributes across 4 stages |
| Cross-stage comparison (categorical) | Chi-squared + Cramer's V | `scipy.stats` | Compare intent/domain distributions |
| Topic ranking agreement | Kendall's W | `scipy.stats` | Measure inter-user consensus |
| Persona x domain independence | Chi-squared | `scipy.stats` | Test if persona predicts domain focus |
| Persona ranking comparison | Spearman correlation | `scipy.stats` | Compare ranking patterns |
| Semantic similarity | Cosine similarity on embeddings | `sentence-transformers` | Detect novel vs. repeated questions |
| Inter-rater reliability | Cohen's Kappa | `sklearn.metrics` | Validate human annotation |
| Topic clustering | Hierarchical clustering | `scipy.cluster.hierarchy` | Group co-ranked topics |
| Aggregate ranking | Borda count + bootstrap CI | Custom + `numpy` | Composite priority scores |
| Classification | LLM-based (Claude API) | `anthropic` SDK | Automated corpus annotation |

---

## Part 4: Visualisations Required

| # | Figure | Type | Tool |
|---|--------|------|------|
| 1 | Participant demographics by persona | Horizontal bar chart | matplotlib/seaborn |
| 2 | Questions per user distribution | Histogram + box plot | matplotlib |
| 3 | Domain distribution (Level 1) | Stacked bar or treemap | matplotlib/plotly |
| 4 | Intent type by stage | Grouped bar chart | seaborn |
| 5 | Stage comparison: diversity & complexity | Box plots (4 stages) | seaborn |
| 6 | TF-IDF top terms per stage | Horizontal bar charts (4 panels) | matplotlib |
| 7 | Novelty rate across stages | Line chart with CI bands | matplotlib |
| 8 | Persona x Domain heatmap | Annotated heatmap | seaborn |
| 9 | Topic priority (Borda scores) | Horizontal lollipop chart | matplotlib |
| 10 | Topic dendrogram | Hierarchical dendrogram | scipy |
| 11 | Priority vs. volume scatter | Scatter with labels | matplotlib |
| 12 | Question preference by topic | Small multiples bar charts | matplotlib |
| 13 | Framework architecture | System diagram | draw.io / tikz |
| 14 | Capability matrix | Annotated grid | matplotlib |

---

## Part 5: Execution Order & Tool Selection

### Recommended Execution Sequence

```
Phase A (Data Prep)          ~1 session    Python + pandas
    |
Phase B (Taxonomy + Coding)  ~2 sessions   Claude API + manual review
    |
Phase C (Stage Analysis)     ~1 session    Python + scipy + sentence-transformers
    |
Phase D (Persona Analysis)      ~1 session    Python + scipy
    |
Phase E (Topic Rankings)     ~1 session    Python + scipy + numpy
    |
Phase F (Question Rankings)  ~0.5 session  Python + pandas
    |
Phase G (Framework Design)   ~1 session    Synthesis + diagramming
```

### Python Environment Setup

```bash
pip install pandas numpy scipy scikit-learn scikit-posthocs matplotlib seaborn
pip install sentence-transformers anthropic wordcloud
```

### Folder Structure

```
analysis and results/
    ANALYSIS_METHODOLOGY.md          <- this file
    scripts/
        A_data_preparation.py
        B_corpus_classification.py
        C_stage_comparison.py
        D_persona_analysis.py
        E_topic_rankings.py
        F_question_rankings.py
        G_framework_synthesis.py
    outputs/
        tables/                      <- CSV tables for the paper
        figures/                     <- PNG/PDF figures for the paper
        intermediate/                <- Working files not for publication
    taxonomy/
        taxonomy_v1.md               <- Initial taxonomy definition
        coding_guide.md              <- Instructions for human coders
        irr_samples.csv              <- 300 questions for inter-rater reliability
    corpus/
        classified_corpus.csv        <- Final annotated corpus (the deliverable)
        corpus_summary_stats.md      <- Key numbers for the paper
```

---

## Part 6: Paper Outline Mapping

Each analysis phase maps to a section of the paper:

| Paper Section | Content Source |
|---------------|---------------|
| **3. Methodology** | Survey design (stages 1-5), elicitation strategy, participant recruitment |
| **3.1 Participants** | Phase A: demographics table |
| **3.2 Survey Design** | Stage descriptions, rationale for 4-stage elicitation |
| **3.3 Data Collection** | Corpus size, collection period, ethical approval |
| **3.4 Analysis Approach** | This methodology document (statistical methods, taxonomy) |
| **4.1 Corpus Overview** | Phase B: taxonomy, domain distribution, intent distribution |
| **4.2 Stage Comparison** | Phase C: how elicitation method affects queries |
| **4.3 Persona-Based Differences** | Phase D: how user persona influences queries |
| **4.4 Topic Prioritisation** | Phase E: aggregate rankings, topic clusters |
| **4.5 Question Preferences** | Phase F: within-topic preference patterns |
| **5. Framework Design** | Phase G: classification framework, capability matrix, architecture |
| **6. Discussion** | Synthesis: implications for smart building NL interfaces |
| **7. Limitations** | Sample size, single-building context, simulated data |

---

## Part 7: Key Quality Criteria for Journal Publication

To meet the standards of journals such as Building and Environment, Automation in Construction, or Applied Energy:

1. **Rigour in coding**: Two independent coders + Cohen's Kappa >= 0.70
2. **Statistical reporting**: Effect sizes alongside p-values, confidence intervals on key estimates
3. **Reproducibility**: All scripts committed, random seeds documented, data anonymised
4. **Triangulation**: Quantitative (statistics) + qualitative (thematic analysis) + user rankings converging on findings
5. **Contribution clarity**: The corpus itself IS the primary contribution; the framework is secondary
6. **Data availability**: Anonymised corpus published as supplementary material or open dataset
7. **Limitations honesty**: Discuss simulated participants, single-building context, English-only

---

## Part 8: How to Begin (First 3 Actions)

1. **Run Phase A** — Execute `A_data_preparation.py` to load, clean, and profile the data. This gives you the demographics table and confirms data quality.

2. **Develop taxonomy (Step B1)** — Read 200 random questions manually. Draft the two-level taxonomy. This is the intellectual core of the paper and cannot be fully automated.

3. **Classify corpus (Step B2)** — Use Claude API to annotate all 5,127 questions. Then validate with human inter-rater reliability on 300 samples.

Everything else builds on the classified corpus.
