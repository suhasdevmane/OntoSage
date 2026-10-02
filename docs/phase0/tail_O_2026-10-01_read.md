# Tail O — 60 unseen questions from the real survey corpus, hand-read

Drawn 2026-10-01 by `scripts/draw_tail.py --name O --n 60 --seed 20261001` from `paper/Survey analysis and results/corpus/classified_corpus.csv`, **excluding every one of the 1,352 questions that appears in any stored answer file** (tails C–N, the demo path, the probe packs). Mix 53 LOOKUP / 5 AGGREGATION / 2 MULTI_STEP against the corpus's own 88/9/3. Question file sha256 `7f3681c35937f53b697fa6de14d459c17a1d17043e07b8900c2cf45d4024e877`.

**Identity: `occupant01` → role=occupant, confirmed from the server's own `[forwarded-user] … (role=occupant)` line, not from the flag typed** (lesson #169). Endpoint `/v1/chat/completions`, streaming, `resp_cache:*` flushed before each ask.

## The measurement was contaminated, and here is exactly how

Partway through, the host restarted Docker **and killed Ollama**, which did not come back. The orchestrator's circuit breaker logged `OPEN — the ollama provider has been unresponsive` **134 times**, and `ollama.exe` was absent from the host process list. **14 of the 60 answers are provider failures** — six *"I wasn't able to generate an answer just now"* and eight *"the readings could not be summarised"*. Ollama was restarted, the breaker cleared, and those 14 were re-asked.

**A re-ask that succeeds is still a first-pass failure**, so both bases are reported below rather than one replacing the other. Host RAM was never the problem: 95.2 GiB total, 56.4 GiB free, 40.8% used — this is not BUG-1194's shape.

## Result

### Second pass (the 14 provider failures re-asked on a healthy LLM)

| label | n | share |
|---|---|---|
| GOOD | 24 | 40.0% |
| DECLINE-OK | 12 | 20.0% |
| **DECLINE-BAD** | **11** | **18.3%** |
| **WEIRD** | **13** | **21.7%** |
| **FABRICATED** | **0** | **0.0%** |

**Acceptable (GOOD + DECLINE-OK): 36/60 = 60.0%**
**Unacceptable: 24/60 = 40.0%**
**FABRICATED: 0** — no figure in any of the 60 traces to data that does not support it.

### First pass (provider failures counted as failures)

**Acceptable: 27/60 = 45.0% · provider failures: 14**

### Against tail N

Tail N (2026-09-30, same corpus, same occupant `/v1` path) read **46/60 = 76.7% acceptable**. Tail O reads **60.0%**. **This is NOT presented as a regression.** Two confounds, neither resolved: tail O excludes 1,352 previously-asked questions so it is a genuinely harder residue, and these labels are mine while tail N's were applied by an earlier pass — a stricter reader produces a lower number from the same system. Resolving it needs one reader labelling both sets.

### What the failures are

**False declines dominate: 11 of 60 (18.3%).** Several are provably false against the graph — filters (30 cleaning-task records the same question listed on its first pass), parking (a `parking_data` store and a Transport Parking amenity), "any movement?" (501 occupancy series), "Room available now?" (the longer phrasing answers it), lighting (a `Lighting` capability topic), continuity (12 ContinuityProvision records).

**Wrong-quantity and misread answers: 13 of 60 (21.7%).** The worst is #39, whose headline contradicts its own table. Two leak internal content to the reader (#21 an incident log, #58 raw AutoCAD markup) and one leaks raw IRIs (#17).

**What worked, and it is structural rather than lucky:** the clarification lane refused "this room" correctly twice (#5, #31); the RBAC refusal named the role and the remedy (#33); privacy was answered correctly when asked directly (#35); and the capability lane gave specific grounded answers on catering, CCTV, wellbeing, sustainability, HVAC zoning and power resilience.

---

## 1. and how can i planted in the roof top
*lane `general_knowledge` · 13.9 s*

> General knowledge (not from this building's records): Planting on a rooftop can be a rewarding way to add greenery and improve insulation, but it requires careful planning. First, assess the roof’s structural load capacity and ensure it can support the weight of soil, plants, and water. Use lightweight, shallow-rooted plants such as succulents, herbs, or dwarf shrubs, and consider a raised planter or a modular container system to keep the soil depth minimal. Install a waterproof membrane and a drainage layer to protect the roof, and use a mulch or gravel layer to reduce evaporation and help retain moisture. Finally, schedule regular maintenance—watering, fertilizing, and checking for leaks—to keep the rooftop garden healthy and the roof protected.

**LABEL: GOOD** — general knowledge, explicitly framed 'not from this building's records'. I first marked this WEIRD for ignoring green-roof records; `bldg1_greenroof_types.ttl` is 11 lines with no labels, so the generic answer is defensible. CORRECTED.

## 2. Are there locations to get food in this Building?
*lane `capability` · 2.6 s*

> Here is what I found for **Abacws Building**: **Catering Amenities**. Abacws amenities include: (1) Ground-floor café (Abacws Café) open 08:00–16:30 weekdays, serving hot drinks, food, and snacks; (2) Vending machines on Floor 1 and Floor 3; (3) Kitchen/breakout areas on Floors 2, 3, and 4 with microwaves and filtered water; (4) Toilets on every floor, with accessible and gender-neutral facilities; (5) Shower facilities on Floor 1; (6) Secure bike storage in the basement; (7) Limited car parking available on Senghennydd Road. *Answered live from the building's own records.*

**LABEL: GOOD** — names the cafe, its hours, vending and kitchens

## 3. if you had a favorite room, which one would it be ?
*lane `general_knowledge` · 9.4 s*

> General knowledge (not from this building's records): I don’t have personal experiences, but if I could pick a favorite room, I’d probably choose a well‑designed, naturally lit space—like a bright, airy study or a cozy lounge—where people can relax, focus, and enjoy a comfortable environment. Such rooms often blend good acoustics, ergonomic furniture, and smart lighting to create a pleasant, productive atmosphere.

**LABEL: GOOD** — whimsical question, honest non-answer, no fabrication

## 4. Does the building have any type of security cameras?
*lane `capability` · 3.6 s*

> Here is what I found for **Abacws Building**: **Cctv Surveillance**. CCTV cameras are installed throughout the building's public areas, corridors, entrances, and car parks. Cameras operate 24/7 and footage is retained for 30 days. The system is monitored by Cardiff University Security Services. CCTV signage is displayed at all camera locations in compliance with GDPR requirements. For CCTV requests (e.g. incident investigation), contact Security Services or submit a Subject Access Request through the university's data protection office. From the full policy document (**governance.md**): # OntoSage Building Intelligence — Governance & Privacy Statement ## What the System Monitors OntoSage monitors the following building systems in **Abacws, Cardiff University**: - **Environmental sensors** (every floor, 0 to 5): temperature, humidity, CO2 concentration, air quality index, TVOC, noise levels, illuminance - **Infrastructure status**: lift/elevator status, HVAC operation mode - **Occupancy indicators**: aggregate motion/presence detection per zone (no individual tracking) - **Energy meters**: electrical consumption at floor and building level ## What the System Does NOT Infer OntoSage is designed around strict data minimisation principles: - **No individual tracking**: The system cannot identify specific people. Occupancy data is aggregate counts, not identities. - **No behavioural

**LABEL: GOOD** — CCTV coverage, 24/7, 30-day retention, GDPR signage

## 5. what is the temperature in this room?
*lane `clarification` · 0.5 s*

> Which room do you mean by "this room"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL: GOOD** — clarification: cannot know which room the asker is in, and says why

## 6. Did you detect aby unusual activity today?
*lane `events` · 49.1 s*

> - **spike** · Room0.31 (noise) [open/low] - seasonal residual · Room4.07 (temperature) [open/low] - **spike** · Room4.60 (air_quality) [open/medium] - **spike** · Room2.48 (air_quality) [open/medium] - seasonal residual · Room1.06 (temperature) [open/medium] _(showing the most recent 500; narrow the window for the full picture)_ _Episodes come from the hourly detector sweep over this building's own sensors; ask 'why was <room> <symptom>?' to see the evidence behind one._

**LABEL: GOOD** — lists anomaly episodes with room and modality

## 7. are lights automatically adjusting properly to current conditions?
*lane `capability` · 8.7 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Asset status record, Condition survey and Fire safety asset records, which I can read for you.

**LABEL: DECLINE-BAD** — a `Lighting` topic EXISTS with lay terms 'lighting, light, lux, brightness, dim, bright, lights, led, natural light, daylight' -- verified in bldg1_capabilities.ttl. The decline named Asset status, Condition survey and Fire safety instead.

## 8. what happens to parking lot security during a power failure?
*lane `metadata` · 8.6 s*

> During a power failure the building’s parking‑lot security device behaves as follows: - **Vehicle barrier (Car park vehicle barrier – DR‑013)** - **Fail state on power loss:** *fail open* – the barrier lifts and the gate opens. - **Current status:** active (the record is in use and has not expired). No other parking‑lot security hardware is recorded in the register, so the vehicle barrier is the only device that determines parking‑lot security during a power outage. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?

**LABEL: GOOD** — names the barrier DR-013, its fail-open state on power loss, and that no other parking security hardware is recorded

## 9. Does this building use a chiller or some other more sophisticated HVAC system? I'm concerned about high power use in winter and summer.
*lane `analytics` · 53.9 s*

> **Electrical energy consumption per floor** is the only property measured. The latest readings range from 5.32 kWh on Floor 5 to 5.91 kWh on Floor 3. This data does not provide information about whether the building uses a chiller or another HVAC system. _At least one sensor returned the full 1000 rows this question reads per sensor, so these readings are a SAMPLE of the newest data and their number is not a count of what the period holds. The readings used run from 2026-09-19 08:20:25 to 2026-10-01 12:55:54. That is the newest part of the last 30 days, not the whole of it._ **Boundary:** summed across 6 meters (Energy_Meter_Floor0, Energy_Meter_Floor1, Energy_Meter_Floor2, Energy_Meter_Floor3, Energy_Meter_Floor4, Energy_Meter_Floor5), covering Floor 0 (Ground Floor), Floor 1 (First Floor), Floor 2 (Second Floor), Floor 3 (Third Floor), Floor 4 (Fourth Floor), Floor 5 (Fifth Floor). The total is the sum of those boundaries — it is not a separate whole-site reading. --- **You might also ask:** Plot this data? | Check compliance against ASHRAE? | Compare with another zone? --- *Sources: `Building model` `Energy Metering System` `Analytics Engine`*

**LABEL: WEIRD** — an HVAC-system question answered with per-floor energy, and it says so itself: 'This data does not provide information about whether the building uses a chiller'. #13 proves an HVAC Zoning topic exists.

## 10. Are there any areas currently under maintenance restrictions?
*lane `metadata` · 57.8 s*

> I could not find any record of an **“Maintenance Restriction”** sensor or area in the portion of the building’s records that was searched. The data that was retrieved focuses on **Mode Status** points, which indicate the current operating mode of systems, devices, or control loops (e.g., heating, cooling, occupied, unoccupied, etc.). While a maintenance‑related mode might be represented by a specific Mode Status value, no such value or label was present in this query’s results. If you are looking for an indication that a particular area is under maintenance, you might want to check whether any of the Mode Status points are set to a value that represents a maintenance or “off‑line” state. However, that specific information is not present in the data that was returned. --- **You might also ask:** Show current readings for these sensors? | Compare zones? | Generate a report? --- *Sources: `Building model`*

**LABEL: DECLINE-BAD** — ClosurePeriod=10 and WorkOrder=24 records exist; the register list in the same session names both

## 11. Is it possible to set different detection thresholds for different chemicals you may want more accurate detection of?
*lane `capability` · 17.2 s*

> **I could not find this in Abacws Building's documents.** I searched them and none is about this question, so I have nothing grounded to answer it with. Name the record or the measurement it would be written down as and I will look there next.

**LABEL: DECLINE-OK** — configurability of chemical thresholds is genuinely not a recorded fact

## 12. Do you like having people inside you?
*lane `general_knowledge` · 25.7 s*

> General knowledge (not from this building's records): I don’t have feelings or preferences, so I don’t “like” or “dislike” having people inside me.

**LABEL: GOOD** — honest non-answer to a question about feelings

## 13. how do we prevent over heating
*lane `capability` · 8.6 s*

> Here is what I found for **Abacws Building**: **Hvac Zoning**. The building has a zone-based HVAC system with independent climate control per zone. Zones are mapped to BACnet IDs. Occupants cannot directly adjust HVAC settings; facility management controls setpoints. The system adjusts automatically based on occupancy schedules and sensor feedback. Contact facility management for comfort complaints or temperature adjustments. From the full policy document (**hvac_operation.md**): | Level 4 offices and meeting rooms | 21 degC +/- 1.5, CO2 below 1000 ppm | 16 degC frost protection only | Mon-Fri 07:00-19:00 | Heating 01 Oct to 30 Apr; cooling 01 May to 30 Sep | | BMS-HVAC operators | Active | | | REG-006 | AHU Floor 5 supply air | Level 5 seminar, conference and offices | 21 degC +/- 1.5, CO2 below 1000 ppm | 16 degC frost protection only | Mon-Fri 07:00-19:00 | Heating 01 Oct to 30 Apr; cooling 01 May to 30 Sep | Runs to 21:00 when a conference is booked in 5.15 or 5.16 | BMS-HVAC operators | Active | No flow measurement is fitted on AEP-006, so conformance to this regime cannot currently be verified | | REG-007 | Chilled water system | All AHUs and Level 2 laboratory fan coil units | Flow 6 degC, return 12 degC | System off below 14 degC ambient | Continuous while enabled | Enabled 01 May to 30 Sep | Enabled outside the cooling season when ambient exceeds 18 degC | M and E Main

**LABEL: GOOD** — HVAC Zoning topic, specific and grounded

## 14. Is there adequate handicapped parking?
*lane `capability` · 23.9 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Stock item records, which I can read for you.

**LABEL: DECLINE-OK** — no accessible-parking record found in the amenity files; the live amenity is a step-free ENTRANCE at the car park, not bay counts. I first marked this DECLINE-BAD. CORRECTED. The pointer ('Stock item records') is still irrelevant.

## 15. humidity safe
*lane `sensor_data` · 18.9 s*

> **Across the building humidity is averaging 54.6 %**, ranging from 50.5 to 58.9 %. | Floor | Now % | Lowest | Highest | Sensors | |---|---|---|---|---| | Floor 0 | 54.4 | 52.0 | 57.0 | 17 | | Floor 1 | 54.5 | 50.7 | 58.6 | 14 | | Floor 2 | 54.1 | 50.5 | 57.2 | 49 | | Floor 3 | 54.2 | 50.7 | 57.5 | 49 | | Floor 4 | 54.4 | 51.0 | 57.9 | 58 | | Floor 5 | 56.0 | 52.9 | 58.9 | 87 | Floor 5 is the highest of the 6 floors at 56.0 %; Floor 2 the lowest at 54.1 %. Based on 275 humidity sensors on 6 floors, the newest reading from each sensor in the last 60 minutes (to Thu 01 Oct 14:00, building time): each sensor's newest reading. 1 sensors have no recorded location and are left out of the grouping. --- *Sources: `Building model`*

**LABEL: GOOD** — humidity by floor with sensor counts; does not state a safety verdict, which is the weakness, but the figures answer the quantity asked about

## 16. Are all doors equipped with sensors?
*lane `sensor_data` · 57.3 s*

> All of the doors listed in the sensor inventory have a sensor installed. Below are the key statistics for each sensor, followed by the most recent reading that was captured on 2026‑10‑01. | Door sensor | Period | Mean | Min | Max | Night mean (00‑06) | Day mean (08‑18) | Latest reading (timestamp) | |-------------|--------|------|-----|-----|--------------------|-----------------|----------------------------| | **Door Position Sensor – Main Entrance** | 24 Sep 15:28 – 01 Oct 13:57 | 51 | 34 | 66 | 42 | 58.2 | 58.0 @ 2026‑10‑01 13:57:29 | | **Door Position Sensor – Server Room Floor 2 (Room 2.44)** | 24 Sep 15:28 – 01 Oct 13:57 | 49.3 | 32 | 66 | 40.9 | 56.2 | 63.0 @ 2026‑10‑01 13:57:30 | | **Door Position Sensor – Server Room Floor 4 (Room 4.44)** | 24 Sep 15:28 – 01 Oct 13:57 | 49.3 | 32 | 65 | 40.6 | 56.4 | 61.0 @ 2026‑10‑01 13:57:29 | | **Door Position Sensor – Server Room Floor 5 (Room 5.44)** | 24 Sep 15:28 – 01 Oct 13:57 | 51.9 | 36 | 68 | 43.5 | 58.9 | 61.0 @ 2026‑10‑01 13:57:30 | | **Fire Exit Door Sensor – Floor 1** | 24 Sep 15:28 – 01 Oct 13:57 | 50.1 | 33 | 64 | 41.3 | 57.0 | 59.0 @ 2026‑10‑01 13:57:29 | | **Fire Exit Door Sensor – Floor 2** | 24 Sep 15:28 – 01 Oct 13:57 | 48.1 | 32 | 64 | 40.0 | 54.8 | 54.0 @ 2026‑10‑01 13:57:30 | | **Fire Exit Door Sensor – Ground Floor** | 24 Sep 15:28 – 01 Oct 13:57 | 49.0 | 33 | 64 | 40.4 | 56.2 | **58.0 @ 2026‑10‑01 13:57:30** 

**LABEL: WEIRD** — 'All of the doors listed in the sensor inventory have a sensor installed' is a TAUTOLOGY presented as a finding. The question asks for coverage against the total number of doors.

## 17. what role does mold play in indoor pollution?
*lane `sensor_data` · 237.0 s*

> I could not find any record of **mold** or indoor‑pollution sensors in the building’s records that were searched. - **AccessPermission** (class of named grants over controlled openings) - Instances like **bldg:access/APG‑001**, **bldg:access/APG‑002**, …, **bldg:access/APG‑013** (and 23 more) If you’re looking for information on indoor air quality or mold detection, you might want to check other parts of the building’s data set that include relevant sensors or environmental monitoring records. --- *Sources: `Building model`*

**LABEL: WEIRD** — a general-knowledge question about mould answered with a list of **AccessPermission** instances and raw IRIs (bldg:access/APG-001...), 237 s

## 18. Which meeting room is available immediately?
*lane `events` · 31.8 s*

> **5 of 18 meeting rooms have no booking today**: Room 2.14, Room 3.26, Room 5.15, Room 5.17, Room 5.18 _Availability = no booking on record; walk-in use isn't tracked here._

**LABEL: GOOD** — 5 of 18 meeting rooms unbooked, named, and discloses that walk-in use is not tracked

## 19. Can the energy meter keep notes about why we had spikes for future year reference?
*lane `capability` · 9.5 s*

> **I could not find this in Abacws Building's documents.** I searched them and none is about this question, so I have nothing grounded to answer it with. Name the record or the measurement it would be written down as and I will look there next.

**LABEL: DECLINE-OK** — whether a meter can keep notes is not a recorded fact

## 20. power saved?
*lane `capability` · 1.4 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Door and shutter hardware records, which I can read for you.

**LABEL: DECLINE-BAD** — 'power saved?' pointed at Door and shutter hardware; the building holds energy and submeter series

## 21. Are the doors locked
*lane `capability` · 3.4 s*

> Here is what I found in **Abacws Building** documentation: **From: Incident And Near Miss Log** LEV left running; room ventilated | Container placed too close to the sash; no procedural failure found | false | | Lab manager | Building Safety Adviser | 2026-04-24 | Closed | | | INC-2026-005 | Lift entrapment, two occupants, 18 minutes | 2026-05-02 | Main lift core | service failure | minor | serious | Lift engineer attended; occupants released; lift taken out of service | Door interlock intermittent fault; component replaced | true | | Security officers | M and E Maintenance Supervisor | 2026-05-30 | Closed | Reportable as a dangerous occurrence. The lift is the only step-free route between levels | | INC-2026-006 | Unauthorised access to the Level 2 comms room | 2026-05-21 | Room 2.13 - Meeting Room | security | none | serious | Door secured; access log reviewed | A permission group granted through an inherited template nobody had reviewed | false | Inheritance review of all comms room groups - NOT YET COMPLETE | Security officers | Security Duty Manager | | Open | Directly connected to the access permission register: the override on AP-014 is the same path | | INC-2026-007 | Delivery vehicle blocked the fire service access route | 2026-06-08 | Room 0.06 - Loading and Goods Storage | near miss | none | major | Vehicle moved within four minutes; driver briefed | | false | Delive

**LABEL: WEIRD** — 'Are the doors locked' answered with a raw dump of the Incident and Near Miss Log, including a lift-entrapment incident. Internal register content to a reader -- BUG-785's family.

## 22. what am i supposed to accomplish herh?
*lane `general_knowledge` · 15.5 s · **RE-ASKED** (first pass was a provider failure)*

> General knowledge (not from this building's records): It’s hard to give a precise answer without knowing the context, but generally you should start by clarifying the goal you’re trying to reach. Identify the main objective, break it down into smaller, actionable steps, and set realistic milestones. Then track progress, adjust as needed, and keep communication open with any stakeholders involved. If you can share more details about the project or task, I can offer more specific guidance.

**LABEL: GOOD** — RE-ASKED: general knowledge, honestly framed. First pass was a provider failure.

## 23. How about hearing everything? Even when whispered to?
*lane `general_knowledge` · 11.9 s · **RE-ASKED** (first pass was a provider failure)*

> General knowledge (not from this building's records): Humans can’t literally hear everything, even whispered words. Our ears are most sensitive to mid‑frequency sounds (around 2–4 kHz) and can pick up whispers only in very quiet settings where background noise is below roughly 30 dB. In louder environments the low‑level signal is masked, and even with hearing aids or directional microphones the ability to detect a whisper depends on the device’s gain, frequency response, and the acoustic isolation of the listener. So while technology can extend our hearing range, it can’t make us hear every whispered sound in all conditions.

**LABEL: WEIRD** — RE-ASKED: in a building-sensor context this reads as a question about microphones and privacy; answered with human-hearing physiology (2-4 kHz, 30 dB). The building records noise in dB, not audio.

## 24. are you religious?
*lane `capability` · 0.4 s*

> Here is what I found for **Abacws Building**: **Wellbeing Facilities**. Wellbeing facilities in Abacws: (1) A multi-faith prayer and reflection room is located on Floor 1 (room 1.04) — available to all; (2) Gender-neutral toilet facilities are available on every floor; (3) A nursing/feeding room for parents is on Floor 2; (4) Welfare and mental health support is available through Cardiff University Student Services (studentconnect.cardiff.ac.uk) and the Staff Wellbeing team. The building has a calm, quiet breakout area on Floor 4 for focused work or informal welfare conversations. *Answered live from the building's own records.*

**LABEL: GOOD** — wellbeing facilities: prayer room on floor 1, gender-neutral toilets, nursing room

## 25. How does "Ozone" get inside a building if it’s usually in the atmosphere?
*lane `capability` · 2.3 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team.

**LABEL: DECLINE-OK** — how ozone enters a building is general science, not a building record

## 26. Will this building help me save money or only saving cost for the company?
*lane `metadata` · 28.9 s · **RE-ASKED** (first pass was a provider failure)*

> The register does not contain any information about whether the building will help you save money or whether the cost savings are only for the company. What it does record for the financial period 2026‑08 is: - **24 cost records** in total - 19 records are *open* - 3 records are *query* - 2 records are *closed* - The records are grouped by cost centre: - ABW‑UTIL – 2 records - ABW‑MECH – 5 records - ABW‑SOFT – 5 records - ABW‑COMP – 3 records - ABW‑SEC – 3 records - ABW‑CAP – 2 records - ABW‑IT – 2 records - ABW‑LAB – 2 records No record in the register contains a statement or a field that indicates money‑saving benefits for an individual user or for the company. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?

**LABEL: DECLINE-OK** — RE-ASKED: states the register holds no answer to the question and then what it DOES hold (24 cost records, 19 open, 3 query, 2 ...)

## 27. What is the purity of the drinking water?
*lane `analytics` · 7.0 s*

> Analysis complete. Output: Sensor readings (9000 data points): Sensor : Floor0 sat water flow rate Latest : 31.00 at 2026-10-01 13:09:51 Mean : 23.52 | Median: 23.70 Min : 13.70 | Max : 32.10 Std Dev: 4.67 ---------------------------------------- Sensor : Water Flow Sensor Main Latest : 32.30 http://qudt.org/vocab/unit/L-PER-MIN at 2026-10-01 13:09:52 Mean : 24.14 http://qudt.org/vocab/unit/L-PER-MIN | Median: 23.50 http://qudt.org/vocab/unit/L-PER-MIN Min : 14.50 http://qudt.org/vocab/unit/L-PER-MIN | Max : 35.20 http://qudt.org/vocab/unit/L-PER-MIN Std Dev: 4.82 http://qudt.org/vocab/unit/L-PER-MIN ---------------------------------------- Sensor : Floor3 sat water flow rate Latest : 30.70 at 2026-10-01 13:09:51 Mean : 24.06 | Median: 24.15 Min : 14.60 | Max : 32.90 Std Dev: 4.79 ---------------------------------------- Sensor : Water Flow Sensor HotWater Latest : 35.20 at 2026-10-01 13:09:51 Mean : 26.00 | Median: 25.80 Min : 17.20 | Max : 37.20 Std Dev: 4.83 ---------------------------------------- Sensor : Water Meter Floor5 Latest : 31.20 http://qudt.org/vocab/unit/M3 at 2026-10-01 13:09:52 Mean : 23.65 http://qudt.org/vocab/unit/M3 | Median: 23.60 http://qudt.org/vocab/unit/M3 Min : 13.90 http://qudt.org/vocab/unit/M3 | Max : 33.10 http://qudt.org/vocab/unit/M3 Std Dev: 4.79 http://qudt.org/vocab/unit/M3 ---------------------------------------- Sensor : Floor4 sat water f

**LABEL: WEIRD** — 'purity of the drinking water' answered with water FLOW RATE in L/min, plus a raw QUDT unit URI. `bldg1_potability.ttl` exists.

## 28. what's the currents voltage and is it stable?
*lane `capability` · 2.9 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team.

**LABEL: DECLINE-OK** — voltage and its stability are not recorded

## 29. Is there a warmer area than the lobby?
*lane `capability` · 10.7 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Asset engineering profile and Workspace profile records, which I can read for you.

**LABEL: DECLINE-BAD** — 'Is there a warmer area than the lobby?' declined, over ~296 temperature sensors; #32 answers the same quantity building-wide

## 30. Is this a gun-free site?
*lane `general_knowledge` · 24.6 s · **RE-ASKED** (first pass was a provider failure)*

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Service continuity provision, Interval record and Timetabled session records. Ask about one of those and I will read them. **I couldn't read Abacws Building's sensor catalogue just now,** so I can't list what it measures. Ask about a particular quantity, or try again in a moment.

**LABEL: DECLINE-OK** — RE-ASKED: declines a weapons-policy question. Defensible; the pointer (Service continuity, Interval record, Timetabled session) is irrelevant, and it carries the cold-cache 'couldn't read the sensor catalogue' line.

## 31. IS THIS ROOM WARMER THAN THE OTHER ROOMS IN THE BUILDING ?
*lane `clarification` · 0.4 s*

> Which room do you mean by "this room"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL: GOOD** — clarification on 'THIS ROOM', same correct refusal as #5

## 32. Is any area overheating right now?
*lane `sensor_data` · 10.3 s*

> **Across the building temperature is averaging 23.8 °C**, ranging from 15.4 to 25.1 °C. | Floor | Now °C | Lowest | Highest | Sensors | |---|---|---|---|---| | Floor 0 | 23.9 | 20.2 | 24.6 | 19 | | Floor 1 | 23.0 | 15.4 | 24.3 | 16 | | Floor 2 | 23.8 | 16.5 | 24.6 | 51 | | Floor 3 | 23.9 | 18.2 | 24.6 | 51 | | Floor 4 | 23.9 | 17.6 | 24.9 | 60 | | Floor 5 | 24.4 | 16.2 | 25.1 | 89 | Floor 5 is the highest of the 6 floors at 24.4 °C; Floor 1 the lowest at 23.0 °C. Based on 288 temperature sensors on 6 floors, the newest reading from each sensor in the last 60 minutes (to Thu 01 Oct 14:15, building time): each sensor's newest reading. 2 sensors have no recorded location and are left out of the grouping. --- *Sources: `Building model`*

**LABEL: GOOD** — temperature by floor with sensor counts and a building range

## 33. can you turn off lights in rooms that are not being used?
*lane `control` · 1.0 s*

> You don't have permission to control building systems (role: occupant). Facility managers and administrators can make configuration changes. Contact your facility manager if you need this access.

**LABEL: GOOD** — RBAC refusal that names the role and says who can do it -- design contract #7

## 34. Which workspace has the best air circulation at the moment?
*lane `metadata` · 13.6 s · **RE-ASKED** (first pass was a provider failure)*

> The register does not record any information about air circulation in the workspaces. It does record the following for each workspace: * **Network rating** (e.g., strong, adequate, weak) * **Daylight aspect** (e.g., South‑facing, North‑facing, internal, no daylight) * **Noise profile** (e.g., quiet, conversational, silent) * **Suitability for calls** (true/false) * **Other attributes** such as seat count, opening hours, access classification, etc. All 28 workspace records are currently marked **active**. No record contains a field that indicates air circulation quality or performance. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?

**LABEL: DECLINE-OK** — RE-ASKED: states air circulation is not recorded and lists what the workspace register does hold (network rating, daylight aspect, noise profile)

## 35. Is my data safe?
*lane `capability` · 0.6 s*

> Here is what I found for **Abacws Building**: **Data Privacy Gdpr**. Your privacy is protected. The Abacws smart building does NOT track individual people or personal movements. Environmental sensors (temperature, CO2, humidity, PIR presence) collect zone-level aggregated data only — no personal identifiers are recorded or linked to individuals. GDPR compliance: (1) Data is collected solely for building management (energy optimisation, comfort, maintenance); (2) All sensor data is anonymised at the point of collection; (3) No data is shared with third parties without consent; (4) Retention periods follow Cardiff University's data schedule. CCTV cameras operate separately under Cardiff University's CCTV policy (footage retained 30 days, access restricted to Security Services and authorised investigators). For a full privacy notice, Subject Access Request, or to contact the Data Protection Officer: dataprotection@cardiff.ac.uk or visit the Cardiff University data protection pages online. From the full policy document (**governance.md**): Deletion or Access Contact dataprotection@cardiff.ac.uk with subject line "OntoSage Data Request". Requests are processed within 30 days per GDPR Article 12. ## Ethical Commitments - The system will clearly state when it cannot answer a question with the available data rather than guessing. - No decisions affecting individuals are made automatica

**LABEL: GOOD** — privacy answered correctly: zone-level aggregates, no personal identifiers

## 36. I want to know more about flow rate and how those sensors can be used to save residents' money.
*lane `capability` · 2.9 s*

> **I could not find this in Abacws Building's documents.** I searched them and none is about this question, so I have nothing grounded to answer it with. Name the record or the measurement it would be written down as and I will look there next.

**LABEL: DECLINE-OK** — how flow sensors could save money is not a recorded fact

## 37. do you have to be very intelligent
*lane `general_knowledge` · 10.7 s · **RE-ASKED** (first pass was a provider failure)*

> General knowledge (not from this building's records): No, you don’t have to be exceptionally intelligent to succeed in most areas. While a strong aptitude can help with complex tasks, many skills—such as communication, organization, creativity, and perseverance—can be developed through practice, learning, and experience. Success often depends more on effort, curiosity, and the willingness to keep improving than on innate intelligence alone.

**LABEL: GOOD** — RE-ASKED: general knowledge, honestly framed

## 38. VOC detected?
*lane `sensor_data` · 41.9 s · **RE-ASKED** (first pass was a provider failure)*

> Yes – VOC levels are being recorded in the building. The most recent snapshot (2026‑10‑01 14:43:22) shows the following TVOC readings (unit not recorded): | Sensor | Value | |--------|-------| | TVOC Level Sensor 5.13 | 375 | | TVOC Level Sensor 5.06 | 376 | | TVOC Level Sensor 5.01 | 351 | | TVOC Level Sensor 5.05 | 341 | | TVOC Level Sensor 5.02 | 343 | | TVOC Level Sensor 5.03 | 350 | | TVOC Level Sensor 5.04 | 333 | | TVOC Level Sensor 5.07 | 307 | | TVOC Level Sensor 5.08 | 341 | | TVOC Level Sensor 5.09 | 362 | Across all 41 000 records (from 29 Sep 22:17 to 01 Oct 14:41, building time) the overall statistics are: * **Floor‑sat TVOC sensors** – mean 228–234, minimum 114–125, maximum 363–377. * Daytime (08:00‑18:00) averages are about 305–323, while nighttime (00:00‑06:00) averages are 155–170. * **Individual 5.x TVOC sensors** – mean 267–292, minimum 142–178, maximum 392–387. * Daytime averages are roughly 310–325, nighttime averages 180–200. The latest values fall comfortably within these historical ranges, indicating normal VOC activity for the building. _At least one sensor returned the full 1000 rows this question reads per sensor, so these readings are a SAMPLE of the newest data and their number is not a count of what the period holds. The readings used run from 2026-09-29 21:17:59 to 2026-10-01 13:43:22. That is the newest part of the last 30 days, not the whole of

**LABEL: GOOD** — RE-ASKED: 'Yes - VOC levels are being recorded', with TVOC per sensor and a timestamp. First pass could not summarise.

## 39. Do you adjust temperature based on how crowded it is?
*lane `sensor_data` · 3.5 s*

> **Across the building temperature is averaging 27.6 °C**, ranging from 7.2 to 71.0 °C. | Floor | Now °C | Lowest | Highest | Sensors | |---|---|---|---|---| | Floor 0 | 23.9 | 20.2 | 24.6 | 19 | | Floor 1 | 23.0 | 15.4 | 24.3 | 16 | | Floor 2 | 23.8 | 16.5 | 24.6 | 51 | | Floor 3 | 23.9 | 18.2 | 24.6 | 51 | | Floor 4 | 23.9 | 17.6 | 24.9 | 60 | | Floor 5 | 24.4 | 16.2 | 25.1 | 89 | | Floor http://abacwsbuilding.cardiff.ac.uk/abacws#Rooftop | 50.6 | 7.2 | 71.0 | 8 | Floor http://abacwsbuilding.cardiff.ac.uk/abacws#Rooftop is the highest of the 7 floors at 50.6 °C; Floor 1 the lowest at 23.0 °C. Based on 296 temperature sensors on 7 floors, the newest reading from each sensor in the last 60 minutes (to Thu 01 Oct 14:15, building time): each sensor's newest reading. 2 sensors have no recorded location and are left out of the grouping. --- *Sources: `Building model`*

**LABEL: WEIRD** — **THE MOST SERIOUS ANSWER IN THIS SET.** Headline 'averaging 27.6 °C, ranging from 7.2 to 71.0 °C' sits directly above its own per-floor table reading 23.0-23.9 °C. The headline CONTRADICTS the table in the same answer, and 71 °C is a heating circuit, not room air -- BUG-521's quantity-mixing shape.

## 40. Are systems running efficiently?
*lane `clarification` · 24.9 s · **RE-ASKED** (first pass was a provider failure)*

> Which system are you referring to? For example: 1) HVAC, 2) lighting, or 3) overall building energy efficiency?

**LABEL: GOOD** — RE-ASKED: asks which system is meant (HVAC, lighting, or overall energy)

## 41. Can the lifts "learn" that the cafeteria floor is the priority destination at exactly 12:05 PM?
*lane `capability` · 7.3 s*

> 'cafeteria' does not exist in this building, so there is nothing to report about it.

**LABEL: DECLINE-BAD** — "'cafeteria' does not exist in this building" -- the building has a cafe, which answer #2 names with its opening hours. A synonym miss rendered as a flat non-existence claim.

## 42. What is the function of your building?
*lane `capability` · 7.3 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Emergency coordination function records, which I can read for you.

**LABEL: DECLINE-BAD** — 'What is the function of your building?' declined; `bldg1_description.ttl` exists

## 43. Are there any free parking spots available right now?
*lane `sensor_data` · 115.1 s · **RE-ASKED** (first pass was a provider failure)*

> I couldn't put an answer together from Abacws Building's records — I did read them, but what I could make of them did not answer the question you asked. The nearest things I can answer are the Building cost line, Accessible route and Interval record records. Ask about one of those and I will read them. **I couldn't read Abacws Building's sensor catalogue just now,** so I can't list what it measures. Ask about a particular quantity, or try again in a moment. --- *Sources: `Building model` `Occupancy Sensing System`*

**LABEL: DECLINE-BAD** — RE-ASKED: still declines, now pointing at Building cost line and Accessible route. A `parking_data` store and a Transport Parking amenity exist. The FIRST pass was worse -- it answered with meeting-room booking status.

## 44. what kind of cement using for buidings?
*lane `general_knowledge` · 11.5 s · **RE-ASKED** (first pass was a provider failure)*

> General knowledge (not from this building's records): For most conventional buildings the standard material is Portland cement, which is a hydraulic binder made from clinker (calcium silicates, aluminates, and ferrites) mixed with gypsum to control setting time. It is available in several grades (e.g., CEM I 52.5, CEM I 42.5) that differ in compressive strength and workability, and can be blended with supplementary cementitious materials such as fly ash, slag, or silica fume to improve durability, reduce heat of hydration, or lower carbon footprint. In special applications—high‑strength concrete, rapid‑setting mixes, or low‑carbon designs—other types such as high‑performance concrete (HPC), geopolymer cement, or blended cements may be chosen.

**LABEL: GOOD** — RE-ASKED: general knowledge on Portland cement, honestly framed

## 45. is the building currently using renewable energy
*lane `capability` · 7.1 s*

> Here is what I found for **Abacws Building**: **Sustainability**. Abacws was designed to BREEAM 'Excellent' specification. Sustainability features: (1) High-performance building fabric with triple-glazed facades; (2) Mechanical heat recovery ventilation; (3) LED lighting with daylight harvesting throughout; (4) Electric vehicle charging points in the car park; (5) Green roof on the second-floor terrace; (6) Rainwater harvesting for toilet flushing; (7) Building energy performance is monitored in real-time. Recycling facilities (general waste, paper, glass, cans) are available on every floor. *Answered live from the building's own records.*

**LABEL: GOOD** — sustainability: BREEAM Excellent, triple glazing, heat recovery, LED with daylight harvesting, EV charging

## 46. how often are the filters cleaned and maintained?
*lane `metadata` · 10.8 s · **RE-ASKED** (first pass was a provider failure)*

> The register does not record any information about filter cleaning or maintenance. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?

**LABEL: DECLINE-BAD** — RE-ASKED: 'The register does not record any information about filter cleaning or maintenance' -- and the FIRST PASS of the same question listed 30 cleaning-task records (CLN-0001..CLN-0030, scheduled). ServiceSchedule=25 also exists, and the AHU filter differential-pressure sensors are literally a filter-clogging measure. **The re-ask is WORSE than the first pass: a false absence over records it had just listed.**

## 47. NO2 present?
*lane `sensor_data` · 77.2 s · **RE-ASKED** (first pass was a provider failure)*

> At 2026‑10‑01 14:47:22 the **NO2 Level Sensor installed‑node 5.19** recorded **27** (unit not recorded). During the period from 01 Oct 05:19 to 01 Oct 14:47 this sensor’s readings ranged from a low of **19** to a high of **29**, with an average of **21.1**. The floor‑level NO₂ sensors show similar averages around **22–23**, indicating a stable concentration within the typical range. No values exceed the observed maximum of 29, so the current reading is well within the normal operating range. _At least one sensor returned the full 1000 rows this question reads per sensor, so these readings are a SAMPLE of the newest data and their number is not a count of what the period holds. The readings used run from 2026-09-29 21:21:55 to 2026-10-01 13:47:22. That is the newest part of the last 30 days, not the whole of it._ --- *Sources: `Building model` `Live Sensor Data` `Indoor Air Quality System`*

**LABEL: GOOD** — RE-ASKED: NO2 named sensor, value, range, mean and timestamp

## 48. What jobs can you do?
*lane `metadata` · 22.2 s · **RE-ASKED** (first pass was a provider failure)*

> The building’s work‑order register contains 24 records that cover a range of maintenance and inspection tasks. Below is a quick snapshot of the job types that are recorded, grouped by the location where they are carried out. **Air Handling Unit – Floor 1** • Fault investigation (WO‑001 – in‑progress) • Electrical inspection (WO‑002, WO‑003, WO‑004, WO‑005, WO‑006, WO‑007 – all completed) • Belt tensioning (WO‑003 – completed) • Vibration check (WO‑004 – completed) • Annual service (WO‑005 – completed) • Preventive maintenance (WO‑006 – completed) **Air Handling Unit – Floor 3** • Electrical inspection (WO‑008 – open) • Filter replacement (WO‑009 – completed) **Electrical Breaker Panel – Floor 3** • Thermographic survey (WO‑010 – in‑progress) • Annual service (WO‑011 – in‑progress) • Torque check on terminations (WO‑012 – in‑progress) • Insulation resistance test (WO‑013 – open) **Fan Coil Unit Room 5.03** • Coil clean and filter change (WO‑014 – completed) • Condensate drain clearance (WO‑015 – open) **Main Passenger Lift** • Preventive maintenance (WO‑016 – completed) • Annual service (WO‑017 – completed) • Electrical inspection (WO‑018 – completed) • Emergency repair (WO‑019 – completed) • Door interlock adjustment (WO‑020 – completed) • Vibration check (WO‑021 – in‑progress) • Annual service (WO‑022 – in‑progress) • Rope tension check (WO‑023 – completed) **Chiller Pump 1** 

**LABEL: WEIRD** — RE-ASKED: 'What jobs can you do?' is a self-description question; answered with the work-order register (24 maintenance tasks)

## 49. any movement?
*lane `capability` · 1.2 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team.

**LABEL: DECLINE-BAD** — 'any movement?' declined, over 501 occupancy series

## 50. how does the building communicate with is owner?
*lane `capability` · 2.6 s*

> **I could not find this in Abacws Building's documents.** I searched them and none is about this question, so I have nothing grounded to answer it with. Name the record or the measurement it would be written down as and I will look there next.

**LABEL: DECLINE-OK** — how the building communicates with its owner is not a recorded fact

## 51. are the CO2 sensors forcing extra ventilation n raising energy use
*lane `analytics` · 5.2 s*

> **Across the building CO2 is averaging 923 ppm**, ranging from 816 to 1,142 ppm. | Floor | Now ppm | Lowest | Highest | Sensors | |---|---|---|---|---| | Floor 0 | 888 | 830 | 1,082 | 17 | | Floor 1 | 891 | 838 | 1,087 | 14 | | Floor 2 | 887 | 835 | 1,060 | 49 | | Floor 3 | 889 | 826 | 1,086 | 50 | | Floor 4 | 906 | 816 | 1,115 | 58 | | Floor 5 | 1,076 | 952 | 1,142 | 88 | Floor 5 is the highest of the 6 floors at 1,076 ppm; Floor 2 the lowest at 887 ppm. Based on 280 CO2 sensors on 6 floors, the newest reading from each sensor in the last 60 minutes (to Thu 01 Oct 14:18, building time): each sensor's newest reading. 4 sensors have no recorded location and are left out of the grouping. --- **You might also ask:** Plot this data? | Check compliance against ASHRAE? | Compare with another zone? --- *Sources: `Building model`*

**LABEL: WEIRD** — a question about whether CO2 control raises energy use answered with CO2 averages; the question is about control behaviour and cost

## 52. Can I program fresh air boosts on schedule?
*lane `sensor_data` · 6.0 s*

> I couldn't tie that question to a reading I can give you, so I have no figure for it. I can answer about a room, a floor or a quantity the building measures, for example "What is the temperature in a named room right now?" or "Which floor has the most people right now?". --- *Sources: `Building model`*

**LABEL: DECLINE-OK** — honest, and offers two concrete example questions

## 53. Room available now?
*lane `events` · 29.4 s · **RE-ASKED** (first pass was a provider failure)*

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Cleaning task, Workspace profile and Teaching AV readiness records and the readings of air quality, carbon monoxide, co2 and damper position. Ask about one of those and I will read them.

**LABEL: DECLINE-BAD** — RE-ASKED: 'Room available now?' declines, while #18 answers the longer phrasing with 5 of 18 rooms named. Same question, two outcomes.

## 54. How does the flow sensor know if a toilet is leaking or running to much, that is, how does it know for that particular toilet model, since it's not clear it has the model information?
*lane `capability` · 1.6 s*

> **I have no evidence record for a previous answer in this conversation.** Every consequential answer carries one — its sources and their owners, the operation performed, when the evidence was observed and when it was retrieved, and the checks that fired. Ask a question first and then ask how I know, and I will read that record back to you. I would rather say this than reconstruct an explanation after the fact, which is not the same thing as provenance.

**LABEL: WEIRD** — a question about how a flow sensor detects a leak answered with 'I have no evidence record for a previous answer in this conversation' -- the provenance lane firing on a question that is not about provenance

## 55. How many emergency fire pull stations are in your building?
*lane `capability` · 1.2 s*

> Here is what I found in **Abacws Building** documentation: **From: Fire Safety** # Fire Safety Asset Register - Abacws Building ## Evacuation procedure The procedural content of the earlier document is unchanged and still applies: 1. On hearing the fire alarm (continuous bell), **leave the building immediately** via the nearest fire exit. 2. **Do not use the lift** during a fire evacuation - use the stairs. The lift homes to ground on alarm and its doors open. 3. Assembly point: **Maindy Road car park** (north side, 50 metres from the main entrance). 4. Report to your floor warden at the assembly point. People who cannot use stairs should go to the nearest refuge point and use the communication unit; the refuge points and the personal evacuation plans are held in the evacuation and PEEPs document, not here. **Emergency contacts:** University Security (24/7) 029 2087 4444 - Emergency Services 999 - Fire Safety Officer fire.safety@example.ac.uk ## Fire safety asset register | code | name | kind | location | floor | standard | last_tested_on | next_test_due | evidence_ref | open_defect | owner | status | note | |---|---|---|---|---|---|---|---|---|---|---|---|---| | FSA-001 | Fire alarm control panel | alarm | Room 0.10 - Building Management Office | 0 | BS 5839-1 weekly test | 2026-09-09 | 2026-09-16 | FA-WK-2026-34 | | Building Fire Warden Coordinator | Overdue | Weekly test not

**LABEL: WEIRD** — 'How many emergency fire pull stations?' answered with the fire-safety evacuation PROCEDURE document, not a count. FireSafetyAsset=30 records exist.

## 56. Is the people count used to monitor employee activity?
*lane `sensor_data` · 5.4 s*

> **Floor 2 has the most people in it right now: 30**. | Floor | People now | Sensors | |---|---|---| | Floor 2 | 30 | 1 | | Floor 5 | 30 | 1 | | Floor 0 | 29 | 1 | | Floor 1 | 29 | 1 | | Floor 3 | 28 | 1 | | Floor 4 | 28 | 1 | Based on 6 occupancy sensors on 6 floors, the newest reading from each sensor in the last 60 minutes (to Thu 01 Oct 14:20, building time): each floor's figure is its counter's newest reading, added up where a floor has several. Each floor's figure is the reading of that floor's own counter; the room-level counters are not added to it, so nobody is counted twice. --- *Sources: `Building model`*

**LABEL: WEIRD** — 'Is the people count used to monitor employee activity?' is a PRIVACY question; answered with live per-floor people counts. #35 handles privacy correctly.

## 57. How does it ensure that the most important systems keep running?
*lane `capability` · 2.4 s*

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Stock item records, which I can read for you.

**LABEL: DECLINE-BAD** — 'How does it ensure the most important systems keep running?' declined; ContinuityProvision=12 records exist

## 58. in this kitchen area, how much vampire power do appliaces draw after hours?
*lane `spatial_query` · 1.6 s*

> ## Kitchen **1** space(s) found: | Floor | Zone | Label | Type | Area (m²) | |-------|------|-------|------|-----------| | 4 | `0.16` | \pxqc;{\fArial|b0|i0|c0|p34;\H1.6x;0.16\P\H0.625x;Kitchen} | kitchen | — | --- *I couldn't render the chart this time; the figures above are unchanged. Please try again, or ask for one sensor over a stated period as a line chart.*

**LABEL: WEIRD** — printed RAW AutoCAD MTEXT markup as a room label: `\pxqc;{\fArial|b0|i0|c0|p34;\H1.6x;0.16\P\H0.625x;Kitchen}`. Internal formatting codes to a reader.

## 59. is there a way to compare different areas based on comfort and usage?
*lane `capability` · 2.9 s*

> **I could not find this in Abacws Building's documents.** I searched them and none is about this question, so I have nothing grounded to answer it with. Name the record or the measurement it would be written down as and I will look there next.

**LABEL: DECLINE-OK** — whether areas can be compared on comfort and usage is not a recorded fact, though the deliberation lane arguably does this

## 60. how does indoor humidity vary across different floors?
*lane `compare` · 4.6 s*

> **Across the building humidity is averaging 54.5 %**, ranging from 51.2 to 58.7 %. | Floor | Now % | Lowest | Highest | Sensors | |---|---|---|---|---| | Floor 0 | 54.1 | 51.9 | 56.7 | 17 | | Floor 1 | 54.5 | 52.2 | 58.5 | 14 | | Floor 2 | 54.0 | 51.2 | 56.4 | 49 | | Floor 3 | 54.3 | 51.6 | 56.3 | 49 | | Floor 4 | 54.3 | 51.5 | 57.9 | 58 | | Floor 5 | 56.1 | 53.5 | 58.7 | 87 | Floor 5 is the highest of the 6 floors at 56.1 %; Floor 2 the lowest at 54.0 %. Based on 275 humidity sensors on 6 floors, the newest reading from each sensor in the last 60 minutes (to Thu 01 Oct 14:20, building time): each sensor's newest reading. 1 sensors have no recorded location and are left out of the grouping. --- **You might also ask:** Plot the comparison? | Export results? | Check for anomalies? --- *Sources: `Building model`*

**LABEL: GOOD** — humidity across floors with per-floor figures and sensor counts
