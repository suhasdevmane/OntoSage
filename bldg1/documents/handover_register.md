---
record_type: handover
owner: "Estates Asset Information"
authority: "Cardiff University Estates"
source_system: "Handover and O&M Register"
effective_from: 2025-08-31
version: "1.8"
review_due: 2027-08-31
simulated: true
tables:
  - name: "Handover register"
    maps_to: handover
---

# Project Handover and O&M Register — Abacws Building

_**Synthetic demonstration record** — fictional history, not a real compliance document._

## What a handover record is for

A claim that a system is *commissioned* must rest on a record, not on a flag somebody
set. Three assets below are marked **outstanding**: no handover documentation is held for
them, so any commissioning claim about those assets is unverified, and the register says
so rather than staying silent.

## Handover register

| reference | asset | document_kind | issued | issued_by | status |
|---|---|---|---|---|---|
| HO-AHU01-OM | AHU-01 — roof plant enclosure | O&M manual | 2024-09-30 | Meridian Mechanical Ltd | Held |
| HO-AHU02-OM | AHU-02 — roof plant enclosure | O&M manual | 2024-09-30 | Meridian Mechanical Ltd | Held |
| HO-BMS-COMM | BMS head end and field controllers | Commissioning certificate | 2025-01-08 | Meridian Controls | Held |
| HO-CHILL-OM | Chiller 1 — basement plant room | O&M manual | 2022-09-11 | Coldstream Refrigeration | Outstanding |
| HO-LIFT1-LOLER | Passenger lift 1 | Thorough examination record | 2026-05-03 | Vertical Transport Services Ltd | Held |
| HO-PV-ASBUILT | Roof PV array and inverters | As-built drawing set | 2025-12-24 | Brecon Solar | Held |
| HO-GEN-OM | Standby generator | O&M manual | 2024-03-14 | Powerline Generation | Outstanding |
| HO-FIRE-CERT | Fire alarm system | Commissioning certificate | 2026-01-13 | Cambrian Fire Systems | Held |
| HO-SPRINK-OM | Sprinkler system | O&M manual | 2022-04-14 | Unknown | Outstanding |

## Retrieval

Held documents are filed with Estates Asset Information. An outstanding record is chased
from the original installer where one can still be identified; HO-SPRINK-OM predates the
current register and its installer is not recorded.
