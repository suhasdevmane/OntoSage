---
record_type: accessible_route
owner: "Accessibility and Inclusion Team"
authority: "Cardiff University Estates — Access Consultant survey"
source_system: "Accessible Route Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Accessible route register"
    maps_to: accessible_routes
---

# Accessible Route Register — Abacws Building

_**Synthetic demonstration record** — fictional survey, not a real access audit._

## Why every row carries a survey date

The questions this register answers all use the same word: *verified*. A route inferred
from a floor plan is a guess about somebody's journey, and a wrong guess costs that person
the journey. So `surveyed_on` and `surveyed_by` are required: **a route with no survey
behind it is not published here**, and an answer drawn from this register can say when it
was last walked and by whom.

**"Allow" is not walking time.** It includes doors, lifts, waiting and check-in, because
the question asked is "how much time should I allow before my appointment", not "how far is
it".

**Door operation is recorded per route, not per building.** A route can be step-free and
still have a heavy manual door on it, which is the difference between usable and not.

## Assistance contacts

| method | contact | hours |
|---|---|---|
| Text message | 07700 900142 | 07:00–19:00, Monday–Friday |
| Email | abacws-access@example.ac.uk | Monitored 08:00–17:00 |
| In-person | Main Reception, Room 0.01 | 07:30–18:00 |
| Intercom (text display fitted) | All controlled entrances | Continuous |

A phone call is never required. The text and email routes are the official arrival contacts
and are answered by the same reception team.

## Accessible route register

| route | name | from_point | to_point | entrance | step_free | seated_rests | door_type | lift | lift_status | distance_m | allow_minutes | sensory | assistance_contact | surveyed_on | surveyed_by | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RTE-001 | Accessible drop-off to Reception | Accessible drop-off — Senghennydd Road north | Room 0.01 — Main Reception | Main Entrance | true | 2 | Automatic | | | 40 | 10 | Moderate | Text 07700 900142 | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Level approach throughout; two benches on the approach. |
| RTE-002 | Cathays station to Reception | Cathays railway station | Room 0.01 — Main Reception | Main Entrance | true | 3 | Automatic | | | 640 | 20 | Busy | Text 07700 900142 | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Dropped kerbs at all crossings; three benches en route. |
| RTE-003 | Bus stop to Reception | Bus stop — Senghennydd Road | Room 0.01 — Main Reception | Main Entrance | true | 1 | Automatic | | | 120 | 12 | Moderate | Text 07700 900142 | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | One bench at the entrance forecourt. |
| RTE-004 | Reception to Level 1 Atrium | Room 0.01 — Main Reception | Room 1.04 — Common Area / Atrium | Main Entrance | true | 1 | Automatic | Lift A | In service | 55 | 8 | Busy | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Seating available on arrival in the atrium. |
| RTE-005 | Reception to Level 1 Computer Laboratory | Room 0.01 — Main Reception | Room 1.06 — Computer Laboratory | Main Entrance | true | 1 | Assisted | Lift A | In service | 70 | 10 | Moderate | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Push-pad door at the laboratory corridor. |
| RTE-006 | Reception to Level 2 laboratories | Room 0.01 — Main Reception | Room 2.01 — Research Laboratory | Main Entrance | true | 1 | Manual heavy | Lift A | In service | 85 | 14 | Moderate | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | restricted | Heavy manual fire door at the Level 2 lobby; assisted alternative is Lift B and the north corridor. |
| RTE-007 | Reception to Level 3 laboratories | Room 0.01 — Main Reception | Room 3.01 — Research Laboratory | Main Entrance | true | 1 | Assisted | Lift A | In service | 90 | 14 | Moderate | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | |
| RTE-008 | Reception to Level 4 laboratories | Room 0.01 — Main Reception | Room 4.01 — Research Laboratory | Main Entrance | true | 1 | Assisted | Lift A | In service | 95 | 15 | Moderate | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | |
| RTE-009 | Reception to Level 5 offices | Room 0.01 — Main Reception | Room 5.04 — Academic Office | Main Entrance | true | 1 | Assisted | Lift A | In service | 100 | 16 | Quiet | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Level 5 is the quietest arrival on a teaching day. |
| RTE-010 | Quiet arrival route | Accessible drop-off — Senghennydd Road north | Room 1.09 — Quiet Room | Main Entrance | true | 2 | Automatic | Lift B | In service | 75 | 12 | Quiet | Text 07700 900142 | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Avoids the atrium; lower footfall and lighting throughout. |
| RTE-011 | Low-vision route to Reception | Cathays railway station | Room 0.01 — Main Reception | Main Entrance | true | 3 | Automatic | | | 640 | 22 | Busy | Text 07700 900142 | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Tactile paving at every crossing; high-contrast handrails and a single unbroken approach with no changes of level. |
| RTE-012 | Companion or assistance-dog route | Accessible drop-off — Senghennydd Road north | Room 1.04 — Common Area / Atrium | Main Entrance | true | 2 | Automatic | Lift A | In service | 80 | 12 | Moderate | Text 07700 900142 | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Same authorised entrance for a companion, carer or assistance dog; no separate registration. Water bowl at reception on request. |
| RTE-013 | Evacuation route — Level 1 refuge | Room 1.04 — Common Area / Atrium | Fire Exit - Floor 1 North | Main Entrance | true | 0 | Assisted | | | 30 | 3 | Moderate | Intercom at refuge point | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Refuge point with two-way intercom; PEEP required for independent use. |
| RTE-014 | Reception to accessible washroom | Room 0.01 — Main Reception | Level 1 accessible washroom | Main Entrance | true | 1 | Assisted | Lift A | In service | 60 | 9 | Moderate | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | open | Radar-key washroom; key held at reception. |
| RTE-015 | North stair route — not step free | Bus stop — Senghennydd Road | Room 2.02 — Research Laboratory | Floor 2 Entrance | false | 0 | Manual heavy | | | 110 | 18 | Moderate | In-person, Main Reception | 2026-07-14 | Access Consultant — Hywel Access Ltd | restricted | Recorded so it is never offered as an accessible option; 22 steps, no handrail on the left descending. |
| RTE-016 | Lift B route to Level 3 | Room 0.01 — Main Reception | Room 3.06 — Research Laboratory | Main Entrance | true | 1 | Assisted | Lift B | Out of service | 95 | 15 | Moderate | In-person, Main Reception | 2026-08-28 | Access Consultant — Hywel Access Ltd | closed | Lift B is out of service to 2026-09-12; use RTE-007 and the north corridor instead. |

## Exceptions at the date of this version

- **Lift B is out of service** to 2026-09-12, so RTE-016 is closed and RTE-010 falls back to
  Lift A with the atrium approach — a busier arrival than the quiet route it replaces.
- **RTE-006** is restricted by a heavy manual fire door; the assisted alternative is
  recorded on the row rather than left to be discovered.
- **RTE-015** is deliberately published as *not* step-free so it is never offered as an
  accessible option.
