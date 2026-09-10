# Cold-start verification — what "cold" means, and how the claim is tested

**Row:** TODO-072 (P1, `FIXED_UNVERIFIED`) — *"build a working building entirely through the
Admin Console from a neutral/empty `input/`."*

Everything else on that row is verified. Every control exists, the readiness signal is correct
on a fully-built building, and the upload path round-trips end to end (documents went 1 → 2 → 1
through the multipart API exactly as the browser sends it). What is owed is the **cold run**:
starting from nothing and reaching the same answers.

The row could not say what "nothing" means, and that is the reason it stayed open rather than
the reason it stayed unverified. This document fixes the definition first, because a cold test
run against warm state proves nothing and looks like a pass — the failure mode that produced
two fictitious numbers in this project already (CAVEAT-173, BUG-176).

---

## Cold, defined per state source

A building's state does not live in one place. `input/` is the only one that is obvious, and
it is the one that matters least — emptying it while GraphDB still holds the building's
triples leaves the readiness screen reporting 52 spaces and the whole exercise measuring
nothing.

| # | State source | Cold means | How it is made cold | How cold is asserted |
|---|---|---|---|---|
| 1 | **`input/`** | No `building.yaml`, no `*.ttl`, no `documents/`, no floor plans, no `database_registry.yaml` | A fresh directory | Directory listing contains none of them |
| 2 | **GraphDB** | No triples in the building's namespace; no named graphs for it | Fresh `./volumes/<id>/graphdb` | `SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }` returns 0 |
| 3 | **Qdrant** | No `documents_<id>` / `capability_<id>` / `floor_plans` points | Fresh `./volumes/<id>/qdrant` | Collections absent, or present with 0 points |
| 4 | **Time-series datasource** | No datasource registered *for this building* | No `database_registry.yaml` in `input/` | The Databases tab lists nothing |
| 5 | **Redis** | No cached responses, no sensor-map cache | Fresh `./volumes/<id>/redis` | `resp_cache:*` and the sensor map are absent |

Note on (4): "cold" is about the **registry**, not the server. Pointing a new building at a
database that already holds readings is not a warm start — it is the product's central claim
("connect a building's data, then ask it anything"). What must be cold is the building's
knowledge that the database exists.

Two things are deliberately **not** required to be cold, because they are infrastructure
rather than building content:

- **`.env`** must carry `BUILDING_ID`, `COMPOSE_PROJECT_NAME` and secrets. Compose refuses to
  interpolate without `BUILDING_ID` by design, and a stack that cannot boot cannot be
  onboarded through its own console.
- **The container images and the stack itself.** The claim is GUI-only onboarding, not
  install-free operation; `docker compose up -d` is step zero of the documented workflow.

### Why a scratch building id, and not a real one

Every stateful service is bind-mounted at `./volumes/${BUILDING_ID}/*`. A scratch id therefore
gets its own empty GraphDB, Qdrant, Redis, Postgres and Mongo, and **cannot touch** the
existing buildings' state — no drops, no deletes, nothing to restore afterwards beyond
removing a directory. Reusing `bldg3`'s id would have meant moving its volumes aside, which is
a destructive operation standing between the test and the user's data.

`data-publisher` is scaled to zero for the run. Its `MYSQL_DB` defaults to `sensordb` when the
building does not set one, and that is bldg1's real archived snapshot — a generator writing
into it is precisely what CLAUDE.md says must never happen.

---

## The acceptance test

Phase 0 asserts cold, then each step is driven through **the same admin endpoints the console
calls** — not through the file system, and not through a helper script that happens to reach
the same result:

| Step | Endpoint the console uses |
|---|---|
| identity | `PUT /api/v1/admin/building/config` |
| ontology | `POST /api/v1/admin/ontology/upload` |
| datasource | `POST /api/v1/admin/databases` |
| documents | `POST /api/v1/admin/documents/upload` (multipart) |
| floor plans | `POST /api/v1/admin/floor-plans/upload` (multipart) |

Readiness is re-read from `GET /api/v1/admin/onboarding/status` after every step. Three
assertions per step, and the second and third are the ones that make the test worth running:

1. the step flips to done;
2. **no other step flips** — a readiness signal that moves when unrelated state changes is
   reading something other than what it claims to;
3. the numbers are real (spaces counted in the graph, sensors with rows, spaces linked to an
   IRI), not booleans that record that an upload happened.

Phase 6 then asks the building a question that requires the data, because readiness is a claim
about the system and an answer is evidence. A building that reports 5/5 and cannot answer
"how many temperature sensors are there?" has passed a checklist, which is exactly what this
row's own fix argued against.

The source files come from a parked building's folder — they play the part of the files on an
administrator's laptop. `input/` starts empty and everything reaches the running system over
HTTP.

## What a failure means

If the orchestrator will not boot against an empty `input/`, the cold claim is false and the
run has found the defect it exists to find. That is a result, not an obstacle: the portability
thesis is stated as "drop TTL + register the DB + load rows — no code change", and a stack
that requires a hand-placed `building.yaml` before it will start does not meet it.
