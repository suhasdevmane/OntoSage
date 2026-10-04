# Tail N — hand read, 2026-09-30

60 unseen questions from `paper/Survey analysis and results/corpus/classified_corpus.csv`
(the real pre-design survey corpus, 96 participants), one question per participant, excluding
every question asked in tails C–M. Mix 87% LOOKUP / 12% AGGREGATION / 2% MULTI_STEP against
the corpus's own 88/9/3 — representative of what real people ask.

Asked live on a healthy orchestrator, caches flushed, fresh chat id each, **no restart during
the run** (container `StartedAt` identical before and after). 60/60 returned OK.

## Result

| label | n | share |
|---|---|---|
| GOOD | 14 | 23.3% |
| DECLINE-OK | 18 | 30.0% |
| **DECLINE-BAD** | **8** | **13.3%** |
| **WEIRD** | **20** | **33.3%** |
| **FABRICATED** | **0** | **0%** |

**Acceptable (GOOD + DECLINE-OK): 32/60 = 53.3%**
**Unacceptable: 28/60 = 46.7%**

**NOT COMPARABLE TO TAIL M's 33.9%.** Tail M was harder synthesised multi-clause stakeholder
questions; tail N is the real user distribution, which is dominated by short vague LOOKUPs
("is this area safe?", "did you go to college?", "does the building sound feel good"). The two
measure different things and neither supersedes the other.

**THE NUMBER THAT MATTERS MOST IS THE ZERO.** Design contract #4 is "never surface a
plausible-but-wrong value". Across 60 unseen real questions I found no invented figure. Every
failure is a decline that should have been an answer, or an answer about the wrong thing —
both visible to the reader. That is the failure mode this project chose, and it held.

## Limitation of this read, stated rather than buried

`scripts/ask_questions.py` truncates answers in its log, so for roughly ten of the longer
answers I read a preview rather than the full text. A truncated answer could continue into
something better (or worse). The labels below are therefore a floor on quality for those, not
a precise measure. Three were re-read in full to check the labels held; they did.

## The failures cluster into three causes, not twenty-eight

### 1. BUG-947's shape — 6 of the 8 false declines
The answer **names the right reading or register in the same sentence as the refusal**:

- #23 "Has the humidity changed significantly in the past hour?" → *"I couldn't answer that …
  the nearest things I can answer are … **the readings of humidity**, runtime hours, air
  quality"*
- #43 "What is the return air temperature?" → *"… **the readings of return air temperature**,
  supply air temperature"*
- #45 "how is water consumption monitored here?" → *"… **the readings of entering water
  temperature, leaving water temperature, water flow**"*
- #46 "are there any spaces reserved but not currently in use?" → *"… the Workspace profile,
  **Room booking** and Interval record records"*
- #9 "Does the server room keep track of who visits?" → searched *Stakeholder Group Register*;
  the building holds **AccessEvent, 679 records**
- #25 "do the entry and exit logs reconcile for a roll call right now?" → searched *emergency
  coordination function register*; same AccessEvent holds entry/exit

One fix — make the selector read what the pointer already found — would move six of these.

### 2. Developer onboarding text shown to a user — 5 instances (#3, #8, #14, #28, #53)
*"You can add it — no code changes needed: **1.** **2.** Point it at its readings — give each
sensor a `ref:hasExternalReference` → `ref:hasTimeseriesId` … plus `ref:storedAt` (a key from
`database_registry.yaml`)."*
Two defects in one block: **item 1 renders EMPTY**, and internal schema and filenames are shown
to someone asking whether there is a mailroom. NOTE: asked as `facility01@example.com`
(facility_manager). BUG-719 records this instruction being hidden for non-admins, so a guest may
see something different — **this cluster's size is role-dependent and was measured on one role.**

### 3. Wrong lane — ~6
- #5 *"if the main exit is blocked by smoke, what is the alternative route"* → **logged as an
  URGENT safety REPORT, REP-F9828F.** A question about evacuation, filed as an incident. The
  routing contract's own rule is "Questions are NOT reports". Safety-relevant and the worst of
  the twenty-eight.
- #40 *"can you call for a repairman?"* → *"I couldn't find a report with ID **REP-AIRMAN**"* —
  "repairman" parsed as a report identifier.
- #12 *"This room is far too hot. Where is a nearby area to cool down?"* → floor-plan menu.
- #30 *"which areas are currently overcrowded?"* → *"No sensor data available for anomaly
  detection"* + floor-plan menu, with occupancy data present.
- #50 *"are there alerts for unusual energy patterns?"* → treated as a request to CREATE an alert.
- #52 *"Can the building remind me to adjust lighting?"* → treated as an actuation request.

## What worked, and it is worth keeping
- **Deictic clarification is solid: 5/5.** "this office", "this area", "this room" all got
  *"Which room do you mean … answering about a different one would look right and be wrong."*
  That is BUG-719's fix holding on unseen questions.
- **Honest scoping.** #58 *"if the weather forecast shows a cold snap …"* → *"**I don't hold a
  weather forecast.** Abacws Building's outdoor sensors report what the weather is doing now …"*
- **#18 legionella** — answered from four water-hazard records AND stated *"The register does
  **not** contain the word 'legionella'"*. Exactly the right shape.
- **#34** — 3 overdue compliance items with due dates and responsible roles.
- **General guidance is labelled as such** (#13, #27, #35, #56): *"General guidance (not from
  this building's records)"*.

## Per-question labels

1 GOOD · 2 GOOD · 3 WEIRD · 4 DECLINE-OK · 5 WEIRD · 6 WEIRD · 7 GOOD · 8 WEIRD · 9 DECLINE-BAD ·
10 WEIRD · 11 DECLINE-OK · 12 WEIRD · 13 DECLINE-OK · 14 WEIRD · 15 GOOD · 16 GOOD · 17 DECLINE-OK ·
18 GOOD · 19 DECLINE-OK · 20 DECLINE-OK · 21 DECLINE-OK · 22 GOOD · 23 DECLINE-BAD · 24 WEIRD ·
25 DECLINE-BAD · 26 DECLINE-OK · 27 DECLINE-OK · 28 DECLINE-BAD · 29 WEIRD · 30 WEIRD ·
31 DECLINE-OK · 32 WEIRD · 33 GOOD · 34 GOOD · 35 DECLINE-OK · 36 DECLINE-BAD · 37 DECLINE-OK ·
38 GOOD · 39 DECLINE-OK · 40 WEIRD · 41 GOOD · 42 GOOD · 43 DECLINE-BAD · 44 DECLINE-OK ·
45 DECLINE-BAD · 46 DECLINE-BAD · 47 GOOD · 48 DECLINE-OK · 49 WEIRD · 50 WEIRD · 51 WEIRD ·
52 WEIRD · 53 WEIRD · 54 DECLINE-OK · 55 WEIRD · 56 DECLINE-OK · 57 DECLINE-OK · 58 GOOD ·
59 WEIRD · 60 WEIRD

## One flaw in the draw, recorded
#27 and #35 are the SAME question ("how can the building optimise energy use during weekends
and holidays?") from two different participants. One-per-participant does not dedupe question
TEXT. Both were answered consistently (general guidance, labelled), so it cost nothing here,
but the next draw should dedupe on normalised text as well as on participant.
