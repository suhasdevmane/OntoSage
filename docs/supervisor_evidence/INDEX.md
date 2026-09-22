# Evidence pack — the system answering, one screenshot per question

Captured 2026-09-21 against the running stack through Open WebUI (`ontobot-pipeline`), signed in as `facility01` — a facility-manager account, not an administrator, so nothing here is admin-only output.

Each question was asked in a **fresh chat** with both answer caches flushed beforehand, so every answer is a first pass and none was served from cache. The screenshots are full-page captures of the real browser; the answer text below each row is what the page showed.

**26 of 26 captured completely. Every answer was then read against what the question asked: 24 answer it, 2 do not.** Median answer time 56 s (slowest 203 s).

> Read this with `docs/SUPERVISOR_BRIEF.md`. Two things are deliberate. The pack includes
> the questions the system **declines**, because declining what it cannot ground is the
> behaviour being claimed and a pack of successes alone would not evidence it. And it
> includes the answers that came out **wrong**, with what is wrong with each: a pack that
> showed only the good ones would not be evidence, it would be advertising.

**Read these before the rest:**

- **24. Will the CO2 in room 5.01 exceed 1000 ppm tomorrow afternoon?** — WEAK. Declines rather than guessing, which is right, but the reason reaches the reader as internal jargon ('too_sparse_after_resample') instead of plain words.
- **25. Where is the nearest defibrillator?** — FLAGGED. States defibrillator positions and an emergency number as fact. The record behind it says the positions are 'modelled'. Safety-critical, so it must not be relied on until the owner confirms the three positions. Logged as BUG-858 (P1).

## Contents

| # | shape | question | verdict | time | screenshot |
|---|---|---|---|---|---|
| 1 | A room or floor, and a quantity | What is the CO2 level in room 5.01 right now? | answers it | 30 s | [view](screenshots/01_what-is-the-co2-level-in-room-5-01-right-now.png) |
| 2 | A room or floor, and a quantity | Which floor is the warmest right now? | answers it | 93 s | [view](screenshots/02_which-floor-is-the-warmest-right-now.png) |
| 3 | A room or floor, and a quantity | What is the average CO2 on each floor right now? | answers it | 162 s | [view](screenshots/03_what-is-the-average-co2-on-each-floor-right-now.png) |
| 4 | A comparison | Which floor used the most energy yesterday? | answers it | 203 s | [view](screenshots/04_which-floor-used-the-most-energy-yesterday.png) |
| 5 | A comparison | Where's the coolest place to work in the building right now? | answers it | 52 s | [view](screenshots/05_where-s-the-coolest-place-to-work-in-the-buildin.png) |
| 6 | A register, by record id | Which permits are open? | answers it | 38 s | [view](screenshots/06_which-permits-are-open.png) |
| 7 | A register, by record id | When was the CO2 sensor in Room 5.01 last calibrated? | answers it | 40 s | [view](screenshots/07_when-was-the-co2-sensor-in-room-5-01-last-calibr.png) |
| 8 | A register, by record id | Which shutters or doors fail open versus fail locked on power loss? | answers it | 61 s | [view](screenshots/08_which-shutters-or-doors-fail-open-versus-fail-lo.png) |
| 9 | Which ... are overdue / open / have no ... | How many open work orders are there, and which are overdue? | answers it | 45 s | [view](screenshots/09_how-many-open-work-orders-are-there-and-which-ar.png) |
| 10 | Which ... are overdue / open / have no ... | Which hazard controls are overdue for test? | answers it | 8 s | [view](screenshots/10_which-hazard-controls-are-overdue-for-test.png) |
| 11 | Which ... are overdue / open / have no ... | Which fire safety assets are overdue or cannot be evidenced? | answers it | 57 s | [view](screenshots/11_which-fire-safety-assets-are-overdue-or-cannot-b.png) |
| 12 | Which ... are overdue / open / have no ... | How many sensors are overdue for calibration? | answers it | 57 s | [view](screenshots/12_how-many-sensors-are-overdue-for-calibration.png) |
| 13 | Where something is | What is the nearest accessible toilet to room 3.10? | answers it | 26 s | [view](screenshots/13_what-is-the-nearest-accessible-toilet-to-room-3-.png) |
| 14 | Where something is | Show me floor 3 | answers it | 105 s | [view](screenshots/14_show-me-floor-3.png) |
| 15 | Where something is | Is tap water free somewhere, or do I have to buy bottles? | answers it | 12 s | [view](screenshots/15_is-tap-water-free-somewhere-or-do-i-have-to-buy-.png) |
| 16 | Is a room ready or free | Is Room 1.06 ready for my class? | answers it | 56 s | [view](screenshots/16_is-room-1-06-ready-for-my-class.png) |
| 17 | Is a room ready or free | Is Room1.06 free for the next two hours? | answers it | 117 s | [view](screenshots/17_is-room1-06-free-for-the-next-two-hours.png) |
| 18 | Asset state | Is the lift working? | answers it | 162 s | [view](screenshots/18_is-the-lift-working.png) |
| 19 | What the building is | What is this building and who runs it? | answers it | 20 s | [view](screenshots/19_what-is-this-building-and-who-runs-it.png) |
| 20 | Something the building does not measure | What is the radiation level in the atrium? | answers it | 67 s | [view](screenshots/20_what-is-the-radiation-level-in-the-atrium.png) |
| 21 | A fault report | The toilet on floor 2 is leaking. | answers it | 44 s | [view](screenshots/21_the-toilet-on-floor-2-is-leaking.png) |
| 22 | A suggestion | Suggestion: add more bike racks near the main entrance. | answers it | 22 s | [view](screenshots/22_suggestion-add-more-bike-racks-near-the-main-ent.png) |
| 23 | Refused by design — a person | Where was John Smith in the building yesterday? | answers it | 38 s | [view](screenshots/23_where-was-john-smith-in-the-building-yesterday.png) |
| 24 | Declined — a prediction | Will the CO2 in room 5.01 exceed 1000 ppm tomorrow afternoon? | **does not answer it** | 123 s | [view](screenshots/24_will-the-co2-in-room-5-01-exceed-1000-ppm-tomorr.png) |
| 25 | Declined — a safety fact nobody recorded | Where is the nearest defibrillator? | **do not rely on** | 8 s | [view](screenshots/25_where-is-the-nearest-defibrillator.png) |
| 26 | Is a room ready or free | Is Room 2.15 free this morning? | answers it | 81 s | [view](screenshots/26_is-room-2-15-free-this-morning.png) |

---

## The answers

### 1. What is the CO2 level in room 5.01 right now?

*Shape: A room or floor, and a quantity · 30 s · screenshot: [`01_what-is-the-co2-level-in-room-5-01-right-now.png`](screenshots/01_what-is-the-co2-level-in-room-5-01-right-now.png)*

**Verdict: GOOD.** Live reading with its timestamp, plus the range over the last 60 records.

> Pipeline steps Served at 5-second resolution — this building's access policy sets the finest detail available to you for data this recent. The figures below are averages over each interval, not instantaneous readings. The latest reading from the CO₂ Level Sensor installed‑node 5.01 is 1015 ppm (at 2026‑09‑21 16:38:10). Across all 60 records taken between 21 Sep 16:08 and 21 Sep 16:38, the CO₂ level averages 1,026 ppm, with a low of 995 ppm (at 21 Sep 16:23) and a high of 1,052 ppm (at 21 Sep 16:31). Spatial basis: a served zone links these spaces, but the link is not validated Sources: Building model Live Sensor Data

### 2. Which floor is the warmest right now?

*Shape: A room or floor, and a quantity · 93 s · screenshot: [`02_which-floor-is-the-warmest-right-now.png`](screenshots/02_which-floor-is-the-warmest-right-now.png)*

**Verdict: GOOD.** Names the floor, the mean, the spread and the runners-up.

> Pipeline steps Floor 5 is the warmest, with a mean temperature of 23.8 °C. Across the six floors, the mean temperatures range from 23.2 °C on Floor 1 to 23.8 °C on Floor 5, a spread of 0.6 °C. Floor 5 also has the widest range, 22 °C to 25.1 °C, compared with the narrowest range of 22.0 °C to 24.3 °C on Floor 1. Floors 0, 2, and 3 each average 23.4 °C, while Floor 4 averages 23.3 °C. Thus, Floor 5 is the warmest floor. You might also ask: Plot the comparison? | Export results? | Check for anomalies? Sources: Building model Sensor data Temperature Sensing System Live Sensor Data Analytics Engine

### 3. What is the average CO2 on each floor right now?

*Shape: A room or floor, and a quantity · 162 s · screenshot: [`03_what-is-the-average-co2-on-each-floor-right-now.png`](screenshots/03_what-is-the-average-co2-on-each-floor-right-now.png)*

**Verdict: GOOD.** All six floors, highest and lowest identified.

> Pipeline steps Floor 5 has the highest average CO₂ concentration at 1,032 ppm. Across the six floors, the averages range from 835 ppm on Floor 0 to 1,032 ppm on Floor 5, a spread of 197 ppm. Floor 1 averages 840 ppm, Floor 2 837 ppm, Floor 3 836 ppm, and Floor 4 856 ppm, all well below the peak on Floor 5. The lowest average is 835 ppm on Floor 0, with the next lowest at 836 ppm on Floor 3. Thus, Floor 5’s average CO₂ concentration of 1,032 ppm is the highest among all floors. You might also ask: Plot this data? | Check compliance against ASHRAE? | Compare with another zone? Sources: Building model Sensor data CO2 Sensing System Indoor Air Quality System Live Sensor Data Analytics Engine

### 4. Which floor used the most energy yesterday?

*Shape: A comparison · 203 s · screenshot: [`04_which-floor-used-the-most-energy-yesterday.png`](screenshots/04_which-floor-used-the-most-energy-yesterday.png)*

**Verdict: GOOD.** Totals per floor and it names the six meters it summed.

> Pipeline steps Floor 3 used the most energy yesterday, with a total of 86.9 kWh. The next highest was Floor 4 at 84.5 kWh, followed by Floor 5 at 82.6 kWh. The lowest consumption was Floor 1, recording 76.2 kWh, while Floor 0 and Floor 2 logged 78.2 kWh and 79.3 kWh, respectively. The spread between the highest and lowest floors is 10.7 kWh. Floor 3 used the most energy yesterday, with a total of 86.9 kWh. Boundary: summed across 6 meters (Energy_Meter_Floor0, Energy_Meter_Floor1, Energy_Meter_Floor2, Energy_Meter_Floor3, Energy_Meter_Floor4, Energy_Meter_Floor5), covering Floor 0 (Ground Floor), Floor 1 (First Floor), Floor 2 (Second Floor), Floor 3 (Third Floor), Floor 4 (Fourth Floor), Floor 5 (Fifth Floor). The total is the sum of those boundaries — it is not a separate whole-site reading. You might also ask: Plot the comparison? | Export results? | Check for anomalies? Sources: Buil …

### 5. Where's the coolest place to work in the building right now?

*Shape: A comparison · 52 s · screenshot: [`05_where-s-the-coolest-place-to-work-in-the-buildin.png`](screenshots/05_where-s-the-coolest-place-to-work-in-the-buildin.png)*

**Verdict: GOOD.** Now ranks rooms by live temperature and states how it read the question: "'coolest place to work' scored as minimize temperature against the 20-26 band". 'coolest' was in no lay-term list, so no measurand resolved and the workspace register answered instead; the model now resolves the word against this building's own concepts, and a resolved measurand takes a live superlative off a register lane. BUG-860 fixed.

> Pipeline steps Best match: Room 5.15 — Seminar / Conference Room (floor Floor5, score 0.7208 out of 1, where 1 fits everything you asked for). Room 5.15 — Seminar / Conference Room — score 0.7208 (temperature: 21.675) Room 5.11 — Academic Office — score 0.7158 (temperature: 21.705) Room 5.51 — Research Laboratory — score 0.7093 (temperature: 21.744) Assumptions: 'coolest place to work' scored as minimize temperature against the 20-26 band; all stated preferences weighted equally. Coverage: 195 of 234 spaces considered; temperature: 195/195 instrumented; 39 excluded (listed). Privacy: computed under this building's access rules for your role, which limit how finely individual readings can be shown. The top choice is stable under ±25% preference-weight changes. How I worked this out (evidence dossier) As measured at 22:33 on 21 Sep, 3 minutes ago. Recheck by 22:48 (15 minutes of useful lif …

### 6. Which permits are open?

*Shape: A register, by record id · 38 s · screenshot: [`06_which-permits-are-open.png`](screenshots/06_which-permits-are-open.png)*

**Verdict: GOOD.** 3 of 15 records, each with its id, permit kind and provider.

> Pipeline steps 3 of the 15 records in the Permit to work register match (recorded status: open): PTW-2026-0416 — permit kind: Confined space; provider name: Severn Water Hygiene PTW-2026-0417 — permit kind: Roof access; provider name: Caldicot Plant Services PTW-2026-0418 — permit kind: Hot works; provider name: Meridian Mechanical Ltd You might also ask: Who owns these records? | Which of these are on floor 3? | Show the full register?

### 7. When was the CO2 sensor in Room 5.01 last calibrated?

*Shape: A register, by record id · 40 s · screenshot: [`07_when-was-the-co2-sensor-in-room-5-01-last-calibr.png`](screenshots/07_when-was-the-co2-sensor-in-room-5-01-last-calibr.png)*

**Verdict: GOOD.** Gives the date and distinguishes the room sensor from the general air-quality sensor.

> Pipeline steps The CO₂ sensor that is specifically installed in Room 5.01 was last calibrated on 27 May 2026. The room‑specific sensor is named Room5.01_sat_co2 and its calibrated on date is 2026‑05‑27. For reference, there is also an Air_CO2_Level_Sensor_5.01 (a general air‑quality sensor) that was calibrated on 17 November 2025. You might also ask: Show current readings for these sensors? | Compare zones? | Generate a report? Sources: Building model

### 8. Which shutters or doors fail open versus fail locked on power loss?

*Shape: A register, by record id · 61 s · screenshot: [`08_which-shutters-or-doors-fail-open-versus-fail-lo.png`](screenshots/08_which-shutters-or-doors-fail-open-versus-fail-lo.png)*

**Verdict: GOOD.** Splits fail-open from fail-locked with the device ids behind each.

> Pipeline steps Fail‑state on power loss FAIL‑STATE DOORS / SHUTTERS THAT HAVE IT RECORD IDS Fail open 2 devices – a reception turnstile and a car‑park vehicle barrier DR‑012, DR‑013 Fail locked 5 devices – three security doors (server room, communications room, mechanical plant room) and two other security doors (basement tank room, bike store) DR‑006, DR‑007, DR‑008, DR‑015, DR‑016 There are 16 shutter/door records in total. 2 of them are set to stay open when power is lost, and 5 are set to stay locked. What the register does not record The register does not contain a direct comparison or “versus” statement between the two fail‑states. It only records the individual fail‑state for each device. You might also ask: Who owns these records? | Which of these are on floor 3? | Show the full register?

### 9. How many open work orders are there, and which are overdue?

*Shape: Which ... are overdue / open / have no ... · 45 s · screenshot: [`09_how-many-open-work-orders-are-there-and-which-ar.png`](screenshots/09_how-many-open-work-orders-are-there-and-which-ar.png)*

**Verdict: GOOD.** Lists the 9 open records AND states plainly that the register holds no due date, so 'overdue' cannot be derived from it. Refusing the second half of the question is the right answer.

> Pipeline steps 9 of the 24 records in the Work order register match (recorded status: in progress or open — 6 in progress, 3 open): WO-001 — Fault investigation — status: in progress WO-008 — Electrical inspection — status: open WO-010 — Thermographic survey — status: in progress WO-011 — Annual service — status: in progress WO-012 — Torque check on terminations — status: in progress WO-013 — Insulation resistance test — status: open WO-015 — Condensate drain clearance — status: open WO-021 — Vibration check — status: in progress WO-022 — Annual service — status: in progress The Work order register records no due date and no 'overdue' status, so which of its records are overdue cannot be worked out from it. It does record 9 of 24 as not complete (WO-001, WO-008, WO-010, WO-011, WO-012, WO-013, WO-015, WO-021 and WO-022); that is not the same thing as overdue. You might also ask: Who owns …

### 10. Which hazard controls are overdue for test?

*Shape: Which ... are overdue / open / have no ... · 8 s · screenshot: [`10_which-hazard-controls-are-overdue-for-test.png`](screenshots/10_which-hazard-controls-are-overdue-for-test.png)*

**Verdict: GOOD.** Both overdue controls with their due dates, as at today.

> Pipeline steps 2 of the 12 records in the Hazard control register are overdue (as at 21 September 2026): HZ-003 — Fume cupboard FC-301 — due 12 August 2026; recorded as overdue HZ-010 — Little-used outlets, Level 5 washrooms — due 11 September 2026; recorded as overdue You might also ask: Who owns these records? | Which of these are on floor 3? | Show the full register?

### 11. Which fire safety assets are overdue or cannot be evidenced?

*Shape: Which ... are overdue / open / have no ... · 57 s · screenshot: [`11_which-fire-safety-assets-are-overdue-or-cannot-b.png`](screenshots/11_which-fire-safety-assets-are-overdue-or-cannot-b.png)*

**Verdict: GOOD.** Breaks 30 assets into active/defective/overdue and separates 'cannot be evidenced'.

> Pipeline steps There are 30 fire‑safety assets recorded for the building. The register shows: Active 24 assets Defective 4 assets (FSA‑005, FSA‑008, FSA‑018, FSA‑021) Overdue 2 assets (FSA‑001, FSA‑027) Assets that are overdue ASSET DESCRIPTION LOCATION DUE DATE EVIDENCE REFERENCE FSA‑001 Fire alarm control panel Room 0.10 – Building Management Office 16 Sep 2026 FA‑WK‑2026‑34 FSA‑027 Dry riser – main lift core Main lift core 05 May 2026 none recorded Assets that cannot be evidenced Only one asset has no evidence reference recorded: FSA‑027 – Dry riser – main lift core (no evidence reference) No other assets in the register lack an evidence reference, and no other assets are marked as overdue. You might also ask: Who owns these records? | Which of these are on floor 3? | Show the full register?

### 12. How many sensors are overdue for calibration?

*Shape: Which ... are overdue / open / have no ... · 57 s · screenshot: [`12_how-many-sensors-are-overdue-for-calibration.png`](screenshots/12_how-many-sensors-are-overdue-for-calibration.png)*

**Verdict: GOOD.** Gives the count and the denominator it came from.

> Pipeline steps There are 237 sensors that are overdue for calibration. Context The building model records 2,727 sensors that have a declared sampling or archival interval. Of those, 1,929 sensors have a calibration regime defined. Within that group, 237 sensors are currently overdue for calibration. If you’d like to see which specific sensors are overdue or need a plan for re‑calibration, let me know! You might also ask: Show current readings for these sensors? | Compare zones? | Generate a report? Sources: Building model

### 13. What is the nearest accessible toilet to room 3.10?

*Shape: Where something is · 26 s · screenshot: [`13_what-is-the-nearest-accessible-toilet-to-room-3-.png`](screenshots/13_what-is-the-nearest-accessible-toilet-to-room-3-.png)*

**Verdict: GOOD.** Now answers from the same floor. The earlier capture sent a wheelchair user one floor up because only two accessible WCs were recorded for the whole building; the surveyed provision (two per floor, every floor) is now in the graph.

> Pipeline steps The accessible toilet nearest 3.10 is on the same floor: Accessible gender-neutral toilet — Floor 3 (one end). Also recorded: Accessible gender-neutral toilet — Floor 3 (other end), Accessible gender-neutral toilet — Floor 2 (one end), Accessible gender-neutral toilet — Floor 2 (other end), Accessible gender-neutral toilet — Floor 4 (one end). From the building's amenity catalogue, measured in floors — not a surveyed route. It does not account for walking distance, door types or whether the lift is in service.

### 14. Show me floor 3

*Shape: Where something is · 105 s · screenshot: [`14_show-me-floor-3.png`](screenshots/14_show-me-floor-3.png)*

**Verdict: GOOD.** Plan plus the spaces on the floor, grouped by kind.

> Pipeline steps 🏢 Abacws — Floor 3 📄 Open Floor 3 Plan (PDF) I've pulled up the floor plan for Floor 3. Use the plan above to locate the room or zone you're interested in. Spaces on this floor: Lab: 10P Collab Sp, 3Z01 10P Collab Sp 3Z01 Meeting Room: 3.01, 3.46, 3.15, 3.02 Office: 3.08, 3.05, 3.04, 3.66, 3.64, 3.63 Sensor zones: 3.11, 3.09, 3Z004, 3.06, 3.03, 3.71, 3.70, 3.67, 3Z018, 3.61, 3.56, 3.58 … (+33 more) 💬 Which zone or room would you like sensor data for? (e.g. "zone 3.12" or "the meeting room")

### 15. Is tap water free somewhere, or do I have to buy bottles?

*Shape: Where something is · 12 s · screenshot: [`15_is-tap-water-free-somewhere-or-do-i-have-to-buy-.png`](screenshots/15_is-tap-water-free-somewhere-or-do-i-have-to-buy-.png)*

**Verdict: GOOD.** Lists the free bottle-filling stations, two per floor. The earlier capture named single placeholder points that had been dropped into arbitrary rooms.

> Pipeline steps Here is what I found for Abacws Building: Bottle-filling station — Floor 0 (one end) — Free bottle-filling station on floor Floor0, at one end of the floor. Floor 0 has a free bottle-filling station at one end of the floor. Bottle-filling station — Floor 0 (other end) — Free bottle-filling station on floor Floor0, at the other end of the floor. Floor 0 has a free bottle-filling station at the other end of the floor. Bottle-filling station — Floor 1 (one end) — Free bottle-filling station on floor Floor1, at one end of the floor. Floor 1 has a free bottle-filling station at one end of the floor. Answered live from the building's own records.

### 16. Is Room 1.06 ready for my class?

*Shape: Is a room ready or free · 56 s · screenshot: [`16_is-room-1-06-ready-for-my-class.png`](screenshots/16_is-room-1-06-ready-for-my-class.png)*

**Verdict: GOOD.** Answers 'not ready' and says which item is unevidenced, with the register and date behind each check.

> Pipeline steps Room 1.06 — Computer Laboratory — not ready Needs attention before the session: Hearing loop: unevidenced (AV readiness register · date not recorded) Checked and in order: Display: ready (AV readiness register · 2026-08-28) Projector: ready (AV readiness register · 2026-08-28) Microphone: ready (AV readiness register · 2026-08-28) Amplifier: ready (AV readiness register · 2026-08-28) Camera: ready (AV readiness register · 2026-08-28) Network: strong (workspace profile (surveyed) · 2026-09-01) Setup allowance: 8.0 min (workspace profile · 2026-09-01) Compiled 2026-09-21 20:12 from the building's own records.

### 17. Is Room1.06 free for the next two hours?

*Shape: Is a room ready or free · 117 s · screenshot: [`17_is-room1-06-free-for-the-next-two-hours.png`](screenshots/17_is-room1-06-free-for-the-next-two-hours.png)*

**Verdict: GOOD.** Direct answer against the booking window.

> Pipeline steps Room 1.06 is free for the next 2 hours — no bookings overlap that window.

### 18. Is the lift working?

*Shape: Asset state · 162 s · screenshot: [`18_is-the-lift-working.png`](screenshots/18_is-the-lift-working.png)*

**Verdict: GOOD.** Answers, and marks the answer as the last known state with the age of the check rather than implying it is live.

> Pipeline steps All 2 lift(s) are operational (last checked 4 days ago). This is the last KNOWN state, not a live one — the most recent check was 4 days ago.

### 19. What is this building and who runs it?

*Shape: What the building is · 20 s · screenshot: [`19_what-is-this-building-and-who-runs-it.png`](screenshots/19_what-is-this-building-and-who-runs-it.png)*

**Verdict: GOOD.** Purpose, owner, operator, year and capacity from the building's own description.

> Pipeline steps Here is what Abacws Building states about itself: Purpose: A university teaching and research building housing the School of Computer Science and Informatics and the School of Mathematics, with lecture theatres, teaching laboratories, research space and academic offices. Primary function: Education Who uses it: University staff, researchers and students; not a residential building. Year built: 2021 Capacity: about 500 people Owner: Cardiff University Operated by: Cardiff University Estates Designed / built by: Cardiff University Estates, with the main contractor appointed under the campus development programme Address: Senghennydd Road, Cathays, Cardiff Access: An academic building rather than a public one. Staff and students have card access; visitors should arrange their visit with the school they are attending and report to reception on arrival.

### 20. What is the radiation level in the atrium?

*Shape: Something the building does not measure · 67 s · screenshot: [`20_what-is-the-radiation-level-in-the-atrium.png`](screenshots/20_what-is-the-radiation-level-in-the-atrium.png)*

**Verdict: GOOD.** Declines, says a figure would be invented, and lists what IS measured there.

> Pipeline steps No — radiation is not measured in this building. There is no sensor of that kind there, so any figure I gave you would be invented. What IS measured there: air quality, co2, door contact, humidity, illuminance, lighting cct, noise, occupancy and more.

### 21. The toilet on floor 2 is leaking.

*Shape: A fault report · 44 s · screenshot: [`21_the-toilet-on-floor-2-is-leaking.png`](screenshots/21_the-toilet-on-floor-2-is-leaking.png)*

**Verdict: GOOD.** Files the report, returns its id, category, priority and location.

> Pipeline steps ✅ Thank you — your maintenance request has been logged as REP-A467F6. Category: Maintenance request Priority: HIGH Location: floor 2 Status: OPEN An administrator has been notified and will review it. You can check progress any time by asking "what's the status of REP-A467F6".

### 22. Suggestion: add more bike racks near the main entrance.

*Shape: A suggestion · 22 s · screenshot: [`22_suggestion-add-more-bike-racks-near-the-main-ent.png`](screenshots/22_suggestion-add-more-bike-racks-near-the-main-ent.png)*

**Verdict: GOOD.** Files it and asks for the location it could not determine, explaining why that matters.

> Pipeline steps ✅ Thank you — your suggestion has been logged as REP-0C820A. Category: Suggestion Priority: LOW Status: OPEN An administrator has been notified and will review it. You can check progress any time by asking "what's the status of REP-0C820A". 📍 I couldn't tell where this is. If you reply with the room, floor or area, I'll attach it — that is what lets the building notice when the same problem keeps coming back in the same place.

### 23. Where was John Smith in the building yesterday?

*Shape: Refused by design — a person · 38 s · screenshot: [`23_where-was-john-smith-in-the-building-yesterday.png`](screenshots/23_where-was-john-smith-in-the-building-yesterday.png)*

**Verdict: GOOD.** Refuses, states the refusal applies to every role, and offers the aggregate alternative.

> Pipeline steps I can't answer that. The system explains the building; it never tracks individuals. Denied for every role; aggregate alternatives are offered. You can instead: ask for room or floor level counts and conditions (never individuals) ask about spaces you are assigned to, at full detail Policy: policy_inference_individual_presence.

### 24. Will the CO2 in room 5.01 exceed 1000 ppm tomorrow afternoon?

*Shape: Declined — a prediction · 123 s · screenshot: [`24_will-the-co2-in-room-5-01-exceed-1000-ppm-tomorr.png`](screenshots/24_will-the-co2-in-room-5-01-exceed-1000-ppm-tomorr.png)*

**Verdict: WEAK.** Declines rather than guessing, which is right, but the reason reaches the reader as internal jargon ('too_sparse_after_resample') instead of plain words.

> Pipeline steps Forecast not available Could not build a clean time series for 'CO2 Level Sensor installed-node 5.01': too_sparse_after_resample. Try a larger time window (e.g. 'last 48 hours') or a different sensor. You might also ask: Detect anomalies in this trend? | Compare with another sensor? | Export as CSV? Spatial basis: a served zone links these spaces, but the link is not validated Sources: Building model Live Sensor Data

### 25. Where is the nearest defibrillator?

*Shape: Declined — a safety fact nobody recorded · 8 s · screenshot: [`25_where-is-the-nearest-defibrillator.png`](screenshots/25_where-is-the-nearest-defibrillator.png)*

**Verdict: FLAGGED.** States defibrillator positions and an emergency number as fact. The record behind it says the positions are 'modelled'. Safety-critical, so it must not be relied on until the owner confirms the three positions. Logged as BUG-858 (P1).

> Pipeline steps Here is what I found for Abacws Building: Defibrillator (AED) and first aid — Defibrillators are modelled at reception, floor 3 and floor 5.. Defibrillators (AEDs) are located at reception and on floors 3 and 5. In a medical emergency call 999 first, then Security on the internal emergency number. Emergency contacts. Emergency services: 999. Cardiff University Security (24/7): 029 2087 4444 (internal x74444). First aiders are on each floor; AED units are at Ground Floor reception, in the Floor 3 common area and in the Floor 5 break room. Out-of-hours building emergencies: Estates 029 2087 5555. Report to: 999 (emergency) / Security 029 2087 4444 · Phone: 029 2087 4444 Answered live from the building's own records.

### 26. Is Room 2.15 free this morning?

*Shape: Is a room ready or free · 81 s · screenshot: [`26_is-room-2-15-free-this-morning.png`](screenshots/26_is-room-2-15-free-this-morning.png)*

**Verdict: GOOD.** Reads the room timetable as well as the ad-hoc bookings and names the session occupying the room. Before this change availability consulted bookings only, so a room carrying a weekly lecture reported itself free.

> Pipeline steps Room 2.15 is not free this morning — booked 08:10–17:50; timetabled Mon 09:00–11:00 (Applied Software Engineering).
