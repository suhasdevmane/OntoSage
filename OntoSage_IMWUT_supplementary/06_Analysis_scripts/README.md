# Analysis scripts

The scripts that produce the article's numbers, tables and figures. No number in the article is typed by hand: each comes from one of three generated files of values, which the article's source reads as macros.

| Values | Macro | Written by | File here |
|---|---|---|---|
| Study (§5–§8, Appendices D–G) | `\sv{}` | `post_development_study/run_pipeline.py`, last step `make_number_macros.py`; extra study values by `article_tables/make_draft_study_tables.py` | `values_printed_in_the_article/numbers.tex`, `numbers_extra.tex` |
| Survey (§3, Appendices A–C, H) | `\pv{}` | `pre_development_survey/make_phase1_macros.py` | `values_printed_in_the_article/numbers_phase1.tex` |
| System as frozen (§4) | `\fv{}` | `system/freeze_facts.py` | `values_printed_in_the_article/freeze_facts.tex` |

Each line of these files gives one value under its key.

## Folders

| Folder | What it holds |
|---|---|
| `values_printed_in_the_article/` | The four files of values, exactly as the article's source reads them. |
| `post_development_study/` | The study's analysis scripts (Parts A–C): `run_pipeline.py` runs them in order. `figures/` draws the study figures; `author_check/` turns the first author's reviewed proposals into the label files. `results/` holds the analyses' outputs: `results/results_numbers.csv` lists every study value with the script and input files it comes from, and `results/rq3/lme4_*.txt` is the two mixed models' R output. `e6_run.py`, `e6_rerun_pf.py` and `e6_aminus.py` ran the offline comparison of §5.3; `make_e6_inputs.py` drew its question sets. |
| `pre_development_survey/` | The survey's analysis scripts (`scripts/`, run in the order of their letters), the classifier's prompt, `make_phase1_macros.py`, and two drivers: `run_repro.py` re-ran the deterministic scripts from the survey's inputs, and `run_contrib.py` re-ran the ranking analyses over contributors only, as the article reports them. |
| `system/` | `freeze_facts.py` reads the counts and settings the article prints from the tagged code (`git show v3.0-study:<path>`) and the freeze record. `recount_frozen_graph.py` re-counted the building's graph as frozen for the study, in a separate GraphDB, with `live_building_facts.py`. `checks.csv` and `lanes.csv` tie each row of §4's tables to lines of the tagged code, which `freeze_facts.py` checks. `freeze_facts.csv` gives every system value with its source; `building-characteristics.csv` holds the counts from the frozen graph. |
| `article_tables/` | `make_draft_study_tables.py`, which writes the agreement tables, the situations table and Appendices D, E and G's tables from the study results and the task bank. |

## Environment

- Python 3.10. `requirements.txt` pins the versions of the authors' environment.
- The two mixed models (`rq3_mixed_model.R`, `rq3_mixed_model_sensitivity.R`) need R 4.3 or later with `lme4` and `emmeans`. They were run apart from the pipeline; their output is in `results/rq3/lme4_*.txt`, and nothing else needs R.
- Scripts that call a language model need an API key, which is not included: the survey's automated classifier (`B_corpus_classification.py`, with `smart_building_classification_prompt.md`), the second automated classifier used for agreement (`B3_irr_llm_coder.py`, `gpt-4o`) and the difficulty ratings of Appendix B.7 (`J_complexity_*.py`). They are here to show how those labels and ratings were made; a re-run would not return exactly the same labels.

## Seeds

- `20261009` is the project's seed (`study_paths.SEED`): the Part A sample of 400 questions and the 90 corpus questions mixed with participants' own (`make_partA_samples.py`), the second coder's samples (`draw_second_coder_samples.py`, `draw_double_coding_sample.py`), the shuffling of the blind sheets (`make_blind_sheet.py`), the order in which the two systems answered each question (`e6_run.py`), and the instances of the task bank (`02_Task_bank_and_keys`).
- The offline question sets are drawn with string seeds built on it, for example `random.Random("20261009:T-LIVE")` (`make_e6_inputs.py`).
- Bootstrap intervals use 2,000 resamples (§5.6).

## Re-running

The scripts are the ones that produced the article's outputs. They expect the authors' folder layout, which `post_development_study/study_paths.py` sets out, and the original names of the data files:

| Name the scripts read | File in `08_Data` |
|---|---|
| `G_Study_Data/deidentified_v1/{participants,decisions,own_questions,turn_checks,task_keys}.csv`, `turns.jsonl` | `post_development_study/data/` (same names) |
| `G_Study_Data/labels/answer_labels_agreed.csv` | `post_development_study/labels/live_answer_labels.csv` |
| `G_Study_Data/labels/agreement/agreed_draft.csv` | `post_development_study/labels/live_answer_labels_both_coders.csv` |
| `G_Study_Data/labels/rq2/rq2_labels_comparison.csv` | `post_development_study/labels/offline_answer_labels.csv` |
| `G_Study_Data/labels/agreement_comparison/agreed_draft.csv` | `post_development_study/labels/offline_answer_labels_both_coders.csv` |
| `G_Study_Data/labels/qual/qual_codes_agreed.csv` | `post_development_study/labels/reason_and_comment_codes.csv` |
| `G_Study_Data/labels/qual/agreement/agreed_draft.csv` | `post_development_study/labels/reason_and_comment_codes_both_coders.csv` |
| `G_Study_Data/labels/rq1/fresh_vs_corpus_agreed.csv` | `post_development_study/labels/own_question_codes.csv` |
| `G_Study_Data/labels/rq1/agreement/agreed_draft.csv` | `post_development_study/labels/own_question_codes_both_coders.csv` |
| `G_Study_Data/e6_offline_runs/{runs,inputs}/*.jsonl` | `post_development_study/offline_runs/{runs,inputs}/` (same names) |
| `C_Task_Bank_and_Keys/task_bank.csv` | `02_Task_bank_and_keys/task_bank.csv` (study forms only) |

Some inputs of the study pipeline are not among the released data: the labels of the repeated runs, the second coder's returned sheets, and the files the review tool and the samplers wrote. Their results are in `results/`. One summary step counts participants' roles and age bands, whose columns are not released; its output, totals only, is `results/rq3/table1_sample.csv`. The survey scripts read the survey's exported files, which hold the platform's usernames and are not released; `08_Data/pre_development_survey/` holds the same data with contributor codes. `system/freeze_facts.py` reads the code at the frozen commit, which the anonymised copy of the repository shows, and the authors' freeze record, which is not released; `system/recount_frozen_graph.py` needs the graph exported at the freeze, which is not released either. Their outputs are `values_printed_in_the_article/freeze_facts.tex`, `system/freeze_facts.csv` and `system/building-characteristics.csv`. We have not re-run the scripts from this folder's layout.

Not included: the data-preparation scripts whose outputs are fixed inputs here, or which read the identifiable study data, account files or the second coder's pack (`build_study_dataset.py`, `save_raw_study_data.py`, `backup_analysis.py`, `build_check_records.py`, `make_second_coder_pack.py`, `import_second_coder_return.py`, `make_assignment_schedule.py`), and `pii_audit_outputs.py`, the check of the outputs against the identifiable data.

## Edits for anonymity

Comments and strings that named an author now say "the first author" or "the third author"; folder names in paths that held the first author's name now read `[anonymised]`; and a Windows path in a usage comment now reads `<repository>`. In `pre_development_survey/scripts/J_complexity_*.py`, the prompt's description of the building names it "Building A" and the institution "[university]". Where code matched the building's name or the interface's name, the match now uses a placeholder:

- `post_development_study/phrasing_analysis.py`: the building's name and two misspellings that participants typed, in one pattern, became `BUILDING_NAME`, `BUILDING_NAME_MISSPELT_1` and `BUILDING_NAME_MISSPELT_2`. In the anonymised data, the name reads "Building A", which the same pattern's alternative `building` still matches.
- `pre_development_survey/make_phase1_macros.py`: one of the name markers for the research team's test accounts, the first author's first name, became `[first author's first name]`. The released survey data hold contributors only, so the rule changes nothing there.
- `post_development_study/e6_run.py` and `e6_rerun_pf.py`: no change; the account names they use (`offline@study.example.com`) are placeholders.

`post_development_study/run_pipeline.py` omits the authors' last step, a check of the outputs against the identifiable data, which is not included. The classifier's prompt is taken from the copy published in the repository, with the username in one example written as a contributor code (`C096`); the authors' working copy held a contributor's username there. The comments in the code are as written at the time: "tracker", "plan" and "notes" refer to the authors' project records, and "pre-registered" means the study plan approved before the first session, which was not registered publicly (§5).
