# Phase 0 run 6, labelled by hand (READER-6)

- input: `docs/phase0/phase0_run6.md.jsonl` — the same 147 questions via `/v1` streaming as
  facility01, 2026-09-18 ~06:40–07:35. Labels are in `docs/phase0/phase0_run6_read.jsonl`.
- earlier reads: `phase0_read.jsonl` (READER, run 1), `phase0_rerun_read.jsonl` (READER-2),
  `phase0_run3_read.jsonl` (READER-3), `phase0_run4_read.jsonl` (READER-4),
  `phase0_run5_read.jsonl` (READER-5). Verdicts, cause codes, C-classes and strictness follow
  `phase0_read.md` and READER-5's two standing precedents: a clarification counts as
  GOOD_DECLINE, and the reworded document decline counts as GOOD_DECLINE **only** where the
  registers it names are the relevant ones and the absence is real.
- I also kept READER-5's two refinements, because run 6 turns on both. A raw field name that
  appears once as a parenthetical gloss beside a plain-English label is a **secondary defect**;
  where it is the answer's own vocabulary it counts against the row — but, following READER-5's
  own treatment of run-5 row 4, a raw name **alone** does not fail an otherwise honest answer.
  Floor or kind *groupings* that contradict the record identifier in the same table are counted;
  room labels that disagree with the architect's drawings are not.
- every run-6 answer was read in full against its question and its written boundary. WEIRD =
  would read as broken, off-topic, incomplete, invented, or as an instruction to add data. A
  fluent answer untrue about the building is WEIRD. A decline is GOOD_DECLINE only when the
  building truly lacks the thing and the wording neither blames the reader, invites adding data,
  nor states an absence the same answer contradicts.
- offline only: no SPARQL, no live re-ask, no stack, no git. Where I say the building holds
  something I rely first on **another answer in this same run 6** — 35 of my 96 weird rows are
  contradicted by a run-6 answer or by their own printed table, and those are the safe ones —
  then on run 5's own answers, and last on READER's baseline SPARQL counts.
- the calibrated grader (`scripts/grade_answers_rubric.py --grade … --judge deterministic
  --asof 2026-09-18`) was run offline over this file for comparison only. It reproduced the
  **27.9%** I was given, exactly: `GOOD_ANSWER 37 · GOOD_DECLINE 69 · WEIRD 41`.

## Headline — six runs

| verdict | run 1 | run 2 | run 3 | run 4 | run 5 | run 6 |
|---|---:|---:|---:|---:|---:|---:|
| GOOD_ANSWER | 19 (12.9%) | 10 (6.8%) | 14 (9.5%) | 16 (10.9%) | 19 (12.9%) | **17 (11.6%)** |
| GOOD_DECLINE | 21 (14.3%) | 24 (16.3%) | 37 (25.2%) | 36 (24.5%) | 38 (25.9%) | **34 (23.1%)** |
| WEIRD | 107 (72.8%) | 113 (76.9%) | 96 (65.3%) | 95 (64.6%) | 90 (61.2%) | **96 (65.3%)** |

**Weird share: 72.8% → 76.9% → 65.3% → 64.6% → 61.2% → 65.3%.** WEIRD at high confidence only:
60 → 68 → 65 → 60 → 55 → **59**.

**Run 6 is the first run since run 2 to move backwards, and it gives back four of the five runs'
worth of ground run 5 gained.** Underneath the six-row swing, **39 rows moved: 6 improved, 11
regressed, 22 changed defect without changing verdict** — the most churn any reader has recorded,
and for the first time the regressions outnumber the improvements two to one.

The honest summary is narrower than the headline and more useful. **The five changes this run was
built to test all landed, and four of them worked.** The keyword census fell by more than half; the
declared-partition rule is clean wherever a partition is printed; the dead "say the register does
not cover this, and stop" branch is gone; the group-naming rule prints its records. But the
register narration underneath moved back to the run-4 failure — **reading a field's value as
something it does not say** — and that shape now carries 13 of the 27 C7 rows, more than the census
and the arithmetic together. Run 5 traded confident misreadings for correct computations narrated
wrongly; run 6 has traded them back.

## Transitions (run 5 → run 6)

| run 5 \ run 6 | GOOD_ANSWER | GOOD_DECLINE | WEIRD | total |
|---|---:|---:|---:|---:|
| GOOD_ANSWER | 12 | 2 | **5** | 19 |
| GOOD_DECLINE | 1 | 31 | **6** | 38 |
| WEIRD | 4 | 1 | 85 | 90 |

| change | rows | row numbers |
|---|---:|---|
| IMPROVED | 6 | 21, 45, 49, 95, 133, 145 |
| SAME_GOOD | 45 | 4, 5, 9, 19, 20, 39, 40, 50, 52, 62, 64, 65, 67, 68, 69, 71, 73, 74, 78, 79, 84, 85, 87, 94, 100, 101, 102, 105, 106, 107, 108, 113, 114, 118, 120, 124, 125, 126, 127, 130, 131, 137, 138, 140, 143 |
| SAME_WEIRD | 63 | 0, 1, 2, 6, 8, 14, 16, 23, 24, 25, 26, 29, 30, 31, 32, 33, 36, 41, 42, 46, 47, 48, 51, 53, 54, 55, 56, 57, 58, 59, 61, 66, 72, 77, 82, 83, 86, 88, 89, 90, 93, 96, 97, 98, 99, 103, 104, 109, 110, 111, 112, 115, 117, 119, 121, 122, 132, 135, 136, 139, 141, 142, 144 |
| CHANGED_STILL_WEIRD | 22 | 3, 10, 11, 12, 13, 17, 28, 34, 35, 43, 44, 60, 63, 70, 75, 76, 80, 81, 91, 128, 134, 146 |
| REGRESSED | 11 | 7, 15, 18, 22, 27, 37, 38, 92, 116, 123, 129 |

## Which of the five changes did what it was meant to

Checked by reading the answers, not by trusting the change list.

**1. The census is more than halved and is not gone.** One regex per row over all six files, so the
columns are like-for-like. The **word-level** census — a word or term named as the unit of absence
or presence ("contains the word X", "no field or value", "the terms …", a keyword table) — runs
**0 · 0 · 0 · 0 · 17 · 8**. It survives on rows **23, 26, 37, 38, 53, 61, 98, 107**, and on three of
those it is still the answer's own table:

- row 38: `| Concept | Number of records | Record IDs |` … `| **across** | 1 | CL-2026-023 |` — the
  question's preposition filed as a Concept found in a cost record. Run 5 declined this cleanly.
- row 98: "The only records that **contain the words** 'rooms', 'required' or
  'assistive-technology' are:" followed by the five hits, including APR-009 "Level 2 research
  laboratories".
- row 59: the table's own column headings are the question's two words — `| Workspace | Seat count
  | "options" | "meet" |` — with ticks under them.
- row 23 prints the search out loud: "it **notes the words** 'command', 'agency' and 'point' in
  certain records".
- row 37: "None of the fields in either register include the terms 'conflicts', 'interest', …
  '**approval**', '**payment**', or '**role**'" — under its own table row that reads "Approval
  decisions, dates, evidence type, and review dates".

**2. Group naming landed, and the counts it was meant to fix did not.** Row 36 — the row READER-5
opened this shape on — now names its records and still prints "High-criticality assets (**9
records**)" above a table of 8 and "Medium-criticality assets (**7 records**)" above a table of 5.
AEP-012, AEP-014 and AEP-021 appear in no table at all. That is worse than run 5's 9-over-8 and
7-over-6. Row 92 acquires the same defect fresh: "There are **10 rooms** that are both
*group-friendly* (**8 of them**) and *suitable for calls*", contradicted three lines later.

**3. Declared partitions are the cleanest win in this run.** Every partition I could check is
sound and names each record once: row 43 (12 = 6 + 4 + 1 + 1), row 49 (24 = 15 + 6 + 3), row 53 (28
= 18 + 1 + 8 + 1), row 64 (28 three different ways), row 108 (24 three different ways), row 118 (24
twice), row 97 (20), row 130 (5 + 2 of 16). Run 5's row 59 — WS-15, WS-16 and WS-01 filed under two
kinds each, 31 placements for 28 records — is gone, and row 61's table headed "open" holding a
restricted and a closed route is gone with it.

**4. The dead branch is gone and something worse took two of its rows.** No answer in run 6 says the
register does not cover this and stops on a word miss. But rows 80 and 88 now make the flat claim
instead: "**This building doesn't keep a record of that**" (80, for three alternative rooms, while
rows 53, 59 and 64 read 28 workspace records) and "**This building does not have workplace occupancy
sensors**" (88, while row 46 of this same run counts 257 Occupancy Count Sensors and row 58 ranks
194 spaces on occupancy). Row 88 took **124 seconds** to say it.

**5. The absence-note rule is the change that did not land.** An absence sentence still stands over
records the same answer prints on rows 11, 53, 59, 70, 111, 116 and 123, and over records another
run-6 answer prints on rows 15, 23, 26, 27, 33, 34, 35, 41, 54, 66, 88, 122, 129 and 139. Row 111 —
one of READER-5's eight regressions — now prints the three step-free drop-off routes **and still
closes** "the register contains no field that directly answers 'pushchair-friendly from the car
park,' so that specific question remains unanswered". Row 53 prints 18 bookable active rooms under
"No record in the register records the concepts of 'assigned', 'withdrawn', 'eligible alternative',
'room team', or 'consider'".

**What else moved, unasked.** The wording rules hold: *ontology* appears in no user-visible prose
for a second run, attribution reaches **zero** (run 5 had one), nothing says simulated or synthetic,
no TTL or upload instruction survives. Raw internal tokens fall 15 → **10** and raw camelCase field
names 13 → **6**. Against that: **"install / add sensors" advice rises 1 → 3** (rows 57, 88, 121),
and row 57 puts the forbidden instruction back in as many words — "consider installing a dedicated
facility and **recording it in the building model with appropriate tags and access-control
metadata**", to an accessibility user asking about a Changing Places toilet.

## Regressed rows (11)

### row 7 (AI-050, Accessibility, inclusion and well-being) — GOOD_DECLINE → WEIRD [C7], med
"**The register itself is the owner of the data it holds** … the owner of the register would be
responsible for reconciling that conflict." An invented governance answer to "which owner must
resolve each conflict", where run 5 scoped the decline in two sentences.
*Likely cause:* the narration answering a question the register cannot, from the register's own
existence.

### row 15 (BM-003, BMS-HVAC operators) — GOOD_DECLINE → WEIRD [C7], med
"nor does it contain any scheduled start-or-stop times against which a delay could be measured" —
rows 27 and 76 of this same run print "Approved window | Mon-Fri 07:00-19:00" for these same ten
regimes. **92.9 s.**
*Likely cause:* an absence asserted about a field the same register holds and two other answers read.

### row 18 (CT-066, Cleaning and caretaking) — GOOD_ANSWER → WEIRD [C7], med
"The register contains no other records that identify a different special-waste category." Run 5
listed six from this register — WCP-008 and WCP-010 laboratory glass, WCP-016 confidential
shredding — and run 6 shows two. The capacity, fill and threshold columns are new and good.
*Likely cause:* a narrowed selection narrated as an exhaustive one.

### row 22 (EC-069, Emergency coordinators) — GOOD_ANSWER → WEIRD [C7], low
"**Facts** — … Lift recall and entrapment / Waste and contamination containment / Roll call and
accounting / Media and enquiries": four coordination-function titles filed as facts to hand over at
a shift change, plus "Incident command declares FIRE_EVAC or LOCKDOWN" and a duplicated Head of
Security. The open actions, restrictions and the Lift B controller/maintainer contradiction survive
intact. **The row I could most easily be argued out of; a reader who passes it puts run 6 at 95.**
*Likely cause:* register category labels emitted as content.

### row 27 (SU-011, Energy, carbon and sustainability) — GOOD_ANSWER → WEIRD [C7], high
"Runs to 22:00 on published open days | **Frost protection (recorded as 'frost' in the register)**"
— a justification column invented for three exceptions. Row 15 of this same run prints their texts
and none mentions frost; run 5 said correctly that no justification is recorded.
*Likely cause:* the run-4 shape returning — a field's value read as something it does not say.

### row 37 (FP-064, Finance and procurement) — GOOD_DECLINE → WEIRD [C7], high
"None of the fields in either register include the terms … '**approval**', '**payment**', or
'**role**'", printed under its own table row "Approval decisions, dates, evidence type, and review
dates", while rows 3 and 5 give approval routes by role.
*Likely cause:* the census, contradicting the same answer's own table.

### row 38 (FP-046, Finance and procurement) — GOOD_DECLINE → WEIRD [C7], high
The keyword search printed as the answer table, with "**across**" as a Concept found in CL-2026-023.
Run 5 declined this with the 24 cost lines and their statuses.
*Likely cause:* the census as the answer.

### row 92 (PGT-044, Taught postgraduates) — GOOD_ANSWER → WEIRD [C7], med
"There are **10 rooms** that are both *group-friendly* (**8 of them**) and *suitable for calls*" and
"**10 rooms** meet the criteria of being group-friendly, suitable for calls, and labelled as meeting
spaces" — then "WS-27 and WS-28 are not". Run 5 gave eight and was right.
*Likely cause:* a group count computed over the union and narrated as the intersection.

### row 116 (Q060, no stakeholder) — GOOD_ANSWER → WEIRD [C7], high
"the **four bins on that floor**" — the table includes "Level 3 laboratory sharps (WCP-024)" under a
floor-2 question, a grouping the record's own name contradicts in the same row. Run 5 listed the
three floor-2 points correctly.
*Likely cause:* the group-membership listing widened past the filter it was listing.

### row 123 (Q481, Energy manager) — GOOD_DECLINE → WEIRD [C7], med
"the four tariff contracts that are **currently in force**", the first of which reads "Effective 31
Dec 2024 to **30 Dec 2025**"; and "**Boundary: not declared**" attached to a decline carrying no
energy figure. Run 5 named TAR-ELEC-2026 as the one in force today and carried no meter footer.
*Likely cause:* the date arithmetic that worked on five run-5 rows is not applied to tariff
effective ranges; the meter footer misfire (C6a) returns after two clean runs.

### row 129 (Q440, Facility manager) — GOOD_DECLINE → WEIRD [C9], high
"The register does not record any information about **drains**, jetting" — row 125 of this same run
names "WO-015 – Condensate drain clearance" from the same register. Run 5 found it and said plainly
that a clearance is not a jetting.
*Likely cause:* the drain reach phrase fires on one row and not the other, as READER-5 suspected
and could not resolve; run 6 shows it on the other side.

**Read the eleven together.** Six (7, 22, 27, 92, 116, 123) are the register narration asserting
something the register does not say or grouping records against their own identifiers. Three (15,
37, 38) are the census, still deciding rows. Two (18, 129) are a reach or a selection narrowing and
the narration claiming the narrow set is all there is. **None is a new capability failing. Every one
is narration.** That is the same conclusion READER-5 reached about a different set of rows, one run
later, which is the part worth acting on.

## (a) How many answers still carry census text, in any form

**Eight in its own words; nineteen counting the paraphrase.** Measured mechanically, one regex per
row, over all six files.

| form | r1 | r2 | r3 | r4 | r5 | r6 |
|---|---:|---:|---:|---:|---:|---:|
| **word-level census** ("contains the word X", "no field or value", "the terms …", "Word(s) found", a keyword table) | 0 | 0 | 0 | 0 | **17** | **8** |
| **plus the paraphrase** ("no field that records / specifies / directly answers X") | 1 | 1 | 8 | 6 | **34** | **19** |

The word-level form is new in run 5 and is **not** eliminated: rows 23, 26, 37, 38, 53, 61, 98, 107.
The paraphrase is older than run 5 (8 rows in run 3, 6 in run 4) and is not the thing the change
note was about; where it only scopes an honest decline I let it pass and counted it as a blemish —
rows 4, 5, 19, 20, 44, 55, 64, 79, 102, 125, 140. Where it states an absence the same answer or
another run-6 answer contradicts, it decided the row: 11, 15, 37, 53, 59, 61, 111.

**The census is still the single most load-bearing defect in this run.** It is the primary cause on
5 of my 11 regressions and on 11 of my 27 C7 rows.

## (b) Did each of the eight run-5 regressions recover? Individually

| row | question | run 5 → run 6 | recovered? |
|---|---|---|---|
| **23** EC-064 | open actions before the next decision point | WEIRD → **WEIRD** | **No.** The word search is still the answer — "it notes the words 'command', 'agency' and 'point' in certain records" — `decisionRequired` is still raw, and row 22 of this same run still lists two decisions and four open actions from this register. |
| **31** MC-040 | next manual test | WEIRD → **WEIRD** | **No.** Whole answer: "Thermographic survey." The fragment changed its two words (run 5: "Electrical inspection") and nothing else. |
| **36** FP-041 | funding priority | WEIRD → **WEIRD** | **No, and worse.** "High-criticality assets (9 records)" over 8 rows, "Medium-criticality (7 records)" over **5**; three of the 24 assets appear nowhere. Run 5 was 9-over-8 and 7-over-6. |
| **45** IT-078 | verified alternative location, path, capacity | WEIRD → **GOOD_ANSWER** | **Yes.** The closing census paragraph that denied continuity information for a communications room, four lines under a table naming the secondary comms room, is gone. The three verified provisions are correct and consistent with rows 21 and 43. |
| **59** AR-023 | seat near an exit | WEIRD → **WEIRD** | **No — defect swapped.** The double placement of WS-15, WS-16 and WS-01 is fixed (the partition rule working). The answer table is now headed with the question's own two words, `"options"` and `"meet"`, with ticks under them. |
| **61** PHD-061 | step-free route to supervision | WEIRD → **WEIRD** | **No — defect swapped.** The table headed "open" holding RTE-006 (restricted) and RTE-016 (closed) is gone. The answer now declines on "No other record in the register **contains the word 'avoids'** or a sensory level quieter than 'busy'", which run 5 read several routes against. |
| **111** Q216 | pushchair-friendly from the car park | WEIRD → **WEIRD** | **No — closer.** The three drop-off routes are now printed with their step-free status, which is the answer, and the closing sentence still says no field answers the question. Run 4 answered it "Yes" from these rows. |
| **133** Q224 | isolate water for the second-floor toilets | WEIRD → **GOOD_DECLINE** | **Yes.** "Incoming main stop valve SV-1" — the building's incoming main offered to a contractor as a second-floor isolation — is replaced by an honest search of the Asset Engineering Register. |

**Two of eight recovered. Three more (59, 61, 111) had their named sub-defect fixed and stayed
weird for a different reason in the same sentence.** That is the pattern of the run: the specific
thing was fixed, the lane that produced it was not.

## (c) Did C7 shrink, and what is its dominant sub-shape now?

**No. It grew, by more than any class has moved in six runs: 21 → 19 → 27.** Its share of the weird
set went 22.1% → 21.1% → **28.1%**. It has been the largest class by a factor of two in all six
runs and is now larger than the next two combined.

Eleven run-5 C7 rows left the class (3, 21, 43→changed, 44→changed, 45, 60, 63, 70, 75, 76, 111 —
of which 21 and 45 became good answers) and **seventeen entered it** (7, 10, 11, 15, 18, 22, 27,
36→stayed, 37, 38, 53, 55, 59, 72, 92, 116, 123).

**The sub-shape has changed completely, and it has changed back.** Run 5's C7 was *"compute
something correct, then write a sentence the computation contradicts"* — the arithmetic shape.
Run 6's is **"read a field's value as something it does not say"**, which is run 4's shape, and it
is now the majority:

| sub-shape | rows | n |
|---|---|---:|
| **A field's value read as something it does not say** | 3, 7, 10, 22, 27, 43, 44, 55, 60, 63, 70, 72, 123 | **13** |
| An absence stated over records the same answer or the same run shows | 11, 15, 18, 23, 26, 37, 38, 53, 59, 61, 111 | 11 |
| A stated count ≠ the rows printed, or a record in the wrong group | 36, 92, 116 | 3 |

Worked examples of the dominant shape, all checkable by eye:

- row 27 — three operating-regime exceptions ("runs to 22:00 on published open days") given
  "**Frost protection**" as their recorded justification.
- row 44 — 10 compliance checks marked **open** relabelled "the ones that are currently outstanding
  (i.e., '**current**' evidence)" to a safety officer.
- row 55 — all 24 **electrical isolation points** offered to an M&E engineer under the heading
  "Isolation points that should be trended" for a commissioning test.
- row 63 — a damper-position plant alarm served to professional-services staff as "**You are the
  responsible role for this alarm**", with no official channel, which the boundary requires.
- row 72 — "Lift B is currently out of service … **so** the alternative route RTE-006 is the only
  officially verified step-free option", where RTE-006's own alternative *is* Lift B and its status
  is *restricted*.
- row 60 — a mock viva room certified "**confidential**, accessible, quiet" from a record, where the
  boundary says acoustic measurement does not certify confidentiality, with "Bookable (so it can be
  reserved)" standing in for accessible.
- row 43 — a question about **verified impairments** answered with the services that are *not*
  impaired; the two that are (CP-005 overdue, CP-008 unverified) are named only in passing.
- row 123 — a tariff effective to 30 Dec 2025 listed among "the four tariff contracts **currently
  in force**".

**The gate this suggests is different from READER-5's and cheaper.** Hers — a stated count must
equal the rows printed, each record once per partition — is now largely satisfied and would catch 3
of 27. The one that would catch 13 is: **a conclusion the register does not state as a value must be
attributed, not asserted** — no "so", "therefore" or "this means" bridging a field to a judgement
the field does not carry. Combined with READER-5's third rule (no absence sentence about anything
the same answer has printed, which catches 11), the two together reach 24 of the 27.

## (d) The grader says 27.9%. What do I measure, and is its honest-decline bucket still inflating?

I measure **65.3%** (96 rows). The grader measures **27.9%** (41 rows). Re-run offline it reproduces
exactly: `GOOD_ANSWER 37 · GOOD_DECLINE 69 · WEIRD 41`.

| grader bucket | run 4 | run 5 | run 6 |
|---|---:|---:|---:|
| GOOD_ANSWER | 52 | 28 | **37** |
| GOOD_DECLINE | 42 | 75 | **69** |
| WEIRD | 53 | 44 | **41** |

| I say \ grader says | GOOD_ANSWER | GOOD_DECLINE | WEIRD |
|---|---:|---:|---:|
| GOOD_ANSWER | 8 | 9 | 0 |
| GOOD_DECLINE | 8 | 20 | 6 |
| WEIRD | 21 | **40** | 35 |

Exact agreement **63/147 = 42.9%**; weird-or-not **80/147 = 54.4%**. READER-5 measured 63 and 87 on
run 5, READER-4 74 and 89 on run 4. **Weird-or-not agreement has now fallen for the fourth run in a
row and is below 55% for the first time.**

**Yes, the honest-decline bucket is still inflating, and it is now inflating worse per row.** It
shrank from 75 to 69 as the census wording halved — the mechanism READER-5 identified is real and
visible. But **40 of its 69 rows are rows I call weird (58%), up from 36 of 75 (48%)**, and 19 of
those 40 are declines of something another run-6 answer demonstrably holds: row 15 (approved windows
rows 27 and 76 print), row 23 (the open actions row 22 lists), row 33 (the inspections row 44 reads),
row 34 (the handover records row 22 names), row 35 (the 269 illuminance sensors row 46 counts), row
41 (the defective hazard controls row 42 reads), row 54 (the unproven isolations row 11 names), row
66 (the Room 1.06 readings rows 58, 99 and 117 read), row 88 (the 257 occupancy sensors row 46
counts), row 122 (the 16 bookings row 110 reads), row 129 (WO-015, which row 125 names), row 139
(the 3,248 sensors row 46 counts).

**The new thing this run is the other bucket.** The grader's GOOD_ANSWER count rose 28 → 37, and
**21 of its 37 are rows I call weird** — including the four fetch-budget refusals that answer nothing
("That question reaches 296 sensors": rows 0, 16, 25, 134), both closure-shortcut lists (6, 24), the
five bare coordination-function labels (104), the vehicle-counting answer to a waste-weight question
(109) and the funding table that drops three of 24 assets (36). Length and table shape now score as
an answer. A gate reading "weird fell again" would have passed a run in which five good answers
became confident misreadings.

**Six rows the grader calls WEIRD and I call good** (40, 50, 52, 71, 94, 133). All six are the
document-decline template its DOCUMENT_CATCHALL rule penalises on sight; I checked each and the
registers named are the relevant ones and the absence is real. Row 133 is the one where that rule
and I now agree in direction and disagree in sign — it is a recovery from a dangerous fragment.

**My reading: the grader is measuring shape, and the shape improved while the content did not.**
The single change that would close most of the gap is unchanged from what READER-3, READER-4 and
READER-5 all asked for, and run 6 makes it more specific: give it the register rows, and let it check
(1) that no absence sentence names a thing the same answer has printed, (2) that every stated count
equals the rows shown, and (3) **that every causal or evaluative claim quotes a field value that
carries it**. Those three would flag 24 of my 27 C7 rows and 9 of my 11 regressions.

## Per-class counts across six runs (primary class of each WEIRD row)

| class | name | r1 | r2 | r3 | r4 | r5 | r6 | run-6 rows |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C7 | Register narration misreads statuses, dates and fields, or invents conclusions | 18 | 17 | 20 | 21 | 19 | **27** | 3, 7, 10, 11, 15, 18, 22, 23, 26, 27, 36, 37, 38, 43, 44, 53, 55, 59, 60, 61, 63, 70, 72, 92, 111, 116, 123 |
| C11 | Catch-all 'documents do not answer this' for out-of-scope or planning requests | 6 | 12 | 5 | 7 | 9 | **12** | 8, 12, 75, 80, 82, 86, 89, 90, 103, 112, 144, 146 |
| C8 | Register chosen on a bare word; the lane declines with unrelated register statistics | 14 | 8 | 7 | 8 | 10 | **10** | 1, 30, 34, 41, 42, 48, 76, 97, 98, 110 |
| C9 | The building holds the data and no lane reaches it (false absence) | 9 | 8 | 8 | 8 | 7 | **8** | 32, 33, 35, 54, 66, 88, 122, 129 |
| C2 | Fetch-budget refusal for whole-building, multi-measurement questions | 2 | 4 | 5 | 4 | 4 | **4** | 0, 16, 25, 134 |
| C4 | Metadata/discovery fallback: schema as answer, false absence, add-data | 6 | 14 | 9 | 9 | 4 | **4** | 13, 57, 121, 139 |
| C5 | 'I understood the question but could not put an answer together' | 4 | 6 | 6 | 4 | 6 | **4** | 2, 51, 81, 83 |
| C13 | Deliberation lane: blocked phrases, out-of-band rankings, routes reaching ranking | 5 | 4 | 4 | 4 | 4 | **4** | 58, 99, 117, 119 |
| C12 | Open-domain questions answered from general model knowledge, unlabelled | 4 | 4 | 4 | 4 | 4 | 4 | 135, 136, 141, 142 |
| C3 | Narration hygiene: attribution, raw field names, internal provenance | 6 | 5 | 5 | 6 | 3 | **3** | 28, 77, 115 |
| C10 | Document lane returns a bare fragment or an internal token as the whole answer | 4 | 5 | 6 | 4 | 6 | **3** | 31, 93, 104 |
| C19 | Assorted shortcut misroutes (operator, building figures, host metrics) | 5 | 6 | 3 | 4 | 3 | **3** | 14, 46, 47 |
| C22 | Recommend lane produces generic advice not grounded in the building | 4 | 4 | 4 | 4 | 5 | **3** | 56, 109, 132 |
| NEW | closure-shortcut: a closure list answers anything mentioning closures | 0 | 2 | 2 | 2 | 2 | 2 | 6, 24 |
| C18 | Report lane answers a non-report question and recommends metadata edits | 1 | 1 | 1 | 2 | 1 | **2** | 91, 96 |
| C14 | Compare/trend fallback dead end ('no measured series') | 2 | 1 | 1 | 2 | 0 | **1** | 17 |
| C16 | Anomaly question answered from user reports, UUIDs as place names | 1 | 1 | 1 | 1 | 1 | 1 | 29 |
| C17 | Future or hypothetical questions answered by the current-reading lane | 2 | 1 | 2 | 1 | 2 | **1** | 128 |
| C1 | Absence guard rewrites a valid answer on a substring match | 3 | 0 | 3 | 0 | 0 | 0 | — |
| C6a | Shelf-life and meter footers on answers they do not describe | 4 | 4 | 0 | 0 | 0 | 0 | — (footer misfires on 123 and 132 counted under their primary class) |
| C6b | Deictic referent resolved to an arbitrary sensor or declined | 4 | 4 | 0 | 0 | 0 | 0 | — |
| C15 | 'You can add it — upload a TTL' as the answer | 2 | 0 | 0 | 0 | 0 | 0 | — |
| C20 | Referent gate treats a descriptive phrase as a named space | 1 | 1 | 0 | 0 | 0 | 0 | — |
| NEW | question-filed-as-report (write side effect) | 0 | 1 | 0 | 0 | 0 | 0 | — |
| **total** | | **107** | **113** | **96** | **95** | **90** | **96** | |

Three classes rose: **C7 19 → 27**, **C11 9 → 12** (the catch-all is now the second-largest class and
five of its twelve decline with registers the same run uses to answer other questions: 12, 80, 82,
86, 89), and **C14 0 → 1** — "I have no measured series for the requested sensor or zone", which
reached zero in run 5, is back on row 17. Three fell: **C10 6 → 3**, **C22 5 → 3**, **C5 6 → 4**.
C4, C12, C13, C19, C3 and the deictic and absence-guard classes are unchanged, which for C12 is now
six runs of the same four rows.

### Phrases counted mechanically across all 147 answers, six runs

| phrase | r1 | r2 | r3 | r4 | r5 | r6 |
|---|---:|---:|---:|---:|---:|---:|
| the word *ontology* anywhere in the answer | 36 | 41 | 37 | 37 | **0** | **0** |
| user attribution ('you provided' / 'records you have' / 'you retrieved') | 7 | 11 | 3 | 3 | 1 | **0** |
| 'simulated' / 'synthetic' / 'fake' | 3 | 1 | 0 | 0 | 0 | 0 |
| TTL / upload instruction | 5 | 0 | 0 | 0 | 0 | 0 |
| 'add or update it' | 6 | 0 | 0 | 0 | 0 | 0 |
| 'The room holds N records' | 9 | 0 | 0 | 0 | 0 | 0 |
| "I can't complete that request as asked" (absence guard) | 3 | 0 | 3 | 0 | 0 | 0 |
| 'Evidence time: unknown' | 4 | 4 | 0 | 0 | 0 | 0 |
| meter footer 'Boundary: not declared' | 7 | 10 | 2 | 2 | 1 | **2** |
| recheck footer 'Switch if:' | 9 | 10 | 2 | 2 | 2 | 2 |
| **keyword census, word-level** | 0 | 0 | 0 | 0 | **17** | **8** |
| **census incl. 'no field that records X'** | 1 | 1 | 8 | 6 | **34** | **19** |
| access-control warning ('Check you can use it first') | 0 | 0 | 0 | 0 | 3 | 3 |
| 'documents do not answer this' / 'I searched …' | 6 | 19 | 12 | 13 | 14 | **17** |
| 'I understood the question but could not put an answer together' | 4 | 6 | 5 | 4 | 5 | **3** |
| 'That question reaches N sensors' | 2 | 5 | 5 | 4 | 4 | 4 |
| "couldn't render the chart" | 2 | 2 | 2 | 2 | 2 | 2 |
| deictic clarification ('Which room do you mean…') | 1 | 0 | 5 | 5 | 5 | 5 |
| internal token (IRI, snake_case, CamelCase class, raw table name) | 35 | 16 | 18 | 15 | 15 | **10** |
| raw camelCase field name | 14 | 5 | 14 | 15 | 13 | **6** |
| **'install / add sensors' advice** | 1 | 0 | 0 | 1 | 1 | **3** |
| 'consult other sources' pointer | 4 | 7 | 4 | 10 | 6 | **7** |

The owner's standing rule is broken on **zero** answers for attribution and on **ten** for naming
internal machinery: `【continuity_provision_register】` as a suffix to the whole answer (93),
`hazard_controls` / `coshh_and_lev` / "Model version: 2026.9" (77), `Ablutions_Room` twice and "No
**triples** reference a Changing Places facility" (57), `Temperature_Sensor` "a general pollutant
supertype" (46), `occupancy_data` / `noise_data` / `database1_floors04` in the dossiers (58, 99, 117,
119), `policy_inference_individual_pattern` (131), `Energy_Meter_Floor0` (145), `AHU_runtime` (128),
and the schema author's own design note printed verbatim to a user — "what the SYSTEM records it as
… collapsing them into a single stream field makes that disagreement unrepresentable when the
disagreement IS the answer" (139). Row 132 prints the prompt's own instruction as a heading: "### 3-6
actionable recommendations based on the existing sensors".

## What remains, ranked by how visible it would be to a supervisor asking live

| rank | class | rows | severity | why it shows |
|---:|---|---:|---|---|
| 1 | **C7** register narration, now mostly a field read as something it does not say | 27 | P1 | The largest class in every run and now the largest it has ever been. Worst on the day: row 63 (professional-services staff told "**You are the responsible role for this alarm**" about a damper), row 55 (24 electrical isolators offered as commissioning trend points), row 72 (a step-free alternative recommended that depends on the lift the reader says is unavailable, and is itself recorded *restricted*), row 27 (an open-day extension justified by "frost protection"), row 36 (a funding priority list that drops three of 24 assets and misstates two of its three group sizes), row 60 (a mock viva certified confidential, which the boundary forbids in as many words). Thirteen of the twenty-seven bridge a field to a judgement with a "so" or a "therefore". |
| 2 | **the census + C9 + C4** — the building holds it and the answer denies it | 8 + 4 + the 11 census rows | P1 | What a supervisor asking two related questions sees. Nineteen rows are contradicted by another run-6 answer: row 88 says "**This building does not have workplace occupancy sensors**" while row 46 counts 257 and row 58 ranks 194 spaces on them; row 139 says "the only sensor-related entities listed are Waste Collection Points" in a building whose own row 46 counts 3,248; row 129 denies all drain data while row 125 names WO-015 Condensate drain clearance; row 35 denies lighting data while row 30 prints "300 lux maintained"; row 15 denies scheduled start times while rows 27 and 76 print them. |
| 3 | **C11 + C10** the catch-all and the fragment | 12 + 3 | P2 | C11 is up 9 → 12 and is now the second-largest class. Five of the twelve decline with registers the same run uses elsewhere (12, 80, 82, 86, 89); "Book me a hotel" still ends in "I searched Room Bookings" (112). The fragment is down to three but includes the worst single line of the run: "Lecture capture and streaming (Room 4.44 — Server Room)**【continuity_provision_register】**" (93) and "Thermographic survey." (31). |
| 4 | **C13** deliberation lane | 4 | P1 | Still the most impressive-looking output and the most likely to be demonstrated. Row 58 now says plainly "**The readings don't separate these spaces** … the order between them is not something these readings support", warns the reader cannot enter a lab — and then closes "**Primary:** Room 5.54 — Research Laboratory". Row 99 recommends a room at **74 dB** as a "calm, relatively quiet place" against a stated 30-70 dB band, unflagged, while flagging occupancy and PM2.5 out-of-band correctly. Row 117 separates its top three by 0.09 °C and calls the choice stable. Row 119 still gives an exclusion reason as the reason for zero candidates, over a dossier of twelve rooms with values. |
| 5 | **C8** bare-word register capture | 10 | P2 | Flat at 10, and now carrying date errors: row 110 gives "the next confirmed booking **after today (18 September 2026)**" as one dated **9 September 2026**, inside a room-booking answer to a loading-bay question the waste register answers in rows 18 and 19. Row 98's answer is still the keyword hits. Row 30 relabels the chilled-water regime "a **fault**" by word match. |
| 6 | **C2 + C5** the two dead-end templates, and their cost in seconds | 4 + 4 | P2 | Unchanged in wording and now the most expensive rows in the run. Row 81 spends **198.2 s** to say "I could not match **resources** or **priority** to anything this building records" — for the incident recovery-order question rows 21, 43 and 45 have the continuity register for. Four rows are told "That question reaches N sensors" (0, 16, 25, 134), one of them (134) having arrived there from a false absence, which is an improvement in truth and none in use. |
| 7 | **C22 + C18** recommend and report lanes | 3 + 2 | P1 | Down from 6, and the two worst are still whole answers. Row 109 answers how to allocate shared-vehicle **weights** by counting cars with the parking-free sensor and gives no weight figure. Row 132 answers "is tap water free" with leak-monitoring advice from flow rates under a heading that prints the prompt's own instruction. Rows 91 and 96 answer a study plan and an enrolment question with a sensor Summary Report recommending "Declare units for the 66 un-summarised sensors". |
| 8 | **C4 + C19** schema-as-answer and shortcut misroutes | 4 + 3 | P2 | Row 14 still answers a per-control ownership and testing question with "**Abacws Building** — operated by: **Cardiff University Estates**." in 0.5 s, sixth run running. Row 46's Brick note still calls `Temperature_Sensor` "a general pollutant supertype". Row 121 serves a Brick class definition as the answer and advises installing a "filter-size sensor". Row 57 puts the add-data instruction back. |
| 9 | **C3** narration hygiene | 3 | P1 wording | Attribution is at zero for the first time, and row 13's replacement reads "The building's records, **as represented in the building's records**, do not contain…" — a string substitution visible in the output. Rows 28 and 115 still close "feel free to share them". Row 77 still prints three registers' provenance fields. |
| 10 | **C12** open-domain prose | 4 | P3 | Unchanged across all six runs: autism, ozone, glare sensors, CO₂ — all general knowledge, none marked as not from the building, and row 142 still does not use any of the building's 280 CO₂ sensors. |
| 11 | **closure shortcut + C16 + C17 + C14** | 2 + 1 + 1 + 1 | P2 | Rows 6 and 24 are answered by the identical three-closure list for a sixth run — and row 6 now takes **28.5 s** to print it. Row 29 still prints "d 7baf 689-b 028-5ba 7-91a 4-686a 66265659" as a place name. Row 17 brings back "I have no measured series". |

**If one thing is fixed before the demo, it is not the census.** The census is now eight rows, and
halving it again buys three. **Fix the bridge**: forbid a causal or evaluative clause ("so", "therefore",
"this means", "you are") that is not carried by a printed field value. That is 13 of my 27 C7 rows,
6 of my 11 regressions, and the rows a supervisor will notice because they are confidently wrong
rather than merely empty. **If two, apply READER-5's absence rule** — no absence sentence may name a
thing the same answer has already printed — which is 11 more and finishes rows 53, 59, 111 and 116
where the substance is already on the page.

**Latency, which no reader has graded.** Run 6 took **59.0 minutes** (run 5: 55.3), median **13.1 s**
— the fastest median of the six runs — but the tail is the worst since run 1: **10 answers over 60 s**
(run 5: 7), and the four slowest all produce nothing usable: row 81 at **198.2 s** (the template),
row 75 at **190.9 s** (a calibration question searched in the Accessible Route Register), row 96 at
**146.6 s** (a sensor report to a timetabling team), row 88 at **124.0 s** (a false absence about
occupancy sensors). Three and a half minutes for a wrong register is worse in a live demo than a
wrong answer in twelve seconds.

## New in run 6 that was not in run 5

- **Zero user attribution**, for the first time — and the substitution is visible: "as represented in
  the building's records" (13).
- **Declared partitions that hold**, on eight rows, with every record placed once (43, 49, 53, 64,
  97, 108, 118, 130).
- **A closure linked to the routes it interrupts**, correctly anchored to today: "Scheduled closure
  (Floor 1) … active from 08:00 to 17:00 on 18 September 2026" over the five Level-1 routes (85).
  Run 5 said closures were not linked to routes.
- **A readiness-triage answer that says what an absence does and does not mean**: "No AV readiness
  record names Room 5.52, so its teaching technology **has not been assessed — which is not the same
  as it working**" (95).
- **The run-5 inverted CO₂ claim corrected** inside the same recommendation set, which now also
  declares its six meters and closes "without adding new equipment" (145).
- **A ranking that says its own readings cannot separate the candidates** — and then names a primary
  anyway (58).
- **`【continuity_provision_register】`** appended to a fragment in CJK brackets (93) — a new shape of
  internal leak.
- **The prompt's own instruction as a user-visible heading**: "### 3-6 actionable recommendations
  based on the existing sensors" (132).
- **A past date given as the next event**, twice: "the next confirmed booking after today (18
  September 2026) … on 9 September 2026" (110) and an expired tariff among those "currently in
  force" (123).
- **"This building does not have workplace occupancy sensors"** (88) and **"the only sensor-related
  entities listed are Waste Collection Points"** (139) — two flat, confident, false statements about
  the building's instrumentation, each contradicted by row 46 of the same run.
- **The meter footer returns** after two clean runs, on a tariff decline with no energy figure (123).

## Things I could not tell

- **Whether run 6 is worse than run 5 or differently wrong.** Six rows of weird share on one sample at
  non-zero temperature is inside the churn every reader since READER-3 has measured — 39 rows moved
  to produce a net of six. What I will stand behind is narrower: **the wording rules are done and
  stayed done; the census halved; the partition rule works; and the register narration moved back to
  the run-4 shape, which is the shape that produces confidently wrong sentences rather than empty
  ones.** Eleven regressions against six recoveries is the first time any reader has seen that ratio.
- **Rows 22, 111 and 9 are the ones I could most easily be argued out of.** Row 22's handover is
  substantively useful and only its "Facts" section is broken — a reader who passes it puts run 6 at
  95. Row 111 prints the three routes that answer the question and only its closing sentence denies
  them; a reader who passes it puts run 6 at 94. Row 9 I *passed* at low confidence despite a
  backticked list of five raw field names being a whole section of the answer, on READER-5's own
  precedent that a raw name alone does not fail an honest decline; a stricter reader puts run 6 at 97.
- **Rows 19, 20, 64, 102, 107, 113, 120, 140 and 145 I passed at low confidence**, each with a named
  blemish in its evidence line. Applied strictly — counting the census paraphrase, the consult-elsewhere
  pointer and the redundant recommendation as failures — run 6 is 105, and the comparison with run 5
  would need re-reading under the same strictness to mean anything.
- **Row 18 rests on run 5's answer, not on a run-6 one.** Run 5 listed WCP-008, WCP-010 and WCP-016 as
  special-waste points from this register; run 6 shows two and says there are no others. If run 5 was
  the wrong reading, row 18 is a good answer and run 6 is 95.
- **Rows contradicted only by READER's baseline SPARQL**: 42 (the AED first-aid point), 48 (15 permits),
  56 and 75 (1,929 calibrated points), 93 and 98 (22 AV readiness, 12 AV equipment), 104 (25 service
  schedules), 122 (the Room 1.06 projector), 132 (13 drinking-water points). I ran no query. The 35
  rows contradicted inside run 6 are the safe ones.
- **Whether rows 15, 27 and 76 disagree or are reading different fields.** Row 15 says the
  operating-regime register holds no scheduled start-or-stop times; rows 27 and 76 print approved
  windows for the same ten regimes. Two answers in the same run cannot both be right, and I cannot
  tell offline which field each read.
- **Rows 70 and 72 still disagree about how many routes use a lift** — 15 versus 10, from the same
  register, minutes apart. READER-5 recorded the same disagreement at 10 versus 8. The numbers moved;
  the disagreement did not.
- **Whether row 43 and row 21 agree.** Row 21 makes CP-003 high-criticality; row 43 files it under
  "none" — but those are different fields (criticality versus verification state), so this may be the
  first run in which they are consistent. I could not confirm it offline.
- **Row 75 took 190.9 seconds to search the Accessible Route Register for a calibration question.**
  Run 5 reached the calibration data on this row for the first time in five runs and reported a round
  "1 000" sensors. Run 6 loses the reach entirely. I cannot tell whether the reach was withdrawn or
  whether the register selection simply lost a coin toss.
- **Latency.** Not graded, and it should be. Over 60 s in run 6: rows 81 (198.2 s), 75 (190.9 s), 96
  (146.6 s), 88 (124.0 s), 51 (93.7 s), 15 (92.9 s), 91 (86.4 s), 94 (85.1 s), 99 (81.6 s), 57 (71.2 s).
  Row 94 spent 85.1 s on a one-sentence document decline; row 87 spent 37.7 s on two sentences; row 79
  spent 34.2 s on two. The time is not going into the answers that are long.
