# QA probe rounds through the Open WebUI endpoint — 10 October 2026

**Scope.** bldg1 (Abacws), live stack, questions asked through `/v1/chat/completions` exactly as
Open WebUI asks them (its chat-id and user-email headers, streamed), as the QA account
`facility03@example.com`, with all four answer and routing caches flushed before every ask.
`scripts/qa_probe.py` records the route (`ontosage_route`), the answer, and whether every chart
image it links actually loads.

**What this is not.** It is not an evaluation. Every question here was written by the developer,
and every defect found was fixed against the question that found it, so these questions are
tuned-on. "PASS" from the probe means *routed to an expected lane and delivered without an error,
an unexpected decline or a missing image*; it does not mean *correct*. Correctness was judged by
reading the answers, and several PASSes were wrong (they are in the tables below).
No Paper 3 study task, room, date or criterion appears in any probe question.

## The rounds

| Run | Questions | Probe PASS | Charts loaded | What it was |
|---|---|---|---|---|
| round 1 | 127 | 104 | 6 | the full pool, `scripts/qa_probe_questions.yaml` |
| round 2 | 74 | 63 | 4 | 74 NEW questions written after round 1, `scripts/qa_probe_questions_r2.yaml` |
| re-asks 1–6 | 32 / 15 / 15 / 17 / 10 / 5 | 23 / 13 / 14 / 17 / 10 / 4 | — | the flagged questions after each batch of fixes |
| bank sample | 40 | 33 (7 declines or clarifications, 0 errors) | — | a seeded draw from the 4,060-question development bank (no route expectations) |
| round 3 | 72 | 60 | 4 | 72 NEW questions by role (occupant, analyst, operator, sustainability, safety, visitor, student), asked as QA accounts of those roles, `scripts/qa_probe_questions_r3.yaml` |
| re-ask 7 | 18 | 17 (the 1 flag is a correct answer plus the "I can't make the booking" note) | 1 | round 3's failures after the fixes below |
| round 4 | 46 | 43 | 3 | 46 NEW questions written to test whether round 3's fixes generalise to new phrasings, `scripts/qa_probe_questions_r4.yaml` |
| re-asks 8–9 | 12 / 4 | 12 / 4 | 2 | round 4's failures after the fixes below, plus new phrasings of the two hardest |
| bank sample v2 | 40 | 31 (9 declines, 0 errors) | — | a second seeded draw from the development bank (seed 20261011, excluding v1 and the gate), asked after round 3's fixes; questions are not printed, so the declines are counted, not judged |
| round 5 | 12 conversations, 32 turns | read by hand: 10 of 20 follow-ups and 3 of 12 openers had a defect | 1 | multi-turn conversations, `docs/phase0/conversations_r5/`; the affected conversations re-asked twice after fixes (see Round 5) |
| round 6 | 10 NEW conversations, 30 turns | read by hand: 7 defects (one a round-5 regression), all fixed; 2 minor open | 2 (re-ask) | a second battery, `docs/phase0/conversations_r6/`, to test whether round 5's fixes generalise |
| bank sample v3 | 40 | 33 (7 flagged, 0 errors) | — | a third seeded draw (seed 20261012, excluding v1 and v2), asked after rounds 5–6; answers read, questions not printed: 1 correct "which room do you mean by this room?", 3 generic declines, 1 false absence ("the glass atrium", CAVEAT-1629), 2 odd answers (a UUID narrated as a value, CAVEAT-1630; a "saturated + chilled + hot" water-flow sum) |

The bank sample's seven non-passes were read (answers only — bank questions are never printed): one
correct "which room do you mean by *here*?" clarification and honest declines of compound
questions about things the building does not record (installation constraints, utilisation by room
class, a service-dependency map). None was a false absence that data could fix.

Median answer time 19–39 s; the slowest are the deliberation lane and forecasts (up to ~3 min).

## What was wrong, and what changed (tracker BUG-1503 … BUG-1561)

**Wrong room, wrong quantity, wrong scope (P1s).**
- A room id was dropped when the hinted sensor class was narrow: "temperature in room 1.06" read
  the outdoor weather feed; "light levels in room 4.03" read six floor-level sensors (BUG-1503).
- "Is room 5.01 warmer than room 3.10?" lost room 3.10 and said it had no temperature data
  (BUG-1514). Each named place is now resolved.
- "What maintenance was done last month?" listed six static issue CATEGORIES as "all the
  maintenance actions recorded" (BUG-1520). It now reads the work-order register by date.
- Forecasts started where the training span ended, two days in the past (BUG-1538), and a
  building "total" forecast was the mean of single sensors, ~30 people for ~225 (BUG-1539).
- "Will floor 3 be warmer than floor 4 tomorrow?" was asserted from two past means 0.1 °C apart
  (BUG-1545). Each floor is now forecast and the forecasts compared with their bands
  (`services/forecast_comparison.py`).
- Floor water flow was labelled L/s and integrated to 12,661 m³ in a day (BUG-1557).
- "Which staff member badged in first today?" was not refused (BUG-1551).

**Routing (each shape measured over the 4,060-question bank before it was added).**
Sensors that stopped reporting → freshness lane; incident and near-miss logs, work orders, who
maintains / services / cleans → the registers; "what does the building measure" and "what sensors
are in room X" → the reach answer; imperative comfort requests ("make room X warmer") → control;
"what's on in room X tomorrow" → bookings; a room id like "1.06" no longer splits a question as a
numbered list; the post stage no longer undoes a register decision.

**Registers.** A named period ("in September", "last month", "next year") now filters on the date
that says when a record happened, ended or was completed; a floor named against free-text
locations ("Level 4") filters by storey; "When does X expire?" gives the end date; a counted
"none" is no longer rewritten as a search miss.

**Charts.** Light-level charts were refused as the wrong quantity; bar and forecast charts never
reached Open WebUI (the executor's output key was misread, the forecast code imported a module the
sandbox forbids, and base64 charts are not rendered by Open WebUI); bar charts now start at zero
and name floors.

**Narration.** Chat shorthand ("temp in rm 5.01 now") is expanded; "muggy" is a humidity word,
not a CO2 one; comparatives ("warmer", "noisier") name their quantity; "the day before" is a
baseline; a count followed by a quantity word is no longer flagged as an impossible reading;
QUDT units print as units.

## Round 3 (tracker BUG-1563 … BUG-1582)

Round 3's 60 "PASS"es hid at least 14 wrong or empty answers; every one below was found by reading
the answer, and all but two are verified live after the fix.

- **A per-day or per-hour question got one figure for the whole period** (BUG-1563). "The daily
  average temperature in room 4.18 for the last 7 days" now returns one row per day and "CO2 in
  room 1.06 hour by hour yesterday" one row per hour, reduced in the store (no row cap), days
  aligned to the building's midnight (`services/aggregate_breakdown.py`).
- **A carbon-monoxide question was answered with the floor energy meters** (BUG-1567, P1): the word
  "carbon" inside "carbon monoxide" also resolved the carbon-footprint concept. A concept whose only
  evidence sits inside another concept's longer term is now dropped (47 of 4,060 bank questions
  change, all a generic concept losing to a specific one).
- **"List the open work orders for the lifts" was refused as a control command** (BUG-1568, P1);
  a verb after a determiner ("the open") is no longer an order.
- **Energy from power readings was summed, not integrated** (BUG-1582, P1): "solar energy
  yesterday" said 135 kWh; it is now about 34 kWh, stated as an integral of the kW readings.
- **A limit the reader states is used** (BUG-1572): "did any room go over 1000 ppm yesterday?" →
  "Yes … on 104 of 280 sensors (the limit you gave)".
- Named rooms by kind ("lab 4.20", "computer lab 1.07") are places (BUG-1565, BUG-1569); a booking
  request is an availability check that says the booking itself is not made here (BUG-1569); "how
  bright is the seminar room 3.13" is a reading, not the public-event register (BUG-1566, two
  shortcuts); a floor-named total is checked against placement instead of vetoed (BUG-1571);
  "how many CO2 sensors" counts CO2 sensors (BUG-1573); "too humid" gets a verdict against the
  listed standards (BUG-1574); chart captions are in building time (BUG-1570); a point's own QUDT
  unit is no longer dropped (BUG-1581); the route record names the contract rules that fired
  (CAVEAT-1526); "which sensors stopped reporting" reaches the freshness lane.

**Data (TTL-first, synthetic, no study referent):** the chiller's water points are typed chilled
water supply/return and the vocabulary knows those words (BUG-1564); a rooftop-solar topic and a
gas-leak procedure were authored through the admin Capabilities API (BUG-1575/1576); a
`PV_Generation_Power_Sensor` class, the PV points typed with it and declared in kW, a solar
generation shape in the publisher (zero at night), and the last week of PV rows regenerated with
it, backup in `outputs/backups/` (BUG-1580).

**Deliberately not changed, because they would move answers for study rooms days before the
freeze:** linking floor 0–4 rooms to their HVAC zone (CAVEAT-1577), cleaning the floor-4 plan's
ground-floor labels (CAVEAT-1578), extending the term timetable past 18 September
(CAVEAT-1583), and typing the boilers' water points.

## Round 4 (tracker BUG-1584 … BUG-1593)

**Round 3's fixes generalised:** every breakdown phrasing ("for each day this week", "hour by
hour today", "daily … over the last 5 days" on a floor), every stated limit ("above 26 degrees",
"more than 60% humidity"), every room named by kind ("office 4.07", "classroom 1.09"), and the new
plant and solar vocabulary answered first time. Reading the answers found ten more defects, all
fixed and verified live:

- **"Which contracts expire before the end of the year?" said two dates existed, both passed**
  (BUG-1585, P1): the verb "expire" selected the state "expired". Six contracts end this year,
  three of them still to come; the answer now lists all six with their status.
- **"How many PM2.5 sensors?" answered "one"** (BUG-1586, P1): "2.5" in "PM2.5" was read as a room.
- An indoor question no longer counts the outdoor sensor (BUG-1584); a change question ("gone up
  since this morning") is answered by comparing the last hour with this morning (BUG-1587/1593);
  "will it get stuffy this afternoon?" is forecast and answered against the standards band —
  "Unlikely: peaks at 865 ppm, the band's edge at 988, inside the 1000 ppm limit" (BUG-1592); a
  comparison answers its yes/no first (BUG-1588); "electricity use per floor" is a total, drawn as
  a bar chart (BUG-1591); "energy rating" reads the building's recorded rating, not its meters
  (BUG-1590); "when was the building opened?" reads its build year (BUG-1589).

**Open from round 4:** a forecast's "measured skill" line reported an MAE of ~800 ppm for one
room (CAVEAT-1594): the skill registry was graded on 28 August, before the generator fixes, and
should be re-graded after the study freeze.

## Round 5 — conversations (tracker BUG-1599 … BUG-1614)

Single questions were by now mostly right, so round 5 asked **12 multi-turn conversations** (32
turns, `docs/phase0/conversations_r5/`, `scripts/run_conversations.py`, one chat id per
conversation, as `facility03`): a value then "and the X?", a ranking then "there", a count then
"which floor has the most of them?", a register list then "the first one" and "it", a judgement
then "what about room Y?", a solar total then "and the day before?". **In the first run 10 of the 20
follow-up turns and 3 of the 12 opening questions had a defect**, and the worst were confidently
wrong rather than declined. Each was traced in the log to its cause and fixed, then the conversations were asked
again after a restart with all four caches flushed (`outputs/qa_probe/conversations_r5{,b,c}.jsonl`).

| Turn | First run | After the fixes |
|---|---|---|
| "and the day before?" after solar yesterday | **2,323 kWh from the six floor electricity meters, called solar** (BUG-1599) | "About 35 kWh was generated … Thu 08 Oct", the two PV arrays |
| "which of the two was higher?" after floor 3 / floor 4 electricity | "Which comparison? 1) Humidity in Room 2.03 vs 3.01 …" — none from this chat (BUG-1600) | "Floor 4 used more electricity, 403 kWh against Floor 3's 389 kWh" |
| "and the CO2?" after a clarification | "Across the building CO2 is averaging 909 ppm, ranging from 909 to 909" from one room (BUG-1601) | "In Room 5.09 — Academic Office, CO2 is averaging 845 ppm" |
| "who is assigned to the first one?" | WO-008 listed, no party (BUG-1602) | "responsible role: Electrical technician; owner: M and E Maintenance Supervisor" |
| "when is it due?" | "it" taken as floor 3, read from a suggestion chip (BUG-1603) | "The register does not record a next due date for this work order" (WO-008) |
| "Is it too humid in room 2.52?" | opened with "the recorded humidity value (1000) is outside the range" — 1000 was the row count (BUG-1604) | no warning; "49.98 % RH … within the acceptable range" |
| "what was the peak?" | "62.80 dB … also the lowest recorded … a spread of 0 dB" (BUG-1605) | "62.80 dB was the highest noise level recorded … on 10 Oct" |
| "which floor has the most of them?" (PM2.5 sensors) | PM2.5 LEVELS per floor (BUG-1606) | declined, then **counted from the graph: "Floor 5 has the most PM2.5 Level Sensors: 63"** with the per-floor table (BUG-1614) |
| "Which meeting rooms are free this afternoon?" | **"Primary: Room 0.01 — Main Reception"**, every room "not what you asked for" (BUG-1607) | the events lane's answer: "14 of 18 meeting rooms have no booking this afternoon" (BUG-1613) |
| (same) | — | a second run listed meeting rooms as meeting "everything you asked for" with availability **never checked** — the reason the routing was changed |
| "and the day before?" (second run) | the correct PV answer was **deleted by the relevance gate** ("only Oct 8") (BUG-1608) | kept |
| "what time does it close?" after the café | "On floor 0: Cafe" (BUG-1609) | the café's entry, "open 08:00–16:30 on weekdays" |
| "is that normal for an office?" | CO2 statistics, no judgement (BUG-1610) | "Both CO₂ 781 ppm and temperature 23.7 °C are compliant" against ASHRAE 62.1 / 55 |
| "Will meeting room 4.11 get stuffy this afternoon?" at 19:03 | a six-hour table, no verdict (BUG-1611) | "The time asked about (afternoons, 12:00–18:00) is not in this forecast … **Unlikely:** peaks at 801 ppm" |
| "what's its leaving water temperature?" after the heat pump | all four plants (BUG-1612) | Heat Pump 1 only, 70.76 °C |

**The two findings worth carrying forward.**

1. **The relevance gate's protection of grounded answers (BUG-873) never covered the aggregate
   lane.** `_grounded_evidence_behind` looks for `figures` on the bus copy of `aggregate_result`,
   and the SQL node never copied them, so any store-computed answer the gate objected to was
   replaced by "I couldn't answer that from the records". Found only because a follow-up gave the
   gate the bare "and the day before?" to judge. Both halves are fixed (BUG-1608).
2. **The v2 compound router took a question the events lane answers well and sent it to a lane
   that cannot check the period it names.** A kind of room plus a free window, and nothing else,
   now stays with the events lane (4 of 4,060 bank questions; 0 of the 56 study texts mention
   availability). A third facet (quiet, seats, a projector) still escalates. Separately, a
   deliberation ranking in which every space scores 0 is no longer presented as a recommendation
   (BUG-1607).

**New single questions after the fixes (`scripts/qa_probe_questions_r5.yaml`, 9 questions): 9/9
delivered**, read by hand: per-floor counts of CO2, noise (`ontosage:Sound_Level_Sensor`, found
through the lay-term resolver because no Brick class name says "noise") and occupancy sensors;
"free tomorrow morning" and "available this evening" from the events lane; "who is assigned to
WO-010?"; and "which QUIET meeting rooms are free tomorrow afternoon?" now names availability under
"Not checked" (BUG-1615) instead of implying it was checked. One is still weak: **"How much energy
did the solar panels produce on Wednesday?" reads ten days and says no kWh exists**, because a bare
weekday is resolved by nothing deterministic (CAVEAT-1616) — and that is **deferred for the study
freeze: 25 of the 56 study texts name a weekday**, so changing weekday resolution now would move
study answers.

Every new rule was measured on the 4,060-question bank before it was kept; most move 0 bank
questions because conversation phrasings ("the two", "its", "who is assigned", "what time does it
close") are rare in single questions. **Still open:** the deliberation lane cannot check availability for a named period
(CAVEAT-1617; it now says so); a two-subject amenity question ("which floors have accessible
toilets and where is baby changing?") declines under the capability subject test (CAVEAT-1618,
the live test `test_floor_word_does_not_steal_capability` fails on it; not caused by this round);
a follow-up that only changes the place ("what about room 2.53?") drops the "too humid?" judgement
(CAVEAT-1619); and a clarification the user ignores ("and the CO2?" after "which one do you
mean?") is answered for the room the classifier picked from the previous reply, which the answer
now names but does not flag as assumed.

## Round 6 — a second, NEW conversation battery (tracker BUG-1620 … BUG-1626)

Ten new conversations (`docs/phase0/conversations_r6/`, 30 turns) written after round 5's fixes, to
see whether they generalise to new follow-up shapes. Most did: a possessive ("what's its leaving
water temperature?" → the chiller only, then "and the boiler's?"), a per-floor count of water
meters, "compare it with room 3.16" then "which is quieter?", "and the day before?" on floor
humidity, the nearest toilet after the nearest drinking water. Seven new defects, all fixed and
re-asked live; **one was a regression from round 5's own fix**:

- **"What's the temperature in office 4.07?" → "I can't find 'office 4.07'"** (BUG-1624, P1): the
  v2 compound router read "in office" as choosing an office, and the deliberation lane could not
  match "office 4.07". A kind plus a dotted id is now one named place (0 of the 451 bank
  questions that select spaces change). Now 22.3 °C.
- **The rewrite invented a year** (BUG-1620, P1): "plot it" became "… on Saturday, 10 October
  **2023**", and since written years are authoritative the chart found nothing. A year that no
  message contains is now removed, and the rewrite prompt keeps "today" as "today".
- **Record ids were cut at their first number** (BUG-1626, P1, *my regression from BUG-1603*):
  "the second one" of a contract list became "CON-2025", which two contracts share. Ids now keep
  every part, and Unicode hyphens are normalised. Now "CON-2025-003 — Clearview Facilities …
  ends 4 November 2026".
- "how much was that?" after "Floor 4 used the most electricity" is answered (BUG-1625); "when was
  it highest?" keeps the CO2 instead of becoming "when was floor 2 highest?" (BUG-1623), and a
  single day's peak is that day's hours, not "usually around 14:00" (BUG-1622); **a per-hour
  breakdown is now plotted as a line chart** (BUG-1621; verified: two charts linked and loading).

**Open from round 6 (minor, no study shape):** "is it working?" after the nearest drinking water
reads the room's sensors, not the water point's status (CAVEAT-1627); "what did they record
yesterday?" after a count of water meters declines (CAVEAT-1628). A follow-up that turns "the day
before" into "Thursday, 8 October" (no year) cannot be resolved to a window — the deferred weekday
and date family (CAVEAT-1616).

## Checks after round 5 (late evening)

**Regression gate, run alone after every round-5 change:** 49 of 51 recorded, flagged #37 and #70 —
both read: #37 is the fresh-chat recall case ("Nothing has been asked in this conversation yet"),
#70 the correct "no air-pressure sensor recorded for Room 2.01" decline the classifier misreads.
**51/51 in substance**; #17, the intermittent of the evening run, answered first time. Median
13.0 s, slowest 78.3 s, 15.2 min in total
(`scripts/outputs/regression_answerability_20261010_211559.json`).

**Unit suite (bldg1 active), run alone after round 5:** 15,565 pass, 2 fail, 30 error, 79 skip
(61 min). All 32 are the known state-dependent set (CAVEAT-1500: 30 errors in three files that
read parked paths, 2 failures comparing against the active `.env`), the same count as the
morning; none is new.

**After round 6, the gate again, alone:** 49 of 51 recorded, the same two misreads (#37, #70), so
**51/51 in substance**; median 14.1 s, slowest 77.1 s, 17.3 min
(`scripts/outputs/regression_answerability_20261010_232123.json`). **Unit suite after round 6, the last measurement of the session:** 15,583 pass, 2 fail, 30 error, 79 skip (61 min) — again exactly the CAVEAT-1500 set, nothing new.

## Checks on the final build (evening)

**Unit suite, bldg1 active, run alone after rounds 3–4:** 15,494 pass, 6 fail, 30 error, 79
skip. The 30 errors and 2 of the failures are the known state-dependent set (tests that read
parked paths or compare against the active `.env`; CAVEAT-1500, same count as this morning). The
other 4 failures were mine and are fixed: the PV shape rule had been written into the service,
which a test forbids (moved to `scripts/derive_generation_shapes.py`); a unit test pinned the raw
token "degF" (now printed °F); and this morning's register period filter narrowed a "which rooms
have sessions this week?" grouping to nothing (BUG-1597). The affected files re-run green; the
full suite was **not** re-run after those fixes, so the expected 15,498 / 2 / 30 is not a
measurement.

**Regression gate, run alone on the final build:** 48 of 51 recorded, flagged #17, #37, #70.
#37 is the known fresh-chat case; #70 is a correct decline ("no air-pressure sensor listed for
Room 2.01") that the gate's classifier misreads (CAVEAT-1415). **#17 ("What is the average CO2
on each floor right now?") declined once — the relevance gate judged that narration off-topic —
and answered 3 of 3 when re-asked.** It is an intermittent, and it counts as a first-pass
failure, not a pass. Median 14.4 s, slowest 57.1 s, 16.5 min in total; orchestrator memory
1.1–1.8 GiB over the run.

## Data added or corrected (all synthetic, no study referent touched)

- **Occupancy made coherent:** room counts bounded by space kind, floor counters = sum of their
  rooms, presence from the room's count — and the boot-time map rebuild now keeps this (two TTL
  uploads had silently reverted it, BUG-1540). This week's history (3–10 Oct) rescaled to match,
  with a full backup in `outputs/backups/`.
- **Registers brought up to date:** 10 work orders (Sep–Oct 2026), 4 incidents (Sep 2026), an
  HVAC/chiller maintenance contract.
- **Amenities:** EV charging at the ground-level parking; the ground-floor "study area" that had
  been placed in a mechanical plant room removed.
- **Vocabulary (TTL-first):** contract and work-order lay terms, "who cleans", the water-use /
  water-flow split, "muggy" — every source CSV edit regenerated through its generator.

## Checks after every change was in

**Regression gate, run alone (`scripts/regression_answerability.py`, 51 cases):** the script
recorded 49 of 51 steady and flagged #37 and #68. Both answers were read:

- **#37** ("the evidence behind your answer about the coolest room") is the known apparatus
  case: the gate asks it in a fresh chat with no earlier answer, and the system correctly says
  there is no earlier answer to explain. Same shape as BUG-1397 and every gate since 3 October.
- **#68** is a correct decline worded in a way the gate's decline classifier does not list
  ("it cannot answer what this question asks"). The answer asserts nothing.

So **51/51 in substance**; median 12.7 s, slowest 68.2 s, 15.6 min in total
(`scripts/outputs/regression_answerability_20261010_145819.json`). Orchestrator memory stayed
flat at about 4.6–4.8 GiB through the run. That is higher than the ~2 GiB measured on 30
September, but it did not climb.

**The four development forms (S1-D … S4-D), re-asked after the changes:** all four answer as
before. One answer changed its form: S3-D (radon in a room) used to be a short decline and is now
"No — radon is not measured in Room 4.09", because place-scoped "what is measured" questions now
reach the observability lane. Both forms are correct. If the study's answer key quotes the old
wording, check it.

**Future comparisons, re-asked after the last edit:** "Will floor 3 be warmer than floor 4
tomorrow?" and "Will floor 2 be cooler than floor 5 tomorrow?" are each answered from two separate
forecasts. In both cases the 80% bands overlap, so neither answer names a warmer or cooler floor,
and the "cooler" question keeps its own word. Each forecast was trained on 85–169 hourly points,
because the readings fetch stops at 1,000 rows (the answer says so).

## Open, and what needs the owner

1. **CAVEAT-1527 (P1 for online sessions): chart images and floor-plan links are built on
   `http://localhost:8080`.** They render on this machine and in no browser that reaches Open WebUI
   through the Cloudflare tunnel. Route the public hostname's `/static` and `/floor-plans` (or a
   second hostname) to `127.0.0.1:8080` and set `STATIC_BASE_URL` in `.env`. No code change.
2. Water used "yesterday" is now honest (it declines a total) but not answered: the building's
   `litres/day` usage point has no well-defined generated shape for a daily total (CAVEAT-1562).
   The EV charger state points report 0/1 codes with no declared meaning, so "are the chargers
   available?" gives the codes, not "available"/"charging".
3. ~~`ontosage_route.overrides_applied` is empty even when contract rules fired (CAVEAT-1526).~~
   Fixed and verified live the same day: it now lists `contract:` plus the parse and concept rules
   that fired.
4. **Deferred for the study freeze (they move study answers):** a bare weekday ("on Wednesday")
   resolved to that day (CAVEAT-1616 — 25 of the 56 study texts name a weekday), and the items
   listed under Round 3 (CAVEAT-1577/1578/1583, the boilers' water typing, re-grading the stale
   forecast-skill registry CAVEAT-1594). Each is a small change once the study data is collected.
5. Open from round 5, none a study shape: availability for a named period in the deliberation lane
   (CAVEAT-1617, now stated as not checked), a two-subject amenity question (CAVEAT-1618), a
   place-only follow-up dropping its judgement (CAVEAT-1619).
6. Nothing is committed. Park bldg1 and run both commit gates first (CLAUDE.md, Workflow rule 8).
