---
record_type: cleaning_task
owner: "Caretaking and Cleaning Supervisor"
authority: "Cardiff University Estates — Soft Services"
source_system: "Cleaning Task Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-09-01
simulated: true
tables:
  - name: "Cleaning task register"
    maps_to: cleaning_tasks
---

# Cleaning Task Register — Abacws Building

_**Synthetic demonstration record** — fictional schedule, not a real service contract._

## How the register is used

The building is divided into six cleaning zones, one per floor, each covered by a named
shift. A task row is the unit a caretaker works from: it names the zone, the area within
it, the standard that applies, how often it recurs, which shift owns it, and the time by
which the area must be ready.

**Ready-by is a service commitment, not an aspiration.** Teaching and laboratory areas are
released for use at a fixed time; a task still open past its ready-by is an exception the
supervisor is expected to see, which is why `status` is recorded per task rather than
inferred from dates.

**Status is read, never inferred.** An area that is closed, restricted or temporarily
reassigned is recorded as `suspended` with the reason in the note — a caretaker sent to a
suspended area wastes a shift, and a suspended area silently omitted from the list is worse.

## Cleaning standards

| standard | what it means |
|---|---|
| **Enhanced** | Laboratory and washroom specification: full sanitisation of touch points, spill checks, waste segregation, consumables replenished. |
| **Standard** | Offices, meeting rooms and circulation: waste, surfaces, floors, touch points. |
| **Presentation** | Reception, atrium and visitor routes: as Standard, plus glass, signage and seating dressed for public view. |
| **Light** | Low-occupancy or recently serviced areas: waste and spot checks only. |

## Shifts

| shift | hours | zones covered |
|---|---|---|
| Early | 05:30–09:30 | Z0 Ground, Z1 Level 1, Z2 Level 2 |
| Day | 09:30–16:30 | All zones — reactive and event support |
| Late | 16:30–21:00 | Z3 Level 3, Z4 Level 4, Z5 Level 5 |

## Cleaning task register

| task | zone | area | standard | frequency | shift | ready_by | minutes | last_done | next_due | status | owner | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CLN-0001 | Z0 Ground | Room 0.01 — Main Reception | Presentation | daily | Early | 08:00 | 45 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | Visitor-facing; dress seating before first arrivals. |
| CLN-0002 | Z0 Ground | Main Entrance Zone — Ground Floor | Presentation | daily | Early | 08:00 | 30 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | Includes external matting and glass to eye height. |
| CLN-0003 | Z0 Ground | Room 0.04 — Mechanical Plant Room | Light | monthly | Day | 16:00 | 20 | 2026-08-14 | 2026-09-14 | Scheduled | Caretaking Supervisor | Plant room — permit required for work at height. |
| CLN-0004 | Z0 Ground | Ground floor washrooms | Enhanced | twice daily | Early | 08:30 | 40 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | Second visit falls to the Day shift at 13:30. |
| CLN-0005 | Z1 Level 1 | Room 1.04 — Common Area / Atrium | Presentation | daily | Early | 08:30 | 50 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | High footfall; check waste before 12:00 as well. |
| CLN-0006 | Z1 Level 1 | Room 1.06 — Computer Laboratory | Standard | daily | Late | 21:00 | 35 | 2026-09-02 | 2026-09-03 | Scheduled | Caretaking Supervisor | Keyboards and shared peripherals wiped. |
| CLN-0007 | Z1 Level 1 | Level 1 circulation and stairs | Standard | daily | Early | 08:30 | 30 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0008 | Z2 Level 2 | Room 2.01 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Suspended | Laboratory Manager | Closed for instrument recalibration until 2026-09-08; do not enter. |
| CLN-0009 | Z2 Level 2 | Room 2.02 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Scheduled | Caretaking Supervisor | Waste segregation — sharps checked by lab staff first. |
| CLN-0010 | Z2 Level 2 | Level 2 washrooms | Enhanced | twice daily | Early | 08:30 | 40 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0011 | Z2 Level 2 | Level 2 circulation and stairs | Standard | daily | Early | 08:30 | 30 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0012 | Z3 Level 3 | Room 3.01 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Scheduled | Caretaking Supervisor | |
| CLN-0013 | Z3 Level 3 | Room 3.02 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Scheduled | Caretaking Supervisor | |
| CLN-0014 | Z3 Level 3 | Level 3 washrooms | Enhanced | twice daily | Early | 08:30 | 40 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0015 | Z3 Level 3 | Level 3 circulation and stairs | Standard | daily | Early | 08:30 | 30 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0016 | Z4 Level 4 | Room 4.01 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Scheduled | Caretaking Supervisor | |
| CLN-0017 | Z4 Level 4 | Room 4.02 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Added | Caretaking Supervisor | Added this shift — spill reported 2026-09-03, deep clean required. |
| CLN-0018 | Z4 Level 4 | Level 4 washrooms | Enhanced | twice daily | Early | 08:30 | 40 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0019 | Z4 Level 4 | Level 4 circulation and stairs | Standard | daily | Early | 08:30 | 30 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0020 | Z5 Level 5 | Room 5.01 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Scheduled | Caretaking Supervisor | |
| CLN-0021 | Z5 Level 5 | Room 5.04 — Academic Office | Standard | daily | Late | 21:00 | 20 | 2026-09-02 | 2026-09-03 | Scheduled | Caretaking Supervisor | |
| CLN-0022 | Z5 Level 5 | Level 5 washrooms | Enhanced | twice daily | Early | 08:30 | 40 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0023 | Z5 Level 5 | Level 5 circulation and stairs | Standard | daily | Early | 08:30 | 30 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0024 | Z1 Level 1 | Room 1.04 — Common Area / Atrium | Presentation | event-driven | Day | 17:30 | 45 | 2026-08-27 | 2026-09-04 | Added | Events Coordinator | Public seminar 2026-09-04 18:00 — reset seating and refresh waste before doors. |
| CLN-0025 | Z0 Ground | Room 0.01 — Main Reception | Presentation | event-driven | Day | 17:30 | 25 | 2026-08-27 | 2026-09-04 | Added | Events Coordinator | Same event — visitor route and check-in desk. |
| CLN-0026 | Z2 Level 2 | Room 2.03 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-01 | 2026-09-03 | Handed over | Caretaking Supervisor | Late shift ran short 2026-09-02; passed to Early on 2026-09-03. |
| CLN-0027 | Z3 Level 3 | Room 3.06 — Research Laboratory | Enhanced | daily | Late | 20:00 | 40 | 2026-09-02 | 2026-09-03 | Suspended | Laboratory Manager | Restricted — COSHH assessment under review until 2026-09-09. |
| CLN-0028 | Z0 Ground | Waste compound and bin store | Standard | daily | Early | 09:00 | 25 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | Segregation checked against the waste register. |
| CLN-0029 | Z0 Ground | Level 0 circulation and stairs | Standard | daily | Early | 08:00 | 30 | 2026-09-03 | 2026-09-04 | Scheduled | Caretaking Supervisor | |
| CLN-0030 | Z5 Level 5 | Room 5.16 — Academic Office | Light | weekly | Late | 21:00 | 15 | 2026-08-29 | 2026-09-05 | Scheduled | Caretaking Supervisor | Low occupancy — spot check only. |

## Exceptions open at the date of this version

- **Room 2.01** and **Room 3.06** are suspended; neither is to be entered by cleaning staff
  until the dates in the note above.
- **Room 4.02** carries an added deep clean from a reported spill.
- **Room 2.03** was handed over from the Late shift and is owed by the Early shift.
