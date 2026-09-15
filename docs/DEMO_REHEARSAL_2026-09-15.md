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
* **Do not ask building-wide rankings** ("best room in the building") — they decline above the
  120-space fetch budget (RUN-09, deferred). Floor-scoped ones answer.
* **Known cosmetic issues:** answers citing the wide real-data table show a `Unknown Source`
  chip; the readiness footer prints its compile time in UTC.
* **Honest declines are part of the demo:** privacy, control and absent-sensor answers show the
  boundaries working; they are the strongest evidence for the design contract.
