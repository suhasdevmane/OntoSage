# OntoSage Onboarding Contract

**The promise:** connect a building's data in the shapes below and its
questions become answerable — *no code changes*. This document is the
contract; `scripts/check_onboarding.py` is the machine check that tells you
which half of it you have satisfied so far.

```bash
docker exec ontosage-orchestrator python /app/scripts/check_onboarding.py
```

It prints a per-capability table — unlocked ✅ / partial 🟡 / locked ⛔ — and
for every locked row, the **specific artefact** that is missing.

---

## The three data shapes

### S1 — scalar time-series (readings)

The backbone: temperature, CO₂, occupancy, noise, energy…

A point is *backed* when **both** halves exist:

1. **A triple in the graph** — the sensor, its type, its space, and its
   time-series id:
   ```turtle
   bldg:RM101_temp a brick:Temperature_Sensor ;
       brick:isPointOf bldg:RM101 ;
       ref:hasExternalReference [ ref:hasTimeseriesId "uuid-…" ;
                                  ref:storedAt "temperature_data" ] .
   ```
2. **Rows in a registered database** — the `ref:storedAt` key must name a
   source in `input/database_registry.yaml`, and that table must hold
   `(uuid, datetime, value)` rows.

Miss either half and the point is invisible: the graph half without rows
answers "no data for that sensor"; rows without the triple are unreachable.

**Unlocks:** readings · ranking/deliberation · diagnosis · (with history)
prediction and detection.

### S2 — intervals and events

Bookings, work orders, access counts, anomaly episodes — anything with a
start, an optional end, and a status.

- One `events` table (`event_id, event_type, subject_uuid, start_dt, end_dt,
  status, attrs`) — DDL in `data/mysql-init/create_events_table.sql`.
- Registered as an `events_data` source in `database_registry.yaml` **and**
  listed in `building.yaml`'s storage block.
- `subject_uuid` joins to spaces by the documented derivation
  (`derive_point_uuid(building_id, "evt_subject", <room_local>)`); the
  building entrance uses the pseudo-subject `entrance_main`.

**Unlocks:** availability/bookings · work orders · access counts ·
persistence of anomaly episodes (DETECT writes here).

### S3 — dated registers

Compliance checks, inspections, certificates: records whose value is a
**date**, not a series.

- Loaded as triples, not a sidecar file:
  ```turtle
  bldg:check_fire_alarm_w32 a ontosage:ComplianceCheck ;
      rdfs:label "Fire alarm weekly test" ;
      ontosage:dueDate "2026-08-23T00:00:00"^^xsd:dateTime ;
      ontosage:recordStatus "open" ;
      ontosage:responsibleRole "facility_manager" .
  ```
- Generate a starter register with
  `python scripts/generate_compliance_register.py`, or upload your own via
  the admin portal (Ontology → upload).

**Unlocks:** overdue / due-soon / last-completed questions.

---

## Non-data prerequisites (stated honestly)

| prerequisite | needed by | why |
|---|---|---|
| **≥2 days of history** per point | DETECT | hour-of-week profiles and peer groups do not exist before that; scanning earlier produces noise, not findings |
| **≥2 days of history**, ideally **~2 weeks** | PREDICT | forecasts run from 2 days, but the seasonal tier only beats a flat baseline once weekday patterns are visible; below that the honest answer is a wide interval |
| **DWG-derived adjacency** in floor-plan manifests | wayfinding | routes need which room touches which; PDF-only ingestion yields locations, not a graph |
| **AccessPolicy triples** | PROTECT | without them every authenticated role reads everything (`scripts/generate_access_policies.py --all`) |

These are reported as 🟡 *partial* with the shortfall named — the system
never pretends a fresh building can forecast a week ahead.

---

## Onboarding sequence

1. **Drop the TTL** into `input/` (`<id>_*.ttl`) — `ttl_uploader` ingests it
   on restart (SHA-gated).
2. **Register the databases** in `input/database_registry.yaml`; list the
   storage keys in `input/building.yaml`.
3. **Load rows** into the narrow tables (or point at an existing warehouse).
4. **Optional shapes:** events table (S2), register TTL (S3), floor-plan
   DWG (geometry), policies (PROTECT).
5. **Run the validator** — it names anything still missing.
6. **Let history accumulate** — re-run the validator after two days; PREDICT
   and DETECT flip from 🟡/⛔ to ✅ on their own.

## What never changes

No step above edits code. The routing contract, the deliberative planner,
the detectors, the graders and the policy engine are all building-agnostic
by construction — enforced by scan tests
(`tests/test_deliberation_agnostic.py`, `tests/test_ocbv2_schema.py`) that
fail if a building literal appears in core code, config templates, or TBox.
