# Stakeholder run #1 — triage (2026-09-15)

**What was run.** The 67-question bank (`docs/demo_question_bank.jsonl`: one question per
stakeholder catalogue, one per answer category, one per survey reasoning level), asked once
each through `/v1/chat/completions` — the Open WebUI path — as the demo login
(`suhasdevmanemech@gmail.com` → OntoSage `Suhas`, role admin, after BUG-542), response cache
flushed before every ask. Raw answers: `scripts/outputs/stakeholder_run1_2026-09-15.md(.jsonl)`.

**Verdicts are one reader's judgement against each catalogue's answer boundary**, not a
graded benchmark. They are recorded so the re-run can be compared with the same eyes.

| verdict | count | meaning |
|---|---:|---|
| PASS | 16 | answers from the right data, or declines honestly and usefully |
| PARTIAL | 12 | not wrong, but misses what was asked (generic, adjacent register, over-broad absence) |
| FAIL | 39 | wrong register or lane, invented mapping, certification, wrong date, dump, timeout, unsafe side effect |

**First-pass rate: 16/67 (24%).** This is the number to quote. The demo claim "any stakeholder
can ask anything" is not supported by it; a scripted subset drawn from the PASS rows, re-asked
three times, is.

## The failures that matter most

| # | question (abridged) | what happened | owner |
|---|---|---|---|
| 57 | which shutters fail open vs fail locked on power loss? | **queued an actuation command** on AHU-F5-SP with no value | BUG-548 |
| 56 | which drains needed jetting more than twice? | **filed maintenance report REP-452756** | BUG-548 |
| 51 | daylight hour count in the deepest workstation | count of 269 illuminance sensors reported as "269 daylight hours" | BUG-547 |
| 14 | zones lacking confirmed fire-warden coverage | "none of the occupied zones have coverage" — from the approvals register | BUG-545 |
| 6 | systems started late vs approved schedule | approval date read as a start time: "1 day late" | BUG-545/546 |
| 24, 35 | compliance retention / closed work-order evidence | certified as adequate | BUG-546 |
| 8, 15, 25 | continuity / first aid / step-free alternative | raw "Found N result(s)" dump after empty completions | BUG-546 |
| 29, 52 | events due today / open work orders | "today (2026-09-05)" on 15 September | BUG-546 |
| 2 | orphaned permission groups ("mapped opening") | empty bar chart narrated as a finding | BUG-543 |
| 3 | closures and "room moves" | 27.6 s graph scan for the word "moves", then declined | BUG-544 |
| 54 | "you mentioned a sensor fault earlier" | claimed the earlier (non-existent) fault was resolved | OPEN |
| 58 | can my manager see when I badge in? | "Yes" — asserted from access-group records | OPEN |
| 44 | pregnant and overheating — coolest place today? | ranked by daylight/noise, not measured temperature | OPEN |
| 59 | is tap water free somewhere? | events lane read "free" as room availability | OPEN |
| 67 | energy saving suggestions | "could not put an answer together" | OPEN |
| 28, 34 | recovery order / calm place next Wednesday | timeout at 150 s | OPEN |

## Patterns

1. **Register narration invents the link between question and data** (6, 18, 21, 27, 33, 37,
   40, 46, 49, 53). The register lane is handed a register and told to answer; it maps
   whatever fields exist onto the question. BUG-546 adds explicit rules and the date.
2. **Generic words claim a register** (6, 14, 16, 32). BUG-545 makes attributive qualifiers
   stop counting.
3. **Unsafe defaults on side-effecting lanes** (56, 57). BUG-548.
4. **Out-of-scope general knowledge answered** (62 autism, 65 glare sensors, 39 hotel booking).
5. **Timeouts** on multi-criteria recommendation questions (28, 34).

## Fixed during the run, deployed, and re-asked live

| bug | what | live re-ask result |
|---|---|---|
| BUG-542 | Open WebUI login resolved to readonly | `suhasdevmanemech@gmail.com → Suhas (admin)` |
| BUG-543 | chart keyword substring / empty chart | orphaned-groups answered from two registers, no chart |
| BUG-544 | 27.6 s graph scan for an absent word | closures question 147 s → 9 s |
| BUG-545 | attributive "approved/confirmed" claimed approvals | fire-warden and approved-schedule questions no longer answered from approvals |
| BUG-546 | register prompt overflow, remapping, certification, date | step-free alternative grounded (was a dump); no-shows, first aid honest; date correct |
| BUG-547 | count of sensors reported as "269 daylight hours" | "the building model doesn't store daylight-hour counts… 269 illuminance sensors" |
| BUG-548 | question queued an AHU command / filed a report | no command, no report (DB checked) |
| BUG-549 | "is tap water free" routed to bookings | bottle refill points listed |
| BUG-550 | grounded answer suppressed for "the data you shared" | energy suggestions returned |
| BUG-551 | bare "schedule" → room-booking prose | answered from operating regimes, honestly |
| BUG-552 | zero-threshold alerts firing every cycle (621 reports) | 7 rules disabled; creation now asks for measurement and value |
| BUG-553 | "can my manager see my badge logs" → "Yes" | policy-cited refusal |
| BUG-554 | energy advice saw one meter of six | per-floor comparison with real figures |
| BUG-555 | "you mentioned a fault earlier" → invented resolution | "I haven't said anything earlier in this conversation" |
| BUG-537/556 | floor comparison narrated / "which floor" found no sensors | deployed, re-ask pending |
| BUG-557/558 | coolest place → register; reading times in UTC | deployed, re-ask pending |

Raw answers: `scripts/outputs/reask1_2026-09-15.md`, `reask2_…`, `reask3_…`, `demo_pass1_…`.
