---
record_type: waste_collection
owner: "Soft Services Manager"
authority: "Cardiff University Estates — Waste and Recycling"
source_system: "Waste Collection Point Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Waste collection point register"
    maps_to: waste_points
---

# Waste Collection Point Register — Abacws Building

_**Synthetic demonstration record** — fictional waste data, not a real service record._

## Why the stream is three columns and not one

A station where the system record says **General waste**, the bin is labelled **Mixed
recycling** and the aperture is a **narrow slot** is a station people will use wrongly — and
the disagreement is invisible if all three are collapsed into a single "stream" field.

So `stream_record`, `stream_label` and `aperture` are recorded separately. **Where they
disagree, that is the answer to a question, not a data-entry error to be tidied away.**

**Fill threshold is per point.** A 240-litre bin in a busy atrium and a 60-litre bin in a
quiet corridor do not cross "full" at the same percentage, and the approved threshold is a
service decision rather than a constant.

## Waste collection point register

| point | name | station | location | stream_record | stream_label | aperture | capacity_litres | fill_percent | fill_threshold | next_collection | service_period | temporary | status | owner | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WCP-001 | Reception mixed recycling | ST-GROUND-A | Room 0.01 — Main Reception | Mixed recycling | Mixed recycling | Wide opening | 120 | 55 | 80 | 2026-09-05 | twice weekly | false | Active | Soft Services Manager | |
| WCP-002 | Reception general waste | ST-GROUND-A | Room 0.01 — Main Reception | General waste | General waste | Wide opening | 120 | 70 | 80 | 2026-09-05 | twice weekly | false | Active | Soft Services Manager | |
| WCP-003 | Reception paper | ST-GROUND-A | Room 0.01 — Main Reception | Paper and card | Paper only | Narrow slot | 90 | 45 | 80 | 2026-09-05 | weekly | false | Active | Soft Services Manager | Label says "Paper only" while the record covers card; the slot will not take flattened card either. |
| WCP-004 | Atrium mixed recycling | ST-L1-A | Room 1.04 — Common Area / Atrium | Mixed recycling | Mixed recycling | Wide opening | 240 | 88 | 85 | 2026-09-05 | twice weekly | false | Active | Soft Services Manager | Over threshold. |
| WCP-005 | Atrium general waste | ST-L1-A | Room 1.04 — Common Area / Atrium | General waste | General waste | Wide opening | 240 | 92 | 85 | 2026-09-05 | twice weekly | false | Active | Soft Services Manager | Over threshold. |
| WCP-006 | Atrium food waste | ST-L1-A | Room 1.04 — Common Area / Atrium | Food waste | Food waste | Caddy | 60 | 74 | 70 | 2026-09-05 | daily | false | Active | Soft Services Manager | Over threshold. |
| WCP-007 | Level 1 corridor recycling | ST-L1-B | Level 1 circulation and stairs | Mixed recycling | General waste | Wide opening | 120 | 40 | 80 | 2026-09-08 | weekly | false | Active | Soft Services Manager | Label contradicts the record: bin is labelled General waste but recorded as Mixed recycling. |
| WCP-008 | Level 2 laboratory glass | ST-L2-A | Level 2 circulation and stairs | Laboratory glass | Laboratory glass | Restricted opening | 60 | 30 | 60 | 2026-09-11 | fortnightly | false | Active | Laboratory Manager | |
| WCP-009 | Level 2 general waste | ST-L2-A | Level 2 circulation and stairs | General waste | General waste | Wide opening | 120 | 62 | 80 | 2026-09-08 | weekly | false | Active | Soft Services Manager | |
| WCP-010 | Level 3 laboratory glass | ST-L3-A | Level 3 circulation and stairs | Laboratory glass | Laboratory glass | Restricted opening | 60 | 18 | 60 | 2026-09-11 | fortnightly | false | Active | Laboratory Manager | |
| WCP-011 | Level 3 general waste | ST-L3-A | Level 3 circulation and stairs | General waste | General waste | Wide opening | 120 | 51 | 80 | 2026-09-08 | weekly | false | Active | Soft Services Manager | |
| WCP-012 | Level 4 mixed recycling | ST-L4-A | Level 4 circulation and stairs | Mixed recycling | Mixed recycling | Wide opening | 120 | 66 | 80 | 2026-09-08 | weekly | false | Active | Soft Services Manager | |
| WCP-013 | Level 4 general waste | ST-L4-A | Level 4 circulation and stairs | General waste | General waste | Wide opening | 120 | 58 | 80 | 2026-09-08 | weekly | false | Active | Soft Services Manager | |
| WCP-014 | Level 5 mixed recycling | ST-L5-A | Level 5 circulation and stairs | Mixed recycling | Mixed recycling | Wide opening | 120 | 44 | 80 | 2026-09-08 | weekly | false | Active | Soft Services Manager | |
| WCP-015 | Level 5 general waste | ST-L5-A | Level 5 circulation and stairs | General waste | General waste | Wide opening | 120 | 39 | 80 | 2026-09-08 | weekly | false | Active | Soft Services Manager | |
| WCP-016 | Confidential shredding | ST-L5-B | Room 5.04 — Academic Office | Confidential paper | Confidential | Narrow slot | 90 | 81 | 75 | 2026-09-09 | monthly | false | Active | Soft Services Manager | Over threshold; next collection is five days away. |
| WCP-017 | WEEE and batteries | ST-GROUND-B | Waste compound and bin store | WEEE | Electrical and batteries | Restricted opening | 60 | 25 | 70 | 2026-09-25 | monthly | false | Active | Soft Services Manager | |
| WCP-018 | Compound general waste | ST-GROUND-B | Waste compound and bin store | General waste | General waste | Bulk container | 1100 | 47 | 85 | 2026-09-05 | twice weekly | false | Active | Soft Services Manager | |
| WCP-019 | Compound mixed recycling | ST-GROUND-B | Waste compound and bin store | Mixed recycling | Mixed recycling | Bulk container | 1100 | 63 | 85 | 2026-09-05 | twice weekly | false | Active | Soft Services Manager | |
| WCP-020 | Open-day temporary recycling | ST-TEMP-01 | Room 1.04 — Common Area / Atrium | Mixed recycling | Mixed recycling | Wide opening | 240 | 12 | 85 | 2026-09-12 | event only | true | Active | Events and Communications Coordinator | Placed for EVT-2026-0042 on 2026-09-11; removed after the event. |
| WCP-021 | Open-day temporary general | ST-TEMP-01 | Room 1.04 — Common Area / Atrium | General waste | General waste | Wide opening | 240 | 8 | 85 | 2026-09-12 | event only | true | Active | Events and Communications Coordinator | Placed for EVT-2026-0042. |
| WCP-022 | Seminar temporary recycling | ST-TEMP-02 | Room 1.04 — Common Area / Atrium | Mixed recycling | Mixed recycling | Wide opening | 120 | 0 | 85 | 2026-09-04 | event only | true | Withdrawn | Events and Communications Coordinator | Placed for the 2026-09-04 seminar; removed the following morning. |
| WCP-023 | Level 2 laboratory sharps | ST-L2-B | Room 2.01 — Research Laboratory | Clinical sharps | Sharps | Restricted opening | 20 | 55 | 60 | 2026-09-18 | monthly | false | Active | Laboratory Manager | Collected under the clinical waste contract, not the general one. |
| WCP-024 | Level 3 laboratory sharps | ST-L3-B | Room 3.06 — Research Laboratory | Clinical sharps | Sharps | Restricted opening | 20 | 40 | 60 | 2026-09-18 | monthly | false | Overdue | Laboratory Manager | Collection missed 2026-08-18: the room is under a COSHH restriction and the contractor could not enter. |

## Points over their approved threshold

Four are over now, and the atrium's three all collect on **2026-09-05**:

- **WCP-005** general waste, 92% against 85%
- **WCP-004** mixed recycling, 88% against 85%
- **WCP-016** confidential shredding, 81% against 75%, next collection **2026-09-09**
- **WCP-006** food waste, 74% against 70%, collected daily

## Stations where the records disagree

- **ST-GROUND-A / WCP-003** — recorded as *Paper and card*, labelled *Paper only*, and fitted
  with a narrow slot that will not accept flattened card. All three disagree.
- **ST-L1-B / WCP-007** — recorded as *Mixed recycling*, labelled *General waste*. Whatever
  is put in it is wrong against one of the two.
