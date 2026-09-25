# Pre-Design Survey & Corpus Analysis — OntoSage

**What this folder is:** the complete empirical foundation of OntoSage. It contains the pre-development survey corpus, the full analysis pipeline that turns that corpus into journal-grade findings, the LLM-graded complexity master table, and the reports that trace every finding to a concrete OntoSage design decision. In short: **this folder is the specification; the OntoSage codebase is its implementation.**

> **If you read one thing, read [`outputs/SURVEY_ANALYSIS_REPORT.md`](outputs/SURVEY_ANALYSIS_REPORT.md)** — the full findings (SF1–SF24). Then [`outputs/SURVEY_TO_SYSTEM_TRACEABILITY.md`](outputs/SURVEY_TO_SYSTEM_TRACEABILITY.md) for the findings→system audit trail.

**Study:** A Survey-Based Corpus Study to Characterise Natural Language Interaction Needs for Smart Buildings · **Author:** Suhas Devmane.

---

## Current dataset (post-2026-06-25 refresh)

|                                    |                                                                                                                                           |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Participants                       | **96** across **8 personas**                                                                                                              |
| Question records (analysis corpus) | **7,151**                                                                                                                                 |
| Unique questions (LLM-classified)  | **6,117**                                                                                                                                 |
| Topic rankers / question rankings  | 91 / 760                                                                                                                                  |
| Personas                           | Guests, Occupants, Students, Health & Safety Officers, Sustainability & Energy teams, Building Owners, IT/Data Science, Facility Managers |

Dataset covers 96 participants across 8 standardized personas (Students, Facility Managers, Sustainability & Energy Teams, Building Owners, IT/Data Science, Health & Safety Officers, Occupants, Guests).

---

## Where to put this folder in the OntoSage repo

Place it at **`paper/Survey analysis and results/`** in the OntoSage project root:

```
OntoSage/
├── paper/
│   └── Survey analysis and results/   ← THIS FOLDER
├── orchestrator/ ...                  ← the system this corpus specified
├── tasks/                             ← L_architecture_coverage.py writes its crosswalk here
└── ...
```

This placement matters: scripts resolve paths relative to their own location, and `scripts/L_architecture_coverage.py` writes to `<repo-root>/tasks/` via `REPO_ROOT = SURVEY_ROOT.parent.parent` — i.e. two levels above this folder. At `paper/Survey analysis and results/` that resolves to the OntoSage root, exactly as intended. Reference this README from the OntoSage top-level `README.md` (e.g. under a "Research / provenance" heading).

---

## How to reproduce everything

```bash
# from anywhere — every script resolves its own paths
cd "paper/Survey analysis and results"

# 1. deterministic pipeline (free, no API) — regenerates all tables + figures
python scripts/A_data_preparation.py        # PIDs, demographics, A2/A3 + persona figure
python scripts/B_corpus_classification.py    # taxonomy classification -> corpus/classified_corpus.csv
python scripts/B4_corpus_statistics.py
python scripts/C_stage_comparison.py
python scripts/D_persona_analysis.py
python scripts/E_topic_priorities.py
python scripts/F_question_preferences.py
python scripts/G_framework_synthesis.py
python scripts/H_evaluation_analysis.py      # reads outputs/survey_evaluation_results.csv
python scripts/I_borda_vs_analytical_demand.py

# 2. LLM complexity master table (needs OPENAI_API_KEY; resumable; only classifies NEW questions)
python scripts/J_complexity_master_table.py --provider openai --model gpt-5.5 --dedup --temperature 1
python scripts/K_master_table_analysis.py    # -> outputs/master table analysis/*
python scripts/L_architecture_coverage.py    # -> <repo-root>/tasks/architecture_coverage_*.csv

# 3. reports
python outputs/stakeholder_participation.py  # persona participation table + figure
python scripts/_md_to_pdf.py "outputs/SURVEY_ANALYSIS_REPORT.md"   # regenerate a report PDF
```

Notes: `J` requires `--temperature 1` for gpt-5.5 (it rejects `0`). Use `--turns 1` to smoke-test one LLM call first. `clean_duplicate_questions.py` regenerates `inputs/questions_by_user_unique.csv` after editing the corpus.

---

## File map

### Start-here documents (folder root)

| File                      | What it is                                                          |
| ------------------------- | ------------------------------------------------------------------- |
| `README.md`               | This index.                                                         |
| `ANALYSIS_METHODOLOGY.md` | The journal-grade analysis plan (RQs, phases, statistical methods). |
| `SURVEY_PROTOCOL.md`      | Complete instrument protocol and data artifact specification.       |

### `inputs/` — the raw survey data (source of truth)

| File                                             | What it is                                                                                                            |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `questions_by_user.csv`                          | **Canonical corpus.** `Username, Personas, QuestionNumber, Stage, Timestamp, Question`. Everything derives from this. |
| `questions_by_user_unique.csv`                   | Deduplicated copy (input to the LLM classifier). Created by `clean_duplicate_questions.py`.                       |
| `questions_only.csv`                             | Question text only.                                                                                                   |
| `topic_rankings.csv` / `.json`                   | Stage-5: each participant's ranking of the 20 building domains.                                                       |
| `question_rankings.csv` / `.json`                | Stage-5: within-topic ranking of the four depth levels (L1–L4).                                                       |
| `topics_reference.csv`                           | The 20-topic catalogue (Topic_ID → Label).                                                                            |
| `questions_reference.csv`                        | The 4 depth-level question variants per topic.                                                                        |
| `questions_by_user_unique_duplicates_report.csv` | What the deduplicator removed.                                                                                        |

### `taxonomy/` — the coding scheme (Phase B)

`taxonomy_v1.md` (the six-tuple taxonomy), `coding_guide.md`, `sample_200.csv` (open-coding sample), `irr_samples.csv` (300-question inter-rater-reliability sample, κ targets set — _reconciliation not yet done; see todos_).

### `scripts/` — the analysis pipeline (A→L) + tooling

| Script                                    | Phase | Produces                                                                           |
| ----------------------------------------- | ----- | ---------------------------------------------------------------------------------- |
| `A_data_preparation.py`                   | A     | PIDs, `A2_demographics_table`, `A3_user_summary`, persona-distribution figure      |
| `B_corpus_classification.py`              | B     | `corpus/classified_corpus.csv` (deterministic lexicon classifier — no API)         |
| `B4_corpus_statistics.py`                 | B     | corpus stat tables + domain/intent/complexity figures                              |
| `C_stage_comparison.py`                   | C     | stage stats, Kruskal/Dunn tests, novelty, TF-IDF                                   |
| `D_persona_analysis.py`                   | D     | persona × domain chi-square, concordance, personas, heatmap                        |
| `E_topic_priorities.py`                   | E     | Borda priorities, Kendall's W, topic clusters                                      |
| `F_question_preferences.py`               | F     | depth-level preferences overall + per persona                                      |
| `G_framework_synthesis.py`                | G     | capability matrix, classification framework, gap analysis                          |
| `H_evaluation_analysis.py`                | H     | system-replay outcome analysis (reads `survey_evaluation_results.csv`)             |
| `I_borda_vs_analytical_demand.py`         | I     | priority-vs-demand crosswalk                                                       |
| `J_complexity_master_table.py`            | J     | **LLM** two-axis complexity master table (gpt-5.5; resumable)                      |
| `J_complexity_standalone.py`              | J     | portable copy of J (⚠ contains a hardcoded API key — rotate)                       |
| `K_master_table_analysis.py`              | K     | iceberg analysis, capability-gap taxonomy, hardest-question tables                 |
| `L_architecture_coverage.py`              | L     | maps corpus intents to OntoSage architecture → `<repo-root>/tasks/`                |
| `clean_duplicate_questions.py`            | —     | regenerate the unique corpus                                                       |
| `_md_to_pdf.py`                           | —     | Markdown → PDF (pip-only, xhtml2pdf) for the reports                               |
| `smart_building_classification_prompt.md` | —     | the frozen LLM rubric spec behind J                                                |

### `corpus/` — the deliverable corpus

`classified_corpus.csv` (every question with its six-tuple taxonomy labels), `corpus_summary_stats.md` (auto-updated key numbers).

### `outputs/` — generated results

- **Reports:** `SURVEY_ANALYSIS_REPORT.md/.pdf`, `SURVEY_TO_SYSTEM_TRACEABILITY.md/.pdf`.
- `tables/` — 40+ CSV/MD tables (A2–I1), the paper's quantitative backbone, incl. `complexity_master_table.csv` and the `A4_stakeholder_participation*` persona-balance tables.
- `figures/` — 25 PNG/PDF figures (A2–I1), persona-named.
- `master table analysis/` — `MASTER_ANALYSIS_REPORT.md/.pdf`, `01_summary_statistics.json`, `00_data_quality_report.md`, `F1–F6` figures, `T1–T7` tables (hardest questions, icebergs, capability gaps, per-persona difficulty).
- `intermediate/` — `username_to_pid.csv`, `baseline_metrics_*.json` (pre-refresh snapshot — keep for provenance).
- `stakeholder_participation.py` — standalone persona-balance analysis.
- `survey_evaluation_results.csv` — the system-replay outcomes consumed by Phase H.

---

## How it maps to the OntoSage system

The mapping is documented in full in [`outputs/SURVEY_TO_SYSTEM_TRACEABILITY.md`](outputs/SURVEY_TO_SYSTEM_TRACEABILITY.md) — every finding `SFn` → design requirement → OntoSage component/file. Headlines:

- **SF1/SF15** (Energy/Safety/Air-Quality lead) → dense Brick/BACnet ontology for those domains.
- **SF2/SF3** (91% status+capability, 92% informational) → fast SPARQL status path + Qdrant capability KB + LLM fast-path.
- **SF4/SF23** (3.5% multi-step, mostly diagnostic) → LangGraph orchestrator + planner.
- **SF5** (20.5% off-ontology) → capability KB + graceful boundary path.
- **SF12/SF14/SF21** (persona predicts domain, V=0.28; depth is persona-specific) → blended **persona registry** with `default_complexity` priors.
- **Master table / K** → the engineering backlog: 74% of questions `requires_extension`, concentrated in ~8 data gaps (occupancy, BMS write-back, energy metering, …) — the data-onboarding roadmap.

---

## Forward plan & todos (from here)

### A. Integration into OntoSage (do at move time)

- [ ] Move this folder to `paper/Survey analysis and results/` in the OntoSage repo.
- [ ] Add a "Research / provenance" link to this README from OntoSage's top-level `README.md`.
- [ ] Re-run `python scripts/L_architecture_coverage.py` **from inside the OntoSage repo** so the architecture crosswalk lands in the real `OntoSage/tasks/` and reflects the current intent registry.
- [ ] Reconcile `scripts/L_architecture_coverage.py`'s intent list against the live `orchestrator/intents/intent_definitions.yaml` (it should map to the 26 deployed intents).

### B. Data integrity / housekeeping

- [ ] **Rotate the OpenAI API key** hardcoded in `scripts/J_complexity_standalone.py` (move all keys to a `.env` read by `J_complexity_master_table.py`). **Do this before pushing to any shared/remote repo.**
- [ ] Remove regenerable cruft before/after the move: `**/__pycache__/`, `llm calls/` (stale duplicate of J + master table), `llm calls (2).zip`, `outputs/master table analysis.zip`. (Archived copies only — none are inputs.)
- [ ] Delete the timestamped backup folder `../Survey analysis and results_BACKUP_*` once you are satisfied with the refresh.

### C. Methodological completion (publication-grade)

- [ ] **Complete the inter-rater reliability (B3).** The 300-question sample (`taxonomy/irr_samples.csv`) and κ≥0.70 targets are set; run a second coder (or a second LLM via `J --provider anthropic`) and report Cohen's κ per dimension in `outputs/tables/B3_irr_report.md`.
- [ ] **Optional dual-model check on the complexity master table:** re-classify a ~150-row sample with Anthropic Claude and report agreement, to evidence the gpt-5.5 grading is not model-specific.
- [ ] **Phase H expansion:** the deployment evaluation logs 5,865 replay questions in `survey_evaluation_results.csv`; to expand replay coverage across all 7,151 corpus questions, execute additional query runs through the live OntoSage deployment and append to `survey_evaluation_results.csv`, then re-run `H_*`.

### D. Research extension (the novel contribution)

- [ ] **Concept-layer ontology extending Brick** — mine the 6,117 questions for the human-vocabulary → Brick-class → analytic-recipe mapping (e.g. "stuffy" → `brick:CO2_Level_Sensor` + threshold recipe). This is authored once and inherited by every Brick-conformant building. See `MASTER_ANALYSIS_REPORT.md` §6.
- [ ] Use `T5_new_capability_gaps.csv` to drive the data-onboarding roadmap (Phases 1–6 in the master report): input enrichment → connect floors 0–4 → generic feed adapter → sensor expansion → ECA rule engine → guarded BMS write-back.
