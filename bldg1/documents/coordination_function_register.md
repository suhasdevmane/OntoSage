---
record_type: coordination_function
owner: "Emergency Coordination Lead"
authority: "Cardiff University Estates — Resilience"
source_system: "Emergency Coordination Function Register"
effective_from: 2026-09-04
version: "2026.9.4"
review_due: 2026-12-04
simulated: true
tables:
  - name: "Coordination function register"
    maps_to: coordination_functions
---

# Emergency Coordination Function Register — Abacws Building

_**Synthetic demonstration record** — fictional readiness data, not a live incident file._

## Operational period

This register covers **operational period 2026-09-04 day shift (07:00–19:00)**. A new period
gets new rows; nothing here is carried forward by assumption, because a function confirmed
yesterday is not confirmed today.

## Why "unknown" is a state and not a blank

In an incident, *"we have not established whether this criterion is met"* and *"this
criterion is not met"* lead to different decisions. A register that collapsed them into one
empty cell would be actively dangerous. So `criterion_state` carries an explicit **unknown**,
and **a row with no evidence reference cannot be recorded as met**.

**The approved fallback sits beside the function it replaces.** A fallback that has to be
looked up somewhere else during an incident is not a fallback.

## Coordination function register

| function | name | accountable_role | operational_period | primary_system | system_state | fallback | activation_criterion | criterion_state | evidence_ref | decision_needed | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CF-01 | Incident command | Estates Duty Manager | 2026-09-04 day | Incident management platform | Ready | Paper incident log at Main Reception | A confirmed fire alarm activation, or an instruction from the Fire Service | Not met | RES-EV-2026-0901 | false | Confirmed | |
| CF-02 | Building evacuation control | Head of Security | 2026-09-04 day | Voice alarm and PA | Ready | Hand-held loudhailers, one per floor warden | Fire alarm confirmed on two or more zones | Not met | RES-EV-2026-0902 | false | Confirmed | |
| CF-03 | Refuge point communication | Head of Security | 2026-09-04 day | Refuge intercom system | Degraded | Radio channel 3 with a warden posted at each refuge | Any evacuation with a registered PEEP holder in the building | Unknown | | true | Provisional | Level 3 refuge intercom has intermittent audio since 2026-09-01. Whether a PEEP holder is present today has not been established. |
| CF-04 | Casualty and first aid | Estates Duty Manager | 2026-09-04 day | First-aider call-out list | Ready | Direct 999 call from reception | Any reported injury | Not met | RES-EV-2026-0903 | false | Confirmed | |
| CF-05 | Laboratory spill response | Laboratory Manager | 2026-09-04 day | COSHH response procedure | Degraded | Evacuate the room and isolate ventilation; await contractor | A spill of a listed substance | Unknown | | true | Provisional | Room 3.06's COSHH assessment is under review (APR-008), so the criterion cannot be evidenced for that room. |
| CF-06 | Utilities isolation | Estates Duty Manager | 2026-09-04 day | BMS isolation controls | Ready | Manual valves and breakers, plant room, permit required | Instruction from incident command | Not met | RES-EV-2026-0904 | false | Confirmed | |
| CF-07 | External agency liaison | Emergency Coordination Lead | 2026-09-04 day | Campus control room bridge | Ready | Direct mobile to the on-call estates number | Any incident involving the Fire Service or Police | Not met | RES-EV-2026-0905 | false | Confirmed | |
| CF-08 | Occupant communication | Events and Communications Coordinator | 2026-09-04 day | Mass notification service | Unavailable | Floor wardens with printed call lists | An incident affecting occupancy for more than 30 minutes | Not met | RES-EV-2026-0906 | true | Provisional | The notification service is out of service pending the network switch refresh (CL-2026-017, delivery slipped). |
| CF-09 | Access control override | Head of Security | 2026-09-04 day | Access control global modes | Ready | Mechanical override keys held at the control room | Incident command declares FIRE_EVAC or LOCKDOWN | Not met | RES-EV-2026-0907 | false | Confirmed | Global modes are recorded in the access permission register. |
| CF-10 | Lift recall and entrapment | Estates Duty Manager | 2026-09-04 day | Lift controller recall | Degraded | Contractor call-out under the lift maintenance contract | Alarm from any lift car, or an evacuation | Conflicting | RES-EV-2026-0908 | true | Provisional | Lift B is out of service to 2026-09-12; the controller reports ready while the maintainer's record says otherwise. |
| CF-11 | Waste and contamination containment | Soft Services Manager | 2026-09-04 day | Spill kit stations | Ready | Contractor call-out | A spill outside a laboratory | Not met | RES-EV-2026-0909 | false | Confirmed | |
| CF-12 | Business continuity handover | Estates Governance Lead | 2026-09-04 day | Continuity plan | Ready | Printed plan held at Main Reception | An incident expected to exceed four hours | Not met | RES-EV-2026-0910 | false | Confirmed | |
| CF-13 | Roll call and accounting | Head of Security | 2026-09-04 day | Access control presence data | Degraded | Assembly point marshals with printed lists | Any full evacuation | Unknown | | true | Provisional | Presence data is room-level aggregate only under the data retention policy (APR-026), so individual accounting is not possible by design. |
| CF-14 | Media and enquiries | Events and Communications Coordinator | 2026-09-04 day | Communications office | Ready | Duty press mobile | Any incident attracting external attention | Not met | RES-EV-2026-0911 | false | Confirmed | |

## What needs an authorised decision before the next period

Five functions carry `decision_needed`:

- **CF-03 Refuge point communication** — degraded intercom, and whether a PEEP holder is in
  the building today is unestablished.
- **CF-05 Laboratory spill response** — the criterion cannot be evidenced for Room 3.06
  while its COSHH assessment is under review.
- **CF-08 Occupant communication** — the primary system is unavailable and the fallback is
  manual.
- **CF-10 Lift recall** — the controller and the maintainer's record disagree.
- **CF-13 Roll call** — individual accounting is impossible by policy, not by fault. The
  decision is whether marshalled assembly lists are accepted as sufficient.

**Four criteria are not evidenced**: CF-03, CF-05 and CF-13 are `unknown`, CF-10 is
`conflicting`. None of them may be reported as met.
