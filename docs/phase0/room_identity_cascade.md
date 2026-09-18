# Room identity cascade: bldg1, 2026-09-17

**Status: inventory only. Only the room-identity triples have moved; nothing else in this file has.**
The building owner ruled that the architect's drawings are authoritative for room identity (the
lead passed this on 2026-09-17). The identity triples are corrected in the TTL source files
(section 1). Everything that *refers* to those rooms is listed below with a proposed correction,
and none of it has changed yet. Nothing has been uploaded, restarted or written to a database.

How it was measured, all offline or read-only:
- **The drawings:** the committed DXFs, extracted to `tests/fixtures/floor_plans/bldg1_drawing_rooms.json`.
  That file lists 225 room outlines, each holding exactly one room number and its text.
- **The building's TTL files:** read with rdflib.
- **The live graph:** read-only SPARQL against `bldg`.
- **The events store:** read-only SQL in a `READ ONLY` transaction, session pinned to `+00:00`.
  The store clock read 2026-09-17 14:28 UTC.
- **The register documents:** `input/documents/*.md`.
- **The floor-plan manifests:** `volumes/bldg1/floor-plans`.
- **The question banks.**

---

## 1. What changed (already applied to the TTL sources)

| file | triples | change |
|---|---|---|
| `input/bldg1_abacws_metadata.ttl` | 132 `rdf:type` and 132 `rdfs:label` replaced; 4 `brick:Room` added | 132 of 225 room blocks contradicted the drawing |
| `input/bldg1_enrichment_metadata.ttl` | 19 `hbco:spaceFunction` replaced | e.g. 1.06 "Teaching room" became "Office"; 0.01 "Atrium / reception area" became "Lecture theatre" |
| `input/bldg1_enhancements.ttl` | 29 `bldg:maxOccupancy` rewritten, Room2.15's removed | same drawing rule as `hbco:roomCapacity` |
| `input/bldg1_enrichment_metadata.ttl` | 19 `hbco:roomCapacity` + `ontosage:capacityBasis` | BUG-671 |

Other files that assert room identity were checked and needed no change:
- `bldg1_expanded_protege_clean.ttl` asserts only `owl:NamedIndividual`.
- `bldg1_zone_room_links.ttl` asserts only a provenance comment.
- `bldg1_enhancements.ttl` asserts only `brick:Room` on 1.04.

Room IRIs are unchanged.

**The changes, by kind of room:**

| kind | rooms |
|---|---:|
| offices | 96 |
| plant rooms | 12 |
| teaching | 9 |
| lecture theatres | 4 |
| stores | 4 |
| meeting rooms | 3 |
| workshops | 2 |
| break-out | 1 |
| laboratory | 1 |

**Offices the graph had typed as something else:**

| old type | rooms |
|---|---:|
| Laboratory ("Computer/Research Laboratory") | 64 |
| Conference_Room | 14 |
| Restroom | 5 |
| Break_Room / Office_Kitchen | 5 |
| Telecom_Room | 3 |
| Mechanical_Room | 2 |
| Storage_Room | 2 |
| Server_Room | 1 |

**Brick 1.4 has no lecture-hall or classroom class** (checked against `Brick_v1.4.ttl`), so:
- Lecture theatres are `brick:Auditorium` plus `brick:Room`. Auditorium is a Common_Space, not a Room, and the explicit Room keeps coverage from losing them (CAVEAT-301).
- Seminar and teaching rooms are `brick:Conference_Room`.
- Computer rooms are `brick:Laboratory`.
- A class such as `ontosage:Teaching_Room` would be more exact. That file belongs to VOCAB and is not changed here.

**Left as they were, because the drawing does not settle them:**
- 1.38 "IT Hub"
- 2.14 / 3.65 / 5.45 "Project Rm"
- 3.27 "Magic Room"
- 4.07 "Cyber Security"

**Not yet live.** The running graph still holds the old triples. The default graph can shadow a
named graph (BUG-194), so after re-upload, check that no `Laboratory` type or "Computer
Laboratory" label survives on Room1.06 in any graph.

Tests: `tests/test_room_identity_matches_drawing.py`. On the pre-change files, three rule tests
fail with 82, 128 and 148 findings; on the corrected files all 34 pass.

---

## 2. Where the reception really is

**The drawing shows no room named reception.** On the Abacws floor-0 DXF (GIA 1,622.88 m²),
outline 0.01 contains only "120 Person Lecture Theatre". No text anywhere on floor 0 says
reception, and the main entrance is not a numbered outline.

The nearest front-of-house function the drawing records is **Room 0.19**: "3 Person Prof Serv &
Post", with the ROOM ASSIGNMENT layer text "STUDENT SERVICES" inside the same outline. 0.18
("9 Person Prof Serv") and 0.20 ("2 Person Prof Serv") sit next to it. The circulation and
collaboration zones ("41P Collab S" 0Z21, "Collab Sp Soft Seat" 0Z23, "Vending" 0Z19) have no
room IRI.

The "0.01 Meeting Room / Reception / 0.13 College Room / 0.18 Boardroom" text that looked like
evidence is in the **floor-4** PDF and DXF. It is an inset of a different ground floor: it does
not match the floor-0 drawing, where 0.18 is Prof Serv and 0.10 is Gas Meter & Tank.

**Proposal:**
- Model "Main Entrance / Reception" as its own space, not as Room0.01.
- Ask the owner whether 0.19 (Student Services) is the reception desk.

Until that is answered, anything described below as "reception" has no correct room to move to.

---

## 3. Cascade inventory

### 3.1 Timetabled sessions: `input/documents/timetabled_sessions.md` and `input/bldg1_timetable.csv`

**646 of the 675 sessions (96%) sit in 42 rooms whose identity changed. All 646 rows still carry the old label.**

The timetable is synthetic: the provisioner chose "teaching rooms" by Brick class, so wrong types
put the classes in offices (commit 8f04d3a). By what the drawing now says the host room is:

| drawing says | sessions |
|---|---:|
| Office | 507 |
| DB Room (2.15, 7.83 m²) | 24 |
| ICT LAN (3.57) | 14 |
| PhD research offices | 41 |
| research office | 21 |
| 90P Lecture (5.05) | 23 |
| 16-20P Meeting (3.01) | 16 |

By session kind:

| kind | sessions |
|---|---:|
| laboratory session | 471 |
| seminar | 66 |
| computer lab session | 60 |
| small-group session | 49 |

**Proposed moves.** Each is a drawn room of the right kind and capacity, on the same floor where
one exists. Every move was clash-checked against the CSV, and none produces an overlapping
session.

| sessions now in | kind | n | move to | drawing | capacity |
|---|---|---:|---|---|---:|
| **Room 1.06** (Office) | computer lab | 23 | **Room 1.39** | 42P Computer Room, floor 1 | 42 |
| Room 1.07 (Office) | computer lab | 15 | Room 1.34 | 60P Computer Room, floor 1 | 60 |
| Room 4.05 (Office) | computer lab | 6 | Room 1.34 | (no computer room on floor 4) | 60 |
| Room 2.08, 3.05 (Offices) | computer lab | 16 | Room 2.35 | 48P Computer Room, floor 2 | 48 |
| Room 1.26 (6P Research Office) | seminar | 21 | Room 1.04 | 30P Seminar Room, floor 1 | 30 |
| Room 2.15 (DB Room) | seminar | 24 | Room 3.38 | 48P Seminar Room (no seminar room on floor 2) | 48 |
| Room 4.13 (Office) | seminar | 13 | Room 4.35 | 20 P Seminar, floor 4 | 20 |
| Room 5.16 (Office) | seminar | 8 | Room 5.44 | 60P Teaching, floor 5 | 60 |
| Room 3.16 (Office) | small-group | 21 | Room 3.15 | 8-12 Exec Meeting, floor 3 | 12 |
| Room 3.26 (6P PHD Research) | small-group | 8 | Room 3.01 | 16-20P Meeting, floor 3 | 20 |
| Room 5.17 (Office) | small-group | 20 | Room 1.40 | 8-12P Meet Rm (no meeting room on floor 5) | 12 |

**The 471 "laboratory sessions" in 30 rooms cannot be hand-moved.** Of those rooms, 28 are
offices, PhD offices or an ICT LAN room on the drawing; the other two are 5.05 and 3.01. The drawing holds only two
laboratories (2.53 "Research Lab", 4.38 "Financial Lab") plus two workshops (4.47, 4.71). Moving
them there would stack about 470 sessions into four rooms.

**Proposal:** regenerate the timetable with `scripts/provision_synthetic_sources.py` after the
corrected types are loaded. It already picks rooms by Brick class, so the corrected graph gives
it the drawn teaching rooms. The same run fixes:
- 5.05, which is now a lecture theatre holding "laboratory sessions";
- 3.01, now a meeting room.

The regression case "Which teaching sessions are scheduled in Room 1.06?" (expects `23`) must
follow whichever room the 23 sessions go to.

### 3.2 Events store (`sensordb.events`, read-only)

8,923 rows name a drawn room as their subject: 8,500 `booking`, 423 `workorder`. The generator
booked every room, whatever it is.

- **Rows in the 18 rooms the drawing shows unoccupied** (DB rooms, ICT LAN, stores, UPS, switch
  room, gas meter room, refuse store, Server Rm): 640 past bookings, 17 future bookings, 23 work
  orders.
  - **Proposal:** delete the future bookings; keep the work orders, since plant rooms do get work
    orders; regenerate past bookings so none falls in such a room.
- **Bookings whose attendee count exceeds the drawing capacity:** 5,008 past and 104 future,
  across 172 rooms. The worst are cellular offices with 36-41 over-capacity bookings each (2.56,
  2.11, 2.12, 3.53, 4.21, 2.21, 5.08, 2.05).
  - **Proposal:** regenerate bookings restricted to the drawn bookable kinds (Conference_Room,
    Auditorium, computer-room Laboratory), with attendees capped at `hbco:roomCapacity`.
- **`asset_outage` rows whose attributes name 0.01 (2), 0.04 (2) and 0.07 (1).** They describe
  reception, plant-room and service-room assets.
  - **Proposal:** re-point them with the asset moves in 3.4.

Every one of the 132 changed rooms carries bookings, 17 to 65 each: Room1.06 has 61 bookings (2
in the future) and 2 work orders. The per-room table is Appendix A.

### 3.3 Register documents (`input/documents/*.md`)

**866 rows in 22 registers name a changed room.**

| register | rows | rooms | rows still carrying the old label | proposed correction |
|---|---:|---:|---:|---|
| timetabled_sessions | 646 | 42 | 646 | section 3.1 |
| workspace_profile_register | 25 | 25 | 0 (uses "Room X - label") | see below |
| accessible_route_register | 24 | 10 | 20 | routes "to Reception" end at Main Entrance (section 2); "to Level 1 Computer Laboratory" goes to Room 1.39; "to Level 2/3/4 laboratories" go to 2.53 / (none) / 4.38 |
| event_activity_register | 23 | 6 | 22 | open-day and outreach activities in 1.06 go to Room 1.39 (42) or the 96-person lecture theatre 0.34 for talks; the "Laboratory demonstration" in 2.01/2.02 (stated capacity 30) goes to 2.53 Research Lab |
| av_readiness_register | 22 | 7 | 21 | see below |
| asset_engineering_register | 17 | 8 | 0 | see 3.4 (plant rooms) |
| cleaning_task_register | 17 | 15 | 14 | relabel; "Presentation" standard for 0.01 now means a lecture theatre; "Enhanced" lab cleaning in offices 2.03/3.06/5.01 drops to "Standard" |
| room_bookings | 16 | 6 | 16 | 5.15 / 5.16 / 5.01 / 5.04 (12-24 attendees, all offices now) go to 5.44 (60); 5.17 (30 attendees, office) goes to 5.44; 5.18 (6 attendees, PhD office) goes to 1.40 or 3.15 |
| public_event_register | 14 | 6 | 12 | "Open day" and "Schools outreach" in 1.06 go to 1.39 / 0.34; 1.04 events above 30 people ("Careers fair", "Alumni evening reception") need a larger venue, and the atrium they were written for is not a numbered room on the drawing |
| waste_collection_register | 11 | 4 | 11 | reception bins have no room until section 2 is answered; atrium bins in 1.04 have no drawn atrium; sharps bins in 2.01 / 3.01 go to 2.53 Research Lab |
| incident_and_near_miss_log | 9 | 9 | 0 | history: keep what was recorded, relabel the room |
| coshh_and_lev | 8 | 7 | 0 | fume cupboards in offices 2.05 / 2.06 / 3.01 go to 2.53 Research Lab; solvent store in 2.05 goes to a store; asbestos flue remnant "in 0.04" now sits in a seminar room, **so the owner must confirm where the plant room is** |
| approval_evidence_register | 5 | 4 | 0 | "Room 1.06 Computer Laboratory — teaching use" goes to 1.39; COSHH approvals for 2.01 / 3.06 go to 2.53 |
| continuity_provision_register | 5 | 5 | 5 | BMS depends on "0.04 Mechanical Plant Room" (now a seminar room); fire alarm panel in 0.08 (Switch Room); "Teaching AV in Level 1 laboratories" (1.06 / 1.07) goes to 1.39 / 1.34 |
| fire_safety | 5 | 4 | 0 | fire alarm control panel "in 0.10" is now in a gas meter room; the fire door on 1.06 is described as a computer laboratory suite |
| patrol_checkpoint_register | 5 | 5 | 3 | "Main reception desk" (section 2); "Level 1 atrium" (1.04 is a seminar room); "Mechanical plant room" (0.04); "Comms room" (0.07 is UPS & Battery) |
| access_permission_register | 4 | 4 | 2 | "Mechanical plant room" on 0.04; "Server and comms room" on 0.07; lab permissions on offices 2.01 / 3.06 |
| door_hardware_register | 3 | 3 | 3 | reception turnstile on 0.01; plant-room door on 0.04; "Level 5 conference suite door" on office 5.15 |
| hvac_operation | 3 | 3 | 0 | "Server room cooling" scoped to office 2.13; "Level 5 seminar, conference" scope on offices 5.15 / 5.16 |
| maintenance_log | 2 | 1 | 0 | fan coil unit in office 5.03: consistent, relabel only |
| coordination_function_register | 1 | 1 | 0 | lab spill response in office 3.06 goes to 2.53 |
| service_schedules | 1 | 1 | 0 | "Atrium glazing" on 1.04: no drawn atrium |

**AV readiness (the "ready for my class" questions).** Records sit in 1.06 (6 components,
including the hearing loop "Unevidenced"), 1.04 (4), 2.01 (3), 2.02 (2), 3.01 (4), 4.01 (2) and
5.04 (1). Of those, only 1.04 and 3.01 are teaching or meeting rooms on the drawing.

Proposal:
- Move the six-component 1.06 set to **Room 1.39** (the same "computer lab" rig, the same floor,
  42 seats), keeping the unevidenced hearing loop so the demo still shows a named blocker.
- 1.04 keeps its set. Relabel it from "Atrium" to "Seminar Room".
- 2.01 / 2.02 go to 2.35 (computer room, floor 2).
- 4.01 goes to 4.35.
- 5.04 goes to 5.44.
- 3.01 keeps its set.

**Workspace profiles.**

| profile | now | proposal |
|---|---|---|
| WS-02..05 "Level 1 computer lab" | offices 1.06-1.09 (24-30 seats) | 1.39 (42) and 1.34 (60) |
| WS-08/09 | 2.07 / 2.08 | 2.35 |
| WS-13/14 | 3.05 / 3.06 | no computer room on floor 3: drop or point to 2.35 |
| WS-06/07 "Seminar room" | 1.25 / 1.26 | 1.04 |
| WS-12 | 2.15 (DB room) | drop |
| WS-15/16 | 3.13 / 3.14 | 3.38 / 3.02 |
| WS-24 | 4.13 | 4.35 |
| WS-25/26 | 5.15 / 5.16 | 5.44 |
| WS-10/18/20/22/23/27/28 "Meeting room" | 2.13 / 3.16 / 3.26 / 4.11 / 4.12 / 5.17 / 5.18 | only 1.40 / 3.15 / 3.01 / 0.17 are drawn meeting rooms; floors 2, 4 and 5 have none |
| WS-19 "Staff common room" | 3.17 | 3.36 "Staff Room" |

This changes the answers to "Which bookable rooms are suitable for a confidential call?" (expects
5.17 / 5.18) and "Where can I work for three hours…" (expects 1.25 / 1.06 / "computer lab").

### 3.4 Graph instances in the building TTLs that point at a changed room

| file | referring subjects | rooms | subjects whose own label names the old function |
|---|---:|---:|---:|
| `bldg1_saturation_*.ttl` (11 modality files) | 1,132 sensors | 132 | **1,030** name a non-office function, e.g. "Room 0.01 — Main Reception illuminance [lux]"; all 1,132 embed the old label |
| `bldg1_configuration_history.ttl` | 779 ConfigurationPeriod | 131 | 0 (no labels; the location link stays valid) |
| `bldg1_floors_0_4_sensors.ttl` | 312 sensors | 104 | 0 |
| `bldg1_door_access_events.ttl` (not loaded) | 148 AccessEvent | 1 (Room0.01) | door events at the "reception" turnstile: re-point to the Main Entrance space |
| `bldg1_waste_points.ttl` | 24 fill/weight points | 6 | 24 |
| `bldg1_amenity_locations.ttl` | 24 amenities | 24 | 23 |
| `bldg1_enhancements.ttl` | 44 | 19 | 40 |
| `bldg1_zone_room_links.ttl` | 12 HVAC zones | 12 | 0 |
| `bldg1_synthetic_status.ttl` | 7 AV rigs | 7 | 5 |
| `bldg1_abacws_metadata.ttl` (non-room subjects: 6 telecom rooms, 2 server rooms, 3 AEDs, 1 camera) | 12 | 12 | re-parent, see below |
| `bldg1_alarm_events.ttl` (not loaded) | 1 AlarmEvent | 1 | 1 ("Leak Detector - Ground Floor Plant Room" on 0.04) |

**Saturation sensor labels.** They embed the old room label: 1,030 labels across 11 files.
Proposal: regenerate from the new `rdfs:label`, the same generator with no identity change. The
point IRIs (`Room1.06_sat_co2`) are unaffected.

**The waste bins provisioned today** (`bldg1_waste_points.ttl`, 12 bins x fill + weight).
`provision_damper_and_waste_points.py` put one pair per floor in "that floor's own kitchen / break
room / common area", as the graph typed them:

| now in | old identity | drawing says |
|---|---|---|
| Room0.01 | Main Reception | 120 Person Lecture Theatre |
| Room1.04 | Common Area / Atrium | 30P Seminar Room |
| Room2.66 | Staff Break Room / Kitchen | Office |
| Room3.18 | Kitchen | Office |
| Room4.70 | Staff Break Room | 6P Prof Serv- IT |
| Room5.26 | Staff Break Room / Kitchen | Small Research |

The drawing holds **one** break-out room in the whole building: **3.36 "Staff Room"** (84.77 m²).
It has no drawn kitchen and no drawn atrium, and 0.29 is a "Refuse Store".

Proposal:
- The floor-3 pair goes to 3.36.
- The floor-0 pair goes to 0.29 Refuse Store, or to the Main Entrance space once it exists (section 2).
- Floors 1, 2, 4 and 5: locate the pairs at floor level (`brick:hasLocation bldg:FloorN`) rather
  than in a room the drawing says is an office or a seminar room.

The same applies to the older bins in `bldg1_enhancements.ttl`: WasteBin_*_F0_Reception, _F2_Kitchen (2.66), _F3_Common (3.17), _F3_Kitchen (3.18), _F5_Break (5.26).

**Amenities** (`bldg1_amenity_locations.ttl`).
- 12 drinking-water points and 6 study areas sit in rooms such as 1.06 "Computer Laboratory".
- 6 **toilet facilities** are located in 0.04 (seminar room), 1.07 (office), 2.02 (research office), 3.02 (64-person seminar room), 4.02 (PhD office) and 5.02 (PhD office).
- The drawing numbers no toilets; the WCs are unnumbered core spaces.

Proposal: locate all 24 at floor level with a `locationText` naming the core ("Level 1 WCs, next
to the lifts") until the core spaces are modelled. Do not leave a toilet answer pointing into a
PhD office.

**`bldg1_enhancements.ttl` (other subjects).**
- Occupancy-count and booking-status sensors labelled "Seminar Room 1.25 / 1.26 / 2.15 / 4.13 / 5.15 / 5.16", "Meeting Room 3.13 / 3.26" and "Lab 3.01 / 4.01 / 5.01". Relabel, or move with the bookable rooms in 3.3.
- CCT luminaires and commands in "Lab 3.01 / 5.01": relabel.
- Door sensors "Server Room Floor 2 (Room 2.44)" and "Floor 5 (Room 5.44)": 2.44 is a PhD office and 5.44 a 60-person teaching room. There is no drawn server room on floors 2 or 5; 4.44 is the only Server Rm.
- Leak detector "Ground Floor Plant Room" on 0.04: needs the owner (section 5).
- **Main-entrance access reader, entry counter and door sensor are `isPartOf Room0.01`.** Re-point them to the Main Entrance space.

**`bldg1_abacws_metadata.ttl` (non-room subjects).**
- Telecom_Room_F0..F5 are `isPartOf` 0.34 / 1.34 / 2.34 / 3.38 / 4.34 / 5.34, which are lecture theatres, computer rooms, PhD offices and a seminar room.
  - Proposal: floors 2-5 go to the drawn ICT LAN rooms 2.24 / 3.57 / 4.24 / 5.57; floors 0 and 1 have no drawn LAN room.
- Server_Room_F2 / F5 are in 2.44 / 5.44; only F4 (4.44) matches the drawing.
- AED_Reception (0.01), AED_Floor3 (3.17, an office) and AED_Floor5 (5.26, a small research office) need a real location from Estates.

**AV rigs** (`bldg1_synthetic_status.ttl`).
- av_Room0.05 (Records Store), av_Room0.07 (UPS & Battery), av_Room0.08 (Switch Room) and av_Room0.10 (Gas Meter & Tank): **remove**.
- av_Room0.01 (lecture theatre) and av_Room0.04 (seminar room) now fit: relabel.
- av_Room0.17 (Meeting Room) fits: relabel.

### 3.5 Floor-plan manifests (`volumes/bldg1/floor-plans`, not in git)

139 manifest spaces link to changed rooms. Their DWG-derived types mostly agree with the drawing already. **10 contradict it:**
- **7 in `floor_4.manifest.json`** carry floor-0 IRIs (Room0.01 / 0.04 / 0.05 / 0.07 / 0.08 / 0.10 / 0.17) with no area. They are typed from the floor-4 inset of another building: 0.07 and 0.08 as toilets, 0.01 as a meeting room, 0.17 as storage.
  - Proposal: remove those links. The spaces are not on floor 4 and not in Abacws.
- **Room2.44** is typed `lab`; the drawing says 5P PHD Research.
- **Room4.47** is typed `lab`; the drawing says I.T Workshop.
- **Room4.36** is typed `meeting_room`; the drawing says 5P Research. Its alias "4P Tut Niche 4Z24 5P Research 4.36 20 P Seminar 4.35" smears a neighbour's "20 P Seminar" onto it.

### 3.6 Question sources

| file | lines naming a changed room or its old function | proposal |
|---|---|---|
| `docs/demo_script_questions.txt` | L13 "Is Room 1.06 ready for my class?", L14 "Is Room1.06 free for the next two hours?", L7/L34/L36 room 5.01, L51 room 2.01, L75 "radiation level in the atrium" | **Use Room 1.39 for L13 and L14.** It is the drawing's 42-person computer room on the same floor, and it receives 1.06's 23 sessions and AV set under 3.1 / 3.3. Its 35 bookings (1 in the future) keep "free for the next two hours?" answerable. L7/L34/L36/L51 are sensor questions, so the room change does not break them, but 5.01 and 2.01 are now PhD offices and the answer text will say so. L75: 1.04 is no longer an atrium, so the referent gate may now answer "no such space" rather than "not measured"; the owner should say whether the atrium is a space to model. |
| `scripts/regression_cases.json` | L45-46 (1.25, 1.06, "computer lab"), L61-62 and L385-386 (5.17, 5.18), L204 (sessions in 1.06, expects 23), L215/L422/L535/L550 (5.01), L341 ("Level 1 computer laboratories", expects 26), L397 (1.06 ready, expects "hearing loop"), L409 (3.13 ready), L469 ("seminar room from reception"), L666-667 (3.01 / 3.05 on "Show me floor 3"), L679 (atrium) | Change these together with the data moves, **one rule at a time with the probe green before and after**. The 1.06 cases follow the room chosen in 3.1 (1.39). The 5.17 / 5.18 workspace markers follow the workspace decision in 3.3. L469 waits on section 2. |
| `docs/demo_question_bank.jsonl` (67 lines) | none | nothing to do |
| `docs/phase0/phase0_bank.jsonl` (147 lines) | none by room number or old function | nothing to do |
| `docs/phase0/guard_set.jsonl` (VOCAB) | names 1.06 | tell VOCAB |

---

## 4. Order, if the owner approves

1. Load the corrected identity TTLs. Verify no old label or type survives in any graph (BUG-194).
2. Regenerate the derived and synthetic data from the corrected graph, not by hand:
   - saturation labels;
   - the timetable (`provision_synthetic_sources.py`);
   - bookings in the events store (the same generator, restricted to bookable kinds and capped at capacity);
   - the capacity file `tasks/held_back/bldg1_room_capacity.ttl.held`, whose regeneration is already done offline.
3. Apply the hand decisions: AV set 1.06 → 1.39; workspace profiles; room_bookings; public events; bins; amenities; telecom / server / AED re-parenting; manifest links.
4. Flush `resp_cache:*`, run the probe, then move the regression markers one group at a time.

## 5. Decisions only the owner can make

1. Where the reception and the main entrance are (section 2). Is 0.19 "Student Services" the reception desk?
2. Where the mechanical plant room is. `asset_engineering`, `coshh_and_lev`, `continuity_provision`, `patrol_checkpoint`, `door_hardware` and `fire_safety` all place AHUs, pumps, the BMS head end, an asbestos remnant and the fire alarm panel in 0.04 / 0.05 / 0.10. The drawing names those rooms a 30-person seminar room, a records store and a gas meter room. The only "Plant Room" text is in the floor-4 inset of another building.
3. Whether the atrium is a space to model. 1.04 is a seminar room, and seven registers held events, bins, patrols and cleaning in "the atrium".
4. The six ambiguous rooms (Appendix B), in particular 4.07 "Cyber Security": laboratory or teaching room?
5. Whether 2.26 "120S Lecture Theatre - Group Bench seating style 30SD Cap." is really a 120-seat theatre. Its drawn outline is 27.44 m², so the outline is incomplete. Capacity is withheld for now.

## Appendix A — the 132 rooms whose identity changed

Drawing text is verbatim from the room's own outline. Old values are what `bldg1_abacws_metadata.ttl` asserted before 2026-09-17; sessions are rows in `input/bldg1_timetable.csv`; bookings are `booking` rows in the events store whose subject is the room (all dates).

| room | drawing says | old type | old label | new type | new label | sessions | bookings |
|---|---|---|---|---|---|---:|---:|
| Room0.01 | 120 Person Lecture Theatre | Reception | Main Reception | Auditorium, Room | Lecture Theatre (120 people) | 0 | 37 |
| Room0.04 | 30 P Seminar | Mechanical_Room | Mechanical Plant Room | Conference_Room | Seminar Room (30 people) | 0 | 36 |
| Room0.05 | Records Storage | Mechanical_Room | Mechanical Plant Room | Storage_Room | Records Store | 0 | 40 |
| Room0.07 | Main UPS & Batt | Mechanical_Room | Service Room | Electrical_Room | UPS and Battery Room | 0 | 40 |
| Room0.08 | Switch Room | Mechanical_Room | Service Room | Electrical_Room | Switch Room | 0 | 36 |
| Room0.10 | Gas Meter & Tank | Office | Building Management Office | Service_Room | Gas Meter and Tank Room | 0 | 33 |
| Room0.17 | Meeting Room | Office | Office | Conference_Room | Meeting Room | 0 | 31 |
| Room0.29 | Refuse Store | Storage_Room | Storage Room | Waste_Storage | Refuse Store | 0 | 37 |
| Room0.31 | Records Storage | Mechanical_Room | Mechanical/Service Room | Storage_Room | Records Store | 0 | 40 |
| Room0.32 | 4 P Prof Serv | Mechanical_Room | Mechanical/Service Room | Shared_Office | Professional Services Office (4 people) | 0 | 41 |
| Room0.33 | 3 P Prof Serv | Mechanical_Room | Mechanical/Service Room | Shared_Office | Professional Services Office (3 people) | 0 | 37 |
| Room0.34 | 96P Lecture | Telecom_Room | Building Telecommunications Room | Auditorium, Room | Lecture Theatre (96 people) | 0 | 29 |
| Room1.04 | 30P Seminar Room | Common_Space | Common Area / Atrium | Conference_Room | Seminar Room (30 people) | 0 | 17 |
| Room1.06 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 23 | 61 |
| Room1.07 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 15 | 51 |
| Room1.08 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 0 | 28 |
| Room1.09 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 0 | 35 |
| Room1.25 | 8P Research Office | Conference_Room | Conference/Seminar Room | Shared_Office | Research Office (8 people) | 0 | 34 |
| Room1.26 | 6P Research Office | Conference_Room | Conference/Seminar Room | Shared_Office | Research Office (6 people) | 21 | 64 |
| Room1.34 | 60P Computer Room 16 SD Cap. | Telecom_Room | Telecommunications Room | Laboratory | Computer Room (60 people) | 0 | 40 |
| Room1.37 | DB Room | Office | Academic Office | Electrical_Room | Distribution Board Room | 0 | 35 |
| Room1.39 | 42P Computer Room 14SD cap. | Office | Academic Office | Laboratory | Computer Room (42 people) | 0 | 35 |
| Room1.40 | 8-12P Meet Rm | Office | Academic Office | Conference_Room | Meeting Room (8-12 people) | 0 | 34 |
| Room2.01 | 8P PHD Students | Laboratory | Research Laboratory | Shared_Office | PhD Students' Office (8 people) | 0 | 32 |
| Room2.02 | 4P Research | Laboratory | Research Laboratory | Shared_Office | Research Office (4 people) | 0 | 36 |
| Room2.03 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 35 |
| Room2.04 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 33 |
| Room2.05 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 7 | 47 |
| Room2.06 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 37 |
| Room2.07 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 0 | 34 |
| Room2.08 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 8 | 43 |
| Room2.13 | Office | Conference_Room | Meeting Room | Enclosed_Office | Office | 0 | 36 |
| Room2.15 | DB Room | Conference_Room | Seminar Room | Electrical_Room | Distribution Board Room | 24 | 53 |
| Room2.17 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 21 | 58 |
| Room2.18 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 33 |
| Room2.19 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 32 |
| Room2.20 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 19 | 51 |
| Room2.21 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 22 | 60 |
| Room2.22 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 20 | 59 |
| Room2.24 | ICT LAN | Office | Academic Office | Telecom_Room | ICT LAN Room | 0 | 29 |
| Room2.26 | 120S Lecture Theatre - Group Bench seating style 30SD Cap. | Office | Academic Office | Auditorium, Room | Lecture Theatre (120 people) | 0 | 41 |
| Room2.34 | 8P PHD Students | Telecom_Room | Telecommunications Room | Shared_Office | PhD Students' Office (8 people) | 0 | 36 |
| Room2.35 | 48P Computer Room 14 SD Cap. | Restroom | Restroom (Male) | Laboratory | Computer Room (48 people) | 0 | 31 |
| Room2.36 | 8P PHD Students | Restroom | Restroom (Female) | Shared_Office | PhD Students' Office (8 people) | 0 | 31 |
| Room2.44 | 5P PHD Research | Server_Room | Server Room | Shared_Office | PhD Research Office (5 people) | 0 | 29 |
| Room2.52 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 7 | 41 |
| Room2.54 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 22 | 57 |
| Room2.55 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 38 |
| Room2.56 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 44 |
| Room2.57 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 31 |
| Room2.66 | Office | Break_Room | Staff Break Room / Kitchen | Enclosed_Office | Office | 0 | 39 |
| Room2.67 | 5P PHD Students | Storage_Room | Storage Room | Shared_Office | PhD Students' Office (5 people) | 0 | 33 |
| Room3.01 | 16-20P Meeting | Laboratory | Research Laboratory | Conference_Room | Meeting Room (16-20 people) | 16 | 48 |
| Room3.02 | 64P Seminar Room | Laboratory | Research Laboratory | Conference_Room | Seminar Room (64 people) | 0 | 31 |
| Room3.03 | 6P PHD Research | Laboratory | Research Laboratory | Shared_Office | PhD Research Office (6 people) | 19 | 45 |
| Room3.04 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 21 | 56 |
| Room3.05 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 8 | 44 |
| Room3.06 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 0 | 34 |
| Room3.13 | Office | Conference_Room | Seminar Room | Enclosed_Office | Office | 0 | 43 |
| Room3.14 | Exec PA | Conference_Room | Seminar Room | Enclosed_Office | Executive PA Office | 0 | 36 |
| Room3.16 | Office | Conference_Room | Meeting Room | Enclosed_Office | Office | 21 | 50 |
| Room3.17 | Office | Break_Room | Staff Common Room | Enclosed_Office | Office | 0 | 31 |
| Room3.18 | Office | Office_Kitchen | Kitchen | Enclosed_Office | Office | 0 | 32 |
| Room3.26 | 6P PHD Research | Conference_Room | Meeting Room | Shared_Office | PhD Research Office (6 people) | 8 | 41 |
| Room3.36 | Staff Room | Restroom | Restroom (Male) | Break_Room | Staff Room | 0 | 33 |
| Room3.37 | 5P Research | Restroom | Restroom (Female) | Shared_Office | Research Office (5 people) | 0 | 43 |
| Room3.38 | 48P Seminar Room | Telecom_Room | Telecommunications Room | Conference_Room | Seminar Room (48 people) | 0 | 32 |
| Room3.50 | DB Room | Laboratory | Research Laboratory | Electrical_Room | Distribution Board Room | 0 | 40 |
| Room3.51 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 15 | 53 |
| Room3.52 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 32 |
| Room3.53 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 7 | 51 |
| Room3.54 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 7 | 40 |
| Room3.56 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 35 |
| Room3.57 | ICT LAN | Laboratory | Research Laboratory | Telecom_Room | ICT LAN Room | 14 | 47 |
| Room3.58 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 19 | 57 |
| Room4.01 | 7P PHD Research | Laboratory | Research Laboratory | Shared_Office | PhD Research Office (7 people) | 14 | 49 |
| Room4.02 | 8P PHD Research | Laboratory | Research Laboratory | Shared_Office | PhD Research Office (8 people) | 0 | 41 |
| Room4.03 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 33 |
| Room4.05 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 6 | 40 |
| Room4.06 | Office | Laboratory | Computer Laboratory | Enclosed_Office | Office | 0 | 26 |
| Room4.11 | 6P Research | Conference_Room | Meeting Room | Shared_Office | Research Office (6 people) | 0 | 35 |
| Room4.12 | Office | Conference_Room | Meeting Room | Enclosed_Office | Office | 0 | 29 |
| Room4.13 | Office | Conference_Room | Seminar Room | Enclosed_Office | Office | 13 | 52 |
| Room4.16 | DB Room | Office | Academic Office | Electrical_Room | Distribution Board Room | 0 | 29 |
| Room4.18 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 8 | 45 |
| Room4.19 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 5 | 40 |
| Room4.20 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 38 |
| Room4.21 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 23 | 65 |
| Room4.22 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 7 | 43 |
| Room4.24 | ICT LAN | Office | Academic Office | Telecom_Room | ICT LAN Room | 0 | 37 |
| Room4.34 | 8P PHD Research | Telecom_Room | Telecommunications Room | Shared_Office | PhD Research Office (8 people) | 0 | 32 |
| Room4.35 | 20 P Seminar | Restroom | Restroom (Male) | Conference_Room | Seminar Room (20 people) | 0 | 38 |
| Room4.36 | 5P Research | Restroom | Restroom (Female) | Shared_Office | Research Office (5 people) | 0 | 29 |
| Room4.38 | Financial Lab | Mechanical_Room | Mechanical/Service Room | Laboratory | Financial Laboratory | 0 | 30 |
| Room4.47 | I.T Workshop | Office | Academic Office | Workshop | IT Workshop | 0 | 33 |
| Room4.55 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 22 | 53 |
| Room4.56 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 14 | 48 |
| Room4.57 | Visiting Staff | Laboratory | Research Laboratory | Enclosed_Office | Visiting Staff Office | 0 | 35 |
| Room4.58 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 22 | 57 |
| Room4.59 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 15 | 40 |
| Room4.60 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 37 |
| Room4.67 | I.T. Store | Office | Academic Office | Storage_Room | IT Store | 0 | 29 |
| Room4.70 | 6P Prof Serv- IT | Break_Room | Staff Break Room | Shared_Office | Professional Services Office (6 people) | 0 | 34 |
| Room4.71 | Maker Rm | Storage_Room | Storage Room | Workshop | Maker Room | 0 | 39 |
| Room5.01 | 8P PHD Research | Laboratory | Research Laboratory | Shared_Office | PhD Research Office (8 people) | 0 | 34 |
| Room5.02 | 8P PHD Research | Laboratory | Research Laboratory | Shared_Office | PhD Research Office (8 people) | 0 | 33 |
| Room5.03 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 14 | 45 |
| Room5.04 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 36 |
| Room5.05 | 90P Lecture | Laboratory | Research Laboratory | Auditorium, Room | Lecture Theatre (90 people) | 23 | 59 |
| Room5.06 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 19 | 54 |
| Room5.15 | Office | Conference_Room | Seminar / Conference Room | Enclosed_Office | Office | 0 | 36 |
| Room5.16 | Office | Conference_Room | Seminar / Conference Room | Enclosed_Office | Office | 8 | 40 |
| Room5.17 | Office | Conference_Room | Meeting Room | Enclosed_Office | Office | 20 | 50 |
| Room5.18 | 5P PHD Research | Conference_Room | Meeting Room | Shared_Office | PhD Research Office (5 people) | 0 | 34 |
| Room5.26 | Small Research | Break_Room | Staff Break Room / Kitchen | Enclosed_Office | Small Research Office | 0 | 40 |
| Room5.34 | 8P PHD Research | Telecom_Room | Telecommunications Room | Shared_Office | PhD Research Office (8 people) | 0 | 38 |
| Room5.35 | 10P PHD Students | Restroom | Restroom (Male) | Shared_Office | PhD Students' Office (10 people) | 0 | 35 |
| Room5.36 | 6P Research | Restroom | Restroom (Female) | Shared_Office | Research Office (6 people) | 0 | 31 |
| Room5.44 | 60P Teaching | Server_Room | Server Room | Conference_Room | Teaching Room (60 people) | 0 | 38 |
| Room5.49 | DB Room | Office | Academic Office | Electrical_Room | Distribution Board Room | 0 | 32 |
| Room5.50 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 31 |
| Room5.51 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 36 |
| Room5.52 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 23 | 52 |
| Room5.53 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 6 | 44 |
| Room5.54 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 35 |
| Room5.56 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 32 |
| Room5.57 | ICT LAN | Laboratory | Research Laboratory | Telecom_Room | ICT LAN Room | 0 | 33 |
| Room5.58 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 31 |
| Room5.59 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 36 |
| Room5.60 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 0 | 37 |
| Room5.61 | Office | Laboratory | Research Laboratory | Enclosed_Office | Office | 20 | 56 |
| Room5.71 | 4P Research | Storage_Room | Storage Room | Shared_Office | Research Office (4 people) | 0 | 35 |

## Appendix B — rooms left as they were because the drawing does not settle them

| room | drawing says | type kept | label kept |
|---|---|---|---|
| Room1.38 | IT Hub | Office | Academic Office |
| Room2.14 | Project Rm - 1 | Conference_Room | Meeting Room |
| Room3.27 | Magic Room | Conference_Room | Meeting Room |
| Room3.65 | Project Rm - 2 | Office | Academic Office |
| Room4.07 | Cyber Security | Office | Academic Office |
| Room5.45 | Project Rm - 3 | Office | Academic Office |

## Appendix C — hbco:spaceFunction corrected in `bldg1_enrichment_metadata.ttl`

| room | old | new |
|---|---|---|
| Room5.01 | Seminar room | PhD research office |
| Room5.02 | Seminar room | PhD research office |
| Room5.03 | Lecture / seminar room | Office |
| Room5.04 | Seminar room | Office |
| Room5.05 | Seminar room | Lecture theatre |
| Room5.06 | Meeting room / office | Office |
| Room5.07 | Meeting room / office | Office |
| Room5.08 | Large seminar / teaching room | Research office |
| Room5.09 | Seminar room | Office |
| Room5.10 | Seminar room | Office |
| Room4.01 | Research lab / seminar room | PhD research office |
| Room4.05 | Teaching lab | Office |
| Room3.01 | Collaborative pod / group study room | Meeting room |
| Room3.05 | Teaching room | Office |
| Room2.01 | Study room / seminar room | PhD research office |
| Room2.05 | Teaching lab | Office |
| Room1.04 | Study room | Seminar room |
| Room1.06 | Teaching room | Office |
| Room0.01 | Atrium / reception area | Lecture theatre |
