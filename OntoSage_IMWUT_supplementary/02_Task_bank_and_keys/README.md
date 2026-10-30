# Task bank and keys

Supports §5.4 (Tasks; Keys) and Appendix G.

The task bank holds the twelve study forms, three in each of four situations that differ in what the building's data hold: the whole answer (S1), part of it or only a related quantity (S2), nothing that answers it (S3), or two facts to combine (S4). It was frozen on 14 October 2026, before the first session on 19 October 2026.

## Files

| File | What it holds |
|---|---|
| `task_bank.csv` | The 12 study forms, S1-1 to S4-3, one row each, with the values of the frozen bank. |
| `task_keys.json` | Each form's key as the script computed it from the stores: the answer, and what it rests on (for readings: the number of readings, minimum, maximum, mean, first and last time in UTC, the timeseries identifier and the store; for records: the record and its source). |

## Columns of `task_bank.csv`

| Column | Meaning |
|---|---|
| `form` | The form's code, S1-1 to S4-3. |
| `situation` | S1, S2, S3 or S4, as above. |
| `goal_card` | The goal shown while the participant asked OntoSage+ (§5.4). |
| `decision_question` | The question on the decision page. |
| `option_a` … `option_f` | The options on the decision page, in the order shown. Forms with four or five options leave the last columns empty. |
| `warranted_options` | The options the data support (the correct decisions). In S3, both "not recorded" and "I could not find out" are correct; on every other form, "I could not find out" is wrong. |
| `failure_per_option` | What choosing each other option would mean, for example "proxy substitution" or "under-reliance". |
| `key_answer` | The answer the data support. |
| `provenance` | What the key rests on, as the bank records it (Appendix G, third column). |
| `eligible_n` | How many candidate instances in the stores met the form's rule; the instance was drawn from these. |
| `params` | The instance: room or floor, date, time window and threshold, as JSON. |
| `canonical_question` | The form's question in the researchers' wording. These twelve questions form one of the two repeatability sets of §7. |
| `kind_of_data` | Appendix G's last column, assigned from `provenance` by a fixed rule: real readings, generated series, constructed record, deliberate absence. |

## How the keys were derived

1. A script drew each form's instance from the building's stores with the project's seed (20261009), keeping only candidates that met the form's rule, and computed its key from the graph and time-series stores (`task_keys.json`).
2. Before the freeze, the first author re-derived every key by hand, query by query, against the live stores and confirmed all twelve. At that stage two forms were re-drawn because their first draws did not fit their situation: one had a definite answer where a partial one was intended; in the other, the people count changed during the window (§5.4).
3. The bank was frozen on 14 October 2026 and its SHA-256 recorded. At start, the study form compared the bank with that hash and refused to start if they differed (`07_Study_materials`).

Every form names a fixed date or asks about a record, so no key depends on the time of a session. Times in `task_keys.json` are in UTC; the goal cards use the building's local time.

## What differs from the frozen file

- The frozen bank also holds four development forms (S1-D to S4-D), used only to test Assistant B before the study (§5.3). They are left out, as are two bookkeeping columns (`use`, `lineage`).
- `kind_of_data` is added from Appendix G.
- Values are otherwise unchanged. Nothing in these two files needed anonymising.
