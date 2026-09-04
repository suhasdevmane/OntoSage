---
record_type: event_activity
owner: "Events and Communications Coordinator"
authority: "Cardiff University — School Events Office"
source_system: "Event Activity Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-09-01
simulated: true
tables:
  - name: "Event activity register"
    maps_to: event_activities
---

# Event Activity Register — Abacws Building

_**Synthetic demonstration record** — fictional agendas, not a real programme._

## Why activities are rows and not a paragraph

`Public Event Register` answers a visitor's arrival questions. This one answers what happens
after they are inside: how long each part runs, where it is, whether a companion may join,
and what can be dropped when time is short.

**Companion policy is recorded per activity, not per event.** A campus tour and a
one-to-one admissions conversation can sit inside the same open day and differ on whether a
parent may attend. A family planning their day needs that at the activity level, or the
answer is wrong for half the visit.

**`optional` exists so "we only have two hours, what should we prioritise" is answerable by
dropping the optional activities** rather than by the system inventing a preference. What is
core and what is extra is the events office's decision, so it is recorded rather than judged.

## Event activity register

| activity | event | title | sequence | starts | minutes | location | companion | optional | access_note | status | owner |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ACT-0042-1 | EVT-2026-0042 | Welcome and registration | 1 | 09:30 | 30 | Room 0.01 — Main Reception | Companions welcome; no separate registration. | false | Step-free; seating available. | Scheduled | Events and Communications Coordinator |
| ACT-0042-2 | EVT-2026-0042 | Course talk — Computer Science | 2 | 10:00 | 45 | Room 1.06 — Computer Laboratory | Companions welcome. | false | Step-free; hearing loop at the front. | Scheduled | Events and Communications Coordinator |
| ACT-0042-3 | EVT-2026-0042 | Building tour | 3 | 10:45 | 40 | Starts Room 1.04 — Common Area / Atrium | Companions welcome; step-free tour available on request. | false | A step-free tour route runs in parallel; ask at registration. | Scheduled | Events and Communications Coordinator |
| ACT-0042-4 | EVT-2026-0042 | Questions with academic staff | 4 | 11:25 | 30 | Room 1.04 — Common Area / Atrium | Companions welcome. | false | Step-free; quieter after 11:45. | Scheduled | Events and Communications Coordinator |
| ACT-0042-5 | EVT-2026-0042 | Laboratory demonstration | 5 | 12:00 | 30 | Room 2.01 — Research Laboratory | Companions welcome; capacity 30 including companions. | true | Step-free. Closed footwear required. | Scheduled | Events and Communications Coordinator |
| ACT-0042-6 | EVT-2026-0042 | Lunch and informal chat | 6 | 12:30 | 45 | Room 1.04 — Common Area / Atrium | Companions welcome. | true | Step-free; busiest part of the day. | Scheduled | Events and Communications Coordinator |
| ACT-0042-7 | EVT-2026-0042 | One-to-one admissions conversation | 7 | 13:15 | 20 | Room 5.04 — Academic Office | Applicant only; a companion may wait in Room 1.09. | true | Step-free via the Main Entrance lifts. | Scheduled | Events and Communications Coordinator |
| ACT-0042-8 | EVT-2026-0042 | Student accommodation talk | 8 | 13:45 | 30 | Room 1.06 — Computer Laboratory | Companions welcome. | true | Step-free; hearing loop at the front. | Scheduled | Events and Communications Coordinator |
| ACT-0042-9 | EVT-2026-0042 | Close and departure | 9 | 14:30 | 30 | Room 0.01 — Main Reception | Companions welcome. | false | Step-free. | Scheduled | Events and Communications Coordinator |
| ACT-0047-1 | EVT-2026-0047 | Schools group arrival | 1 | 12:30 | 30 | Room 0.01 — Main Reception | Accompanying staff registered by the school. | false | Step-free. | Scheduled | Events and Communications Coordinator |
| ACT-0047-2 | EVT-2026-0047 | Hands-on coding workshop | 2 | 13:00 | 90 | Room 1.06 — Computer Laboratory | Accompanying staff must remain with the group. | false | Step-free; adjustable-height benches at positions 1-4. | Scheduled | Events and Communications Coordinator |
| ACT-0047-3 | EVT-2026-0047 | Campus walk | 3 | 14:30 | 45 | Starts Main Entrance | Accompanying staff must remain with the group. | true | Step-free route available; ask at arrival. | Scheduled | Events and Communications Coordinator |
| ACT-0047-4 | EVT-2026-0047 | Close | 4 | 15:15 | 15 | Room 0.01 — Main Reception | | false | Step-free. | Scheduled | Events and Communications Coordinator |
| ACT-0043-1 | EVT-2026-0043 | Showcase opening | 1 | 14:00 | 20 | Room 2.01 — Research Laboratory | Companions welcome. | false | Step-free. Closed footwear required. | Scheduled | Events and Communications Coordinator |
| ACT-0043-2 | EVT-2026-0043 | Poster session | 2 | 14:20 | 70 | Room 1.04 — Common Area / Atrium | Companions welcome. | false | Step-free; seating along the north wall. | Scheduled | Events and Communications Coordinator |
| ACT-0043-3 | EVT-2026-0043 | Demonstrations | 3 | 15:30 | 60 | Room 2.02 — Research Laboratory | Companions welcome; capacity 30. | true | Step-free. | Scheduled | Events and Communications Coordinator |
| ACT-0043-4 | EVT-2026-0043 | Closing remarks | 4 | 16:30 | 30 | Room 1.04 — Common Area / Atrium | Companions welcome. | true | Step-free. | Scheduled | Events and Communications Coordinator |
| ACT-0052-1 | EVT-2026-0052 | Panel welcome | 1 | 14:00 | 15 | Room 1.04 — Common Area / Atrium | Support persons attend without separate registration. | false | Level approach; BSL interpreter present; hearing loop. | Scheduled | Accessibility and Inclusion Team |
| ACT-0052-2 | EVT-2026-0052 | Barriers discussion | 2 | 14:15 | 60 | Room 1.04 — Common Area / Atrium | Support persons welcome. | false | BSL interpreter present; breaks every 20 minutes. | Scheduled | Accessibility and Inclusion Team |
| ACT-0052-3 | EVT-2026-0052 | Quiet break | 3 | 15:15 | 20 | Room 1.09 — Quiet Room | Support persons welcome. | true | Low lighting, low noise; no interpreter in this period. | Scheduled | Accessibility and Inclusion Team |
| ACT-0052-4 | EVT-2026-0052 | Actions and close | 4 | 15:35 | 25 | Room 1.04 — Common Area / Atrium | Support persons welcome. | false | BSL interpreter present. | Scheduled | Accessibility and Inclusion Team |
| ACT-0045-1 | EVT-2026-0045 | Postgraduate welcome | 1 | 16:00 | 30 | Room 1.04 — Common Area / Atrium | Companions welcome. | false | Step-free; hearing loop. | Scheduled | Events and Communications Coordinator |
| ACT-0045-2 | EVT-2026-0045 | Meet your supervisor | 2 | 16:30 | 45 | Room 1.04 — Common Area / Atrium | Applicant only. | true | Step-free. | Full | Events and Communications Coordinator |
| ACT-0045-3 | EVT-2026-0045 | Facilities tour | 3 | 17:15 | 45 | Starts Room 1.04 — Common Area / Atrium | Companions welcome. | true | Step-free route available. | Scheduled | Events and Communications Coordinator |

## Where a family member can wait

**Room 1.09 — Quiet Room** is the confirmed public waiting space: low lighting, low noise,
seating for six, open whenever the building is. It is used as a scheduled activity only
during EVT-2026-0052; at all other times it is available to wait in.

The Level 1 Atrium has seating throughout but is the busiest part of the building on an
event day.

## Notes on timing

Total for the open day (EVT-2026-0042) is **5 hours 30 minutes** across nine activities, of
which four are optional. Dropping the optional four leaves **2 hours 25 minutes**: welcome,
course talk, tour, questions and close.
