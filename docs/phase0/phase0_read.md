# Phase 0 answers, labelled by hand (READER)

- input: `docs/phase0/phase0_baseline.md.jsonl` — 147 answers via `/v1` streaming as facility01, 2026-09-17 14:10–15:20, BEFORE today's offline fixes were loaded
- every answer was read in full; labels are in `docs/phase0/phase0_read.jsonl`
- WEIRD = the answer would read as broken, off-topic, incomplete, invented or as an instruction to add data. An honest decline of something the building does not hold is GOOD_DECLINE, not a failure.
- FALSE_ABSENCE claims were checked with read-only SPARQL against `bldg` (instance counts, labels, calibration properties). Register selection before and after today's vocabulary was measured OFFLINE with `scripts/register_reach.py`'s scorer (HEAD schema vs working-tree schema, same graph snapshot). That is a prediction, not a live re-ask.
- `confidence` is my confidence in the label. 47 WEIRD labels are `low`/`med`, mostly because I could not tell from the answer alone whether a register's content was misread, or the flag is about framing rather than a false statement.

## Headline

| verdict | n | share |
|---|---:|---:|
| GOOD_ANSWER | 19 | 12.9% |
| GOOD_DECLINE | 21 | 14.3% |
| WEIRD | 107 | 72.8% |

WEIRD at high confidence only: **60 / 147 = 40.8%**. The grader's weird count was 29 (19.7%); by hand it is 107 (72.8%).

## Per stakeholder role

| role | n | good answer | good decline | weird | weird % |
|---|---:|---:|---:|---:|---:|
| Academic office occupants | 3 | 0 | 0 | 3 | 100% |
| Architects and building designers | 3 | 0 | 0 | 3 | 100% |
| BMS-HVAC operators | 3 | 0 | 0 | 3 | 100% |
| Contractor | 1 | 0 | 0 | 1 | 100% |
| Energy manager | 4 | 0 | 0 | 4 | 100% |
| Energy, carbon, and sustainability teams | 3 | 0 | 0 | 3 | 100% |
| Executive | 1 | 0 | 0 | 1 | 100% |
| External maintenance contractors | 3 | 0 | 0 | 3 | 100% |
| Facility Managers / Building Maintenance Teams | 1 | 0 | 0 | 1 | 100% |
| Guests/Visitors | 2 | 0 | 0 | 2 | 100% |
| Health and Safety Officers | 1 | 0 | 0 | 1 | 100% |
| Health and safety officers | 3 | 0 | 0 | 3 | 100% |
| IT, network, and server-infrastructure teams | 3 | 0 | 0 | 3 | 100% |
| IT/Data Scientists | 5 | 0 | 0 | 5 | 100% |
| Lecturers and tutors | 3 | 0 | 0 | 3 | 100% |
| Maintenance technician | 1 | 0 | 0 | 1 | 100% |
| PhD students | 3 | 0 | 0 | 3 | 100% |
| Research staff | 3 | 0 | 0 | 3 | 100% |
| Researchers and data scientists | 3 | 0 | 0 | 3 | 100% |
| Room-booking team | 3 | 0 | 0 | 3 | 100% |
| Student | 1 | 0 | 0 | 1 | 100% |
| Student/Researchers/Academics | 1 | 0 | 0 | 1 | 100% |
| Timetabling team | 3 | 0 | 0 | 3 | 100% |
| Undergraduate students | 3 | 0 | 0 | 3 | 100% |
| Visitor | 2 | 0 | 0 | 2 | 100% |
| Access-control administrators | 3 | 0 | 1 | 2 | 67% |
| Auditors and certification assessors | 3 | 1 | 0 | 2 | 67% |
| Cleaning and caretaking teams | 3 | 1 | 0 | 2 | 67% |
| Facilities managers | 3 | 1 | 0 | 2 | 67% |
| Fire-safety personnel | 3 | 0 | 1 | 2 | 67% |
| Insurers and risk assessors | 3 | 0 | 1 | 2 | 67% |
| Mechanical and electrical engineers | 3 | 0 | 1 | 2 | 67% |
| Occupant | 3 | 0 | 1 | 2 | 67% |
| People with mobility, sensory, or other accessibility requirements | 3 | 0 | 1 | 2 | 67% |
| Professional-services staff | 3 | 1 | 0 | 2 | 67% |
| School leadership, university leadership, and building owners | 3 | 0 | 1 | 2 | 67% |
| Security officers | 3 | 1 | 0 | 2 | 67% |
| Space-planning teams | 3 | 0 | 1 | 2 | 67% |
| Taught postgraduate students | 3 | 1 | 0 | 2 | 67% |
| Teaching and audiovisual support team | 3 | 0 | 1 | 2 | 67% |
| University estates and asset-management teams | 3 | 1 | 0 | 2 | 67% |
| Waste-management teams | 3 | 0 | 1 | 2 | 67% |
| Facility manager | 4 | 1 | 1 | 2 | 50% |
| Retrofit consultant | 2 | 0 | 1 | 1 | 50% |
| Space planner | 2 | 0 | 1 | 1 | 50% |
| Accessibility, inclusion, and well-being teams | 3 | 0 | 2 | 1 | 33% |
| Emergency coordinators | 3 | 2 | 0 | 1 | 33% |
| Emergency responders | 3 | 1 | 1 | 1 | 33% |
| Finance and procurement teams | 3 | 1 | 1 | 1 | 33% |
| Prospective students and family members | 3 | 1 | 1 | 1 | 33% |
| Regulatory and institutional compliance teams | 3 | 1 | 1 | 1 | 33% |
| Visitors and event attendees | 3 | 1 | 1 | 1 | 33% |
| (no stakeholder in bank) | 2 | 2 | 0 | 0 | 0% |
| Building Owners/Property Managers | 1 | 1 | 0 | 0 | 0% |
| Fire service liaison | 1 | 1 | 0 | 0 | 0% |
| Occupants/Tenants/Employees | 1 | 0 | 1 | 0 | 0% |

## Causes (a WEIRD row can carry several)

| cause | rows |
|---|---:|
| WRONG_REGISTER | 30 |
| ADD_DATA_INSTRUCTION | 28 |
| FALSE_ABSENCE | 26 |
| WRONG_LANE_OTHER | 26 |
| INCOMPLETE | 24 |
| OTHER | 24 |
| UNGROUNDED | 23 |
| USER_ATTRIBUTION | 10 |
| ROOM_WORDING | 9 |
| SAYS_SIMULATED | 3 |

Primary (first-listed) cause: WRONG_REGISTER 18, INCOMPLETE 17, ADD_DATA_INSTRUCTION 16, WRONG_LANE_OTHER 15, UNGROUNDED 15, USER_ATTRIBUTION 8, ROOM_WORDING 8, OTHER 6, FALSE_ABSENCE 3, SAYS_SIMULATED 1.

## Grader vs hand labels

- exact verdict agreement (ANSWERED→GOOD_ANSWER, HONEST_DECLINE→GOOD_DECLINE, other buckets→WEIRD): **67/147 = 45.6%**
- weird-or-not agreement: **69/147 = 46.9%**

| grader bucket \ hand | GOOD_ANSWER | GOOD_DECLINE | WEIRD |
|---|---:|---:|---:|
| ANSWERED | 17 | 0 | 42 |
| HONEST_DECLINE | 2 | 21 | 36 |
| ADD_DATA_INSTRUCTION | 0 | 0 | 14 |
| WRONG_LANE | 0 | 0 | 6 |
| INCOMPLETE | 0 | 0 | 9 |
| INVENTED | 0 | 0 | 0 |

Where the grader disagrees most:

1. **ANSWERED but WEIRD: 42 rows.** Confident register narration that misreads or invents (rows 11, 19, 27, 41, 43, 44, 60, 64, 83, 85, 107, 113), 'The room holds N records' on answers otherwise graded good, wrong-lane content that has the shape of an answer (29, 47, 61, 71, 96, 99, 110, 128), footers (54, 56, 132, 145) and open-domain prose. The grader's rules read SHAPE, so none of these can be seen: rows 11, 19, 21, 27, 29, 41, 43, 44, 45, 47, 54, 56, 60, 61, 64, 71, 72, 76, 77, 80, 83, 85, 93, 95, 96, 99, 101, 107, 109, 110, 113, 117, 119, 128, 132, 135, 136, 139, 141, 142, 145, 146.
2. **HONEST_DECLINE but WEIRD: 36 rows.** Declines that cite an unrelated register ('They record 20 access-permission groups' for a Changing Places toilet), 'the records you have', false absences of data the graph holds (calibration, AV readiness, cleaning tasks, projectors), RAG prose telling a security officer to 'Add Security record entities', and the 'no measured series' and 'couldn't verify coverage' non-answers: rows 1, 2, 3, 4, 8, 9, 13, 15, 17, 20, 30, 32, 33, 37, 42, 46, 50, 51, 57, 58, 62, 63, 66, 73, 75, 78, 79, 86, 91, 97, 98, 104, 115, 121, 122, 129.
3. **Grader WEIRD but hand GOOD: 0 rows** (none).

## What today's offline fixes cover

| status | rows | share of WEIRD |
|---|---:|---:|
| COVERED | 8 | 7% |
| PARTLY_COVERED | 42 | 39% |
| UNCOVERED | 57 | 53% |

Fix IDs cited on covered/partly rows: CAVEAT-650 ×20, TODO-692 ×18, BUG-678 ×9, TODO-696 ×5, BUG-679 ×3, BUG-663 ×2, BUG-698 ×2, BUG-693 ×1, BUG-652 ×1, TODO-490 ×1.

How to read this:

- **COVERED** means a landed offline fix removes the defect I labelled, judged from the code in the working tree (e.g. `enablement_hint` now returns '' for non-admins) or from offline register reach. None is verified live.
- **PARTLY_COVERED** means a landed fix removes one cause and another remains. The usual pairs: wording fixed but the misread content stays (BUG-678 + C7); the ApprovalRecord capture removed (CAVEAT-650) but the right register still not reached (C9); the TTL instruction hidden (TODO-692) but the false absence or missing clarification stays.
- Rows whose only owner is an OPEN row (BUG-679, BUG-693, BUG-699, BUG-670) are counted as UNCOVERED, and the open ID is named in `fix_ids`.
- **Even if everything landed today works exactly as intended, 99 of 107 weird rows keep at least one visible defect.**

### Covered rows

- row 4 (AC-064): CAVEAT-650 — Bare 'evidence' removed from ApprovalRecord; offline reach selects no register. Which lane answers instead is unverified.
- row 39 (FS-041): TODO-692 — grounding_guard.enablement_hint now returns '' unless the role holds system:admin (defaults to False).
- row 45 (IT-078): BUG-678 — Opening now 'There are N records in total'.
- row 50 (IR-034): CAVEAT-650 — Bare 'collection' removed from WasteCollectionPoint; offline reach selects no register.
- row 52 (LT-059): TODO-692 — capability_agent now appends that sentence only when reader_is_admin_in(state).
- row 57 (AR-052): CAVEAT-650, TODO-696 — Offline reach: no register; AccessibilityFeature/ToiletFacility kinds reached.
- row 73 (RS-078): CAVEAT-650 — Offline reach selects no register.
- row 114 (Q516): TODO-692 — enablement_hint empty for non-admins.

## Regression risk from today's vocabulary (offline prediction; verify live)

Offline reach with the working-tree schema moves these rows, which were fine or partly fine in the baseline, off the register that answered them:

- row 6 (AI-048, GOOD_DECLINE): register before `ClosurePeriod` → after `None`. Q: Have closures, room moves and route changes reached each affected attendee and accompanying person through their selected authorised channels before travel?
- row 26 (ER-008, GOOD_ANSWER): register before `AccessibleRoute` → after `None`. Q: Which boundary-to-door route is currently evidenced for ambulance crews, stretcher teams and responders on foot, including step-free constraints?
- row 84 (SO-031, GOOD_ANSWER): register before `PublicEvent` → after `None`. Q: Which events are due today, and which approved Security arrangements are current, missing or no longer valid for each one?
- row 105 (VE-071, GOOD_ANSWER): register before `PublicEvent` → after `None`. Q: The event room has changed. What is the new confirmed room, and what public route should I take?
- row 72 (RS-068, WEIRD): register before `AccessibleRoute` → after `WorkspaceProfile`. Q: The lift on my usual route is unavailable. What current step-free alternative or suitable relocated workspace is officially verified?

The guard set (124 questions) passed with 0 violations, so these phrasings are not in it. 'step-free', 'event(s)' and 'closures' are ordinary stakeholder words. Rows 26 and 72 are step-free route questions.

## Defect classes that remain after today's fixes (UNCOVERED, plus PARTLY residue)

| rank | class | uncovered rows | partly rows | severity | demo visibility |
|---:|---|---:|---:|---|---|
| 1 | C7 Register narration misreads statuses, dates and fields, or invents conclusions | 8 | 9 | P1 | high |
| 2 | C8 Register chosen on a single bare word; the lane then declines with unrelated register statistics | 4 | 6 | P2 | med |
| 3 | C9 The building holds the data but no lane reaches it (false absence) | 3 | 6 | P1 | high |
| 4 | C4 Metadata/discovery RAG fallback: 'the ontology you provided', 'add entities', false absence | 5 | 1 | P1 | high |
| 5 | C19 Assorted shortcut misroutes (operator shortcut, building figures, compliance template, space listing, readiness lane) | 5 | 0 | P2 | high |
| 6 | C3 Narration hygiene: 'the data you provided', raw field names, provenance flags, runaway repetition | 3 | 3 | P1 | high |
| 7 | C5 'I understood the question but could not put an answer together' — lane jargon, no content | 4 | 0 | P2 | high |
| 8 | C10 Document lane returns a bare fragment or an internal token as the whole answer | 4 | 0 | P2 | high |
| 9 | C12 Open-domain questions answered from general model knowledge, unlabelled | 4 | 0 | P3 | med |
| 10 | C13 Deliberation lane: an unmapped phrase blocks the query, rankings pick out-of-band spaces, routes reach ranking | 2 | 3 | P1 | very high |
| 11 | C1 Absence guard rewrites a valid decline because a modality alias matched inside another word | 3 | 0 | P2 | high |
| 12 | C22 Recommend lane produces generic advice not grounded in the building | 2 | 2 | P1 | high |
| 13 | C6b Deictic referent ('this room', 'here', 'the meeting room') resolved to an arbitrary sensor or declined | 2 | 2 | P1 | high |
| 14 | C6a Recommendation shelf-life and meter-boundary footers attached to answers they do not describe | 1 | 3 | P2 | very high |
| 15 | C11 Catch-all 'documents do not answer this' for out-of-scope or planning requests | 0 | 5 | P3 | med |
| 16 | C2 Fetch-budget refusal for whole-building, multi-measurement questions | 2 | 0 | P2 | med |
| 17 | C17 Future or hypothetical questions answered by the current-reading lane | 2 | 0 | P2 | med |
| 18 | C20 Referent gate treats a descriptive phrase as a named space | 1 | 0 | P2 | high |
| 19 | C16 Anomaly question answered from user reports, with UUIDs as place names and test-report pollution | 1 | 0 | P1 | high |
| 20 | C14 Compare/trend fallback claims 'no measured series' and lists snake_case modality names | 0 | 2 | P2 | med |
| 21 | C18 Report lane answers a non-report question and recommends metadata edits | 1 | 0 | P2 | med |

### C7 — Register narration misreads statuses, dates and fields, or invents conclusions

**Severity P1 · demo visibility high**

UNCOVERED:
- row 11 (AD-058, Architects and building designers) — Table headed '### Water-supply & drainage assets' lists AHU-00..05, the exhaust fan and breaker panels; opens '21 of the 24 assets' but shows 19. _[Register narration misfit; no fix today.]_
- row 15 (BM-003, BMS-HVAC operators) — 'The records do not show any **late starts**. They do record approved exceptions that extend the stop time' — planned exceptions narrated as late running; no observed run data consulted.
- row 19 (CT-065, Cleaning and caretaking teams) — 'the **next authorised collection is scheduled for 8 September 2026**' (asked 17 Sep) and 'Each bin should contain waste that has reached or exceeded its approved fill threshold'. _[No date anchoring of register dates against today.]_
- row 21 (EC-073, Emergency coordinators) — 'Critical activities that are currently displaced ... Why it's displaced: No alternative location or path is recorded.' — lack of a recorded alternative narrated as displacement.
- row 27 (SU-011, Energy, carbon, and sustainability teams) — 'Of those 5, only **3** have a clear justification ... 1 override, 1 specialist service, 2 overrides' (adds to 4); justification types assigned by the narrator.
- row 60 (PHD-043, PhD students) — Under '**Floor 3**' the table lists 'Seminar room 2.15' and 'Meeting room 4.11/4.12'; confidentiality never addressed.
- row 79 (RB-033, Room-booking team) — '**Confirmed bookings** (11 records) – remain protected from release ... **Cancelled** ... can be released' — a release rule nobody recorded, for an unnamed room.
- row 107 (VE-050, Visitors and event attendees) — 'the companion can wait at the **visitor entrance (Main Entrance)** while the session takes place' — a waiting permission no record states.

PARTLY_COVERED:
- row 3 (AC-056, Access-control administrators) — 'None of these Permission group records contain a `recordOwner` ... Therefore, the orphaned permission groups are: APR-009 ...' — orphan status inferred from fields the approval register never carries. _[Offline reach now selects AccessPermission (right register); the narration that turns an absent field into a finding (C7) is not addressed.]_
- row 41 (FS-062, Fire-safety personnel) — 'The room holds 32 records ... All 26 current approval records have an evidenceKind and an evidenceDate, so they contain evidence of placement, operation and coverage.' _[Wording fixed; offline reach moves to HandoverRecord; the inference narration is not addressed.]_
- row 43 (HS-029, Health and safety officers) — 'The room holds 12 records ... records **verified impairments** ... CP-007 Fire alarm monitoring and call-out' — 'verified' (tested alternative) read as a verified impairment. _[Only the opening wording is fixed; offline reach still selects ContinuityProvision and the misreading stands. Safety-relevant.]_
- row 44 (HS-071, Health and safety officers) — 'Because the evidence is recorded in the building's system, it is automatically permissioned (only the record owner can view it), traceable ... and reproducible'. _[Wording fixed and ApprovalRecord no longer selected; invented assurance claims are not addressed.]_
- row 64 (PS-071, Professional-services staff) — 'Your **access** and **workspace** needs are officially confirmed for the evening of 17 September 2026' — from a policy record and room-use approvals. _[Offline reach moves to WorkspaceProfile; confirming a personal entitlement from policy rows is not addressed.]_
- row 72 (RS-068, Research staff) — 'The room holds 12 records in total — verified 6 ...' then 'liftStatus in_service ... isStepFree true' before a useful step-free alternative. _[Wording fixed. REGRESSION RISK: offline reach with today's vocabulary selects WorkspaceProfile ('workspace') instead of AccessibleRoute.]_
- row 83 (LB-006, School leadership, university leadership, and building owners) — 'APR-005 – Room 1.06 Computer Lab ... Uses the same room as the public-event space (APR-006)' — APR-006 is Room 1.04; clashes invented from approvals. _[ApprovalRecord no longer selected offline; invention by narration not addressed.]_
- row 85 (SO-013, Security officers) — 'Lift fault | Lift service (step-free access) | CP-012 | none | The lift is not available' and 'Door release is overdue for testing; the door is effectively unavailable' while RTE-016 is recorded closed. _[Only wording fixed; continuity register still misread.]_
- row 113 (Q306, Facility manager) — '**9 plant assets that are operating below their commissioned (scheduled) duty at the moment**' — 8 rows, static register duty narrated as 'right now' — + meterServes footer. _[Meter wording only.]_

**Root-cause hypothesis.** The register lane hands whole registers to the model with free interpretation. No 'today' anchoring ('next collection 8 September' on 17 Sep), no glossary for status values ('verified' read as 'verified impairment'), no check that cited IDs, counts or floors match the rows. `register_facts` dictates only the count sentence (BUG-642/678).

**Suggested fix (building-agnostic).** Precompute per-row temporal flags (past/overdue/upcoming vs `store_now`) and pass them as fields. Inject the schema's `rdfs:comment` for status values and properties. Verify after narration that every cited ID exists, every count equals a computed count and every floor grouping matches the row. Instruct that any conclusion not stated by a field is 'not recorded'. All derived from the schema, so building-agnostic.

### C8 — Register chosen on a single bare word; the lane then declines with unrelated register statistics

**Severity P2 · demo visibility med**

UNCOVERED:
- row 1 (AO-031, Academic office occupants) — Shared-desk availability declined with 'They record operating regimes for HVAC and lighting systems in the building.' _[Offline reach with today's vocabulary STILL selects OperatingRegime (term 'unoccupied'); the single-word ranker (BUG-693) is open.]_
- row 30 (MC-035, External maintenance contractors) — 'the building's data do not contain any information about maintenance, setpoint ... changes ... They only describe the operating regimes'. _[Offline reach still selects OperatingRegime ('setpoint').]_
- row 97 (TT-070, Timetabling team) — Fairness-check question: 'They record 20 access-permission group entries'. _[Offline reach still selects AccessPermission ('permissions').]_
- row 98 (TT-025, Timetabling team) — 'none of the 32 approval records ... record a current approval for a hybrid lecture-capture ... APR-032 ... is due_review ... so it is not yet in force' (12 AVEquipment, 22 AVReadiness records exist). _[Offline reach still selects ApprovalRecord ('approved').]_

PARTLY_COVERED:
- row 42 (HS-063, Health and safety officers) — 'the building's data do not contain any information about first-aid cover ... They record only hazard control details' (FirstAidPoint 'Defibrillator (AED) and first aid' exists). _[FirstAidPoint kind is now reachable, but HazardControl ('hazards') is still selected offline.]_
- row 51 (LT-001, Lecturers and tutors) — 'The records do not contain a 9 a.m. lecture. They do record a **Doctoral symposium**' — no timetable consulted, no clarification about which lecture. _[Offline reach now selects TimetabledSession ('lecture'); the personal referent still needs a clarification.]_
- row 63 (PS-076, Professional-services staff) — Alarm instruction question: 'They record 14 coordination function records, with 9 confirmed and 5 provisional statuses.' — no pointer to the official channel the boundary requires. _[Offline reach now names AlarmEvent as absent; alarm data is prepared, not loaded.]_
- row 78 (RB-034, Room-booking team) — No-show question: 'They only record approval status, evidence kind, effective dates, and review dates.' (16 bookings and occupancy sensors exist). _['owner' removed; Booking still not selected offline.]_
- row 80 (RB-010, Room-booking team) — Room-booking alternatives answered 'Level 3 riser cupboard (secondary comms room) ... Gas Boiler 2 — Building Central Plant (standby)'. _[Wording fixed; offline reach predicts no register, but the live pick came from a term the offline model did not predict — unverified.]_
- row 104 (EA-025, University estates and asset-management teams) — Condition-based maintenance tasks declined from coordination functions: 'They only record each task's status, system state, fallback control, activation criterion' (25 ServiceSchedule records exist). _['fallback' capture removed; ServiceSchedule not reached.]_

**Root-cause hypothesis.** `record_registry` selects a register on one bare-word hit with no minimum score (BUG-693, OPEN). When the chosen register lacks the asked field, the lane declines ('They record 20 access-permission groups') instead of trying the next register or lane. Offline reach on today's vocabulary still picks OperatingRegime('unoccupied'/'setpoint'), AccessPermission('permissions'), ApprovalRecord('approved'), HazardControl('hazards').

**Suggested fix (building-agnostic).** BUG-693 (score floor and specificity, measured against the guard set). When the selected register has no field matching the question, fall through to the next lane before declining.

### C9 — The building holds the data but no lane reaches it (false absence)

**Severity P1 · demo visibility high**

UNCOVERED:
- row 66 (PF-035, Prospective students and family members) — 'you may need to consult other sources (e.g., room capacity data, HVAC logs, or real-time occupancy sensors)' — Room 1.06 has occupancy and CO2 sensors.
- row 122 (Q250, Occupant) — 'The records do not indicate which rooms have a projector, their current availability from 2-4 pm today, or their proximity to the cafe' (AV records 'Room 1.06 projector', 16 bookings, seat counts, cafe amenity exist). _[Offline reach still selects WorkspaceProfile ('room for') alone; nothing composes AV + booking + seats.]_
- row 134 (Q705, Energy manager) — 'The available data consists solely of PIR lighting and intrusion detector activity ... install a dedicated free-cooling monitoring sensor'.

PARTLY_COVERED:
- row 20 (CT-021, Cleaning and caretaking teams) — 'The room holds 32 records in total ... they do not contain any information about washroom service frequency' (30 CleaningTask records exist). _[Wording fixed; offline reach drops ApprovalRecord and reaches ToiletFacility, but CleaningTask is still not selected.]_
- row 46 (IT-027, IT, network, and server-infrastructure teams) — 'These records do not contain any information about connectivity status. They only record access-control permission groups' (8 NetworkService records; stream freshness is known). _[AccessPermission ('access') no longer selected; nothing reaches NetworkService or stream freshness.]_
- row 62 (PHD-077, PhD students) — 'The building's records do **not** contain any sensor-based information about the corridor' followed by approval-record statistics. _[ApprovalRecord no longer selected; the false absence depends on the lane that picks it up.]_
- row 93 (AV-035, Teaching and audiovisual support team) — 'The room holds 32 records ... There are no records that show a room AV function with current evidence' (22 AVReadiness records exist). _[Wording and ApprovalRecord capture fixed; AVReadiness still not reached.]_
- row 95 (AV-010, Teaching and audiovisual support team) — 'APR-008 ... has **no remote-readiness evidence**' and 'stale evidence (reviewDue date already passed): 3 (APR-004, APR-010, APR-019)' — APR-019 is due 2026-09-30. _[ApprovalRecord no longer selected; AVReadiness not reached.]_
- row 111 (Q216, Visitor) — Pushchair from car park: 'I don't have that specific information ... You can add it — upload a TTL' (16 AccessibleRoute records; 'Step-free entrance - Ground Level Parking'). _[Instruction hidden; the false 'no information' remains.]_

**Root-cause hypothesis.** Held registers with no reaching vocabulary (AVReadiness 22, AVEquipment 12 incl. projectors, CleaningTask 30, ServiceSchedule 25, NetworkService 8, Permit 15). Sensor-level properties (`calibratedOn`/`calibrationDueOn` on 1,929 points) have no lane. Multi-register composition (seats + projector + booking + near cafe) is not supported. Plant data (outside-air temperature, dampers) is not reached for free-cooling.

**Suggested fix (building-agnostic).** Add class-level `layTerms` for those registers, one at a time, guard set green (TODO-651 discipline). Add a schema-discovered property query for sensor metadata such as calibration. Add a room-finding composition over WorkspaceProfile + AVEquipment + Booking + amenity proximity.

### C4 — Metadata/discovery RAG fallback: 'the ontology you provided', 'add entities', false absence

**Severity P1 · demo visibility high**

UNCOVERED:
- row 75 (RD-023, Researchers and data scientists) — 'The building ontology data you provided contains information only about noise profile ... If you have additional data sources or a different ontology ... feel free to share them' (1,929 sensors have calibration dates) + 'Evidence time: unknown' footer. _[CAVEAT-654's typed absence covers data intents only; this is the metadata RAG path.]_
- row 86 (SO-072, Security officers) — 'The provided ontology data does **not contain any entities ... that represent Security records** ... Add Security record entities (e.g., `s223:SecurityEvent`) ... please provide it'. _[Metadata RAG path; CAVEAT-654 does not apply.]_
- row 121 (Q358, Maintenance technician) — 'The ontology data you provided does not contain any information about fan-coil units (FCUs) or their filter sizes on floor 4.'
- row 129 (Q440, Facility manager) — 'The provided ontology does not contain any information about drains ... (No such sensors are listed in the current ontology.)' — water-flow sensors and drainage service records exist.
- row 139 (q3991cad9d778, IT/Data Scientists) — 'The building ontology you provided contains information only about **waste collection points**' followed by the full class definition.

PARTLY_COVERED:
- row 76 (RD-010, Researchers and data scientists) — '**Total results:** 3 (all identical, describing the same building)' + meterServes footer. _[Meter wording fixed; RAG narration of 'query results' is not.]_

**Root-cause hypothesis.** `sparql_agent` sends metadata/discovery intents with empty bindings to `answer_semantically`. CAVEAT-654's typed absence deliberately excludes these intents, and BUG-643's gate acts only on quantitative claims under GATED_INTENTS. The RAG prompt generalises from its retrieved slice ('contains information only about waste collection points') and invites the reader to supply data or add `s223:` entities.

**Suggested fix (building-agnostic).** (1) The RAG prompt must never suggest adding or providing data, and must not state what the building lacks: absence comes from a COUNT, as `absence_guard` already argues. (2) For a named thing-kind, run a class/property count, e.g. calibration properties on 1,929 sensors, and answer or decline from it. (3) Treat 'you provided' as a hard post-filter until BUG-679 lands.

### C19 — Assorted shortcut misroutes (operator shortcut, building figures, compliance template, space listing, readiness lane)

**Severity P2 · demo visibility high**

UNCOVERED:
- row 14 (AU-008, Auditors and certification assessors) — Whole answer: '**Abacws Building** — operated by: **Cardiff University Estates**.' to a control-ownership question. _[building_profile.py:87 'who operates' shortcut fires on 'who operates, monitors and evidences'.]_
- row 47 (IT-016, IT, network, and server-infrastructure teams) — Host CPU/memory question answered with 'Live building figures ... Instrumented points in the ontology: 3,512'.
- row 71 (RC-014, Regulatory and institutional compliance teams) — Procedures-vs-policy question answered '**Compliance Check — Zone or Sensor Required** ... 'Is the temperature in Zone 5.28 within ASHRAE 55 comfort limits?''. _[_orchestrator.py ~2694 fallback; also a building literal (Zone 5.28) in core code.]_
- row 89 (SP-065, Space-planning teams) — Space-mix question answered '## Lab **21** space(s) found' listing '41P Collab S | lab'.
- row 110 (WM-047, Waste-management teams) — Loading-area readiness answered '**Room 4.01 — Research Laboratory — no blockers found** ... Display: ready'.

**Root-cause hypothesis.** `building_profile.py:87` matches 'who operates' anywhere. IT host metrics fall to self-description figures. The compliance fallback in `_orchestrator.py` ~2694 is a template carrying a building literal ('Zone 5.28', contract 3). A space-mix question hits the spatial listing. 'operationally ready for the next collection' hits the teaching-room readiness lane.

**Suggested fix (building-agnostic).** Anchor shortcut regexes to the building as object. Give non-building IT an out-of-scope decline. Build the compliance fallback from measured modalities and a real space label. The readiness lane should require a teaching room or session referent.

### C3 — Narration hygiene: 'the data you provided', raw field names, provenance flags, runaway repetition

**Severity P1 · demo visibility high**

UNCOVERED:
- row 33 (FM-014, Facilities managers) — 'The records you have do not contain any information about entrances ... 72 checks already completed (recordStatus = **done**)'. _[Offline reach still selects ComplianceCheck ('inspection'); attribution OPEN.]_
- row 37 (FP-064, Finance and procurement teams) — '32 approval records - 24 current, 1 due_review, 1 no_evidence, 1 expired, 1 pending, 1 withdrawn, ...' repeated ~100 times, then 'the data you have does not provide any record'. _[Degenerate repetition has no owner; attribution OPEN.]_
- row 77 (RD-065, Researchers and data scientists) — '**Environment**: simulated = true' (three times) + 'I summarised the data above but couldn't render the chart'. _[BUG-699 OPEN.]_

PARTLY_COVERED:
- row 8 (AI-054, Accessibility, inclusion, and well-being teams) — 'The records you have do not contain any information about how long people wait for an accessible toilet. They record: 32 approval records'. _[Vocabulary moves it off ApprovalRecord to the ToiletFacility/AccessibilityFeature kinds; 'the records you have' is BUG-679, OPEN.]_
- row 13 (AU-030, Auditors and certification assessors) — 'The 32 approval records you provided do **not** contain any information about the movement, replacement ... of assets' (2,175 ConfigurationPeriod records and 24 work orders exist). _[ApprovalRecord no longer selected offline; attribution (BUG-679) OPEN.]_
- row 32 (MC-069, External maintenance contractors) — 'The 32 approval records you asked about do **not** contain any fields ...' then a table of approvedByRole / accountableRole / evidenceKind. _[ApprovalRecord not selected offline; attribution OPEN.]_

**Root-cause hypothesis.** Narration prompts put retrieved rows in the user turn (BUG-679, OPEN) and pass raw predicate names and provenance flags (BUG-699, OPEN). No repetition or length guard exists on register narration: row 37 printed '1 due_review, 1 no_evidence, ...' about 100 times.

**Suggested fix (building-agnostic).** Frame rows as retrieved from the building's own systems in the system turn. Map predicates to `rdfs:label` before narration and strip `isSimulated`/`nature`. Add a repeated-n-gram detector with a max-token cap that truncates and regenerates once. These are building-agnostic text contracts.

### C5 — 'I understood the question but could not put an answer together' — lane jargon, no content

**Severity P2 · demo visibility high**

UNCOVERED:
- row 10 (AD-052, Architects and building designers) — 'I understood the question but could not put an answer together for it. ... The ontology lane, the time-series lane ran, but returned nothing to report.' _[_orchestrator.py ~994 template unchanged.]_
- row 28 (SU-055, Energy, carbon, and sustainability teams) — 'I understood the question but could not put an answer together for it. ... The ontology lane ran'.
- row 35 (FM-025, Facilities managers) — 'I understood the question but could not put an answer together ... The ontology lane ran' for lighting vs schedule (269 illuminance sensors exist).
- row 103 (EA-076, University estates and asset-management teams) — 'I understood the question but could not put an answer together ... The ontology lane ran'.

**Root-cause hypothesis.** Template in `orchestrator/workflow/_orchestrator.py` ~994 names internal lanes ('The ontology lane, the time-series lane ran') and offers no building content.

**Suggested fix (building-agnostic).** Replace it with the role-aware decline pattern: say plainly that nothing was found for <subject>, then list the closest registers or measured modalities the building holds (from `record_classes` and `present_modalities`). No lane names.

### C10 — Document lane returns a bare fragment or an internal token as the whole answer

**Severity P2 · demo visibility high**

UNCOVERED:
- row 31 (MC-040, External maintenance contractors) — Whole answer: 'Thermographic survey' from the Asset Engineering Register and Maintenance Log.
- row 133 (Q224, Contractor) — Whole answer: 'Incoming main stop valve SV-1' (the building main, not a second-floor isolation).
- row 143 (q711e1631b50f, IT/Data Scientists) — Whole answer: 'calls_ok requires acoustic separation, not merely a door.'
- row 146 (q70c6523737ce, Facility Managers / Building Maintenance Teams) — Semantic-model question answered 'The AV readiness register records equipment relationships as an audio path chain' + 'couldn't render the chart'.

**Root-cause hypothesis.** `capability_agent._answer_from_passages` accepts a composed extract with no minimum shape ('Thermographic survey', 'Incoming main stop valve SV-1', 'calls_ok requires acoustic separation') and accepts passages from registers unrelated to the question.

**Suggested fix (building-agnostic).** Require a full sentence that restates the subject. Reject extracts under a word floor or containing snake_case tokens, and run `grounding_guard.is_on_topic` on the question's subject before composing. On reject, use the documents-do-not-answer decline.

### C12 — Open-domain questions answered from general model knowledge, unlabelled

**Severity P3 · demo visibility med**

UNCOVERED:
- row 135 (q7e048379f5a4, IT/Data Scientists) — Out-of-scope 'why autism happens' answered with general prose ('prenatal exposure to certain medications, infections').
- row 136 (q19ac2643d4e8, IT/Data Scientists) — Out-of-scope ozone question answered with general prose.
- row 141 (q30ebf51cf838, Guests/Visitors) — Glare-sensor physics described in general terms with no building basis.
- row 142 (qb220cfa24ae4, Guests/Visitors) — General CO2 prose ('levels around 1,000–2,000 ppm are often perceived as stale') with none of the building's own CO2 data.

**Root-cause hypothesis.** The general lane answers non-building questions (autism causes, ozone, glare sensors) with no statement that the answer is not from the building. Row 142 (CO2) could have used the building's own CO2 distribution.

**Suggested fix (building-agnostic).** Label general background explicitly or decline non-building topics, especially medical ones. For building-adjacent concepts, add the building's own figures.

### C13 — Deliberation lane: an unmapped phrase blocks the query, rankings pick out-of-band spaces, routes reach ranking

**Severity P1 · demo visibility very high**

UNCOVERED:
- row 58 (AR-027, People with mobility, sensory, or other accessibility requirements) — 'I couldn't verify this building's sensor coverage just now, so I won't rank spaces ... **Evidence time: unknown.**' for a seating-area question (118 s).
- row 119 (Q1045, Space planner) — 'I couldn't map part of your request (by demand; two phone booths) — could you rephrase or drop that part?'

PARTLY_COVERED:
- row 61 (PHD-061, PhD students) — Route request answered 'Best match: Room 5.14 — Academic Office (score 0.1601) ... 'step-free route' isn't a sensed modality here — ignored', dossier column 'simulated | yes'. _[Dossier 'simulated' column fixed; a route question still reaches the ranking lane.]_
- row 99 (UG-001, Undergraduate students) — Calm low-traffic place → 'Best match: Room 4.03 — Research Laboratory ... noise: 84.026, occupancy: 60.391', out of its own 30-70 dB band; dossier shows raw IRIs and 'simulated | yes'. _[Simulated column fixed; the ranking itself is not.]_
- row 117 (Q108, Occupant) — 'I couldn't map part of your request (coolest place to work today; pregnant) — could you rephrase or drop that part?' _[Working-tree compiler folds 'coolest'->'cool'->temperature (BUG-640 area), but any unmapped phrase ('pregnant') still blocks the whole query.]_

**Root-cause hypothesis.** `deliberation/capability_schema.validate` returns CLARIFY when ANY phrase is unmapped ('pregnant', 'by demand'). Scoring is relative among candidates, so a lab at 84 dB wins 'calm, quiet' against a 30–70 dB band. A step-free ROUTE request is ranked as rooms. A coverage-check failure is returned as the answer ('couldn't verify this building's sensor coverage').

**Suggested fix (building-agnostic).** Drop unmappable context with a stated assumption instead of refusing. For comfort-direction constraints, filter out candidates outside the band, or say none qualify. Send wayfinding to AccessibleRoute/CirculationTime. Retry or degrade the coverage check instead of returning it.

### C1 — Absence guard rewrites a valid decline because a modality alias matched inside another word

**Severity P2 · demo visibility high**

UNCOVERED:
- row 24 (ER-010, Emergency responders) — 'I can't complete that request as asked. ... this building **does** have 296 temperature sensor(s)' for temporary works (15 Permit records exist). _[absence_guard alias 'temp' matches 'temporary' and replaces the answer.]_
- row 48 (IR-007, Insurers and risk assessors) — 'I can't complete that request as asked ... 296 temperature sensor(s)' for temporary construction exposure. _[Same 'temp' ~ 'temporary' substring match.]_
- row 88 (SP-066, Space-planning teams) — 'I can't complete that request as asked. ... this building **does** have 270 occupancy sensor(s)'.

**Root-cause hypothesis.** `orchestrator/services/absence_guard.py` `_MODALITY_ALIASES` tokens are matched with no trailing word boundary, so 'temp' matches 'temporary' and 'occupant' matches 'occupants'. `guard_answer` then replaces the WHOLE answer with `correction_text` ('I can't complete that request as asked ... this building does have 296 temperature sensor(s)'). For 'temporary works' the building holds 15 Permit records the replaced answer might have used.

**Suggested fix (building-agnostic).** Put `\b` on both sides of the alias token. Intervene only when the claimed modality is one the QUESTION resolved to (concept resolver). Correct only the false sentence and keep the rest of the answer.

### C22 — Recommend lane produces generic advice not grounded in the building

**Severity P1 · demo visibility high**

UNCOVERED:
- row 109 (WM-062, Waste-management teams) — Waste weight allocation answered 'Assign the total vehicle weight to this zone (Ground Level Parking)' + 'Evidence time: unknown ... the space becomes occupied'.
- row 145 (qeaadc185293b, Student/Researchers/Academics) — 'Install motion sensors or daylight sensors on each floor' (269 illuminance sensors exist) and 'Raise the temperature set-point by 1 °C during 00:00–06:00 ... closer to the day mean' + recheck footer.

PARTLY_COVERED:
- row 56 (ME-053, Mechanical and electrical engineers) — 'Calibrate the Air-Quality Sensors in Zone 5.01 first — Zone 5.01 contains the main entrance and is typically the most heavily trafficked area' (1,929 sensors carry calibratedOn/calibrationDueOn) + meter and recheck footers. _[Only the meter footer wording changes; invented rationale, missed calibration data and recheck footer remain.]_
- row 132 (Q203, Student) — 'Whether you can drink it for free or need to buy bottled water depends on the building's policy' + flow-rate 'recommendations' + meter/recheck footers (13 DrinkingWater points incl. bottle refill points, and a PotabilityStatement exist). _[DrinkingWater kind now reachable offline; whether it pre-empts the recommend lane is unverified.]_

**Root-cause hypothesis.** The analytics/recommend '3-6 actionable recommendations' prompt narrates advice over whatever series was fetched: 'install motion or daylight sensors' in a building with 269 illuminance sensors; 'check with facilities' about tap water in a building with 13 drinking-water points and a potability statement; invented zone roles for calibration. BUG-643's gate does not cover this intent's prose.

**Suggested fix (building-agnostic).** Every recommendation must cite a building fact (row or figure), otherwise drop it. Before recommending installation, check the class count as absence_guard does. Amenity and register questions phrased as advice ('is tap water free') should reach the amenity lane first.

### C6b — Deictic referent ('this room', 'here', 'the meeting room') resolved to an arbitrary sensor or declined

**Severity P1 · demo visibility high**

UNCOVERED:
- row 100 (UG-019, Undergraduate students) — 'here' resolved to an arbitrary sensor: 'Could not build a clean time series for 'Sound/Loudness Sensor installed-node 5.07': too_few_points'.
- row 101 (UG-024, Undergraduate students) — 'this room' resolved to 'CO₂ Level Sensor installed-node 5.01' and 'Temperature data were not provided'.

PARTLY_COVERED:
- row 74 (RS-064, Research staff) — Headache 'in this room' answered in 1.7 s with 'You can add it — ... upload a TTL naming the entity'. _[Instruction removed for non-admins; still no 'which room?' clarification.]_
- row 137 (q49b16d713c45, Health and Safety Officers) — 'What systems are specific for the meeting room?' → 'You can add it — upload a TTL'. _[Instruction hidden; still no 'which meeting room?'.]_

**Root-cause hypothesis.** No guard for a deictic space referent on a first turn. Lanes take the first matching sensor (node 5.07, node 5.01) or fall to the add-data decline. The prior-turn guard that handles 'you mentioned earlier' (row 127, good) has no space equivalent.

**Suggested fix (building-agnostic).** Detect a deictic space referent with no resolvable prior turn and return one clarification ('Which room are you in?') with a short list of candidates. Never bind to a sensor by default.

### C6a — Recommendation shelf-life and meter-boundary footers attached to answers they do not describe

**Severity P2 · demo visibility very high**

UNCOVERED:
- row 115 (Q972, Retrofit consultant) — 'If you have additional data on glazing or roof replacements ... I can help' + '**Evidence time: unknown.** ... Switch if: conditions in the space you chose moves outside the range'.

PARTLY_COVERED:
- row 54 (ME-003, Mechanical and electrical engineers) — Relevant asset-reconciliation table, then '**Boundary: not declared.** ... the meter behind it has no `ontosage:meterServes` in the ontology.' _[meter_boundary wording is now plain for non-admins; the footer still fires on a non-energy answer ('Energy Storage' matches _ENERGY_ANSWER_RE).]_
- row 118 (Q856, Energy manager) — Decline on submetering cost followed by '**Boundary: not declared.** ... no `ontosage:meterServes` in the ontology'. _[Wording plain now; footer still attached to a decline with no energy figure.]_
- row 123 (Q481, Energy manager) — Tariff decline followed by '**Boundary: not declared.** ... no `ontosage:meterServes` in the ontology'. _[Wording plain now; footer misfire remains.]_

**Root-cause hypothesis.** `_recheck_line` (~4803) fires whenever `current_intent == 'recommend'`, even with no chosen space ('Switch if: conditions in the space you chose'). `_meter_boundary_line` (~4916) gates on `_ENERGY_ANSWER_RE` over question+answer TEXT ('Energy Storage', 'energy-efficient', 'metered') plus any digit, and with no meter hit it still prints 'Boundary: not declared'. TODO-692 removed the TTL wording, not the misfire. One or both footers appear on 12 of 147 answers (54, 56, 58, 75, 76, 109, 113, 115, 118, 123, 132, 145), most of them as a SECONDARY defect on rows filed under another class.

**Suggested fix (building-agnostic).** Recheck: require `deliberate_result` with a chosen space. Meter boundary: require that `contributing_uuids` hit a meter (`_mb.match` non-empty); drop the text-regex path.

### C11 — Catch-all 'documents do not answer this' for out-of-scope or planning requests

**Severity P3 · demo visibility med**

PARTLY_COVERED:
- row 53 (LT-005, Lecturers and tutors) — Documents template ('add or update it') for alternative rooms, though 28 WorkspaceProfile records could list eligible alternatives. _[Wording fixed; the document lane still answers a workspace question.]_
- row 82 (LB-013, School leadership, university leadership, and building owners) — 'I searched Stakeholder Group Register, Workspace Profile Register ... add or update it' — the workspace register could answer the mix of settings. _[Wording fixed; lane unchanged.]_
- row 90 (PGT-054, Taught postgraduate students) — Day-plan request: 'documents do not answer this ... add or update it'. _[Wording fixed; a planning request still ends in a document decline.]_
- row 112 (Q753, Visitor) — 'Book me a hotel' → 'documents do not answer this. I searched Room Bookings ... add or update it'. _[Wording fixed; no out-of-scope decline.]_
- row 144 (q9773eb2f64c3, IT/Data Scientists) — 'documents do not answer this. I searched Department Directory ... add or update it'. _[Wording fixed; general question still ends in a document decline.]_

**Root-cause hypothesis.** The capability/document lane is the catch-all. After TODO-692 the add-data sentence is admin-only, but 'Book me a hotel' still reads 'I searched Room Bookings ... The owner of that record holds the answer.'

**Suggested fix (building-agnostic).** Add an out-of-scope decline ('outside what this building assistant does', plus what it can do). Send planning requests ('plan my day') to deliberation or a clarification.

### C2 — Fetch-budget refusal for whole-building, multi-measurement questions

**Severity P2 · demo visibility med**

UNCOVERED:
- row 0 (AO-016, Academic office occupants) — Replies 'That question reaches **296 sensors** ... Narrow it: one measurement at a time (temperature, or CO2 — not both)' to a question that is inherently four measurements at once. _[No fix today touches the sql_agent fetch budget.]_
- row 16 (BM-004, BMS-HVAC operators) — 'That question reaches **296 sensors** — more than I can read and summarise in one request'.

**Root-cause hypothesis.** `orchestrator/agents/sql_agent.py` ~411 refuses when the resolved UUID set exceeds the per-request read budget, and suggests 'one measurement at a time', which cannot express a four-measurement question.

**Suggested fix (building-agnostic).** Aggregate in the store (per space x hour, through the adapter) or hand multi-modality 'best period/which zones' questions to the deliberation lane, which already ranks ~195 spaces. Keep the narrowing message as a last resort, and say which part of the question it would drop.

### C17 — Future or hypothetical questions answered by the current-reading lane

**Severity P2 · demo visibility med**

UNCOVERED:
- row 91 (PGT-002, Taught postgraduate students) — Tomorrow's plan answered 'No data was retrieved ... 100 sensor(s) were identified for this request but returned no rows'.
- row 128 (Q789, Energy manager) — What-if on cutting AHU runtime answered '**0.77 hours** is the latest reading from the AHU Run Time Sensor — Floor 5'.

**Root-cause hypothesis.** 'tomorrow' and 'what happens if' have no scenario lane. The SQL lane queries a future window ('100 sensors returned no rows') or returns the latest reading ('0.77 hours').

**Suggested fix (building-agnostic).** Detect future/hypothetical framing: route to the forecast lane when a series exists, otherwise decline the simulation plainly and give the current baseline.

### C20 — Referent gate treats a descriptive phrase as a named space

**Severity P2 · demo visibility high**

UNCOVERED:
- row 2 (AO-015, Academic office occupants) — ''brief corridor' does not exist in this building, so there is nothing to report about it.' — a phrase in a noise question was treated as a named space; 233 sound sensors exist. _[Referent gate false positive; nothing today changes it.]_

**Root-cause hypothesis.** `referent_resolver.detect_typed_referent` extracted 'brief corridor' from 'a brief corridor-related peak' and declared it absent.

**Suggested fix (building-agnostic).** Assert non-existence only for identifier-like referents (numbers, codes, proper names). A modifier plus a space-type noun is a type filter, not an instance.

### C16 — Anomaly question answered from user reports, with UUIDs as place names and test-report pollution

**Severity P1 · demo visibility high**

UNCOVERED:
- row 29 (SU-004, Energy, carbon, and sustainability teams) — Meter anomaly question answered '4 place(s) with repeat reports' with place 'd 7baf 689-b 028-5ba 7-91a 4-686a 66265659 | other | 556'. _[BUG-670 (anomaly store not consulted) is OPEN; UUID mangling and 556 location-less test reports are unlogged.]_

**Root-cause hypothesis.** 'repeating anomaly' routes to `event_query_service` repeat-report summary (~630) instead of the anomaly store (BUG-670 OPEN: 185k scanner rows). user_reports hold 636 reports whose location is a UUID or missing (probe/test traffic), and a digit/letter spacing pass mangles the UUIDs ('d 7baf 689-b 028').

**Suggested fix (building-agnostic).** Anomaly wording goes to `_anomaly_summary` (with BUG-670). Exclude reports whose location is not a resolvable space and never render raw identifiers. Removing probe-filed reports from the demo store is a data operation for the lead.

### C14 — Compare/trend fallback claims 'no measured series' and lists snake_case modality names

**Severity P2 · demo visibility med**

PARTLY_COVERED:
- row 9 (AD-072, Architects and building designers) — 'I have no measured series for the requested sensor or zone ... What this building measures: air_quality, carbon_monoxide, co2, damper_position' for a design-vs-observed route question (21 CirculationTime records exist). _[Today's code builds the list from MEASURED modalities (damper_position drops out); snake_case names and the compare-lane dead end remain.]_
- row 17 (BM-022, BMS-HVAC operators) — 'I have no measured series for the requested sensor or zone' for a setback-recovery question in a building with 296 temperature sensors. _[Measured-modality list fixed; the false 'no measured series' is not.]_

**Root-cause hypothesis.** `_orchestrator.py` ~2647–2690: when SPARQL yields no UUIDs, the compare branch says 'I have no measured series for the requested sensor or zone' even for zone temperature (296 sensors).

**Suggested fix (building-agnostic).** Say which referent could not be identified and ask for it. Use measurand labels, not identifiers. Try the floor-scoped query for zone/whole-building comparisons before declining.

### C18 — Report lane answers a non-report question and recommends metadata edits

**Severity P2 · demo visibility med**

UNCOVERED:
- row 96 (TT-018, Timetabling team) — Enrolment question answered with a sensor 'Summary Report' recommending 'Define Units for Un-summarised Sensors – Assign appropriate measurement units to the 522 sensors'.

**Root-cause hypothesis.** A timetabling question produced a sensor 'Summary Report' whose LLM recommendations tell the reader to 'Assign appropriate measurement units to the 522 sensors'. That is an add-data instruction outside TODO-692's reach because the model generates it.

**Suggested fix (building-agnostic).** Report recommendations must not instruct data/metadata changes for non-admins (post-filter). Route enrolment/allocation wording to WorkspaceProfile/TimetabledSession.

## Things I could not tell

- Rows 15, 21, 36, 79, 104 and the C12 rows are low confidence. The content may be defensible and the flag is about framing.
- For rows where offline reach now selects no register (4, 46, 50, 62, 73, 83, 93, 95), I cannot tell offline which lane answers instead. COVERED there means the wrong-register defect is gone, not that the answer is good.
- The live baseline sometimes used registers the HEAD-schema reach did not predict (rows 43, 45, 80, 85 used ContinuityProvision), so the live graph's vocabulary at 14:10 was not exactly HEAD's. The 'after' prediction uses the working-tree schema and is the more relevant of the two.
- Latency is not graded here, but 17 answers took over 60 s and 4 took over 150 s (row 46 170 s, 48 151 s, 59 218 s, 99 198 s).

