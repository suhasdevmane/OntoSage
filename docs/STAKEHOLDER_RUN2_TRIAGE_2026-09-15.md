# Stakeholder run #2 — triage (2026-09-15, after BUG-539..564)

Same 67-question bank, same path (`/v1`, forwarded admin login), cache flushed per ask.
Raw: `scripts/outputs/stakeholder_run2_2026-09-15.md(.jsonl)`.

| verdict | run #1 | run #2 |
|---|---:|---:|
| PASS | 16 | **41** |
| PARTIAL | 12 | 10 |
| FAIL | 39 | **16** |

**Read this before quoting it.**
* The same person fixed the defects and graded both runs; the bias runs toward improvement.
* About **20 of the 41 passes are honest "the records do not hold that" answers** (e.g. #11, #12,
  #15, #17, #24, #27, #45, #53). They count because each catalogue's answer boundary makes that
  the correct answer — but substantive grounded answers are closer to **21/67**.
* Nothing unsafe recurred: no command queued, no report filed from a question, no privacy
  leak, no invented "earlier" context, no count reported as a measurement.

## Remaining failures (16)

| # | pattern | example |
|---|---|---|
| 4 | canned compare template for a non-sensor comparison | route lengths vs design assumptions |
| 6 | timeout (150 s) — answered honestly on re-ask earlier | late starts vs approved schedule |
| 8, 33, 40, 55 | narration invents a mapping (sensor count = fragility; below-design duty = off-schedule; runtime figure) | continuity; enrolment fragility |
| 16, 49, 57, 60, 63, 64 | wrong lane or register, answered about something else (lab list, AV register, energy meter, toilet topic) | server-room alternatives; room for 12 with projector |
| 21, 46 | "could not put an answer together" | mock viva room; phone-booth conversion |
| 39, 62 | out of scope answered (hotel booking; medical) — **scope decision is the user's** | book a hotel; why autism happens |

## Next fixes (after the demo unless trivial)
1. Compare lane's canned template should say the building holds no such series, not ask for zone IDs.
2. Static capability topics ("Quiet Study", "Transport Parking", "Toilet facility") answer
   questions that merely share a word — the capability short-circuit needs the same yield rules
   as the register one (lesson #105).
3. Recommendation/deliberation prompts: forbid proxies (sensor count) as evidence for a property.
