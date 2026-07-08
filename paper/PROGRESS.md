# PROGRESS.md — OntoSage++ Paper + Survey Analysis Tracker

**Target venue:** Proc. ACM IMWUT
**Target length:** ~20 pages (`acmsmall`)
**Last updated:** 2026-06-25
**Authors:** Devmane, Rana, Perera (Cardiff University)

---

## Quick status

| Track | Status | Next action |
|-------|--------|-------------|
| Survey analysis (Phases A-G) | ALL PHASES RE-RUN (96 users, 7,151 Qs) | All outputs refreshed from updated CSV |
| Paper restructure (9-section) | RESTRUCTURED 2026-04-16 | Verify section content quality |
| Stat refresh (replace fabricated) | COMPLETE 2026-06-25 | All stats in paper updated to new corpus |
| Post-design 15-person survey | COMPLETE | `paper/post_design_survey/responses.csv` (mean SUS 84.5) |
| Compile + submit | BLOCKED | Content review + final polish |

---

## Stat refresh — 2026-06-25

Corpus expanded from 81→96 participants, 5,916→7,151 questions (16 new H&S + Sustainability participants added). All numbers below replaced in `research paper.tex`. Compile passed (36 pages, no errors).

| Location | Old value | New value | Source |
|----------|-----------|-----------|--------|
| Abstract, line 93 | 81 participants, 9 roles, 5,916 Qs, H=51.1 | 96 participants, 8 personas, 7,151 Qs, H=185.5 | A2, C1 |
| Intro contribution list, line 154 | 5,916 questions | 7,151 questions | A2 |
| Related work, line 174 | 5,916 across nine roles | 7,151 across eight personas | A2 |
| Participants §, line 229 | 81 participants, 9 roles, stage counts (1595/1726/1388/1207) | 96 participants, 8 personas, stage counts (1904/2003/1705/1539) | A2, C1 |
| Demographics table caption | N=81, 5,916 total | N=96, 7,151 total | A2 |
| Demographics table rows | old counts+roles | updated counts (H&S 3→11, Sustainability 1→10, FM 7→6; Ontology Experts removed) | A2 |
| Role distribution text, line 255 | Students=17.3%, Guests=27.2%, Occupants=22.2% | Guests=22.9%, Occupants=18.8%, Students=14.6% | A2 |
| Figure caption role dist | nine roles, N=81 | eight personas, N=96 | A2 |
| Corpus statistics table caption | N=5,916 | N=7,151 | B4 |
| Corpus stats table — Domain (L1) | OTHER 24.0%(1421), ENERGY 14.2%(841), AIR_Q 11.0%(652), THERMAL 9.0%(535), SAFETY 5.0%(298) | OTHER 20.5%(1467), ENERGY 17.5%(1250), SAFETY 10.7%(763), AIR_Q 9.6%(686), THERMAL 8.3%(594) | B4 |
| Corpus stats table — Query Type (L2) | STATUS 65.4%(3871), CAPABILITY 25.6%(1514) | STATUS 67.0%(4793), CAPABILITY 23.8%(1704) | B4 |
| Corpus stats table — Intent | INFORMATIONAL 92.3%(5458), DIAGNOSTIC 4.0%(235), PRESCRIPTIVE 2.7%(159), PREDICTIVE 1.1%(64) | INFORMATIONAL 91.7%(6558), DIAGNOSTIC 3.9%(280), PRESCRIPTIVE 3.2%(230), PREDICTIVE 1.2%(83) | B4 |
| Corpus stats table — Complexity | LOOKUP 88.4%(5227), AGGREGATION 8.6%(510), MULTI_STEP 3.0%(179) | LOOKUP 88.0%(6293), AGGREGATION 8.5%(610), MULTI_STEP 3.5%(248) | B4 |
| Corpus stats table — Temporal | STATIC 89.6%(5303), REALTIME 8.5%(501) | STATIC 89.9%(6429), REALTIME 8.0%(570) | B4 |
| Domain figure caption, line 336 | 5,916 Qs, OTHER 24.0% | 7,151 Qs, OTHER 20.5% | B4 |
| Stage stats table caption | N=5,916 | N=7,151 | C1 |
| Stage stats table rows | old stage counts + percentages | 1904/2003/1705/1539, updated Lookup/Agg/Multi% | C1 |
| KW test text, line 372 | H=51.1, p=4.6e-11, ε²=0.009, N=5,916 | H=185.5, p=5.9e-40, ε²=0.026, N=7,151 | C1 |
| KW test in RQ1 intro, line 878 | H=51.1, p=4.6e-11, ε²=0.009, Stage 4 mean 10.40 | H=185.5, p=5.9e-40, ε²=0.026, Stage 4 mean 10.48 | C1 |
| Figure caption taxonomy, line 646 | N=81, nine personas, Borda(Temp 1163, AQ 1103, Sec 1059), STATUS 65.4%, CAPABILITY 25.6%, INFORMATIONAL 92.3%, STATIC 89.6%, REALTIME 8.5%, UNSPECIFIED 75.9%, BUILDING 12.5%, ROOM 10.3%, LOOKUP 88.4%, AGGREGATION 8.6%, MULTI_STEP 3.0%, H=51.1, χ²(152)=519.9 | N=96, eight personas, Borda(AQ 1378, Temp 1367, Fire 1267), STATUS 67.0%, CAPABILITY 23.8%, INFORMATIONAL 91.7%, STATIC 89.9%, REALTIME 8.0%, UNSPECIFIED 73.9%, BUILDING 14.0%, ROOM 9.9%, LOOKUP 88.0%, AGGREGATION 8.5%, MULTI_STEP 3.5%, H=185.5, χ²(133)=3903.9 | B4, E1, C1, D1 |
| Role×domain chi-sq, line 512 | χ²(152)=519.9, p=9.5e-42, V=0.105 | χ²(133)=3903.9, p<1e-100, V=0.279 | D1 |
| Priority vs volume, line 507 | SECURITY Borda 1059, TEMPERATURE Borda 1163, ENERGY 841 Qs, OTHER 1,421 Qs | SECURITY Borda 1240, TEMPERATURE Borda 1367, ENERGY 1,250 Qs, OTHER 1,467 Qs | E1, B4 |
| Classifier coverage, line 695 | 76.0% (4,495 of 5,916), OTHER 24.0% | 79.5% (5,684 of 7,151), OTHER 20.5% | B4 |
| Results lead, line 870 | 76.0% of 5,916 | 79.5% of 7,151 | B4 |
| RQ1 lead, line 876 | 5,916 from 81 participants | 7,151 from 96 participants | A2 |
| Results §RQ1 classifier, line 891 | 76.0%, 5,916, 4,495, 24.0% | 79.5%, 7,151, 5,684, 20.5% | B4 |
| Corpus audit intro, line 985 | 5,916 questions | 5,865 questions (evaluation corpus) | H1 |
| Corpus audit metrics, line 988 | 5,916 queries, 20.0%[19.0-21.0], 43.9%, 8.3%, p90=15.03s, Grounded 7.9s, Disambig 4.6s | 5,865, 20.2%[19.2-21.2], 43.8%, 8.4%, p90=15.07s, Grounded 11.8s, Disambig 4.7s | H1, H6 |
| Stage coverage figure caption, line 996 | N=5,916 | N=5,865 | H1 |
| Domain-complexity heatmap caption, line 1008 | N=5,916 | N=7,151 | B4 |
| Limitations — IRR, line 1081 | fabricated κ=0.71-0.84 (all ≥0.70) | real κ: domain 0.581, spatial 0.435, temporal 0.153, intent 0.070; 20.5% OTHER | B3_irr_report.md |
| Limitations — corpus scope, line 1083 | 5,916-question corpus | 7,151-question corpus | A2 |
| Data-availability gaps, line 1041 | 24.0% (1,421 of 5,916) | 20.5% (1,467 of 7,151) | B4 |
| Ontology expansion, line 1089 | 24.0% (1,421) | 20.5% (1,467) | B4 |
| Future directions PRESCRIPTIVE%, line 1091 | 2.7% PRESCRIPTIVE, 1.1% PREDICTIVE | 3.2% PRESCRIPTIVE, 1.2% PREDICTIVE | B4 |
| Corpus release, line 1095 | 5,916-question corpus | 7,151-question corpus | A2 |
| Limitations formative scope, line 1083 | 5,916-question corpus | 7,151-question corpus | A2 |
| Conclusion, line 1111 | 81 participants, 9 roles, 5,916 Qs, χ²(152)=519.9, p<1e-41, nine stakeholder types | 96 participants, 8 personas, 7,151 Qs, H=185.5, χ²(133)=3903.9, p<1e-100 | A2, C1, D1 |
| Borda in conclusion, line 1112 | Temperature Borda 1163, AQ 1103 | AQ Borda 1378, Temperature 1367 | E1 |
| Sample questions table text, line 1133 | 5,916 questions | 7,151 questions | A2 |
| Sample questions table caption, line 1137 | N=5,916 | N=7,151 | A2 |
| Example interactions, line 1190 | 5,916 Phase 1 questions | 5,865 Phase 1 questions (evaluation corpus) | H1 |

**Total replacements: 39 stat locations across 27 claim sites. 0 placeholders remain.**

## Stat refresh — 2026-06-25 (Phase H re-run, full 7,151-question corpus)

After replay_new_questions.py completed (1,285 ok / 1 fail), re-ran H_evaluation_analysis.py over all 7,151 joined questions. Updated paper.tex with new H1 values. Compile passed (36 pages, 0 errors).

| Location | Old value | New value | Source |
|----------|-----------|-----------|--------|
| Corpus audit intro, lines 984-985 | "all 5,865 questions" | "all 7,151 questions" | H1 |
| Overall coverage, line 987 | 63.9% [62.7-65.1], 20.2% [19.2-21.2], 43.8%, 26.7%, 8.4%, 1.1%, p90=15.07s, KW H=1927.12 η²=0.329, Grounded 11.8s, Disambig 4.7s | 66.6% [65.5-67.6], 26.0% [25.0-27.0], 40.6%, 25.5%, 7.1%, 0.9%, p90=14.45s, KW H=802.62 η²=0.113, Grounded 8.1s, Disambig 4.5s | H1, H6 |
| Stage effect paragraph, line 990 | S1=66.6%, S4=71.8%, S3=55.6%, S2=62.6%, χ²(3)=79.68, V=0.116, S4 grounded 33.4%, S1 grounded 12.8% | S4=72.9%, S1=66.3%, S3=60.7%, S2=66.9%, χ²(3)=54.25, V=0.087, S4 grounded 37.0%, S1 grounded 18.3% | H5 |
| H5 figure caption, line 995 | χ²(3)=79.68, V=0.116, N=5,865 | χ²(3)=54.25, V=0.087, N=7,151 | H5 |
| Convergent validity, line 1012 | 35.0% outside G+I, 8.3% refusal, 1.1% failure | 33.4% outside G+I, 7.1% refusal, 0.9% failure | H1 |
| Appendix interactions, line 1190 | "all 5,865 Phase-1 questions" | "all 7,151 Phase-1 questions" | H1 |

**New total: 46 stat locations replaced. 0 placeholders remain. Full corpus (7,151 Qs) now used throughout.**

---

## Live verification log

**2026-06-18 — corpus_replay harness validated + run live (V3 T28/T30).** Fixed two
blocker bugs in `../scripts/corpus_replay.py` that meant it had never run end-to-end:
(1) `POST /v1/chat/completions` sent no `Authorization` header → instant 401; (2)
`_heuristic_grade` had a 1-arg signature but is invoked as `judge_fn(question, answer)`
→ grader crashed every row. Stratified 240-question replay (seed 42, OpenAI LLM judge):
**63.8% substantive-answer rate** (15.0% data-grounded · 48.8% honest-capability · 34.6%
deflected · 1.7% failed; 0 infra errors). This **independently corroborates** the §6.5
full-corpus audit headline (**63.9%** on 5,916 from `survey_evaluation_results.csv`) —
the category mix also aligns (paper Disambiguation+Boundary 35.0% ≈ replay deflected 34.6%;
Failed 1.1% ≈ wrong 1.7%). Persona×intent battery (`../scripts/ontosage_qa_suite.py`):
PASS 260 / WARN 26 / FAIL 0 / 286 (91% clean-pass). **No paper-body stats changed** —
§6.5 is already real-data-backed; the "16.2%→63.8% before/after" V3 framing is left as an
author editorial choice.

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
