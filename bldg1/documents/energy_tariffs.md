---
record_type: tariff
owner: "Energy and Sustainability Manager"
authority: "Cardiff University Estates"
source_system: "Energy Tariff Register"
effective_from: 2025-08-31
version: "2026.1"
review_due: 2027-08-31
simulated: true
tables:
  - name: "Tariff register"
    maps_to: tariffs
---

# Energy Tariff Register — Abacws Building

_**Synthetic demonstration record** — fictional history, not a real compliance document._

## How cost is computed

A cost answer is metered consumption multiplied by the unit rate **of the tariff in force
for that period**, plus the standing charge for the days covered. Where no tariff covers a
period, no cost is stated — an assumed rate produces a confident wrong number, and the
previous year's rate is not this year's.

Rates are shown per kWh for electricity and gas, and per cubic metre for water. All
rates exclude VAT.

## Tariff register

| reference | utility | unit_rate | standing_charge | currency | start | end | supplier |
|---|---|---|---|---|---|---|---|
| TAR-ELEC-2026 | Electricity | 0.2847 | 0.6120 | GBP | 2025-12-31 | 2026-12-31 | Cardiff University Estates energy framework |
| TAR-GAS-2026 | Gas | 0.0691 | 0.3410 | GBP | 2025-12-31 | 2026-12-31 | Cardiff University Estates energy framework |
| TAR-WATER-2026 | Water | 1.9450 | 0.0000 | GBP | 2025-12-31 | 2026-12-31 | Dwr Cymru Welsh Water |
| TAR-ELEC-2025 | Electricity | 0.3102 | 0.5880 | GBP | 2024-12-31 | 2025-12-30 | Cardiff University Estates energy framework |

## Authority

Rates are set by the university energy framework and are not negotiated at building level.
The Energy and Sustainability Manager owns this register.
