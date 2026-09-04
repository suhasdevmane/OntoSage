---
record_type: access_permission
owner: "Access Control Administrator"
authority: "Cardiff University Estates — Security Systems"
source_system: "Access Permission Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Access permission register"
    maps_to: access_permissions
---

# Access Permission Register — Abacws Building

_**Synthetic demonstration record** — fictional configuration, not a live security export._

## What this register records, and what it deliberately does not

Each row is a **permission group**: a named grant, over one controlled opening, to a **role
template**, under a time profile.

**No individual is named anywhere in this register, by design.** The access catalogues ask
which entitlements a role justifies, how concurrent affiliations combine, and whether a
scope needs a formal exception — all answerable from role templates. They also ask the
system not to expose who holds what. So "which permission group controls this opening" is
answerable here and "who can open this door" is not, and that is a decision rather than a
gap.

**Inheritance is data, not prose.** A group that inherits names its parent, so the path from
a role to an opening can be followed and reported. A blank `inherits_from` means the group
stands alone.

**An override is recorded on the row it overrides.** A time profile that is superseded by a
global mode or a controller rule is only discoverable if the superseding thing is named
where someone looking at the group will see it.

## Time profiles

| profile | hours |
|---|---|
| `CORE` | Monday–Friday 07:00–19:00 |
| `EXTENDED` | Monday–Sunday 06:00–23:00 |
| `H24` | Continuous |
| `ESCORTED` | By arrangement only, with an accountable escort present |

## Global modes that override a time profile

| mode | effect |
|---|---|
| `FIRE_EVAC` | All openings fail safe and release; every profile is suspended. |
| `LOCKDOWN` | Only `H24` security groups retain access. |
| `OUT_OF_HOURS_LAB_HOLD` | Laboratory openings drop to `ESCORTED` regardless of profile. |

## Access permission register

| group | name | opening | role_template | inherits_from | time_profile | override | approval_route | valid_from | valid_to | status | owner | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| APG-001 | Building core access | Main Entrance | All staff and students | | CORE | FIRE_EVAC | Automatic on enrolment | 2026-01-01 | | active | Access Control Administrator | Base grant every other group inherits from. |
| APG-002 | Building extended access | Main Entrance | Academic staff | APG-001 | EXTENDED | FIRE_EVAC, LOCKDOWN | Line manager | 2026-01-01 | | active | Access Control Administrator | |
| APG-003 | Level 1 teaching spaces | Floor 1 Entrance | Teaching staff | APG-001 | CORE | FIRE_EVAC | Timetable office | 2026-01-01 | | active | Access Control Administrator | |
| APG-004 | Level 2 research laboratories | Floor 2 Entrance | Research staff | APG-002 | EXTENDED | FIRE_EVAC, OUT_OF_HOURS_LAB_HOLD | Laboratory manager plus COSHH sign-off | 2026-01-01 | | active | Laboratory Manager | Out of hours drops to escorted, not denied. |
| APG-005 | Level 3 research laboratories | Floor 3 Entrance | Research staff | APG-002 | EXTENDED | FIRE_EVAC, OUT_OF_HOURS_LAB_HOLD | Laboratory manager plus COSHH sign-off | 2026-01-01 | | active | Laboratory Manager | |
| APG-006 | Level 4 research laboratories | Floor 4 Entrance | Research staff | APG-002 | EXTENDED | FIRE_EVAC, OUT_OF_HOURS_LAB_HOLD | Laboratory manager plus COSHH sign-off | 2026-01-01 | | active | Laboratory Manager | |
| APG-007 | Level 5 academic offices | Floor 5 Entrance | Academic staff | APG-002 | EXTENDED | FIRE_EVAC | Line manager | 2026-01-01 | | active | Access Control Administrator | |
| APG-008 | Mechanical plant room | Room 0.04 — Mechanical Plant Room | Estates maintenance | | H24 | FIRE_EVAC | Estates duty manager plus permit to work | 2026-01-01 | | active | Estates Duty Manager | Permit required in addition to the grant. |
| APG-009 | Security patrol — all openings | All controlled openings | Security officers | | H24 | | Head of Security | 2026-01-01 | | active | Head of Security | Retains access under LOCKDOWN. |
| APG-010 | Cleaning and caretaking round | All floor entrances | Caretaking and cleaning | APG-001 | CORE | FIRE_EVAC, LOCKDOWN | Soft services supervisor | 2026-01-01 | | active | Caretaking Supervisor | Excludes laboratories; those are escorted. |
| APG-011 | External maintenance contractor — lifts | Main Entrance | External contractor | | ESCORTED | FIRE_EVAC, LOCKDOWN | Estates duty manager plus signed-in escort | 2026-08-01 | 2026-12-31 | active | Estates Duty Manager | Bounded to the contract term. |
| APG-012 | Visitor and event access | Main Entrance | Registered visitor | | CORE | FIRE_EVAC, LOCKDOWN | Event registration | 2026-09-01 | | active | Events and Communications Coordinator | Valid only while a registered event is running. |
| APG-013 | Instrument recalibration — one-off | Room 2.01 — Research Laboratory | External contractor | | ESCORTED | FIRE_EVAC, LOCKDOWN | Laboratory manager, single approval | 2026-09-02 | 2026-09-08 | exception | Laboratory Manager | Bounded to one opening and one week; expires without renewal. |
| APG-014 | Sponsored project collaborator | Floor 3 Entrance | Sponsored collaborator | APG-001 | CORE | FIRE_EVAC, LOCKDOWN, OUT_OF_HOURS_LAB_HOLD | Accountable sponsor plus purpose statement | 2026-07-01 | 2027-06-30 | active | Research Office | Bounded by sponsor and end date. |
| APG-015 | Out-of-hours study access | Floor 1 Entrance | Postgraduate researcher | APG-001 | EXTENDED | FIRE_EVAC, LOCKDOWN | School office | 2026-01-01 | | active | Access Control Administrator | |
| APG-016 | Roof plant access | Roof access hatch | Estates maintenance | APG-008 | ESCORTED | FIRE_EVAC | Estates duty manager plus permit to work and work-at-height sign-off | 2026-01-01 | | active | Estates Duty Manager | |
| APG-017 | Waste compound | Waste compound gate | Caretaking and cleaning | APG-010 | CORE | FIRE_EVAC | Soft services supervisor | 2026-01-01 | | active | Caretaking Supervisor | |
| APG-018 | Server and comms room | Room 0.07 — Comms Room | IT infrastructure | | H24 | FIRE_EVAC | IT infrastructure manager | 2026-01-01 | | active | IT Infrastructure Manager | |
| APG-019 | Decommissioned — old contractor grant | Floor 4 Entrance | External contractor | | EXTENDED | | Estates duty manager | 2025-09-01 | 2026-08-31 | withdrawn | Estates Duty Manager | Withdrawn at contract end; retained for audit. |
| APG-020 | Suspended pending review | Room 3.06 — Research Laboratory | Research staff | APG-005 | EXTENDED | FIRE_EVAC, OUT_OF_HOURS_LAB_HOLD | Laboratory manager | 2026-01-01 | | suspended | Laboratory Manager | Suspended while the COSHH assessment is under review to 2026-09-09. |

## Exceptions and expiries at the date of this version

- **APG-013** is a one-off exception bounded to a single opening and expires 2026-09-08.
- **APG-020** is suspended pending a COSHH review, so Room 3.06 is unreachable under any
  inherited grant.
- **APG-019** is withdrawn and retained only so an audit can see that it once existed.
- **APG-011** and **APG-014** are bounded by an end date; neither renews automatically.
