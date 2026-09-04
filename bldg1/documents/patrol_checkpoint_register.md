---
record_type: patrol_checkpoint
owner: "Head of Security"
authority: "Cardiff University Estates — Security Operations"
source_system: "Patrol Checkpoint Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Patrol checkpoint register"
    maps_to: patrol_checkpoints
---

# Patrol Checkpoint Register — Abacws Building

_**Synthetic demonstration record** — fictional patrol data, not a live security log._

## How a shift reads this

A checkpoint belongs to a **circuit**, has a position in that circuit, and carries the time
it was last verified and the time it is next due. An officer starting a shift asks four
things of it: what is overdue, what is unverifiable, is the circuit feasible in the window,
and what must be called out at handover.

**Status is recorded, never derived from the due time.** *Overdue* and *unverifiable* are
different facts with different remedies — one needs walking, the other needs a lock or a tag
fixed — and inferring both from a date would collapse them into "late".

**`walk_minutes` exists so feasibility can be computed.** "Which approved circuit is
evidenced as feasible for the next window" is a sum against the window, not a judgement.

## Circuits

| circuit | covers | full walk |
|---|---|---|
| `C1-PERIMETER` | External doors, waste compound, drop-off, roof hatch | 25 min |
| `C2-PUBLIC` | Reception, atrium, Level 1 circulation, washrooms | 20 min |
| `C3-LABS` | Levels 2–4 laboratory corridors and lobbies | 30 min |
| `C4-PLANT` | Plant room, comms room, risers | 15 min |

## Patrol checkpoint register

| checkpoint | name | circuit | sequence | location | shift | frequency | last_verified | due | walk_minutes | qualification | status | exception | owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CHK-101 | Main entrance doors | C1-PERIMETER | 1 | Main Entrance | Night | 2-hourly | 2026-09-04 02:10:00 | 2026-09-04 04:10:00 | 4 | SIA licence | Current | | Head of Security |
| CHK-102 | Waste compound gate | C1-PERIMETER | 2 | Waste compound and bin store | Night | 2-hourly | 2026-09-04 02:18:00 | 2026-09-04 04:18:00 | 5 | SIA licence | Current | | Head of Security |
| CHK-103 | Accessible drop-off | C1-PERIMETER | 3 | Accessible drop-off — Senghennydd Road north | Night | 2-hourly | 2026-09-04 02:26:00 | 2026-09-04 04:26:00 | 4 | SIA licence | Current | | Head of Security |
| CHK-104 | Roof access hatch | C1-PERIMETER | 4 | Roof access hatch | Night | nightly | 2026-09-03 23:40:00 | 2026-09-04 23:40:00 | 6 | SIA licence + work at height awareness | Due | | Head of Security |
| CHK-105 | Fire exit — Floor 1 North | C1-PERIMETER | 5 | Fire Exit - Floor 1 North | Night | 2-hourly | 2026-09-04 01:05:00 | 2026-09-04 03:05:00 | 3 | SIA licence | Overdue | Not walked on the 03:00 round; officer diverted to an alarm on Level 3. | Head of Security |
| CHK-201 | Main reception desk | C2-PUBLIC | 1 | Room 0.01 — Main Reception | Day | 4-hourly | 2026-09-04 08:15:00 | 2026-09-04 12:15:00 | 3 | SIA licence | Current | | Head of Security |
| CHK-202 | Level 1 atrium | C2-PUBLIC | 2 | Room 1.04 — Common Area / Atrium | Day | 4-hourly | 2026-09-04 08:22:00 | 2026-09-04 12:22:00 | 4 | SIA licence | Current | | Head of Security |
| CHK-203 | Level 1 washrooms | C2-PUBLIC | 3 | Level 1 accessible washroom | Day | 4-hourly | 2026-09-04 08:30:00 | 2026-09-04 12:30:00 | 4 | SIA licence | Current | | Head of Security |
| CHK-204 | Level 1 circulation | C2-PUBLIC | 4 | Level 1 circulation and stairs | Day | 4-hourly | 2026-09-04 08:38:00 | 2026-09-04 12:38:00 | 5 | SIA licence | Current | | Head of Security |
| CHK-301 | Level 2 laboratory lobby | C3-LABS | 1 | Floor 2 Entrance | Evening | 3-hourly | 2026-09-03 21:10:00 | 2026-09-04 00:10:00 | 5 | SIA licence + laboratory induction | Overdue | Missed on the 00:00 round; single-crewed shift. | Head of Security |
| CHK-302 | Level 3 laboratory lobby | C3-LABS | 2 | Floor 3 Entrance | Evening | 3-hourly | 2026-09-03 21:20:00 | 2026-09-04 00:20:00 | 5 | SIA licence + laboratory induction | Overdue | Missed on the 00:00 round; single-crewed shift. | Head of Security |
| CHK-303 | Level 4 laboratory lobby | C3-LABS | 3 | Floor 4 Entrance | Evening | 3-hourly | 2026-09-03 21:30:00 | 2026-09-04 00:30:00 | 5 | SIA licence + laboratory induction | Current | | Head of Security |
| CHK-304 | Room 3.06 corridor | C3-LABS | 4 | Room 3.06 — Research Laboratory | Evening | 3-hourly | | 2026-09-04 00:40:00 | 5 | SIA licence + laboratory induction | Unverifiable | COSHH review restriction — no entry authorised to 2026-09-09, so this point cannot be walked. | Laboratory Manager |
| CHK-305 | Level 2 north corridor | C3-LABS | 5 | Level 2 circulation and stairs | Evening | 3-hourly | 2026-09-03 21:45:00 | 2026-09-04 00:45:00 | 5 | SIA licence | Current | | Head of Security |
| CHK-306 | Level 4 north corridor | C3-LABS | 6 | Level 4 circulation and stairs | Evening | 3-hourly | 2026-09-03 21:52:00 | 2026-09-04 00:52:00 | 5 | SIA licence | Current | | Head of Security |
| CHK-401 | Mechanical plant room | C4-PLANT | 1 | Room 0.04 — Mechanical Plant Room | Night | nightly | 2026-09-04 01:30:00 | 2026-09-05 01:30:00 | 6 | SIA licence + plant awareness | Current | | Head of Security |
| CHK-402 | Comms room | C4-PLANT | 2 | Room 0.07 — Comms Room | Night | nightly | 2026-09-04 01:40:00 | 2026-09-05 01:40:00 | 4 | SIA licence + IT escort | Unverifiable | Reader tag faulty since 2026-09-02; entry requires an IT escort not rostered on nights. | IT Infrastructure Manager |
| CHK-403 | Level 3 riser | C4-PLANT | 3 | Level 3 circulation and stairs | Night | nightly | 2026-09-04 01:48:00 | 2026-09-05 01:48:00 | 5 | SIA licence | Current | | Head of Security |

## Open exceptions for handover

- **CHK-105**, **CHK-301** and **CHK-302** are overdue — all three were missed on a
  single-crewed round and none has been walked since.
- **CHK-304** cannot be walked at all until the COSHH restriction lifts on 2026-09-09.
- **CHK-402** has a faulty reader tag and needs an IT escort who is not rostered at night.

## Posts required by the operating plan

| post | shift | required qualification | assigned |
|---|---|---|---|
| Main entrance control | Day | SIA licence | yes |
| Roving patrol — public | Day | SIA licence | yes |
| Roving patrol — laboratories | Evening | SIA licence + laboratory induction | **no** |
| Night patrol | Night | SIA licence | yes |
| Control room | Night | SIA licence + CCTV endorsement | yes |
