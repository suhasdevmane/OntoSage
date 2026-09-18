# Phase 0 run 3, labelled by hand (READER-3)

- input: `docs/phase0/phase0_run3.md.jsonl` — the same 147 questions via `/v1` streaming as facility01,
  2026-09-17 ~22:00–23:30, after the night's fixes
- earlier reads: `docs/phase0/phase0_read.jsonl` (READER, 14:10–15:20) and
  `docs/phase0/phase0_rerun_read.jsonl` (READER-2, ~16:00–17:30). Labels for this run are in
  `docs/phase0/phase0_run3_read.jsonl`
- every run-3 answer was read in full against its question and its written boundary. Verdicts, cause
  codes and classes follow `phase0_read.md` exactly. WEIRD = would read as broken, off-topic,
  incomplete, invented, or as an instruction to add data. A decline is GOOD_DECLINE only when the
  building truly lacks the thing and the wording neither attributes the data to the reader nor asks
  for more of it. A clarification counts as GOOD_DECLINE (the precedent both earlier readers set on
  rows 127 and 138).
- the owner's standing rule was applied as written: no user-visible text may say simulated, synthetic
  or fake, name internal machinery, or call the building's own data something the user supplied.
- Room 0.01 "Main Reception" wording was not counted against any answer (known, deliberately held).
- offline only: no SPARQL, no live re-ask, no stack. Where I say the building holds something, I rely
  on READER's read-only counts, or on **another answer in the same run 3** that shows the record. The
  second kind is the stronger evidence and I have used it wherever it exists (rows 85, 86, 129 are
  each contradicted by a different answer in their own run).
- the calibrated grader (`scripts/grade_answers_rubric.py --judge deterministic`) was run offline over
  this file for comparison only. Its verdicts are a tool's opinion, never ground truth.

## Headline

| verdict | run 1 | run 2 | run 3 |
|---|---:|---:|---:|
| GOOD_ANSWER | 19 (12.9%) | 10 (6.8%) | **14 (9.5%)** |
| GOOD_DECLINE | 21 (14.3%) | 24 (16.3%) | **37 (25.2%)** |
| WEIRD | 107 (72.8%) | 113 (76.9%) | **96 (65.3%)** |

**Weird share: 72.8% → 76.9% → 65.3%.** WEIRD at high confidence only: 60 → 68 → **65**.

That is the first movement in the right direction across the three runs, and it is not small: 24 rows
improved against 7 regressed, net **+17**. But read the composition before celebrating. Of the 51
rows I now call good, **37 are declines and 14 are answers** — the run gained 13 declines and 4
answers. The system got markedly more honest; it did not get much more capable. Run 1 had 19 good
answers; run 3 has 14.

## Transitions (run 2 → run 3)

| run 2 \ run 3 | GOOD_ANSWER | GOOD_DECLINE | WEIRD | total |
|---|---:|---:|---:|---:|
| GOOD_ANSWER | 7 | 0 | 3 | 10 |
| GOOD_DECLINE | 0 | 20 | 4 | 24 |
| WEIRD | 7 | 17 | 89 | 113 |

| change | rows | row numbers |
|---|---:|---|
| IMPROVED | 24 | 15, 20, 27, 28, 45, 51, 53, 61, 71, 73, 74, 84, 87, 100, 101, 102, 105, 107, 111, 118, 121, 123, 137, 143 |
| SAME_GOOD | 27 | 7, 18, 22, 23, 37, 38, 39, 40, 50, 52, 62, 67, 68, 79, 94, 106, 114, 116, 124, 125, 126, 127, 130, 131, 133, 138, 140 |
| SAME_WEIRD | 64 | 0, 1, 3, 4, 6, 8, 10, 11, 13, 14, 16, 17, 21, 24, 25, 29, 30, 31, 32, 35, 36, 42, 43, 44, 46, 47, 48, 56, 57, 58, 60, 63, 64, 66, 69, 75, 76, 77, 82, 83, 86, 92, 93, 95, 96, 97, 98, 99, 103, 104, 109, 112, 113, 117, 122, 128, 129, 132, 135, 136, 139, 141, 142, 145 |
| CHANGED_STILL_WEIRD | 25 | 2, 9, 12, 26, 33, 41, 49, 54, 55, 70, 72, 78, 80, 81, 85, 88, 89, 90, 91, 110, 115, 119, 134, 144, 146 |
| REGRESSED | 7 | 5, 19, 34, 59, 65, 108, 120 |

### Which of the night's changes actually did what it was meant to

Checked by reading the answers, not by trusting the change list.

- **The deictic clarification landed and is the single biggest win.** "Which room do you mean by
  'this room'?" appears on 6 answers (rows 73, 74, 100, 101, 137, 143) where run 2 had an arbitrary
  sensor, an add-data decline, a 296-sensor refusal or an internal fragment. Class C6b: 4 → **0**.
  Rows 100 and 101 went from 125 s and 0.5 s of wrong answer to 0.4 s of the right question.
- **The footers were fixed at the source, not just reworded.** "Boundary: not declared" 10 → 2
  answers; "Switch if: conditions in the space you chose" 10 → 2; "Evidence time: unknown" 4 → **0**.
  Class C6a: 4 → **0**. Row 145's energy footer is now correct and names its six meters. Two misfires
  survive (rows 113, 132).
- **Questions are no longer filed as tickets.** Row 49's maintenance ticket REP-7420E1 and "An
  administrator has been notified" are gone; no answer in run 3 writes anything. The NEW
  question-filed-as-report class is at 0.
- **"The owner of that record holds the answer" is gone** — 19 answers in run 2, **0** in run 3,
  replaced by "so the building's records do not cover this", which is honest and which turned 9
  document declines into GOOD_DECLINE.
- **Route questions get an explanation.** Row 61 now says "You asked about a route, and I answer by
  comparing spaces — so I won't hand you a room instead". Row 72 reaches the accessible-route
  register and finds RTE-007 as the verified alternative.
- **The unmapped-phrase block is gone.** Row 117 ("I'm pregnant and overheating") now answers with
  "'pregnant' isn't a sensed modality here — ignored" as a stated assumption, and row 58's
  "I couldn't verify this building's sensor coverage" non-answer is gone.
- **Registers are consulted before the document lane declines**, visibly: the cleaning register
  answers row 20, the workspace register rows 53 and 59, the accessible-route register rows 72 and
  111, the continuity register row 81, the event register rows 84 and 105.
- **Record dates rolled forward and overdue records stayed overdue** — rows 18, 19, 20, 130 all carry
  correct today-relative dates, and WCP-024 and DR-015 are still reported overdue.
- **What did not work: the whole-building-scope change.** "A phrase naming no space is treated as
  whole-building scope instead of blocking the question" reads, in practice, as five fetch-budget
  refusals (rows 0, 16, 17, 25, 134 — class C2 is now 5, its highest across the three runs) and as the
  absence guard firing three times (rows 41, 70, 108) where it fired **zero** times in run 2. C1 is
  back from 0 to 3, and it took two rows that had been fine.

## Regressed rows (7)

### row 5 (AC-001, Access-control administrators) — GOOD_DECLINE → WEIRD [C7], high

Q: Which minimum approved permission package should be prepared for this verified starter on the
authorised effective date?

- **run 2 (12.0 s):** "The records do not contain a concept of a 'verified starter' or an 'authorised
  effective date.' They record the following fields for each permission group…"
- **run 3 (14.8 s):** "The only record that matches a 'verified starter' (i.e., a single-off,
  exception-type permission) is **APG-013 – Instrument recalibration — one-off** … **Granted to:**
  External contractor … **Time profile:** ESCORTED"
- **likely cause:** the register lane stopped declining and instead invented an equivalence — an
  escorted external contractor's one-off lab permit read as a new staff member's starter package. The
  honest "no such concept" answer was the correct one and it was dropped.

### row 19 (CT-065, Cleaning and caretaking teams) — GOOD_ANSWER → WEIRD [C7], high

Q: When is the next authorised waste collection, and what needs to be ready before the contractor arrives?

- **run 2 (17.8 s):** "the **next authorised collection is scheduled for 18 September 2026** … 'No
  explicit "ready-before-arrival" instructions … are recorded'"
- **run 3 (18.4 s):** "**Bins must be at or above the approved fill threshold** … WCP-023: fill 55 %
  (threshold 60 %) – below threshold – **should be filled**."
- **likely cause:** the same phrasing READER flagged in run 1 ("Each bin should contain waste that has
  reached or exceeded its approved fill threshold") is back. The fill threshold is a collection
  trigger, and the narration turned it into an instruction to a cleaner to fill a clinical sharps bin.
  The date anchoring, which was the run-1 defect, is still correct.

### row 34 (FM-040, Facilities managers) — GOOD_DECLINE → WEIRD [C7], med

Q: Is the evidence complete enough for organiser and service owners to review event-space handover?

- **run 2 (9.1 s):** "These records do not contain evidence for event-space handover; they record
  handover records for equipment such as AHUs, BMS, fire alarm, lift"
- **run 3 (108.1 s):** "**No** – the handover evidence is not yet complete … **HO-CHILL-OM** … **HO-GEN-OM**
  … **HO-SPRINK-OM** … Because three required handover documents are still outstanding, the evidence
  set is incomplete for a full review."
- **likely cause:** the same register, narrated with a conclusion instead of a limit. Three outstanding
  chiller, generator and sprinkler handovers are used to answer a question about an event space. The
  verdict is confidently right about the wrong subject.

### row 59 (AR-023, People with mobility, sensory or other accessibility requirements) — GOOD_DECLINE → WEIRD [C3], high

Q: I need a seat near an exit. Which authorised seating options meet that preference without
obstructing circulation?

- **run 2 (17.5 s):** "I'm sorry, but the building's records do not contain any information about how
  close a workspace is to an exit…"
- **run 3 (7.6 s):** "**The records you have** do not contain any information about how close a seat
  is to an exit…"
- **likely cause:** user attribution (BUG-679) re-entered a decline that was otherwise word-for-word
  correct. The owner's rule names this exact phrasing, and it is the only defect on the row.

### row 65 (PS-053, Professional-services staff) — GOOD_ANSWER → WEIRD [C10], high

Q: I have appointments on different floors with a short gap. What conservative travel and setup buffer
should I allow?

- **run 2 (6.6 s):** "Use a buffer of at least **9.5 minutes** travel time – the longest journey
  (Level 0 to Level 5) takes 9.5 minutes walking, which exceeds the standard five-minute changeover."
- **run 3 (10.7 s):** "9.5 minutes." + document footer. That is the whole answer.
- **likely cause:** the document lane's extract shortened to a bare figure with no subject and no
  basis, the same shape as rows 31, 93 and 144. The setup half of the question is dropped silently,
  and a reader cannot tell 9.5 minutes of what.

### row 108 (WM-054, Waste-management teams) — GOOD_DECLINE → WEIRD [C1], high

Q: Were bins, skips, compactors, seals or locks exchanged and handed back exactly as recorded?

- **run 2 (7.5 s):** "The records do not contain information about whether bins, skips, compactors,
  seals or locks were exchanged and handed back exactly as recorded. They do record the current status
  of each waste-collection point…"
- **run 3 (9.0 s):** "I can't complete that request as asked. To be accurate about one thing: this
  building **does** have 12 waste_fill sensor(s) — the limitation isn't a lack of sensing."
- **likely cause:** the absence guard replaced a correct decline with a correction to a claim the
  answer never made, and printed a snake_case modality name while doing it. This is the run-1 C1
  pattern, which run 2 had at zero.

### row 120 (Q325, Facility manager) — GOOD_ANSWER → WEIRD [C7], high

Q: What's the delta-T across the heating circuit, and is it healthy?

- **run 2 (45.0 s):** "Boiler 2 … = 11.05 °C (the largest ΔT). Boiler 1 shows a ΔT of 10.52 °C … the
  heating circuit is operating with a consistent temperature rise."
- **run 3 (34.6 s):** "**Latest snapshot (2026-09-12 17:50:00)** - Boiler 1: 57.16 °C → 68.01 °C …
  **Overall statistics (12 Sep 17:50 – 17 Sep 23:37)**"
- **likely cause:** the snapshot labelled "latest" is the **start** of the answer's own stated window —
  the oldest reading named as the newest, the BUG-520 shape. A five-day-old reading then carries the
  "so the heating circuit is healthy" verdict.

Three of the seven (59, 108, and 65) are single-sentence regressions in wording or extract length and
should be cheap to fix. Two (5, 34) are the register lane preferring a confident wrong answer to an
honest limit — the opposite trade from the one the night's work was aiming at. Row 120 is a date bug
with a real number attached, which makes it the most dangerous of the seven in front of a supervisor.

## Per-class counts (primary class of each WEIRD row)

| class | name | run 1 | run 2 | run 3 | run-3 rows |
|---|---|---:|---:|---:|---|
| C1 | Absence guard rewrites a valid answer because a modality alias matched inside another word | 3 | 0 | **3** | 41, 70, 108 |
| C2 | Fetch-budget refusal for whole-building, multi-measurement questions | 2 | 4 | **5** | 0, 16, 17, 25, 134 |
| C3 | Narration hygiene: 'the records you have', raw field names, internal provenance | 6 | 5 | 5 | 32, 59, 69, 77, 115 |
| C4 | Metadata/discovery RAG fallback: the ontology named, false absence, add-data | 6 | 14 | **9** | 4, 13, 44, 49, 57, 75, 76, 129, 139 |
| C5 | 'I understood the question but could not put an answer together' | 4 | 6 | 6 | 10, 12, 35, 80, 83, 95 |
| C6a | Shelf-life and meter-boundary footers attached to answers they do not describe | 4 | 4 | **0** | — |
| C6b | Deictic referent resolved to an arbitrary sensor or declined | 4 | 4 | **0** | — |
| C7 | Register narration misreads statuses, dates and fields, or invents conclusions | 18 | 17 | **20** | 3, 5, 11, 19, 21, 26, 34, 36, 54, 55, 60, 63, 64, 72, 78, 81, 90, 92, 113, 120 |
| C8 | Register chosen on a bare word; the lane declines with unrelated register statistics | 14 | 8 | **7** | 1, 30, 42, 48, 97, 98, 110 |
| C9 | The building holds the data but no lane reaches it (false absence) | 9 | 8 | 8 | 9, 33, 43, 66, 85, 86, 88, 122 |
| C10 | Document lane returns a bare fragment or an internal token as the whole answer | 4 | 5 | **6** | 31, 65, 93, 104, 144, 146 |
| C11 | Catch-all 'documents do not answer this' for out-of-scope or planning requests | 6 | 12 | **5** | 8, 82, 89, 103, 112 |
| C12 | Open-domain questions answered from general model knowledge, unlabelled | 4 | 4 | 4 | 135, 136, 141, 142 |
| C13 | Deliberation lane: blocked phrases, out-of-band rankings, routes reaching ranking | 5 | 4 | 4 | 58, 99, 117, 119 |
| C14 | Compare/trend fallback dead end | 2 | 1 | 1 | 2 |
| C15 | 'You can add it — upload a TTL' as the answer | 2 | 0 | 0 | — |
| C16 | Anomaly question answered from user reports, UUIDs as place names | 1 | 1 | 1 | 29 |
| C17 | Future or hypothetical questions answered by the current-reading lane | 2 | 1 | **2** | 91, 128 |
| C18 | Report lane answers a non-report question | 1 | 1 | 1 | 96 |
| C19 | Assorted shortcut misroutes (operator, building figures, compliance template, space listing) | 5 | 6 | **3** | 14, 46, 47 |
| C20 | Referent gate treats a descriptive phrase as a named space | 1 | 1 | **0** | — |
| C22 | Recommend lane produces generic advice not grounded in the building | 4 | 4 | 4 | 56, 109, 132, 145 |
| NEW | closure-shortcut: a closure list answers anything mentioning closures | 0 | 2 | 2 | 6, 24 |
| NEW | question-filed-as-report (write side effect) | 0 | 1 | **0** | — |
| **total** | | **107** | **113** | **96** | |

Three classes went to zero (C6a, C6b, C20, plus the report-capture), four fell (C4, C8, C11, C19), and
three rose (C1, C2, C7, C10). **C7 is now the largest single class it has ever been** — 20 of 96 weird
rows, one in five. The pattern is consistent: as the wrong-register and catch-all declines were
removed, the right register was reached more often, and the narration over that register is where the
remaining damage is.

### Phrases counted mechanically across all 147 answers (secondary defects included)

| phrase | run 1 | run 2 | run 3 |
|---|---:|---:|---:|
| meter footer 'Boundary: not declared' | 7 | 10 | **2** |
| recheck footer 'Switch if:' | 9 | 10 | **2** |
| 'Evidence time: unknown' | 4 | 4 | **0** |
| user attribution ('you provided' / 'records you have' / 'you retrieved' / 'you posted') | 8 | 12 | **4** |
| 'simulated' | 3 | 1 | **0** |
| TTL / upload instruction | 5 | 0 | 0 |
| 'The room holds N records' | 7 | 0 | 0 |
| 'add or update it' | 6 | 0 | 0 |
| 'The owner of that record holds the answer.' | 0 | 19 | **0** |
| 'I understood the question but could not put an answer together' | 4 | 6 | 5 |
| 'That question reaches N sensors' | 2 | 5 | **5** |
| "couldn't render the chart" | 2 | 2 | 2 |
| "I can't complete that request as asked" (absence guard) | 3 | 0 | **3** |
| "Which room do you mean…" (deictic clarification) | 0 | 0 | **6** |
| internal IRI/class token in backticks (`bldg:`, `s223:`, `brick:`) | 9 | 2 | 2 |

All three columns were counted with one regex over all three files, so the run-1 and run-2 numbers
here differ by one or two from READER-2's hand-checked table (she excluded "the area you asked about"
inside the meter footer by eye, and counted 'Switch if' as 7 where the pattern finds 9). The
comparison within this table is like-for-like; the absolute run-1/run-2 figures in
`phase0_rerun_read.md` are the hand-checked ones.

The owner's standing rule is now broken on 4 answers for attribution (rows 13, 59, 69, 115) and on
roughly a dozen for naming internal machinery: `ApprovalRecord` and `policyOwner` (row 4),
`bldg:approval/APR-001` and "the snippet you posted" (13), `servesService` (44), `Ablutions_Room` (57),
"The query returned three records" (76), "schema mapping: hazard_controls" (77), "the building's
**events store**" (80), Brick class names inside the ranking dossiers (58, 99, 117, 119),
`bldg:continuity/CP-001` (129), and an internal schema design note quoted verbatim to a user (139,
146). None of these is a false statement; every one of them tells the reader what the system is made
of instead of what the building is like.

## What remains, ranked by how visible it would be to a supervisor asking live

| rank | class | rows | severity | why it shows |
|---:|---|---:|---|---|
| 1 | **C7** register narration misreads fields, dates and statuses, or invents conclusions | 20 | P1 | It reads as confident fact and it is the most likely output of any question that hits a register. Worst for a demo: row 120 (a five-day-old reading called the latest, then "the heating circuit is healthy"), row 63 (a professional-services user told to "inspect the damper on the VAV box"), row 19 (a cleaner told to fill a clinical sharps bin), row 78 ("a clear sign of repeated no-shows" from two cancellations, called "consecutive days" for 30 Aug and 2 Sep), row 54 (two overdue dates computed wrong), row 60 and row 92 (rooms 2.15, 4.11, 4.12 filed under the wrong floor). |
| 2 | **C9** the building holds it and no lane reaches it | 8 | P1 | Three of the eight are contradicted **by another answer in the same run**: row 85 says no lift fault is recorded while row 72 reports RTE-016 closed with Lift B out of service; row 86 says the patrol register has nothing while row 22 lists three overdue checkpoints; row 122 denies a projector record. A supervisor who asks two related questions sees the contradiction himself. |
| 3 | **C4** metadata RAG fallback: the ontology named, false absence | 9 | P1 | Row 57 tells a person with accessibility needs the building holds "no reference to a location named Abacws"; row 44 tells a safety officer to "**create a record**" and link it "using `servesService`"; row 129 denies drain work while row 125 lists "WO-015 – Condensate drain clearance"; row 139 prints an internal schema note. |
| 4 | **C13** deliberation lane | 4 | P1 | It is the most impressive-looking output, so it is the most likely to be demonstrated. Row 99 prints "**occupancy: -7.719**" and "co2: -260.986" and recommends a research laboratory to an undergraduate; row 119 says "I couldn't rank any spaces … **Why:** not an occupied space — name it to include it (Mechanical_Room)"; row 58 recommends an academic office as a seating area; row 117 separates its top three by 0.03 °C and calls the choice stable. |
| 5 | **C1** absence guard | 3 | P1 | Three whole answers replaced by "I can't complete that request as asked … this building **does** have 296 temperature sensor(s)", for a fire impairment (41), an accessibility question (70) and a waste handover (108). Two of the three were correct before tonight. It is a single-line fix with a `\b` and it takes back two regressions. |
| 6 | **C22** recommend lane | 4 | P1 | Row 132 answers a student asking whether tap water is free with "install on-site water-filtration stations", on a flow figure of 292 m³/s; row 109 talks about "the capacity of each ABACWS"; row 145 contradicts its own list within two lines. |
| 7 | **C2** fetch-budget refusal | 5 | P2 | Five answers now say "That question reaches **296 sensors**", up from two in run 1. The new wording is better, but rows 25 and 134 cannot be reworded into "which place is best for". |
| 8 | **C10** bare fragment as the whole answer | 6 | P2 | "Electrical inspection." (31), "9.5 minutes." (65), "Lecture capture and streaming (Room 4.44 — Server Room)" (93). A one-line answer with a footer looks like a failure even when it is arithmetically right. |
| 9 | **C5** 'could not put an answer together' | 6 | P2 | The lane names are gone, but the replacement offers "it measures air quality, carbon monoxide, co2 and damper position" to five different questions, none of which is about any of those, and asks the reader to "tell me where **priorities** is written down". |
| 10 | **C19** shortcut misroutes | 3 | P2 | Row 14 still answers a control-ownership question with one line: "**Abacws Building** — operated by: **Cardiff University Estates**." Rows 46 and 47 answer network and host questions with the sensor census. |
| 11 | NEW closure-shortcut | 2 | P2 | Rows 6 and 24: whatever is asked, the answer is the same three-closure list. |
| 12 | **C8** bare-word register capture | 7 | P2 | Down from 14, but "They only contain access-permission group records" still answers a fairness question (97). |
| 13 | **C3** narration hygiene | 5 | P1 wording | Four attribution hits, one uuid dump (32). Each is one sentence. |
| 14 | **C11** document catch-all | 5 | P3 | Halved, and the wording is honest now. "Book me a hotel" still ends in "I searched Room Bookings" (112). |
| 15 | **C12** open-domain prose | 4 | P3 | Unchanged: autism, ozone, glare sensors, CO2 — all answered from general knowledge with nothing marking them as not from the building. |

**If only one thing is fixed before the demo, fix C1** (3 rows, one word-boundary, recovers two
regressions). **If two, add the C7 date arithmetic** (rows 54, 72, 120 all compute or label a date
wrong, and row 120 attaches a verdict to it).

## The calibrated grader says the weird share fell 53.7% → 40.1%. What do I measure?

I measure **76.9% → 65.3%** (113 → 96 rows). The grader measures 53.7% → 40.1% (79 → 59 rows). I
re-ran the grader offline over run 3 to check the number I was given: `GOOD_ANSWER 56 ·
GOOD_DECLINE 32 · WEIRD 59 · weird share 40.1%`. It reproduces.

**On the direction we agree, and that matters.** Both instruments move down by roughly the same
amount — the grader by 13.6 points, I by 11.6. This is the first time in three runs that the grader
and a reader have moved the same way (READER-2 recorded them moving in opposite directions on run 2),
and it is the strongest evidence in this file that the night's work did something real. The
calibrated grader is a very different instrument from the old heuristic: on the 294 labelled rows it
scores kappa 0.42 against the old grader's 0.12, and on this run it agrees with me on 80/147 exactly
and 92/147 weird-or-not, against 52/147 for the old one on run 2.

**Where we disagree is the level, and the disagreement is one-sided.**

| I say \ grader says | GOOD_ANSWER | GOOD_DECLINE | WEIRD |
|---|---:|---:|---:|
| GOOD_ANSWER | 12 | 2 | 0 |
| GOOD_DECLINE | 10 | 18 | 9 |
| WEIRD | 34 | 12 | 50 |

- **46 rows the grader calls good and I call weird.** That is the whole gap and it is the same gap
  READER found: the grader's rules read SHAPE. It has a rule for a named ontology, for a footer
  misfire, for a fragment, for user attribution, for lane jargon — and it fires correctly on all of
  those. It has **no way to know that a date was computed wrong** (54, 120), that a floor label
  contradicts the room number (60, 92), that "cancelled" is not "no-show" (78), that a status field
  called `none` does not mean "displaced" (21), that an inspection interval is not a sampling rate
  (55), or that the building holds the record the answer just denied (85, 86, 122, 129). Those are
  content checks against the register, and the grader never reads the register. Most of my C7 and C9
  rows are invisible to it by construction: it scores 13 of my 20 C7 rows as GOOD_ANSWER.
- **9 rows the grader calls WEIRD and I call good** (40, 50, 52, 67, 71, 79, 94, 118, 133). Eight are
  the document-decline template, which its DOCUMENT_CATCHALL rule penalises on sight. I checked each:
  the registers named are the relevant ones and the thing asked for genuinely is not held. A decline
  is not a defect, and the grader's own calibration table shows this rule firing on 5 human-GOOD rows,
  the worst false-positive rate of any rule it has. On run 3 that rule alone costs it 8 rows.
- **The two share a blind spot.** Neither of us graded latency, and 11 answers took over 60 s
  (row 12 at 138.9 s and row 24 at 125.9 s are both non-answers).

**My reading of the grader: trust its direction, not its level.** As a regression gate — "did the
weird share rise?" — it is now good enough to use, and its 40.1% is a floor, not an estimate. As a
number to put in front of a supervisor, it is 25 points optimistic, and the 25 points are entirely
made of answers that look right and are not. The single change that would close most of the gap is
giving it the register rows: a check that every cited ID exists, every count equals a computed count,
every date arithmetic resolves, and every floor grouping matches the room number, would let it see
most of C7 — the class that is now the largest.

## Things I could not tell

- **Whether run 3 is better or merely luckier.** All three runs are one sample each at a non-zero
  temperature. Seven of my 24 improvements (15, 27, 51, 84, 87, 107, 121) are the same register and
  the same lane narrating *better* this time, with no obvious fix behind them, exactly mirroring the
  seven run-2 regressions READER-2 attributed to narration variance. If all seven flipped back, the
  weird count would be 103, not 96 — still the best of the three, but a 4-point improvement rather
  than 11.6. The claim I will stand behind is **a real but partly compositional improvement, made
  mostly of honest declines**, not "the weird share fell by a sixth".
- **Whether I am more lenient than READER-2.** I made two judgement calls she did not face: I counted
  the six "Which room do you mean?" clarifications as GOOD_DECLINE (following the rows-127/138
  precedent, which both earlier readers set), and I counted the reworded document decline as
  GOOD_DECLINE where the registers searched were relevant and the absence real. Those two decisions
  account for 15 of my 51 good rows. A reader who called clarifications INCOMPLETE would put run 3 at
  102 weird (69.4%) — still an improvement, still the best of three.
- **The rows where the building's holdings are asserted from READER's SPARQL, not from this run.**
  Rows 1, 30, 33, 42, 48, 66, 88, 98, 122, 128, 139 rest on the baseline counts (AVReadiness 22,
  CleaningTask 30, FirstAidPoint, Permit 15, 1,929 calibrated sensors). I ran no query. Rows 85, 86
  and 129 are the safe ones: another answer in the same run shows the record.
- **Row 27.** I marked it GOOD_ANSWER because "None of the exception texts include explicit evidence
  of safety, frost, specialist service, override or fault" is honest and the counts check. But REG-001
  says "published open days" and REG-002 "approved by the School", which an auditor might read as
  override evidence. If so the answer is wrong in the safe direction — under-claiming — and I have
  given it the benefit of the doubt where I gave none to over-claiming.
- **Rows 111 and 117 are GOOD at low confidence.** Row 111 answers a pushchair question well and then
  says "**Distance:** 40 m (≈ 10 min walk)". Row 117 I called WEIRD at low confidence and it is the
  one row I could most easily be argued out of: it answers, it states its assumptions, it drops the
  unmappable phrase rather than blocking — the defect is only that its top three are within 0.03 °C
  and it calls the winner stable.
- **Row 131.** "Denied for every role; aggregate alternatives are offered" and
  "_Policy: `policy_inference_individual_pattern`_" are internal wording under the owner's rule, but
  both earlier readers passed this row with the token present, so I did too. If the rule is applied
  strictly it is WEIRD and the count is 97.
- **Latency.** Not graded. Run-3 answers over 60 s: rows 12 (138.9 s), 24 (125.9 s), 98 (111.3 s),
  34 (108.1 s), 42 (99.2 s), 40 (92.7 s), 89 (92.0 s), 99 (91.6 s), 109 (77.5 s), 49 (77.0 s),
  81 (73.8 s), 54 (67.9 s). Four of the six slowest are non-answers, which is the worst possible
  trade: rows 12 and 24 spend over two minutes to produce a template and a closure list.
- **Whether anything downstream of the four removed write paths still writes.** Row 49 no longer files
  a ticket, but I can only see the answer text; I cannot tell offline whether REP-7420E1 from run 2
  still sits in `user_reports`, and it would be visible if the demo shows the report store.

## New in run 3 that was not in run 2

- **Negative physical quantities printed as evidence** (row 99: "occupancy: -7.719",
  "co2: -260.986"), from the forecast path feeding the ranking dossier.
- **"The building's events store doesn't record that."** (row 80) — a new internal-store decline.
- **Internal schema design notes quoted verbatim to the reader** (rows 139 and 146 print an
  `rdfs:comment` written for developers, including "what the SYSTEM records it as" and "makes that
  disagreement unrepresentable").
- **The oldest reading labelled "Latest snapshot"** (row 120) — the BUG-520 shape, on a live sensor
  answer with a health verdict attached.
- **A day plan that invents which sessions are yours** (row 90) — an improvement over the run-2
  document decline, and a new way to be wrong.
- **Two flow figures that are physically impossible** presented as the basis of a recommendation
  (row 132: mean 14.2 m³/s, peak 292 m³/s).
- **The absence guard back after a run at zero** (rows 41, 70, 108), and the fetch-budget refusal at
  its highest count of the three runs (5).
