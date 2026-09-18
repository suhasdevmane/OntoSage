# Stakeholder answer grades

- input: read phase0_rerun.md.jsonl
- bank: docs/phase0/phase0_bank.jsonl
- rows: **147**; transport failures (status not OK): 0

Grades describe the SHAPE of each answer, not whether its facts are true. INVENTED is only ever a low-confidence flag. An honest decline is a correct outcome, not a failure.

| bucket | n | share | of which high confidence |
|---|---:|---:|---:|
| ANSWERED | 54 | 36.7% | 40 |
| HONEST_DECLINE | 73 | 49.7% | 61 |
| ADD_DATA_INSTRUCTION | 3 | 2.0% | 3 |
| WRONG_LANE | 6 | 4.1% | 1 |
| INCOMPLETE | 11 | 7.5% | 10 |
| INVENTED | 0 | 0.0% | 0 |

**Weird** (add-data + wrong lane + incomplete + invented): **20 / 147 = 13.6%**; high-confidence only: 14 / 147 = 9.5%.

| flag (does not change the bucket) | rows |
|---|---:|
| speaks_as_if_user_supplied_data | 10 |
| partial_decline | 4 |
| general_knowledge_ungrounded | 4 |
| decline_cites_unrelated_source | 3 |
| says_simulated | 1 |

<details><summary>Rules that decided the grades</summary>

| rule | rows |
|---|---:|
| answered | 49 |
| decline.lead | 42 |
| decline.documents_do_not_answer | 19 |
| incomplete.could_not_put_together | 6 |
| incomplete.fetch_budget | 5 |
| lane.short_unrelated | 5 |
| decline.not_on_record | 5 |
| answered.general_knowledge | 4 |
| decline.unrelated_store | 3 |
| decline.referent_absent | 1 |
| decline.no_measured_series | 1 |
| add.extend_ontology | 1 |
| answered.lookup | 1 |
| lane.space_listing | 1 |
| decline.no_prior_turn | 1 |
| decline.privacy_policy | 1 |
| add.need_to_add | 1 |
| add.add_to_model | 1 |

</details>

## Per stakeholder role

| group | n | answered | decline | add-data | wrong lane | incomplete | invented | weird |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Auditors and certification assessors | 3 | 0 | 1 | 1 | 1 | 0 | 0 | 66.7% |
| BMS-HVAC operators | 3 | 1 | 0 | 0 | 0 | 2 | 0 | 66.7% |
| Undergraduate students | 3 | 1 | 0 | 0 | 1 | 1 | 0 | 66.7% |
| Space planner | 2 | 0 | 1 | 0 | 0 | 1 | 0 | 50.0% |
| IT/Data Scientists | 5 | 2 | 1 | 1 | 1 | 0 | 0 | 40.0% |
| Academic office occupants | 3 | 0 | 2 | 0 | 0 | 1 | 0 | 33.3% |
| Architects and building designers | 3 | 1 | 1 | 0 | 0 | 1 | 0 | 33.3% |
| Emergency responders | 3 | 2 | 0 | 0 | 0 | 1 | 0 | 33.3% |
| External maintenance contractors | 3 | 0 | 2 | 0 | 1 | 0 | 0 | 33.3% |
| Facilities managers | 3 | 1 | 1 | 0 | 0 | 1 | 0 | 33.3% |
| PhD students | 3 | 2 | 0 | 0 | 1 | 0 | 0 | 33.3% |
| Research staff | 3 | 0 | 2 | 0 | 0 | 1 | 0 | 33.3% |
| School leadership, university leadership, and building owner | 3 | 0 | 2 | 0 | 0 | 1 | 0 | 33.3% |
| Space-planning teams | 3 | 0 | 2 | 0 | 1 | 0 | 0 | 33.3% |
| Teaching and audiovisual support team | 3 | 1 | 1 | 0 | 0 | 1 | 0 | 33.3% |
| Energy manager | 4 | 1 | 2 | 1 | 0 | 0 | 0 | 25.0% |
| (no stakeholder in bank) | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Access-control administrators | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| Accessibility, inclusion, and well-being teams | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Building Owners/Property Managers | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Cleaning and caretaking teams | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Contractor | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Emergency coordinators | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Energy, carbon, and sustainability teams | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Executive | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Facility Managers / Building Maintenance Teams | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Facility manager | 4 | 2 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Finance and procurement teams | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Fire service liaison | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Fire-safety personnel | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| Guests/Visitors | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Health and Safety Officers | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Health and safety officers | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| IT, network, and server-infrastructure teams | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Insurers and risk assessors | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Lecturers and tutors | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Maintenance technician | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Mechanical and electrical engineers | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Occupant | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Occupants/Tenants/Employees | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| People with mobility, sensory, or other accessibility requir | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Professional-services staff | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Prospective students and family members | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Regulatory and institutional compliance teams | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Researchers and data scientists | 3 | 2 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Retrofit consultant | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Room-booking team | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| Security officers | 3 | 0 | 3 | 0 | 0 | 0 | 0 | 0.0% |
| Student | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Student/Researchers/Academics | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Taught postgraduate students | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Timetabling team | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| University estates and asset-management teams | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Visitor | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Visitors and event attendees | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Waste-management teams | 3 | 1 | 2 | 0 | 0 | 0 | 0 | 0.0% |

## Per category

Catalogue rows carry no category; they are grouped under their source.

| group | n | answered | decline | add-data | wrong lane | incomplete | invented | weird |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Cross-domain / open-ended reasoning | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 100.0% |
| Weather coupling | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 100.0% |
| Factual Recall | 2 | 1 | 0 | 1 | 0 | 0 | 0 | 50.0% |
| Meta / Strategic Reasoning | 2 | 0 | 1 | 0 | 1 | 0 | 0 | 50.0% |
| (stakeholder_catalogue_37) | 111 | 41 | 54 | 1 | 5 | 10 | 0 | 14.4% |
| Accessibility | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Ambiguous, underspecified & out-of-scope | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Anomaly detection & diagnosis | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Benchmarking & comparison | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Carbon & retrofit | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Causal Diagnosis | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Cleaning & daily operations | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Comfort & place-finding | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Comparative Analysis | 2 | 0 | 2 | 0 | 0 | 0 | 0 | 0.0% |
| Cost & finance | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Current state / lookup | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Documents, compliance & institutional knowledge | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Events & scheduling | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Generation, storage & grid | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Inferential Reasoning | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Lighting & acoustics | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Maintenance, tickets & complaints | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Occupancy & space utilisation | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Personalisation, memory & follow-up | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Prediction & forward-looking | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Retrospective analysis & reporting | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Safety, security & emergency | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| System self-knowledge & explainability | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Systemic Synthesis | 2 | 1 | 1 | 0 | 0 | 0 | 0 | 0.0% |
| Water & waste | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| Wayfinding & entity resolution | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0.0% |

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

### AU-030 — ADD_DATA_INSTRUCTION (high)

**Q:** When assets were moved, replaced, isolated, recommissioned or retired, were active controls transferred while prior evidence remained linked and retrievable?

- stakeholder: Auditors and certification assessors
- rule: `add.extend_ontology` — instructs the reader to add data: "...ack this information, you would need to extend the ontology with properties that capture asset life..."
- flags: speaks_as_if_user_supplied_data

```
**Answer** The ontology data you provided contains only information about **ApprovalRecord** objects and the **accountableRole** property. There is no explicit statement or triple that describes: * the transfer of active controls when an asset is moved, replaced, isolated, recommissioned or retired,
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

### BM-022 — INCOMPLETE (high)

**Q:** Which zones are recovering from setback more slowly than their own recent verified warm-up or cool-down pattern?

- stakeholder: BMS-HVAC operators
- rule: `incomplete.fetch_budget` — non-answer template: "That question reaches 296 sensors — more than I can read and summarise in one request without ei..."
- flags: —

```
That question reaches **296 sensors** — more than I can read and summarise in one request without either timing out or quietly answering from a fraction of them. Narrow it and I can answer directly: - one floor, or one room - one measurement at a time (temperature, or CO₂ — not both) - a shorter per
```

### ER-031 — INCOMPLETE (high)

**Q:** What defensible aggregate occupancy range applied to each affected zone at the incident start time?

- stakeholder: Emergency responders
- rule: `incomplete.fetch_budget` — non-answer template: "That question reaches 250 sensors — more than I can read and summarise in one request without ei..."
- flags: —

```
That question reaches **250 sensors** — more than I can read and summarise in one request without either timing out or quietly answering from a fraction of them. Narrow it and I can answer directly: - one floor, or one room - one measurement at a time (temperature, or CO₂ — not both) - a shorter per
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

### PHD-077 — WRONG_LANE (low)

**Q:** Can the corridor sensor outside this office tell me what conditions were like inside, or is valid room-level evidence required?

- stakeholder: PhD students
- rule: `lane.short_unrelated` — short answer sharing ['room'] with the question
- flags: —

```
**Which space did you mean?** I can say what is measured in a particular room, floor or zone, but I need to know which one before I can answer whether it is instrumented.
```

### RS-078 — INCOMPLETE (high)

**Q:** What evidence is missing, stale or too weak for the building to answer my question about this room responsibly?

- stakeholder: Research staff
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a metadata ques..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **metadata** question. - The ontology lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such data. Rephrasing with a specific room, floor or date range o
```

### LB-006 — INCOMPLETE (high)

**Q:** Where are teaching, research, workplace and public-facing priorities competing for the same room, route or service, and which trade-off needs an accountable decision?

- stakeholder: School leadership, university leadership, and building owners
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a metadata ques..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **metadata** question. - The ontology lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such data. Rephrasing with a specific room, floor or date range o
```

### SP-065 — WRONG_LANE (high)

**Q:** What mix of desks, focus rooms, collaboration areas, meeting rooms, storage and support space is justified by approved operating assumptions and consultation?

- stakeholder: Space-planning teams
- rule: `lane.space_listing` — a listing of 'Lab' spaces for a question not about them
- flags: —

```
## Lab **21** space(s) found: | Floor | Zone | Label | Type | Area (m²) | |-------|------|-------|------|-----------| | 0 | `0Z013` | 41P Collab S | lab | 102.2 | | 1 | `1Z01` | 1Z01 16P Collab Sp 1Z01 | lab | — | | 1 | `1Z011` | 4P Collab Space | lab | 10.4 | | 1 | `1Z013` | 16P Collab Sp | lab | 3
```

### AV-010 — INCOMPLETE (high)

**Q:** Which scheduled rooms should be included in the walk-round because remote readiness evidence is missing, stale or contradictory?

- stakeholder: Teaching and audiovisual support team
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a metadata ques..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **metadata** question. - The ontology lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such data. Rephrasing with a specific room, floor or date range o
```

### UG-019 — WRONG_LANE (low)

**Q:** Should I stay here, or are noise, crowding or CO2 likely to get noticeably worse during the next hour?

- stakeholder: Undergraduate students
- rule: `lane.short_unrelated` — short answer sharing ['hour'] with the question
- flags: —

```
**Forecast not available** Could not build a clean time series for 'Sound/Loudness Sensor installed-node 5.06': too_few_points. Try a larger time window (e.g. 'last 48 hours') or a different sensor. --- **You might also ask:** Detect anomalies in this trend? | Compare with another sensor? | Export a
```

### UG-024 — INCOMPLETE (high)

**Q:** The previous class has just ended. Are CO2 and temperature back near this room's usual pre-class levels?

- stakeholder: Undergraduate students
- rule: `incomplete.fetch_budget` — non-answer template: "That question reaches 296 sensors — more than I can read and summarise in one request without ei..."
- flags: —

```
That question reaches **296 sensors** — more than I can read and summarise in one request without either timing out or quietly answering from a fraction of them. Narrow it and I can answer directly: - one floor, or one room - one measurement at a time (temperature, or CO₂ — not both) - a shorter per
```

### Q1045 — INCOMPLETE (high)

**Q:** Whats the best empty room to convert into two phone booths, by demand?

- stakeholder: Space planner
- rule: `incomplete.could_not_put_together` — non-answer template: "I understood the question but could not put an answer together for it. - I read it as a recommend que..."
- flags: —

```
I understood the question but could not put an answer together for it. - I read it as a **recommend** question. - The ontology lane ran, but returned nothing to report. That is a gap on my side, not a statement that the building has no such data. Rephrasing with a specific room, floor or date range 
```

### Q705 — ADD_DATA_INSTRUCTION (high)

**Q:** How many free-cooling hours did we capture last month versus what was available?

- stakeholder: Energy manager
- rule: `add.need_to_add` — instructs the reader to add data: "...n actual cooling usage or availability, you would need to add a free-cooling sensor to the building's..."
- flags: —

```
**Answer** - **Free‑cooling sensors**: This building does not have free‑cooling sensors. - **Closest available information**: The ontology provides building access hours, which describe when card‑holders can enter the building. - **Card‑holder access**: 07:00 – 22:00 on weekdays, 08:00 – 18:00 on we
```

### q3991cad9d778 — ADD_DATA_INSTRUCTION (high)

**Q:** in the barometric meter will functions

- stakeholder: IT/Data Scientists
- rule: `add.add_to_model` — instructs the reader to add data: "...nclude such sensors. You might consider adding a new sensor type to the ontology or checking other data sources for baro..."
- flags: speaks_as_if_user_supplied_data

```
**Answer** The ontology data you provided contains information only about **Waste Collection Points** (e.g., `bldg:waste/WCP-001`, `bldg:waste/WCP-002`, …). There is **no barometric meter sensor** listed in this building’s data. **What is available** - **Waste Collection Point** - **Label**: *Waste 
```

### q711e1631b50f — WRONG_LANE (low)

**Q:** how does building prevent this space?

- stakeholder: IT/Data Scientists
- rule: `lane.short_unrelated` — short answer sharing nothing with the question
- flags: —

```
calls_ok requires acoustic separation, not merely a door. --- *From Abacws Building's documents: Workspace Profile Register. For the current version, contact facility management.*
```

## Low-confidence verdicts — read these

| row | id | bucket | rule | reason | question |
|---:|---|---|---|---|---|
| 0 | AO-016 | INCOMPLETE | `incomplete.fetch_budget` | non-answer template: "That question reaches 296 sensors — more than I can read and summarise in one request without ei..." (the boundary permits a clarification | Which remaining period today has the best supported balance of temperature, ventilation, l |
| 1 | AO-031 | HONEST_DECLINE | `decline.unrelated_store` | declines ("the building's data do not contain any information about shared desk avail...") but says it read '10 operating regime entries, with 9 marked active a | Is this shared desk officially available to me now, or does it only appear unoccupied? |
| 2 | AO-015 | HONEST_DECLINE | `decline.referent_absent` | referent gate refused 'brief corridor' — check it was a real place, not an adjective the gate picked up: "'brief corridor' does not exist in this building, so t | Is today's noise a brief corridor-related peak or a sustained room-level problem likely to |
| 4 | AC-064 | HONEST_DECLINE | `decline.lead` | opens by declining: "The ontology does not contain a dedicated "restoration" or "erroneous..." (substantial body: may be a partial answer); consistent with the  | What authority, prior-state evidence and independent checks are required before considerin |
| 6 | AI-048 | ANSWERED | `answered` | substantive answer sharing ['closure'] with the question | Have closures, room moves and route changes reached each affected attendee and accompanyin |
| 14 | AU-008 | WRONG_LANE | `lane.short_unrelated` | short answer sharing ['operat'] with the question | For each local, shared or inherited control, who operates, monitors and evidences each com |
| 26 | ER-008 | ANSWERED | `answered` | substantive answer sharing ['route'] with the question | Which boundary-to-door route is currently evidenced for ambulance crews, stretcher teams a |
| 29 | SU-004 | ANSWERED | `answered` | substantive answer sharing ['repeat'] with the question | Which utility or end-use profiles show a persistent step change, drift or repeating anomal |
| 31 | MC-040 | WRONG_LANE | `lane.short_unrelated` | short answer sharing nothing with the question | Which next manual test would best distinguish the remaining plausible fault locations whil |
| 46 | IT-027 | ANSWERED | `answered.lookup` | class inventory sharing ['sensor'] with the question — may not answer it | Which approved plant, sensor, access-control or building-management endpoints have lost ex |
| 47 | IT-016 | ANSWERED | `answered` | substantive answer sharing [] with the question; no visible grounding | Which hosts, clusters or hypervisors face sustained CPU, memory, storage-I/O or network-I/ |
| 55 | ME-055 | HONEST_DECLINE | `decline.lead` | opens by declining: "the building's data do not contain any sensor-point names or sampling-rate..." (substantial body: may be a partial answer); consistent with | Which points and sampling rates should be trended so this commissioning or diagnostic test |
| 59 | AR-023 | HONEST_DECLINE | `decline.lead` | opens by declining: "I'm sorry, but the building's records do not contain any information about how close a works..." (substantial body: may be a partial answer | I need a seat near an exit. Which authorised seating options meet that preference without  |
| 62 | PHD-077 | WRONG_LANE | `lane.short_unrelated` | short answer sharing ['room'] with the question | Can the corridor sensor outside this office tell me what conditions were like inside, or i |
| 65 | PS-053 | ANSWERED | `answered` | substantive answer sharing ['buffer', 'travel'] with the question; no visible grounding | I have appointments on different floors with a short gap. What conservative travel and set |
| 66 | PF-035 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records do not contain any information about crowding or venti...") but says it read 'for that activity (ACT-0042-2) is: / for that activity (ACT | Is my next course talk likely to be crowded or poorly ventilated enough to consider a repe |
| 71 | RC-014 | ANSWERED | `answered` | substantive answer sharing [] with the question | Do Abacws local procedures and work instructions implement the current institutional polic |
| 81 | LB-065 | HONEST_DECLINE | `decline.lead` | opens by declining: "...only lists the building's sensors - it doesn't include any information about a recovery order..." (substantial body: may be a partial an | Which dependency-aware recovery order should incident leaders adopt to restore priority se |
| 96 | TT-018 | ANSWERED | `answered` | substantive answer sharing ['allocation', 'count', 'enrolment', 'group', 'room'] with the question; no visible grounding; also declines part: "...ng efficiency. | If enrolment moves within the approved planning range, which group counts or room allocati |
| 100 | UG-019 | WRONG_LANE | `lane.short_unrelated` | short answer sharing ['hour'] with the question | Should I stay here, or are noise, crowding or CO2 likely to get noticeably worse during th |
| 102 | EA-028 | HONEST_DECLINE | `decline.lead` | opens by declining: "The records do not contain any evidence of asset, test or outcome..." (substantial body: may be a partial answer); consistent with the cata | Which closed work orders lack enough asset, test or outcome evidence for estates teams to  |
| 104 | EA-025 | ANSWERED | `answered` | substantive answer sharing ['control'] with the question | Which non-mandatory tasks have enough sensing, failure-mode knowledge and fallback control |
| 108 | WM-054 | HONEST_DECLINE | `decline.unrelated_store` | declines ("The records do not contain information about whether bins, skips,...") but says it read 'the current status of each waste-collection point (active, o | Were bins, skips, compactors, seals or locks exchanged and handed back exactly as recorded |
| 117 | Q108 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | I'm pregnant and overheating - where's the coolest place to work today? |
| 122 | Q250 | HONEST_DECLINE | `decline.lead` | opens by declining: "I'm sorry, but the building's records do not contain the information you're looking for. The..." (substantial body: may be a partial answer | Find a room for 12 with a projector, free 2-4pm today, near the cafe. |
| 123 | Q481 | HONEST_DECLINE | `decline.lead` | opens by declining: "I'm sorry, but the building's data do not contain any information about battery dispatch..." (substantial body: may be a partial answer) | What's the optimal battery dispatch for tomorrow's tariff and solar forecast? |
| 129 | Q440 | HONEST_DECLINE | `decline.lead` | opens by declining: "This building does not have any records or sensors related to drain..." (substantial body: may be a partial answer) | Which drains have needed jetting more than twice this year? |
| 135 | q7e048379f5a4 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | why autism happens |
| 136 | q19ac2643d4e8 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | What if ozone layer vanished |
| 141 | q30ebf51cf838 | ANSWERED | `answered` | substantive answer sharing ['come', 'glare', 'monitor', 'sens', 'sensor'] with the question; no visible grounding | How do glare sensors work? Does that come from the monitor itself? |
| 142 | qb220cfa24ae4 | ANSWERED | `answered.general_knowledge` | general-knowledge prose with no source, record or building reference | Does co2 ever realistically get so high that it bothers people? |
| 143 | q711e1631b50f | WRONG_LANE | `lane.short_unrelated` | short answer sharing nothing with the question | how does building prevent this space? |
