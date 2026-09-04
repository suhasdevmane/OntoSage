---
record_type: cost_line
owner: "Estates Finance Business Partner"
authority: "Cardiff University Finance — Estates ledger extract"
source_system: "Building Cost Line Register"
effective_from: 2026-08-01
version: "2026.08"
review_due: 2026-10-01
simulated: true
tables:
  - name: "Building cost line register"
    maps_to: cost_lines
---

# Building Cost Line Register — Abacws Building

_**Synthetic demonstration record** — fictional ledger, not a real financial extract._

## How a balance is read here

**Free balance = budget − actual − committed − accrued.** Those are four separate columns
on purpose. A register that folded commitments into actuals could report money as available
when a purchase order has already claimed it, and "decision-ready free balance" is precisely
the figure after all three.

**`variance_cause` is recorded, not inferred.** A line can move because a unit price rose,
because more of it was needed, because the work slipped into another period, or because the
scope changed — and the number alone cannot say which. The remedies differ, so the cause is
a column.

**`coding_check` marks a posting whose cost centre, project or period looks wrong** and
needs an owner to confirm before it is relied on. It is a flag on the row rather than a
separate list, because a list gets stale the moment the row is corrected.

## Spend categories

| category | meaning |
|---|---|
| **Planned** | Programmed or cyclical work with a date set in advance. |
| **Reactive** | Raised in response to a fault or a report. |
| **Statutory** | Required by regulation; not discretionary. |
| **Contract-fixed** | Committed under a term contract at an agreed rate. |
| **Demand-led** | Varies with occupancy, weather or usage. |

## Building cost line register

| line | description | cost_centre | category | period | budget | actual | committed | accrued | variance_cause | supplier | coding_check | status | owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CL-2026-001 | Electricity supply | ABW-UTIL | Demand-led | 2026-08 | 42000.00 | 38150.40 | 0.00 | 3100.00 | Unit price — tariff uplift from 2026-07 | Meridian Energy Supply | false | Open | Estates Finance Business Partner |
| CL-2026-002 | Water and wastewater | ABW-UTIL | Demand-led | 2026-08 | 8600.00 | 7420.15 | 0.00 | 640.00 | Measured quantity — higher laboratory usage | Dwr Cymru Business | false | Open | Estates Finance Business Partner |
| CL-2026-003 | HVAC planned maintenance | ABW-MECH | Contract-fixed | 2026-08 | 24000.00 | 24000.00 | 0.00 | 0.00 | | Meridian Mechanical Ltd | false | Open | Estates Duty Manager |
| CL-2026-004 | HVAC reactive callouts | ABW-MECH | Reactive | 2026-08 | 6000.00 | 9240.00 | 1500.00 | 0.00 | Measured quantity — three AHU-02 belt failures | Meridian Mechanical Ltd | false | Open | Estates Duty Manager |
| CL-2026-005 | Lift maintenance | ABW-MECH | Contract-fixed | 2026-08 | 9000.00 | 9000.00 | 0.00 | 0.00 | | Cambrian Lift Services | false | Open | Estates Duty Manager |
| CL-2026-006 | Lift B repair — out of service | ABW-MECH | Reactive | 2026-08 | 0.00 | 0.00 | 14800.00 | 0.00 | Scope — unbudgeted controller replacement | Cambrian Lift Services | false | Open | Estates Duty Manager |
| CL-2026-007 | Legionella monitoring | ABW-COMP | Statutory | 2026-08 | 5200.00 | 5200.00 | 0.00 | 0.00 | | Severn Water Hygiene | false | Open | Estates Compliance Team |
| CL-2026-008 | Asbestos re-inspection | ABW-COMP | Statutory | 2026-08 | 3400.00 | 0.00 | 3400.00 | 0.00 | Timing — survey moved to 2026-09 | Hywel Surveying | false | Open | Estates Compliance Team |
| CL-2026-009 | Fire alarm servicing | ABW-COMP | Statutory | 2026-08 | 4100.00 | 4100.00 | 0.00 | 0.00 | | Caldicot Fire Systems | false | Open | Estates Compliance Team |
| CL-2026-010 | Cleaning contract | ABW-SOFT | Contract-fixed | 2026-08 | 31000.00 | 31000.00 | 0.00 | 0.00 | | Bright Facilities Ltd | false | Open | Caretaking Supervisor |
| CL-2026-011 | Cleaning consumables | ABW-SOFT | Demand-led | 2026-08 | 2600.00 | 3180.25 | 420.00 | 0.00 | Measured quantity — event programme | Bright Facilities Ltd | true | Query | Caretaking Supervisor |
| CL-2026-012 | Waste and recycling | ABW-SOFT | Demand-led | 2026-08 | 4200.00 | 3960.00 | 0.00 | 310.00 | | Cardiff Waste Partners | false | Open | Caretaking Supervisor |
| CL-2026-013 | Window cleaning | ABW-SOFT | Planned | 2026-08 | 3800.00 | 3800.00 | 0.00 | 0.00 | | Summit Access Cleaning | false | Closed | Caretaking Supervisor |
| CL-2026-014 | Security staffing | ABW-SEC | Contract-fixed | 2026-08 | 27500.00 | 29100.00 | 0.00 | 0.00 | Measured quantity — single-crewed cover backfilled | Vigil Security Services | false | Open | Head of Security |
| CL-2026-015 | CCTV maintenance | ABW-SEC | Contract-fixed | 2026-08 | 4600.00 | 4600.00 | 0.00 | 0.00 | | Vigil Security Services | false | Open | Head of Security |
| CL-2026-016 | Access control reader replacement | ABW-SEC | Reactive | 2026-08 | 1200.00 | 0.00 | 980.00 | 0.00 | Scope — comms room tag faulty | Vigil Security Services | false | Open | Head of Security |
| CL-2026-017 | Network switch refresh | ABW-IT | Planned | 2026-08 | 18000.00 | 0.00 | 18000.00 | 0.00 | Timing — delivery slipped to 2026-09 | Tamesis Networks | false | Open | IT Infrastructure Manager |
| CL-2026-018 | Wireless access point licences | ABW-IT | Contract-fixed | 2026-08 | 7400.00 | 7400.00 | 0.00 | 0.00 | | Tamesis Networks | false | Open | IT Infrastructure Manager |
| CL-2026-019 | Laboratory gas supply | ABW-LAB | Demand-led | 2026-08 | 11200.00 | 12850.00 | 900.00 | 0.00 | Unit price — cylinder rate increase | Severn Lab Gases | true | Query | Laboratory Manager |
| CL-2026-020 | Laboratory instrument calibration | ABW-LAB | Planned | 2026-08 | 8800.00 | 8800.00 | 0.00 | 0.00 | | Precision Calibration Ltd | false | Open | Laboratory Manager |
| CL-2026-021 | Small tools and sundries | ABW-MECH | Demand-led | 2026-08 | 900.00 | 1640.00 | 0.00 | 0.00 | Measured quantity — 23 separate purchases under £100 | Various | true | Query | Estates Duty Manager |
| CL-2026-022 | Grounds maintenance | ABW-SOFT | Planned | 2026-08 | 2200.00 | 2200.00 | 0.00 | 0.00 | | Cardiff Grounds Care | false | Closed | Caretaking Supervisor |
| CL-2026-023 | Accessibility improvements | ABW-CAP | Planned | 2026-08 | 15000.00 | 4200.00 | 9600.00 | 0.00 | Timing — phased across the quarter | Hywel Access Ltd | false | Open | Accessibility and Inclusion Team |
| CL-2026-024 | Energy metering upgrade | ABW-CAP | Planned | 2026-08 | 12500.00 | 0.00 | 12500.00 | 0.00 | Timing — awaiting outage window | Meridian Energy Supply | false | Open | Energy and Sustainability Manager |

## Positions worth an owner's attention

- **CL-2026-021** carries 23 separate purchases under £100 against a £900 budget. The
  catalogues ask whether repeated low-value purchases represent one aggregable requirement;
  this is that case, and it is flagged for a coding check.
- **CL-2026-011** and **CL-2026-019** are also flagged for coding checks and sit in query.
- **CL-2026-006** is an unbudgeted commitment of £14,800 for the Lift B controller, which is
  the same outage the accessible route register records as closing RTE-016.
