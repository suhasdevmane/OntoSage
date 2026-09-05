---
record_type: evacuation_provision
owner: "Building Fire Warden Coordinator"
authority: "Cardiff University Fire Safety and Student Support"
source_system: "Evacuation Provision Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Evacuation provision register"
    maps_to: evacuation_provisions
---

# Evacuation Provision Register - Abacws Building

_**Synthetic demonstration record** - fictional states, not a live PEEP file._

## What this records, and the line it does not cross

Refuge points, evacuation chairs, communication units and personal plans were held only as
prose. Their **existence, location, state and review date** are operational facts a fire
warden, an accessibility adviser and a responding officer all need.

**Whose plan it is, is not recorded.** A personal emergency evacuation plan names a disabled
person by definition, and this register is answerable by anyone the access decision point
admits. Personal plans therefore appear as a **count and a review date against a floor** -
never as a subject. *"How many personal plans are overdue for review?"* is answerable;
*"whose"* is not, and that asymmetry is the whole design rather than an omission.

Two rows state a failure that equipment lists normally hide:

- **EV-003** is a refuge point whose communication unit does not work. A place to wait with
  no way to say you are there is not a refuge.
- **EV-007** is a serviceable evacuation chair with **no trained operator on that floor**.
  Equipment without somebody trained to use it is not a provision, and an inventory that
  counts the chair would report Level 5 as covered.

## Evacuation provision register

| code | name | kind | location | floor | state | last_checked | review_due | owner | status | note |
|---|---|---|---|---|---|---|---|---|---|---|
| EV-001 | Refuge point - Level 1 north stair | refuge point | North Stairwell - Fire Escape Route | 1 | Communication unit tested and working | 2026-08-14 | 2026-11-14 | Building Fire Warden Coordinator | Active |  |
| EV-002 | Refuge point - Level 2 north stair | refuge point | North Stairwell - Fire Escape Route | 2 | Communication unit tested and working | 2026-08-14 | 2026-11-14 | Building Fire Warden Coordinator | Active |  |
| EV-003 | Refuge point - Level 3 north stair | refuge point | North Stairwell - Fire Escape Route | 3 | Communication unit FAULTY - no two-way audio | 2026-08-14 | 2026-11-14 | Building Fire Warden Coordinator | Defective | A refuge point whose communication unit does not work is a place to wait with no way to say you are there |
| EV-004 | Refuge point - Level 4 north stair | refuge point | North Stairwell - Fire Escape Route | 4 | Communication unit tested and working | 2026-08-14 | 2026-11-14 | Building Fire Warden Coordinator | Active |  |
| EV-005 | Refuge point - Level 5 north stair | refuge point | North Stairwell - Fire Escape Route | 5 | Communication unit tested and working | 2026-08-14 | 2026-11-14 | Building Fire Warden Coordinator | Active |  |
| EV-006 | Evacuation chair - Level 3 north stair | evacuation chair | North Stairwell - Fire Escape Route | 3 | Serviceable, trained operators on Level 3 | 2026-06-11 | 2026-12-11 | Building Fire Warden Coordinator | Active |  |
| EV-007 | Evacuation chair - Level 5 north stair | evacuation chair | North Stairwell - Fire Escape Route | 5 | Serviceable, NO trained operator currently on Level 5 | 2026-06-11 | 2026-12-11 | Building Fire Warden Coordinator | Defective | The chair is present and nobody on the floor is trained to use it. Equipment without a trained operator is not a provision |
| EV-008 | Assisted route - main lift core to ground | assisted route | Main lift core | 0 | Available while the lift is in service | 2026-06-16 | 2026-12-16 | Accessibility Adviser | Active | Depends entirely on AEP-011, the only step-free route between levels; a lift failure removes this provision |
| EV-009 | Personal plans - Level 3 occupants | personal plan | Level 3 | 3 | 4 plans held, all reviewed within 12 months | 2026-04-22 | 2027-04-22 | Accessibility Adviser | Active | Count and review date only. Whose plans these are is deliberately not recorded here |
| EV-010 | Personal plans - Level 4 occupants | personal plan | Level 4 | 4 | 2 plans held, both reviewed within 12 months | 2026-04-22 | 2027-04-22 | Accessibility Adviser | Active | Count and review date only |
| EV-011 | Personal plans - Level 5 occupants | personal plan | Level 5 | 5 | 3 plans held, ONE OVERDUE for review | 2025-08-29 | 2026-08-29 | Accessibility Adviser | Overdue | Review date passed on 2026-08-29. Count and review date only; whose plan is overdue is not recorded |
| EV-012 | Assembly point A | assisted route | Fire Assembly Point A - Senghennydd Road (North side) | 0 | Level approach, step-free from the main entrance | 2026-03-11 | 2027-03-11 | Building Fire Warden Coordinator | Active |  |

**12 provisions. 2 are defective and 1 overdue. Every assisted route between levels depends on one lift (AEP-011), so a lift failure removes step-free evacuation from the building rather than degrading it.**
