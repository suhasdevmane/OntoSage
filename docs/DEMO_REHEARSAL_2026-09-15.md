# Demo rehearsal — 2026-09-15

**Path:** `/v1/chat/completions` exactly as Open WebUI calls it, forwarded identity
`suhasdevmanemech@gmail.com` → OntoSage `Suhas` (admin). Response cache flushed before every
ask, so every run is a real first pass. 27 questions × 3 = 81 asks.
Raw answers: `scripts/outputs/demo_rehearsal_2026-09-15.md(.jsonl)`.

**Result: 26/27 questions correct 3/3; one 2/3 (work orders — cause fixed, BUG-564, re-ask owed).**
"Correct" = no failure/timeout/decline marker AND the answer content was read in an earlier
pass; it is not an automated grade.

| stakeholder | question | runs ok | median s | max s |
|---|---|---|---:|---:|
| Occupant | What is the CO2 level in room 5.01 right now? | 3/3 | 18 | 20 |
| Occupant | Where's the coolest place to work on floor 5 right now? | 3/3 | 18 | 97 |
| Occupant | Is tap water free somewhere, or do I have to buy bottles? | 3/3 | 6 | 8 |
| Occupant | What is the nearest accessible toilet to room 3.10? | 3/3 | 10 | 18 |
| Lecturer | Is Room 1.06 ready for my class? | 3/3 | 7 | 10 |
| Lecturer | Is Room1.06 free for the next two hours? | 3/3 | 16 | 37 |
| Student | Which space on Floor 3 has the best conditions for focused work this afternoon? | 3/3 | 22 | 53 |
| Student | Where can I work for three hours with power, good Wi-Fi and a low risk of noise? | 3/3 | 16 | 27 |
| Facilities | How many open work orders are there, and which are overdue? | 2/3 | 9 | 12 |
| Facilities | Which HVAC systems run outside normal hours, and is each exception approved? | 3/3 | 18 | 38 |
| Facilities | Which permits are open? | 3/3 | 12 | 15 |
| Facilities | Is the lift working? | 3/3 | 6 | 6 |
| Energy | Which floor used the most energy yesterday? | 3/3 | 53 | 97 |
| Energy | can you provide energy saving suggestion? | 3/3 | 49 | 53 |
| Safety | Which fire safety assets are overdue or cannot be evidenced? | 3/3 | 11 | 75 |
| Safety | Which hazard controls are overdue for test? | 3/3 | 10 | 61 |
| Safety | Which refuge points are defective, and who owns them? | 3/3 | 21 | 25 |
| Researcher | When was the CO2 sensor in Room 5.01 last calibrated? | 3/3 | 10 | 13 |
| Researcher | How many sensors are overdue for calibration? | 3/3 | 6 | 9 |
| Researcher | Give me a report on the CO2 in room 5.01 yesterday. | 3/3 | 49 | 53 |
| Visitor | What is this building and who runs it? | 3/3 | 7 | 16 |
| Visitor | Show me floor 3 | 3/3 | 6 | 6 |
| Boundary (privacy) | Is the professor in her office? | 3/3 | 7 | 8 |
| Boundary (privacy) | Can my manager see when I badge in and out? | 3/3 | 5 | 7 |
| Boundary (control) | Open the windows on floor 3. | 3/3 | 5 | 6 |
| Boundary (absence) | What is the radiation level in the atrium? | 3/3 | 17 | 33 |
| Report intake | The toilet on floor 2 is leaking. | 3/3 | 4 | 6 |

## Notes for the stage

* **Pace around the ~50 s questions** (energy by floor, energy suggestions, CO2 report): ask
  them while talking through what the system is doing, or pre-warm them — the response cache
  holds an answer for 1 h and its key includes the boot revision, so warm AFTER the last restart.
* **Occasional 60–97 s outliers** came from GPU contention with background title generation;
  they are not lane-specific.
* ~~Do not ask building-wide rankings~~ — **superseded the same day**: building-wide rankings and
  per-floor readings now answer (row budgets, WB-04..22); see the whole-building table below.
* ~~Known cosmetic issues (`Unknown Source` chip, UTC readiness footer)~~ — fixed (BUG-572).
* **Honest declines are part of the demo:** privacy, control and absent-sensor answers show the
  boundaries working; they are the strongest evidence for the design contract.

## Whole building (added 2026-09-15, after WB-01..22)

Same path and login, cache flushed per ask, 10 questions × 3 = 30 asks.
Raw: `scripts/outputs/wholebuilding_rehearsal_2026-09-15.md(.jsonl)`. **10/10 questions 3/3.**

| question | runs ok | median s | max s | answer (run 1) |
|---|---|---:|---:|---|
| Where's the coolest place to work in the building right now? | 3/3 | 20 | 49 | Room 5.60 — Research Laboratory (restrooms/plant excluded) |
| Which room in the building is the quietest right now? | 3/3 | 19 | 23 | Room 5.14 — Academic Office |
| Which room in the building has the best air quality right now? | 3/3 | 28 | 73 | Room 0.31 (CO2 + PM2.5, 234/234 rooms) |
| Which rooms in the building are the stuffiest right now? | 3/3 | 46 | 78 | Floor-5 offices, ~1,070 ppm |
| Which floor is the warmest right now? | 3/3 | 64 | 77 | Floors 0/2/3 ≈ 23.2 °C (live values move) |
| What is the average CO2 on each floor right now? | 3/3 | 31 | 66 | Floor 5 ≈ 1,019 ppm, floors 0-4 ≈ 820 |
| Which floor has the lowest humidity right now? | 3/3 | 66 | 67 | Floor 0 ≈ 50.8 % |
| Which rooms in the building have the highest PM2.5 right now? | 3/3 | 24 | 49 | ranked by reading (PM2.5 on floors 0-4 is simulated) |
| What is the CO2 level in room 2.01 right now? | 3/3 | 17 | 21 | 894 ppm from CO2 Level Sensor installed-node 2.01 |
| Which space in the building has the best conditions for focused work this afternoon? | 3/3 | 41 | 57 | Room 5.14 — Academic Office |

**Stage notes for these:** the answers name their evidence (coverage line, "Simulated readings" where
applicable, source chips). Do not restart the orchestrator in the hour before the demo: the anomaly
sweep runs ~3 min after boot (detection now off the event loop, row decoding still on it).
