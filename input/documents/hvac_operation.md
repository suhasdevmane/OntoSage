# HVAC Operation — Abacws Building, Cardiff University

## System Overview

Abacws uses a **central air handling unit (AHU)** system with variable air volume (VAV) distribution to each floor. The system provides heating, cooling, and mechanical ventilation year-round.

- **Heating**: Gas-fired boilers supply hot water to perimeter fan coil units and the AHU heating coil
- **Cooling**: District chilled water from the campus network supplies the AHU cooling coil
- **Ventilation**: 100% fresh air supply with heat recovery (rotary wheel heat exchanger); minimum fresh air per occupant: 10 L/s per person (CIBSE Guide A)
- **Control**: Honeywell EBI building management system; automatic control of supply air temperature, supply air volume, and room setpoints

## Setpoints and Operating Hours

| Parameter | Occupied (07:00–22:00) | Unoccupied |
|-----------|------------------------|------------|
| Heating setpoint | 21°C | 15°C (frost protection) |
| Cooling setpoint | 24°C | Not active |
| Relative humidity target | 40–60% | Uncontrolled |
| CO2 limit (demand control) | 1000 ppm | Ventilation reduced |
| Minimum fresh air flow | 10 L/s/person | 10% of design flow |

Operating schedule overrides can be requested from the Estates team for after-hours events.

## Known Limitations

- **Floor 5 south-facing offices**: Solar gain can cause temperatures above 24°C on sunny afternoons; the AHU cooling capacity is sized for steady-state, not peak solar events. Opening windows (where operable) is the recommended mitigation.
- **Server room (5.20)**: Has dedicated precision cooling unit; not on the main AHU zone — reports its own setpoint independently.
- **Thermal lag**: The building structure has moderate thermal mass; setpoint changes take approximately 30 minutes to stabilise.

## Fault Reporting

HVAC faults should be reported to the Estates helpdesk:
- **Online**: Cardiff Estates portal (intranet.cardiff.ac.uk/estates)
- **Phone**: 029 2087 6026 (08:00–18:00 weekdays)
- **Emergency (out of hours)**: 029 2087 4444 (Security, who will escalate)

## Air Quality Targets

| Pollutant | Target | Alert Threshold |
|-----------|--------|----------------|
| CO2 | < 800 ppm (occupied) | > 1000 ppm triggers demand-control ventilation boost |
| TVOC | < 300 ppb | > 500 ppb triggers investigation |
| PM2.5 | < 12 μg/m³ (24h avg) | > 35 μg/m³ triggers air quality alert |
| Relative humidity | 40–60% | < 30% or > 70% triggers fault log |

## Maintenance Schedule

- **Filters**: Changed every 6 months (April and October) — HEPA G4/F7 combination
- **Heat recovery wheel**: Inspected quarterly, cleaned annually
- **Boiler servicing**: Annual (July, during summer shutdown)
- **Chiller checks**: Monthly inspection by campus facilities team
- **Fire dampers**: Tested annually as part of fire safety compliance

## OntoSage Integration

OntoSage monitors temperature, humidity, CO2, TVOC, and air quality index via sensors on Floor 5. Sensor readings update every 30 seconds. HVAC setpoint changes can be **requested** through OntoSage by authorised users (Facility Manager role), subject to approval workflow. Physical actuation requires the Honeywell BMS driver integration (planned; current deployment uses simulation mode).
