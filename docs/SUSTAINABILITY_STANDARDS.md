# Sustainability Standards Mapping

Action Plan References: #4 (mapping), #11 (evaluation tables), #1 (tempered claims)

This document links implemented and planned analytics functions to major building performance and sustainability standards.

## Covered Standards

| Code / Standard | Domain | Core Focus | Key Threshold Examples |
|-----------------|--------|-----------|------------------------|
| ASHRAE 55       | Thermal Comfort | Occupant comfort (temperature, humidity) | 18–24 °C (illustrative), 40–60 %RH |
| ASHRAE 62.1     | IAQ / Ventilation | Minimum ventilation & contaminant control | CO₂ < 1000 ppm (design proxy) |
| ASHRAE 90.1     | Energy Efficiency | Envelope, systems, energy cost budget | EUI relative to baseline |
| ISO 50001       | Energy Management | Continuous energy performance improvement | Baselines + EnPIs |
| WELL (Air, Thermal, Sound) | Health & Wellbeing | IAQ, comfort, acoustic performance | CO₂, PM, Noise < 55 dB(A) |
| LEED (EQ, EA)   | Indoor Environmental Quality / Energy | Performance credit attainment | Ventilation effectiveness, EUI |

> NOTE: Thresholds here are representative; project deployments must configure jurisdiction-specific or design-specific values.

## Analytics Function Mapping

| Analytics Function | Implemented? | Standard(s) Supported | Purpose | Gaps / Next Steps |
|--------------------|--------------|-----------------------|---------|-------------------|
| `analyze_temperatures` | Yes | ASHRAE 55, WELL | Comfort band assessment | Add PMV/PPD extension |
| `analyze_humidity` | Yes | ASHRAE 55, WELL | RH compliance | Correlate with temperature for comfort index |
| `analyze_co2` (implicit via generic handlers) | Partial | ASHRAE 62.1, WELL, LEED EQ | CO₂ ventilation proxy | Add ventilation effectiveness calc |
| `percentage_time_in_range` | Yes | ASHRAE 55 / 62.1 / WELL | Compliance ratio metric | Add per-standard presets & reporting bundle |
| `difference_from_setpoint` | Yes | ASHRAE 55, ISO 50001 | Deviation analysis | Integrate adaptive comfort logic |
| `baseline_comparison` | Yes | ISO 50001, ASHRAE 90.1 | Performance drift vs baseline | Add weather normalization hook |
| `rate_of_change` | Yes | Monitoring / Faults | Detect rapid shifts (potential faults) | Link to fault taxonomy |
| `rolling_trend_slope` | Yes | Energy / IAQ trend detection | Early anomaly slope | Add seasonal decomposition |
| `missing_data_report` | Yes | Data Quality (All) | Coverage KPI | Add data completeness SLA export |
| `time_to_threshold` | Yes | Proactive Alerts | Predict threshold breach | Integrate confidence intervals |
| `top_n_by_latest` / `bottom_n_by_latest` | Yes | Prioritization | Rank improvement candidates | Add weighting (criticality) |
| `correlate_sensors` | Legacy | Diagnostics | Cross-variable relationships | Add significance testing |
| `calculate_eui` | Planned | ASHRAE 90.1, ISO 50001, LEED EA | Annualized energy intensity | Requires energy meter ingestion |
| `ventilation_effectiveness` | Planned | ASHRAE 62.1, LEED EQ | Outdoor air effectiveness (CO₂ differential) | Needs return & outdoor CO₂ points |
| `comfort_pmv_ppd` | Planned | ASHRAE 55 | Predictive mean vote / % dissatisfied | Requires metabolic rate & clothing assumptions |
| `acoustic_compliance` | Planned | WELL (Sound) | Noise threshold evaluation | Add octave-band support |
| `iaq_composite_index` | Planned | WELL, LEED EQ | Multi-pollutant scoring | Aggregation weighting scheme |
| `fault_detection_score` | Planned | Operational Reliability | Aggregated anomaly indicator | Fault rule library |

## Parameter Profiles (Planned)

Profiles will allow automatic parameter injection based on declared `standard`:

```jsonc
{
  "ASHRAE_55": {
    "temperature_c": {"min": 18, "max": 24},
    "humidity_rh": {"min": 40, "max": 60}
  },
  "ASHRAE_62_1": {
    "co2_ppm": {"max": 1000, "design_max": 1500}
  },
  "WELL_AIR": {
    "pm2_5_ugm3": {"max": 35},
    "pm10_ugm3": {"max": 50},
    "hcho_mgm3": {"max": 0.1},
    "co_ppm": {"max": 9}
  },
  "WELL_SOUND": {"noise_db": {"max": 55}}
}
```

## Standard-to-Metric Coverage Matrix

| Metric / Sensor Class | ASHRAE 55 | ASHRAE 62.1 | ASHRAE 90.1 | ISO 50001 | WELL | LEED |
|-----------------------|-----------|-------------|-------------|-----------|------|------|
| Air Temperature       | ✓         |             | (process)   | (enPI)    | ✓    | ✓ (EQ) |
| Relative Humidity     | ✓         |             |             |           | ✓    | ✓ (EQ) |
| CO₂ Concentration     |           | ✓           |             |           | ✓    | ✓ (EQ) |
| PM2.5 / PM10          |           |             |             |           | ✓    | ✓ (EQ) |
| Formaldehyde (HCHO)   |           |             |             |           | ✓    | ✓ (EQ) |
| Noise Levels          |           |             |             |           | ✓    |        |
| Energy (kWh)          |           |             | ✓           | ✓         |      | ✓ (EA) |
| Ventilation Flow      |           | ✓           |             |           | ✓    | ✓ (EQ) |

## Reporting Bundles (Planned)

A reporting bundle will orchestrate multiple analytics runs and produce a composite compliance JSON suitable for export:

```jsonc
{
  "standard": "ASHRAE_62_1",
  "period": "2025-02-01/2025-02-28",
  "zones_evaluated": 18,
  "co2_compliance_rate": 0.93,
  "ventilation_effectiveness_mean": 0.78,
  "top_violations": ["Zone_5.12", "Zone_6.03"],
  "recommendations": [
    "Increase outdoor air fraction for AHU_02 during peak occupancy",
    "Investigate persistent CO₂ plateau in Zone_6.03"
  ]
}
```

## Integration Points

- Action Server: Accept `standard` slot to auto-select analytics sequence.
- Decider Service: Pattern match phrases like "ASHRAE", "WELL", "LEED" → inject bundle analytics plan.
- Analytics Microservice: Provide `/profiles` endpoint returning parameter sets.

## Roadmap Increments

| Phase | Deliverable | PR Milestone |
|-------|-------------|--------------|
| P1 | Map existing analytics to standards (this doc) | M1 |
| P2 | Implement `calculate_eui`, `ventilation_effectiveness` | M2 |
| P3 | Parameter profiles + bundle endpoint | M3 |
| P4 | Comfort PMV/PPD prototype | M4 |
| P5 | Composite compliance report export (CSV/JSON) | M5 |
| P6 | Documentation + evaluation tables in manuscript | Camera-ready |

## Limitations
- Current implementation lacks direct energy meter ingestion; EUI is pending.
- No PMV/PPD thermal comfort model yet (requires additional environmental + personal parameters).
- Ventilation effectiveness requires reliable outdoor and return air CO₂ points; synthetic buildings may approximate values.
- Acoustic analysis currently only uses scalar dB(A); octave band & NC/RC ratings not computed.

## Change Log
| Date | Change | Author |
|------|--------|--------|
| 2025-10-06 | Initial draft created | System Assistant |
