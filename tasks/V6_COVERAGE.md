# V6 Question Coverage

**Generated 2026-08-21 15:58 UTC** by `scripts/build_coverage_report.py` — do not hand-edit.
Re-run after any tracker change and after every replay.

---

## 1. What the supervisors' questions need, and what provides it

Demand counted over the **480 supervisor catalogue questions**, by matching each
question's own `Sensors_Required` / `Authoritative_Sources` text. A question usually needs
several families, so the column sums past 100% — this is a demand ranking, not a partition.

| Source family | Questions | Share | Provided by | Status |
|---|---:|---:|---|---|
| Occupancy / doorway counts | 374 | 78% | exists | already in system |
| Opening hours & closures | 271 | 56% | V6-T57 | todo |
| Room bookings / reservations | 249 | 52% | V6-T57 | todo |
| Lift status | 162 | 34% | V6-T58 | todo |
| Network / Wi-Fi / IT service | 158 | 33% | V6-T58 | todo |
| BMS / HVAC plant state | 117 | 24% | V6-T59 | todo |
| Timetable / teaching schedule | 99 | 21% | V6-T57 | todo |
| AV / teaching equipment | 94 | 20% | V6-T58 | todo |
| Weather / outdoor reference | 73 | 15% | exists | already in system |
| Accessibility inventory | 59 | 12% | V6-T60 | todo |
| Compliance register | 57 | 12% | exists | already in system |
| Electricity / submeters | 47 | 10% | V6-T59 | todo |
| Maintenance / work orders | 39 | 8% | V6-T60 | todo |
| Alarms / safety systems | 39 | 8% | V6-T60 | todo |
| Cleaning / service schedules | 23 | 5% | V6-T60 | todo |
| Access control / entitlement | 19 | 4% | V6-T57 | todo |
| Desk / workspace allocation | 17 | 4% | V6-T57 | todo |
| Equipment / lab readiness | 12 | 2% | V6-T58 | todo |
| Water / leak detection | 7 | 1% | V6-T44 | todo |
| Waste / recycling | 1 | 0% | V6-T43 | done |

## 2. Readiness tiers (the supervisors' own classification)

| Tier | Meaning | Count | Share |
|---|---|---:|---:|
| **R1** | Answerable with core sensing + basic verified spatial/access data | 27 | 5.6% |
| **R2** | Needs an integration — timetable, booking, BMS, access, AV, lift, network, meters | 303 | 63.1% |
| **R3** | Needs research-grade validation, governed data, or restricted permissions | 150 | 31.2% |

R2 and R3 are addressed by phase **P12** (V6-T56…T63), which provisions the missing sources
as *declared synthetic data* generated from each building's own graph. A synthetic booking
stays synthetic: V6-T62 requires every answer resting on one to say so.

## 3. Readiness by stakeholder

| Stakeholder | R1 | R2 | R3 | Total |
|---|---:|---:|---:|---:|
| Undergraduate Student | 12 | 45 | 23 | 80 |
| Taught Postgraduate Student | 6 | 52 | 22 | 80 |
| Lecturer or Tutor | 4 | 54 | 22 | 80 |
| PhD Student | 2 | 52 | 26 | 80 |
| Academic Office Occupant | 2 | 62 | 16 | 80 |
| Research Staff | 1 | 38 | 41 | 80 |

## 4. V6 progress

**25 / 64 tasks done** (39%)

| Phase | Done | Total |
|---|---:|---:|
| P0-Contract | 4 | 8 |
| P1-Observability | 3 | 6 |
| P10-Certification | 1 | 3 |
| P11-V5Carryover | 0 | 5 |
| P12-SyntheticData | 0 | 8 |
| P2-NonSubstitution | 3 | 4 |
| P3-Quality | 3 | 5 |
| P4-Authority | 0 | 7 |
| P5-Access | 4 | 4 |
| P6-Consequence | 2 | 4 |
| P7-Recommendation | 1 | 4 |
| P8-Analysis | 2 | 3 |
| P9-Domains | 2 | 3 |

## 5. Measured answerability

Latest replay: `postrepair_60_summary.csv` (2026-08-19 14:16)

Regenerate after each replay to refresh this section.

---

Corpus: **1580 questions** — 1100 V5 synthetic bank + 480 supervisor catalogue.
