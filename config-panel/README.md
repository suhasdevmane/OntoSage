# OntoSage — Admin Console (`:3001`)

A localhost-only admin control panel: a static SPA (HTML + vanilla JS) served by
nginx that reverse-proxies `/api`, `/auth`, and `/health` to the orchestrator —
same-origin, so no CORS and no API-base config. No build step, no `node_modules`.

## Tabs

| Tab | What it does | API |
|---|---|---|
| **Data Sources** | Toggle synthetic sources on/off, regenerate data, preview (sparkline), add a new source, view the provenance legend | `/api/v1/datasources*` |
| **Settings (.env)** | View/edit the root `.env` (secrets masked; add custom keys) | `/api/v1/admin/env` |
| **Databases** | Add DB connections (creds → `.env`, entry → overlay) **and register their sensors** (TTL upload or points form → Brick triples + UUIDs into `urn:ontosage:db:<key>`) so the DB becomes SPARQL-discoverable and used per-question | `/api/v1/admin/databases`, `/api/v1/admin/databases/{key}/sensors[/ttl]` |
| **Users & Access** | Create/delete users, assign roles, and set which data sources each **role** may query (enforced in the pipeline) | `/api/v1/admin/users`, `/api/v1/admin/role-access` |
| **Health** | Live orchestrator health + feature state | `/health` |

## Signing in — admin bootstrap

There is no default admin. Set both in `.env` and restart the orchestrator:

```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<your-strong-password>
```

On startup the orchestrator **creates that admin-role account if it doesn't
exist** (safe-create: it never overwrites an existing account). Sign in with it
to reach all tabs. Alternatively, create/promote an admin manually:

```bash
docker exec ontosage-orchestrator python /app/orchestrator/create_admin.py <user> <pass>
```

## Connecting an external database (two required halves)

A connected DB is **inert until its sensors are described in the ontology** — the
pipeline finds a sensor + UUID + `ref:storedAt` via SPARQL, then routes the fetch
to that DB. So a connection has two steps:

1. **Add connection** (credentials) — Databases tab → *Add connection*.
2. **Register sensors** — the connection's *Register sensors* button:
   - **Add points**: type each sensor's local name, Brick class, location, unit,
     and its **real UUID** (the id that exists in the DB) → triples generated with
     `ref:storedAt bldg:<key>`.
   - **Upload TTL**: paste a Brick Turtle doc of the sensors (validated) — for many
     sensors. Each must carry `ref:hasTimeseriesId` + `ref:storedAt bldg:<key>`.

   Both land in the named graph `urn:ontosage:db:<key>` (re-registering replaces
   it). This applies **immediately** (no restart) — the response cache is flushed.

## Roles & data-source access

Each of the 6 RBAC roles (admin / facility_manager / analyst / operator /
occupant / readonly) can be given a **data-source allow-list** in the Users tab.
When a user asks a question that needs a source their role isn't allowed, the
pipeline declines with a "your role doesn't have access to X" message (same gate
as locked-capability). A role left unconfigured is unrestricted (opt-in control).
`admin` always has full access. Role-access changes apply **immediately** (no
restart); `.env` and database changes need a restart.

## Important: how changes apply

`.env` and `database_registry` are read **when the orchestrator boots**. The
console writes the files and shows a **"restart required"** banner — changes take
effect only after:

```bash
docker-compose up -d orchestrator     # no image rebuild (code is bind-mounted)
```

There is intentionally **no auto-restart** from the browser.

## Security

- Bound to `127.0.0.1:3001` only.
- `.env` + database edits require a **`system:admin`** session; data-source toggles
  require `config:write`. Sign in (top-left) with an admin account.
- Secret values (`*PASSWORD*`, `*SECRET*`, `*KEY*`, `*TOKEN*`, …) are **masked**
  (`********`). Leaving a masked field unchanged keeps the current value; only a
  freshly typed value overwrites a secret.

## Persistence model (nothing curated is clobbered)

- New **data sources** → `input/datasources.custom.yaml`
- New **database connections** → `input/database_registry.custom.yaml` (entry) +
  `.env` (credentials as `${KEY}` values)
- The hand-authored `datasources.yaml` / `database_registry.yaml` are **read-only
  inputs** — the loaders merge the curated file + the custom overlay, and the
  curated entry wins on any id clash.

## Run

```bash
# .env:  DATASOURCE_TOGGLES_ENABLED=true
docker-compose up -d orchestrator config-panel
# open http://127.0.0.1:3001
```

Requires the orchestrator to mount `./input`, `./volumes/artifacts`, and `./.env`
read-write (already set in docker-compose.yml).

See `tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md`.
