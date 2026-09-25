# OntoSage — data and materials

Everything the paper *OntoSage: Enabling Zero-Knowledge Conversational AI for Smart Buildings
through Semantic Intent Mapping* refers to, in one place.

Ethics: Cardiff University SREC **COMSC/Ethics/2025/044b**.
Contact: Suhas Devmane, Cardiff University — DevmaneSP1@cardiff.ac.uk

**Participant data is pseudonymised.** Names, one email address and eight worker IDs were
replaced with participant identifiers (P01–P96) throughout — 27,330 replacements in identifier
columns, and a further 9,699 inside composite keys such as `<name>|1|qd892c3dfb8ef`. The
name-to-identifier mapping is **not** included, so the data here cannot be re-identified.

`pii_scan.py` re-checks the whole folder for emails, names in free text, worker IDs, phone
numbers, postcodes and identifying file names. It currently passes. Run it again after adding
anything.

---

## What is in each folder

### 1. `Survey analysis and results/` — the formative study

The 7,151-question corpus from 96 participants, its six-dimensional classification, and every
analysis behind Section 3 of the paper.

| | |
|---|---|
| `SURVEY_INSTRUMENT_AS_ADMINISTERED.md` | the fullest account: every screen, what was asked for, what came back, and how the rules actually behaved |
| `SURVEY_PROTOCOL.md` | the condensed version used to check the paper. **Where the paper and these two disagree, they are right.** |
| `inputs/` | raw exports: questions by participant and stage, topic rankings, within-topic question rankings, and the Stage 5 open responses |
| `corpus/classified_corpus.csv` | all 7,151 questions with domain, query type, intent, temporal scope, spatial scope and complexity |
| `taxonomy/` | the coding frame |
| `scripts/` | every analysis, lettered by phase (A–L), plus `Z_*` scripts added for the paper |
| `outputs/tables/` | one CSV per result. Every number in Section 3 traces to a file here |
| `outputs/figures/` | the figures as published |
| `outputs/survey_evaluation_results.csv` | the corpus replay: all 7,151 questions submitted to the live system, with the outcome class and latency of each |
| `ANALYSIS_METHODOLOGY.md` | how the analysis was specified |

### 2. `Stakeholder question catalogue/` — 37 roles, 2,960 records

One PDF per role, 80 question-to-evidence records each. Every record carries the question, the
sensing it needs, the authoritative non-sensor sources, the analysis, the **answer boundary**
(what the system must not infer, certify or authorise) and the decision it supports.

**This artefact is synthetic.** It records what a role plausibly needs to ask, not what anyone
was observed asking. It was generated from the building's floor plan and room schedule and
corrected by the research team, without the survey corpus as input. It shaped the design and is
excluded from evaluation — no result in the paper is computed from it.

### 3. `Ontology/` — the semantic model

| | |
|---|---|
| `ontosage_schema.ttl` | OCBV, the conversational building vocabulary |
| `ontosage_capabilities.ttl` | amenities and knowledge topics |
| `hbco_core.ttl`, `hbco_mappings.ttl` | the lay-term concept ontology ("stuffy" → CO₂) |
| `measurand_kinds.ttl` | what each class actually measures, used to constrain query scope |
| `record_documents/` | the specification for each register type (permits, rotas, inspections) |
| `mining/` | how the concept terms were derived |

Brick Schema itself is not redistributed here; it is available from the Brick Consortium.

### 4. `System evaluation/Evidence pack - 73 probes/`

73 author-written probes asked of the deployed system at Building A, each answer read by hand
against what the question asked and marked **good** (51), **weak** (21) or **flagged** (1).

`answers.jsonl` holds the questions and full answers; `review.json` holds the verdict and
reasoning for each; `screenshots/` has one capture per question. `INDEX.md` lists them.

These probes measure *depth* — whether a forecast shows its model, whether a ranking states its
coverage, whether a decline is honest. They are not sampled from the corpus and are not a
coverage measure; the corpus replay in folder 1 is.

### 5. `Deployment study (pilot)/`

The instrument, session structure and pilot responses. **The 30-participant study reported in
the paper has not yet been run** — every outcome value in Sections 5 to 7 of the paper is shown
as a red placeholder until it is.

---

## Which evidence supports which claim

| Paper claim | Where to check it |
|---|---|
| 7,151 questions, 96 participants, five stages | `Survey analysis and results/SURVEY_PROTOCOL.md`, `corpus/classified_corpus.csv` |
| The context gap (34.2% → 13.7% off-ontology) | `outputs/tables/Z_domain_by_stage.csv` |
| Topic priorities (Borda) and Kendall's W | `outputs/tables/E1_topic_priority_table.csv`, `E1_kendalls_w.md` |
| Complexity preference L1–L4 | `outputs/tables/F1_overall_level_preference.csv` |
| Classifier reliability (no dimension reaches κ ≥ 0.70) | `outputs/tables/B3_irr_report.md` |
| Stage 5 trust and privacy themes | `outputs/tables/Z_stage5_vision_themes.csv` |
| Corpus coverage (66.6% answered, 7.1% refused) | `outputs/survey_evaluation_results.csv`, `outputs/tables/H*.csv` |
| Answer quality on targeted probes | `System evaluation/Evidence pack - 73 probes/review.json` |
| The five-layer semantic model | `Ontology/` |
| Demand from roles the survey did not sample | `Stakeholder question catalogue/` |

## Two things to read before citing anything here

**The corpus classification is automated, not human-coded.** A deterministic lexicon classifier
labelled all 7,151 questions; a cross-paradigm check against an independent model pass reaches
κ ≥ 0.70 on **no** dimension (domain is strongest at 0.581). Domain-level results carry the
paper's argument and can bear it; the intent, temporal and complexity distributions describe
classifier output rather than validated ground truth.

**The corpus replay measures whether an answer was returned, not whether it was correct.** A
response marked *grounded* retrieved real building data; nothing verifies it was the data the
question asked about.
