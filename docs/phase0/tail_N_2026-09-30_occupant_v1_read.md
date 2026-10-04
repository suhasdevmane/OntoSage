# Tail N — 60 unseen questions from the real survey corpus

Source: `paper/Survey analysis and results/corpus/classified_corpus.csv` — 60 distinct participants, one question each, excluding every question asked in tails C–M.
Mix: {'AGGREGATION': 7, 'LOOKUP': 52, 'MULTI_STEP': 1} against the corpus's own 88/9/3 — representative of what real people ask, and deliberately NOT comparable to tail M's harder synthesised set.

Labels: GOOD · DECLINE-OK · DECLINE-BAD · WEIRD · FABRICATED (DECLINE-BAD, WEIRD and FABRICATED all count as unacceptable).

---

## 1. what is the most unique design ?
*AGGREGATION · COMPARISON · UNSPECIFIED · Building Owners/Property Managers* — 18.4s, OK

> General knowledge (not from this building's records): The most unique design often depends on the context, but one standout example is the *Guggenheim Museum Bilbao* in Spain. Designed by Frank Gehry, its flowing titanium curves and sculptural form break conventional architectural norms, creating a dynamic, almost living structure that has become a global icon of contemporary design.

**LABEL:** 

## 2. How many restrooms are on each floor?
*AGGREGATION · STATUS · FLOOR · Guests/Visitors* — 3.7s, OK

> **8 rooms are recorded as Restroom**: - Floor 2 (2): Room 2.35, Room 2.36 - Floor 3 (2): Room 3.36, Room 3.37 - Floor 4 (2): Room 4.35, Room 4.36 - Floor 5 (2): Room 5.35, Room 5.36 _From the building's own room records._

**LABEL:** 

## 3. Are there any issues with the building that prospective tenants should know about?
*LOOKUP · CAPABILITY · BUILDING · Occupants/Tenants/Employees; Sustainability and Energy Management Teams* — 18.7s, OK

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team.

**LABEL:** 

## 4. Why is my furnace not running?
*LOOKUP · DIAGNOSTIC · UNSPECIFIED · Student/Researchers/Academics* — 22.2s, OK

> I couldn't answer that about **Furnace** from Abacws Building's records. The nearest things I can answer are the Stock item, Interval record and Timetabled session records. Ask about one of those and I will read them. **I couldn't read Abacws Building's sensor catalogue just now,** so I can't list what it measures. Ask about a particular quantity, or try again in a moment.

**LABEL:** 

## 5. if the main exit is blocked by smoke, what is the alternative route
*LOOKUP · STATUS · UNSPECIFIED · Health and Safety Officers* — 8.3s, OK

> the pedestrian door beside it (DR‑004) --- *From Abacws Building's documents: Door Hardware Register, Fire Safety. For the current version, contact facility management.*

**LABEL:** 

## 6. Could the sensors be used to monitor pollutions and then make suggestion on a safer time for there use?
*MULTI_STEP · CAPABILITY · UNSPECIFIED · Guests/Visitors* — 74.7s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Asset engineering profile, Door and shutter hardware and Hazard control records and the readings of air quality, carbon monoxide, co2 and damper position. Ask about one of those and I will read them.

**LABEL:** 

## 7. How many people are currently in this office?
*AGGREGATION · STATUS · ROOM · Occupants/Tenants/Employees* — 1.0s, OK

> Which room do you mean by "this office"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL:** 

## 8. is there a separate mailroom for large packages
*LOOKUP · CAPABILITY · UNSPECIFIED · Guests/Visitors* — 103.7s, OK

> I couldn't answer that about **Mailroom** from Abacws Building's records. The nearest things I can answer are the Interval record, Timetabled session and Access event records and the readings of air quality, carbon monoxide, co2 and damper position. Ask about one of those and I will read them.

**LABEL:** 

## 9. Does the server room keep track of who visits the room?
*LOOKUP · STATUS · ROOM · Guests/Visitors* — 32.0s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Access event, Asset engineering profile and Cleaning task records and the readings of air quality, carbon monoxide, co2 and damper position. Ask about one of those and I will read them. --- **You might also ask:** Show current readings for these sensors? | Compare zones? | Generate a report? --- *Sour

**LABEL:** 

## 10. How many people are currently inside the building?
*AGGREGATION · STATUS · BUILDING · Occupants/Tenants/Employees; Student/Researchers/Academics* — 17.8s, OK

> 🔒 This question needs the **Occupancy Sensing System**, but your role (**occupant**) doesn't have access to the **Occupancy Sensing** data source. Ask an administrator to grant your role access in the admin console.

**LABEL:** 

## 11. How does the system respond to high occupancy?
*LOOKUP · CAPABILITY · UNSPECIFIED · IT/Data Scientists; Building Owners/Property Managers* — 17.9s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Interval record, Timetabled session and Access event records and the readings of occupancy, occupancy status, air quality and carbon monoxide. Ask about one of those and I will read them.

**LABEL:** 

## 12. This room is far too hot. Where is a nearby area that I can go to cool down?
*LOOKUP · STATUS · ROOM · Guests/Visitors* — 7.7s, OK

> Which room do you mean by "this room"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL:** 

## 13. What happens if certain individuals are using too more than an average amount of energy?
*AGGREGATION · STATUS · UNSPECIFIED · Occupants/Tenants/Employees* — 59.1s, OK

> General guidance (not from this building's records): People who use more energy than the typical level can raise overall consumption, increase costs, and put extra load on the building’s systems. This can lead to higher bills and a larger environmental footprint. Facilities often track usage patterns, provide feedback, and encourage habits that reduce waste. If usage remains high, managers may rev

**LABEL:** 

## 14. Is there a parking area under the building?
*LOOKUP · CAPABILITY · BUILDING · Occupants/Tenants/Employees; Guests/Visitors* — 19.5s, OK

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Asset engineering profile and Workspace profile records, which I can read for you.

**LABEL:** 

## 15. Is this area safe?
*LOOKUP · STATUS · UNSPECIFIED · Occupants/Tenants/Employees* — 10.6s, OK

> Which room do you mean by "this area"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL:** 

## 16. What is the average sound level?
*AGGREGATION · STATUS · UNSPECIFIED · Guests/Visitors* — 20.2s, OK

> I found nothing in Abacws Building's records that answers that. --- **You might also ask:** Plot this data? | Check compliance against ASHRAE? | Compare with another zone? --- *Sources: `Building model`*

**LABEL:** 

## 17. can the building quantify the carbon saved by daylight harvesting
*LOOKUP · CAPABILITY · BUILDING · Sustainability and Energy Management Teams* — 26.6s, OK

> I couldn't tie that question to a reading I can give you, so I have no figure for it. I can answer about a room, a floor or a quantity the building measures, for example "What is the temperature in a named room right now?" or "Which floor has the most people right now?". --- *Sources: `Building model`*

**LABEL:** 

## 18. how is water safety managed to prevent legionella?
*LOOKUP · STATUS · UNSPECIFIED · Health and Safety Officers* — 17.1s, OK

> The register records four water‑system hazards (HZ‑009, HZ‑010, HZ‑011, HZ‑012) that describe how the building keeps its water safe.  The measures recorded are: | Record | Location | Control measure | Monitoring / inspection | |--------|----------|-----------------|--------------------------| | **HZ‑009** | Room 0.07 – Service Room | Hot‑water stored at 60 °C, distributed above 50 °C | Monthly te

**LABEL:** 

## 19. How much user data is needed to figure out a balanced noise level workspace?
*AGGREGATION · STATUS · UNSPECIFIED · IT/Data Scientists* — 8.6s, OK

> The workspace profile register (28 records) cannot answer this: it records group friendly, location, nearest vertical route, floor and workspace kind, and nothing about balanced, figure and user. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?

**LABEL:** 

## 20. Do you have multiple redundant lighting systems to make sure that even if there are several failures, it's safe for people to navigate the lot?
*LOOKUP · CAPABILITY · UNSPECIFIED · Guests/Visitors* — 23.4s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Door and shutter hardware, Fire safety asset and Access event records and the readings of lighting cct, air quality, carbon monoxide and co2. Ask about one of those and I will read them. --- *Sources: `Building model`*

**LABEL:** 

## 21. Is any employee food space able to be secured so people don’t steal other people’s food?
*LOOKUP · STATUS · UNSPECIFIED · Student/Researchers/Academics* — 11.5s, OK

> **I could not find this in Abacws Building's documents.** I searched them and none is about this question, so I have nothing grounded to answer it with. Name the record or the measurement it would be written down as and I will look there next.

**LABEL:** 

## 22. Is there any mold in this room?
*LOOKUP · CAPABILITY · ROOM · Guests/Visitors; Vendors/Service Providers; Student/Researchers/Academics; Facility Managers / Building Maintenance Teams; Occupants/Tenants/Employees; Sustainability and Energy Management Teams* — 3.9s, OK

> Which room do you mean by "this room"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL:** 

## 23. Has the humidity changed significantly in the past hour?
*LOOKUP · STATUS · UNSPECIFIED · Student/Researchers/Academics* — 22.0s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Operating regime, Approval and evidence record and Circulation time records and the readings of humidity, runtime hours, air quality and carbon monoxide. Ask about one of those and I will read them. --- *Sources: `Building model`*

**LABEL:** 

## 24. Can the building harvest rainwater for use in the building?
*LOOKUP · CAPABILITY · BUILDING · Guests/Visitors* — 4.4s, OK

> Here is what I found for **Abacws Building**: **Sustainability**. Abacws was designed to BREEAM 'Excellent' specification. Sustainability features: (1) High-performance building fabric with triple-glazed facades; (2) Mechanical heat recovery ventilation; (3) LED lighting with daylight harvesting throughout; (4) Electric vehicle charging points in the car park; (5) Green roof on the second-floor t

**LABEL:** 

## 25. do the entry and exit logs reconcile for a roll call right now?
*LOOKUP · STATUS · UNSPECIFIED · Health and Safety Officers* — 44.7s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Access event, Asset engineering profile and Emergency coordination function records and the readings of air quality, carbon monoxide, co2 and damper position. Ask about one of those and I will read them. --- **You might also ask:** Show current readings for these sensors? | Compare zones? | Generate a

**LABEL:** 

## 26. can i see how air circulation differs between rooms on this floor?
*LOOKUP · CAPABILITY · FLOOR · Student/Researchers/Academics* — 57.8s, OK

> I couldn't tie that question to a reading I can give you, so I have no figure for it. I can answer about a room, a floor or a quantity the building measures, for example "What is the temperature in a named room right now?" or "Which floor has the most people right now?". --- *Sources: `Building model`*

**LABEL:** 

## 27. how can the building optimise energy use during weekends and holidays?
*LOOKUP · STATUS · BUILDING · Sustainability and Energy Management Teams* — 22.2s, OK

> General guidance (not from this building's records): Buildings can lower energy use on weekends and holidays by turning down heating or cooling when spaces are empty, dimming lights, and using occupancy sensors to control equipment. Scheduling HVAC and lighting to match expected use reduces waste. Automating these settings through a building management system keeps comfort while saving power. Chec

**LABEL:** 

## 28. does the building sound feel good
*LOOKUP · CAPABILITY · BUILDING · Facility Managers / Building Maintenance Teams* — 48.9s, OK

> **Across the building sound is averaging 56.2**, ranging from 52.9 to 59.4. | Floor | Now | Lowest | Highest | Sensors | |---|---|---|---|---| | Floor 0 | 55.6 | 53.6 | 57.7 | 17 | | Floor 1 | 56.2 | 54.5 | 58.1 | 13 | | Floor 2 | 56.4 | 53.8 | 59.4 | 49 | | Floor 3 | 56.6 | 54 | 58.6 | 49 | | Floor 4 | 56.3 | 53.3 | 58.9 | 52 | | Floor 5 | 56.3 | 52.9 | 59.3 | 53 | Floor 3 is the highest of the

**LABEL:** 

## 29. What type of internal lights are used and could altering the light colors slightly help with glare and visibility?
*LOOKUP · STATUS · UNSPECIFIED · Guests/Visitors* — 18.0s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Fire safety asset, Workspace profile and Department records and the readings of lighting cct, air quality, carbon monoxide and co2. Ask about one of those and I will read them. --- *Sources: `Building model`*

**LABEL:** 

## 30. Can you tell me which areas are currently overcrowded?
*LOOKUP · CAPABILITY · UNSPECIFIED · Student/Researchers/Academics* — 21.6s, OK

> ## Explain how overcrowded areas are identified. a step of this request could not be carried out --- ## Spatial Information ## All spaces **354** space(s) found: | Floor | Zone | Label | Type | Area (m²) | |-------|------|-------|------|-----------| | 0 | `0.01` | 0.01 | zone | 184.5 | | 0 | `0.04` | 0.04 | zone | 69.3 | | 0 | `0.05` | 0.05 | zone | 10.2 | | 0 | `0.06` | 0.06 | zone | 6.2 |

**LABEL:** 

## 31. Are all emergency exit clear
*LOOKUP · STATUS · UNSPECIFIED · Building Owners/Property Managers; IT/Data Scientists; Real Estate Developers* — 9.3s, OK

> I did not find any answer in the records I searched. The closest this building keeps is the building's record of Fire Exit - Ground Floor North, which I can read for you. That is a statement about the documents, not about the building — if you can name the record or the measurement this would be written down as, I will look there next.

**LABEL:** 

## 32. Could the humidity detection be tied in with the water sensors to more accurately tell if there are water/leakage issues?
*LOOKUP · CAPABILITY · UNSPECIFIED · Guests/Visitors* — 24.8s, OK

> The register records six fire‑alarm‑zone assets that are classified as **detection**: - **FSA‑002** – Fire alarm zone, Ground floor (active) - **FSA‑003** – Fire alarm zone, Level 1 (active) - **FSA‑004** – Fire alarm zone, Level 2 (active) - **FSA‑005** – Fire alarm zone, Level 3 (defective) – two detectors report low signal - **FSA‑006** – Fire alarm zone, Level 4 (active) - **FSA‑007

**LABEL:** 

## 33. did you go to college?
*LOOKUP · STATUS · UNSPECIFIED · Guests/Visitors* — 122.9s, OK

> I'm **OntoSage** — a building-agnostic framework for asking a building questions in plain English. I'm not built for any one site: I work from a building's own description of itself and the readings from its sensors, and answer questions about it. Connecting a different building is a matter of setup, with no code changes. I'm meant for whoever needs to ask: facility managers, occupants, researche

**LABEL:** 

## 34. can the building flag any life-safety system that is overdue a test?
*LOOKUP · CAPABILITY · BUILDING · Health and Safety Officers* — 12.7s, OK

> **3 compliance item(s) overdue**: - **Legionella flushing of infrequently used outlets** — due 23 Sep 2026 (responsible: facility_manager) - **Fire alarm weekly call-point test** — due 23 Sep 2026 (responsible: facility_manager) - **Hot/cold water temperature monitoring** — due 29 Sep 2026 (responsible: maintenance)

**LABEL:** 

## 35. how can the building optimise energy use during weekends and holidays?
*LOOKUP · STATUS · BUILDING · Sustainability and Energy Management Teams* — 8.5s, OK

> General guidance (not from this building's records): During weekends and holidays, a building can lower energy use by adjusting temperature setpoints to a more relaxed range when fewer occupants are present. Turning off or dimming lights in unoccupied spaces reduces lighting load. Equipment that is not needed can be shut down or set to standby. Using programmable controls that detect occupancy or

**LABEL:** 

## 36. Is there a lock on office doors?
*LOOKUP · CAPABILITY · ROOM · Guests/Visitors* — 18.9s, OK

> **Abacws Building's documents do not answer this.** I searched Door Hardware Register; they are the closest material and none of them contains the answer. That is a statement about the documents, not about the building — if you can name the record or the measurement this would be written down as, I will look there next.

**LABEL:** 

## 37. Safety is a major concern. How will people be screened and kept from entering the building? Will there by a connection to local police?
*LOOKUP · STATUS · BUILDING · Occupants/Tenants/Employees* — 9.8s, OK

> **I could not find this in Abacws Building's documents.** I searched them and none is about this question, so I have nothing grounded to answer it with. Name the record or the measurement it would be written down as and I will look there next.

**LABEL:** 

## 38. Can you monitor energy usage in this area?
*LOOKUP · CAPABILITY · UNSPECIFIED · Student/Researchers/Academics* — 1.2s, OK

> Which room do you mean by "this area"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL:** 

## 39. How long does it take when the smart systems are down for them to come back online?
*LOOKUP · STATUS · UNSPECIFIED · Guests/Visitors* — 5.1s, OK

> The circulation time register (21 records) cannot answer this: it records from floor, nearest vertical route and to floor, and nothing about online, smart and systems. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?

**LABEL:** 

## 40. can you call for a repairman?
*LOOKUP · CAPABILITY · UNSPECIFIED · Guests/Visitors* — 163.7s, OK

> I’m sorry, but the building’s records do not contain any information about a repair‑man service or a way to request one directly. If you need maintenance assistance, please contact the building’s **facility management** or **maintenance desk**. They can arrange for a repairman to visit. --- **You might also ask:** Show current readings for these sensors? | Compare zones? | Generate a report? -

**LABEL:** 

## 41. is glare hight right now
*LOOKUP · STATUS · UNSPECIFIED · Facility Managers / Building Maintenance Teams; Building Owners/Property Managers* — 228.7s, OK

> The latest illuminance reading (the most recent snapshot) is from the **Illuminance Sensor installed‑node 5.17** at **2026‑09‑30 17:46:11**. - Value: **785** (unit not recorded). - For this sensor the recorded range during the 30 Sep 17:16 – 17:46 window is 747 – 835, with an average of 786. - The current value is very close to the average and well below the maximum, so glare is **not high**

**LABEL:** 

## 42. is there any unusual odor detected in this area?
*LOOKUP · CAPABILITY · UNSPECIFIED · Student/Researchers/Academics* — 1.8s, OK

> Which room do you mean by "this area"? I cannot tell which one you are in, and answering about a different one would look right and be wrong. Give me its number or name — or name the floor and I will narrow it down.

**LABEL:** 

## 43. What is the return air temperature?
*LOOKUP · STATUS · UNSPECIFIED · Occupants/Tenants/Employees* — 31.1s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Waste return, Asset status record and Interval record records and the readings of return air temperature, supply air temperature, air quality and entering water temperature. Ask about one of those and I will read them. --- *Sources: `Building model`*

**LABEL:** 

## 44. Is there anything on the roof like a patio or pool?
*LOOKUP · CAPABILITY · UNSPECIFIED · Occupants/Tenants/Employees; Guests/Visitors* — 41.1s, OK

> I couldn't answer that about **Roof** from Abacws Building's records. The nearest things I can answer are the Stock item, Permit to work and Interval record records and the readings of air quality, carbon monoxide, co2 and damper position. Ask about one of those and I will read them.

**LABEL:** 

## 45. how is water consumption montored here?
*LOOKUP · STATUS · UNSPECIFIED · Sustainability and Energy Management Teams* — 64.4s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Hazard control, Interval record and Timetabled session records and the readings of entering water temperature, leaving water temperature, water flow and water flow chilled. Ask about one of those and I will read them. --- **You might also ask:** Plot this data? | Check compliance against ASHRAE? | Comp

**LABEL:** 

## 46. are there any spaces reserved but not currently in use?
*LOOKUP · CAPABILITY · UNSPECIFIED · Student/Researchers/Academics* — 55.3s, OK

> Yes – the register shows 16 booking records, all of which are scheduled for dates in August or September 2026. Because today is 30 September 2026 17:49, every booking is in the past, so every room that has a booking record is currently **not in use**. **Room 5.15 – Seminar / Conference Room** • BK‑2026‑0001 – confirmed, 24 Aug 2026 09:00‑11:00 • BK‑2026‑0007 – confirmed, 31 Aug 2026 09:00

**LABEL:** 

## 47. Which rooms are best suited for video calls right now?
*LOOKUP · STATUS · UNSPECIFIED · Student/Researchers/Academics* — 104.9s, OK

> **Best match: Room 2.10 — Academic Office** (floor Floor2, score 0.7488 out of 1, where 1 fits everything you asked for). 1. **Room 2.10 — Academic Office** — score 0.7488 (illuminance: 769.846, noise: 56.487, occupancy: 24.8, temperature: 23.014) 2. **Room 4.24 — Academic Office** — score 0.7465 (illuminance: 777.769, noise: 55.2, occupancy: 24.2, temperature: 23.042) 3. **Room 2.01 — Research La

**LABEL:** 

## 48. Can you provide me with some interesting tidbits about the house?
*LOOKUP · CAPABILITY · UNSPECIFIED · Sustainability and Energy Management Teams; IT/Data Scientists; Student/Researchers/Academics* — 74.6s, OK

> I found **8 sensors** that give a quick snapshot of how the building is instrumented: **Floor 0 (Ground Floor)** - PIR Lighting Detector - Lift Vibration Sensor **Floor 1** - PIR Lighting Detector **Floor 2** - PIR Lighting Detector **Floor 3** - PIR Lighting Detector **Floor 4** - PIR Lighting Detector **Floor 5** - PIR Lighting Detector - Noise Level Sensor **Take‑away tid

**LABEL:** 

## 49. are EV chargers powered by clean energy?
*LOOKUP · STATUS · UNSPECIFIED · Sustainability and Energy Management Teams* — 24.9s, OK

> The cleaning task register (30 records) cannot answer this: it records cleaning zone, location, service frequency and shift name, and nothing about chargers, energy and powered. --- **You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?

**LABEL:** 

## 50. are there alerts for unusual energy patterns or wastage?
*LOOKUP · CAPABILITY · UNSPECIFIED · Student/Researchers/Academics* — 5.6s, OK

> This building does measure **energy trend** (26 sensor point(s)), so you can ask me for its current value or its recent history at any time. No notification channel is set up for this building, so I can't send you an automatic alert. **What I cannot do yet (physical actuation):** - Automatically change a physical system (e.g. open a valve, adjust a thermostat setpoint) — that needs a building-co

**LABEL:** 

## 51. Are you the only building that can talk around here?
*LOOKUP · STATUS · UNSPECIFIED · Guests/Visitors* — 15.0s, OK

> The register records two “talk” activities that take place in this building: - **Course talk – Computer Science** (ACT‑0042‑2) - **Student accommodation talk** (ACT‑0042‑8) So, within the 24 event‑activity records held for this building, there are exactly two talks. The register does not contain any information about other buildings or whether they can hold talks. Therefore, it cannot confirm

**LABEL:** 

## 52. Can the building remind me to adjust lighting?
*LOOKUP · CAPABILITY · BUILDING · Occupants/Tenants/Employees* — 17.7s, OK

> I couldn't answer that from Abacws Building's records. The nearest things I can answer are the Fire safety asset, Interval record and Timetabled session records and the readings of lighting cct, air quality, carbon monoxide and co2. Ask about one of those and I will read them. --- *Sources: `Building model`*

**LABEL:** 

## 53. is the power factor normal or inefficient?
*LOOKUP · STATUS · UNSPECIFIED · Occupants/Tenants/Employees; Student/Researchers/Academics* — 26.9s, OK

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Door and shutter hardware and Operating regime records, which I can read for you.

**LABEL:** 

## 54. can you promote eco friendly operations?
*LOOKUP · CAPABILITY · UNSPECIFIED · Student/Researchers/Academics* — 6.3s, OK

> I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact your building's facilities / estates management team. Abacws Building does keep Asset status record, Accessible route and Service continuity provision records, which I can read for you.

**LABEL:** 

## 55. different types of buildings you can build
*LOOKUP · STATUS · UNSPECIFIED · Facility Managers / Building Maintenance Teams* — 10.1s, OK

> Here is what I found for **Abacws Building**: **Building access hours**. Card-holders can access Abacws 07:00-22:00 on weekdays and 08:00-18:00 at weekends; reception is staffed Mon-Fri 09:00-16:30 only. **Building management and contacts**. Abacws is managed by Cardiff University Estates and Facilities Management; the School of Computer Science admin is on Floor 2. Report to: Estates and Facil

**LABEL:** 

## 56. How does an increase in Relative Humidity affect the perceived Temperature (Heat Index) in a room?
*LOOKUP · STATUS · ROOM · IT/Data Scientists* — 20.7s, OK

> General guidance (not from this building's records): An increase in relative humidity makes the air feel warmer than the actual temperature. Moist air reduces the body’s ability to cool itself by evaporation, so the perceived temperature rises. This effect is captured by the heat index, which rises as humidity climbs. For exact values, refer to the building’s own data. For this building's own rea

**LABEL:** 

## 57. Whats the buildings current power factor?
*LOOKUP · STATUS · UNSPECIFIED · Guests/Visitors* — 54.9s, OK

> Because no power‑factor readings are available in the records, I can’t give you a current value for the building’s power factor. _At least one sensor returned the full 60 rows this question reads per sensor, so these readings are a SAMPLE of the newest data and their number is not a count of what the period holds. The readings used run from 2026-09-30 01:06:37 to 2026-09-30 16:42:56. That is the

**LABEL:** 

## 58. if the weather forecast shows a cold snap, how should pre-heating be scheduled
*LOOKUP · STATUS · UNSPECIFIED · Sustainability and Energy Management Teams* — 19.3s, OK

> **I don't hold a weather forecast.** Abacws Building's outdoor sensors report what the weather is doing now — outdoor temperature, outdoor humidity, wind speed and solar irradiance — not what it will do tomorrow. Ask for one of those, for example *"what is the outside temperature?"*, and I will answer from its latest reading.

**LABEL:** 

## 59. how often do you check for safety issues ?
*LOOKUP · STATUS · UNSPECIFIED · Occupants/Tenants/Employees* — 25.1s, OK

> I searched the building's **compliance register** (82 checks). It records, for each check, what it is, when it is next due, when it was last completed and which role is responsible — and nothing else, so it cannot answer what this question asks. Tell me which of those you need, or which register or system holds the rest, and I will read it.

**LABEL:** 

## 60. What is the VOC level
*LOOKUP · STATUS · UNSPECIFIED · Guests/Visitors; Occupants/Tenants/Employees* — 19.0s, OK

> If you need VOC information, you’ll need to query the specific VOC sensors that are installed in the building. --- *Sources: `Building model`*

**LABEL:** 
