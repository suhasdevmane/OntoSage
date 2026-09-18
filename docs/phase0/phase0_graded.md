# Stakeholder answer grades

- input: read phase0_baseline.md.jsonl (complete answers)
- bank: docs/phase0/phase0_bank.jsonl
- rows: **147**; transport failures (status not OK): 0

Grades describe the SHAPE of each answer, not whether its facts are true. INVENTED is only ever a low-confidence flag. An honest decline is a correct outcome, not a failure.

| bucket | n | share | of which high confidence |
|---|---:|---:|---:|
| ANSWERED | 59 | 40.1% | 46 |
| HONEST_DECLINE | 59 | 40.1% | 37 |
| ADD_DATA_INSTRUCTION | 14 | 9.5% | 12 |
| WRONG_LANE | 6 | 4.1% | 1 |
| INCOMPLETE | 9 | 6.1% | 8 |
| INVENTED | 0 | 0.0% | 0 |

**Weird** (add-data + wrong lane + incomplete + invented): **29 / 147 = 19.7%**; high-confidence only: 21 / 147 = 14.3%.

| flag (does not change the bucket) | rows |
|---|---:|
| decline_cites_unrelated_source | 9 |
| speaks_as_if_user_supplied_data | 7 |
| remediation_footer | 7 |
| register_summary_calls_it_a_room | 6 |
| general_knowledge_ungrounded | 5 |
| partial_decline | 3 |
| says_simulated | 3 |

<details><summary>Rules that decided the grades</summary>

| rule | rows |
|---|---:|
| answered | 54 |
| decline.lead | 45 |
| decline.unrelated_store | 9 |
| add.add_or_update | 6 |
| lane.short_unrelated | 5 |
| add.you_can_add_it | 5 |
| answered.general_knowledge | 5 |
| incomplete.could_not_put_together | 4 |
| incomplete.cannot_complete_as_asked | 3 |
| incomplete.fetch_budget | 2 |
| decline.no_measured_series | 2 |
| add.footer_on_decline | 2 |
| decline.referent_absent | 1 |
| lane.space_listing | 1 |
| decline.no_prior_turn | 1 |
| decline.privacy_policy | 1 |
| add.install_sensor | 1 |

</details>

## Per stakeholder role

| group | n | answered | decline | add-data | wrong lane | incomplete | invented | weird |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Contractor | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 100.0% |
| Executive | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Health and Safety Officers | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Visitor | 2 | 0 | 0 | 2 | 0 | 0 | 0 | 100.0% |
| Energy manager | 4 | 1 | 0 | 3 | 0 | 0 | 0 | 75.0% |
| Lecturers and tutors | 3 | 0 | 1 | 2 | 0 | 0 | 0 | 66.7% |
| Space-planning teams | 3 | 0 | 1 | 0 | 1 | 1 | 0 | 66.7% |
| IT/Data Scientists | 5 | 3 | 0 | 1 | 1 | 0 | 0 | 40.0% |
| Academic office occupants | 3 | 0 | 2 | 0 | 0 | 1 | 0 | 33.3% |
| Architects and building designers | 3 | 1 | 1 | 0 | 0 | 1 | 0 | 33.3% |
| Auditors and certification assessors | 3 | 1 | 1 | 0 | 1 | 0 | 0 | 33.3% |
| BMS-HVAC operators | 3 | 0 | 2 | 0 | 0 | 1 | 0 | 33.3% |
| Emergency responders | 3 | 1 | 1 | 0 | 0 | 1 | 0 | 33.3% |
| Energy, carbon, and sustainability teams | 3 | 2 | 0 | 0 | 0 | 1 | 0 | 33.3% |
| External maintenance contractors | 3 | 0 | 2 | 0 | 1 | 0 | 0 | 33.3% |
| Facilities managers | 3 | 1 | 1 | 0 | 0 | 1 | 0 | 33.3% |
| Fire-safety personnel | 3 | 1 | 1 | 1 | 0 | 0 | 0 | 33.3% |
| Insurers and risk assessors | 3 | 0 | 2 | 0 | 0 | 1 | 0 | 33.3% |
| Research staff | 3 | 1 | 1 | 1 | 0 | 0 | 0 | 33.3% |
| School leadership, university leadership, and building owner | 3 | 1 | 1 | 1 | 0 | 0 | 0 | 33.3% |
| Taught postgraduate students | 3 | 1 | 1 | 1 | 0 | 0 | 0 | 33.3% |
| Undergraduate students | 3 | 2 | 0 | 0 | 1 | 0 | 0 | 33.3% |
| University estates and asset-management teams | 3 | 0 | 2 | 0 | 0 | 1 | 0 | 33.3% |
| (no stakeholder in bank) | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Access-control administrators | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| Accessibility, inclusion, and well-being teams | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| Building Owners/Property Managers | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Cleaning and caretaking teams | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Emergency coordinators | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Facility Managers / Building Maintenance Teams | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Facility manager | 4 | 2 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Finance and procurement teams | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| Fire service liaison | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Guests/Visitors | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Health and safety officers | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| IT, network, and server-infrastructure teams | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Maintenance technician | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Mechanical and electrical engineers | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Occupant | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Occupants/Tenants/Employees | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| People with mobility, sensory, or other accessibility requir | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| PhD students | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Professional-services staff | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Prospective students and family members | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Regulatory and institutional compliance teams | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Researchers and data scientists | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Retrofit consultant | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Room-booking team | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Security officers | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Space planner | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Student | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Student/Researchers/Academics | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Teaching and audiovisual support team | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Timetabling team | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Visitors and event attendees | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Waste-management teams | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |

## Per category

Catalogue rows carry no category; they are grouped under their source.

| group | n | answered | decline | add-data | wrong lane | incomplete | invented | weird |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Accessibility | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Ambiguous, underspecified & out-of-scope | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Benchmarking & comparison | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Cost & finance | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Generation, storage & grid | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Meta / Strategic Reasoning | 2 | 0 | 0 | 1 | 1 | 0 | 0 | 100.0% |
| Wayfinding & entity resolution | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 100.0% |
| Weather coupling | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Comparative Analysis | 2 | 0 | 1 | 1 | 0 | 0 | 0 | 50.0% |
| (stakeholder_catalogue_37) | 111 | 42 | 50 | 6 | 4 | 9 | 0 | 17.1% |
| Anomaly detection & diagnosis | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Carbon & retrofit | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Causal Diagnosis | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Cleaning & daily operations | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Comfort & place-finding | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Cross-domain / open-ended reasoning | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Current state / lookup | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Documents, compliance & institutional knowledge | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Events & scheduling | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Factual Recall | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Inferential Reasoning | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Lighting & acoustics | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Maintenance, tickets & complaints | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Occupancy & space utilisation | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Personalisation, memory & follow-up | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Prediction & forward-looking | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Retrospective analysis & reporting | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Safety, security & emergency | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| System self-knowledge & explainability | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Systemic Synthesis | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Water & waste | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |

## Every weird answer

### AO-016 — INCOMPLETE (low)

**Q:** Which remaining period today has the best supported balance of temperature, ventilation, light and quiet for concentrated work?

- stakeholder: Academic office occupants
- rule: `incomplete.fetch_budget` — non-answer template: "That question reaches 296 sensors — more than I can read and summarise in one request without ei..." (the boundary permits a clarification; a human may call it a decline)
- flags: —

```
That question reaches **296 sensors** — more than I can read and summarise in one request without either timing out or quietly answering from a fraction of them. Narrow it and I can answer directly: - one floor, or one room - one measurement at a time (temperature, or CO₂ — not both) - a shorter per
```

### AD-052 — INCOMPLETE (high)

**Q:** Which electrical, heating, cooling, ventilation, water and data capacities and connection routes are adequate for the proposal, and where is an upgrade decision needed?

- stakeholder: Architects and building designers
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a sensor data q..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **sensor data** question. - The ontology lane, the time-series lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such data. Rephrasing with a specific ro
```

### AU-008 — WRONG_LANE (low)

**Q:** For each local, shared or inherited control, who operates, monitors and evidences each component, and what must be tested within this unit?

- stakeholder: Auditors and certification assessors
- rule: `lane.short_unrelated` — short answer sharing ['operat'] with the question
- flags: —

```
**Abacws Building** — operated by: **Cardiff University Estates**.
```

### BM-004 — INCOMPLETE (high)

**Q:** Which zones have not stabilised after the approved warm-up or cool-down period should have completed?

- stakeholder: BMS-HVAC operators
- rule: `incomplete.fetch_budget` — non-answer template: "That question reaches 296 sensors — more than I can read and summarise in one request without ei..."
- flags: —

```
That question reaches **296 sensors** — more than I can read and summarise in one request without either timing out or quietly answering from a fraction of them. Narrow it and I can answer directly: - one floor, or one room - one measurement at a time (temperature, or CO₂ — not both) - a shorter per
```

### ER-010 — INCOMPLETE (high)

**Q:** Which temporary works, events, parked plant, barriers or closures have changed emergency access since the latest controlled access plan?

- stakeholder: Emergency responders
- rule: `incomplete.cannot_complete_as_asked` — non-answer template: "I can't complete that request as asked. To be accurate about one thing: this..."
- flags: —

```
I can't complete that request as asked. To be accurate about one thing: this building **does** have 296 temperature sensor(s) — the limitation isn't a lack of sensing. Try narrowing the request (fewer spaces, a coarser interval, or a specific room) and I'll answer from the building's own data.
```

### SU-055 — INCOMPLETE (high)

**Q:** Which planned purchases can be met from verified internal reuse stock without compromising safety, function or timing?

- stakeholder: Energy, carbon, and sustainability teams
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a metadata ques..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **metadata** question about **planned purchases, verified internal reuse stock**. - The ontology lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such d
```

### MC-040 — WRONG_LANE (low)

**Q:** Which next manual test would best distinguish the remaining plausible fault locations while minimising intrusive work?

- stakeholder: External maintenance contractors
- rule: `lane.short_unrelated` — short answer sharing nothing with the question
- flags: —

```
Thermographic survey --- *From Abacws Building's documents: Asset Engineering Register, Maintenance Log. For the current version, contact facility management.*
```

### FM-025 — INCOMPLETE (high)

**Q:** Which rooms have lighting levels or control states that do not fit their current authorised task and schedule?

- stakeholder: Facilities managers
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a sensor data q..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **sensor data** question. - The ontology lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such data. Rephrasing with a specific room, floor or date rang
```

### FS-041 — ADD_DATA_INSTRUCTION (high)

**Q:** Which occupied zones lack confirmed fire-warden or marshal coverage for the current operating period?

- stakeholder: Fire-safety personnel
- rule: `add.you_can_add_it` — instructs the reader to add data: "...facilities / estates management team. You can add it — no code changes needed: 1. Describe i..."
- flags: —

```
I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. You can add it — no code changes needed: 1. **Describe it in the ontology** — upload a TTL naming the entity and its relationsh
```

### IR-007 — INCOMPLETE (high)

**Q:** What temporary exposure is created by active construction, refurbishment, commissioning, relocation or intrusive maintenance, and during which zones and time windows?

- stakeholder: Insurers and risk assessors
- rule: `incomplete.cannot_complete_as_asked` — non-answer template: "I can't complete that request as asked. To be accurate about one thing: this..."
- flags: —

```
I can't complete that request as asked. To be accurate about one thing: this building **does** have 296 temperature sensor(s) — the limitation isn't a lack of sensing. Try narrowing the request (fewer spaces, a coarser interval, or a specific room) and I'll answer from the building's own data.
```

### LT-059 — ADD_DATA_INSTRUCTION (high)

**Q:** Which approved network, presentation and account requirements should I send an external speaker before arrival?

- stakeholder: Lecturers and tutors
- rule: `add.add_or_update` — instructs the reader to add data: "...If the answer should be in a document, add or update it — a document carrying record-document f..."
- flags: —

```
**Abacws Building's documents do not answer this.** I searched Av Readiness Register; they are the closest material and none of them contains the answer. If the answer should be in a document, add or update it — a document carrying record-document front-matter is also lifted into queryable data on i
```

### LT-005 — ADD_DATA_INSTRUCTION (high)

**Q:** If my assigned room is withdrawn, which currently eligible alternative should I ask the room team to consider?

- stakeholder: Lecturers and tutors
- rule: `add.add_or_update` — instructs the reader to add data: "...If the answer should be in a document, add or update it — a document carrying record-document f..."
- flags: —

```
**Abacws Building's documents do not answer this.** I searched Continuity Provision Register, Room Bookings; they are the closest material and none of them contains the answer. If the answer should be in a document, add or update it — a document carrying record-document front-matter is also lifted i
```

### RS-064 — ADD_DATA_INSTRUCTION (high)

**Q:** I've developed a headache in this room. What are the current measured conditions, and is anything clearly unusual compared with this room's reliable baseline?

- stakeholder: Research staff
- rule: `add.you_can_add_it` — instructs the reader to add data: "...facilities / estates management team. You can add it — no code changes needed: 1. Describe i..."
- flags: —

```
I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. You can add it — no code changes needed: 1. **Describe it in the ontology** — upload a TTL naming the entity and its relationsh
```

### LB-013 — ADD_DATA_INSTRUCTION (high)

**Q:** Does the current portfolio provide enough suitable bookable and informal settings for teaching, collaboration, focus, confidentiality and accessible use?

- stakeholder: School leadership, university leadership, and building owners
- rule: `add.add_or_update` — instructs the reader to add data: "...If the answer should be in a document, add or update it — a document carrying record-document f..."
- flags: —

```
**Abacws Building's documents do not answer this.** I searched Stakeholder Group Register, Workspace Profile Register; they are the closest material and none of them contains the answer. If the answer should be in a document, add or update it — a document carrying record-document front-matter is als
```

### SP-066 — INCOMPLETE (high)

**Q:** Which workplace peaks and troughs are stable enough to plan for, and how do they vary across weekdays, term phases, projects and exceptional periods?

- stakeholder: Space-planning teams
- rule: `incomplete.cannot_complete_as_asked` — non-answer template: "I can't complete that request as asked. To be accurate about one thing: this..."
- flags: —

```
I can't complete that request as asked. To be accurate about one thing: this building **does** have 270 occupancy sensor(s) — the limitation isn't a lack of sensing. Try narrowing the request (fewer spaces, a coarser interval, or a specific room) and I'll answer from the building's own data.
```

### SP-065 — WRONG_LANE (high)

**Q:** What mix of desks, focus rooms, collaboration areas, meeting rooms, storage and support space is justified by approved operating assumptions and consultation?

- stakeholder: Space-planning teams
- rule: `lane.space_listing` — a listing of 'Lab' spaces for a question not about them
- flags: —

```
## Lab **21** space(s) found: | Floor | Zone | Label | Type | Area (m²) | |-------|------|-------|------|-----------| | 0 | `0Z013` | 41P Collab S | lab | 102.2 | | 1 | `1Z01` | 1Z01 16P Collab Sp 1Z01 | lab | — | | 1 | `1Z011` | 4P Collab Space | lab | 10.4 | | 1 | `1Z013` | 16P Collab Sp | lab | 3
```

### PGT-054 — ADD_DATA_INSTRUCTION (high)

**Q:** I am on campus for only one day this week. Can you plan a practical sequence for study, an online call, printing and a group meeting around my classes?

- stakeholder: Taught postgraduate students
- rule: `add.add_or_update` — instructs the reader to add data: "...If the answer should be in a document, add or update it — a document carrying record-document f..."
- flags: —

```
**Abacws Building's documents do not answer this.** I searched Event Activity Register, Public Event Register, Timetabled Sessions; they are the closest material and none of them contains the answer. If the answer should be in a document, add or update it — a document carrying record-document front-
```

### UG-019 — WRONG_LANE (low)

**Q:** Should I stay here, or are noise, crowding or CO2 likely to get noticeably worse during the next hour?

- stakeholder: Undergraduate students
- rule: `lane.short_unrelated` — short answer sharing ['hour'] with the question
- flags: —

```
**Forecast not available** Could not build a clean time series for 'Sound/Loudness Sensor installed-node 5.07': too_few_points. Try a larger time window (e.g. 'last 48 hours') or a different sensor. --- **You might also ask:** Detect anomalies in this trend? | Compare with another sensor? | Export a
```

### EA-076 — INCOMPLETE (high)

**Q:** How would plausible growth or change in teaching, research and workplace demand affect asset capacity, service headroom and operational risk?

- stakeholder: University estates and asset-management teams
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a sensor data q..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **sensor data** question. - The ontology lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such data. Rephrasing with a specific room, floor or date rang
```

### Q216 — ADD_DATA_INSTRUCTION (high)

**Q:** Is the building pushchair-friendly from the car park?

- stakeholder: Visitor
- rule: `add.you_can_add_it` — instructs the reader to add data: "...facilities / estates management team. You can add it — no code changes needed: 1. Describe i..."
- flags: —

```
I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. You can add it — no code changes needed: 1. **Describe it in the ontology** — upload a TTL naming the entity and its relationsh
```

### Q753 — ADD_DATA_INSTRUCTION (high)

**Q:** Book me a hotel near the building for tomorrow.

- stakeholder: Visitor
- rule: `add.add_or_update` — instructs the reader to add data: "...If the answer should be in a document, add or update it — a document carrying record-document f..."
- flags: —

```
**Abacws Building's documents do not answer this.** I searched Room Bookings; they are the closest material and none of them contains the answer. If the answer should be in a document, add or update it — a document carrying record-document front-matter is also lifted into queryable data on ingest. O
```

### Q516 — ADD_DATA_INSTRUCTION (high)

**Q:** Which capital project this year had the best measured outcome?

- stakeholder: Executive
- rule: `add.you_can_add_it` — instructs the reader to add data: "...facilities / estates management team. You can add it — no code changes needed: 1. Describe i..."
- flags: —

```
I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. You can add it — no code changes needed: 1. **Describe it in the ontology** — upload a TTL naming the entity and its relationsh
```

### Q856 — ADD_DATA_INSTRUCTION (low)

**Q:** How much would submetering every floor cost, and when does it pay back?

- stakeholder: Energy manager
- rule: `add.footer_on_decline` — decline ("The records do not contain information about the cost of submeteri...") with a remediation footer "...his figure covers — the meter behind it has no `ontosage:meterServes` in the ontology. Declaring the meter's boundary and all..."
- flags: remediation_footer

```
The records do not contain information about the cost of submetering every floor or its payback period. They record 24 cost line entries for various services such as electricity, water, HVAC, lift maintenance, cleaning, security, IT, laboratory supplies, grounds maintenance, accessibility improvemen
```

### Q481 — ADD_DATA_INSTRUCTION (low)

**Q:** What's the optimal battery dispatch for tomorrow's tariff and solar forecast?

- stakeholder: Energy manager
- rule: `add.footer_on_decline` — decline ("the building's data do not contain information about battery dispatch or s...") with a remediation footer "...his figure covers — the meter behind it has no `ontosage:meterServes` in the ontology. Declaring the meter's boundary and all..."
- flags: remediation_footer

```
the building's data do not contain information about battery dispatch or solar forecast. They record the following tariff details for the building: - **Electricity Tariff 2025** (effective 31 Dec 2024 - 30 Dec 2025): unit rate £0.3102/kWh, standing charge £0.588/day, provider Cardiff University Esta
```

### Q224 — WRONG_LANE (low)

**Q:** Where can I isolate the water supply for the second-floor toilets?

- stakeholder: Contractor
- rule: `lane.short_unrelated` — short answer sharing nothing with the question
- flags: —

```
Incoming main stop valve SV-1 --- *From Abacws Building's documents: Asset Engineering Register. For the current version, contact facility management.*
```

### Q705 — ADD_DATA_INSTRUCTION (high)

**Q:** How many free-cooling hours did we capture last month versus what was available?

- stakeholder: Energy manager
- rule: `add.install_sensor` — tells the reader to install sensors to get the answer: "...oling hours. To enable this analysis, install a dedicated free-cooling monitoring sensor and log its uptime. _1365 reading(s) f..."
- flags: —

```
**No free‑cooling hours were captured in the current dataset.** The available data consists solely of PIR lighting and intrusion detector activity across floors 0‑5. Therefore, we cannot compare captured versus available free‑cooling hours. To enable this analysis, install a dedicated free‑cooling m
```

### q49b16d713c45 — ADD_DATA_INSTRUCTION (high)

**Q:** What systems are specific for the meeting room?

- stakeholder: Health and Safety Officers
- rule: `add.you_can_add_it` — instructs the reader to add data: "...facilities / estates management team. You can add it — no code changes needed: 1. Describe i..."
- flags: —

```
I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. You can add it — no code changes needed: 1. **Describe it in the ontology** — upload a TTL naming the entity and its relationsh
```

### q711e1631b50f — WRONG_LANE (low)

**Q:** how does building prevent this space?

- stakeholder: IT/Data Scientists
- rule: `lane.short_unrelated` — short answer sharing nothing with the question
- flags: —

```
calls_ok requires acoustic separation, not merely a door. --- *From Abacws Building's documents: Workspace Profile Register. For the current version, contact facility management.*
```

### q9773eb2f64c3 — ADD_DATA_INSTRUCTION (high)

**Q:** How can a building shift to greener hours and still be productive?

- stakeholder: IT/Data Scientists
- rule: `add.add_or_update` — instructs the reader to add data: "...If the answer should be in a document, add or update it — a document carrying record-document f..."
- flags: —

```
**Abacws Building's documents do not answer this.** I searched Department Directory, Stakeholder Group Register; they are the closest material and none of them contains the answer. If the answer should be in a document, add or update it — a document carrying record-document front-matter is also lift
```

## Low-confidence verdicts — read these

| row | id | bucket | rule | reason | question |
|---:|---|---|---|---|---|
| 0 | AO-016 | INCOMPLETE | `incomplete.fetch_budget` | non-answer template: "That question reaches 296 sensors — more than I can read and summarise in one request without ei..." (the boundary permits a clarification | Which remaining period today has the best supported balance of temperature, ventilation, l |
| 1 | AO-031 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records do not contain any information about shared desk avail...") but says it read 'operating regimes for HVAC and lighting systems in the buil | Is this shared desk officially available to me now, or does it only appear unoccupied? |
| 2 | AO-015 | HONEST_DECLINE | `decline.referent_absent` | referent gate refused 'brief corridor' — check it was a real place, not an adjective the gate picked up: "'brief corridor' does not exist in this building, so t | Is today's noise a brief corridor-related peak or a sustained room-level problem likely to |
| 3 | AC-056 | HONEST_DECLINE | `decline.lead` | opens by declining: "...PR-009, APR-010) - Expired: 1 (APR-011) None of these Permission group records contain a `recordOwner`, a mapped open..." (substantial b | Which permission groups or zones are orphaned because no current owner, purpose or mapped  |
| 13 | AU-030 | HONEST_DECLINE | `decline.lead` | opens by declining: "The 32 approval records you provided do not contain any information about the movement, rep..." (substantial body: may be a partial answer) | When assets were moved, replaced, isolated, recommissioned or retired, were active control |
| 14 | AU-008 | WRONG_LANE | `lane.short_unrelated` | short answer sharing ['operat'] with the question | For each local, shared or inherited control, who operates, monitors and evidences each com |
| 15 | BM-003 | HONEST_DECLINE | `decline.lead` | opens by declining: "The records do not show any late starts. They do record approve..." (substantial body: may be a partial answer); consistent with the catalo | Which systems started late or stopped late against today's approved schedule, and by how m |
| 20 | CT-021 | HONEST_DECLINE | `decline.lead` | opens by declining: "...provals and related documentation; they do not contain any information about washroom service..." (substantial body: may be a partial an | Which washroom should I service next, considering required frequency, time since the last  |
| 29 | SU-004 | ANSWERED | `answered` | substantive answer sharing ['repeat'] with the question | Which utility or end-use profiles show a persistent step change, drift or repeating anomal |
| 31 | MC-040 | WRONG_LANE | `lane.short_unrelated` | short answer sharing nothing with the question | Which next manual test would best distinguish the remaining plausible fault locations whil |
| 32 | MC-069 | HONEST_DECLINE | `decline.lead` | opens by declining: "The 32 approval records you asked about do not contain any fields that record a "witness", "ac..." (substantial body: may be a partial answ | Which authorised role must witness, accept or close each hold point, and what evidence mus |
| 33 | FM-014 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records you have do not contain any information about entrances or rout...") but says it read 'compliance checks for equipment and systems such a | Which entrances or route segments need a facilities inspection before the next high-footfa |
| 36 | FP-041 | HONEST_DECLINE | `decline.lead` | opens by declining: "The records do not contain any explicit "risk" or "whole-life cost..." (substantial body: may be a partial answer); consistent with the cat | Which assets should receive survey, maintenance, refurbishment or replacement funding firs |
| 37 | FP-064 | HONEST_DECLINE | `decline.lead` | opens by declining: "the building's data do not contain any information about conflicts of inte..." (substantial body: may be a partial answer); consistent with | Are conflicts of interest, related-party links and segregation-of-duty controls complete f |
| 47 | IT-016 | ANSWERED | `answered` | substantive answer sharing [] with the question; no visible grounding | Which hosts, clusters or hypervisors face sustained CPU, memory, storage-I/O or network-I/ |
| 49 | IR-045 | HONEST_DECLINE | `decline.lead` | opens by declining: "the building's data do not contain the information you asked for. They do..." (substantial body: may be a partial answer); consistent with  | For each defect, what remedial scope and acceptance evidence were required, what was compl |
| 51 | LT-001 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records do not contain a 9 a.m. lecture. They do record a Doct...") but says it read 'a Doctoral symposium (EVT-2026-0049) that starts at 09:00 a | I have a 9 a.m. lecture. Before I leave my office, what is confirmed, what is still unknow |
| 57 | AR-052 | HONEST_DECLINE | `decline.lead` | opens by declining: "The records do not mention a Changing Places toilet. They record 2..." (substantial body: may be a partial answer); consistent with the cat | Is a Changing Places toilet available in or near Abacws, and what are the current verified |
| 62 | PHD-077 | HONEST_DECLINE | `decline.lead` | opens by declining: "The building's records do not contain any sensor-based information about the..." (substantial body: may be a partial answer) | Can the corridor sensor outside this office tell me what conditions were like inside, or i |
| 63 | PS-076 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records do not specify an instruction for a particular locatio...") but says it read '14 coordination function records, with 9 confirmed and 5 pr | An alarm or emergency message has occurred. What is the latest authoritative instruction f |
| 65 | PS-053 | ANSWERED | `answered` | substantive answer sharing ['allow', 'buffer', 'conservative', 'setup', 'travel'] with the question; no visible grounding | I have appointments on different floors with a short gap. What conservative travel and set |
| 69 | RC-054 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records do not contain information about retention period, aut...") but says it read 'due dates, completion dates, status, responsible role and r | Are compliance records retained for the correct period, in the authorised system and forma |
| 71 | RC-014 | ANSWERED | `answered` | substantive answer sharing [] with the question | Do Abacws local procedures and work instructions implement the current institutional polic |
| 75 | RD-023 | HONEST_DECLINE | `decline.unrelated_store` | declines ("...nsors in this dataset. - Conclusion: We cannot confirm whether a calibration chain is traceabl...") but says it read 'noise profile and workspace  | Is the calibration chain traceable and accurate enough for the smallest difference or thre |
| 79 | RB-033 | HONEST_DECLINE | `decline.lead` | opens by declining: "The records do not show any explicit disagreement between sourc..." (substantial body: may be a partial answer) | The authorised occupancy sources disagree about this booked room. Should the booking remai |
| 84 | SO-031 | ANSWERED | `answered` | substantive answer sharing ['arrangement', 'due', 'event', 'security'] with the question | Which events are due today, and which approved Security arrangements are current, missing  |
| 86 | SO-072 | HONEST_DECLINE | `decline.unrelated_store` | declines ("...t ontology - The provided ontology data does not contain any entities, properties, or triples th...") but says it read '- The property `http://ont | Which current Security records are incomplete, stale, duplicated or conflicting, and which |
| 96 | TT-018 | ANSWERED | `answered` | substantive answer sharing [] with the question; no visible grounding | If enrolment moves within the approved planning range, which group counts or room allocati |
| 100 | UG-019 | WRONG_LANE | `lane.short_unrelated` | short answer sharing ['hour'] with the question | Should I stay here, or are noise, crowding or CO2 likely to get noticeably worse during th |
| 102 | EA-028 | HONEST_DECLINE | `decline.lead` | opens by declining: "...show that all 15 completed work orders do not contain enough asset, test or outcome evidence..." (substantial body: may be a partial ans | Which closed work orders lack enough asset, test or outcome evidence for estates teams to  |
| 106 | VE-018 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The event records do not provide information about an official coat or b...") but says it read 'details of scheduled, cancelled, and moved public eve | Is there an official place near check-in to leave a coat or bag, and is it open? |
| 108 | WM-054 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records do not record any exchange or handback of bins, skips...") but says it read 'the status, location, waste stream, capacity, fill percentag | Were bins, skips, compactors, seals or locks exchanged and handed back exactly as recorded |
| 110 | WM-047 | ANSWERED | `answered` | substantive answer sharing ['ready'] with the question | Is the loading or exchange area clear, booked and operationally ready for the next confirm |
| 117 | Q108 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | I'm pregnant and overheating - where's the coolest place to work today? |
| 118 | Q856 | ADD_DATA_INSTRUCTION | `add.footer_on_decline` | decline ("The records do not contain information about the cost of submeteri...") with a remediation footer "...his figure covers — the meter behind it has no ` | How much would submetering every floor cost, and when does it pay back? |
| 119 | Q1045 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | Whats the best empty room to convert into two phone booths, by demand? |
| 123 | Q481 | ADD_DATA_INSTRUCTION | `add.footer_on_decline` | decline ("the building's data do not contain information about battery dispatch or s...") with a remediation footer "...his figure covers — the meter behind it  | What's the optimal battery dispatch for tomorrow's tariff and solar forecast? |
| 133 | Q224 | WRONG_LANE | `lane.short_unrelated` | short answer sharing nothing with the question | Where can I isolate the water supply for the second-floor toilets? |
| 135 | q7e048379f5a4 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | why autism happens |
| 136 | q19ac2643d4e8 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | What if ozone layer vanished |
| 141 | q30ebf51cf838 | ANSWERED | `answered` | substantive answer sharing ['come', 'glare', 'monitor', 'sensor'] with the question; no visible grounding | How do glare sensors work? Does that come from the monitor itself? |
| 142 | qb220cfa24ae4 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | Does co2 ever realistically get so high that it bothers people? |
| 143 | q711e1631b50f | WRONG_LANE | `lane.short_unrelated` | short answer sharing nothing with the question | how does building prevent this space? |
