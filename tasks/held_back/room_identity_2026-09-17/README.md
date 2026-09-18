# Held back until after the 2026-09-18 demo: room identity from the architect's drawings

**Owner decisions (2026-09-17):** the architect's DXF drawings are authoritative for what a
room is; Room 0.01 is a 120-person lecture theatre. **Sequencing decision (same day): hold the
whole correction and apply it after the demo as ONE coherent change**, because loading identity
without its cascade creates contradictions a reader can see (e.g. 23 teaching sessions in what
the drawing shows is a one-person office).

## What is staged here

| File | What it corrects (vs the restored `input/` version) |
|---|---|
| `input/bldg1_abacws_metadata.ttl.corrected` | 132 of 225 room blocks: rdfs:label + Brick type to the drawing (IRIs unchanged). Lecture theatres = brick:Auditorium + explicit brick:Room (CAVEAT-301). Brick 1.4 has no Lecture_Hall/Classroom. |
| `input/bldg1_enrichment_metadata.ttl.corrected` | 19 hbco:roomCapacity values with ontosage:capacityBasis; 19 hbco:spaceFunction values. |
| `input/bldg1_enhancements.ttl.corrected` | 28 of 29 bldg:maxOccupancy to the drawing; Room2.15 (DB room) removed. |
| `tests/test_room_identity_matches_drawing.py` | 34 tests pinning identity against the drawing. |
| `tests/test_declared_capacities_are_physical.py` | density + agreement between capacity properties. |
| `../bldg1_room_capacity.ttl.held` | 187 derived capacities from drawing labels; 0 contradictions with the drawing. |

Evidence and per-room appendices: `docs/phase0/room_identity_cascade.md`. Drawing data:
`tests/fixtures/floor_plans/bldg1_drawing_rooms.json` (left in place; the provisioner tests use it).
Tracker: BUG-671, BUG-688, BUG-689, CAVEAT-690.

## The cascade that must land in the SAME change

- 646 of 675 timetabled sessions sit in 42 changed rooms (507 in offices). 11 moves clash-checked;
  the 471 "laboratory sessions" must be regenerated from corrected types (the drawing has 2 labs).
- Events store: 657 rows in 18 unoccupied rooms (17 future bookings); 5,112 bookings exceed the
  drawing capacity (104 future) — regenerate bookable rooms only, attendees capped at capacity.
- 866 register rows across 22 record documents name changed rooms.
- 1,132 room-sensor labels embed old room labels.
- Waste bins provisioned 2026-09-17 in 0.01/1.04/2.66/3.18/4.70/5.26 — relocate.
- Toilets located in PhD offices/seminar rooms; entrance access reader and entry counter hang off
  Room0.01; telecom/server entities parented to lecture theatres and offices.
- 10 manifest spaces contradict the drawing (7 floor-0 IRIs taken from the floor-4 inset).
- 16 lines of `scripts/regression_cases.json` move — one change at a time, probe green before/after.
- Demo-script room questions: move to Room 1.39 (42-seat computer room) with 1.06's sessions + AV.

## Owner questions still open

1. Where are the reception and main entrance? Is 0.19 (Student Services) the reception desk?
2. Where is the plant room? Registers put AHUs, BMS, an asbestos remnant and the fire alarm panel
   in 0.04 / 0.05 / 0.10 (drawing: seminar room, records store, gas meter room).
3. Should the atrium be modelled as a space? Seven registers put events, bins, patrols and cleaning
   there, and 1.04 is a seminar room on the drawing.
4. 2.26: really a 120-seat theatre inside a 27 m² outline?

## To apply after the demo

Answer the four questions, then copy each `.corrected` file over its `input/` twin, move the two
test files back into `tests/`, place `bldg1_room_capacity.ttl.held` as `input/bldg1_room_capacity.ttl`,
land the cascade above, re-upload, check no old triples linger in the default graph (BUG-194), and
run the unit suite, the probe (flushed) and the stakeholder bank.
