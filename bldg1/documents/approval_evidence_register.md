---
record_type: approval_evidence
owner: "Estates Governance Lead"
authority: "Cardiff University Estates — Governance and Assurance"
source_system: "Approval and Evidence Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Approval and evidence register"
    maps_to: approvals
---

# Approval and Evidence Register — Abacws Building

_**Synthetic demonstration record** — fictional governance data, not a real assurance file._

## What this register is for

Across every stakeholder group, the questions the building could not answer used the same
six words: *evidence, approved, authorised, owner, confirmed, verified*. This register holds
those facts for anything in the building that can be approved — a route, a room's use, a
procedure, a permission group, a patrol circuit, a cleaning standard, a system, a policy.

Each row answers, for one subject:

- **Is it approved**, by which role, under whose authority, and until when?
- **What evidence substantiates it**, referenced and dated?
- **Who is accountable**, and when is it next reviewed?

**Approval and evidence are separate columns.** A thing can be approved with no evidence
recorded, or evidenced but never formally approved. Those are different problems with
different remedies, and collapsing them into one "verified" flag would hide precisely the
gap an auditor is looking for. A row with `status = No evidence` is a finding, not a blank.

**Roles, never people.** `approved_by_role` and `accountable_role` name a role template. The
building does not record who holds what, and this register does not change that.

## Evidence kinds

| kind | what it is |
|---|---|
| **Certificate** | A third-party certificate with a number and an expiry. |
| **Survey** | A walked, dated survey by a named consultancy. |
| **Test record** | A test with a result, retained by the testing body. |
| **Inspection** | A periodic inspection against a checklist. |
| **Sign-off** | A named role accepting a handover or a change. |
| **Committee minute** | A recorded decision of a governing body. |
| **Drawing** | An as-built or approved drawing revision. |

## Approval and evidence register

| approval | subject | subject_kind | decision | approved_by_role | authority | approved_on | valid_until | reference | evidence_type | evidence_ref | evidence_date | accountable_role | review_due | conditions | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| APR-001 | RTE-001 Accessible drop-off to Reception | Accessible route | Approved | Accessibility and Inclusion Lead | Cardiff University Estates | 2026-07-20 | 2027-07-20 | ACC-2026-14 | Survey | HYW-SUR-2026-07 | 2026-07-14 | Accessibility and Inclusion Lead | 2027-01-20 | | Current |
| APR-002 | RTE-006 Reception to Level 2 laboratories | Accessible route | Conditional | Accessibility and Inclusion Lead | Cardiff University Estates | 2026-07-20 | 2027-07-20 | ACC-2026-15 | Survey | HYW-SUR-2026-07 | 2026-07-14 | Accessibility and Inclusion Lead | 2027-01-20 | Heavy manual fire door at the Level 2 lobby; assisted alternative must be published alongside. | Current |
| APR-003 | RTE-015 North stair route | Accessible route | Refused | Accessibility and Inclusion Lead | Cardiff University Estates | 2026-07-20 | | ACC-2026-16 | Survey | HYW-SUR-2026-07 | 2026-07-14 | Accessibility and Inclusion Lead | 2027-01-20 | Not step-free; must never be offered as an accessible option. | Current |
| APR-004 | RTE-016 Lift B route to Level 3 | Accessible route | Withdrawn | Estates Duty Manager | Cardiff University Estates | 2026-08-28 | | ACC-2026-22 | Inspection | LIFT-INSP-2026-08 | 2026-08-28 | Estates Duty Manager | 2026-09-12 | Withdrawn while Lift B is out of service. | Current |
| APR-005 | Room 1.06 Computer Laboratory — teaching use | Space use | Approved | Head of School | School of Computer Science | 2026-01-15 | 2027-08-31 | TEACH-2026-03 | Committee minute | SCS-TLC-2026-01 | 2026-01-15 | Timetabling Lead | 2027-05-31 | | Current |
| APR-006 | Room 1.04 Atrium — public event use | Space use | Approved | Estates Governance Lead | Cardiff University Estates | 2026-02-10 | 2027-02-10 | EVT-USE-2026-02 | Committee minute | EST-GOV-2026-02 | 2026-02-10 | Events and Communications Coordinator | 2026-11-10 | Maximum 120 standing; egress route must remain clear. | Due review |
| APR-007 | Room 2.01 Research Laboratory — COSHH procedure | Procedure | Approved | Laboratory Manager | School of Computer Science | 2026-03-01 | 2027-03-01 | COSHH-2026-11 | Test record | COSHH-TR-2026-03 | 2026-03-01 | Laboratory Manager | 2026-12-01 | | Current |
| APR-008 | Room 3.06 Research Laboratory — COSHH procedure | Procedure | Pending | Laboratory Manager | School of Computer Science | | | COSHH-2026-19 | | | | Laboratory Manager | 2026-09-09 | Under review; no entry authorised until a decision is recorded. | No evidence |
| APR-009 | APG-004 Level 2 research laboratories | Permission group | Approved | Laboratory Manager | Cardiff University Estates | 2026-01-01 | 2027-01-01 | SEC-2026-04 | Sign-off | SEC-SO-2026-01 | 2026-01-01 | Head of Security | 2026-10-01 | Requires COSHH sign-off in addition to the grant. | Current |
| APR-010 | APG-013 Instrument recalibration one-off | Permission group | Conditional | Laboratory Manager | Cardiff University Estates | 2026-09-02 | 2026-09-08 | SEC-2026-31 | Sign-off | SEC-SO-2026-31 | 2026-09-02 | Laboratory Manager | 2026-09-08 | Escorted only; expires without renewal. | Current |
| APR-011 | APG-019 Decommissioned contractor grant | Permission group | Withdrawn | Estates Duty Manager | Cardiff University Estates | 2026-08-31 | | SEC-2026-28 | Sign-off | SEC-SO-2026-28 | 2026-08-31 | Head of Security | | Retained for audit only. | Expired |
| APR-012 | C1-PERIMETER patrol circuit | Patrol circuit | Approved | Head of Security | Cardiff University Estates | 2026-04-01 | 2027-04-01 | SEC-2026-12 | Sign-off | SEC-SO-2026-12 | 2026-04-01 | Head of Security | 2026-10-01 | | Current |
| APR-013 | C3-LABS patrol circuit | Patrol circuit | Conditional | Head of Security | Cardiff University Estates | 2026-04-01 | 2027-04-01 | SEC-2026-13 | Sign-off | SEC-SO-2026-13 | 2026-04-01 | Head of Security | 2026-10-01 | Officer must hold laboratory induction; single-crewed running is not authorised. | Current |
| APR-014 | Enhanced cleaning standard — laboratories | Cleaning standard | Approved | Soft Services Manager | Cardiff University Estates | 2026-01-05 | 2027-01-05 | SOFT-2026-02 | Inspection | SOFT-INSP-2026-01 | 2026-01-05 | Caretaking Supervisor | 2026-10-05 | | Current |
| APR-015 | Presentation cleaning standard — visitor routes | Cleaning standard | Approved | Soft Services Manager | Cardiff University Estates | 2026-01-05 | 2027-01-05 | SOFT-2026-03 | Inspection | SOFT-INSP-2026-01 | 2026-01-05 | Caretaking Supervisor | 2026-10-05 | | Current |
| APR-016 | Fire alarm system — annual certification | System | Approved | Estates Compliance Lead | Cardiff University Estates | 2026-03-14 | 2027-03-14 | FIRE-2026-01 | Certificate | BAFE-2026-8842 | 2026-03-14 | Estates Compliance Lead | 2026-12-14 | | Current |
| APR-017 | Emergency lighting — periodic test | System | Approved | Estates Compliance Lead | Cardiff University Estates | 2026-06-02 | 2027-06-02 | FIRE-2026-07 | Test record | EL-TR-2026-06 | 2026-06-02 | Estates Compliance Lead | 2027-03-02 | | Current |
| APR-018 | Legionella written scheme | Procedure | Approved | Estates Compliance Lead | Cardiff University Estates | 2026-02-20 | 2027-02-20 | WAT-2026-02 | Certificate | SWH-2026-1120 | 2026-02-20 | Estates Compliance Lead | 2026-11-20 | | Current |
| APR-019 | Asbestos management plan | Procedure | Approved | Estates Compliance Lead | Cardiff University Estates | 2025-09-30 | 2026-09-30 | ASB-2025-04 | Survey | HYW-ASB-2025-09 | 2025-09-30 | Estates Compliance Lead | 2026-09-30 | Re-inspection due; survey moved to 2026-09. | Due review |
| APR-020 | Lift maintenance contract | Contract | Approved | Estates Duty Manager | Cardiff University Estates | 2026-01-01 | 2026-12-31 | CON-2026-05 | Sign-off | PROC-SO-2026-05 | 2026-01-01 | Estates Duty Manager | 2026-10-01 | | Current |
| APR-021 | Network switch refresh — capital release | Cost line | Conditional | Estates Finance Business Partner | Cardiff University Finance | 2026-07-15 | 2027-03-31 | FIN-2026-33 | Committee minute | EST-CAP-2026-07 | 2026-07-15 | IT Infrastructure Manager | 2026-12-15 | Release conditional on the outage window being agreed with Teaching. | Current |
| APR-022 | Accessibility improvements — capital release | Cost line | Approved | Estates Finance Business Partner | Cardiff University Finance | 2026-06-10 | 2027-03-31 | FIN-2026-28 | Committee minute | EST-CAP-2026-06 | 2026-06-10 | Accessibility and Inclusion Lead | 2026-12-10 | | Current |
| APR-023 | Lift B controller replacement — unbudgeted | Cost line | Pending | Estates Finance Business Partner | Cardiff University Finance | | | FIN-2026-41 | | | | Estates Duty Manager | 2026-09-12 | Unbudgeted £14,800 commitment awaiting a decision. | No evidence |
| APR-024 | Visitor admission policy | Policy | Approved | Estates Governance Lead | Cardiff University Estates | 2026-02-01 | 2027-02-01 | GOV-2026-06 | Committee minute | EST-GOV-2026-02 | 2026-02-01 | Events and Communications Coordinator | 2026-11-01 | | Current |
| APR-025 | Out-of-hours access policy | Policy | Approved | Estates Governance Lead | Cardiff University Estates | 2026-02-01 | 2027-02-01 | GOV-2026-07 | Committee minute | EST-GOV-2026-02 | 2026-02-01 | Head of Security | 2026-11-01 | | Current |
| APR-026 | Data retention — sensor telemetry | Policy | Approved | Information Governance Lead | Cardiff University | 2026-01-20 | 2028-01-20 | IG-2026-03 | Committee minute | IG-2026-01 | 2026-01-20 | Information Governance Lead | 2027-01-20 | Room-level aggregation only; no individual attribution. | Current |
| APR-027 | AHU-02 as-built drawing revision C | Asset | Approved | Estates Duty Manager | Cardiff University Estates | 2024-11-08 | | HAND-2024-19 | Drawing | ABW-M-201-RevC | 2024-11-08 | Estates Duty Manager | 2026-11-08 | | Current |
| APR-028 | Roof plant enclosure — work at height method | Procedure | Approved | Estates Duty Manager | Cardiff University Estates | 2026-05-12 | 2027-05-12 | H&S-2026-09 | Sign-off | HS-SO-2026-05 | 2026-05-12 | Estates Duty Manager | 2027-02-12 | Permit to work required for every access. | Current |
| APR-029 | Comms room access — IT escort requirement | Procedure | Approved | IT Infrastructure Manager | Cardiff University IT | 2026-03-05 | 2027-03-05 | IT-2026-04 | Sign-off | IT-SO-2026-03 | 2026-03-05 | IT Infrastructure Manager | 2026-12-05 | Escort must be rostered; night cover is not currently provided. | Current |
| APR-030 | Carbon reduction target SUS-CARBON-2030 | Sustainability target | Approved | Energy and Sustainability Manager | University Environmental Strategy | 2025-08-31 | 2029-12-29 | SUS-2025-01 | Committee minute | UES-2025-08 | 2025-08-31 | Energy and Sustainability Manager | 2026-12-31 | | Current |
| APR-031 | Level 5 academic office use | Space use | Approved | Head of School | School of Computer Science | 2026-01-15 | 2027-08-31 | TEACH-2026-05 | Committee minute | SCS-TLC-2026-01 | 2026-01-15 | Head of School | 2027-05-31 | | Current |
| APR-032 | Teaching AV standard — Level 1 rooms | System | Conditional | Teaching and AV Support Lead | School of Computer Science | 2026-04-18 | 2027-04-18 | AV-2026-02 | Inspection | AV-INSP-2026-04 | 2026-04-18 | Teaching and AV Support Lead | 2026-10-18 | Room 1.06 hearing loop untested since installation. | Due review |

## Findings open at the date of this version

Three subjects carry `No evidence` or a lapsed approval and are the register's own audit
findings:

- **APR-008** — Room 3.06 COSHH procedure is pending with no evidence recorded, which is why
  no entry is authorised and why the patrol checkpoint there is unverifiable.
- **APR-023** — the £14,800 Lift B controller commitment has no approval and no evidence.
- **APR-019** — the asbestos management plan is due review and its re-inspection has moved.
- **APR-032** — the Level 1 AV standard is conditional on a hearing-loop test that has not
  been done.
