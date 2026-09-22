---
record_type: hazard_control
owner: "Building Safety Adviser"
authority: "Cardiff University Safety Office"
source_system: "Hazard Control Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
tables:
  - name: "Hazard control register"
    maps_to: hazard_controls
---

# Hazard Control Register - Abacws Building

## Why four documents became one register

The building held COSHH and LEV, asbestos, and water hygiene and legionella as three separate
prose documents, none of them mapped. They share exactly one shape: **a hazard that is managed
rather than removed, whose safety depends on a test somebody has to keep doing.** Three
near-identical registers would have meant three places for *"which controls are overdue?"* to
be half-answered.

**`condition` is separate from `status`.** HZ-008 is why: an asbestos cement flue remnant in
good condition, properly encapsulated, under a **damaged label**. The material is safe; the
labelling is not. A single state field would force a safety officer to guess which of those
two problems they have, and they need different actions from different people.

`status` is derived from the dates and the condition, never asserted.

## Hazard control register

| code | hazard | kind | location | control | condition | regime | last_tested_on | next_test_due | evidence_ref | owner | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HZ-001 | Fume cupboard FC-201 | local exhaust ventilation | Room 2.05 - Research Laboratory | LEV extract at 0.5 m/s face velocity | Face velocity within tolerance at last test | COSHH Regulation 9, 14-monthly thorough examination | 2026-01-19 | 2027-03-19 | LEV-2026-01 | Building Safety Adviser | Active | Tested at 0.52 m/s; the spill INC-2026-004 was contained by this unit |
| HZ-002 | Fume cupboard FC-202 | local exhaust ventilation | Room 2.06 - Research Laboratory | LEV extract at 0.5 m/s face velocity | Face velocity marginal at 0.44 m/s | COSHH Regulation 9, 14-monthly thorough examination | 2026-01-19 | 2027-03-19 | LEV-2026-01 | Building Safety Adviser | Defective | Below the 0.5 m/s design figure but above the 0.4 m/s action level |
| HZ-003 | Fume cupboard FC-301 | local exhaust ventilation | Room 3.01 - Research Laboratory | LEV extract at 0.5 m/s face velocity | Face velocity within tolerance | COSHH Regulation 9, 14-monthly thorough examination | 2025-06-12 | 2026-08-12 | LEV-2025-06 | Building Safety Adviser | Overdue | OVERDUE since 2026-08-12. The room is also under the COSHH restriction that blocked the WCP-024 sharps collection |
| HZ-004 | Solvent store, flammables cabinet | COSHH substance | Room 2.05 - Research Laboratory | Fire-rated cabinet, 50 litre limit, bunded | Cabinet intact, inventory within limit | COSHH assessment review, annual | 2026-03-04 | 2027-03-04 | COSHH-2026-03 | Lab manager | Active |  |
| HZ-005 | Compressed gas cylinders | COSHH substance | Room 2.02 - Research Laboratory | Chained storage, ventilated enclosure, gas detection | Restraints and detection in order | COSHH assessment review, annual | 2026-03-04 | 2027-03-04 | COSHH-2026-03 | Lab manager | Active |  |
| HZ-006 | Cleaning chemical store | COSHH substance | Room 0.29 - Storage Room | Locked store, decanting prohibited, MSDS held on site | Store secure, labels legible | COSHH assessment review, annual | 2026-02-18 | 2027-02-18 | COSHH-2026-02 | Caretaking Supervisor | Active |  |
| HZ-007 | Asbestos insulating board, riser lining | asbestos-containing material | Level 2 riser cupboard | Managed in place, labelled, access controlled by permit | Good condition, label legible | Asbestos management survey, annual re-inspection | 2026-03-27 | 2027-03-27 | ASB-2026-03 | Estates Operations Manager | Active | The same riser carries the unsealed penetration recorded as FSA-021 |
| HZ-008 | Asbestos cement flue remnant | asbestos-containing material | Room 0.04 - Mechanical Plant Room | Managed in place, encapsulated, labelled | Encapsulation intact, LABEL DAMAGED | Asbestos management survey, annual re-inspection | 2026-03-27 | 2027-03-27 | ASB-2026-03 | Estates Operations Manager | Defective | Material in good condition under a damaged label - a labelling failure, not a material failure, and the two need different actions |
| HZ-009 | Domestic hot water calorifier | water system | Room 0.07 - Service Room | Stored at 60 degC, distributed above 50 degC | Temperatures within scheme | L8 / HSG274 written scheme, monthly temperature monitoring | 2026-09-14 | 2026-10-15 | WH-2026-08 | Estates Operations Manager | Active |  |
| HZ-010 | Little-used outlets, Level 5 washrooms | water system | Level 5 | Weekly flushing regime | Flushing recorded weekly | L8 / HSG274 written scheme, weekly flushing | 2026-09-04 | 2026-09-11 | WH-2026-08 | Caretaking Supervisor | Overdue | OVERDUE by one day; little-used outlets are the highest-risk part of the scheme |
| HZ-011 | Cold water storage tank | water system | Roof plant area | Lidded, insulated, temperature below 20 degC | Tank clean, temperature compliant | L8 / HSG274 written scheme, six-monthly inspection | 2026-05-06 | 2026-11-06 | WH-2026-05 | Estates Operations Manager | Active |  |
| HZ-012 | Thermostatic mixing valves, accessible washrooms | water system | All floors | TMV set to 41 degC, annual service and temperature check | Within tolerance | L8 / HSG274 written scheme, annual TMV service | 2026-05-06 | 2027-05-06 | WH-2026-05 | M and E Maintenance Supervisor | Active |  |

**12 hazard controls. 2 overdue: the Level 3 fume cupboard (HZ-003, since 2026-08-12) and the Level 5 little-used outlet flushing (HZ-010, by one day). Little-used outlets are the highest-risk element of a legionella scheme, so a one-day slip there is not equivalent to a one-day slip elsewhere.**
