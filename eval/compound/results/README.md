# Captured answers

One directory per system version. Each `<set>.jsonl` holds one line per item: the answer exactly
as `/v1/chat/completions` returned it (non-streamed), the lane that answered (`ontosage_intent`,
`ontosage_route`), the plan trace, sources, turn and retrieval outcomes, and the wall-clock
seconds. Each `<set>.meta.json` records the git commit the stack was running, the identity the
questions were asked as, the UTC start and finish, and the transport error count.

Captured with `scripts/run_compound_eval.py`; paired and blinded for reading with
`scripts/make_blinded_sheet.py`; scored with `scripts/score_blinded.py`. The protocol and the
pre-registered analysis are in `tasks/V2_COMPOUND_PLAN.md` section 5.

## v1 (commit 8965cd1, tag `v1.0-demo`)

| file | items | asked as | notes |
|---|---|---|---|
| `T-REAL.jsonl` | 27 | facility01 (facility_manager) | held-out, primary |
| `T-REAL-SUPPLEMENT.jsonl` | 22 | facility01 | held-out, primary (pooled with T-REAL) |
| `T-CAT.jsonl` | 42 | facility01 | held-out, secondary; one turn degraded (the LLM did not answer in time) and is kept as v1's answer |
| `DEV-40-s1.jsonl` | 40 | facility01 | development sample only, never a thesis number |
| `DEV-40-s1.INVALID-graphdb-wedge.jsonl` | 40 | facility01 | **not data.** GraphDB stopped responding during this run (39 of 40 turns degraded); it was restarted and the sample re-captured as `DEV-40-s1.jsonl`. Kept so the re-capture is visibly a re-capture. |

The held-out captures ran 23:02-23:22 UTC on 2026-10-07, before the GraphDB fault (its log
stopped at 00:01:53 UTC on 2026-10-08), and none of their turns is degraded except the one
T-CAT turn noted above. The role was confirmed from the server's own `[forwarded-user]` log line,
not from the flag passed to the script.
