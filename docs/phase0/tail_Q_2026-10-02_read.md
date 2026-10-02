# Tail Q — first read (2026-10-02, drawn after the mechanism-routing fix)

60 never-asked questions from the real survey corpus (`scripts/draw_tail.py --name Q --n 60
--seed 20261003`, `tail_Q_questions.txt`, sha `43c7699415f8e278…`, **zero overlap** with tails O
and P). Asked as `occupant01` on `/v1` streaming, every answer recorded in full
(`tail_Q_2026-10-02_occupant.md.jsonl`), **zero** breaker-open lines. Same reader as tails O/P.
Build: after BUG-1415 (mechanism routing), BUG-1397, BUG-1414, BUG-1405 part 2, with the QA
access map open.

| label | count |
|---|---|
| GOOD | 10 |
| DECLINE-OK | 31 |
| **DECLINE-BAD** | **7** |
| WEIRD | 12 |
| **FABRICATED** | **0** |
| **ACCEPTABLE** | **41/60 = 68.3%** |

Tail P on the previous build read 65.0%; the two sets are different questions, so this is
consistent-with, not evidence-of, improvement. Tail Q is a harder draw: 31 of 60 are questions
the building genuinely cannot answer (coffee machines, drugs, animals, floods, apartments) and
the honest decline is the right answer for every one of them.

## Labels

GOOD: 1 (lobby palette — general knowledge, labelled), 3 (fire-safety zones), 15 (lifts, with
the staleness caveat), 22, 31 (overcrowding detection — automation lane, grounded), 41 (NO2 by
floor), 43 (humidity by floor), 47 (air quality, with the honest coverage sentence), 54 (water
today), 57 (energy now, with boundary).

DECLINE-OK (31): 4, 6, 8, 9, 10, 11, 13, 16, 18, 19, 20, 23, 24, 25, 26, 27, 28, 29, 30, 32,
35, 36, 38, 39, 42, 48, 49, 50, 51, 52, 53 — clarifications for "here", honest "not recorded",
and register declines that name what the register does hold.

DECLINE-BAD (7): #5 "how do you detect if someone is inside" (PIR/occupancy topics exist;
mechanism shape reached the capability lane and found no subject topic), #7 "is water supply
okay" (flow sensors exist; went to capability), #12 "how does the system maintain fresh air
when many people are in the same area" (classifier said `general_guidance`, which is not a fetch
intent, so the mechanism handoff never saw it; REG-00x CO2 < 1000 ppm is the answer), #37
motion-sensor invasiveness (the governance document answers it), #46 empty rooms with lights on
(occupancy + illuminance both exist; a cross-quantity join no lane makes), #55 how many
bathrooms (24 ToiletFacility records; "bathrooms" is not a declared lay term — TTL fix), #56
rooftop terrace (the green roof is "on the second-floor terrace"; the referent gate refused).

WEIRD (12): #2 walkway advice with invented rules ("motion count < 5 for > 5 min"), #14 PIR
"0 people when still" inference, **#17 and #60 — QUESTIONS routed to the `control` lane and
refused as commands** ("if 3 people enter … do the lights turn off?", "do ozone sensors alert
people or just activate ventilation?"), #21 presentation power inferred from floor kWh, **#33
"nearest bathroom" answered relative to Room 0.01 without being told where the asker is**, #34
sustainability topic for a how-to, #40 temperature-sensor list for standby power, #44 "HVAC is
operating efficiently" from a temperature table, **#45 "can you clean graffiti by yourself?"
FILED AS A MAINTENANCE TICKET (REP-EB3D5D)**, #58 sensor-count dump for ozone, #59 invented
allergy-season recommendations.

## New rows

BUG-1417 (questions reaching `control`), BUG-1418 (a question filed as a ticket — a side
effect, so testers should know tickets may appear), BUG-1419 (a "nearest" answer assuming the
asker's location). Not fixed in this round: each needs its blast radius measured over the
bank, and the control/report precedence rules have been tuned twice already (BUG-200,
BUG-1241).
