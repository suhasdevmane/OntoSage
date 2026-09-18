---
record_type: circulation_time
owner: "Space Planning Manager"
authority: "Cardiff University Estates - Space Planning"
source_system: "Circulation Time Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Circulation time register"
    maps_to: circulation_times
---

# Circulation Time Register - Abacws Building

## Why this register exists

Lecturers were the worst-served role in the re-sample - 0 of 5, after every other role had
improved - and their questions are about the **journey**:

> *"I have back-to-back seminars in different rooms. Which transition needs the larger
> travel and setup allowance?"*

The building knew where both rooms were and nothing whatever about getting between them.

**Floor to floor, not room to room.** A room-pair matrix grows as the square of the room
count: this building would need over five thousand rows to say what twenty-one say here, and
the floor change dominates the time anyway. A register nobody can maintain goes stale, and a
stale travel time is worse than none.

**Two times, not one.** `step_free_minutes` is not `walking_minutes` with a lift substituted
- it includes the wait, and on most pairs it is **longer**. Planning a transition on the
walking figure sends a wheelchair user late. That is the failure this register exists to
prevent, not a rounding difference.

**`depends_on_lift` matters more than either figure.** Every journey marked true has no
step-free alternative when the lift is out - not a slower one, none at all. The lift
(AEP-011) is the only step-free route between levels in this building.

## Circulation time register

| code | route | from_floor | to_floor | walking_minutes | step_free_minutes | depends_on_lift | vertical_route | status | note |
|---|---|---|---|---|---|---|---|---|---|
| CIRC-01 | Within Level 0 | 0 | 0 | 2.0 | 2.5 | false | n/a | Active |  |
| CIRC-02 | Level 0 to Level 1 | 0 | 1 | 3.5 | 4.9 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-03 | Level 0 to Level 2 | 0 | 2 | 5.0 | 5.3 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-04 | Level 0 to Level 3 | 0 | 3 | 6.5 | 5.7 | true | Main lift core | Active |  |
| CIRC-05 | Level 0 to Level 4 | 0 | 4 | 8.0 | 6.1 | true | Main lift core | Active |  |
| CIRC-06 | Level 0 to Level 5 | 0 | 5 | 9.5 | 6.5 | true | Main lift core | Active | The longest journey in the building; a five-minute changeover does not cover it. |
| CIRC-07 | Within Level 1 | 1 | 1 | 2.0 | 2.5 | false | n/a | Active |  |
| CIRC-08 | Level 1 to Level 2 | 1 | 2 | 3.5 | 4.9 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-09 | Level 1 to Level 3 | 1 | 3 | 5.0 | 5.3 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-10 | Level 1 to Level 4 | 1 | 4 | 6.5 | 5.7 | true | Main lift core | Active |  |
| CIRC-11 | Level 1 to Level 5 | 1 | 5 | 8.0 | 6.1 | true | Main lift core | Active | Atrium teaching floor to the top conference rooms. |
| CIRC-12 | Within Level 2 | 2 | 2 | 2.0 | 2.5 | false | n/a | Active |  |
| CIRC-13 | Level 2 to Level 3 | 2 | 3 | 3.5 | 4.9 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-14 | Level 2 to Level 4 | 2 | 4 | 5.0 | 5.3 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-15 | Level 2 to Level 5 | 2 | 5 | 6.5 | 5.7 | true | Main lift core | Active |  |
| CIRC-16 | Within Level 3 | 3 | 3 | 2.0 | 2.5 | false | n/a | Active |  |
| CIRC-17 | Level 3 to Level 4 | 3 | 4 | 3.5 | 4.9 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-18 | Level 3 to Level 5 | 3 | 5 | 5.0 | 5.3 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-19 | Within Level 4 | 4 | 4 | 2.0 | 2.5 | false | n/a | Active |  |
| CIRC-20 | Level 4 to Level 5 | 4 | 5 | 3.5 | 4.9 | true | Main lift core | Active | Step-free is SLOWER than the stairs here, because the lift wait dominates a short climb. |
| CIRC-21 | Within Level 5 | 5 | 5 | 2.0 | 2.5 | false | n/a | Active |  |

**21 floor pairs. 15 involve a floor change and depend on the lift; on 9 of those the step-free route is SLOWER than the stairs, because the lift wait dominates a short climb. The longest journey is Level 0 to Level 5 at 9.5 minutes walking - longer than a standard five-minute changeover allows.**
