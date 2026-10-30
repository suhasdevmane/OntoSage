# Data

The survey's anonymised questions, rankings and answers, and the study's de-identified data with both coders' labels (Data and Materials). These are the files prepared for release with the frozen build, with the further changes for review listed at the end.

## `pre_development_survey/`: the question-writing survey (§3)

Contributors were recruited through Amazon Mechanical Turk. Each has an anonymous code, C001–C096, in order of first participation.

| File | What it holds |
|---|---|
| `questions_all.csv` | Every question submitted: contributor, chosen role profiles, question number, stage (1–4), text. |
| `questions_unique.csv` | The de-duplicated corpus, with the automated classifier's labels (domain, query type, intent, temporal, spatial, complexity). These labels are a language model's, not a person's. |
| `topic_rankings.csv` | Stage 5 rankings of twenty topics, by contributor. |
| `question_rankings.csv` | Stage 5 rankings of the four example questions in each topic, by contributor. |
| `stage5_answers.csv` | Stage 5 free-text answers on scenarios, interaction, trust, success and pain points. |
| `topics_reference.csv`, `questions_reference.csv` | The twenty topics and the eighty example questions that were ranked. |
| `part_a_sample.csv`, `part_a_codes_agreed.csv`, `part_a_agreement.json` | The 400 questions coded with the Part A codebook (§6), their codes, and agreement between the coders. |
| `stage5_codes_by_question.csv` | Counts of the Stage 5 codes (aggregate only). |

## `post_development_study/`: the study (§5, §7, §8)

Participants are identified only by study codes, P01–P30, as in the article. They are unrelated to the survey's codes.

| Folder | What it holds |
|---|---|
| `data/` | `participants.csv` (questionnaire items and scores, counts of activity); `decisions.csv` (each task decision with its key, confidence, reliance, helpfulness and written reason); `turns.jsonl` and `turns.csv` (every question asked, the answer as shown, and what the pipeline recorded); `own_questions.csv`; `turn_checks.csv` (which checks acted on each turn); `task_keys.csv`. |
| `labels/` | The answer labels, live and offline; the codes for written reasons and closing answers; and the codes for participants' own questions. Each comes with a second file holding both coders' labels side by side, and an agreement summary. The labels follow `03_Answer_label_rubric`; the codes, `04_Codebooks`. |
| `offline_runs/` | The offline runs of §5.3: the question sets (`inputs/`) and every answer of OntoSage+, Assistant B and A-minus, including the repeated runs (`runs/`). |

## What was removed or changed before release

Survey:
- platform usernames were replaced by the anonymous contributor codes used in the analysis; the mapping is not released;
- ranking and Stage 5 accounts that submitted no questions are left out, as in the article;
- submission timestamps were removed.

Study:
- each participant's role (`BG1`) and age band (`BG6`) were removed; the article reports their totals;
- the consent timestamp was removed, and every other timestamp was shifted per participant so that each session starts at `2000-01-01T00:00:00+00:00`. Intervals within a session are exact; the session's date and time of day cannot be recovered from these columns;
- dates of the session days were replaced by `[session date]` in questions, answers, coders' notes and evidence quotes. Times of day printed inside OntoSage+'s answers were kept, because the labels judged them;
- the page-event and revision logs are not included (their counts are columns of `participants.csv`);
- e-mail addresses in the data are placeholders (`example.com`, `example.ac.uk`) from the building's records and the study's test accounts, not participants'.

## Further changes for review

- the names, places, domains, addresses and numbers listed in `00_README.md` were replaced in every file, including participants' questions and reasons and OntoSage+'s answers;
- two other people's names that a participant typed (a person whose office they asked about, and a name given as an example in an own question) became `[name]` wherever they appeared: in the questions, in OntoSage+'s answers and log notes, and in the labels;
- the survey's contributor codes were recoded from P01–P96 to C001–C096, in the same order, in the `contributor` column;
- chart file names in answers that carried a session's date and time now read `viz_[removed]`.

## Licence

CC BY 4.0 (`LICENSE.txt`).
