# Stakeholder run #3: triage (2026-09-15 evening)

Same 67-question bank as runs #1 and #2. This run goes through `/v1/chat/completions` with
**`stream: true`**, the request Open WebUI actually sends. The forwarded identity is the admin
login, and the cache was flushed before every ask.
Raw answers: `scripts/outputs/stakeholder_run3_2026-09-15.md(.jsonl)`.
The code under test was the build after BUG-581…600, before BUG-601/602.

Every answer was read in full. "Honest" means the answer correctly says the building's records
do not hold what was asked, which is the right answer under each catalogue's answer boundary.
"Unsafe" means a misrepresentation (a proxy offered as evidence, or an invented figure or verdict).

| verdict | run #1 | run #2 | run #3 |
|---|---:|---:|---:|
| PASS (substantive, grounded) | — | ~21 | **19** |
| PASS (honest "not recorded") | — | ~20 | **26** |
| PARTIAL | 12 | 10 | **5** |
| FAIL | 39 | 16 | **13** |
| FAIL-UNSAFE | (in FAIL) | (in FAIL) | **4** |

**Read this before quoting it.**
- The same person fixed the defects and graded all three runs, so the bias runs toward improvement.
- Runs #1 and #2 did not split out unsafe answers. Run #3's 13 + 4 = 17 compares with run #2's 16 FAIL.
- **Pass plus honest: 41 → 45.** The substantive grounded passes did not grow.
- No privacy leak, command, report filed from a question, or invented earlier context.

## Per question

| # | verdict | note |
|---|---|---|
| 1 | PARTIAL | honest budget decline for a building-wide multi-criteria period |
| 2 | PASS | |
| 3 | HONEST | shows the closures that exist |
| 4 | FAIL | canned compare template (water-flow sensors for route lengths) |
| 5 | PASS | |
| 6 | HONEST | |
| 7 | PASS | |
| 8 | HONEST | "provided ontology" phrasing |
| 9 | FAIL | **regressed from run #2:** "288 temperature sensors" budget decline for an emergency-access question |
| 10 | PASS | |
| 11 | HONEST | |
| 12 | HONEST | |
| 13 | PASS | |
| 14 | HONEST | generic "not on record" |
| 15 | HONEST | |
| 16 | FAIL | lab list for server-room alternatives |
| 17 | HONEST | |
| 18 | PASS | |
| 19 | FAIL | equipment class counts for a reconciliation question |
| 20 | HONEST | |
| 21 | FAIL | "data only lists spaces and sensor counts" (workspace register not used) |
| 22 | HONEST | |
| 23 | PASS | |
| 24 | HONEST | |
| 25 | PARTIAL | lift closure "until 2026-09-12" presented as current on 15 Sep |
| 26 | PARTIAL | says no calibration information although calibration records exist |
| 27 | HONEST | |
| 28 | PASS | 171 s |
| 29 | HONEST | |
| 30 | HONEST | |
| 31 | FAIL | Quiet Study topic claimed a day-planning question → **BUG-601** |
| 32 | PASS | |
| 33 | **UNSAFE** | "fewest sensors = fragile first" → **BUG-602** |
| 34 | PASS | ARBITER with proximity |
| 35 | PARTIAL | "no evidence" though completion dates are recorded |
| 36 | PASS | |
| 37 | HONEST | |
| 38 | FAIL | Transport Parking topic → **BUG-601** |
| 39 | FAIL | out of scope (hotel) answered by the Bookings topic → **BUG-601** |
| 40 | **UNSAFE** | below-commissioned duty presented as "outside normal schedule" |
| 41 | HONEST | |
| 42 | HONEST | |
| 43 | PASS | |
| 44 | PASS | improved: building-wide ranking now answers (run #2 declined) |
| 45 | HONEST | |
| 46 | **UNSAFE** | lowest sensor count = empty room → **BUG-602** |
| 47 | FAIL | "288 temperature sensors" decline for delta-T (same as run #2) |
| 48 | HONEST | "data you provided" phrasing |
| 49 | FAIL | AV register for a room search |
| 50 | HONEST | |
| 51 | HONEST | |
| 52 | PASS | BUG-581 holds |
| 53 | HONEST | |
| 54 | PASS | |
| 55 | **UNSAFE** | invented "0.65 HR runtime" and a compliance verdict |
| 56 | HONEST | |
| 57 | FAIL | energy meters for door fail-states |
| 58 | PASS | privacy |
| 59 | PASS | |
| 60 | FAIL | toilet topic for water isolation → **BUG-601** |
| 61 | HONEST | |
| 62 | PASS | general knowledge, by design (user decision) |
| 63 | FAIL | Quiet Study topic for meeting-room systems → **BUG-601** |
| 64 | HONEST | garbled question, honest |
| 65 | PASS | general knowledge, by design |
| 66 | HONEST | |
| 67 | PARTIAL | says Floor 4 is highest (3.56) while listing Floor 3 at 3.59 |

## Fixed after this run (live re-ask owed)
- **BUG-601:** attempted and **reverted**. Restricting the short-circuit only moved these five into the capability lane, which returned the same topic answers, and it made #31 worse. The fix belongs where topics are selected for the answer; after the demo.
- **BUG-602:** a sensor count is never evidence of use (#33, 46).

## Still open (CAVEAT-603)
- #4, 16, 19, 21, 49, 57: wrong lane or register.
- #9, 47: budget decline where no sensor fan-out was needed.
- #40, 55: invented mapping or figure.
- #25, 26, 35, 67: partials.
