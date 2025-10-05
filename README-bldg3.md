# OntoBot — Building 3 (Cassandra) Quick Guide

This guide covers running OntoBot for Building 3, which uses ThingsBoard with telemetry in Cassandra and ThingsBoard entities in Postgres. The Rasa project lives at `./rasa-bldg3`.

## Services and ports

- ThingsBoard UI: http://localhost:8082
- TB Postgres (host): localhost:5434 → container 5432 (metadata only)
- Cassandra (CQL): localhost:9042
- Rasa: http://localhost:5006/version (host 5006 → container 5005)
- Rasa Action Server: http://localhost:5056/health (host 5056 → container 5055)
- Duckling: http://localhost:8001/
- HTTP File Server: http://localhost:8084/health (host 8084 → container 8080)
- Rasa Editor: http://localhost:6081/
- Rasa Frontend: http://localhost:3001/
- Analytics microservices: http://localhost:6002/health (maps container 6000)
- Decider Service: http://localhost:6010/health (maps container 6009)
- Jena Fuseki (SPARQL): http://localhost:3030/
- MySQL (legacy/migration): host 3308 → container 3306 (DB: sensordb)
- pgAdmin: http://localhost:5051/

All services share the `ontobot-network`. Containers use internal DNS names (e.g., `tb_postgres`, `cassandra`, `mysqlserver`).

## Quick start (PowerShell)

```powershell
# From repo root
# Optional: copy defaults and adjust
Copy-Item .env.example .env -ErrorAction SilentlyContinue

# Bring up Building 3 stack
docker compose -f docker-compose.bldg3.yml up -d --build

# Train Rasa (one-off job)
docker compose -f docker-compose.bldg3.yml --profile manual up --build --abort-on-container-exit rasa-train

# Tail logs for a service (examples)
docker compose -f docker-compose.bldg3.yml logs -f --tail 200 rasa
```

## Extras overlay (optional)

Add NL2SPARQL, GraphDB, Jupyter, Ollama, and Adminer on top of bldg3:

```powershell
docker compose -f docker-compose.bldg3.yml -f docker-compose.extras.yml up -d --build
# … later
docker compose -f docker-compose.bldg3.yml -f docker-compose.extras.yml down
```

Notes:
- `adminer` depends on MySQL in the base stack (present in bldg3 compose).
- `nl2sparql` and `ollama` are optional; set `NL2SPARQL_URL` / `SUMMARIZATION_URL` in the action server if you enable them.

## Load the dataset (Fuseki)

- Fuseki: http://localhost:3030/
- Mounts `./bldg3/trial/dataset` at `/fuseki-data` in the container.
- Use the UI to create/load a dataset from your `bldg3/trial/dataset/*.ttl` files.

## pgAdmin (TB Postgres metadata)

- UI: http://localhost:5051/
- Pre-configured via `bldg3/servers.json`.
- Credentials (defaults; see `.env`):
  - Username: `thingsboard`
  - Password: `thingsboard`
  - Database: `thingsboard`

Useful queries (device token → device UUID):

```sql
SELECT d.id, d.name
FROM device d
JOIN device_credentials dc ON dc.device_id = d.id
WHERE dc.credentials_id = 'YOUR_DEVICE_ACCESS_TOKEN';
```

Note: time-series telemetry is stored in Cassandra; use TB dashboards/APIs or `cqlsh` to explore telemetry.

## Test Rasa and ThingsBoard

Rasa REST test:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:5006/webhooks/rest/webhook -ContentType 'application/json' -Body (@{
  sender = 'tester1'
  message = 'Show humidity trends for last week in Zone B'
} | ConvertTo-Json)
```

Send telemetry to TB (HTTP transport example):

```powershell
# Replace <DEVICE_TOKEN>
Invoke-WebRequest -Method Post -Uri "http://localhost:8080/api/v1/<DEVICE_TOKEN>/telemetry" -ContentType "application/json" -Body '{ "humidity": 48 }'
```

## Environment (.env)

Copy `.env.example` to `.env` and adjust as needed. Relevant keys:
- `PG_THINGSBOARD_DB`, `PG_THINGSBOARD_USER`, `PG_THINGSBOARD_PASSWORD`
- `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD`
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (MySQL legacy)
- `JWT_SECRET`, `FRONTEND_ORIGIN`, `ALLOWED_ORIGINS`
- Optional: `NL2SPARQL_URL`, `SUMMARIZATION_URL`, `JUPYTER_TOKEN`, `GRAPHDB_PASSWORD`

Security note: defaults are for local development—change them for shared or production environments.
