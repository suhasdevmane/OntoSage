# Phase 0 run 4, labelled by hand (READER-4)

- input: `docs/phase0/phase0_run4.md.jsonl` — the same 147 questions via `/v1` streaming as
  facility01, 2026-09-18 ~01:15–02:45. Labels are in `docs/phase0/phase0_run4_read.jsonl`.
- earlier reads: `phase0_read.jsonl` (READER, run 1), `phase0_rerun_read.jsonl` (READER-2,
  run 2), `phase0_run3_read.jsonl` (READER-3, run 3). Verdicts, cause codes and classes follow
  `phase0_read.md` exactly, and I have kept READER-3's two precedents: a clarification counts
  as GOOD_DECLINE, and the reworded document decline counts as GOOD_DECLINE **only** where the
  registers it names are the relevant ones and the absence is real.
- every run-4 answer was read in full against its question and its written boundary. WEIRD =
  would read as broken, off-topic, incomplete, invented, or as an instruction to add data. A
  fluent answer that is untrue about the building is WEIRD. A decline is GOOD_DECLINE only when
  the building truly lacks the thing and the wording neither blames the reader nor invites more
  data.
- the owner's standing rule was applied as written: no user-visible text may say simulated,
  synthetic or fake, name internal machinery, or call the building's own data something the
  reader supplied.
- room labels that disagree with the architect's drawings were **not** counted against any
  answer (known, deliberately held until after the demo). Floor *groupings* that contradict the
  room number in the same table are a different defect and are counted (rows 53, 92).
- offline only: no SPARQL, no live re-ask, no stack, no git. Where I say the building holds
  something I rely either on READER's read-only counts or — better — on **another answer in
  this same run 4** that shows the record. Rows 43, 66, 80, 81, 82, 85, 88, 92, 110, 116, 122 and
  129 are each contradicted by a different answer in their own run, and those are the safe ones.
- the calibrated grader (`scripts/grade_answers_rubric.py --judge deterministic`) was re-run
  offline over this file for comparison only. It reproduced the 36.1% I was given.

## Headline — four runs

| verdict | run 1 | run 2 | run 3 | run 4 |
|---|---:|---:|---:|---:|
| GOOD_ANSWER | 19 (12.9%) | 10 (6.8%) | 14 (9.5%) | **16 (10.9%)** |
| GOOD_DECLINE | 21 (14.3%) | 24 (16.3%) | 37 (25.2%) | **36 (24.5%)** |
| WEIRD | 107 (72.8%) | 113 (76.9%) | 96 (65.3%) | **95 (64.6%)** |

**Weird share: 72.8% → 76.9% → 65.3% → 64.6%.** WEIRD at high confidence only: 60 → 68 → 65 →
**60**.

One row. That is the whole movement between run 3 and run 4, and it is smaller than the
narration variance READER-3 measured inside a single run. Underneath it, 15 rows moved: **8
improved, 7 regressed**. Run 3 bought its 17-row gain mostly with honest declines; run 4 bought
nothing and spent seven rows that were good the night before.

The composition is also flat: 52 good rows, of which **36 are declines and 16 are answers**
(run 3: 37 and 14). Four runs in, the system answers one question in nine.

## Transitions (run 3 → run 4)

| run 3 \ run 4 | GOOD_ANSWER | GOOD_DECLINE | WEIRD | total |
|---|---:|---:|---:|---:|
| GOOD_ANSWER | 11 | 0 | **3** | 14 |
| GOOD_DECLINE | 2 | 31 | **4** | 37 |
| WEIRD | 3 | 5 | 88 | 96 |

| change | rows | row numbers |
|---|---:|---|
| IMPROVED | 8 | 5, 31, 36, 59, 64, 65, 108, 113 |
| SAME_GOOD | 44 | 7, 15, 18, 20, 23, 27, 37, 38, 39, 40, 45, 50, 52, 61, 62, 67, 68, 73, 74, 79, 84, 87, 94, 100, 101, 105, 106, 107, 111, 114, 116, 118, 123, 124, 125, 126, 127, 130, 131, 133, 137, 138, 140, 143 |
| SAME_WEIRD | 65 | 0, 1, 6, 8, 11, 14, 16, 19, 21, 24, 25, 26, 29, 30, 33, 34, 35, 42, 43, 46, 47, 48, 55, 56, 58, 60, 63, 66, 69, 72, 75, 76, 77, 78, 82, 83, 85, 88, 89, 92, 93, 95, 96, 97, 98, 103, 104, 109, 110, 112, 115, 117, 119, 122, 129, 132, 134, 135, 136, 139, 141, 142, 144, 145, 146 |
| CHANGED_STILL_WEIRD | 23 | 2, 3, 4, 9, 10, 12, 13, 17, 32, 41, 44, 49, 54, 57, 70, 80, 81, 86, 90, 91, 99, 120, 128 |
| REGRESSED | 7 | 22, 28, 51, 53, 71, 102, 121 |

### Which of the night's changes did what it was meant to

Checked by reading the answers, not by trusting the change list.

- **The false-absence guard is fixed, and it is the cleanest win in the run.** "I can't complete
  that request as asked" 3 → **0**. Class C1: 3 → **0**. Row 108 is a GOOD_DECLINE again ("They
  only record the status of each waste-collection point"); rows 41 and 70 got real answers from
  real registers instead of a temperature-sensor correction. The three answers it had replaced
  were about a fire impairment, an accessibility publication and a waste handover — the guard
  was destroying exactly the questions it was least qualified to judge.
- **The invented `m³/s` unit is gone** (2 answers → 0). Row 10 now prints "unit not recorded"
  six times rather than a unit it does not have, and row 132's flows read in L min⁻¹.
- **"Latest snapshot" is now the latest reading.** Row 120's snapshot timestamp (02:47:35) is the
  *end* of its stated window, not the start. The BUG-520 shape is gone from this row.
- **"The building's events store" is gone** (row 80) — replaced by a document decline that
  searches Circulation Times and the Continuity Provision Register for three alternative rooms,
  which is a different wrong answer.
- **Negative physical values are gone from the dossiers** (run 3 row 99 printed "occupancy:
  -7.719", "co2: -260.986"). But the exclusion did not produce a better ranking: row 99's whole
  answer is now "**I computed a ranking but its narration failed the evidence check — see the
  dossier**" — and no dossier is shown. An undergraduate asking where to sit gets an internal
  failure notice and two research laboratories.
- **"The ontology" → "the building model" did not hold.** The word appears in **9** run-4
  answers, up from 7 in run 3 (rows 12, 13, 28, 47, 57, 75, 88, 121, 139). Row 124 shows the new
  wording working ("the building model does not contain daylight-hour counts"), so the rewrite
  exists on some paths and not on the RAG/metadata path where it matters most.
- **Attribution is nearly, not quite, gone.** 4 → 3 answers: row 69 still opens "**The records
  you have** do not contain any information about retention periods", row 49 says "the records
  **you retrieved**", and row 28 — clean in run 3 — now says "The building's records **that were
  provided**".
- **Internal schema documentation is not withheld.** Row 139 still prints the developer-facing
  `rdfs:comment` verbatim and now labels it "**Definition** (rdfs:comment)". Rows 12 and 81 go
  further and answer *out of the data model itself*: an auditor's management-representation
  question is answered with "*Class:* `AccessPermission` … *Property:* `policyOwner` (domain:
  `KnowledgeTopic`)", and incident leaders are handed a table of `dependsOnSpace`,
  `alternativeCapacity` and `parentAsset` instead of the twelve continuity records row 45 reads
  from the same register.
- **The restored asset-register dates are not visible anywhere.** In run 3, row 54 surfaced the
  designed finding — "no `isolationProvenOn` recorded; last visited **2025-10-15**, inspection
  interval 365 days → overdue". In run 4 row 54 declines: "No record includes a 'reconciliation
  required' flag or similar indicator." The data fix landed; the only question that would have
  shown it stopped reading the register.
- **Claim binding is credited with nothing**, as instructed. I note only that no answer in run 4
  carries a claim-binding artefact in its text.

## Regressed rows (7)

### row 22 (EC-069, Emergency coordinators) — GOOD_ANSWER → WEIRD [C7], med

Q: What authority, facts, decisions, open actions, restrictions and unresolved risks must be
handed over at command or shift change?

- **run 3 (24.0 s):** "**Open actions** – CHK-105, CHK-301, CHK-302 overdue – none walked since
  single-crewed round · CHK-304 cannot be walked until COSHH restriction lifts"
- **run 4 (45.8 s):** "**Decisions** – Not met (CF-11) · Unknown (CF-13) · Conflicting (CF-10)
  … **Restrictions** – Degraded (CF-10) · Ready (CF-11)"
- **likely cause:** the same register, narrated by pouring field values into headings they do not
  belong to. A criterion state ("not met") is filed as a decision; a system state ("degraded",
  "ready") as a restriction. The overdue patrol checkpoints and the COSHH restriction — the only
  operationally useful lines in run 3 — are gone.

### row 28 (SU-055, Energy and sustainability) — GOOD_DECLINE → WEIRD [C3], med

Q: Which planned purchases can be met from verified internal reuse stock?

- **run 3 (65.0 s):** "The building's records do not contain any information about planned
  purchases, internal reuse stock, or how those items might be sourced."
- **run 4 (94.6 s):** "The building's records **that were provided** contain information about
  coordination functions … Because this information is not present in the building's **ontology
  data** …"
- **likely cause:** a single-sentence regression that re-acquires both defects the night's work
  targeted — an attribution and the internal word. The decline itself is still correct.

### row 51 (LT-001, Lecturers and tutors) — GOOD_DECLINE → WEIRD [C7], high

Q: I have a 9 a.m. lecture. What is confirmed, what is still unknown, how early should I arrive?

- **run 3 (22.9 s):** "**What we don't know** – Which of these sessions is your 9 a.m. lecture …
  A safe rule of thumb is to arrive 15 minutes before the scheduled start."
- **run 4 (37.8 s):** "All 109 sessions listed start at 09:00 am and are marked **recordStatus =
  completed** – so every lecture scheduled for that time is **confirmed**."
- **likely cause:** a status value read as an answer to a different question. `completed` is a
  record state, not a confirmation, and the lecture in question has not happened. The reader is
  told their lecture is confirmed on the strength of 109 records, none of which is theirs.

### row 53 (LT-005, Lecturers and tutors) — GOOD_ANSWER → WEIRD [C7], high

Q: If my assigned room is withdrawn, which currently eligible alternative should I ask for?

- **run 3 (18.5 s):** "All 28 workspace records … **Bookable rooms (18)** – WS-06 Seminar room
  1.25 …" grouped by kind, correctly.
- **run 4 (25.7 s):** "**18 bookable rooms**" over a table of **23** rows, with "Meeting room
  2.13 / 2.14 / Seminar room 2.15" under **Level 1** and rooms **4.11, 4.12, 4.13** under
  **Level 3**.
- **likely cause:** the moment the narration was asked to group by floor it invented the
  grouping, and the stated count stopped matching the table. Same shape as row 92, which has
  carried it since run 1.

### row 71 (RC-014, Regulatory and compliance) — GOOD_DECLINE → WEIRD [C19], high

Q: Do Abacws local procedures implement the current institutional policies without omissions,
contradictions or unauthorised local variation?

- **run 3 (12.1 s):** "I searched Building Policies; they are the closest material and none of
  them contains the answer."
- **run 4 (37.3 s):** whole answer — "**Nothing is overdue** — every open compliance item is
  within its due date."
- **likely cause:** a compliance shortcut now fires on this phrasing and returns a one-line
  status about a different subject. Row 33 and row 69 of the same run both report 10 open
  compliance checks, so the shortcut is also asserting a due-date judgement neither of them
  makes.

### row 102 (EA-028, Estates and asset management) — GOOD_ANSWER → WEIRD [C9], high

Q: Which closed work orders lack enough asset, test or outcome evidence?

- **run 3 (24.8 s):** "All 15 closed work orders … the **comment** field – the place where test
  or outcome details would normally appear – is empty for every completed record", with all 15
  named and grouped by asset.
- **run 4 (9.2 s):** "the building's data do not contain any fields that record asset, test or
  outcome evidence … you would need to look at the fields that record evidence (e.g.,
  `testResult`, `assetReference`, `outcomeNotes`)."
- **likely cause:** the lane stopped reasoning over the register and declined instead, then
  invented three field names that do not exist anywhere and sent the reader to look for them.
  Run 3's answer was in the top three of the whole run; it is now a false absence with fabricated
  schema attached.

### row 121 (Q358, Maintenance technician) — GOOD_DECLINE → WEIRD [C4], med

Q: What's the filter size for the FCUs on floor 4?

- **run 3 (20.8 s):** "…the closest available resource is the **Filter Air Differential Pressure
  Sensor**."
- **run 4 (26.8 s):** "…consult the FCU maintenance records or the manufacturer's specifications,
  **as that detail is not captured in the building's current ontology**."
- **likely cause:** the internal word re-entered, and the reader is sent to a maintenance log the
  building holds and other answers in this run read (rows 31, 77, 146 all cite Maintenance Log).

**Read the seven together.** Five of them (22, 51, 53, 102 and 71) are the same trade run 3 made
in the other direction: a lane that declined honestly now narrates confidently, or a lane that
narrated now declines. Two (28, 121) are single phrases. None of the seven is a new capability
failing; every one is the same register being read differently on a different night.

## Per-class counts (primary class of each WEIRD row)

| class | name | run 1 | run 2 | run 3 | run 4 | run-4 rows |
|---|---|---:|---:|---:|---:|---|
| C7 | Register narration misreads statuses, dates and fields, or invents conclusions | 18 | 17 | 20 | **21** | 2, 3, 4, 10, 11, 19, 21, 22, 26, 34, 51, 53, 55, 60, 63, 70, 72, 78, 86, 92, 120 |
| C4 | Metadata/discovery fallback: the ontology named, schema as answer, false absence | 6 | 14 | 9 | 9 | 12, 13, 57, 75, 76, 81, 121, 129, 139 |
| C8 | Register chosen on a bare word; the lane declines with unrelated register statistics | 14 | 8 | 7 | **8** | 1, 30, 41, 42, 48, 97, 98, 110 |
| C9 | The building holds the data and no lane reaches it (false absence) | 9 | 8 | 8 | 8 | 33, 43, 54, 66, 85, 88, 102, 122 |
| C11 | Catch-all 'documents do not answer this' for out-of-scope or planning requests | 6 | 12 | 5 | **7** | 8, 80, 82, 89, 90, 103, 112 |
| C3 | Narration hygiene: attribution, raw field names, internal provenance | 6 | 5 | 5 | **6** | 28, 32, 49, 69, 77, 115 |
| C10 | Document lane returns a bare fragment or an internal token as the whole answer | 4 | 5 | 6 | **4** | 93, 104, 144, 146 |
| C12 | Open-domain questions answered from general model knowledge, unlabelled | 4 | 4 | 4 | 4 | 135, 136, 141, 142 |
| C13 | Deliberation lane: blocked phrases, out-of-band rankings, routes reaching ranking | 5 | 4 | 4 | 4 | 58, 99, 117, 119 |
| C19 | Assorted shortcut misroutes (operator, building figures, compliance one-liner) | 5 | 6 | 3 | **4** | 14, 46, 47, 71 |
| C2 | Fetch-budget refusal for whole-building, multi-measurement questions | 2 | 4 | 5 | **4** | 0, 16, 25, 134 |
| C22 | Recommend lane produces generic advice not grounded in the building | 4 | 4 | 4 | 4 | 56, 109, 132, 145 |
| C5 | 'I understood the question but could not put an answer together' | 4 | 6 | 6 | **4** | 35, 44, 83, 95 |
| C14 | Compare/trend fallback dead end ('no measured series') | 2 | 1 | 1 | **2** | 9, 17 |
| C18 | Report lane answers a non-report question and recommends metadata edits | 1 | 1 | 1 | **2** | 91, 96 |
| NEW | closure-shortcut: a closure list answers anything mentioning closures | 0 | 2 | 2 | 2 | 6, 24 |
| C16 | Anomaly question answered from user reports, UUIDs as place names | 1 | 1 | 1 | 1 | 29 |
| C17 | Future or hypothetical questions answered by the current-reading lane | 2 | 1 | 2 | **1** | 128 |
| C1 | Absence guard rewrites a valid answer on a substring match | 3 | 0 | 3 | **0** | — |
| C6a | Shelf-life and meter footers on answers they do not describe | 4 | 4 | 0 | 0 | — |
| C6b | Deictic referent resolved to an arbitrary sensor or declined | 4 | 4 | 0 | 0 | — |
| C15 | 'You can add it — upload a TTL' as the answer | 2 | 0 | 0 | 0 | — |
| C20 | Referent gate treats a descriptive phrase as a named space | 1 | 1 | 0 | 0 | — |
| NEW | question-filed-as-report (write side effect) | 0 | 1 | 0 | 0 | — |
| **total** | | **107** | **113** | **96** | **95** | |

One class went to zero (C1). Four fell by one or two (C10, C5, C17, C2). Five rose (C7, C8, C11,
C3, C19, plus C14 and C18 by one each). **C7 is the largest it has ever been in four runs — 21 of
95 weird rows, one in four and a half.** The pattern READER-3 identified holds and has hardened:
the wrong-register declines and the catch-alls have been pushed down, the right register is
reached more often, and the narration over that register is where nearly all the remaining damage
now lives.

### Phrases counted mechanically across all 147 answers (secondary defects included)

One regex per row over all four files, so the columns are like-for-like.

| phrase | run 1 | run 2 | run 3 | run 4 |
|---|---:|---:|---:|---:|
| "I can't complete that request as asked" (absence guard) | 3 | 0 | 3 | **0** |
| meter footer 'Boundary: not declared' | 7 | 10 | 2 | 2 |
| recheck footer 'Switch if:' | 9 | 10 | 2 | 2 |
| 'Evidence time: unknown' | 4 | 4 | 0 | 0 |
| user attribution ('you provided' / 'records you have' / 'you retrieved' / 'that were provided') | 8 | 11 | 4 | **3** |
| 'simulated' / 'synthetic' / 'fake' | 3 | 1 | 0 | 0 |
| TTL / upload instruction | 5 | 0 | 0 | 0 |
| 'The room holds N records' | 7 | 0 | 0 | 0 |
| 'add or update it' | 6 | 0 | 0 | 0 |
| 'The owner of that record holds the answer.' | 6 | 19 | 0 | 0 |
| 'documents do not answer this' | 6 | 19 | 12 | **13** |
| 'I understood the question but could not put an answer together' | 4 | 6 | 5 | **4** |
| 'That question reaches N sensors' | 2 | 5 | 5 | **4** |
| "couldn't render the chart" | 2 | 2 | 2 | 2 |
| 'Which room do you mean…' (deictic clarification) | 0 | 0 | 5 | 5 |
| the ontology named in user-visible text | 22 | 18 | 7 | **9** |
| internal IRI / class / schema token (`bldg:`, `rdfs:`, `Mechanical_Room`, `Air_Quality_Level_Sensor`) | 4 | 5 | 7 | 7 |
| impossible unit (m³/s for water flow) | 0 | 0 | 2 | **0** |
| negative physical quantity in a dossier | 0 | 0 | 1 | **0** |

The owner's standing rule is broken on 3 answers for attribution (28, 49, 69) and on roughly a
dozen for naming internal machinery: `AccessPermission`/`policyOwner`/`KnowledgeTopic` (12),
`bldg:controlTransferRecord` (13), `remedialScope`/`acceptanceEvidence` invented as table names
(49), `Air_Quality_Level_Sensors` (56), `dependsOnSpace`/`parentAsset` (81), 【continuity_provision_register】
printed inside the answer text (93), `Mechanical_Room`/`Storage_Room`/`Telecom_Room` in the
ranking dossiers (58, 117, 119), `bldg:continuity/CP-001` (129), `maps_to hazard_controls` and
"Model version: 2026.9" (77), and the `rdfs:comment` quoted verbatim with its property name
(139). None of these is a false statement; each tells the reader what the system is made of
instead of what the building is like.

## What remains, ranked by how visible it would be to a supervisor asking live

| rank | class | rows | severity | why it shows |
|---:|---|---:|---|---|
| 1 | **C7** register narration misreads fields, dates and statuses, or invents conclusions | 21 | P1 | It reads as confident fact and it is the most likely output of any question that reaches a register. Worst on the day: row 51 ("every lecture scheduled for that time is confirmed" from `recordStatus = completed`), row 120 (idle September plant diagnosed "**not healthy** … check for blockages"), row 63 (a professional-services user told to "check the damper on that VAV box"), row 60 (two rooms recommended for a four-person viva that the same table marks "Group friendly: ✗", with confidentiality certified off a `suitableForCalls` flag the boundary forbids), rows 53 and 92 (floor-4 rooms filed under floor 3, and a count that does not match its own table), row 86 (a **truncated display row** reported to a security officer as an incomplete record), row 10 ("Water capacity … adequate; no upgrade required"). |
| 2 | **C9 + C4** the building holds it and the answer denies it | 17 | P1 | Seven are contradicted **by another answer in the same run**, which is what a supervisor asking two related questions will see: row 85 says no public route is interrupted while rows 26, 70 and 72 all report RTE-016 closed with Lift B out of service; row 88 says "the current ontology does not list any occupancy-related sensors" while rows 58 and 119 rank 194 spaces on occupancy; row 129 denies drain work while row 125 lists "WO-015 – Condensate drain clearance"; row 43 denies any impairment while row 21 calls four of the same records displaced; row 66 denies occupancy and CO₂ for Room 1.06 while rows 58 and 117 read that room; row 122 denies a booking schedule while row 110 counts 16 bookings; row 81 says the records "do not list individual services" while row 45 lists three from the same register. Add the C11 pair (82, 89), which decline from the workspace register that answers rows 53 and 92. |
| 3 | **C13** deliberation lane | 4 | P1 | The most impressive-looking output, so the most likely to be demonstrated — and row 99 now returns "**I computed a ranking but its narration failed the evidence check — see the dossier**" with no dossier attached. Row 58 recommends an academic office as a seating area; row 119 gives exclusion reasons as the reason for zero candidates and leaks three Brick class names; row 117 separates its top three by 0.15 °C and calls it stable. |
| 4 | **C8** bare-word register capture | 8 | P2 | "They record access-permission group details" still answers a fairness question (97); a first-aid question is answered from hazard controls (42) with an AED record held; a fire-impairment question from the equipment handover register (41). |
| 5 | **C22** recommend lane | 4 | P1 | Row 56 tells an M&E engineer to calibrate five zones because "**these are the only sensors we know exist in the building**" — in a building the system elsewhere says has 3,248. Row 109 invents "ABACWS A" and "ABACWS B" as a class of devices. Row 132 reasons from water flow rates to whether tap water is free. Row 145 contradicts its own floor means two lines apart. |
| 6 | **C11** document catch-all | 7 | P3→P2 | Up from 5. "Book me a hotel" still ends in "I searched Room Bookings" (112), and three of the seven decline with registers the same run uses to answer other questions. |
| 7 | **C3** narration hygiene | 6 | P1 wording | Three attribution hits (28, 49, 69), a provenance dump with mapping names and a model version (77), and two invitations to send the system more data (49, 115). Each is one sentence. |
| 8 | **C19** shortcut misroutes | 4 | P2 | Row 14 still answers a control-ownership question with "**Abacws Building** — operated by: **Cardiff University Estates**."; rows 46 and 47 answer network and host questions with the sensor census; row 71 is new and answers a policy-implementation question with "Nothing is overdue". |
| 9 | **C10** fragment as the whole answer | 4 | P2 | "CF-01 Incident command … CF-14 Media and enquiries" (104); "Lecture capture and streaming — Room 4.44 (CP-009)【continuity_provision_register】" (93), which now also prints an internal token. |
| 10 | **C2 + C5 + C14** the three dead-end templates | 10 | P2 | Four different questions are told the building "measures air quality, carbon monoxide, co2 and damper position" (35, 44, 83, 95), none of which is about any of those; four are told "That question reaches N sensors" (0, 16, 25, 134 — row 16 after 185 s); two are told "I have no measured series for the requested sensor or zone" (9, 17) about zones with 296 temperature sensors and 21 circulation-time records. |
| 11 | **C18** report lane | 2 | P2 | Back to two, and the metadata instruction READER-3 recorded as gone is back: row 91 answers "plan tomorrow" with "**Assign consistent units to each sensor reading**" and "Document the unit for each sensor label in the building's asset register". |
| 12 | **C12** open-domain prose | 4 | P3 | Unchanged across four runs: autism, ozone, glare sensors, CO₂ — all answered from general knowledge, none marked as not from the building, and row 142 still does not use any of the building's 280 CO₂ sensors. |

**If one thing is fixed before the demo, fix the four regressions that are a single narration
choice (22, 51, 53, 102)** — they were good twelve hours earlier and all four are register
narration, which is also the largest class. **If two, take the three C7 rows that attach a verdict
to a misread field** (51 "confirmed", 120 "not healthy", 60 "confidential"), because each is a
sentence a supervisor can check by eye and find wrong.

## The grader says 36.1%. What do I measure, and where do I disagree?

I measure **64.6%** (95 rows). The grader measures **36.1%** (53 rows). I re-ran it offline over
run 4 to check the number I was given: `GOOD_ANSWER 52 · GOOD_DECLINE 42 · WEIRD 53 · weird share
36.1%`. It reproduces exactly.

**On direction we now disagree, and that is the finding.** Run 3 → run 4 the grader falls 40.1% →
36.1%, a 4.0-point improvement. I move 65.3% → 64.6%, 0.7 of a point, which is noise. The one
place the two instruments agreed — READER-3's strongest evidence that the night's work was real —
does not repeat. The grader's fall is made of rows it can see improving (the absence-guard text is
gone, the m³/s unit is gone, "events store" is gone), and those really did improve. It cannot see
that seven rows lost their content.

| I say \ grader says | GOOD_ANSWER | GOOD_DECLINE | WEIRD |
|---|---:|---:|---:|
| GOOD_ANSWER | 10 | 5 | 1 |
| GOOD_DECLINE | 10 | 19 | 7 |
| WEIRD | 32 | 18 | 45 |

Exact agreement **74/147 = 50.3%**; weird-or-not **89/147 = 60.5%** (READER-3 measured 80 and 92
on run 3, so agreement fell).

- **50 rows the grader calls good and I call weird.** That is the whole gap, and it is the same
  gap all three earlier readers found: the grader's rules read SHAPE. It fires correctly on a
  named ontology, a footer misfire, a fragment, an attribution, lane jargon. It has **no way to
  know that `recordStatus = completed` does not mean a lecture is confirmed** (51), that 23 rows
  is not 18 (53), that rooms 4.11–4.13 are not on floor 3 (53, 92), that a "not met" criterion
  state is not a decision (22), that a truncated display row is not an incomplete record (86),
  that "these are the only sensors we know exist" is false of a 3,248-sensor building (56), or
  that another answer in the same file contradicts this one (85, 88, 102, 122, 129). Eighteen of
  my 21 C7 rows and 5 of my 8 C9 rows are invisible to it by construction: they are content
  checks against the register, and it never reads the register.
- **8 rows the grader calls WEIRD and I call good** (20, 31, 40, 50, 52, 94, 113, 133). Six are
  the document-decline template, which its DOCUMENT_CATCHALL rule penalises on sight; I checked
  each and the registers named are the relevant ones and the absence is real. Row 20 it penalises
  for "phrase repeated 5x" — the five washrooms genuinely have identical service records, and
  listing them is the answer. Row 113 it penalises because the decline "cites a register sharing
  no term with the question"; that rule is pointing at something real (see below) but on this row
  the register is the right one.
- **We share one blind spot.** Neither of us graded latency. Run 4 took 63.9 minutes for 147
  questions (median 16.0 s, run 3: 18.4 s), but **11 answers took over 60 s and the four slowest
  produced nothing**: row 44 at **224.9 s** ("I could not match *reproducible* or *assurance* to
  anything this building records"), row 16 at **185.5 s** ("That question reaches 296 sensors"),
  row 9 at **150.8 s** ("I have no measured series"), row 75 at 103.9 s (a false absence). Two
  hundred and twenty-five seconds for a template is worse in a live demo than a wrong answer in
  twelve.

**My reading: the grader's 36.1% is a floor, and its direction is no longer safe to use as a
gate.** As an instrument it is unchanged and it is honest about what it measures; what changed is
that this run's movement happened entirely inside the class it cannot see. A gate reading "weird
fell 4 points" would have passed a run that lost seven good answers. The single change that would
close most of the gap is still the one READER-3 named: give it the register rows, and let it check
that every cited ID exists, every stated count equals the rows shown, every date arithmetic
resolves against today, and every floor grouping matches the room number.

## New in run 4 that was not in run 3

- **An internal failure notice as the whole answer**: "I computed a ranking but **its narration
  failed the evidence check** — see the dossier" (row 99), with no dossier in the reply. The
  impossible-value exclusion appears to have cost the answer rather than corrected it.
- **The data model offered as the answer.** Rows 12 and 81 answer an auditor and an incident
  commander with tables of class and property names; row 139 now labels its verbatim developer
  note "**Definition** (rdfs:comment)".
- **The system's own display truncation reported as a defect in the building's records** (row 86:
  "CP-001 | Core network and building u – the row is **truncated**, so the provision is
  incomplete").
- **An internal source token inside the answer text**: 【continuity_provision_register】 (row 93).
- **A compliance one-liner answering a governance question**: "Nothing is overdue" (row 71).
- **Invented field names offered to the reader as places to look**: `testResult`,
  `assetReference`, `outcomeNotes` (row 102); `remedialScope`, `acceptanceEvidence`,
  `completionStatus`, `conditionStability` (row 49).
- **"Measure indoor temperature, humidity, CO₂, PM2.5 and TVOC"** recommended to an energy manager
  (row 128) in a building carrying 296, 281, 280, 245 and 41 of those sensors.
- **A capacity adequacy certification** from water-flow readings (row 10: "Water capacity and
  connection routes are **adequate** for the proposal; no upgrade is required"), which the
  boundary for that question forbids in as many words.
- **The metadata-edit recommendation is back** in the report lane (row 91).

## Things I could not tell

- **Whether run 4 is worse than it looks or the same as run 3 by luck.** Seven regressions and
  eight improvements on one sample at non-zero temperature is exactly the churn READER-3
  predicted: she named seven run-3 improvements (15, 27, 51, 84, 87, 107, 121) as possible
  narration variance, and **three of those seven (51, 121, and the register behind 22) are the
  rows that regressed tonight**. That is the strongest evidence in this file that run 3's
  11.6-point fall was partly compositional. The claim I will stand behind is: **the weird share
  has not moved since run 3, and the movement inside it is narration variance over the same
  registers.**
- **Rows where the building's holdings come from READER's SPARQL rather than this run.** Rows 1,
  30, 33, 42, 48, 54, 56, 66, 75, 98, 128 rest on the baseline counts (AVReadiness 22,
  CleaningTask 30, FirstAidPoint, Permit 15, 1,929 calibrated sensors, 3,248 sensors). I ran no
  query. The ten rows contradicted by another run-4 answer are the safe ones.
- **Row 26 is the row I could most easily be argued out of.** Its table and statuses are right and
  the run-3 certification language is gone; the only defect is the parenthetical "Open: 13 (all
  step-free except RTE-015)", which is corrected two lines later. I called it WEIRD at low
  confidence to stay consistent with READER-3, who marked the same row weird for the same shape of
  self-contradiction. A reader who let it pass would put run 4 at 94 weird (63.9%).
- **Row 36 is the reverse call.** I moved it to GOOD_ANSWER at low confidence because it now
  declares its own proxies ("recordStatus (condition), valueBand (whole-life cost proxy)") and
  lists all 24 assets. A stricter reader would still call recordStatus-as-condition a misread and
  leave it at 96 weird.
- **Row 113 I called GOOD_DECLINE at low confidence.** It honestly says the asset register holds
  no "running outside schedule" field — but the operating-regime register holds the windows and
  the building has run-time and fan-state sensors, so a stricter reading is a false absence. The
  grader independently flagged this row. If it is weird, run 4 is 96.
- **Row 116: two answers in this run disagree about where WCP-023 is.** Rows 18 and 19 place it in
  "Room 2.01 — Research Laboratory"; row 116 gives "Level 2 circulation & stairs". Both report 55
  % fill, so it is the same record. I could not tell offline which field each answer is reading,
  so I left row 116 GOOD_ANSWER at low confidence and note the discrepancy here. It would be
  visible to anyone who asked both questions.
- **Row 140 calls six fire-alarm zone records "smoke-detector assets."** Both READER-3 and I
  passed it; if the records really are zones and not detectors, the answer is confidently wrong
  about what the building has, and I cannot resolve that from the text.
- **Row 131** still prints "Denied for every role" and "_Policy: `policy_inference_individual_pattern`_",
  which is internal wording under the owner's rule. All three earlier readers passed this row, so
  I did too. Applied strictly, run 4 is 96 weird.
- **Whether the restored asset dates are actually in the graph.** I can only see that no run-4
  answer shows them, and that the one row which showed them in run 3 (54) now declines.
- **Latency.** Not graded. Over 60 s in run 4: rows 44 (224.9 s), 16 (185.5 s), 9 (150.8 s), 75
  (103.9 s), 99 (98.3 s), 27 (96.4 s), 28 (94.6 s), 91 (95.1 s), 15 (93.5 s), 129 (78.8 s), 1
  (76.4 s). Row 15 spent 93.5 s on a two-sentence decline that run 3 produced in 24.9 s.
