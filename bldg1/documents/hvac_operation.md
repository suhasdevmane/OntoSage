---
record_type: operating_regime
owner: "M and E Maintenance Supervisor"
authority: "Cardiff University Estates - Building Management System"
source_system: "Operating Regime Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Operating regime register"
    maps_to: operating_regimes
---

# Operating Regime Register - Abacws Building

_**Synthetic demonstration record** - fictional setpoints, not a live BMS export._

## What this makes answerable

> *"Which HVAC assets operate beyond approved service windows, and is each exception
> justified by safety, frost protection or specialist requirement?"*

That question cannot be answered by a reading. A reading says what **is**. This register says
what is **supposed to be**, and only the pair together turns a deviation into a fault.

**`approved_exception` is the load-bearing column.** Without it every legitimate deviation
reads as a fault - the Level 2 laboratories running 24/7, the server room with no night
setback, the chilled water system enabled outside the cooling season. That is exactly how an
alarm list becomes noise and then gets ignored.

Two rows record a limit on their own verifiability rather than hiding it: REG-004 is under
review because the unit serving it delivers 78% of its commissioned duty, and REG-006 cannot
be verified at all because no flow measurement is fitted to that AHU.

## Operating regime register

| code | system | scope | occupied_setpoint | unoccupied_setpoint | operating_window | seasonal_changeover | approved_exception | owner | status | note |
|---|---|---|---|---|---|---|---|---|---|---|
| REG-001 | AHU Floor 0 supply air | Ground floor teaching and reception | 21 degC +/- 1.5, CO2 below 1000 ppm | 16 degC frost protection only | Mon-Fri 07:00-19:00 | Heating 01 Oct to 30 Apr; cooling 01 May to 30 Sep | Runs to 22:00 on published open days | BMS-HVAC operators | Active |  |
| REG-002 | AHU Floor 1 supply air | Level 1 computer laboratories and atrium | 21 degC +/- 1.5, CO2 below 1000 ppm | 16 degC frost protection only | Mon-Fri 07:00-20:00 | Heating 01 Oct to 30 Apr; cooling 01 May to 30 Sep | Extended to 22:00 during assessment weeks, approved by the School | BMS-HVAC operators | Active | Longer window than other floors because the labs are open until 20:00 |
| REG-003 | AHU Floor 2 supply air | Level 2 research laboratories | 21 degC +/- 1.0, CO2 below 900 ppm | 18 degC continuous | Continuous, 24/7 | No seasonal shutdown - laboratory ventilation runs year round | Continuous operation is the approved regime, not an exception | BMS-HVAC operators | Active | Tighter tolerance and continuous running because laboratory work depends on stable conditions |
| REG-004 | AHU Floor 3 supply air | Level 3 seminar rooms, offices and common room | 21 degC +/- 1.5, CO2 below 1000 ppm | 16 degC frost protection only | Mon-Fri 07:00-19:00 | Heating 01 Oct to 30 Apr; cooling 01 May to 30 Sep |  | BMS-HVAC operators | Under review | AEP-004 delivers 78% of its commissioned duty, so this regime may not be achievable as written |
| REG-005 | AHU Floor 4 supply air | Level 4 offices and meeting rooms | 21 degC +/- 1.5, CO2 below 1000 ppm | 16 degC frost protection only | Mon-Fri 07:00-19:00 | Heating 01 Oct to 30 Apr; cooling 01 May to 30 Sep |  | BMS-HVAC operators | Active |  |
| REG-006 | AHU Floor 5 supply air | Level 5 seminar, conference and offices | 21 degC +/- 1.5, CO2 below 1000 ppm | 16 degC frost protection only | Mon-Fri 07:00-19:00 | Heating 01 Oct to 30 Apr; cooling 01 May to 30 Sep | Runs to 21:00 when a conference is booked in 5.15 or 5.16 | BMS-HVAC operators | Active | No flow measurement is fitted on AEP-006, so conformance to this regime cannot currently be verified |
| REG-007 | Chilled water system | All AHUs and Level 2 laboratory fan coil units | Flow 6 degC, return 12 degC | System off below 14 degC ambient | Continuous while enabled | Enabled 01 May to 30 Sep | Enabled outside the cooling season when ambient exceeds 18 degC | M and E Maintenance Supervisor | Active | Single chiller with no N+1; an out-of-season enable is a deliberate approved exception, not a fault |
| REG-008 | Parking level ventilation | Parking level | CO-linked, ramps up above 30 ppm | Trickle ventilation continuous | Continuous, 24/7 | No seasonal variation |  | M and E Maintenance Supervisor | Active | Life-safety interlock; the fan itself (AEP-017) has the longest blind interval in the building |
| REG-009 | Server room cooling | Room 2.13 comms room and Level 2 comms room | 22 degC +/- 2, humidity 40-60% | Same - no unoccupied setback | Continuous, 24/7 | No seasonal variation | No setback is permitted at any time; this is an approved permanent exception to the building night setback | Network Infrastructure Lead | Active | Environmental alarms here route to IT before Estates |
| REG-010 | Lighting control | All common areas and circulation | Presence-detected, 300 lux maintained | Off after 15 minutes vacancy | Mon-Sun 06:00-23:00 | No seasonal variation | Escape route lighting is never switched off and is excluded from this regime | Estates Operations Manager | Active |  |

**10 operating regimes. Three run continuously by design - the Level 2 laboratories, the parking level CO interlock and the server room cooling - and each is an approved permanent exception to the building night setback rather than a fault.**
