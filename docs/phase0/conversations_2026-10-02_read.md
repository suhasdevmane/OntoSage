# Multi-turn battery, hand-read — 2026-10-02 (Phase 1.2 of the QA-trial plan)

**Apparatus.** 20 short conversations (`docs/phase0/conversations/c01..c20_*.txt`, 47 turns as
recorded), each run as ONE chat through `/v1/chat/completions` with streaming by
`scripts/run_conversations.py`, identity `occupant01@example.com` confirmed from the server's
own `[forwarded-user] … (role=occupant)` line (47 of 47). All three caches flushed first. Every
answer recorded IN FULL in `conversations_2026-10-02_occupant.jsonl`; this read was made from the
full text (`scripts/outputs/_conv_dump.txt`), not a window.

**What was measured.** Not the first turn of each conversation (those are tail-style questions
and were read elsewhere) but the FOLLOW-UP turns: 27 of them. The question is whether a second
or third turn that leans on the conversation is resolved from it.

## The number

| follow-up turns | good | acceptable decline | wrong / weird | false decline |
|---|---|---|---|---|
| 27 | 12 | 2 | 9 | 4 |

**14 of 27 (51.9%) acceptable.** No fabricated figure in any turn.

## The shape that works, and the shape that does not

Every follow-up that SUPPLIES a value works: "2.01" after "which room?" (c01), "what about room
2.01?" (c05), "and the CO2 there?" after the user named 2.01 (c01), "plot that" (c14), "when is the
next one due?" (c17), "who do I contact?" (c09), "is that healthy?" (c07).

Every follow-up that POINTS AT WHAT THE ASSISTANT JUST SAID fails, and the four causes are
distinct:

| conv | turn | what happened | cause |
|---|---|---|---|
| c02 | "what is the temperature in the first one?" after a list of ten rooms | no rewrite; a decline naming three registers | the rewrite has no notion of an ordinal into the previous reply |
| c03 | "how warm is it there?" after three kitchens | the model rewrote it CORRECTLY to room 2.66; `rewrite_invents_a_place` rejected it (BUG-940's guard); answered building-wide | the guard cannot tell "a room the assistant named six turns ago" from "a room in the reply being replied to" |
| c06 | "what is the status of that report?" after "logged as REP-EF64E3" | the id dropped; the generic complaints topic; "_Taking 'that' as floor 2_" | nothing carries a report id across turns |
| c13 | "is it free this afternoon?" after the register named Room 1.06 | declined | same as c03: the reply's only room, refused by the guard |
| c19 | "the first one, is it booked today?" after three projector rooms | **159 bookings for the building** — wrong scope, presented as the answer | same as c02 |
| c05 | "which of the two is busier?" after the user asked about 1.06 then 2.01 | a clarification asking which two | the model rewrite returned the text unchanged; both rooms are the USER's own words |
| c08 | "I am in room 3.01" after "where's the nearest toilet?" | answered from the documents ("do not answer this") | a bare location statement is not recognised as a re-ask of the previous question |
| c20 | "what can I ask you?" | declined | `is_self_question` had "what questions can I ask" and "what can you do" but not this phrasing |

Fixes for all eight are deterministic and read ONLY the reply being replied to or the user's own
earlier turns (`context_switch.resolve_ordinal`, `resolve_report_reference`,
`previous_reply_named_it`, `ambiguous_reference`, `resolve_location_statement`,
`resolve_pair_reference`; the self-description regex). BUG-940's case — a room from a reply
that is NOT the one being replied to — is pinned as still refused.

## Residue, logged, not fixed here

- **c04** "which one did you check?" after "all 2 lifts are operational" → the accessible-route
  register. A question about the PROVENANCE of the previous answer has no lane; session_recall
  keeps questions, not answers, by design.
- **c12** "what is the evidence behind your answer?" → session_recall: *"I have no record of you
  mentioning 'evidence', 'behind' or 'answer'"*. Same family as c04 and BUG-1397's question.
- **c10** "How much energy did the building use yesterday?" declined, then "and the day before?"
  ANSWERED the window 30 Sep 23:10 – 01 Oct 22:55 (which is yesterday, labelled as the day
  before), then "which was higher?" could not compare. The energy-by-named-day shape (BUG-540's
  family) is unstable across asks.
- **c11** "when was it last comfortable?" → *"the last time Room 5.08 met ALL listed standards
  was 11:45:13"* in the same paragraph that marks CO₂ ❌ non-compliant with WELL v2 at that time.
- **c16** "which doors do you have records for?" → a refuge-point record. Door contact sensors
  and door access events exist.
- **c18** "what time does it close?" / "is it open on saturdays?" after the café answer → the
  BUILDING's working hours (closes 22:00), not the café's (16:30). An anaphor over an amenity
  resolves to the nearest topic, not the amenity.
- **c15** "forecast it for the next 6 hours" after "no noise measurement for the atrium" → a
  generic capability decline rather than "there is no noise series to forecast".
- **c03** "and yesterday?" after a turn that itself failed: declined. Inherits the failure.
- **c07** "why?" → a building-wide diagnosis, not floor 3's.

## What this does and does not establish

Twenty conversations I wrote. They were written to exercise the follow-up shapes a trial user
produces, not drawn from a corpus, so 51.9% is a measurement of these shapes, not of the trial
population. The re-ask after the fixes is read below.

## The re-ask (same conversations, same identity, same endpoint; three passes)

Eleven conversations: the eight that failed plus three single-turn checks (c21/c22 for Phase 1.5,
c23 for 1.3). Files `conversations_2026-10-02_reask1.jsonl`, `_reask2.jsonl`, `_reask3.jsonl`,
every answer in full.

**Pass 1** (resolvers placed AFTER the follow-up gate): c06, c13 and c19 fixed; c02, c05 and c08
unchanged — no log line, no error. `_is_followup_query` had returned False before the resolvers
were reached ("one?" split on whitespace is not "one"; a location statement has no marker word).
Lesson #188.

**Pass 2** (resolvers BEFORE the gate):

| conv | follow-up | pass 2 | verdict |
|---|---|---|---|
| c02 | "what is the temperature in the first one?" | the reading of node 2.13, 24.49 °C | GOOD |
| c03 | "how warm is it there?" (three kitchens) | still building-wide: the clarification was raised and the concept-stage rescue converted it to analytics | BAD → pass 3 |
| c05 | "which of the two is busier?" | compare lane: "Room 1.06 is busier" (27 vs 24 people) | GOOD |
| c06 | "what is the status of that report?" | "Report REP-565C10 … Status: OPEN" | GOOD |
| c08 | "I am in room 3.01" | "The toilet nearest 3.01 is on the same floor: Male washroom — Floor 3" | GOOD |
| c13 | "is it free this afternoon?" | bound to room 1.06; the events lane declined | BAD (lane) |
| c19 | "the first one, is it booked today?" | "1 booking for Room 1.06 today: 08:20–18:00" | GOOD |
| c20 | "what can I ask you?" | self-description with the live capability list | GOOD |
| c21 | "Which quiet rooms are free in the next hour?" | pass 1: deliberate (an answer that contradicts itself, BUG-1424); pass 2: the bookings lane, 92 rooms, "quiet" ignored | WEIRD, route unstable |
| c22 | "lower noise, lower crowding and less glare" | deliberate: 194 spaces ranked on noise, occupancy and illuminance, assumptions stated | GOOD |
| c23 | "where's the nearest bathroom?" | the assumed start stated in the first line | GOOD (BUG-1419) |

**Pass 3** (the concept stage told why the clarification was raised): c03 → *"Which one do you
mean — Room 2.66, Room 3.18, Room 5.26? My last answer named more than one, and I would rather
ask than answer about the wrong one."* in 0 s. And c13, re-asked unchanged, ANSWERED: *"Room 1.06
is not free this afternoon — booked 08:20–18:00; timetabled Fri 16:00–18:00"*. One decline and
one answer on identical input is CAVEAT-891's shape and is logged as such (BUG-1432), not as
fixed.

**Follow-up turns of the eight re-asked conversations: 9 of 11 acceptable on the final build**
(c03's "and yesterday?" still inherits the clarification, and c21 is route-unstable). Across the
original 27 follow-up turns, the fixes address 8; the 9 residue rows above are unchanged. No
fabricated figure in any pass.

**What this does not establish.** The same twenty conversations were re-asked on the build
tuned against them; these numbers are TUNED-ON. The first multi-turn set drawn from real tester
sessions (Phase 2's weekly draw) is the one that measures users.
