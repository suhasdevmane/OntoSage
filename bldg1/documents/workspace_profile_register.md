---
record_type: workspace_profile
owner: "Space Planning Manager"
authority: "Cardiff University Estates - Space Planning"
source_system: "Workspace Profile Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
tables:
  - name: "Workspace profile register"
    maps_to: workspace_profiles
---

# Workspace Profile Register - Abacws Building

## What this register records, and why geometry could not

The building already knew every room's area, floor and adjacency. None of that answers the
question the five occupant roles actually ask, which was almost word-for-word the same across
undergraduates, taught postgraduates, PhD students, research staff and lecturers:

> *"Where can I work for three hours with power, good Wi-Fi, useful daylight and a low risk
> of noise?"*

This register describes each space as somewhere to **sit down and work**: how reliably a
laptop can be plugged in, what the surveyed wireless is actually like, whether a call can be
taken without being overheard, whether two people can work together without breaking the
room's noise expectation, and when a seat is realistically available.

Four points about how to read it:

- **busiest** and **quietest** are **typical patterns, not live readings**. *"What arrival
  time gives me the best chance?"* is a question about the pattern. Answering it from the
  current occupancy count would be right this afternoon and wrong tomorrow. Live occupancy
  still comes from the sensors, and the two must never be merged.
- **network** is **surveyed in the space**, not inferred from the nearest access point. Room
  3.06 is the case that matters: the AP is close, and the far end of the room is still weak.
- **noise** is an **expectation**, not a measurement. It is what makes a group in the wrong
  room a problem, and it is why `group_ok` is false for silent spaces even when they have
  spare seats.
- **calls_ok** requires **acoustic separation**, not merely a door.

Every room named here exists in the building's own graph. A workspace profile for an invented
room would be precisely the fabrication the referent gate exists to prevent, arriving through
the data instead of through the model.

## Workspace profile register

| code | name | room | floor | kind | seats | bookable | power | network | daylight | noise | calls_ok | group_ok | access | hours | busiest | quietest | setup_minutes | recovery_minutes | vertical_route | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WS-01 | Atrium open study | Room 1.04 - Common Area / Atrium | 1 | open study | 48 | false | perimeter only | strong | South-facing, bright, glare on south seats 12:00-15:00 | conversational | false | true | Open to all | Mon-Sun 07:00-22:00 | Weekday 11:00-14:00 | Before 09:30 and after 18:00 | 0 | 0 | Main lift core | Active | The busiest space in the building at lunchtime; no seat is silent |
| WS-02 | Level 1 computer lab 1.06 | Room 1.06 - Computer Laboratory | 1 | computer lab | 30 | false | at every seat | strong | North-facing, even daylight, no glare | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 10:00-16:00 | Fridays after 15:00 | 8 | 26.0 | Main lift core | Active | Timetabled teaching takes precedence; the hearing loop here is untested (APR-032) |
| WS-03 | Level 1 computer lab 1.07 | Room 1.07 - Computer Laboratory | 1 | computer lab | 30 | false | at every seat | strong | North-facing, even daylight | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 10:00-16:00 | Fridays after 15:00 | 8 | 26.0 | Main lift core | Active |  |
| WS-04 | Level 1 computer lab 1.08 | Room 1.08 - Computer Laboratory | 1 | computer lab | 24 | false | at every seat | adequate | Internal, no daylight | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 10:00-16:00 | Early morning | 8 | 22.4 | Main lift core | Active | Internal room; the only lab with no daylight |
| WS-05 | Level 1 computer lab 1.09 | Room 1.09 - Computer Laboratory | 1 | computer lab | 24 | false | at every seat | adequate | Internal, no daylight | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 10:00-16:00 | Early morning | 8 | 22.4 | Main lift core | Active |  |
| WS-06 | Seminar room 1.25 | Room 1.25 - Conference/Seminar Room | 1 | bookable room | 16 | true | at some seats | strong | East-facing, morning sun | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Teaching weeks, mid-morning | Late afternoon | 5 | 17.6 | Main lift core | Active | Acoustically separated; suitable for confidential calls |
| WS-07 | Seminar room 1.26 | Room 1.26 - Conference/Seminar Room | 1 | bookable room | 16 | true | at some seats | strong | East-facing, morning sun | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Teaching weeks, mid-morning | Late afternoon | 5 | 17.6 | Main lift core | Active |  |
| WS-08 | Level 2 computer lab 2.07 | Room 2.07 - Computer Laboratory | 2 | computer lab | 28 | false | at every seat | strong | West-facing, glare after 16:00 | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 10:00-16:00 | Fridays | 8 | 24.8 | Main lift core | Active |  |
| WS-09 | Level 2 computer lab 2.08 | Room 2.08 - Computer Laboratory | 2 | computer lab | 28 | false | at every seat | strong | West-facing, glare after 16:00 | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 10:00-16:00 | Fridays | 8 | 24.8 | Main lift core | Active |  |
| WS-10 | Meeting room 2.13 | Room 2.13 - Meeting Room | 2 | bookable room | 8 | true | at some seats | strong | Internal, borrowed light | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday 09:00-12:00 | After 16:00 | 5 | 12.8 | Main lift core | Active | Acoustically separated; the usual choice for a sponsor call |
| WS-11 | Meeting room 2.14 | Room 2.14 - Meeting Room | 2 | bookable room | 8 | true | at some seats | strong | Internal, borrowed light | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday 09:00-12:00 | After 16:00 | 5 | 12.8 | Main lift core | Active |  |
| WS-12 | Seminar room 2.15 | Room 2.15 - Seminar Room | 2 | bookable room | 20 | true | at some seats | adequate | North-facing | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Teaching weeks | Vacation | 5 | 20.0 | Main lift core | Active |  |
| WS-13 | Level 3 computer lab 3.05 | Room 3.05 - Computer Laboratory | 3 | computer lab | 26 | false | at every seat | adequate | North-facing | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 11:00-15:00 | Early morning | 8 | 23.6 | Main lift core | Active |  |
| WS-14 | Level 3 computer lab 3.06 | Room 3.06 - Computer Laboratory | 3 | computer lab | 26 | false | at every seat | weak | North-facing | quiet | false | false | Open when not timetabled | Mon-Fri 08:00-20:00 | Teaching weeks 11:00-15:00 | Early morning | 8 | 23.6 | Main lift core | Active | Surveyed wireless is WEAK at the far end; wired sockets are the reliable option here |
| WS-15 | Seminar room 3.13 | Room 3.13 - Seminar Room | 3 | bookable room | 18 | true | at some seats | strong | South-facing, glare 12:00-15:00 | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Teaching weeks | Vacation | 5 | 18.8 | Main lift core | Active |  |
| WS-16 | Seminar room 3.14 | Room 3.14 - Seminar Room | 3 | bookable room | 18 | true | at some seats | strong | South-facing, glare 12:00-15:00 | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Teaching weeks | Vacation | 5 | 18.8 | Main lift core | Active |  |
| WS-17 | Meeting room 3.15 | Room 3.15 - Meeting Room | 3 | bookable room | 6 | true | at every seat | strong | Internal | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday mornings | After 16:00 | 5 | 11.6 | Main lift core | Active |  |
| WS-18 | Meeting room 3.16 | Room 3.16 - Meeting Room | 3 | bookable room | 6 | true | at every seat | strong | Internal | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday mornings | After 16:00 | 5 | 11.6 | Main lift core | Active |  |
| WS-19 | Staff common room 3.17 | Room 3.17 - Staff Common Room | 3 | common room | 20 | false | perimeter only | strong | South-facing | conversational | false | true | Staff only | Mon-Fri 07:00-19:00 | Weekday 12:00-14:00 | Mid-afternoon | 0 | 20.0 | Main lift core | Active | Staff only; not a quiet-study space and never has been |
| WS-20 | Meeting room 3.26 | Room 3.26 - Meeting Room | 3 | bookable room | 10 | true | at some seats | adequate | North-facing | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday mornings | Fridays | 5 | 14.0 | North stair core | Active |  |
| WS-21 | Meeting room 3.27 | Room 3.27 - Meeting Room | 3 | bookable room | 10 | true | at some seats | adequate | North-facing | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday mornings | Fridays | 5 | 14.0 | North stair core | Active |  |
| WS-22 | Meeting room 4.11 | Room 4.11 - Meeting Room | 4 | bookable room | 8 | true | at every seat | strong | East-facing | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday 10:00-15:00 | Before 09:00 | 5 | 12.8 | Main lift core | Active |  |
| WS-23 | Meeting room 4.12 | Room 4.12 - Meeting Room | 4 | bookable room | 8 | true | at every seat | strong | East-facing | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday 10:00-15:00 | Before 09:00 | 5 | 12.8 | Main lift core | Active |  |
| WS-24 | Seminar room 4.13 | Room 4.13 - Seminar Room | 4 | bookable room | 22 | true | at some seats | strong | East-facing | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Teaching weeks | Vacation | 5 | 21.2 | Main lift core | Active |  |
| WS-25 | Seminar room 5.15 | Room 5.15 - Seminar / Conference Room | 5 | bookable room | 30 | true | at some seats | strong | South-facing, best daylight in the building | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday 09:00-13:00 | After 15:00 | 5 | 26.0 | Main lift core | Active | The quietest bookable space above Level 3, and the furthest from the atrium |
| WS-26 | Seminar room 5.16 | Room 5.16 - Seminar / Conference Room | 5 | bookable room | 30 | true | at some seats | strong | South-facing | quiet | true | true | Bookable | Mon-Fri 08:00-18:00 | Weekday 09:00-13:00 | After 15:00 | 5 | 26.0 | Main lift core | Active |  |
| WS-27 | Meeting room 5.17 | Room 5.17 - Meeting Room | 5 | bookable room | 6 | true | at every seat | strong | Internal | silent | true | false | Bookable | Mon-Fri 08:00-18:00 | Weekday mornings | Late afternoon | 5 | 11.6 | Main lift core | Active | Single-occupancy in practice; the usual choice for an interview or a viva |
| WS-28 | Meeting room 5.18 | Room 5.18 - Meeting Room | 5 | bookable room | 6 | true | at every seat | strong | Internal | silent | true | false | Bookable | Mon-Fri 08:00-18:00 | Weekday mornings | Late afternoon | 5 | 11.6 | Main lift core | Active |  |

**28 workspaces, 530 working seats. 18 are bookable, 18 are suitable for a confidential or video call, and 18 allow two people to work together. Only one space - the atrium - is open at weekends, so every question about Saturday or Sunday study has exactly one answer.**
