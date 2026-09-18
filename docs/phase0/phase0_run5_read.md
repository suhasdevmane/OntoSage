# Phase 0 run 5, labelled by hand (READER-5)

- input: `docs/phase0/phase0_run5.md.jsonl` — the same 147 questions via `/v1` streaming as
  facility01, 2026-09-18 ~05:00–06:30. Labels are in `docs/phase0/phase0_run5_read.jsonl`.
- earlier reads: `phase0_read.jsonl` (READER, run 1), `phase0_rerun_read.jsonl` (READER-2,
  run 2), `phase0_run3_read.jsonl` (READER-3, run 3), `phase0_run4_read.jsonl` (READER-4,
  run 4). Verdicts, cause codes, C-classes and strictness follow `phase0_read.md`, and I have
  kept the two standing precedents: a clarification counts as GOOD_DECLINE, and the reworded
  document decline counts as GOOD_DECLINE **only** where the registers it names are the
  relevant ones and the absence is real.
- every run-5 answer was read in full against its question and its written boundary. WEIRD =
  would read as broken, off-topic, incomplete, invented, or as an instruction to add data. A
  fluent answer that is untrue about the building is WEIRD. A decline is GOOD_DECLINE only
  when the building truly lacks the thing and the wording neither blames the reader nor
  invites more data.
- the owner's standing rule was applied as written: no user-visible text may say simulated,
  synthetic or fake, name internal machinery or raw field names, or call the building's own
  data something the reader supplied. **Where a raw field name appears once as a parenthetical
  gloss beside a plain-English label I recorded it as a secondary defect; where it is the
  answer's own vocabulary (an IRI, a snake_case block, a heading) it counts against the row.**
  That line is stated here because run 5 makes it matter on about twenty rows.
- room labels that disagree with the architect's drawings were **not** counted against any
  answer. Floor or kind *groupings* that contradict the record identifier in the same table
  are a different defect and are counted.
- offline only: no SPARQL, no live re-ask, no stack, no git. Where I say the building holds
  something I rely either on READER's read-only counts or — better — on **another answer in
  this same run 5** that shows the record. Rows 11, 23, 26, 33, 43, 53, 54, 61, 66, 70, 72,
  82, 86, 88, 89, 111, 121, 122 and 134 are each contradicted by a different answer in their
  own run, and those are the safe ones.
- the calibrated grader (`scripts/grade_answers_rubric.py --grade … --judge deterministic
  --asof 2026-09-18`) was run offline over this file for comparison only. It reproduced the
  **29.9%** I was given, exactly.

## Headline — five runs

| verdict | run 1 | run 2 | run 3 | run 4 | run 5 |
|---|---:|---:|---:|---:|---:|
| GOOD_ANSWER | 19 (12.9%) | 10 (6.8%) | 14 (9.5%) | 16 (10.9%) | **19 (12.9%)** |
| GOOD_DECLINE | 21 (14.3%) | 24 (16.3%) | 37 (25.2%) | 36 (24.5%) | **38 (25.9%)** |
| WEIRD | 107 (72.8%) | 113 (76.9%) | 96 (65.3%) | 95 (64.6%) | **90 (61.2%)** |

**Weird share: 72.8% → 76.9% → 65.3% → 64.6% → 61.2%.** WEIRD at high confidence only:
60 → 68 → 65 → 60 → **55**.

Five rows. That is the movement, and it is the largest since run 3 — but underneath it **22
rows moved: 14 improved, 8 regressed**, more churn than run 4 produced and in the same
proportion. Composition: **57 good rows, of which 38 are declines and 19 are answers**. Run 5
matches run 1's answer count for the first time, and it is the only run where the good-answer
count rose while the decline count also rose.

The honest summary is: the register lane got quantitatively better at arithmetic and dates and
qualitatively worse at knowing when to stop declining. Nearly every gain and nearly every loss
in this run comes from the same eight computations.

## Transitions (run 4 → run 5)

| run 4 \ run 5 | GOOD_ANSWER | GOOD_DECLINE | WEIRD | total |
|---|---:|---:|---:|---:|
| GOOD_ANSWER | 12 | 0 | **4** | 16 |
| GOOD_DECLINE | 1 | 31 | **4** | 36 |
| WEIRD | 6 | 7 | 82 | 95 |

| change | rows | row numbers |
|---|---:|---|
| IMPROVED | 14 | 4, 9, 19, 22, 49, 69, 71, 78, 85, 92, 102, 113, 120, 129 |
| SAME_GOOD | 43 | 5, 7, 15, 18, 20, 27, 37, 38, 39, 40, 50, 52, 62, 64, 65, 67, 68, 73, 74, 79, 84, 87, 94, 100, 101, 105, 106, 107, 108, 114, 116, 118, 123, 124, 125, 126, 127, 130, 131, 137, 138, 140, 143 |
| SAME_WEIRD | 57 | 0, 1, 6, 8, 13, 14, 16, 24, 25, 29, 30, 35, 41, 42, 46, 47, 48, 54, 55, 56, 57, 58, 60, 63, 70, 72, 77, 80, 82, 83, 88, 89, 90, 93, 95, 96, 97, 98, 99, 103, 104, 109, 110, 112, 115, 117, 119, 121, 122, 132, 135, 136, 139, 141, 142, 145, 146 |
| CHANGED_STILL_WEIRD | 25 | 2, 3, 10, 11, 12, 17, 21, 26, 28, 32, 33, 34, 43, 44, 51, 53, 66, 75, 76, 81, 86, 91, 128, 134, 144 |
| REGRESSED | 8 | 23, 31, 36, 45, 59, 61, 111, 133 |

## Which of the night's changes did what it was meant to

Checked by reading the answers, not by trusting the change list.

**The wording change is the cleanest win in five runs, and it is total.** The word *ontology*
appears in user-visible prose (excluding the source chip) in **22 → 18 → 8 → 9 → 0** answers.
Zero. The chip itself reads `Building model` on every row that carries one. Attribution of the
building's data to the reader — *"you provided" / "records you have" / "you retrieved" / "that
were provided"* — falls **8 → 11 → 3 → 3 → 1**; the single survivor is row 13, "as represented
in the building model **you provided**". No answer says simulated, synthetic or fake; none
contains a TTL or upload instruction; none says "add or update it".

**The date arithmetic works, and it is new.** Row 113 computes overdue inspections "as of
Friday 18 September 2026" and lists ten assets with their due dates; row 69 volunteers that
"the emergency-lighting test due 2026-09-01 is already past"; row 123 says the electricity
tariff "in force today (and tomorrow) is TAR-ELEC-2026"; rows 18 and 19 anchor the waste
next-due dates to today and separate the overdue point from the authorised ones. The
"next collection 8 September, asked 17 September" shape READER opened C7 with is gone from
every row where I could check it.

**The contradiction computation earns its place twice.** Row 108 reports "WCP-007 is labelled
'General waste' but its waste stream is 'Mixed recycling'", which is exactly the disagreement
the register's own schema note says it exists to make representable. Row 22 reports "the
controller reports ready while the maintainer's record says otherwise" about Lift B. Both are
findings no earlier run produced.

**The floor grouping is fixed.** Rows 53 and 92 carried "rooms 4.11–4.13 under Level 3" since
run 1 (READER-4 called it the same shape twice). Neither row groups by floor wrongly now, and
row 92's stated count matches its table.

**The access-control warning on rankings is real and it is good.** Three answers (58, 99, 117)
now carry "Check you can use it first … each of those is a laboratory or an office someone
else holds, not a room anyone may walk into. … ask me for a room that is open to everyone and
I will rank only those." Row 99 also carries the new out-of-band warning: "**Every pm25
reading above sits above the 0 to 15 range used to weigh it**". Row 117 no longer blocks on
*pregnant*; it drops it with a stated assumption. Three of the four C13 defects READER named
have a mitigation in the text. **The ranking underneath is unchanged**, so all three rows still
recommend a room the same answer then says the reader cannot use.

**The census re-wording did not hold, and this is the finding of the run.** The census was
rewritten to say it *bounds what may be claimed and is NOT a reason to decline*. It is used as
a reason to decline on **13 of the 23 answers it appears in** (rows 1, 11, 23, 26, 30, 33, 34,
41, 45, 48, 61, 70, 97, 98). The wording itself is new to run 5 and appears in **23 of 147
answers, up from 0 in every earlier run**:

- row 23: "*No record contains the word 'open' or 'action' in any field, so the register does
  not record any open actions*" — row 22 of the same run lists five.
- row 11: "**Drainage** | 0 | Not recorded — no field or value contains the word 'drainage'" —
  row 125 lists WO-015 Condensate drain clearance.
- row 45: "The term 'communications room' does not appear as a field name or value in any
  record, so no continuity information is available for a communications room" — four lines
  under its own table, which names the "secondary comms room" as the alternative.
- row 70: "Doors, toilets … or 'temporary' are not mentioned in any field or value" — five
  lines below its own row "**Temporary alternatives** | Two records describe alternatives".
- row 98: the keyword search is printed *as the answer table*, with a column headed "Word(s)
  found" and APR-009 "Level 2 research laboratories" matched on **required**.
- rows 64, 78, 92, 118 list the question's own adverbs as absent fields: "the register does not
  contain any information about … 'strongly', 'justify'"; "does not record any fields named
  'considering'".

Where the census only trims a good answer (rows 4, 18, 20, 69, 105, 107, 140) I let it pass and
counted it as a blemish. Where it produces a false absence contradicted by the same answer or
by another answer in the same run, it decides the row.

**"Field names in plain words" landed on two rows and not on sixteen.** Rows 34 and 69 use a
"Field (plain wording)" table, which is exactly right. Raw field names remain the answer's own
vocabulary on rows 3, 4, 21, 23, 33, 36, 44, 48, 53, 60, 70, 76, 77, 88, 111 and 122, and row
28 prints `bldg:coordination/CF-01 … CF-14` and
`http://ontosage.org/capabilities#criterionState` to an energy manager.

**Reach moved routes, and the narration lost them again.** Row 61 now reads the accessible-route
register instead of refusing (run 4 declined by design); row 9 reads all 21 circulation records
where run 4 said "no measured series"; row 85 answers the interrupted-route question correctly
and consistently with rows 26, 70 and 72; row 129 finds WO-015 for a drain question. But row 61
then heads a table "Step-free routes that are **open**" and puts a restricted and a closed route
in it, and row 111 — which run 4 answered from the same rows — declines.

**Two of the five LANES changes did not fire at all.** "Plan my day" (row 90) and "plan
tomorrow" (row 91) still end in a document catch-all and an empty-sensor notice; neither asks
which sessions are the asker's. And recommendations still propose installing sensing on rows
96 ("Deploy additional sensors or data collection points"), 132 ("consider installing one"),
139 ("request that such sensors be installed") and 88 ("Check for occupancy or people-counting
sensors") — though the two worst run-4 instances (rows 56 and 145) are gone.

**Claim binding is credited with nothing, as instructed.** No answer in run 5 carries a
claim-binding artefact in its text.

## Regressed rows (8)

### row 23 (EC-064, Emergency coordinators) — GOOD_ANSWER → WEIRD [C7], high

Q: Which command decisions, agency requests and open actions need coordination before the next
decision point?

- **run 4 (14.4 s):** a five-row table — "CF-03 Refuge point communication | provisional | Head
  of Security | degraded | Any evacuation with a registered PEEP holder | **Yes**" — with role,
  system state and activation criterion for each.
- **run 5 (13.1 s):** "**Open actions** — *No record contains the word 'open' or 'action' in any
  field, so the register does not record any open actions.*" then "**none of the command
  decisions or agency requests require coordination before the next decision point**".
- **likely cause:** the census used as a decline. The five `decisionRequired = true` records are
  still found and listed, but a word search over field names is allowed to assert that a
  register with five open coordination items records no open actions — and row 22 of this same
  run lists them.

### row 31 (MC-040, External maintenance contractors) — GOOD_DECLINE → WEIRD [C10], high

Q: Which next manual test would best distinguish the remaining plausible fault locations?

- **run 4 (5.3 s):** "I searched Asset Engineering Register, Maintenance Log; they are the
  closest material and none of them contains the answer."
- **run 5 (20.5 s):** whole answer — "Electrical inspection".
- **likely cause:** the document lane's minimum-shape check did not hold on this row. Run 3 had
  the same two-word fragment; run 4 fixed it; run 5 has it back, and took four times as long.

### row 36 (FP-041, Finance and procurement) — GOOD_ANSWER → WEIRD [C7], high

Q: Which assets should receive funding first when criticality, condition, risk and whole-life
cost are combined?

- **run 4 (45.5 s):** all 24 assets with "Criticality | Condition (recordStatus) | Value band",
  the proxies declared.
- **run 5 (23.8 s):** "**high** — 9 assets" above a table of **8**; "**medium** — 7 assets"
  above a table of **6**; AEP-009 and AEP-014 appear in no table at all. Value band is dropped
  and reported as "whole-life cost — **no** — not recorded".
- **likely cause:** the count census computed the group totals correctly (9 + 8 + 7 = 24) and
  the narration then wrote tables that do not match them. This is the exact failure the census
  was built to prevent, occurring one layer downstream of it.

### row 45 (IT-078, IT and server infrastructure) — GOOD_ANSWER → WEIRD [C7], low

Q: If the primary server room or core-network area is unavailable, which services have a
verified alternative location, path and capacity?

- **run 4 (23.1 s):** the three verified provisions with location, path and capacity.
- **run 5 (35.2 s):** the same three, correct — then "The term 'communications room' does not
  appear as a field name or value in any record, so **no continuity information is available
  for a communications room**", four lines under a table whose own second column reads "Level 3
  riser cupboard (**secondary comms room**)".
- **likely cause:** the census appended to an answer it had no business commenting on. This is
  the row I could most easily be argued out of: the substance is intact and only the closing
  paragraph is wrong.

### row 59 (AR-023, People with accessibility requirements) — GOOD_DECLINE → WEIRD [C7], med

Q: I need a seat near an exit. Which authorised seating options meet that without obstructing
circulation?

- **run 4 (9.7 s):** "The records do not indicate whether a seat is near an exit … They do
  record the workspace kind, access classification, seat count…" — two sentences, no table.
- **run 5 (18.1 s):** a table in which **WS-15 and WS-16 appear under both "Bookable room" and
  "Computer lab"**, and **WS-01 under both "Common room" and "Open study"** — 31 placements
  under "All 28 records".
- **likely cause:** the value-split computation applied to a multi-valued column and the
  narration presented the result as a partition. Rows 53 and 64 of this same run give the
  correct partition (18 / 8 / 1 / 1).

### row 61 (PHD-061, PhD students) — GOOD_DECLINE → WEIRD [C7], med

Q: I need a step-free route to supervision that avoids the busiest and noisiest areas.

- **run 4 (18.5 s):** "**You asked about a route, and I answer by comparing spaces — so I won't
  hand you a room instead.** … Name the two places."
- **run 5 (51.5 s):** a table headed "Step-free routes that are **open** and have a moderate
  sensory level" containing RTE-006 (status *restricted*) and RTE-016 (status *closed*); the
  recommendation is RTE-001, the drop-off-to-reception arrival route; and RTE-011 is offered as
  the "changeover" record over a comment about tactile paving and handrails.
- **likely cause:** REACH worked and the narration did not. The route register is now reached,
  and then a keyword hit on "changeover" and a header that contradicts its own status column
  turn it into a worse answer than the honest refusal.

### row 111 (Q216, Visitor) — GOOD_ANSWER → WEIRD [C7], high

Q: Is the building pushchair-friendly from the car park?

- **run 4 (15.6 s):** "Yes – the building has step-free, pushchair-friendly routes from the
  car-park drop-off … RTE-001 | RTE-010 | RTE-012 … All three routes are marked step-free."
- **run 5 (10.0 s):** "The register does **not** record whether the building is
  pushchair-friendly from the car park" — above its own "15 routes are step-free" and
  "'Accessible drop-off — Senghennydd Road north' – 3 routes (RTE-001, RTE-010, RTE-012)".
- **likely cause:** the census again. "Pushchair" is not a recorded word, so the question is
  declined over the three rows that answer it, which the same answer then prints.

### row 133 (Q224, Contractor) — GOOD_DECLINE → WEIRD [C10], high

Q: Where can I isolate the water supply for the second-floor toilets?

- **run 4 (3.8 s):** "I searched Asset Engineering Register; … the building's records do not
  cover this."
- **run 5 (7.4 s):** whole answer — "Incoming main stop valve SV-1".
- **likely cause:** the same document-lane fragment as row 31, and the fragment is the
  building's incoming main offered to a contractor as a second-floor isolation.

**Read the eight together.** Six of them (23, 36, 45, 59, 61, 111) are the new register
computations or the new reach, and in every one the computation is correct and the sentence
built on it is not. Two (31, 133) are the document fragment returning after run 4 had removed
it. **None is a new capability failing to work; every one is a new capability working and being
narrated wrongly.** That is a different and more tractable problem than the one READER-4
reported, where the same register was simply read differently on a different night.

## Per-class counts (primary class of each WEIRD row)

| class | name | run 1 | run 2 | run 3 | run 4 | run 5 | run-5 rows |
|---|---|---:|---:|---:|---:|---:|---|
| C7 | Register narration misreads statuses, dates and fields, or invents conclusions | 18 | 17 | 20 | 21 | **19** | 3, 11, 21, 23, 26, 36, 43, 44, 45, 53, 55, 59, 60, 61, 63, 70, 72, 75, 111 |
| C8 | Register chosen on a bare word; the lane declines with unrelated register statistics | 14 | 8 | 7 | 8 | **10** | 1, 30, 34, 41, 42, 48, 76, 97, 98, 110 |
| C11 | Catch-all 'documents do not answer this' for out-of-scope or planning requests | 6 | 12 | 5 | 7 | **9** | 8, 80, 82, 86, 89, 90, 103, 112, 144 |
| C9 | The building holds the data and no lane reaches it (false absence) | 9 | 8 | 8 | 8 | **7** | 32, 33, 54, 66, 88, 122, 134 |
| C5 | 'I understood the question but could not put an answer together' | 4 | 6 | 6 | 4 | **6** | 2, 10, 35, 51, 83, 95 |
| C10 | Document lane returns a bare fragment or an internal token as the whole answer | 4 | 5 | 6 | 4 | **6** | 12, 31, 93, 104, 133, 146 |
| C22 | Recommend lane produces generic advice not grounded in the building | 4 | 4 | 4 | 4 | **5** | 56, 81, 109, 132, 145 |
| C2 | Fetch-budget refusal for whole-building, multi-measurement questions | 2 | 4 | 5 | 4 | **4** | 0, 16, 17, 25 |
| C4 | Metadata/discovery fallback: the ontology named, schema as answer, false absence | 6 | 14 | 9 | 9 | **4** | 13, 57, 121, 139 |
| C13 | Deliberation lane: blocked phrases, out-of-band rankings, routes reaching ranking | 5 | 4 | 4 | 4 | **4** | 58, 99, 117, 119 |
| C12 | Open-domain questions answered from general model knowledge, unlabelled | 4 | 4 | 4 | 4 | 4 | 135, 136, 141, 142 |
| C19 | Assorted shortcut misroutes (operator, building figures, host metrics) | 5 | 6 | 3 | 4 | **3** | 14, 46, 47 |
| C3 | Narration hygiene: attribution, raw field names, internal provenance | 6 | 5 | 5 | 6 | **3** | 28, 77, 115 |
| NEW | closure-shortcut: a closure list answers anything mentioning closures | 0 | 2 | 2 | 2 | 2 | 6, 24 |
| C17 | Future or hypothetical questions answered by the current-reading lane | 2 | 1 | 2 | 1 | **2** | 91, 128 |
| C16 | Anomaly question answered from user reports, UUIDs as place names | 1 | 1 | 1 | 1 | 1 | 29 |
| C18 | Report lane answers a non-report question and recommends metadata edits | 1 | 1 | 1 | 2 | **1** | 96 |
| C14 | Compare/trend fallback dead end ('no measured series') | 2 | 1 | 1 | 2 | **0** | — |
| C1 | Absence guard rewrites a valid answer on a substring match | 3 | 0 | 3 | 0 | 0 | — |
| C6a | Shelf-life and meter footers on answers they do not describe | 4 | 4 | 0 | 0 | 0 | — |
| C6b | Deictic referent resolved to an arbitrary sensor or declined | 4 | 4 | 0 | 0 | 0 | — |
| C15 | 'You can add it — upload a TTL' as the answer | 2 | 0 | 0 | 0 | 0 | — |
| C20 | Referent gate treats a descriptive phrase as a named space | 1 | 1 | 0 | 0 | 0 | — |
| NEW | question-filed-as-report (write side effect) | 0 | 1 | 0 | 0 | 0 | — |
| **total** | | **107** | **113** | **96** | **95** | **90** | |

Two classes fell hard: **C4 9 → 4** (the *ontology* rewrite, and it is the only class whose
fall is fully explained by a landed change) and **C3 6 → 3** (attribution). **C14 reaches
zero** — "I have no measured series for the requested sensor or zone" appears nowhere, though
rows 17 and 9 got there by different routes, one of them into C2. Four classes rose: **C8 8 →
10, C11 7 → 9, C10 4 → 6, C5 4 → 6** — the census-decline, the document catch-all and the
fragment.

### Phrases counted mechanically across all 147 answers (secondary defects included)

One regex per row over all five files, so the columns are like-for-like.

| phrase | run 1 | run 2 | run 3 | run 4 | run 5 |
|---|---:|---:|---:|---:|---:|
| the ontology named in user-visible prose (source chip excluded) | 22 | 18 | 8 | 9 | **0** |
| user attribution ('you provided' / 'records you have' / 'you retrieved' / 'that were provided') | 8 | 11 | 3 | 3 | **1** |
| 'simulated' / 'synthetic' / 'fake' | 3 | 1 | 0 | 0 | 0 |
| TTL / upload instruction | 5 | 0 | 0 | 0 | 0 |
| 'add or update it' | 6 | 0 | 0 | 0 | 0 |
| 'The room holds N records' | 7 | 0 | 0 | 0 | 0 |
| "I can't complete that request as asked" (absence guard) | 3 | 0 | 3 | 0 | 0 |
| 'Evidence time: unknown' | 4 | 4 | 0 | 0 | 0 |
| meter footer 'Boundary: not declared' | 7 | 10 | 2 | 2 | **1** |
| recheck footer 'Switch if:' | 9 | 10 | 2 | 2 | 2 |
| **keyword-census wording ('no field or value contains the word…')** | 0 | 0 | 0 | 0 | **23** |
| **access-control warning ('Check you can use it first')** | 0 | 0 | 0 | 0 | **3** |
| 'documents do not answer this' | 6 | 19 | 12 | 13 | **14** |
| 'I understood the question but could not put an answer together' | 4 | 6 | 5 | 4 | **5** |
| 'That question reaches N sensors' | 2 | 5 | 5 | 4 | 4 |
| "couldn't render the chart" | 2 | 2 | 2 | 2 | 2 |
| 'Which room do you mean…' (deictic clarification) | 0 | 1 | 7 | 7 | 7 |
| internal IRI / class / schema token | 4 | 7 | 8 | 8 | **5** |

The owner's standing rule is broken on **one** answer for attribution (13) and on roughly
sixteen for naming internal machinery: `bldg:coordination/CF-01` and
`http://ontosage.org/capabilities#criterionState` (28), `record_type` / `maps_to
hazard_controls` / `source_system` (77), `bldg:waste/WCP-001` with the developer note verbatim
(139), `Air_Quality_Level_Sensor` (56), `Ablutions_Room` / `Restroom` (57),
`Particulate_Matter_Sensor` / `TVOC_Level_Sensor` (46), "timeseries UUIDs and stored-at
references" (88), `dependsOnSpace` (21), `decisionRequired` (23), `visitorEntrance` / `routeFrom`
(33, 111), `accessClassification` / `suitableForCalls` (60, 122), `servedByLift` / `liftStatus`
/ `assistanceContact` (70), `isBookable` and "as listed in the **query results**" (53),
`operatingWindow` / `occupiedSetpoint` (76), `tagInMaintenance` / `commissionedDuty` /
`inspectionIntervalDays` (36, 48), `policy_inference_individual_pattern` (131), and the
snake_case role values `facility_manager` / `safety_officer` (69). That is down from run 4 in
kind but not in count, and the census sentence has replaced the ontology sentence as the
commonest way an answer tells the reader what the system is made of.

## Did the C7 register-narration class actually shrink?

**No. It fell from 21 to 19 — two rows, 9.5% — and its share of the weird set is flat: 22.1%
→ 21.1%. It remains the largest class by a factor of two, as it has been in all five runs.**

That is the honest headline for the wave that targeted it. The membership tells a more useful
story than the count:

- **11 run-4 C7 rows left the class** (2, 4, 10, 19, 22, 34, 51, 78, 86, 92, 120). Six became
  good answers or declines (4, 19, 22, 78, 92, 120) and five moved to another failure — row 2
  and row 10 to the "could not put an answer together" template, row 34 to a wrong-register
  decline, row 51 to a self-referential refusal, row 86 to the document catch-all. **Trading a
  confident misreading for a content-free template is not a fix; it is a different row in a
  different column.**
- **Nine rows entered C7** (23, 36, 44, 45, 59, 61, 75, 111 and, by a changed defect, 43). Six
  of those nine are new-computation rows, and five of the eight regressions are among them.

The sub-shape has changed completely, and that is the part worth acting on. Run 4's C7 was
*"read the register and assert something it does not say"* — `recordStatus = completed` read as
a lecture confirmation, idle plant diagnosed "not healthy", a display truncation reported as an
incomplete record. Almost all of those are gone. Run 5's C7 is **"compute something correct,
then write a sentence the computation contradicts"**:

| row | the computation | the sentence built on it |
|---|---|---|
| 36 | high 9 · continuity 8 · medium 7 = 24 | three tables holding 8, 8 and 6 |
| 21 | 12 critical records | "a summary of the **12** records" over 9 rows, one marked *low* |
| 43 | criticality by record | high 7 + medium 3 + low 1 = 11 of 12; CP-003 vanishes, and row 21 calls it high |
| 59 | kind counts per record | WS-15, WS-16 and WS-01 filed under two kinds each, 31 placements for 28 records |
| 23 | five `decisionRequired = true` | "the register does not record any open actions" |
| 45 | verified alternatives found | "no continuity information is available for a communications room" |
| 70 | two temporary alternatives listed | "'temporary' … not mentioned in any field or value" |
| 111 | 15 step-free routes, 3 from the drop-off | "does not record whether the building is pushchair-friendly from the car park" |
| 26 | 16 route records reached | "**Foot** — mentioned only in one record" as the whole answer |

Every one of those is checkable by eye inside a single answer, which makes it both the most
visible remaining defect and the easiest to gate: **the count in the prose must equal the rows
printed, every record must appear in exactly one group of a partition, and the census may not
emit an absence sentence about anything the same answer has already shown.**

## What remains, ranked by how visible it would be to a supervisor asking live

| rank | class | rows | severity | why it shows |
|---:|---|---:|---|---|
| 1 | **C7** register narration, now mostly self-contradiction | 19 | P1 | Nine of the nineteen contradict themselves inside one answer (table above). Worst on the day: row 36 (a funding priority list that drops two of the 24 assets and misstates two of its three group sizes), row 55 (electrical **isolation points** offered to an M&E engineer as the points to trend for a commissioning test, and two of five "assets that mention *test*" quote comments containing no such word), row 60 (a mock viva certified "accessible" because the room is *bookable*, and confidential because a record "records the word confidential" — which the boundary forbids in as many words), row 63 (a plant damper alarm at "VAV Box, Floor 5, West Wing" served to professional-services staff as "the latest authoritative instruction for **your** location and role"), row 111 (a visitor told the pushchair routes are not recorded, over the three routes). |
| 2 | **C9 + C4 + the census declines** the building holds it and the answer denies it | 11 + the 13 census rows | P1 | Nineteen rows are contradicted **by another answer in the same run**, which is what a supervisor asking two related questions sees: row 121 says the records hold nothing about fan-coil units while rows 125 and 129 both name "WO-015 — Condensate drain clearance, **Fan Coil Unit Room 5.03**"; row 88 says "there is no data on occupancy … or any sensor-based timeseries" while rows 58, 99 and 119 rank 194 spaces on occupancy; row 134 says to "look for HVAC or temperature sensors that are not listed in the building model" while rows 46 and 47 count 296 of them; row 54 says no asset record shows what must be reconciled while row 11 names three with no isolation proven-on date; row 86 declines from the two registers row 22 uses to report three overdue checkpoints; row 122 says no record holds availability for today while rows 78 and 110 read 16 bookings with times. |
| 3 | **C13** deliberation lane | 4 | P1 | Still the most impressive-looking output and therefore the most likely to be demonstrated. The new access warning makes every ranking end by telling the reader they cannot use the room it just recommended (58, 99, 117) — better than a silent wrong answer, but it reads as the system arguing with itself. Row 117 separates its top three by **0.03 °C** and calls the choice "stable under ±25% preference-weight changes", then tells an overheating pregnant occupant that "**No independent backup exists** … Every alternative shares: Floor5. That is a single point of failure worth raising with the estate team." Row 119 still gives an exclusion reason as the reason for zero candidates, over a dossier listing twelve rooms with occupancy values. Row 99 answers "next Wednesday after 2 p.m." with a 24-hour-ahead forecast and a five-minute recheck. |
| 4 | **C11 + C10** the catch-all and the fragment | 9 + 6 | P2 | Up from 7 and 4. "Book me a hotel" still ends in "I searched Room Bookings" (112). Four of the nine catch-alls decline with registers the same run uses to answer other questions (80, 82, 86, 89). And the fragment is back: "Electrical inspection" (31), "Incoming main stop valve SV-1" (133), "CF-03, CF-05, CF-10, CF-13" (12), "Lecture capture and streaming – Room 4.44 — Server Room." (93). Two of those are regressions from run-4 declines. |
| 5 | **C8** bare-word register capture | 10 | P2 | Up from 8, and now with the census attached: a fairness-of-timetabling question answered "no field name or value in the 20 access-permission-group records includes the words *proposed*, *fairness*, *checks*" (97); an AV-approval question answered with a table headed "**Word(s) found**" (98); a first-aid question declined in one line without naming the register, with an AED record held (42); a fire-impairment question answered from equipment O&M handovers (41); a loading-bay readiness question given two-thirds of the room-booking register before being declined (110). |
| 6 | **C22** recommend lane | 5 | P1 | Row 109 answers how to allocate shared-vehicle **weights** with "Use daylight cues from the *illuminance* sensor … reduce the weight" and gives no weight figure of any kind. Row 81 hands incident leaders a recovery order "based on common building-operations practice" built from user-report categories, while rows 21, 43 and 45 read twelve continuity records with criticality and ride-through minutes. Row 145 is otherwise the best-grounded recommendation set in five runs and contains "**High CO₂ levels often mean over-ventilation**", which is backwards. Row 132 still reasons from water flow rates to whether tap water is free. |
| 7 | **C2 + C5** the two dead-end templates | 4 + 6 | P2 | Six questions are told the building "measures air quality, carbon monoxide, co2 and damper position and keeps Interval record, Access event and Timetabled session records" (2, 10, 35, 83, 95 — none of which is about any of those; row 35 is about lighting in a building with 269 illuminance sensors). Four are told "That question reaches N sensors" (0, 16, 17, 25), and row 17 arrived there from a different template. The lane names are gone from the template, which is a real improvement in wording and none in content. |
| 8 | **C19 + C16 + C18** shortcut misroutes | 3 + 1 + 1 | P2 | Row 14 still answers a per-control ownership and testing question with "**Abacws Building** — operated by: **Cardiff University Estates**." in 0.6 s. Rows 46 and 47 answer network-connectivity and host-CPU questions with the sensor census and the building figures; row 46's Brick note now calls `Temperature_Sensor` "a general pollutant supertype". Row 29 still prints "d 7baf 689-b 028-5ba 7-91a 4-686a 66265659" as a place name to a sustainability team. Row 96 still answers an enrolment question with a sensor report recommending "Deploy additional sensors". |
| 9 | **C3** narration hygiene | 3 | P1 wording | Down to three rows but the machinery moved rather than left: row 28 prints two IRIs, row 77 prints three registers' internal provenance fields verbatim, row 115 invites the reader to supply data. Add the sixteen rows listed above where a raw field name is the answer's vocabulary. |
| 10 | **C12** open-domain prose | 4 | P3 | Unchanged across five runs: autism, ozone, glare sensors, CO₂ — all from general knowledge, none marked as not from the building, and row 142 still does not use any of the building's 280 CO₂ sensors. |
| 11 | **C17 + closure shortcut** | 2 + 2 | P2 | Rows 6 and 24 are still answered by the identical three-closure list, five runs running. Row 128 answers a what-if with "0.57 HR (latest reading)", though it now says plainly that comfort cannot be inferred from it. |

**If one thing is fixed before the demo, fix the census's licence to decline.** Thirteen rows
turn on it, six of the eight regressions are downstream of it, and the fix is a single rule the
change note already contains in writing: the census bounds what may be claimed and is not a
reason to decline. **If two, add the arithmetic self-check** — a stated count must equal the
rows printed, and a partition must place each record once. That is rows 21, 36, 43 and 59, all
four checkable by eye in the answer itself.

## The grader says 29.9%. What do I measure, and where do I disagree?

I measure **61.2%** (90 rows). The grader measures **29.9%** (44 rows). I re-ran it offline to
check the number I was given: `GOOD_ANSWER 28 · GOOD_DECLINE 75 · WEIRD 44 · weird share
29.9%`. It reproduces exactly.

**The gap has widened, and the reason is specific and new.** Run 4 → run 5 the grader falls
36.1% → 29.9%, 6.2 points. I move 64.6% → 61.2%, 3.4 points. But look at what moved inside the
grader's own totals, which is the more interesting number:

| grader bucket | run 4 | run 5 |
|---|---:|---:|
| GOOD_ANSWER | 52 | **28** |
| GOOD_DECLINE | 42 | **75** |
| WEIRD | 53 | **44** |

**Thirty-three answers moved into the grader's honest-decline bucket in one night.** That is
the census wording. "The register does not record X" is the shape its HONEST_DECLINE rule is
built to reward, and it now appears on 23 answers plus the reworded document decline on 14
more. The grader is measuring a phrase, and the phrase got commoner. Of its 75 honest
declines, **36 are rows I call weird**, and 13 of those are declines of something the same
answer or another answer in the same run demonstrably holds.

| I say \ grader says | GOOD_ANSWER | GOOD_DECLINE | WEIRD |
|---|---:|---:|---:|
| GOOD_ANSWER | 3 | 16 | 0 |
| GOOD_DECLINE | 8 | 23 | 7 |
| WEIRD | 17 | 36 | 37 |

Exact agreement **63/147 = 42.9%**; weird-or-not **87/147 = 59.2%**. READER-4 measured 74 and
89 on run 4, so agreement fell again, for the third run in a row.

- **53 rows the grader calls good and I call weird**, and 36 of them are honest-decline calls.
  This is the whole gap and it is qualitatively different from the gap the earlier readers
  found. Until run 5 the disagreement was that the grader reads SHAPE and cannot check content
  — it cannot know that 23 rows is not 18, or that rooms 4.11–4.13 are not on floor 3. That is
  still true (it cannot see that row 36 drops two assets, that row 59 files three workspaces
  twice, that row 55 offers isolators as trend points, that row 60 reads *bookable* as
  *accessible*). **But the new failure is that a decline is now the cheapest way to score well
  on it, and the system has learned the phrasing.** A gate reading "weird fell 6 points" would
  have passed a run in which four good answers became register-shaped declines of data the
  building holds (23, 36, 45, 111).
- **7 rows the grader calls WEIRD and I call good** (40, 50, 52, 67, 69, 71, 94). Five are the
  document-decline template, which its DOCUMENT_CATCHALL rule penalises on sight; I checked
  each and the registers named are the relevant ones and the absence is real. Row 67 it
  penalises because the decline "cites a register sharing no term with the question" — the
  public-event register is the right register for an open-day question. **Row 69 is the one it
  is right about and I let pass**: it flags the snake_case values `facility_manager` and
  `safety_officer`, which are raw values under the owner's rule. I left it good because they sit
  inside an otherwise exemplary plain-word field table; a stricter reader would put run 5 at 91.
- **We still share one blind spot.** Neither of us graded latency. Run 5 took **55.3 minutes**
  for 147 questions (run 4: 63.9), median **15.6 s** (run 4: 16.0), and only **7 answers took
  over 60 s** (run 4: 11). It is the fastest run recorded. But **five of the seven slowest
  produce nothing usable**: row 13 at **126.5 s** (a false absence with the run's only
  attribution), row 11 at **109.7 s** (the drainage denial), row 81 at **108.0 s** (generic
  advice from general practice), row 2 at **79.9 s** ("I could not match *corridor-related* to
  anything this building records"), row 89 at **75.4 s** (the document catch-all). Two minutes
  for a false absence is worse in a live demo than a wrong answer in twelve seconds.

**My reading: the grader's 29.9% is no longer a floor, it is a phrase count.** As an instrument
it is unchanged and honest about what it measures, but the system has moved into its blind spot
rather than out of it. The single change that would close most of the gap is the one READER-3
and READER-4 both named and it is now more specific: give it the register rows, and let it
check that every stated count equals the rows shown, that every record appears once in a
partition, **and that no absence sentence names a thing the same answer has already printed**.
That last rule alone would flag 9 of my 19 C7 rows and 6 of the 8 regressions.

## New in run 5 that was not in run 4

- **The keyword census as user-visible text**, on 23 answers and 0 in every earlier run — the
  largest single textual change in five runs, and the source of six of the eight regressions.
  At its worst it is the whole answer: row 98's table has a column headed "**Word(s) found**".
- **The access-control warning on rankings** (58, 99, 117): "each of those is a laboratory or
  an office someone else holds, not a room anyone may walk into … ask me for a room that is
  open to everyone and I will rank only those." Correct, well-worded, and it does not change
  the ranking it qualifies.
- **The out-of-band warning**: "Every pm25 reading above sits above the 0 to 15 range used to
  weigh it" (99). Correct and new.
- **Correct date arithmetic against today**, in five places (18, 19, 69, 113, 123), including
  ten overdue inspections computed from last-visited plus interval and labelled "as of Friday
  18 September 2026".
- **A recorded contradiction surfaced as a finding**: "WCP-007 is labelled 'General waste' but
  its waste stream is 'Mixed recycling'" (108), and the Lift B controller/maintainer
  disagreement (22).
- **The system describing its own retrieval as the reason for not answering**: "What I read for
  that question was **the description of those records rather than the records themselves**, so
  I would rather not answer from it" (51) — honest, and it reads as broken.
- **A partition that files the same record under two kinds** (59) — a new arithmetic shape.
- **A Brick note misapplied**: `Temperature_Sensor` described as "a general pollutant
  supertype" whose children measure water temperature (46).
- **`http://ontosage.org/capabilities#criterionState` printed as a raw URL** to an energy
  manager (28) — the first full IRI-with-scheme in any run.
- **Isolation points offered as trend points** for a commissioning test (55).
- **"High CO₂ levels often mean over-ventilation"** (145), inside the best-grounded
  recommendation set of the five runs.
- **Zero occurrences of the word *ontology* in user-visible prose**, for the first time.

## Things I could not tell

- **Whether run 5 is better than run 4 or just differently wrong.** Five rows of weird share on
  one sample at non-zero temperature is inside the churn every reader since READER-3 has
  measured: 22 rows moved to produce a net of 5. The claim I will stand behind is narrower and
  I think more useful: **the wording rules landed completely and are safe to consider done; the
  register computations landed correctly and their narration did not; and the weird share has
  fallen 3.4 points in a run where four good answers were converted into confident declines of
  data the building holds.**
- **Rows 45, 113 and 64 are the ones I could most easily be argued out of.** Row 45 is a
  correct three-row answer with one wrong closing paragraph; a reader who let it pass puts run
  5 at 89 weird. Row 113 I called GOOD_ANSWER at low confidence because it states its own
  substitution openly ("the register does not contain a field that records whether a plant item
  is currently operating outside its schedule. What it does record are inspection due dates")
  and computes the dates correctly — but "(and therefore may be out of schedule)" is a false
  bridge, and a stricter reader puts run 5 at 91. Row 64's quietest-period breakdown accounts
  for 24 of its own 28 records and disagrees with row 92 about which periods those are; I left
  it good at low confidence because the breakdown is not claimed to be exhaustive.
- **Row 69 the grader flags and I passed**, for the snake_case role values `facility_manager`
  and `safety_officer`. Applied strictly, run 5 is 91 weird.
- **Row 131** still prints "Denied for every role" and
  "_Policy: `policy_inference_individual_pattern`_", which is internal wording under the owner's
  rule. All four earlier readers passed this row, so I did too. Applied strictly, 92.
- **Rows where the building's holdings come from READER's SPARQL rather than this run.** Rows
  1, 30, 42, 48, 56, 75, 93, 95, 98, 104, 122 and 132 rest on the baseline counts (AVReadiness
  22, AVEquipment 12, CleaningTask 30, ServiceSchedule 25, FirstAidPoint, Permit 15, 1,929
  calibrated sensors, 13 drinking-water points). I ran no query. The nineteen rows contradicted
  by another run-5 answer are the safe ones.
- **Row 75 is the first answer in five runs to reach the calibration data**, and it reports "All
  **1 000** sensors were calibrated by a manufacturer span check". A round thousand where
  READER counted 1,929 points carrying `calibratedOn` looks like a row budget narrated as a
  building total, but I cannot prove that offline, so I labelled it WEIRD at med confidence on
  that ground alone and note that the reach itself is a genuine advance.
- **Rows 21, 43 and 45 disagree with each other about the continuity register.** Row 21 makes
  CP-003 high-criticality; row 43 does not list it at all and its groups total 11 of 12. Row 45
  and row 43 give the same status counts. I could not tell offline which reading is right, only
  that two answers in the same run cannot both be.
- **Rows 70 and 72 disagree about how many routes use Lift A** (10 versus 8). Same register,
  same run, ninety seconds apart.
- **Whether the 'operating-condition, remedial-work and drain' reach phrases fired.** Row 129
  now finds WO-015 where run 4 denied all drain data, and row 49 reads the work-order register
  cleanly — but row 11 still reports "no field or value contains the word 'drainage'", so I can
  see the reach on two rows and its absence on a third, and cannot tell offline whether that is
  the phrase list or the register selection.
- **Latency.** Not graded. Over 60 s in run 5: rows 13 (126.5 s), 11 (109.7 s), 81 (108.0 s),
  99 (84.9 s), 2 (79.9 s), 89 (75.4 s), 145 (68.6 s). Row 2 spent 79.9 s to say it could not
  match two words; run 4 spent 34.8 s on the same row and was also wrong.
