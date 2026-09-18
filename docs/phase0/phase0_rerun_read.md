# Phase 0 rerun, labelled by hand (READER-2)

- input: `docs/phase0/phase0_rerun.md.jsonl` — the same 147 questions via `/v1` streaming as facility01, 2026-09-17 ~16:00–17:30, AFTER the day's fixes were loaded
- baseline: `docs/phase0/phase0_read.jsonl` (READER, same method, answers from 14:10–15:20)
- every rerun answer was read in full against its question and boundary; labels are in `docs/phase0/phase0_rerun_read.jsonl`
- verdicts, causes and classes follow `phase0_read.md` exactly. WEIRD = would read as broken, off-topic, incomplete, invented, or as an instruction to add data. A decline is GOOD_DECLINE only when it is true and does not attribute the data to the user or ask for data. A clarification is GOOD_DECLINE (as the baseline reader labelled rows 127 and 138).
- offline only: no SPARQL, no live re-ask. Where I say the building holds something, I rely on the baseline reader's read-only counts or on another answer in the same run that shows the record (e.g. row 22 shows overdue patrol checkpoints used to judge row 86).
- Room 0.01 'Main Reception' wording was not counted against any answer.
- `fix_status`/`fix_ids`/`offline_register_*` from the baseline file are not repeated; `baseline_verdict`, `baseline_class`, `change` and `class` are added.
- Four rows (26, 72, 84, 105) were fixed after the rerun and re-asked live. They are labelled FROM THE RERUN AS RECORDED; the re-ask outcome is in each row's `note`. I did not see those re-ask answers, only the summary I was given.

## Headline

| verdict | before n | before share | after n | after share |
|---|---:|---:|---:|---:|
| GOOD_ANSWER | 19 | 12.9% | 10 | 6.8% |
| GOOD_DECLINE | 21 | 14.3% | 24 | 16.3% |
| WEIRD | 107 | 72.8% | 113 | 76.9% |

**Weird share: 72.8% → 76.9%** (107 → 113 rows). WEIRD at high confidence only: 60 → 68.

The automatic grader counts 20 weird (13.6%) on the rerun, down from 29 (19.7%) on the baseline; by hand it is 113 (76.9%), up from 107. The grader moved the opposite way to the content. Exact agreement 52/147, weird-or-not agreement 52/147.

**The net movement is small and two-way: 9 rows improved, 15 regressed, net -6.** Of the 107 rows that were weird, 68 are weird for the same class and 30 changed shape and are still weird. The fixes removed several visible phrasings (the TTL/upload instruction, 'The room holds N records', the 'add or update it' document sentence, the 100-fold repetition, the 'temp'~'temporary' absence rewrite, the simulated dossier column) but most rows those phrasings sat on had a second defect underneath, and that defect is now the whole answer. New wrong routes also appeared on rows that were fine.

## Transitions

| before \ after | GOOD_ANSWER | GOOD_DECLINE | WEIRD | total |
|---|---:|---:|---:|---:|
| GOOD_ANSWER | 9 | 2 | 8 | 19 |
| GOOD_DECLINE | 0 | 14 | 7 | 21 |
| WEIRD | 1 | 8 | 98 | 107 |

| change | rows | row numbers |
|---|---:|---|
| IMPROVED | 9 | 19, 37, 39, 50, 52, 62, 79, 114, 133 |
| SAME_GOOD | 25 | 5, 7, 18, 22, 23, 34, 38, 40, 59, 65, 67, 68, 94, 106, 108, 116, 120, 124, 125, 126, 127, 130, 131, 138, 140 |
| SAME_WEIRD | 68 | 0, 1, 2, 3, 9, 10, 11, 14, 15, 16, 20, 21, 27, 29, 30, 31, 32, 35, 42, 45, 47, 53, 54, 56, 58, 60, 61, 64, 66, 71, 74, 75, 76, 77, 82, 89, 90, 96, 97, 98, 99, 100, 101, 107, 109, 110, 111, 112, 113, 115, 117, 118, 121, 122, 123, 128, 129, 132, 134, 135, 136, 137, 139, 141, 142, 143, 144, 145 |
| CHANGED_STILL_WEIRD | 30 | 4, 8, 13, 17, 24, 28, 33, 41, 43, 44, 46, 48, 51, 57, 63, 72, 73, 78, 80, 83, 85, 86, 88, 91, 93, 95, 103, 104, 119, 146 |
| REGRESSED | 15 | 6, 12, 25, 26, 36, 49, 55, 69, 70, 81, 84, 87, 92, 102, 105 |

SAME_WEIRD means the same defect class as the baseline, not identical text: several of those answers were reworded (e.g. row 11's table is now complete but the containment list is invented).

### Improved rows

- row 19 (CT-065, was C7 → GOOD_ANSWER): 'the **next authorised collection is scheduled for 18 September 2026**' (asked 17 Sep) with the two sharps bins, and 'No explicit "ready-before-arrival" instructions ... are recorded' — date now anchored and absence stated plainly.
- row 37 (FP-064, was C3 → GOOD_DECLINE): 'the building's data do not contain any information about conflicts of interest, related-party links, or segregation-of-duty controls' then a short, plain list of what the cost-line and approval registers hold — the 100-fold repetition and 'the data you have' are gone.
- row 39 (FS-041, was C15 → GOOD_DECLINE): 'I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team.' — the TTL/upload instruction is gone; no warden records exist.
- row 50 (IR-034, was C8 → GOOD_DECLINE): '**Abacws Building's documents do not answer this.** I searched Access Permission Register, Approval Evidence Register, Department Directory' — the waste register is no longer cited; chain-of-custody records are not held.
- row 52 (LT-059, was C11 → GOOD_DECLINE): '**Abacws Building's documents do not answer this.** I searched Av Readiness Register ... The owner of that record holds the answer.' — the 'add or update it' instruction is gone.
- row 62 (PHD-077, was C9 → GOOD_DECLINE): '**Which space did you mean?** I can say what is measured in a particular room, floor or zone, but I need to know which one' — a clarification for 'this office' where the baseline gave a false absence plus approval statistics.
- row 79 (RB-033, was C7 → GOOD_DECLINE): 'The records do not indicate whether a booking should remain protected from release. They only record each booking's status' — the invented release rule is gone.
- row 114 (Q516, was C15 → GOOD_DECLINE): 'I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team.' — TTL instruction gone; no capital-project outcome records.
- row 133 (Q224, was C10 → GOOD_DECLINE): '**Abacws Building's documents do not answer this.** I searched Asset Engineering Register' — the misleading bare 'Incoming main stop valve SV-1' is gone; no floor-level isolation is recorded.

## Regressed rows

### row 6 (AI-048, Accessibility, inclusion, and well-being teams) — GOOD_DECLINE → WEIRD [NEW:closure-shortcut], confidence high

Q: Have closures, room moves and route changes reached each affected attendee and accompanying person through their selected authorised channels before travel?

- **before (21 s):** "the building's data do **not** contain any information about whether closures, room moves or route changes were communicated to attendees or their accompanying persons through authorised channels. They only record the closure periods for the building's floors:…"
- **after (40 s):** "**3 planned closure(s) on record**: - Floor2: planned electrical maintenance, from 2026-08-28T08:00 to 2026-08-28T17:00 - Floor0: deep clean, from 2026-09-13T08:00 to 2026-09-13T17:00 - Floor1: planned electrical maintenance, from 2026-09-18T08:00 to 2026-09-1…"
- **why weird:** Whole answer is '**3 planned closure(s) on record**: - Floor2: planned electrical maintenance, from 2026-08-28T08:00 ...' — the notification question (did changes reach attendees through their channels) is neither answered nor declined; two of the three closures are past.
- **likely cause:** Predicted by the baseline reader: 'closures' no longer selects the ClosurePeriod register through the register lane. A closure-list shortcut now answers anything mentioning closures, whatever was asked (it also took row 24).

### row 12 (AU-075, Auditors and certification assessors) — GOOD_ANSWER → WEIRD [C4], confidence high

Q: Which matters require a formal management representation because independent evidence is unavailable, incomplete or solely management-held?

- **before (43 s):** "The records that lack independent evidence (no evidenceReference) and therefore need a formal management representation are: **Service continuity provision** | Record ID | Label (service) | Reason | |-----------|-----------------|--------| | CP‑003 | Research …"
- **after (35 s):** "**Answer** The ontology data you provided does not contain any explicit list of “matters” that are flagged as requiring a formal management representation because independent evidence is unavailable, incomplete, or solely held by management. The only property …"
- **why weird:** 'The ontology data you provided does not contain any explicit list of "matters" ... consult additional policy or governance documents that are not part of the current ontology' — the baseline answered from continuity/approval records with no evidenceReference.
- **likely cause:** The register lane no longer picks up the continuity/approval evidence fields; the metadata RAG fallback (C4) answered instead, with 'The ontology data you provided'.

### row 25 (ER-031, Emergency responders) — GOOD_DECLINE → WEIRD [C2], confidence med

Q: What defensible aggregate occupancy range applied to each affected zone at the incident start time?

- **before (11 s):** "The incident records do not contain defensible aggregate occupancy ranges for the affected zones at the incident start time. They record incident details such as status, location, effectiveFrom, and other incident‑specific information. --- **You might also ask…"
- **after (13 s):** "That question reaches **250 sensors** — more than I can read and summarise in one request without either timing out or quietly answering from a fraction of them. Narrow it and I can answer directly: - one floor, or one room - one measurement at a time (tempera…"
- **why weird:** 'That question reaches **250 sensors** — more than I can read ... Narrow it' — no incident is named; the baseline gave an honest decline from the incident register.
- **likely cause:** The incident register is no longer selected; 'occupancy' sends the question to the sensor fetch lane, which trips the fetch budget (C2) instead of asking which incident.

### row 26 (ER-008, Emergency responders) — GOOD_ANSWER → WEIRD [C10], confidence high

Q: Which boundary-to-door route is currently evidenced for ambulance crews, stretcher teams and responders on foot, including step-free constraints?

- **before (17 s):** "**Boundary‑to‑door routes that are currently evidenced for ambulance crews, stretcher teams and responders on foot (step‑free)** | Route ID | Label (from Accessible route) | From → To | Step‑free? | Approval status | Notes | |----------|-----------------------…"
- **after (12 s):** "RTE-001 Accessible drop‑off to Reception --- *From Abacws Building's documents: Accessible Route Register, Asset Engineering Register, Stakeholder Group Register. For the current version, contact facility management.*"
- **why weird:** Whole answer: 'RTE-001 Accessible drop-off to Reception' + document footer — a bare fragment where the baseline gave two step-free routes with status and constraints.
- **likely cause:** Predicted: 'step-free' no longer selects AccessibleRoute. The document lane returned a one-line fragment (C10). The post-fix re-ask lists six routes but adds 'would not block a stretcher', which no record says, so the re-ask would still be WEIRD (C7).

### row 36 (FP-041, Finance and procurement teams) — GOOD_ANSWER → WEIRD [C7], confidence med

Q: Which assets should receive survey, maintenance, refurbishment or replacement funding first when criticality, condition, risk and whole-life cost are combined?

- **before (26 s):** "The records do not contain any explicit “risk” or “whole‑life cost” figures, so the only factors we can combine are the **criticality** recorded in the Asset Engineering Profile register and the **condition grade** (plus remaining life) recorded in the Conditi…"
- **after (24 s):** "The records show 24 assets in the building. From the data that is recorded we can combine: | Asset | Condition | Criticality | Whole‑life cost (value band) | Why it ranks high | |-------|-----------|-------------|-----------------------------|-----------------…"
- **why weird:** Record status read as condition and value band as whole-life cost ('Condition | active', 'Whole-life cost (value band)'); 'AEP-007 – the only irreplaceable chiller' is invented; then 'No additional assumptions or calculations are made' and a '**Boundary: not declared.** ... the meter behind it' footer on a funding ranking (C6a).
- **likely cause:** The condition-survey register is no longer read; narration takes record status as 'condition' and value band as 'whole-life cost', invents 'the only irreplaceable chiller', and the meter-boundary footer fires on a funding ranking.

### row 49 (IR-045, Insurers and risk assessors) — GOOD_DECLINE → WEIRD [NEW:question-filed-as-report], confidence high

Q: For each defect, what remedial scope and acceptance evidence were required, what was completed, and has the corrected condition remained stable?

- **before (66 s):** "the building's data do **not** contain the information you asked for. They do not record: * **Remedial scope** - what work was planned or carried out to fix a defect. * **Acceptance evidence required** - the evidence that was needed to confirm the defect had b…"
- **after (95 s):** "✅ Thank you — your **maintenance request** has been logged as **REP-7420E1**. - **Category:** Maintenance request - **Priority:** NORMAL - **Status:** OPEN An administrator has been notified and will review it. You can check progress any time by asking *"what'…"
- **why weird:** An insurer's question is filed as a fault ticket: '✅ Thank you — your **maintenance request** has been logged as **REP-7420E1** ... An administrator has been notified' (95 s) — a write side effect and no answer.
- **likely cause:** Report-intake capture: a question about defects, remedial scope and completion was classified as a maintenance report and written to user_reports (REP-7420E1, 'An administrator has been notified'). A side effect, not only a wrong answer.

### row 55 (ME-055, Mechanical and electrical engineers) — GOOD_DECLINE → WEIRD [C9], confidence low

Q: Which points and sampling rates should be trended so this commissioning or diagnostic test can observe the expected behaviour?

- **before (10 s):** "The records do not contain sampling‑rate information; they only record observed duty values for each asset. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?"
- **after (10 s):** "the building's data do not contain any sensor-point names or sampling-rate information. They only record: * **Design duty** (the intended flow or power) * **Commissioned duty** (the value that was verified at installation) * **Observed duty** (the value measur…"
- **why weird:** 'the building's data do not contain any sensor-point names or sampling-rate information ... Because no sensor identifiers or data-sampling frequencies are listed, I can't tell you which points to trend' — the building model declares 3,248 named sensors; only the asset register lacks them.
- **likely cause:** Same register and lane; the narration widened a true absence (sampling rates) into a false one ('do not contain any sensor-point names').

### row 69 (RC-054, Regulatory and institutional compliance teams) — GOOD_DECLINE → WEIRD [C3], confidence high

Q: Are compliance records retained for the correct period, in the authorised system and format, with integrity, access and disposal controls appropriate to their purpose?

- **before (9 s):** "The records do not contain information about retention period, authorised system, format, integrity, access or disposal controls. They only record due dates, completion dates, status, responsible role and record ID. --- **You might also ask:** Who owns these r…"
- **after (11 s):** "The records you have show that the building’s compliance checks are being logged in a single system, with each entry recording: * **Label** – the type of check (e.g., “Emergency lighting monthly function test”) * **Due date** – when the check was scheduled * *…"
- **why weird:** '**The records you have** show that the building's compliance checks are being logged in a single system' and 'the data are stored in the building's compliance-management system' — attribution to the user plus an invented system claim; the substance of the decline is otherwise right.
- **likely cause:** Same register; narration now opens 'The records you have' (user attribution, BUG-679 still open) and invents 'the building's compliance-management system'.

### row 70 (RC-024, Regulatory and institutional compliance teams) — GOOD_ANSWER → WEIRD [C7], confidence med

Q: Are accessible entrances, routes, lifts, doors, toilets, refuges and assistance arrangements available as currently published, including temporary alternatives?

- **before (47 s):** "**Answer to your question** The building’s published records show that: | Feature | Register | Status | Key details | |---------|----------|--------|-------------| | **Accessible entrances / routes** | Accessible route | 13 open, 2 restricted, 1 closed | 13 ro…"
- **after (38 s):** "**Short answer:** Yes – the building’s published records show that accessible entrances, routes, lifts, doors, toilets, refuges and assistance arrangements are all documented, and temporary alternatives are noted where a route or lift is not currently usable. …"
- **why weird:** '**Short answer:** Yes' and '**Bottom line:** The building's published records confirm that all required accessible features ... are available' — while its own table lists 'RTE-010 ... **Lift B** – *in_service*' and 'RTE-016 ... **Lift B** – *out_of_service*', and offers 'Alternative: **Lift B** + north corridor' for RTE-006. The conflict is not reported and availability is certified.
- **likely cause:** Same register; narration adds 'Short answer: Yes' and 'confirm that all ... are available' — certifying accessibility against the boundary — and does not report that Lift B is in_service on RTE-010 and out_of_service on RTE-016.

### row 81 (LB-065, School leadership, university leadership, and building owners) — GOOD_DECLINE → WEIRD [C4], confidence med

Q: Which dependency-aware recovery order should incident leaders adopt to restore priority services safely with the people and resources currently available?

- **before (8 s):** "The records do not contain a dependency‑aware recovery order. They record the following for each incident: - **Incident status** (closed, open, monitoring) - **Incident category** (near miss, injury, service failure, etc.) - **Potential severity** (minor, mode…"
- **after (43 s):** "I'm sorry, but the building's data only lists the building's sensors - it doesn't include any information about a recovery order or how priority services should be restored. **What the results do show:** - 257 sensor entries (e.g., "Entry Count Sensor - Main E…"
- **why weird:** 'the building's data only lists the building's sensors - it doesn't include any information about a recovery order' (the continuity register records dependencies per service), generic 'HVAC depends on power, which depends on the main generator', and 'If you have access to those documents or a dependency map, I can help you interpret them'.
- **likely cause:** The incident register is no longer selected; a sensor-listing SPARQL result was narrated as the whole building ('only lists the building's sensors'), so the continuity register's dependencies are denied, plus generic advice and an invitation to supply documents.

### row 84 (SO-031, Security officers) — GOOD_ANSWER → WEIRD [C11], confidence med

Q: Which events are due today, and which approved Security arrangements are current, missing or no longer valid for each one?

- **before (8 s):** "None of the 12 event records record any events that are due today. They only record scheduled events with their effectiveFrom dates, and no security arrangements are recorded in these records. --- **You might also ask:** Who owns these records? | Which of thes…"
- **after (4 s):** "**Abacws Building's documents do not answer this.** I searched Incident And Near Miss Log, Public Event Register, Service Schedules; they are the closest material and none of them contains the answer. The owner of that record holds the answer."
- **why weird:** '**Abacws Building's documents do not answer this.** I searched Incident And Near Miss Log, Public Event Register, Service Schedules ... none of them contains the answer.' — the event register answers the 'which events are due today' half, which the baseline did.
- **likely cause:** Predicted: 'events' no longer selects PublicEvent; the document catch-all declined. The post-fix re-ask reaches the event register but only says no security arrangements are recorded and does not list today's events, so it would still be INCOMPLETE.

### row 87 (SP-031, Space-planning teams) — GOOD_DECLINE → WEIRD [C3], confidence high

Q: Which functions must be co-located or kept within a stated travel time, which are preferences, and which adjacency claims lack evidence?

- **before (7 s):** "The circulation records do **not** contain any information about functions that must be co‑located, preferences, or adjacency claims. They only record walking and step‑free travel times between floors and within levels. --- **You might also ask:** Who owns the…"
- **after (6 s):** "The circulation records you provided only describe walking and step‑free travel times between floors in the building. They do not contain any information about which functions must be co‑located, any stated travel‑time preferences, or evidence for adjacency cl…"
- **why weird:** 'The circulation records **you provided** only describe walking and step-free travel times between floors' — the decline is otherwise the same as the baseline's GOOD_DECLINE.
- **likely cause:** Same register and decline; narration now says 'The circulation records you provided' (BUG-679 open).

### row 92 (PGT-044, Taught postgraduate students) — GOOD_ANSWER → WEIRD [C7], confidence med

Q: During group-project deadline week, which time windows are most likely to offer a suitable meeting space for our team?

- **before (29 s):** "**Answer** During a group‑project deadline week the building’s bookable rooms (the 18 “bookable room” records) are the most likely to provide a quiet, group‑friendly space. All of those rooms have a *quietestPeriod* that falls after 16:00 on weekdays (or “late…"
- **after (42 s):** "The building’s records show that all 28 work‑spaces are **active**. - **Bookable rooms**: 18 (Mon‑Fri 08:00‑18:00) - **Common room**: 1 (Mon‑Fri 07:00‑19:00) - **Computer labs**: 8 (Mon‑Fri 08:00‑20:00) - **Open study**: 1 (Mon‑Sun 07:00‑22:00) Each space list…"
- **why weird:** 'Each space lists a *busiestPeriod* that is typical for a "group-project deadline week" (i.e., a teaching week)' (invented equivalence) and '**15:00 – 18:00** (after the latest busy period for labs and bookable rooms ...)' while its own table gives labs '10:00-16:00'.
- **likely cause:** Same register; narration switched from quietestPeriod to busiestPeriod and then reasoned wrongly ('15:00 – 18:00 ... after the latest busy period for labs' when labs are busy to 16:00), with an invented 'deadline week = teaching week'.

### row 102 (EA-028, University estates and asset-management teams) — GOOD_ANSWER → WEIRD [C7], confidence low

Q: Which closed work orders lack enough asset, test or outcome evidence for estates teams to rely on the stated result?

- **before (19 s):** "The building’s records show that **all 15 completed work orders** do not contain enough asset, test or outcome evidence for estates teams to rely on the stated result. None of the completed records have a comment, test result, or other evidence field populated…"
- **after (12 s):** "The records do not contain any evidence of asset, test or outcome for closed work orders. They record the following for each work order: - **Status** (completed, in_progress, open) - **Label** (e.g., “Fault investigation”, “Annual service”) - **Location** (e.g…"
- **why weird:** 'The records do not contain any evidence of asset, test or outcome for closed work orders' followed by its own field list including '**Primary system** (e.g., AEP-002, AEP-011)' — asset evidence is recorded; and no work order is named, where the baseline listed the 15 completed orders lacking test/outcome evidence.
- **likely cause:** Same register; the narration declined ('do not contain any evidence of asset, test or outcome') while listing a primary-system field, and no longer names the 15 completed orders.

### row 105 (VE-071, Visitors and event attendees) — GOOD_ANSWER → WEIRD [C4], confidence high

Q: The event room has changed. What is the new confirmed room, and what public route should I take?

- **before (11 s):** "The **Postgraduate welcome** event (EVT‑2026‑0045) has been moved. - **New confirmed room:** **Room 1.04 — Common Area / Atrium** - **Public route to use:** **Main Entrance** (the event’s visitor entrance is listed as “Main Entrance”). --- **You might also ask…"
- **after (24 s):** "I’m sorry, but the building model doesn’t contain information about the event room’s new location or the public route to get there. The data I have shows how many sensors each space holds, but it doesn’t record room changes or navigation routes. **What the mod…"
- **why weird:** 'the building model doesn't contain information about the event room's new location or the public route ... The data I have shows how many sensors each space holds' with sensor counts per floor — the baseline answered from the event register (EVT-2026-0045 moved to Room 1.04).
- **likely cause:** Predicted: 'event' no longer selects PublicEvent; the metadata RAG path answered with sensor counts per floor and 'the building model doesn't contain information about the event room's new location'. Fixed on the post-fix re-ask.

High-confidence regressions: 6, 12, 26, 49, 69, 87, 105. Medium/low: 25, 36, 55, 70, 81, 84, 92, 102.

Three patterns account for most of them: (a) vocabulary changes that moved a question off the register that answered it (6, 26, 84, 105 — all four predicted by the baseline reader's offline reach, and 12, 25, 81 by the same mechanism, unpredicted); (b) the same register narrated worse this time — attribution, a blanket certification, a misread field (36, 55, 69, 70, 87, 92, 102), which is run-to-run narration variance as much as a code change and should be re-asked before being blamed on a fix; (c) one new capture: a question filed as a report (49).

## Per-class counts (primary class of each WEIRD row)

| class | name | before | after | after rows |
|---|---|---:|---:|---|
| C1 | Absence guard rewrites a valid decline because a modality alias matched inside another word | 3 | 0 | — |
| C2 | Fetch-budget refusal for whole-building, multi-measurement questions | 2 | 4 | 0, 16, 17, 25 |
| C3 | Narration hygiene: 'the data you provided', raw field names, provenance flags, runaway repetition | 6 | 5 | 32, 41, 69, 77, 87 |
| C4 | Metadata/discovery RAG fallback: 'the ontology you provided', 'add entities', false absence, schema narrated as fact | 6 | 14 | 4, 12, 13, 28, 44, 57, 75, 76, 81, 88, 105, 121, 129, 139 |
| C5 | 'I understood the question but could not put an answer together' — lane jargon, no content | 4 | 6 | 10, 35, 73, 83, 95, 119 |
| C6a | Recommendation shelf-life and meter-boundary footers attached to answers they do not describe | 4 | 4 | 54, 115, 118, 123 |
| C6b | Deictic referent ('this room', 'here', 'the meeting room') resolved to an arbitrary sensor or declined | 4 | 4 | 74, 100, 101, 137 |
| C7 | Register narration misreads statuses, dates and fields, or invents conclusions | 18 | 17 | 3, 11, 15, 21, 27, 33, 36, 45, 51, 60, 63, 64, 70, 92, 102, 107, 113 |
| C8 | Register chosen on a single bare word; the lane then declines with unrelated register statistics | 14 | 8 | 1, 30, 42, 48, 72, 85, 97, 98 |
| C9 | The building holds the data but no lane reaches it (false absence) | 9 | 8 | 20, 43, 55, 66, 86, 111, 122, 134 |
| C10 | Document lane returns a bare fragment or an internal token as the whole answer | 4 | 5 | 26, 31, 93, 104, 143 |
| C11 | Catch-all 'documents do not answer this' for out-of-scope, planning or analytic requests | 6 | 12 | 8, 53, 78, 80, 82, 84, 90, 91, 103, 112, 144, 146 |
| C12 | Open-domain questions answered from general model knowledge, unlabelled | 4 | 4 | 135, 136, 141, 142 |
| C13 | Deliberation lane: an unmapped phrase blocks the query, rankings pick out-of-band spaces, routes reach ranking | 5 | 4 | 58, 61, 99, 117 |
| C14 | Compare/trend fallback claims 'no measured series' | 2 | 1 | 9 |
| C15 | 'You can add it — upload a TTL' enablement hint as the answer (baseline: COVERED by TODO-692) | 2 | 0 | — |
| C16 | Anomaly question answered from user reports, with UUIDs as place names | 1 | 1 | 29 |
| C17 | Future or hypothetical questions answered by the current-reading lane | 2 | 1 | 128 |
| C18 | Report lane answers a non-report question and recommends metadata edits | 1 | 1 | 96 |
| C19 | Assorted shortcut misroutes (operator shortcut, building figures, compliance template, space listing, readiness lane, sensor census) | 5 | 6 | 14, 46, 47, 71, 89, 110 |
| C20 | Referent gate treats a descriptive phrase as a named space | 1 | 1 | 2 |
| C22 | Recommend lane produces generic advice not grounded in the building | 4 | 4 | 56, 109, 132, 145 |
| NEW:closure-shortcut | A closure-list shortcut answers any question mentioning closures with the raw closure list, ignoring what was asked | 0 | 2 | 6, 24 |
| NEW:question-filed-as-report | A question is captured by report intake and filed as a maintenance ticket (write side effect) | 0 | 1 | 49 |
| **total** | | **107** | **113** | |

Only the primary class is counted, as in the baseline. C21 does not exist in either list. C15 went to zero because TODO-692 removed the TTL instruction for non-admins, but both of its rows depended on the absence being true, and it was (rows 39, 114).

Movement worth reading: C8 14→8, C11 6→12, C4 6→14, C5 4→6. The register-capture declines (C8) partly moved into the document catch-all (C11), the metadata RAG fallback (C4) and the 'could not put an answer together' template (C5): the wrong register is no longer chosen, and nothing better answers instead.

### Phrases counted mechanically across all 147 answers (secondary defects included)

| phrase | baseline answers | rerun answers |
|---|---:|---:|
| meter footer 'Boundary: not declared' | 7 | 10 |
| recheck footer 'Switch if: conditions in the space you chose' | 7 | 7 |
| 'Evidence time: unknown' | 4 | 4 |
| user attribution ('you provided' / 'records or data you have' / 'you retrieved' / 'query you ran') | 9 | 15 |
| 'simulated' | 3 | 1 |
| TTL / upload instruction | 5 | 0 |
| 'The room holds N records' | 9 | 0 |
| 'add or update it' (document sentence) | 6 | 0 |
| 'The owner of that record holds the answer.' | 0 | 19 |
| 'I understood the question but could not put an answer together' | 4 | 6 |
| 'That question reaches N sensors' | 2 | 5 |
| 'couldn't render the chart' | 2 | 2 |

Every attribution hit was checked by eye ('the area you asked about' inside the meter footer is excluded). Rerun hits: rows 12, 13, 28, 30, 32, 41, 57, 69, 75, 87, 88, 109, 121, 129, 139. The TTL/upload instruction, 'The room holds' and 'add or update it' are gone; user attribution grew from 9 to 15 answers, and the new document-decline sentence appears 19 times.

## What remains, ranked

Ranked by severity, then by how visible it would be to a supervisor watching a live demo, then by row count. 'Demo risk' names the rows most likely to be asked or noticed.

| rank | class | rows | severity | demo visibility | rows |
|---:|---|---:|---|---|---|
| 1 | C13 Deliberation lane: an unmapped phrase blocks the query, rankings pick out-of-band spaces, routes reach ranking | 4 | P1 | very high | 58, 61, 99, 117 |
| 2 | NEW:question-filed-as-report A question is captured by report intake and filed as a maintenance ticket (write side effect) | 1 | P1 | very high | 49 |
| 3 | C7 Register narration misreads statuses, dates and fields, or invents conclusions | 17 | P1 | high | 3, 11, 15, 21, 27, 33, 36, 45, 51, 60, 63, 64, 70, 92, 102, 107, 113 |
| 4 | C4 Metadata/discovery RAG fallback: 'the ontology you provided', 'add entities', false absence, schema narrated as fact | 14 | P1 | high | 4, 12, 13, 28, 44, 57, 75, 76, 81, 88, 105, 121, 129, 139 |
| 5 | C9 The building holds the data but no lane reaches it (false absence) | 8 | P1 | high | 20, 43, 55, 66, 86, 111, 122, 134 |
| 6 | C3 Narration hygiene: 'the data you provided', raw field names, provenance flags, runaway repetition | 5 | P1 | high | 32, 41, 69, 77, 87 |
| 7 | C6b Deictic referent ('this room', 'here', 'the meeting room') resolved to an arbitrary sensor or declined | 4 | P1 | high | 74, 100, 101, 137 |
| 8 | C22 Recommend lane produces generic advice not grounded in the building | 4 | P1 | high | 56, 109, 132, 145 |
| 9 | C16 Anomaly question answered from user reports, with UUIDs as place names | 1 | P1 | high | 29 |
| 10 | C6a Recommendation shelf-life and meter-boundary footers attached to answers they do not describe | 4 | P2 | very high | 54, 115, 118, 123 |
| 11 | C5 'I understood the question but could not put an answer together' — lane jargon, no content | 6 | P2 | high | 10, 35, 73, 83, 95, 119 |
| 12 | C19 Assorted shortcut misroutes (operator shortcut, building figures, compliance template, space listing, readiness lane, sensor census) | 6 | P2 | high | 14, 46, 47, 71, 89, 110 |
| 13 | C10 Document lane returns a bare fragment or an internal token as the whole answer | 5 | P2 | high | 26, 31, 93, 104, 143 |
| 14 | NEW:closure-shortcut A closure-list shortcut answers any question mentioning closures with the raw closure list, ignoring what was asked | 2 | P2 | high | 6, 24 |
| 15 | C20 Referent gate treats a descriptive phrase as a named space | 1 | P2 | high | 2 |
| 16 | C8 Register chosen on a single bare word; the lane then declines with unrelated register statistics | 8 | P2 | med | 1, 30, 42, 48, 72, 85, 97, 98 |
| 17 | C2 Fetch-budget refusal for whole-building, multi-measurement questions | 4 | P2 | med | 0, 16, 17, 25 |
| 18 | C14 Compare/trend fallback claims 'no measured series' | 1 | P2 | med | 9 |
| 19 | C17 Future or hypothetical questions answered by the current-reading lane | 1 | P2 | med | 128 |
| 20 | C18 Report lane answers a non-report question and recommends metadata edits | 1 | P2 | med | 96 |
| 21 | C11 Catch-all 'documents do not answer this' for out-of-scope, planning or analytic requests | 12 | P3 | med | 8, 53, 78, 80, 82, 84, 90, 91, 103, 112, 144, 146 |
| 22 | C12 Open-domain questions answered from general model knowledge, unlabelled | 4 | P3 | med | 135, 136, 141, 142 |

### Most visible to a supervisor in a live demo

These are the classes a supervisor would most likely see within a handful of questions, and the rows that show them. A demo question that resembles one of these rows is a live risk.

1. **C7 — register narration invents conclusions (17 rows, P1).** The most common defect after the fixes, and it reads as confident fact. The worst for a demo: row 63 (an emergency-message question answered with an instruction for a 'Mechanical Technician' to 'mark the alarm as closed'), row 70 ('Short answer: Yes ... all required accessible features ... are available' while Lift B is both in and out of service in its own table), row 60 ('all of which meet your confidential ... criteria' from a noise profile), row 64 ('Your access and workspace type are confirmed for the evening'), row 107 (a companion waiting permission no record states), row 113 ('8 plant items currently operating outside their normal schedule' from static duty figures).
2. **C4 — metadata RAG fallback: 'the ontology data you provided', false absence (6 → 14 rows, P1).** It more than doubled. The owner has said 'you provided' must never reach a user, and it now appears on rows 12, 13, 28, 57, 75, 121, 129, 139. Row 57 tells a person with accessibility needs that the building has no toilet records; row 105 (rerun) told a visitor the building does not know the moved event room (fixed on re-ask); row 88 says there are no occupancy sensors.
3. **C13 — deliberation lane ranks the wrong thing (4 rows, P1, very high).** The ranking dossier is the most impressive-looking output, so it is the most likely to be shown, and it is wrong on all four: row 117 ('I'm pregnant and overheating' → 'I couldn't map part of your request'), row 99 (a research laboratory recommended to a student, raw IRIs in the dossier, 'Recheck by 17:10' for next Wednesday), row 61 (a step-free route answered with an office), row 58 (seating answered with offices all scoring 0).
4. **NEW:question-filed-as-report (1 row, P1, very high).** Row 49: an insurer's question was logged as maintenance ticket REP-7420E1 and 'An administrator has been notified'. A write side effect in front of a supervisor is worse than any wrong sentence, and nothing says it is limited to that wording.
5. **C6a — footers that describe nothing (4 primary rows, P2, very high).** The meter-boundary footer or the 'Switch if: conditions in the space you chose' recheck footer appears on 14 rerun answers in total, most of them as a secondary defect (11, 36, 54, 56, 75, 76, 109, 113, 115, 118, 119, 123, 132, 145). It is attached to register tables, declines and a funding ranking, so a supervisor will see it within a few questions.

Close behind: **C11** (12 rows) — 'Abacws Building's documents do not answer this ... The owner of that record holds the answer.' is now the single most repeated sentence in the run, and 'that record' never names a record. One such decline is fine; three in a demo reads as a canned brush-off. **C5** (6 rows) — 'The ontology lane, the time-series lane ran' is internal jargon. **C8** (8 rows) — declines that list the statistics of an unrelated register ('They record 10 operating regime entries' for a shared desk).


## Things I could not tell

- **Whether the net worsening is real or reader and run variance.** Both runs are one sample each at a non-zero temperature. Seven of the fifteen regressions (36, 55, 69, 70, 87, 92, 102) come from the same register and lane narrating worse, not from a routing change. They could flip back on a re-ask. Five of them (36, 55, 70, 92, 102) are medium or low confidence. If all five were really fine, the weird count would be 108, not 113: flat against the baseline's 107, not better. The claim I will stand behind is **no measurable improvement in the weird share**, not a precise worsening.
- **Whether READER-2 is stricter than READER.** I applied the baseline's written definitions and matched its precedents: raw field names alone were not enough for WEIRD (row 12), past dates carried as current were tolerated at low confidence (row 22), and clarifications count as GOOD_DECLINE (rows 127, 138). I did not re-label the baseline. Without a second reader on the same rerun, a systematic difference cannot be ruled out, and it would move borderline rows in the same direction on both runs.
- **The four post-fix rows (26, 72, 84, 105).** I have only the summary, not the answers. On that summary, 72 and 105 would now be GOOD_ANSWER, while 26 (the 'would not block a stretcher' claim) and 84 (today's events not listed) would still be WEIRD. That would give 111 weird rather than 113. The headline uses the rerun as recorded.
- **False-absence claims** rely on the baseline reader's read-only SPARQL counts (calibration dates on 1,929 sensors, AVReadiness 22, CleaningTask 30, FirstAidPoint, ToiletFacility, 16 AccessibleRoute), or on another answer in the same run. I ran no query. The FCU claim on row 121 rests on work orders naming 'Fan Coil Unit Room 5.03' (row 125). The drinking-water points on row 132 rest on the baseline read.
- **Row 49 (question filed as a report).** I cannot tell whether the ticket REP-7420E1 still sits in user_reports or whether the notification went out. Both would matter if the demo store is shown.
- **Rows 70 and 22 (Lift B).** The accessible-route register itself may hold Lift B as in_service on RTE-010 and out_of_service on RTE-016. If so, the conflict is in the data, and the defect is only that the narration reports it as fine. I cannot tell which.
- **Rows 19, 34, 59, 79, 94, 116, 133 are GOOD at low confidence.** Each is honest but weaker than it could be (19 omits that the level-3 sharps point is overdue, 34 and 116 drop evidence the baseline had shown, 59 says all 28 workspaces are authorised though one is staff-only).
- **Latency** is not graded. Rerun answers over 60 s: rows 15 (103 s), 44 (70 s), 49 (96 s), 51 (60 s), 75 (209 s), 88 (60 s), 89 (78 s), 96 (129 s), 99 (123 s), 100 (125 s), 140 (63 s). Row 75 at 209 s is the slowest in the rerun; row 59 fell from 218 s to 17.5 s.

