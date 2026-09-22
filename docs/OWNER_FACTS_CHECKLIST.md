# Owner facts checklist

Generated 2026-09-21 by `scripts/owner_facts_report.py` from `http://127.0.0.1:7200/repositories/bldg`.

The system never invents a safety-critical fact: where one is not recorded it says so and names who to ask. Each line below is a question it currently has to decline.

**0 missing · 0 placeholder only · 4 recorded but hedged · 5 recorded**

*HEDGED* means a record exists and the system WILL answer from it, but the record's own wording calls the fact modelled, assumed or an example. For a safety-critical fact that is the difference between a surveyed position and an invented one, so it is listed as owed.

| fact | status | records | what the record must state |
|---|---|---|---|
| First-aid point / kit / first aider | **HEDGED** | FirstAidPoint: 1, (by lay term): 10 | the room or floor, who is the first aider, and how to reach them out of hours |
| Defibrillator (AED) | **HEDGED** | (by lay term): 3 | the exact position on each floor that has one, and whether it is checked |
| Fire assembly / muster point | **RECORDED** | AssemblyPoint: 1, (by lay term): 19 | the position, the fallback if it is blocked, and where wheelchair users muster |
| Refuge points for people who cannot use stairs | **RECORDED** | EvacuationProvision: 12, (by lay term): 4 | each floor's refuge point, whether its two-way communication unit works, and who owns it |
| Fire exits and escape routes | **RECORDED** | EvacuationProvision: 12, (by lay term): 19 | each exit, its floor, and which routes are step-free |
| Accessible toilets | **HEDGED** | ToiletFacility: 15, (by lay term): 34 | floor and room of each, and whether each is in service |
| Changing Places / adult changing facility | **RECORDED** | (by lay term): 6 | whether one exists and where |
| Emergency and out-of-hours contacts | **HEDGED** | Department: 20, (by lay term): 13 | a number that is answered out of hours, and who answers it |
| What to do when the only step-free route (a lift) is out of service | **RECORDED** | AccessibleRoute: 16, EvacuationProvision: 12, (by lay term): 15 | the alternative route or the assistance contact, per lift |

## To supply

- **First-aid point / kit / first aider** — hedged. an injured person needs a location, not a policy
  - the record itself says: *Cap_first_aid: Defibrillators are modelled at reception, floor 3 and floor 5.*
- **Defibrillator (AED)** — hedged. minutes matter; a wrong position is worse than none
  - the record itself says: *Cap_first_aid: Defibrillators are modelled at reception, floor 3 and floor 5.*
- **Accessible toilets** — hedged. a placeholder record must be replaced before it is relied on
  - the record itself says: *Amenity_ToiletFacility_Floor0: Toilet facility in Room 0.04 — Mechanical Plant Room (floor Floor0)*
  - the record itself says: *Amenity_ToiletFacility_Floor1: Toilet facility in Room 1.07 — Computer Laboratory (floor Floor1)*
  - the record itself says: *Amenity_ToiletFacility_Floor2: Toilet facility in Room 2.02 — Research Laboratory (floor Floor2)*
- **Emergency and out-of-hours contacts** — hedged. the number is what a person in trouble needs
  - the record itself says: *Cap_first_aid: Defibrillators are modelled at reception, floor 3 and floor 5.*

Record each as an `ontosage:Amenity` (or the register row for it) at the place the building's own text states, and only that place. A record the building has not verified must carry `ontosage:isSimulated true`, which this report counts as a placeholder.
