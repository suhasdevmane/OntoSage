# Tail P — first read (2026-10-02, drawn and asked overnight)

60 unseen questions from the real survey corpus (`scripts/draw_tail.py --name P --n 60 --seed
20261002`, `tail_P_questions.txt`, sha `d0c47eb6f1f7da12f9098fb1f889c2f2cf01d0b8182ef8b6d169c97f241eebf5`).
Asked as `occupant01` on `/v1` streaming (role confirmed from the server's `[forwarded-user]`
line), every answer recorded in full (`tail_P_2026-10-02_occupant.md.jsonl`), **zero**
breaker-open lines during the run. One reader, the same as tail O's three reads.

**Two questions overlap tail O** (#57 "vampire power", #60 "weekends vs weekdays" in a variant
spelling): the draw's exclusion misses a stored file. They are labelled here regardless.

**This is the number to quote for readiness, not tail O's 85%:** tail O has been fixed
against three times and is tuned-on; tail P had never been asked.

| label | count |
|---|---|
| GOOD | 13 |
| DECLINE-OK | 26 |
| **DECLINE-BAD** | **7** |
| WEIRD | 14 |
| **FABRICATED** | **0** |
| **ACCEPTABLE** | **39/60 = 65.0%** |

Unacceptable 21/60 = 35.0%: WEIRD 23.3%, false declines 11.7%.

## Labels

| # | label | note |
|---|---|---|
| 1 | DECLINE-OK | "interact with other buildings" |
| 2 | DECLINE-OK | "top source of indoor pollution" — vague |
| 3 | DECLINE-OK | conceptual; occupancy locked for the role anyway |
| 4 | **DECLINE-BAD** | CO reading near the boiler room: CO sensors and a plant room exist |
| 5 | DECLINE-OK | |
| 6 | WEIRD | "the system can automatically activate ventilation" — a capability the records do not state, beside real readings |
| 7 | DECLINE-OK | |
| 8 | WEIRD | honest first line, then an irrelevant sensor-count snapshot per space |
| 9 | GOOD | |
| 10 | DECLINE-OK | |
| 11 | **DECLINE-BAD** | sustainability certifications: the Sustainability topic states BREEAM 'Excellent' |
| 12 | **DECLINE-BAD** | energy spikes: energy series and an anomaly lane exist |
| 13 | DECLINE-OK | unintelligible |
| 14 | DECLINE-OK | honest register decline |
| 15 | DECLINE-OK | |
| 16 | DECLINE-OK | honest: no access-control field |
| 17 | GOOD | general guidance, labelled |
| 18 | WEIRD | self-description answered a building question |
| 19 | WEIRD | temperature sensors listed for an "excessive power" question |
| 20 | GOOD | policies |
| 21 | DECLINE-OK | |
| 22 | **DECLINE-BAD** | "how would it know about noise in one section": 233 noise sensors by room |
| 23 | WEIRD | a noise table for "where does the noise come from" |
| 24 | GOOD | |
| 25 | DECLINE-OK | |
| 26 | DECLINE-OK | clarification |
| 27 | GOOD | |
| 28 | DECLINE-OK | |
| 29 | GOOD | consistent with the HVAC zoning topic |
| 30 | WEIRD | "0.0 = idle … operating normally" inferred from a status flag |
| 31 | DECLINE-OK | |
| 32 | WEIRD → fixed | boiler/chiller water (70 °C) in a room-temperature aggregate on the `recommend` lane; now 288 sensors / 21.8 °C (BUG-1405 part 2, verified live) |
| 33 | DECLINE-OK | clarification |
| 34 | DECLINE-OK | |
| 35 | WEIRD | floor energy meters presented as a server rack's standby load |
| 36 | DECLINE-OK | |
| 37 | DECLINE-OK | |
| 38 | DECLINE-OK | |
| 39 | GOOD | water-safety measures from the hazard controls |
| 40 | WEIRD | outside-air temperature only |
| 41 | GOOD | |
| 42 | WEIRD | an invented "how detection works" procedure beside real flow readings |
| 43 | WEIRD | "boiler type cannot be determined" — the graph holds Gas Boiler 1 and 2 |
| 44 | GOOD | |
| 45 | WEIRD | outside-air temperature; REG-009 (server room cooling) exists in the HVAC regime |
| 46 | **DECLINE-BAD** | entrances open: door contacts exist and were cited as a source |
| 47 | WEIRD → fixed | "air quality on one floor only; the other 5 have no sensor" from 34 of 68 handed; the coverage sentence now asks the graph (BUG-1414, verified live) |
| 48 | DECLINE-OK | clarification |
| 49 | GOOD | |
| 50 | GOOD | |
| 51 | WEIRD | an occupancy-sensor list for "how is comfort maintained" |
| 52 | GOOD | |
| 53 | **DECLINE-BAD** | lights adjusted automatically: the Lighting topic states it |
| 54 | DECLINE-OK | RBAC |
| 55 | DECLINE-OK | |
| 56 | GOOD | |
| 57 | DECLINE-OK | |
| 58 | DECLINE-OK | |
| 59 | DECLINE-OK | |
| 60 | **DECLINE-BAD** | weekends vs weekdays energy: the series exist |

## The shape that dominates WEIRD

Eight of fourteen (#19, #23, #30, #35, #40, #42, #45, #51) are a "how does / what does the
building do" question answered by the reading lane with a table of readings — right subject,
wrong kind of answer. The register and topic lanes hold the real answers for several of them
(#43 Gas Boiler, #45 REG-009, #53 Lighting). This is the next class to work on, and it is a
routing class, not a narration one.
