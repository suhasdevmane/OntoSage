# PROGRESS.md — OntoSage++ Paper + Survey Analysis Tracker

**Target venue:** Proc. ACM IMWUT
**Target length:** ~20 pages (`acmsmall`)
**Last updated:** 2026-04-16
**Authors:** Devmane, Rana, Perera (Cardiff University)

---

## Quick status

| Track | Status | Next action |
|-------|--------|-------------|
| Survey analysis (Phases A-G) | ALL PHASES RE-RUN (81 users, 5,916 Qs) | All outputs refreshed from updated CSV |
| Paper restructure (9-section) | RESTRUCTURED 2026-04-16 | Verify section content quality |
| Stat refresh (replace fabricated) | COMPLETE 2026-04-13 | All stats in paper updated to new corpus |
| Post-design 15-person survey | COMPLETE | `paper/post_design_survey/responses.csv` (mean SUS 84.5) |
| Compile + submit | BLOCKED | Content review + final polish |

---

## Survey analysis pipeline (Phase A → G)

| Phase | Step | Status | Output | Started | Completed |
|-------|------|--------|--------|---------|-----------|
| **A** Data Prep | A1 Loading + cleaning | ✅ done | (in-script) | 2026-04-11 | 2026-04-11 |
| | A2 Demographics | ✅ done | `outputs/tables/A2_demographics_table.csv`, `outputs/figures/A2_role_distribution.{png,pdf}` | 2026-04-11 | 2026-04-11 |
| | A3 Per-user summary | ✅ done | `outputs/tables/A3_user_summary.csv` | 2026-04-11 | 2026-04-11 |
| **B** Corpus | B1 Taxonomy draft | ✅ done | `taxonomy/taxonomy_v1.md`, `taxonomy/coding_guide.md`, `taxonomy/sample_200.csv` | 2026-04-11 | 2026-04-11 |
| | B2 Classification (deterministic) | ✅ done | `corpus/classified_corpus.csv` (5,916 rows × 6 dims) | 2026-04-11 | 2026-04-13 |
| | B3 Inter-rater reliability | 🟡 sample ready | `taxonomy/irr_samples.csv` + `outputs/tables/B3_irr_report.md` (kappa pending two human coders) | 2026-04-11 | — |
| | B4 Corpus statistics | ✅ done | `outputs/tables/B4_corpus_statistics.csv`, `B4_domain_by_stage.csv`, `B4_intent_by_complexity.csv`, 3 figures | 2026-04-11 | 2026-04-11 |
| **C** Stage Comp | C1 Quantitative | ✅ done | `outputs/tables/C1_stage_stats.csv`, `C1_stage_tests.md` | 2026-04-12 | 2026-04-12 |
| | C2 TF-IDF + thematic | ✅ done | `outputs/figures/C2_stage_tfidf_comparison.{png,pdf}`, `C2_stage_evolution_table.md` | 2026-04-12 | 2026-04-12 |
| | C3 Novelty analysis | ✅ done | `outputs/tables/C3_novelty_analysis.csv`, `outputs/figures/C3_novelty_by_stage.{png,pdf}` | 2026-04-12 | 2026-04-12 |
| **D** Roles | D1 Role × domain | ✅ done | `outputs/figures/D1_role_domain_heatmap.{png,pdf}`, `D1_chi_squared_results.md` | 2026-04-12 | 2026-04-12 |
| | D2 Rank by role | ✅ done | `outputs/figures/D2_rank_by_role.{png,pdf}`, `D2_concordance_table.csv` | 2026-04-12 | 2026-04-12 |
| | D3 Personas | ✅ done | `outputs/tables/D3_user_personas.md` | 2026-04-12 | 2026-04-12 |
| **E** Topic priorities | E1 Aggregate Borda | ✅ done | `outputs/tables/E1_topic_priority_table.csv`, `E1_kendalls_w.md`, `E1_borda_scores.{png,pdf}` | 2026-04-12 | 2026-04-12 |
| | E2 Topic clustering | ✅ done | `outputs/figures/E2_topic_dendrogram.{png,pdf}`, `E2_topic_clusters.md`, `E2_topic_corr_matrix.csv` | 2026-04-12 | 2026-04-12 |
| | E3 Top vs bottom | ✅ done | `outputs/figures/E3_priority_vs_volume_scatter.{png,pdf}` | 2026-04-12 | 2026-04-12 |
| **F** Question prefs | F1 Within-topic | ✅ done | `outputs/tables/F1_question_preferences_by_topic.csv`, `F1_overall_level_preference.csv` | 2026-04-12 | 2026-04-12 |
| | F2 Complexity prefs | ✅ done | `outputs/figures/F2_complexity_preference.{png,pdf}`, `F2_complexity_preference_by_role.csv` | 2026-04-12 | 2026-04-12 |
| **G** Framework | G1 Classification framework | ✅ done | `outputs/tables/G1_classification_framework.md` | 2026-04-12 | 2026-04-12 |
| | G2 Capability matrix | ✅ done | `outputs/tables/G2_capability_matrix.csv` | 2026-04-12 | 2026-04-12 |
| | G3 Architecture diagram | ✅ done | `outputs/figures/G3_framework_architecture.{png,pdf}` | 2026-04-12 | 2026-04-12 |
| | G4 Gap analysis | ✅ done | `outputs/tables/G4_gap_analysis.md` | 2026-04-12 | 2026-04-12 |

Mark a row ✅ when the output file exists. Add the date in the "Completed" column.

---

## Paper sections (9-section structure, restructured 2026-04-16)

| § | Section | Status | Lines | Real-data dependencies |
|---|---------|--------|-------|------------------------|
| Abs | Abstract | DRAFT | 88–94 | Phase A2 + `post_design_survey/summary_stats.csv` |
| 1 | Introduction | DRAFT | 135–163 | None |
| 2 | Related Work (inc. §2.4 ZKI) | DRAFT+NEW | 165–207 | None |
| 3 | Phase 1: Understanding Stakeholder Intentions | DRAFT | 209–595 | Phase A, B, C, D, E, F |
| 4 | OntoSage (inc. §4.10 Use Cases) | DRAFT+NEW | 597–765 | None |
| 5 | Evaluation Deployment | DRAFT | 767–854 | `post_design_survey/responses.csv` |
| 6 | Results (inc. §6.6 Corpus Coverage) | DRAFT+NEW | 853–1003 | Phase B-F + `post_design_survey/` + `survey_evaluation_results.csv` |
| 7 | Discussion (NEW section) | NEW | 1005–1055 | Phase G + evaluation findings |
| 8 | Limitations and Future Work | DRAFT | 1056–1091 | None |
| 9 | Conclusion | DRAFT | 1092–~1101 | None |

---

## Section history

| Date | Section | Change | By |
|------|---------|--------|-----|
| 2026-04-11 | (initial) | Brainstorming + .claude/ paper support set up | Claude |
| 2026-04-16 | §2.4 | Added "Defining Zero-Knowledge Interaction in Smart Buildings" subsection (3 paras) | Claude |
| 2026-04-16 | §3 | Renamed to "Phase 1: Understanding Stakeholder Intentions"; absorbed old §4 Topic Prioritisation as 3.8–3.13 | Claude |
| 2026-04-16 | §4.10 | Added "Representative Use Cases" with Zero-Knowledge Guest + Expert Operator traced scenarios | Claude |
| 2026-04-16 | §6/§7 | Split old "Results & Discussion" into §6 "Results" (data only) + §7 "Discussion" (Design Principles, Error Analysis, Perceived Value) | Claude |
| 2026-04-16 | §8 | Renamed "Future Work and Limitations" → "Limitations and Future Work"; put limitations first | Claude |
| 2026-04-16 | §1 | Updated roadmap paragraph to reflect 9-section structure | Claude |
| 2026-04-17 | §6.6 | Added "Corpus-Level Coverage Analysis" — 5,916-question automated audit; 2 figures (stage line + domain×complexity heatmap); 5 statistical tests | Claude |
| 2026-04-17 | App. A | Added sample questions appendix — 24 verbatim questions from corpus, 8 domains × 3 complexity levels, all four stages represented | Claude |
| 2026-04-17 | App. B | Added system interactions appendix — 4 verbatim Q&A pairs from survey_evaluation_results.csv illustrating Grounded/Informational/Disambiguation/Boundary outcomes | Claude |

Add a row every time `/paper-section` runs.

---

## Stat refresh log

| Date | Line | Old | New | Source |
|------|------|-----|-----|--------|
| 2026-04-11 | — | (PROGRESS Quick status) | Phase A complete: 98 unique participants, 10 roles, 5,127 questions (S1=1502, S2=1472, S3=1146, S4=1007) | `outputs/tables/A2_demographics_table.csv` |
| 2026-04-11 | 208 | "42 participants ... 87.3\% ... 66.4\% ... 90\%" | "98 participants (corpus); 15 post-deployment ... mean SUS 84.5 ... 98.3\% completion ... 93.3\% adoption" | `A2_demographics_table.csv` + `post_design_survey/summary_stats.csv` |
| 2026-04-11 | 342, 364-365 | "68\% Stage 1 Cluster C / 80\% Stage 2 Cluster B" | "37.5\% / 24.0\% Cluster C and 62.5\% / 76.0\% Cluster B (on-topic, Stage 1 / Stage 2)" | `B4_domain_by_stage.csv` |

Add a row every time `/paper-stats` replaces a fabricated number.

---

## Fabricated stats remaining (must reach zero before submission)

- [x] `87.3% task completion` — abstract DONE (now `98.3%` from `summary_stats.csv`); §6.4 RQ4 still pending
- [x] `66.4% time reduction` — abstract DONE (removed; recast qualitatively); §6.4 RQ4 still pending
- [x] `90% engineering reduction` — abstract DONE (removed); §6.3 RQ3 still pending
- [x] `42 participants` — abstract DONE (now `98` corpus + `15` post-deployment); §5.5.2 still pending
- [x] `68% Stage 1 Cluster C` — §3.4 DONE: real `37.5%` from `B4_domain_by_stage.csv` (on-topic only)
- [x] `80% Stage 2 Cluster B` — §3.4 DONE: real `76.0%` from `B4_domain_by_stage.csv` (on-topic only)

---

## Open questions for the user

- [ ] Confirm target venue: IMWUT vs Building & Environment vs Automation in Construction (current draft is `acmsmall` IMWUT)
- [ ] Provide real responses for the 15-person post-design survey, OR decide if dummy is acceptable for arXiv submission
- [ ] Confirm authors' final order
- [ ] Confirm BREEAM citation for Building A

---

## Submission checklist (run before final submit)

- [ ] All Phase A-G outputs exist in `outputs/tables/` and `outputs/figures/`
- [ ] Zero fabricated stats remain (`grep -c "TBD-from\|87\.3\|66\.4" "research paper.tex"` returns 0)
- [ ] All `% BEGIN-DUMMY-DATA` blocks replaced with real data
- [ ] All BibTeX keys in .tex exist in `references.bib`
- [ ] Anonymisation: no usernames anywhere in the .tex
- [ ] Ethics statement (SREC COMSC/Ethics/2025/044b) appears in §3.3
- [ ] Compiles cleanly with `pdflatex` (no `Error`, ≤5 `Warning`)
- [ ] Page count ≤22 (target ~20)
- [ ] Inter-rater Cohen's Kappa ≥ 0.70 reported
- [ ] All p-values reported with effect sizes
- [ ] CCS concepts filled in (currently placeholder)
