---
record_type: incident_record
owner: "Building Safety Adviser"
authority: "Cardiff University Safety Office"
source_system: "Incident and Near-Miss Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Incident and near-miss register"
    maps_to: incident_records
---

# Incident and Near-Miss Register - Abacws Building

## What this register records, and the one decision that shapes it

**Two severity columns, not one.** `severity` is what actually happened. `potential_severity`
is what could reasonably have happened. A near miss with **no injury and major potential** is
the single most informative row any incident register holds, and a schema with one severity
field files it as the least important thing in the book.

INC-2026-003 is that row: a Level 3 fire door wedged open, nobody hurt, compartmentation
defeated for an unknown period. It reads as trivial under one column and as the most serious
event of the spring under two.

**Near misses share the register with injuries**, deliberately. Splitting them is how an
organisation stops noticing that the two have the same cause.

**A blank `investigation_finding` is itself a finding.** Three rows are open with high
potential severity and no investigation recorded - the blocked fire service access route
(open since June), the undisplayed hot works permit, and the parking level CO alarm. The
register is built so *"which high-potential events were never investigated?"* is a query
rather than an audit.

Three rows connect to other registers by cause rather than by reference: INC-2026-006 is the
same inherited permission path as the override on AP-014; INC-2026-010 shares its root cause
with the overdue collection at WCP-024; and INC-2026-015 depends on an interlock belonging to
AEP-017, the asset with the longest blind interval in the building.

## Incident and near-miss register

| ref | summary | occurred_on | location | category | severity | potential_severity | immediate_action | investigation_finding | reportable | actions_outstanding | reported_by_role | owner | closed_on | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| INC-2026-001 | Contractor entered a laboratory without induction | 2026-02-11 | Room 2.03 - Research Laboratory | near miss | none | serious | Contractor escorted out; work stopped for the day | The permit named the floor, not the room, so reception issued a general pass | false | Permit template amended to require a room reference | External maintenance contractors | Building Safety Adviser | 2026-03-04 | Closed | Low actual severity, serious potential. The permit wording was the cause, not the contractor |
| INC-2026-002 | Slip on wet floor near the atrium entrance | 2026-02-27 | Room 1.04 - Common Area / Atrium | injury | minor | moderate | First aid given; area cordoned and dried | Wet-weather matting was not deployed; the caretaking round starts after the morning peak | false |  | Occupant | Building Safety Adviser | 2026-03-20 | Closed | Second slip at this location in twelve months |
| INC-2026-003 | Fire door on Level 3 wedged open | 2026-03-16 | Level 3 riser cupboard | near miss | none | major | Wedge removed; door closer checked | Door closer stiff after the Level 3 refurbishment; staff wedged it rather than reporting | false | Closer adjusted; a reminder issued to Level 3 occupants | Health and safety officers | Building Fire Warden Coordinator | 2026-04-02 | Closed | Compartmentation defeated for an unknown period. Highest potential severity of any closed row |
| INC-2026-004 | Chemical spill contained in a fume cupboard | 2026-04-09 | Room 2.05 - Research Laboratory | environmental | minor | moderate | Spill kit used; LEV left running; room ventilated | Container placed too close to the sash; no procedural failure found | false |  | Lab manager | Building Safety Adviser | 2026-04-24 | Closed |  |
| INC-2026-005 | Lift entrapment, two occupants, 18 minutes | 2026-05-02 | Main lift core | service failure | minor | serious | Lift engineer attended; occupants released; lift taken out of service | Door interlock intermittent fault; component replaced | true |  | Security officers | M and E Maintenance Supervisor | 2026-05-30 | Closed | Reportable as a dangerous occurrence. The lift is the only step-free route between levels |
| INC-2026-006 | Unauthorised access to the Level 2 comms room | 2026-05-21 | Room 2.13 - Meeting Room | security | none | serious | Door secured; access log reviewed | A permission group granted through an inherited template nobody had reviewed | false | Inheritance review of all comms room groups - NOT YET COMPLETE | Security officers | Security Duty Manager |  | Open | Directly connected to the access permission register: the override on AP-014 is the same path |
| INC-2026-007 | Delivery vehicle blocked the fire service access route | 2026-06-08 | Room 0.06 - Loading and Goods Storage | near miss | none | major | Vehicle moved within four minutes; driver briefed |  | false | Delivery booking process not yet changed; no owner assigned | Delivery driver | Estates Operations Manager |  | Open | HIGH POTENTIAL SEVERITY AND NO INVESTIGATION RECORDED. Open for nearly three months |
| INC-2026-008 | Water ingress from the roof after heavy rain | 2026-06-19 | Room 5.15 - Seminar / Conference Room | property damage | moderate | moderate | Room closed; ceiling tiles removed; electrical isolation checked | Blocked rainwater outlet on the roof; gully clearance was within its interval | false | Additional gully inspection added before the autumn | Professional-services staff | Estates Operations Manager | 2026-07-10 | Closed |  |
| INC-2026-009 | Trailing cable across a teaching room walkway | 2026-07-01 | Room 1.06 - Computer Laboratory | near miss | none | moderate | Cable rerouted and taped | Temporary AV setup left in place after an event | false |  | Lecturers and tutors | AV Support Team Leader | 2026-07-08 | Closed |  |
| INC-2026-010 | Sharps bin overfilled in a Level 3 laboratory | 2026-07-15 | Room 3.01 - Research Laboratory | near miss | none | serious | Bin sealed and removed; replacement issued | The scheduled collection was missed because the room was under a COSHH restriction | false | Collection route revised to include restricted rooms | Lab manager | Waste and Recycling Officer | 2026-08-05 | Closed | Same root cause as the overdue collection recorded against WCP-024 in the waste register |
| INC-2026-011 | Aggressive visitor at reception | 2026-07-28 | Room 0.01 - Main Reception | security | minor | moderate | Security attended; visitor left the site | Visitor had been refused entry without a booked appointment | false |  | Receptionist | Security Duty Manager | 2026-08-11 | Closed |  |
| INC-2026-012 | Emergency lighting failed in a stairwell during a test | 2026-08-04 | North Stairwell - Fire Escape Route | service failure | none | major | Temporary lighting deployed; stair remained usable | Battery pack at end of life; not flagged by the annual duration test in February | true | Battery packs on the north stair scheduled for replacement | Building Fire Warden Coordinator | M and E Maintenance Supervisor |  | Monitoring | The February duration test passed, so the failure mode is not caught by the current regime |
| INC-2026-013 | Manual handling strain moving furniture | 2026-08-12 | Room 4.13 - Seminar Room | injury | minor | minor | First aid given; task stopped | Two-person lift not used for a table above the single-person limit | false |  | Porter | Building Safety Adviser | 2026-08-26 | Closed |  |
| INC-2026-014 | Hot works permit not displayed at the work location | 2026-08-20 | Roof plant area | near miss | none | serious | Work stopped until the permit was produced |  | false | Permit display requirement to be added to the contractor induction - no date set | External maintenance contractors | Building Safety Adviser |  | Open | Third open row with high potential severity and no completed investigation |
| INC-2026-015 | CO detection alarm at parking level, no fault found | 2026-08-29 | Parking level plant space | near miss | none | major | Level ventilated; area checked; alarm reset |  | false | Exhaust fan interlock to be proven - the fan has not been physically visited since 2025-09-12 | Security officers | M and E Maintenance Supervisor |  | Open | The interlock this alarm depends on belongs to the asset with the longest blind interval in the building (AEP-017) |

**15 events: 7 near misses, 2 externally reportable, 4 still open. 3 rows carry a serious or major potential severity with no investigation recorded - and every one of those is still open. That is the register's own most important output.**
