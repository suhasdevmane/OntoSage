# QA probe rounds, 11 October 2026 — stakeholder intent coverage

Plan: [`tasks/PLAN_2026-10-11_STAKEHOLDER_INTENT_COVERAGE.md`](../../tasks/PLAN_2026-10-11_STAKEHOLDER_INTENT_COVERAGE.md).
All asks went through `scripts/qa_probe.py` (Open WebUI's headers, `/v1/chat/completions`,
streamed, all four caches flushed per ask) as the QA account `facility03@example.com`. Nothing
here is a study form, study room or study wording. Bank questions are counted, never printed.

**PASS in the probe means "routed and delivered", not "correct".** Every answer below was read
by hand; where the probe's decline detector and the read disagree, the read is what is reported.

## M1 — role-stratified bank sample (before the day's fixes)

208 questions: 4 per catalogue role + 60 from the synthetic bank, seed 20261011, excluding the
v1–v3 bank samples. **50/208 declined (24.0%), 0 transport errors, median 15.2 s.** "Declined"
includes correct declines: five are the right "which room do you mean by *this room*?".

| Group | n | declined |
|---|---|---|
| IT | 5 | 3 |
| BMS / M&E | 11 | 5 |
| Space / timetabling | 24 | 8 |
| Facilities / estates | 22 | 7 |
| Students / academics | 37 | 10 |
| Visitors | 14 | 3 |
| Accessibility | 9 | 2 |
| Energy / leadership / finance | 18 | 4 |
| Cleaning / waste | 12 | 2 |
| Safety / security | 28 | 3 |
| Researchers | 8 | 1 |
| Assurance | 12 | 1 |
| Architects | 4 | 0 |

What the declines said was missing, clustered from the answer text: the diagnosis lane declined
6/6 (BUG-1636); compare/trend of RECORDS were sent to series lanes (BUG-1638, 8 turns); a ranking
said the building had no energy sensors when no ROOM had one (BUG-1631); "StudyArea" was looked up
as a room name (BUG-1632); a waste answer listed "Series 1 … 10" with no units (BUG-1639).

## r7 — 142 own questions, 13 stakeholder groups (`scripts/qa_probe_questions_r7.yaml`)

Run on the build with batches 1–5 deployed: **23/142 flagged by the detector, median 18.1 s.**
The first 44 answers on the pre-batch build are kept as `r7_pool_partial_pre_b5.jsonl`.

| Group | n | flagged |
|---|---|---|
| students / academics | 12 | 1 |
| visitors | 10 | 1 |
| accessibility | 10 | 0 |
| facilities / estates | 12 | 1 |
| BMS / M&E | 12 | 1 |
| energy / leadership / finance | 12 | 1 |
| safety / security | 12 | 2 |
| cleaning / waste | 10 | 3 |
| space / timetabling | 12 | 4 |
| IT | 10 | 3 |
| researchers | 10 | 1 |
| assurance | 10 | 2 |
| architects | 10 | 3 |

**The hand read found wrong answers the detector passed**, and these are the ones that matter:
"What condition is the roof in?" answered with the single letter "C" (fixed: a fragment is
declined); "How many sensors are connected and reporting?" → "18 sensors" (fixed: the freshness
sweep answers it — 3,543 of 3,543); "When was the sensor data last updated?" → "no timestamp"
(fixed, same lane); "What units are the illuminance readings in?" → "not recorded" (fixed: lux);
"Were any doors left open after hours?" bound ENERGY meters (fixed: lay terms); "Where are the
network cabinets?" → "No floor plans are available for the Abacws Building Building" (fixed);
"What was the average occupancy of the building this week?" declined (fixed: the sum of the floor
counters' means). Water use, its cost and electricity cost are now computed (below).

**Deferred past the study freeze** (each touches the ranking lane or v2 compound routing, which
study answers depend on): CAVEAT-1649 (hearing loop in a meeting room), CAVEAT-1650 ("rooms that
hold 30 and have a projector" read capacity as the occupancy sensor), "Which kitchens are busiest
at lunchtime?" (ranked labs), "How busy is floor 4 on weekdays?" (answered floor 5 now), "What's the
temperature in the server room?" / "Are any telecom rooms overheating?" (the compile could not map
the room kind).

## Data and capability added (all non-study topics)

- **Building water meter** (TODO-1633): litres per 15-minute interval since 1 June, the publisher's
  own shape (working-day peak, weekends ~1/4); bound ALONE for whole-building questions (BUG-1640:
  it had been summed with its 18 floor meters). Live: yesterday 3,449 L; week on week 66,882 L
  against 66,494 L.
- **Utility cost** (TODO-1646): metered total × the registered tariff in force, standing charge per
  day, "rates exclude VAT", no figure when no single tariff covers the period; tariff rate units
  transcribed from the tariff document as triples. Live: water last week ≈ £130.09; electricity
  yesterday ≈ £699.79.
- **Kitchens** (TODO-1634): the four kitchen/break rooms located as amenities, repeating the catering
  topic's own statement about microwaves and filtered water (floors 2–4).
- **Exports** (BUG-1644): CSV / PDF / Word written in the format named, LINKED in the reply, rows
  carrying sensor name and unit, documents carrying a per-sensor table, the period and (kWh/L) the
  total. **Floor plans** (BUG-1645): the render shown inline, the PDF linked, no IRI.

**Not authored, on purpose** (NOTE-1635): lockers, vending machines, a UPS, work-order due dates
and a maintenance response-time policy — the building's own text states none of them, and a
location or policy invented for a real building is a plausible wrong answer.

## Named weekdays and the study (CAVEAT-1616)

The weekday resolver was deferred on 10 October because 25 of the 56 study texts name a weekday.
Re-measured 11 October: those 25 fields all carry a full date with a year, which the explicit-date
path resolves first, so **0 study fields are newly bounded**. Residual: a participant who types
"on Wednesday" WITHOUT the task's date now gets the most recent Wednesday, where before they got the
default recent window — neither is the task's date, so it is not worse, but the study key should
expect the date to be stated.

## Afternoon — the 13 stakeholder conversations re-run (`docs/phase0/conversations_r7/`)

Each conversation is three turns as one role would ask them; every answer was read in full. On the
build with the morning's fixes deployed, the first turns were mostly right and **the follow-ups were
where it broke** — the same lesson as round 5.

**Fixed and verified live** (rows BUG-1660…1671, TODO-1668):

| Turn | Was | Now |
|---|---|---|
| "How much electricity did the building use last week?" | 15,148 kWh "from 27 September **2023** 23:00 to 04 October 2023" (year invented, bounds UTC) | 15,148 kWh, Mon 28 Sep 00:00 – Sun 4 Oct 23:59 (building time), per floor |
| "how does that compare with the week before?" | "No readings were found" (the rewrite copied the invented year) | 15,148 against 12,570 kWh, up 20.5 %, each floor's total |
| "which floor used the most?" | never rewritten → declined | Floor 4, 2,632 kWh |
| "how long has CO2 been recorded?" | "the data does not include timestamps" | since 1 January 2025, **no readings April 2025 – February 2026** (new: `services/record_span.py`) |
| "export the CO2 readings for floor 3 for last week as CSV" | 30 days exported | last week's rows ("for last week" is the calendar week; "over the last week" is still a trailing duration) |
| "Which compliance checks are due this month?" | "No record matches (completed date …)" | the 2 checks whose due date is in October |
| "who owns them?" | "…does not record october" | the two checks and their roles |
| "is the server room temperature okay?" | humidity | the three server rooms' temperatures |
| visitor: "where do I go when I arrive?" | declined | the visitor policy (sign in at main reception) |
| "When was the fire alarm last tested?" | "The most recent last tested on on record" | "The most recent last tested date on record is 9 September 2026" |
| "Where is the fire assembly point?" | a raw document chunk with a table row | three sentences from the procedure |

**Still open** (each has a row): the AHU "is the difference normal?" binds one of the two series
(TODO-1672); a 125 m² "Restroom (Male)" is ranked the largest room on floor 2 — a floor-plan polygon,
not the ranking (CAVEAT-1673); "what about floor 4?" after a clarification loses the study frame
(TODO-1674); "which floor produces the most waste?" lists bin locations (TODO-1675).

## M1 re-asked on the final build (same 208 questions, same account)

**Declined 50/208 before and 50/208 after — the day's fixes did not move this sample's decline
count.** 15 moved declined → answered and 15 answered → declined; median 17.5 s (was 15.2 s). Reading
the 15 new "declines" (answers only): about nine were declines in the baseline too, in a wording
the detector did not count ("I did not find any answer in the records I searched", "I couldn't map
part of your request"); two replaced a weak answer with an honest decline (advice invented from
noise sensors; a ranking recommending the main reception); one is now a clarification ("Which
space should I check?"); two are answers the detector misread; and one is a routing change caused
by classifier variance (`recommend` instead of `deliberate`, then `event_store_query` moved it to
the events lane — CAVEAT-1677). **Read this as: the detector's decline count is too noisy to show a
change of this size; it is not evidence of improvement or of regression.** The fixes were aimed at
the conversations and the stakeholder pools, where each one was verified by re-asking.

## Gates

- **Regression gate, alone, 08:50: 50/51 recorded, 51/51 in substance** — #37 is the known apparatus case
  (a recall question asked in a fresh chat; the answer "Nothing has been asked in this conversation
  yet" is correct). #70, which misread in recent runs, passed.
- **Unit suite, bldg1 active, after every afternoon change: 15,811 pass / 3 fail / 30 error / 79
  skip / 6 xfail.** 2 fail + 30 error are the known parked-path set (CAVEAT-1500). The third was
  mine (BUG-1676: the water-meter TTL declared `ontosage:isSimulated`), fixed and its files re-run
  13/13 — so the expected clean figure is the CAVEAT-1500 set alone, not re-measured as a full run.
  The run took 63 minutes with an M1 probe on the stack for part of it; do not quote the duration.
- **Regression gate, alone, final build (13:39): 50/51 recorded, 51/51 in substance** — #37 again
  the fresh-chat recall case. Orchestrator memory went 1.0 → ~4.2 GiB and then held ~3.9 GiB, the
  same plateau as the morning run; flat, so not BUG-1194's climb, but the old ~2 GiB reference
  needs re-baselining.

## Owner decisions waiting

1. **NOTE-1652** — 1,164 OPEN user_reports, nearly all from testing (rules_engine 735, admin 194,
   facility01 115, qatest 49, openwebui_user 38, …): the study's "how many faults this month?"
   will count them. Archive before the study.
2. NOTE-1635 — supply real locations for lockers / vending, if they should be answerable.
3. CAVEAT-1527 — remote access needs `STATIC_BASE_URL` and the `/static` + `/floor-plans` routes;
   on this machine every chart, plan and export loads from `localhost:8080`.
