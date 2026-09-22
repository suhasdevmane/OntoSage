---
record_type: fire_safety_asset
owner: "Building Fire Warden Coordinator"
authority: "Cardiff University Fire Safety"
source_system: "Fire Safety Asset Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
tables:
  - name: "Fire safety asset register"
    maps_to: fire_safety_assets
---

# Fire Safety Asset Register - Abacws Building

## Why this register exists, and the premise behind every column

The building held a fire safety document of fifty-one lines of prose with no tables. It could
tell somebody what to do when the alarm sounds, and could not answer one question about
whether the precautions actually work.

**A fire precaution that is merely present proves nothing.** Every column here exists to
answer *when was this last proved to work, and by what evidence*. `last_tested_on` and
`evidence_ref` are deliberately separate: a test somebody remembers doing is not a test, and
the register has to be able to state that difference rather than imply it.

**A blank `open_defect` means none recorded, not none present.** That distinction matters
more in a fire register than anywhere else, so it is stated here rather than left for an
absence to be read as an assurance.

`status` is derived from the dates and the evidence, never asserted. FSA-027 is the row that
makes the point: the dry riser's annual pressure test has been overdue since May and carries
no evidence reference at all - the only suppression asset in the building with neither.

## Evacuation procedure

The procedural content of the earlier document is unchanged and still applies:

1. On hearing the fire alarm (continuous bell), **leave the building immediately** via the
   nearest fire exit.
2. **Do not use the lift** during a fire evacuation - use the stairs. The lift homes to
   ground on alarm and its doors open.
3. Assembly point: **Maindy Road car park** (north side, 50 metres from the main entrance).
4. Report to your floor warden at the assembly point.

People who cannot use stairs should go to the nearest refuge point and use the communication
unit; the refuge points and the personal evacuation plans are held in the evacuation and
PEEPs document, not here.

**Emergency contacts:** University Security (24/7) 029 2087 4444 - Emergency Services 999 -
Fire Safety Officer fire.safety@example.ac.uk

## Fire safety asset register

| code | name | kind | location | floor | standard | last_tested_on | next_test_due | evidence_ref | open_defect | owner | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FSA-001 | Fire alarm control panel | alarm | Room 0.10 - Building Management Office | 0 | BS 5839-1 weekly test | 2026-09-09 | 2026-09-16 | FA-WK-2026-34 |  | Building Fire Warden Coordinator | Overdue | Weekly test not recorded since 2026-08-26; a missed weekly test is reportable |
| FSA-002 | Fire alarm zone - Floor 0 | detection | Ground floor | 0 | BS 5839-1 L1, six-monthly service | 2026-06-16 | 2026-12-16 | FA-SVC-2026-06 |  | Building Fire Warden Coordinator | Active |  |
| FSA-003 | Fire alarm zone - Floor 1 | detection | Level 1 | 1 | BS 5839-1 L1, six-monthly service | 2026-06-16 | 2026-12-16 | FA-SVC-2026-06 |  | Building Fire Warden Coordinator | Active |  |
| FSA-004 | Fire alarm zone - Floor 2 | detection | Level 2 | 2 | BS 5839-1 L1, six-monthly service | 2026-06-16 | 2026-12-16 | FA-SVC-2026-06 |  | Building Fire Warden Coordinator | Active |  |
| FSA-005 | Fire alarm zone - Floor 3 | detection | Level 3 | 3 | BS 5839-1 L1, six-monthly service | 2026-06-16 | 2026-12-16 | FA-SVC-2026-06 | Two detectors in the Level 3 common room repeatedly report low signal | Building Fire Warden Coordinator | Defective |  |
| FSA-006 | Fire alarm zone - Floor 4 | detection | Level 4 | 4 | BS 5839-1 L1, six-monthly service | 2026-06-16 | 2026-12-16 | FA-SVC-2026-06 |  | Building Fire Warden Coordinator | Active |  |
| FSA-007 | Fire alarm zone - Floor 5 | detection | Level 5 | 5 | BS 5839-1 L1, six-monthly service | 2026-06-16 | 2026-12-16 | FA-SVC-2026-06 |  | Building Fire Warden Coordinator | Active |  |
| FSA-008 | Emergency lighting - north stairwell | escape provision | North Stairwell - Fire Escape Route | 0 | BS 5266-1 annual duration test | 2026-02-14 | 2027-02-14 | EL-DUR-2026-02 | Battery pack failed in service on 2026-08-04 despite passing the February duration test | M and E Maintenance Supervisor | Defective | The failure mode is not caught by the current test regime - see INC-2026-012 |
| FSA-009 | Emergency lighting - main lift core escape route | escape provision | Main lift core | 0 | BS 5266-1 annual duration test | 2026-02-14 | 2027-02-14 | EL-DUR-2026-02 |  | M and E Maintenance Supervisor | Active |  |
| FSA-010 | Fire exit - Ground Floor North | escape provision | Fire Exit - Ground Floor North | 0 | Monthly escape route inspection | 2026-09-14 | 2026-10-15 | ESC-2026-08 |  | Building Fire Warden Coordinator | Active |  |
| FSA-011 | Fire exit - Floor 1 North | escape provision | Fire Exit - Floor 1 North | 1 | Monthly escape route inspection | 2026-09-14 | 2026-10-15 | ESC-2026-08 |  | Building Fire Warden Coordinator | Active |  |
| FSA-012 | Fire exit - Floor 2 North | escape provision | Fire Exit - Floor 2 North | 2 | Monthly escape route inspection | 2026-09-14 | 2026-10-15 | ESC-2026-08 |  | Building Fire Warden Coordinator | Active |  |
| FSA-013 | Fire exit - Floor 3 North | escape provision | Fire Exit - Floor 3 North | 3 | Monthly escape route inspection | 2026-09-14 | 2026-10-15 | ESC-2026-08 |  | Building Fire Warden Coordinator | Active |  |
| FSA-014 | Fire exit - Floor 4 North | escape provision | Fire Exit - Floor 4 North | 4 | Monthly escape route inspection | 2026-09-14 | 2026-10-15 | ESC-2026-08 |  | Building Fire Warden Coordinator | Active |  |
| FSA-015 | Fire exit - Floor 5 North | escape provision | Fire Exit - Floor 5 North | 5 | Monthly escape route inspection | 2026-09-14 | 2026-10-15 | ESC-2026-08 |  | Building Fire Warden Coordinator | Active |  |
| FSA-016 | Fire doorset - Level 3 riser cupboard | fire door | Level 3 riser cupboard | 3 | BS 8214 six-monthly doorset inspection | 2026-04-02 | 2026-10-02 | FD-2026-04 |  | Building Fire Warden Coordinator | Active | Closer adjusted after INC-2026-003, when this door was found wedged open |
| FSA-017 | Fire doorset - Level 1 computer laboratory suite | fire door | Room 1.06 - Computer Laboratory | 1 | BS 8214 six-monthly doorset inspection | 2026-04-02 | 2026-10-02 | FD-2026-04 |  | Building Fire Warden Coordinator | Active |  |
| FSA-018 | Fire doorset - Level 2 laboratory corridor | fire door | Room 2.03 - Research Laboratory | 2 | BS 8214 six-monthly doorset inspection | 2026-04-02 | 2026-10-02 | FD-2026-04 | Intumescent strip damaged on the leading edge | Building Fire Warden Coordinator | Defective |  |
| FSA-019 | Fire doorset - plant room, Room 0.04 | fire door | Room 0.04 - Mechanical Plant Room | 0 | BS 8214 six-monthly doorset inspection | 2026-04-02 | 2026-10-02 | FD-2026-04 |  | M and E Maintenance Supervisor | Active |  |
| FSA-020 | Compartment penetration seals - Level 1 riser | compartmentation | Level 1 riser cupboard | 1 | Annual penetration survey | 2025-10-08 | 2026-10-08 | PEN-2025-10 |  | Building Fire Warden Coordinator | Active |  |
| FSA-021 | Compartment penetration seals - Level 2 riser | compartmentation | Level 2 riser cupboard | 2 | Annual penetration survey | 2025-10-08 | 2026-10-08 | PEN-2025-10 | Unsealed data cable penetration recorded and not yet closed out | Building Fire Warden Coordinator | Defective | The only compartmentation defect open against a riser that also carries an LV sub-main |
| FSA-022 | Compartment penetration seals - Level 3 riser | compartmentation | Level 3 riser cupboard | 3 | Annual penetration survey | 2025-10-08 | 2026-10-08 | PEN-2025-10 |  | Building Fire Warden Coordinator | Active |  |
| FSA-023 | Portable extinguishers - Level 0 | extinguisher | Ground floor | 0 | BS 5306-3 annual service | 2026-01-22 | 2027-01-22 | EXT-2026-01 |  | Estates Operations Manager | Active |  |
| FSA-024 | Portable extinguishers - Levels 1 and 2 | extinguisher | Levels 1 and 2 | 1 | BS 5306-3 annual service | 2026-01-22 | 2027-01-22 | EXT-2026-01 |  | Estates Operations Manager | Active |  |
| FSA-025 | Portable extinguishers - Levels 3 to 5 | extinguisher | Levels 3 to 5 | 3 | BS 5306-3 annual service | 2026-01-22 | 2027-01-22 | EXT-2026-01 |  | Estates Operations Manager | Active |  |
| FSA-026 | CO2 extinguishers - plant and comms rooms | extinguisher | Room 0.04 - Mechanical Plant Room | 0 | BS 5306-3 annual service and 10-year test | 2026-01-22 | 2027-01-22 | EXT-2026-01 |  | M and E Maintenance Supervisor | Active |  |
| FSA-027 | Dry riser - main lift core | suppression | Main lift core | 0 | BS 9990 six-monthly visual, annual pressure test | 2025-11-05 | 2026-05-05 |  | Annual pressure test OVERDUE since 2026-05-05 and no evidence reference recorded | Estates Operations Manager | Overdue | The only suppression asset in the building with neither a current test nor evidence |
| FSA-028 | Sprinkler protection - Room 0.06 loading area | suppression | Room 0.06 - Loading and Goods Storage | 0 | BS EN 12845 quarterly inspection | 2026-07-03 | 2026-10-03 | SPR-2026-07 |  | Estates Operations Manager | Active |  |
| FSA-029 | Fire assembly point A signage | signage | Fire Assembly Point A - Senghennydd Road (North side) | 0 | Annual signage and legibility check | 2026-03-11 | 2027-03-11 | SGN-2026-03 |  | Building Fire Warden Coordinator | Active |  |
| FSA-030 | Fire assembly point B signage | signage | Fire Assembly Point B - Car Park (South side) | 0 | Annual signage and legibility check | 2026-03-11 | 2027-03-11 | SGN-2026-03 |  | Building Fire Warden Coordinator | Active |  |

**30 fire safety assets. 2 overdue, 5 carrying an open defect and 1 with no evidence reference at all. The dry riser (FSA-027) is both: overdue since 2026-05-05 and unevidenced, which makes it the single asset here that cannot be shown to work.**
