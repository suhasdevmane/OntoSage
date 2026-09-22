---
record_type: door_hardware
owner: "Head of Security"
authority: "Cardiff University Estates — Security and Fire Safety"
source_system: "Door and Shutter Hardware Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
tables:
  - name: "Door and shutter hardware register"
    maps_to: door_hardware
---

# Door and Shutter Hardware Register — Abacws Building

## What this register records, and why the equipment model could not

The building already models the readers, maglocks and fire doors as equipment. None of that
says what an opening **does** when power is lost or the fire alarm sounds, and that is the
question three different roles ask about the same door:

> *"Which shutters or doors fail open versus fail locked on power loss?"*

A fire officer asks it to know who can get out. A security officer asks it to know what is
left unsecured. An evacuation planner asks it to know which route survives a power cut. The
same opening can be the right answer for one and the wrong answer for another, so the state is
recorded per opening rather than inferred from what kind of opening it is.

## How to read the fail state

| value | meaning |
|---|---|
| fail open | The opening releases and can be pushed through. Nothing holds it shut. |
| fail safe | Released for escape in the direction of travel; secure from the other side. |
| fail locked | Stays secure. A key or a break-glass is needed to pass. |
| fail closed | Drops or closes under its own weight, as a fire shutter is designed to. |

**A fire shutter that fails closed and an escape door that fails open are both correct.** They
sit on the same supply and behave in opposite ways by design. Any answer that groups them by
their circuit rather than by their recorded state is describing the wiring, not the building.

## Door and shutter hardware register

| opening | name | kind | location | floor | power_loss_state | hold_open | release | commanded_by | last_tested | next_due | evidence_ref | status | owner | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DR-001 | Main entrance east leaf | escape door | Main Entrance — Senghennydd Road | 0 | fail safe | Magnet on fire panel | Push pad | Fire alarm | 2026-08-12 | 2027-02-12 | DR-TEST-2026-08 | Active | Head of Security | On the fire panel's cause-and-effect list; releases on any building-wide alarm |
| DR-002 | Main entrance west leaf | escape door | Main Entrance — Senghennydd Road | 0 | fail safe | Magnet on fire panel | Push pad | Fire alarm | 2026-08-12 | 2027-02-12 | DR-TEST-2026-08 | Active | Head of Security |  |
| DR-003 | Goods entrance roller shutter | fire shutter | Room 0.06 — Loading and Goods Storage | 0 | fail closed | Acoustic hold-open | Fire-panel signal | Fire alarm | 2026-06-30 | 2026-12-30 | SHT-2026-06 | Active | Estates Operations Manager | Drops on alarm; the pedestrian door beside it (DR-004) is the escape route |
| DR-004 | Goods entrance pedestrian door | escape door | Room 0.06 — Loading and Goods Storage | 0 | fail safe | None | Push pad | Fire alarm | 2026-06-30 | 2026-12-30 | SHT-2026-06 | Active | Estates Operations Manager | The escape route beside shutter DR-003 |
| DR-005 | North stairwell ground door | escape door | North Stairwell — Fire Escape Route | 0 | fail safe | Magnet on fire panel | Push pad | Fire alarm | 2026-08-12 | 2027-02-12 | DR-TEST-2026-08 | Active | Building Fire Warden Coordinator |  |
| DR-006 | Server room door | security door | Room 4.44 — Server Room | 4 | fail locked | None | Break-glass beside frame | Access control | 2026-07-21 | 2027-01-21 | SEC-2026-07 | Active | Head of Security | Stays secure on power loss by design; break-glass releases it for escape |
| DR-007 | Communications room door | security door | Level 3 riser cupboard | 3 | fail locked | None | Manual key override | Access control | 2026-07-21 | 2027-01-21 | SEC-2026-07 | Active | Head of Security | No break-glass fitted; key override only |
| DR-008 | Mechanical plant room door | security door | Room 0.04 — Mechanical Plant Room | 0 | fail locked | None | Manual key override | Access control | 2026-05-19 | 2026-11-19 | SEC-2026-05 | Active | M and E Maintenance Supervisor |  |
| DR-009 | Level 1 lab corridor fire door | fire door | Level 1 corridor | 1 | fail closed | Acoustic hold-open | Fire-panel signal | Fire alarm | 2026-10-02 | 2027-04-02 | FD-2026-04 | Active | Building Fire Warden Coordinator | Held open in normal use; closes on alarm |
| DR-010 | Level 2 lab corridor fire door | fire door | Level 2 corridor | 2 | fail closed | Acoustic hold-open | Fire-panel signal | Fire alarm | 2026-10-02 | 2027-04-02 | FD-2026-04 | Defective | Building Fire Warden Coordinator | Hold-open does not drop on test; wedged open by users in the meantime |
| DR-011 | Level 3 lab corridor fire door | fire door | Level 3 corridor | 3 | fail closed | Acoustic hold-open | Fire-panel signal | Fire alarm | 2026-10-02 | 2027-04-02 | FD-2026-04 | Active | Building Fire Warden Coordinator |  |
| DR-012 | Reception turnstile | turnstile | Room 0.01 — Main Reception | 0 | fail open | None | Drops arms on power loss | Access control | 2026-08-12 | 2027-02-12 | SEC-2026-08 | Active | Head of Security | Arms drop so the lobby does not trap people; the lobby is then unsecured |
| DR-013 | Car park vehicle barrier | vehicle barrier | Car park — Senghennydd Road | 0 | fail open | None | Manual release handle | Access control | 2026-04-08 | 2026-10-08 | SEC-2026-04 | Active | Estates Operations Manager | Raises on power loss; manual handle if the motor is dead |
| DR-014 | Level 5 conference suite door | security door | Room 5.15 — Seminar / Conference Room | 5 | fail safe | Magnet on fire panel | Push pad | Fire alarm | 2026-08-12 | 2027-02-12 | DR-TEST-2026-08 | Active | Head of Security |  |
| DR-015 | Basement tank room door | security door | Basement cold water storage tank | 0 | fail locked | None | Manual key override | Access control | 2025-09-30 | 2026-09-08 | SEC-2025-09 | Overdue | Estates Operations Manager | Six-monthly test passed its due date on 8 September 2026 |
| DR-016 | Bike store door | security door | Basement bike store | 0 | fail locked | None | Push pad from inside | Access control | 2026-06-16 | 2026-12-16 | SEC-2026-06 | Active | Estates Operations Manager |  |

## What this register does not record

* **Who opened an opening, and when.** Access events are not held in this building, and the
  access-permission register is deliberately role-level: "who can open this door" is
  answerable as a role entitlement, "who did" is not held at all.
* **Whether a door is open right now.** Door contact sensors carry that; this register is the
  hardware's designed behaviour, not its live state.
