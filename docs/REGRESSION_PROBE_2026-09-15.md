# Regression probe — answers this system has already been proved to give

Model: `local/gpt-oss:20b` · building `bldg1` · 59 cases · **50 first-pass pass, 9 first-pass fail**

Each case asserts a FACT the registers hold — a figure, a record id, a department code — not a phrasing, so a reworded answer passes and a wrong figure fails.

**Every case was asked once.** No result here was retried, so a failure is a first-pass failure and is not folded into the pass total.

| result | group | question | why |
|---|---|---|---|
| PASS | departments | Who do I contact about a broken door closer, and how quickly should th |  |
| PASS | departments | Which departments have no out-of-hours route? |  |
| PASS | departments | Who is my contact for a fault with the network, and what is their resp |  |
| PASS | workspace | Where can I work for three hours with power, good Wi-Fi and a low risk |  |
| PASS | workspace | Which bookable rooms are suitable for a confidential call? |  |
| PASS | assets | What duty was the Floor 3 air handling unit designed and commissioned  |  |
| PASS | assets | Which rarely visited plant areas have the longest blind intervals? |  |
| PASS | assets | Which isolation points have never been proved dead? |  |
| PASS | assets | Is each asset linked to the correct parent, engineering system and ser |  |
| PASS | safety | Which high-potential near misses were never investigated? |  |
| PASS | safety | Which fire safety assets are overdue or cannot be evidenced? |  |
| PASS | safety | Which hazard controls are overdue for test? |  |
| PASS | safety | Which refuge points have a working communication unit? |  |
| PASS | safety | Which refuge points are defective, and who owns them? |  |
| PASS | operations | Which HVAC systems run outside normal hours, and is each exception app |  |
| PASS | operations | Which permits are open? |  |
| PASS | timetable | Which teaching sessions are scheduled in Room 1.06? |  |
| PASS | metrology | When was the CO2 sensor in Room 5.01 last calibrated? |  |
| PASS | metrology | How often does a CO2 sensor report? |  |
| PASS | metrology | How many sensors are overdue for calibration? |  |
| PASS | counts | How many CO2 sensors are there? |  |
| **FAIL** | counts | How many sensors are there? | transport TIMEOUT |
| **FAIL** | stakeholders | Which stakeholder groups does DEP-13 serve? | transport TIMEOUT |
| **FAIL** | honesty | What is the temperature in Room 9.99? | transport TIMEOUT |
| **FAIL** | honesty | How warm is the swimming pool? | transport TIMEOUT |
| **FAIL** | circulation | How long does it take to get from Level 1 to Level 5? | transport TIMEOUT |
| **FAIL** | circulation | On which floor pairs is the step-free route slower than the stairs? | transport TIMEOUT |
| **FAIL** | workspace | How long do the Level 1 computer laboratories take to recover after a  | transport TIMEOUT |
| PASS | deliberate | Which space has the best conditions for focused work this afternoon? |  |
| PASS | deliberate | Which space on Floor 3 has the best conditions for focused work this a |  |
| **FAIL** | workspace | I have an online interview next week. Which bookable room and time giv | none of ['5.17', '5.18', 'silent'] |
| PASS | readiness | Is Room 1.06 ready for my class? |  |
| PASS | readiness | Is Room 3.13 ready for my seminar? |  |
| PASS | capability-bypass | What is the CO2 level in room 5.01 right now? |  |
| PASS | capability-bypass | The toilet on floor 2 is leaking. |  |
| PASS | capability-bypass | Open the windows on floor 3. |  |
| PASS | capability-bypass | Show me the floor 3 layout. |  |
| PASS | capability-bypass | What is the total area of floor 3? |  |
| PASS | capability-bypass | How do I get to the seminar room from reception? |  |
| PASS | capability-bypass | Take me to the nearest fire exit. |  |
| PASS | capability-bypass | How many work orders are open? |  |
| PASS | capability-bypass | Is the supply fan running on floor 5? |  |
| PASS | capability-bypass | What is the filter differential pressure on AHU_F5? |  |
| PASS | capability-bypass | How much energy did the building use last week? |  |
| PASS | capability-bypass | How much electricity does the lab on floor 5 use? |  |
| PASS | capability-bypass | Can you measure noise in this building? |  |
| PASS | capability-bypass | Why is room 5.01 stuffy? |  |
| **FAIL** | capability-bypass | When was the fire alarm last tested? | transport TIMEOUT |
| PASS | capability-bypass | Give me a report on the CO2 in room 5.01 yesterday. |  |
| PASS | capability-bypass | Is the professor in her office? |  |
| PASS | w0 | Is the lift working? |  |
| PASS | w0 | How many sensors are there in total? |  |
| PASS | w0 | What is this building and who runs it? |  |
| PASS | w0 | What is the nearest accessible toilet to room 3.10? |  |
| PASS | w0 | Which rooms are stuffy right now? |  |
| PASS | w0 | Compare the average CO2 on floor 1 versus floor 3 |  |
| PASS | w0 | Show me floor 3 |  |
| PASS | portability | What is the radiation level in the atrium? |  |
| PASS | portability | How many floors does this building have? |  |

## What came back instead

### How many sensors are there?

- **why:** transport TIMEOUT · **intent:** ``

```

```

### Which stakeholder groups does DEP-13 serve?

- **why:** transport TIMEOUT · **intent:** ``

```

```

### What is the temperature in Room 9.99?

- **why:** transport TIMEOUT · **intent:** ``

```

```

### How warm is the swimming pool?

- **why:** transport TIMEOUT · **intent:** ``

```

```

### How long does it take to get from Level 1 to Level 5?

- **why:** transport TIMEOUT · **intent:** ``

```

```

### On which floor pairs is the step-free route slower than the stairs?

- **why:** transport TIMEOUT · **intent:** ``

```

```

### How long do the Level 1 computer laboratories take to recover after a full class?

- **why:** transport TIMEOUT · **intent:** ``

```

```

### I have an online interview next week. Which bookable room and time give me the lowest risk of noise?

- **why:** none of ['5.17', '5.18', 'silent'] · **intent:** `deliberate`

```
I couldn't rank any spaces for this request.

**Why:** question spans 234 spaces, above the 120-space fetch budget.

That question covers 234 spaces — more than I can read within one request. Narrow it to a floor (Floor0, Floor1, Floor2, Floor3, Floor4, Floor5) or to a named room and I can answer it directly. I would rather say that than answer from part of the building without telling you which part.

<details>
<summary>How I worked this out (evidence dossier)</summary>

*Decision: select_one over 0 ranked candidates; plan fingerprint in the evidence payload.*

| space | modality | value | basis | points | source table | simulated |
|---|---|---|---|---|---|---|

**Excluded:** all in scope (question spans 234 spaces, above the 120-space fetch budget)

</details>

**Evidence time: unknown.** I can't tell you how old these readings are, so treat the recommendation as unverified rather tha
```

### When was the fire alarm last tested?

- **why:** transport TIMEOUT · **intent:** ``

```

```

