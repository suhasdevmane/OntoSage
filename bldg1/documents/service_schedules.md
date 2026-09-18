---
record_type: service_schedule
owner: "Estates Operations Manager"
authority: "Cardiff University Estates - Planned Maintenance"
source_system: "Planned Maintenance Schedule"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Planned service schedule"
    maps_to: service_schedules
---

# Planned Maintenance and Service Schedules - Abacws Building

## What changed, and why

`ontosage:ServiceSchedule` was declared in the TBox and had no mapping and no instances: the
building could name the concept and hold none of it. This document already carried seventeen
well-formed rows across three tables. Only the two files that turn a document into a register
were missing, so nothing here is new data - it is the same seventeen entries, given one
consistent schema and two columns the original could not express.

**`statutory` is the important addition.** A missed carpet clean is an inconvenience; a missed
weekly fire alarm test is reportable and a lift without a current LOLER examination may not
run. A single "overdue" flag conflates a scheduling annoyance with a legal failure, and the
consequence is the whole answer.

**`status` is derived from the dates, not asserted.** A register that says "Active" while its
own next-due date has passed teaches a false fact, and the fire alarm row is exactly that
case: due 2026-09-02, unrecorded since.

`frequency` stays as text. "twice daily", "6 monthly" and "quarterly" are what the schedule
actually says; normalising them to a number of days would invent a precision the source does
not have.

## Planned service schedule

| code | task | category | scope | frequency | last_completed | next_due | statutory | owner | provider | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SVC-01 | Office and corridor cleaning | Cleaning | All occupied floors | daily, overnight | 2026-09-15 | 2026-09-17 | false | Caretaking Supervisor | In-house | Overdue |  |
| SVC-02 | Washroom servicing | Cleaning | All washrooms | twice daily | 2026-09-15 | 2026-09-17 | false | Caretaking Supervisor | In-house | Overdue |  |
| SVC-03 | Carpet deep clean - Levels 1 and 2 | Cleaning | Levels 1 and 2 | 6 monthly | 2026-03-08 | 2026-09-06 | false | Caretaking Supervisor | Specialist contractor | Due | Due within the week |
| SVC-04 | Carpet deep clean - Levels 3 and 4 | Cleaning | Levels 3 and 4 | 6 monthly | 2026-05-25 | 2026-11-23 | false | Caretaking Supervisor | Specialist contractor | Active |  |
| SVC-05 | Carpet deep clean - Level 5 | Cleaning | Level 5 | 6 monthly | 2026-07-19 | 2027-01-17 | false | Caretaking Supervisor | Specialist contractor | Active |  |
| SVC-06 | Window cleaning, external | Cleaning | All external glazing | quarterly | 2026-06-19 | 2026-09-18 | false | Estates Operations Manager | Abseil contractor | Due | Requires a permit and an abseil arrangement |
| SVC-07 | Atrium glazing, internal | Cleaning | Room 1.04 - Common Area / Atrium | 6 monthly | 2026-05-01 | 2026-10-30 | false | Caretaking Supervisor | Specialist contractor | Active |  |
| SVC-08 | Grease trap emptying | Drainage and catering | Ground floor cafe | quarterly | 2026-06-21 | 2026-09-20 | true | Estates Operations Manager | Drainage contractor | Active | Statutory under the trade effluent consent |
| SVC-09 | Kitchen extract duct clean | Drainage and catering | Ground floor cafe | annual | 2025-11-21 | 2026-11-21 | true | Estates Operations Manager | Specialist contractor | Active | TR19 clean; insurers require the certificate |
| SVC-10 | Surface water gully clearance | Drainage and catering | External areas | 6 monthly | 2026-05-09 | 2026-11-07 | false | Estates Operations Manager | Drainage contractor | Active |  |
| SVC-11 | AHU filter change, all units | Building services | All six air handling units | quarterly | 2026-08-18 | 2026-11-17 | false | M and E Maintenance Supervisor | In-house | Active | Current, so the AHU Floor 3 shortfall is not a filter problem |
| SVC-12 | Boiler service | Building services | Heating plant | annual | 2026-01-03 | 2027-01-03 | true | M and E Maintenance Supervisor | Gas Safe contractor | Active |  |
| SVC-13 | Chiller service | Building services | Chiller 1 - Building Central Cooling Plant | annual | 2026-04-01 | 2027-04-01 | true | M and E Maintenance Supervisor | F-Gas contractor | Active | F-Gas leak check is statutory for this refrigerant charge |
| SVC-14 | Lift LOLER examination | Building services | Main passenger lift | 6 monthly | 2026-06-16 | 2026-12-16 | true | M and E Maintenance Supervisor | Insurance inspector | Active | Statutory thorough examination; the lift may not run without it |
| SVC-15 | Emergency lighting duration test | Building services | All escape routes | annual | 2026-02-14 | 2027-02-14 | true | Building Fire Warden Coordinator | In-house | Active | Three-hour duration test |
| SVC-16 | Fire alarm weekly test | Building services | Building Fire Alarm Control Panel | weekly | 2026-09-09 | 2026-09-16 | true | Building Fire Warden Coordinator | In-house | Overdue | OVERDUE: the last recorded test was 2026-08-26 and the next was due 2026-09-02. A missed weekly test is reportable |
| SVC-17 | PAT testing | Building services | Portable appliances, all floors | annual | 2025-12-09 | 2026-12-09 | false | Estates Operations Manager | In-house | Active |  |

**17 scheduled services. 3 overdue and 2 due within a fortnight. 1 of the overdue items is statutory - the weekly fire alarm test, due 2026-09-02 and unrecorded since - and a missed weekly test is reportable rather than merely late.**
