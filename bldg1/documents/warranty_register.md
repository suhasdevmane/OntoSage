---
record_type: warranty
owner: "Estates Asset Information"
authority: "Cardiff University Estates"
source_system: "Warranty Register"
effective_from: 2025-08-31
version: "2.4"
review_due: 2027-08-31
simulated: true
tables:
  - name: "Warranty register"
    maps_to: warranties
---

# Warranty Register — Abacws Building

_**Synthetic demonstration record** — fictional history, not a real compliance document._

## Why this matters to a work order

Whether a repair is chargeable depends on whether the asset is in warranty. WTY-GEN-2023
is recorded **void**: the generator was serviced outside the approved regime in 2025 and
the manufacturer withdrew cover. A void warranty is not an expired one and the register
keeps them distinct.

## Warranty register

| reference | asset | provider | start | end | status |
|---|---|---|---|---|---|
| WTY-AHU01-2024 | AHU-01 — roof plant enclosure | Meridian Mechanical Ltd | 2024-09-30 | 2026-09-30 | Active |
| WTY-AHU02-2024 | AHU-02 — roof plant enclosure | Meridian Mechanical Ltd | 2024-09-30 | 2026-09-30 | Active |
| WTY-CHILL-2022 | Chiller 1 — basement plant room | Coldstream Refrigeration | 2022-09-11 | 2025-09-15 | Expired |
| WTY-LIFT1-2021 | Passenger lift 1 | Vertical Transport Services Ltd | 2021-09-26 | 2024-09-30 | Expired |
| WTY-BMS-2024 | BMS head end and field controllers | Meridian Controls | 2024-12-29 | 2026-12-29 | Active |
| WTY-PV-2025 | Roof PV array and inverters | Brecon Solar | 2025-12-14 | 2029-12-13 | Active |
| WTY-GEN-2023 | Standby generator | Powerline Generation | 2024-03-14 | 2026-03-14 | Void |

## Claims

Claims are raised by the Estates Asset Information owner. This service reports warranty
state; it never asserts that a claim will be accepted.
