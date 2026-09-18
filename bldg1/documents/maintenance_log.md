---
record_type: work_order
owner: "M and E Maintenance Supervisor"
authority: "Cardiff University Estates - Mechanical and Electrical Maintenance"
source_system: "Maintenance Work Order Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Maintenance work order register"
    maps_to: work_orders
---

# Maintenance Work Order Register - Abacws Building

## What this is, and the two corrections made to the source

`ontosage:WorkOrder` was declared in the ontology with lay terms and had no mapping, so the
building could name the concept and hold none of it. The 24 entries below were already here
as prose bullet lists in the maintenance log: quotable, and impossible to count, filter or
group. Dates, assets, statuses and hours are unchanged.

**Two things were corrected, and both are stated rather than quietly fixed.**

**1. The source named individual technicians.** Every other register in this building holds
identity at role level, because the catalogues forbid exposing who did what and the access
decision point is built on that assumption. Lifting a named technician into the graph would have
put personal names into an answerable store through the back door - not by a decision anyone
took, but by converting a document nobody had read closely. The column is now a **trade**.

**2. Several task types were impossible for their asset.** The source recorded an oil change
and belt tensioning on an *electrical distribution board*, a filter replacement and belt
tensioning on a *passenger lift*, and a smoke test on a *chilled water pump*. They were
randomly generated. Carried over verbatim they would make this register assert maintenance
nobody could have performed - a worse failure than holding no register at all, because an
engineer spots it in seconds and then trusts none of the other rows. Each corrected row says
so in its own note.

Where an asset appears in the asset engineering register, `asset_code` carries its AEP
reference, so fault history and design duty can be read together - which is what *"has this
repaired asset returned to the same abnormal pattern?"* actually requires.

## Maintenance work order register

| ref | task | asset_code | asset_name | raised_on | category | trade | hours | priority | completed_on | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| WO-001 | Fault investigation | AEP-002 | Air Handling Unit - Floor 1 | 2026-06-13 | reactive | Controls technician | 3.6 | high |  | In progress | Still in progress; AEP-002 is the unit serving the Level 1 computer laboratories |
| WO-002 | Electrical inspection | AEP-002 | Air Handling Unit - Floor 1 | 2026-06-08 | planned | Electrical technician | 0.8 | routine | 2026-06-08 | Completed |  |
| WO-003 | Belt tensioning | AEP-002 | Air Handling Unit - Floor 1 | 2026-05-26 | planned | Mechanical technician | 1.0 | routine | 2026-05-26 | Completed |  |
| WO-004 | Vibration check | AEP-002 | Air Handling Unit - Floor 1 | 2026-05-21 | planned | Mechanical technician | 1.9 | routine | 2026-05-21 | Completed |  |
| WO-005 | Annual service | AEP-002 | Air Handling Unit - Floor 1 | 2026-05-11 | planned | Mechanical technician | 0.8 | routine | 2026-05-11 | Completed |  |
| WO-006 | Preventive maintenance | AEP-002 | Air Handling Unit - Floor 1 | 2026-05-07 | planned | Mechanical technician | 2.1 | routine | 2026-05-07 | Completed |  |
| WO-007 | Electrical inspection | AEP-002 | Air Handling Unit - Floor 1 | 2026-05-01 | planned | Electrical technician | 1.1 | routine | 2026-05-01 | Completed |  |
| WO-008 | Electrical inspection | AEP-004 | Air Handling Unit - Floor 3 | 2026-05-20 | planned | Electrical technician | 1.0 | routine |  | Pending |  |
| WO-009 | Filter replacement | AEP-004 | Air Handling Unit - Floor 3 | 2026-05-16 | planned | Mechanical technician | 2.9 | routine | 2026-05-16 | Completed |  |
| WO-010 | Thermographic survey | AEP-021 | Electrical Breaker Panel - Floor 3 | 2026-06-09 | planned | Electrical technician | 1.3 | routine |  | In progress | Task type corrected: the source recorded 'Oil change', which this asset class cannot receive |
| WO-011 | Annual service | AEP-021 | Electrical Breaker Panel - Floor 3 | 2026-06-04 | planned | Mechanical technician | 1.7 | routine |  | In progress |  |
| WO-012 | Torque check on terminations | AEP-021 | Electrical Breaker Panel - Floor 3 | 2026-05-24 | planned | Electrical technician | 1.0 | routine |  | In progress | Task type corrected: the source recorded 'Oil change', which this asset class cannot receive |
| WO-013 | Insulation resistance test | AEP-021 | Electrical Breaker Panel - Floor 3 | 2026-05-09 | planned | Electrical technician | 2.9 | high |  | Pending | Task type corrected: the source recorded 'Belt tensioning', which this asset class cannot receive |
| WO-014 | Coil clean and filter change | FCU-503 | Fan Coil Unit Room 5.03 | 2026-06-17 | planned | Mechanical technician | 3.7 | routine | 2026-06-17 | Completed | Task type corrected: the source recorded 'Belt tensioning', which this asset class cannot receive |
| WO-015 | Condensate drain clearance | FCU-503 | Fan Coil Unit Room 5.03 | 2026-06-11 | planned | Mechanical technician | 1.3 | routine |  | Pending | Task type corrected: the source recorded 'Belt tensioning', which this asset class cannot receive |
| WO-016 | Preventive maintenance | AEP-011 | Main passenger lift | 2026-06-03 | planned | Mechanical technician | 1.5 | routine | 2026-06-03 | Completed |  |
| WO-017 | Annual service | AEP-011 | Main passenger lift | 2026-05-31 | planned | Mechanical technician | 3.5 | routine | 2026-05-31 | Completed |  |
| WO-018 | Electrical inspection | AEP-011 | Main passenger lift | 2026-05-28 | planned | Electrical technician | 3.6 | routine | 2026-05-28 | Completed |  |
| WO-019 | Emergency repair | AEP-011 | Main passenger lift | 2026-05-15 | reactive | Lift engineer | 2.8 | urgent | 2026-05-15 | Completed | The lift entrapment recorded as INC-2026-005 |
| WO-020 | Door interlock adjustment | AEP-011 | Main passenger lift | 2026-05-13 | planned | Lift engineer | 1.3 | high | 2026-05-13 | Completed | Task type corrected: the source recorded 'Filter replacement', which this asset class cannot receive |
| WO-021 | Vibration check | AEP-011 | Main passenger lift | 2026-05-10 | planned | Mechanical technician | 1.4 | routine |  | In progress |  |
| WO-022 | Annual service | AEP-011 | Main passenger lift | 2026-05-04 | planned | Mechanical technician | 2.6 | routine |  | In progress |  |
| WO-023 | Rope tension check | AEP-011 | Main passenger lift | 2026-05-03 | planned | Lift engineer | 2.4 | routine | 2026-05-03 | Completed | Task type corrected: the source recorded 'Belt tensioning', which this asset class cannot receive |
| WO-024 | Mechanical seal inspection | AEP-008 | Chiller Pump 1 | 2026-05-22 | planned | Mechanical technician | 1.9 | routine | 2026-05-22 | Completed | Task type corrected: the source recorded 'Smoke test', which this asset class cannot receive |

**24 work orders across six assets. 9 are not complete, and 8 rows carried a task type the asset could not receive and have been corrected against their asset class. Every technician name in the source has been replaced by a trade.**
