# Corrections to the demo-rehearsal hand labels — 18 September 2026

Two labels were wrong and were changed after checking the answer against the source data. The
changed rows in `demo_rehearsal_2026-09-18_run{1,2}_read.jsonl` keep the old label in
`relabelled_from`. Nothing else was changed.

| item | question | runs | old | new | why |
|---|---|---|---|---|---|
| D17 | Which refuge points are defective, and who owns them? | 1, 2 (and 3, labelled correctly at the time) | GOOD_ANSWER | WEIRD, high | The answer says the register "does not contain a field for ownership". `input/documents/evacuation_and_peeps.md` has an `owner` column; EV-003 reads "Building Fire Warden Coordinator". |
| D38 | Compare this week's electricity use with last week. | 1 | GOOD_ANSWER | WEIRD, high | "Dropped 35.7 % from W37 to W38": W38 held five days (the run was on a Friday) and W37 seven. I noticed that W36 was excluded and missed that W38 was itself partial. Fixed in `series_summary.py` (BUG-820). |

**What this says about the labels.** Both errors were found by checking a figure or a claim
against the source table, which the codebook allows but which I did not do for every answer.
Register answers checked against their source tables on 18 September: work orders, permits, hazard
controls, fire-safety assets, openings, HVAC regimes (all correct) and refuge points (wrong). The
"good" counts are therefore an **upper bound**, not a floor: an answer I did not check against data
may hold an error of the same kind.
