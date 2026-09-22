---
record_type: continuity_provision
owner: "Head of IT Infrastructure"
authority: "Cardiff University Estates and IT — Service Continuity"
source_system: "Service Continuity Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
tables:
  - name: "Service continuity register"
    maps_to: continuity_provision
---

# Service Continuity Register — Abacws Building

## What this register records, and why rooms could not

The building already knows its rooms, its equipment and which floor each sits on. None of that
answers the question every continuity conversation starts with:

> *"If the server room is unavailable, what still runs, from where, and who has proved it?"*

A room list cannot answer it. Asked that question before this register existed, the system
replied with twenty-one lab spaces — true as a list of rooms, and read as a list of options,
which is the most dangerous shape of wrong answer a continuity question can get.

## Verified, unverified and none are three different answers

| status | what it means |
|---|---|
| verified | The arrangement has been exercised end to end, and the evidence reference says when. |
| unverified | An alternative is identified and nobody has proved it carries the service. A plan, not a provision. |
| overdue | It was proved once, and the proof is older than the interval it is meant to be repeated on. |
| none | No alternative is arranged. Recorded deliberately: this is the row a continuity review exists to find. |

**An unverified alternative is never reported as a provision.** A row without proving evidence
cannot be recorded as verified, however confident the plan sounds.

## Service continuity register

| provision | service | depends_on | criticality | alternative_location | alternative_path | alternative_capacity | ride_through_minutes | last_proved_on | next_due | evidence_ref | status | owner | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CP-001 | Core network and building uplink | Room 4.44 — Server Room | high | Level 3 riser cupboard (secondary comms room) | Diverse fibre through the north riser | Full uplink, 60% of switch ports | 25 | 2026-06-18 | 2026-12-18 | CONT-2026-06 | Verified | Head of IT Infrastructure | Proved by failing the primary uplink during the June maintenance window |
| CP-002 | Wireless access across teaching floors | Room 4.44 — Server Room | high | Level 3 riser cupboard (secondary comms room) | Same diverse fibre as CP-001 | Floors 1-3 only; floors 4-5 lose coverage | 25 | 2026-06-18 | 2026-12-18 | CONT-2026-06 | Verified | Head of IT Infrastructure | Partial by design: the secondary room carries no controllers for the upper floors |
| CP-003 | Research compute and lab data capture | Room 4.44 — Server Room | high | None identified |  |  | 25 |  |  |  | None | Head of IT Infrastructure | Research workloads stop with the room. Named here because a continuity review keeps rediscovering it |
| CP-004 | Building management system (BMS) | Room 0.04 — Mechanical Plant Room | high | Room 0.10 — Building Management Office (engineering laptop, local bus) | Direct field bus, no network dependency | Monitoring and manual override; no scheduling | 0 | 2026-04-22 | 2026-10-22 | CONT-2026-04 | Verified | M and E Maintenance Supervisor | Manual override proved; scheduling cannot be restored from the laptop |
| CP-005 | Access control and door release | Room 4.44 — Server Room | high | Local controller cache at each door | Controllers hold the last known permissions | Existing card holders only; no new grants | 480 | 2025-11-14 | 2026-05-14 | CONT-2025-11 | Overdue | Head of Security | Six-monthly proof passed its date on 14 May 2026; the cache itself is designed for 8 hours |
| CP-006 | CCTV recording | Room 4.44 — Server Room | medium | None identified |  |  | 0 |  |  |  | None | Head of Security | Recording stops; live view at the desk continues while power holds |
| CP-007 | Fire alarm monitoring and call-out | Room 0.08 — Service Room (panel) | high | Direct line to the monitoring centre | Dedicated telephone line, independent of the network | Full monitoring | 0 | 2026-08-12 | 2027-02-12 | FA-CONT-2026-08 | Verified | Building Fire Warden Coordinator | Proved during the August alarm test |
| CP-008 | Teaching AV in Level 1 laboratories | Room 1.06 — Computer Laboratory | medium | Room 1.07 — Computer Laboratory | Same floor, same AV standard | One room's worth; a parallel session cannot be accommodated | 0 |  |  |  | Unverified | Audiovisual and Teaching Support | The room exists and the swap has never been exercised under timetable load |
| CP-009 | Lecture capture and streaming | Room 4.44 — Server Room | low | Cloud service (external) | Public internet via the diverse uplink | Full, while the uplink holds | 0 | 2026-06-18 | 2026-12-18 | CONT-2026-06 | Verified | Audiovisual and Teaching Support | Depends on CP-001; if the uplink is lost this goes with it |
| CP-010 | Domestic hot water | Building Domestic Hot Water System | medium | Gas Boiler 2 — Building Central Plant (standby) | Standby boiler on the same circuit | Full for the building | 90 | 2026-05-11 | 2026-11-11 | CONT-2026-05 | Verified | M and E Maintenance Supervisor | Calorifier holds about 90 minutes at normal draw |
| CP-011 | Chilled water to the server room | Chiller 1 — Building Central Cooling Plant | high | None identified |  |  | 12 |  |  |  | None | M and E Maintenance Supervisor | No redundant chiller. Room temperature rises past the alarm point in about twelve minutes |
| CP-012 | Lift service (step-free access) | Main passenger lift | high | None identified |  |  | 0 |  |  |  | None | Estates Operations Manager | There is one lift. Every step-free route in the accessible-route register depends on it |

## What this register does not record

* **Which service is running right now.** This is the arrangement, not the live state.
* **Who to call.** The department directory holds the contacts and their out-of-hours routes.
* **Cost or contractual recovery targets.** The contract register holds those.
