# Regression probe — answers this system has already been proved to give

Response cache flushed before the run: 0 key(s) removed.

Model: `local/gpt-oss:20b` · building `bldg1` · 60 cases · **59 first-pass pass, 1 first-pass fail**

Each case asserts a FACT the registers hold — a figure, a record id, a department code — not a phrasing, so a reworded answer passes and a wrong figure fails.

**Every case was asked once.** No result here was retried, so a failure is a first-pass failure and is not folded into the pass total.

**How long each one took is recorded**, and summarised per lane below. A single typical figure hid a 10x spread across identical re-asks (CAVEAT-500), so a slow case reads as slow here rather than as a mystery failure.

| result | group | question | secs | why |
|---|---|---|---|---|
| PASS | departments | Who do I contact about a broken door closer, and how quickly should th | 55.4 |  |
| PASS | departments | Which departments have no out-of-hours route? | 6.9 |  |
| PASS | departments | Who is my contact for a fault with the network, and what is their resp | 8.8 |  |
| PASS | workspace | Where can I work for three hours with power, good Wi-Fi and a low risk | 22.6 |  |
| **FAIL** | workspace | Which bookable rooms are suitable for a confidential call? | 8.2 | none of ['ws-27', 'ws-28', '5.17', '5.18'] |
| PASS | assets | What duty was the Floor 3 air handling unit designed and commissioned  | 27.6 |  |
| PASS | assets | Which rarely visited plant areas have the longest blind intervals? | 17.6 |  |
| PASS | assets | Which isolation points have never been proved dead? | 15.5 |  |
| PASS | assets | Is each asset linked to the correct parent, engineering system and ser | 21.3 |  |
| PASS | safety | Which high-potential near misses were never investigated? | 10.8 |  |
| PASS | safety | Which fire safety assets are overdue or cannot be evidenced? | 18.0 |  |
| PASS | safety | Which hazard controls are overdue for test? | 14.7 |  |
| PASS | safety | Which refuge points have a working communication unit? | 12.1 |  |
| PASS | safety | Which refuge points are defective, and who owns them? | 15.5 |  |
| PASS | operations | Which HVAC systems run outside normal hours, and is each exception app | 33.8 |  |
| PASS | operations | Which permits are open? | 11.8 |  |
| PASS | timetable | Which teaching sessions are scheduled in Room 1.06? | 22.7 |  |
| PASS | metrology | When was the CO2 sensor in Room 5.01 last calibrated? | 19.1 |  |
| PASS | metrology | How often does a CO2 sensor report? | 14.5 |  |
| PASS | metrology | How many sensors are overdue for calibration? | 8.8 |  |
| PASS | counts | How many CO2 sensors are there? | 10.2 |  |
| PASS | counts | How many sensors are there? | 62.9 |  |
| PASS | stakeholders | Which stakeholder groups does DEP-13 serve? | 12.7 |  |
| PASS | honesty | What is the temperature in Room 9.99? | 18.3 |  |
| PASS | honesty | How warm is the swimming pool? | 21.0 |  |
| PASS | circulation | How long does it take to get from Level 1 to Level 5? | 32.1 |  |
| PASS | circulation | On which floor pairs is the step-free route slower than the stairs? | 15.2 |  |
| PASS | workspace | How long do the Level 1 computer laboratories take to recover after a  | 10.6 |  |
| PASS | deliberate | Which space has the best conditions for focused work this afternoon? | 70.7 |  |
| PASS | deliberate | Which space on Floor 3 has the best conditions for focused work this a | 24.3 |  |
| PASS | workspace | I have an online interview next week. Which bookable room and time giv | 8.8 |  |
| PASS | readiness | Is Room 1.06 ready for my class? | 8.5 |  |
| PASS | readiness | Is Room 3.13 ready for my seminar? | 20.6 |  |
| PASS | capability-bypass | What is the CO2 level in room 5.01 right now? | 33.9 |  |
| PASS | capability-bypass | The toilet on floor 2 is leaking. | 6.5 |  |
| PASS | capability-bypass | Open the windows on floor 3. | 6.3 |  |
| PASS | capability-bypass | Show me the floor 3 layout. | 5.9 |  |
| PASS | capability-bypass | What is the total area of floor 3? | 7.5 |  |
| PASS | capability-bypass | How do I get to the seminar room from reception? | 0.4 | **possible cache hit** |
| PASS | capability-bypass | Take me to the nearest fire exit. | 11.7 |  |
| PASS | capability-bypass | How many work orders are open? | 6.2 |  |
| PASS | capability-bypass | Is the supply fan running on floor 5? | 9.4 |  |
| PASS | capability-bypass | What is the filter differential pressure on AHU_F5? | 21.6 |  |
| PASS | capability-bypass | How much energy did the building use last week? | 40.7 |  |
| PASS | capability-bypass | How much electricity does the lab on floor 5 use? | 31.4 |  |
| PASS | capability-bypass | Can you measure noise in this building? | 34.0 |  |
| PASS | capability-bypass | Why is room 5.01 stuffy? | 18.3 |  |
| PASS | capability-bypass | When was the fire alarm last tested? | 9.1 |  |
| PASS | capability-bypass | Give me a report on the CO2 in room 5.01 yesterday. | 72.2 |  |
| PASS | capability-bypass | Is the professor in her office? | 7.7 |  |
| PASS | w0 | Is the lift working? | 7.1 |  |
| PASS | w0 | How many sensors are there in total? | 35.0 |  |
| PASS | w0 | What is this building and who runs it? | 15.5 |  |
| PASS | w0 | What is the nearest accessible toilet to room 3.10? | 13.9 |  |
| PASS | w0 | Which rooms are stuffy right now? | 29.4 |  |
| PASS | w0 | Compare the average CO2 on floor 1 versus floor 3 | 49.5 |  |
| PASS | w0 | Show me floor 3 | 7.1 |  |
| PASS | portability | What is the radiation level in the atrium? | 40.0 |  |
| PASS | portability | How many floors does this building have? | 7.0 |  |
| PASS | capability-bypass | Set VAV-501-SP to 21 degrees. | 8.1 |  |

**1 case(s) completed in under 1.0 s and are marked possible cache hits.** No pipeline answer has been measured that fast; a PASS marked this way says nothing about the lane it names (BUG-662).

## Latency per lane

Every figure here is an OBSERVED request time taken at the nearest rank — no interpolation, no mean, no estimate — so each one is a wait some question in that lane actually had.

A p95 is printed only for a lane of at least 5 cases. A figure marked `*` comes from a lane of fewer than 20 cases, where the nearest-rank p95 is the slowest case itself rather than a tail.

A case that timed out contributes the time the client waited before giving up. That is a real wait and it is not the time the answer would have taken, so the count is stated separately (CAVEAT-500: a timeout that cannot be told apart from a defect teaches whoever reads this to ignore both).

| lane | n | p50 s | p95 s | slowest s | timed out | slowest case |
|---|---|---|---|---|---|---|
| assets | 4 | 17.6 | — (n<5) | 27.6 | 0 | What duty was the Floor 3 air handling unit designed and com |
| capability-bypass | 18 | 9.1 | 72.2* | 72.2 | 0 | Give me a report on the CO2 in room 5.01 yesterday. |
| circulation | 2 | 15.2 | — (n<5) | 32.1 | 0 | How long does it take to get from Level 1 to Level 5? |
| counts | 2 | 10.2 | — (n<5) | 62.9 | 0 | How many sensors are there? |
| deliberate | 2 | 24.3 | — (n<5) | 70.7 | 0 | Which space has the best conditions for focused work this af |
| departments | 3 | 8.8 | — (n<5) | 55.4 | 0 | Who do I contact about a broken door closer, and how quickly |
| honesty | 2 | 18.3 | — (n<5) | 21.0 | 0 | How warm is the swimming pool? |
| metrology | 3 | 14.5 | — (n<5) | 19.1 | 0 | When was the CO2 sensor in Room 5.01 last calibrated? |
| operations | 2 | 11.8 | — (n<5) | 33.8 | 0 | Which HVAC systems run outside normal hours, and is each exc |
| portability | 2 | 7.0 | — (n<5) | 40.0 | 0 | What is the radiation level in the atrium? |
| readiness | 2 | 8.5 | — (n<5) | 20.6 | 0 | Is Room 3.13 ready for my seminar? |
| safety | 5 | 14.7 | 18.0* | 18.0 | 0 | Which fire safety assets are overdue or cannot be evidenced? |
| stakeholders | 1 | 12.7 | — (n<5) | 12.7 | 0 | Which stakeholder groups does DEP-13 serve? |
| timetable | 1 | 22.7 | — (n<5) | 22.7 | 0 | Which teaching sessions are scheduled in Room 1.06? |
| w0 | 7 | 15.5 | 49.5* | 49.5 | 0 | Compare the average CO2 on floor 1 versus floor 3 |
| workspace | 4 | 8.8 | — (n<5) | 22.6 | 0 | Where can I work for three hours with power, good Wi-Fi and  |
| ALL LANES | 60 | 15.2 | 55.4 | 72.2 | 0 | Give me a report on the CO2 in room 5.01 yesterday. |

## What came back instead

### Which bookable rooms are suitable for a confidential call?

- **why:** none of ['ws-27', 'ws-28', '5.17', '5.18'] · **intent:** `metadata`

```
**Bookable rooms that are recorded as suitable for a confidential call**

- **WS‑06 – Seminar room 1.25**  
  • Floor 1, 16 seats  
  • Comment: “Acoustically separated; suitable for confidential calls”  
  • Bookable: yes  
  • Suitable for calls: yes  

This is the only workspace in the building that the register records as both bookable and suitable for confidential calls. No other bookable room has a recorded “confidential” designation.

---
**You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?
```

