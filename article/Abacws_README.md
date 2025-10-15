<div align="center">

# Abacws — Spatial IoT API + 3D Visualiser

Rich spatial exploration & live telemetry for building / campus devices.

</div>

Abacws is a two‑part platform:

| Component | Purpose |
|-----------|---------|
| API (Node.js/Express) | Device registry, latest + historical data, querying, rules, external timeseries mappings (PostgreSQL / MySQL / MongoDB) |
| Visualiser (React + three.js) | Interactive 3D building viewer: add / move / pin devices, inspect data, align coordinate systems, debug spatial issues |

Runs locally with Docker Compose. Production: place behind a reverse proxy (Traefik / Nginx). Minimal environment configuration flips storage between MongoDB, PostgreSQL, and MySQL without client changes.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [Key Features](#key-features)
4. [Repository Layout](#repository-layout)
5. [Configuring Datastores (MongoDB / PostgreSQL / MySQL)](#configuring-datastores)
6. [Visualiser Usage Guide](#visualiser-usage-guide)
7. [Coordinate Alignment & Migration](#coordinate-alignment--migration)
8. [External Time‑Series Mappings (Experimental)](#external-time-series-mappings-experimental)
9. [Device Adjustment & Highlighting Workflow](#device-adjustment--highlighting-workflow)
10. [Scripts & Utilities](#scripts--utilities)
11. [Environment Variables Reference](#environment-variables-reference)
12. [Troubleshooting](#troubleshooting)
13. [Development (Local & Docker)](#development)
14. [Deployment Notes](#deployment-notes)
15. [License](#license)

---

## Quick Start

```pwsh
# From repo root
docker compose down -v
docker compose up -d --build
```

Open:
- Visualiser: http://localhost:8090/
- API health: http://localhost:5000/health  → `{ "status":"ok" }`
- Swagger UI: http://localhost:5000/api/

Switch to PostgreSQL (hot re‑provision):
```pwsh
docker compose down
setx DB_ENGINE postgres   # or edit docker-compose.yml env for api
docker compose up -d --build
```
> On Linux/macOS just export DB_ENGINE=postgres before `docker compose up`.

---

## Architecture Overview

```
┌──────────┐   REST / JSON   ┌──────────────────────┐
│ Visualiser│ ─────────────▶ │ API (Express)        │
│ (React +  │ ◀───────────── │ /api/... endpoints   │
│ three.js) │  WebSocket/SSE │ (Devices, Query,     │
└─────┬────┘   (future)      │  History, Latest,    │
  │                      │  Mappings, Rules)    │
  │                      └─────────┬────────────┘
  │                                 │
  │                                 │ Storage abstraction
  │                                 ▼
  │                     ┌─────────────────────┐
  │                     │ MongoDB OR PostgreSQL│
  │                     └─────────────────────┘
  │
  │ (Static GLB layers)
  ▼
 Building Model (GLB assets)
```

Datastore engines share a common interface so front‑end code never changes when switching.

---

## Key Features

### Spatial & Editing
* Replaceable building model (multi‑layer GLB manifest)
* Double‑click add device (name, type, floor)
* Live device movement with axis constraints & auto lock/unlock
* Lock / Pin management via sprite, HUD, or keyboard (P)
* Device highlight: selecting from list auto focuses camera, pulses emissive color, shows HUD

### Data & Telemetry
* Latest device data retrieval (storage agnostic)
* Historical queries / range filtering
* External time‑series mappings (Postgres table → virtual device feed) – experimental

### Coordinate System & Alignment
* Legacy offset support (force or heuristic)
* Auto center alignment (device cloud ↔ model floor)
* Scale factor suggestion (non‑destructive)
* Bounding box visual debug overlay
* Migration script to bake translation and optional scale

### UX & Debug Aids
* Orientation helpers (axes/grid toggles via X / G)
* Adjustable devices side panel with search-ready structure
* Floating settings panel (⚙) for alignment & debug toggles
* FPS / stats overlay (top-right, non‑blocking)

### API / Backend
* Pluggable datastore (MongoDB or PostgreSQL) via one env var
* Structured query endpoints & batch latest
* Rules and (optional) future SSE streaming foundation
* Admin DB disable/enable endpoints

### Tooling & Scripts
* Coordinate migration (scale + translation)
* Device bulk export/import (see routers/devicesBulk)
* Telemetry demo script (`demo.py`) for rapid live testing

---

## Repository Layout

```
.
├─ docker-compose.yml            # Compose file for mongo, api, visualiser
├─ LICENSE                       # MIT License
├─ README.md                     # This doc
├─ api/                          # Express API
│  ├─ Dockerfile
│  ├─ openapi.yaml               # Swagger spec served by the API
│  ├─ package.json
│  └─ src/
│     ├─ app.js                  # Express app entry
│     ├─ generate.js             # Seed/generate helpers
│     └─ api/
│        ├─ routers/             # Devices & data routes
│        ├─ middleware/
│        ├─ data/
│        │  └─ devices.json      # Mirrored device data (for convenience)
│        └─ ...
└─ visualiser/                   # React + three.js app
   ├─ Dockerfile
   ├─ package.json
   ├─ public/
   │  ├─ index.html
   │  └─ assets/
   │     ├─ manifest.json        # Which GLB layers to load
   │     └─ *.glb                # Your building layers
   └─ src/
      ├─ three/Graphics.js       # Scene, devices, HUD, interactions
      ├─ components/
      ├─ hooks/
      └─ views/
```

---

## Configuring Datastores

You can switch storage with a single environment variable: `DB_ENGINE`.

| Value | Engine | Notes |
|-------|--------|-------|
| `mongo` (default) | MongoDB | Device history collections per device |
| `postgres` | PostgreSQL  | Unified tables (`devices`, `device_data`, + advanced mappings & rules) |
| `mysql` | MySQL 8+ | Parity with Postgres feature set (JSON columns, mappings, rules) |
| `disabled` | In‑memory   | Read‑only (returns 503 for mutating data endpoints) |

Minimal change to use PostgreSQL or MySQL (both included in compose):
1. Set env: `DB_ENGINE=postgres` or `DB_ENGINE=mysql` (compose file or shell export).
2. Rebuild: `docker compose up -d --build`.
3. API auto creates tables if absent.

No front‑end changes required. JSON shapes are consistent across engines.

To revert: change to `mongo` and rebuild.

### When to choose which engine

| Scenario | Recommended Engine | Reason |
|----------|--------------------|--------|
| Quick local prototyping | `mongo` | Zero config, per‑device collections simple to inspect |
| Time‑series mappings + rules @ scale | `postgres` | Mature window functions & indexing strategy already tuned |
| MySQL ecosystem / existing infra | `mysql` | Full parity with Postgres features using JSON + window functions |

Performance characteristics:
* Postgres & MySQL use a single `device_data` table with composite index for fast latest + bounded history queries.
* Mongo uses one capped-like pattern per device (separate collection) — simple horizontal separation.
* External mappings and rules are available for both Postgres and MySQL; Mongo mode skips those tables.
* MySQL service port is not exposed by default in compose to avoid host port conflicts (e.g. an existing local MySQL on 3306). Uncomment and map to an alternate host port if you need direct CLI access (e.g. `3307:3306`).

---

## Visualiser Usage Guide

- Add a device: double-click on the floor to create a device at that spot; you’ll be prompted for name, type, and floor.
- Select a device: click its icon. A floating HUD shows the name and actions.
- Move a device: use the HUD buttons (↕ Move or ↔ Move) to constrain axes; the app will auto-unlock and re-lock if needed. Live position updates are PATCHed during move and a final save happens on release.
- Pin/unpin: click the lock sprite above the icon, use the HUD “Lock/Unlock” button, right-click the lock, or press P while hovering/selected.
- Deselect: click empty space, click the ✕ in the HUD, or press Escape.
- Camera: mouse wheel to zoom; right mouse button to orbit.

Occlusion & scaling: device icon & lock are sprites that scale with distance and occlude naturally behind geometry.

### Device Adjustment & Highlighting Workflow
* Open Adjust Devices panel (bottom-left handle) – lists all devices.
* Click a device in the list → scene auto focuses, mesh pulses, HUD appears.
* Edit X / Y / Z fields – live updates mesh before saving.
* Save or Cancel changes (cancel reverts to original position this session).
* Panel state can be toggled without losing drafts until save.

### Coordinate Alignment & Debug Tools

Goal: Bring legacy device coordinate clouds into the same origin & scale as the building model without permanently corrupting raw data until you choose to migrate.

Flags / Runtime Controls:
```
VITE_FORCE_LEGACY_OFFSET=true      # Always apply legacy translation (160,0,-120)
VITE_COORDS_NORMALIZED=true        # Mark device coords already normalized; disables heuristic legacy check
VITE_AUTO_ALIGN_DEVICES=true       # Compute & apply center alignment delta (cached in localStorage)
```
Or set at runtime before the app loads (DevTools early):
```
window.__ABACWS_FORCE_LEGACY_OFFSET__ = true;
window.__ABACWS_COORDS_NORMALIZED__ = true;
window.__ABACWS_AUTO_ALIGN__ = true;
```

Settings Panel (⚙ top‑right) lets you:
 - Toggle Auto Align (reload applies)
 - View Suggested Uniform Scale (ratio of model planar span to device cloud span)
 - Show Bounding Boxes (teal = devices, orange = model floor) for visual inspection

Scale Suggestion: Only calculated; NOT auto-applied. Use migration script if you want to bake scale + translation.

Migration Script (with scale + translation):
```
ALIGN_DELTA="dx,dy,dz" SCALE_FACTOR=1.234 \
  node visualiser/scripts/migrateDeviceCoords.js devices.json > devices-aligned.json
```

If you previously relied on auto alignment, grab cached delta from:
```
localStorage.getItem('__abacws_device_alignment_v1')
```
Then apply with SCALE_FACTOR (if desired) and import updated JSON into backend storage.

Bounding Boxes: Helpers can be toggled on/off; they do not persist and are ignored in interaction picking.

Debug Logging:
```
localStorage.setItem('__abacws_debug','1'); location.reload();
```
You will see `[ALIGN]` and scale suggestion events in console.

---

## Swapping / Managing the Building Model (GLB)

- Put your GLB files in `visualiser/public/assets/`.
- Edit `visualiser/public/assets/manifest.json` to list layer filenames in load order, for example:

```
{
  "layers": [
    "floors.glb",
    "exterior-walls.glb",
    "windows.glb",
    "stairs.glb",
    "glass.glb"
  ]
}
```

Tip: If your repo uses Git LFS for assets and you see tiny text files instead of real models, run:

```
git lfs install
git lfs pull
```

---

## API Overview

- Base URL (local): http://localhost:5000/api
- Swagger UI: http://localhost:5000/api/

Key endpoints (see full `api/openapi.yaml`):
- GET /devices — list all devices
- POST /devices — create a device
- GET /devices/{deviceName} — get one device
- PATCH /devices/{deviceName} — update type, floor, position, pinned
- GET /devices/{deviceName}/data — latest data for a device
- PUT /devices/{deviceName}/data — add data (optionally with units)
- GET /devices/{deviceName}/history — historical data
- DELETE /devices/{deviceName}/history — clear historical data
- GET /query — filter devices
- GET /query/data — filter devices and last data
- GET /query/history — filter devices and their history

Persistence engines:
* MongoDB (container `abacws-mongo`). Historical data per device is stored in per-device collections.
* PostgreSQL (container `abacws-postgres`). Tables:
  * `devices(name PRIMARY KEY, type, floor, pos_x, pos_y, pos_z, pinned, created_at, updated_at)`
  * `device_data(id bigserial PK, device_name FK→devices, timestamp bigint, payload jsonb)`
  * `data_sources`, `device_timeseries_mappings`, `device_rules` (advanced features)
* MySQL (container `abacws-mysql`). Schema mirrors Postgres using appropriate MySQL types (DOUBLE, JSON, ENUM). Uses window functions (MySQL 8+) for batch latest mapping aggregation.
* Disabled: `DB_ENGINE=disabled` serves devices from `devices.json` and keeps transient in‑memory history only (no persistence, write endpoints 503).

Runtime switching:
```
DB_ENGINE=postgres docker compose up -d --build
DB_ENGINE=mysql docker compose up -d --build
```
Or edit the `api` service environment in `docker-compose.yml`.

Data parity:
* All three engines expose identical JSON shapes to clients.
* `devices.json` remains a convenience mirror and is updated on creates/updates in any persistent mode.

Migration examples:
* Mongo → Postgres/MySQL: iterate each device collection and bulk insert into target `device_data` table (script not yet included).
* Postgres ↔ MySQL: dump / restore (schema is analogous; adjust auto‑increment & enum differences). JSON payloads portable.

Notes:
* Unique device name enforcement: Mongo index vs Postgres/MySQL primary key.
* Latest data lookup: Mongo sort/findOne vs Postgres/MySQL ORDER BY + LIMIT 1.
* History limits: capped at 10k per request (configurable).
* Disabled mode returns HTTP 503 for mutating endpoints while still allowing GET /devices.
* MySQL requires version 8+ (window functions used for mapping aggregation); earlier versions unsupported.

### External Time‑Series Mappings (Experimental)

You can map existing tables in the same Postgres cluster (e.g. a large time‑series fact table) to Abacws devices without ingesting or duplicating data.

Concepts:
- Data Source: connection + schema metadata (currently reuses main DB connection; future: separate host/credentials).
- Device Mapping: links a device name to a (table, device_id_column, device_identifier_value, timestamp_column, value_columns[]). Optionally pick a primary_value_column for sphere color scaling.

Endpoints (all under `/api` and documented in `openapi.yaml`):
- `GET /datasources` / `POST /datasources` / `PATCH /datasources/{id}` / `DELETE /datasources/{id}`
- `GET /datasources/{id}/tables` — list tables in schema
- `GET /datasources/{id}/columns?table=...` — list columns
- `GET /mappings` / `POST /mappings` / `PATCH /mappings/{id}` / `DELETE /mappings/{id}`
- `GET /mappings/device/{deviceName}/timeseries?from=..&to=..&limit=..`
- `GET /latest` — batch latest primary + value columns for all mapped devices (drives sphere coloration)

Example mapping payload (POST /mappings):
```json
{
  "device_name": "sensor_west_01",
  "data_source_id": 1,
  "table_name": "env_readings",
  "device_id_column": "sensor_id",
  "device_identifier_value": "west-01",
  "timestamp_column": "recorded_at",
  "value_columns": ["temperature_c", "humidity_pct"],
  "primary_value_column": "temperature_c"
}
```

UI Usage:
- Select a device → Data panel → External Time‑Series → Create/Edit Mapping.
- API key (x-api-key) for writes is read from `localStorage.abacws_api_key` (set manually via DevTools or future settings UI).
- After saving, page reload ensures hooks refetch; future enhancement: event-driven refresh.

Color Scaling:
- The `primary_value_column` is normalized across current latest values → gradient Blue (low) → Emerald (mid) → Red (high).
- Hover/Selection colors override the gradient temporarily.

Performance Notes:
- `/latest` groups mappings by (table, cols signature) to reduce queries.
- Per-device timeseries queries use indexed timestamp + device id predicates; ensure your source table has an index: `(sensor_id, recorded_at DESC)`.

Security & Credentials:
- Data source password is write-only (never returned).
- Avoid embedding production credentials in compose files; use environment variables / secrets.
- Future: separate pool per data source; currently assumes same DB for simplicity.

Limitations / Roadmap:
-- Only Postgres/MySQL engines implement external mappings & rules (Mongo omitted by design).
- No aggregation (avg, min/max) or resampling—client fetches raw rows up to a limit (default 2000).
- No transformation expressions; consider adding computed columns or views server-side.
- Manual reload after save; planned improvement: in-memory cache invalidation and hook refresh.

---

### Health endpoints

Top-level (implemented in `app.js`):
- `GET /health` → `{ status: 'ok', db: { engine, status, error? } }`
- `GET /health/db` → direct DB/engine status only

Legacy (router-level):
- `GET /api/health` → basic process status (points you to the top-level endpoint for DB detail)

### Admin DB toggle endpoints

Guarded by `x-api-key` header (value from `API_KEY` env, default placeholder):
- `POST /api/admin/db/disable` → Force a 503 on state-changing datastore operations (simulated offline)
- `POST /api/admin/db/enable` → Re-enable datastore operations
- `GET /api/admin/db/status` → `{ engine, forcedDisabled }`

UI: The visualiser shows a small status panel (top-left) with API status, DB engine, DB status, and a toggle button (needs API key to modify).

---

## Scripts & Utilities

| Script | Location | Purpose |
|--------|----------|---------|
| `migrateDeviceCoords.js` | `visualiser/scripts/` | Bake alignment (translation + optional scale) into device JSON |
| `check-assets.js` | `visualiser/scripts/` | Validate presence / size of GLB assets (avoid LFS pointer issues) |
| `demo.py` | project root | Continuously sends dummy telemetry to a device (default `node_5.20`) |

### demo.py Quick Use
```
pip install requests
python demo.py             # Sends every 5s
INTERVAL_SEC=2 python demo.py
```
Inspect latest device data via: `GET /api/devices/node_5.20/data`.

## Environment Variables Reference

### API / Backend
| Variable | Purpose | Default |
|----------|---------|---------|
| `DB_ENGINE` | `mongo` / `postgres` / `disabled` | `mongo` |
| `API_KEY` | Protect admin & (optionally) write ops | none |
| `PORT` | API listen port | 5000 |

### Visualiser (Vite build or runtime window overrides)
| Variable | Purpose |
|----------|---------|
| `VITE_FORCE_LEGACY_OFFSET` | Force legacy translation (160,0,-120) |
| `VITE_COORDS_NORMALIZED` | Assert coordinates already normalized |
| `VITE_AUTO_ALIGN_DEVICES` | Enable center alignment pass |
| `VITE_SHOW_FPS` (future) | Force show stats overlay |

Runtime (before bundle loads) equivalents: `window.__ABACWS_FORCE_LEGACY_OFFSET__`, `__ABACWS_COORDS_NORMALIZED__`, `__ABACWS_AUTO_ALIGN__`.

### External Mapping (future expansion)
| Variable | Purpose |
|----------|---------|
| `X_API_KEY` | Provided via `x-api-key` header for write operations | 

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Blank visualiser | Missing /assets GLBs or 404 to API | Check Network tab; pull LFS assets (`git lfs pull`) |
| GLB files ~130 bytes | Git LFS pointer files | Run `git lfs install && git lfs pull` |
| Devices misaligned | Legacy offset or origin mismatch | Use Settings (⚙) → Auto Align + bounding boxes; migrate when stable |
| No latest data updates | Polling disabled or datastore offline | Check API `/health`; ensure not `DB_ENGINE=disabled` |
| 503 errors on writes | Forced disabled via admin | POST `/api/admin/db/enable` with API key |
| Device create 409 | Duplicate name | Choose unique name or delete existing device |
| Postgres slow latest queries | Missing index | Ensure `(device_name, timestamp DESC)` index exists (auto created) |
| Mapping not returning data | Wrong identifier value / column case | Verify table + column names with `/datasources/{id}/columns` |

Enable debug logs in visualiser console:
```
localStorage.setItem('__abacws_debug','1'); location.reload();
```
Look for `[ALIGN]`, selection, and mapping batching logs.

## Development

Without Docker (optional):
- API: `cd api && npm install && npm run dev` (listens on 5000)
- Visualiser: `cd visualiser && npm install && npm start` (dev server with proxy to :5000)

With Docker:
- Compose handles builds and runs. Edit code and rebuild with `docker compose up -d --build`.

---

## Deployment Notes

- Reverse proxy (Traefik labels included in docker-compose.yml by default). Nginx/Apache are fine too.
- Visualiser container serves the production build (NGINX) on port 80; compose maps it to 8090 locally.
- Health checks:
  - API: GET /health → { status: "ok" }
  - Visualiser: GET /health (NGINX static 200)

---

## Contributing

PRs and issues welcome. Please run builds locally and sanity-check Docker compose before submitting.

---

## License

This project is licensed under the MIT License. See `LICENSE` for details.

Copyright (c) 2022–2025, the Abacws authors. All rights reserved.
