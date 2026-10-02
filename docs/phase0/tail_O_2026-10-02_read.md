# Tail O — third read (2026-10-02, overnight round)

Same 60 questions (`tail_O_questions.txt`, sha `7f3681c3…`), same reader, same identity
(`occupant01`, `role=occupant` confirmed from the server's own `[forwarded-user]` line), same
endpoint (`/v1/chat/completions`, streaming), every answer recorded in full
(`tail_O_2026-10-02_occupant_after2.md.jsonl`). **Zero** breaker-open lines during the run.
Nothing differs from the two earlier reads but the build.

| label | before (10-01) | after round 4 (10-01) | after round 6 (10-02) |
|---|---|---|---|
| GOOD | 24 | 26 | 28 |
| DECLINE-OK | 12 | 16 | 23 |
| **DECLINE-BAD** | **11** | **11** | **4** |
| WEIRD | 13 | 7 | 5 |
| **FABRICATED** | **0** | **0** | **0** |
| **ACCEPTABLE** | 36/60 = 60.0% | 42/60 = 70.0% | **51/60 = 85.0%** |

12 moved into acceptable, 3 moved out, 45 unchanged.

## Moved in (12) and whether a fix is responsible

| # | question | now | attributable |
|---|---|---|---|
| 10 | areas under maintenance restrictions | ClosurePeriod answers: none current, 10 closures listed | yes — ClosurePeriod lay terms |
| 16 | are all doors equipped with sensors | clarification (which space) | variance |
| 20 | power saved? | honest decline | variance (was DECLINE-BAD by a stricter reading) |
| 21 | are the doors locked | documents cannot state the current state | yes — `is_live_state_question` |
| 23 | hearing everything | general knowledge, labelled | variance |
| 41 | lifts learn the cafeteria floor | honest decline from documents (gate no longer refuses "cafeteria") | yes — lay-term referent check |
| 42 | function of your building | "primary function: Education" | yes — vocabulary + facet + contract fingerprint |
| 43 | free parking spots | 0 free, from the one parking point | yes — binder (BUG-1411) |
| 51 | CO2 sensors forcing ventilation | honest decline | variance |
| 53 | Room available now? | six booking-status rooms, all free | variance (the gate did not delete it this time) |
| 55 | fire pull stations | honest decline — the graph holds no call-point record (checked) | relabelled on evidence |
| 57 | keep the most important systems running | two continuity provisions in full | yes — lay terms + the register decline honouring them |

Seven of twelve are attributable to a change made for them; five are CAVEAT-891 variance.

## Moved out (3)

| # | question | now | cause |
|---|---|---|---|
| 27 | purity of the drinking water | lists the three drinking-water points, says nothing about purity | WEIRD — the amenity answer displaced the earlier honest "no purity measurement is available" |
| 32 | is any area overheating right now | **deleted by the relevance gate** ("does not give a direct yes/no") after binding the 288 room-air sensors | the gate; now protected for the yes/no threshold shape (12 of 4,060 bank questions), re-ask owed |
| 39 | adjust temperature based on crowding | deleted by the relevance gate; the HVAC Zoning topic holds the answer | the gate; deliberately NOT protected (control-behaviour question; BUG-1252's pinned gap) |

## Still unacceptable (9)

DECLINE-BAD: #7 lights adjusting (Lighting topic holds the answer; `automation_capability`
rejected as a route because it would contradict the topic), #32 (above), #39 (above),
#56 "is the people count used to monitor employees" (257 counters; "couldn't find sensors
matching people count").
WEIRD: #9 chiller (energy figures; the HVAC regime document names the single chiller), #27
(above), #29 warmer than the lobby (outside-air temperature only, BUG-879 family), #36 flow
rate (unitless mixed-scale aggregate), #48 "what jobs can you do" (read as the work-order
register).

## Residual noise worth a row

#43 says "unit not recorded" for the parking point: `unit_for_sensor` now prefers the
label-discriminated modality (CAVEAT-1412), but this path did not consult it — a separate
unit lookup; not diagnosed.
