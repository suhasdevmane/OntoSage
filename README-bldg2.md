# OntoBot — Building 2 (TimescaleDB) Quick Guide

This guide covers running OntoBot for Building 2, which uses ThingsBoard backed by TimescaleDB (Postgres + Timescale extension) and its own Rasa project at `./rasa-bldg2`.

## Services and ports

- ThingsBoard UI: http://localhost:8082
- TimescaleDB (host): localhost:5433 → container 5432 (DB: thingsboard)
- Rasa: http://localhost:5005/version
- Rasa Action Server: http://localhost:5055/health
- Duckling: http://localhost:8000/
- HTTP File Server: http://localhost:8080/health
- Rasa Editor: http://localhost:6080/
- Rasa Frontend: http://localhost:3000/
- Analytics microservices: http://localhost:6001/health (maps container 6000)
- Decider Service: http://localhost:6009/health
- Jena Fuseki (SPARQL): http://localhost:3030/
- MySQL (legacy/migration): host 3307 → container 3306 (DB: sensordb)
- pgAdmin: http://localhost:5050/

All services are attached to the `ontobot-network` Docker network; internal DNS names are used in containers (e.g., `timescaledb`, `mysqlserver`).

## Quick start (PowerShell)

```powershell
# From repo root
# Optional: copy defaults and adjust
Copy-Item .env.example .env -ErrorAction SilentlyContinue

# Bring up Building 2 stack
docker compose -f docker-compose.bldg2.yml up -d --build

# Train Rasa (one-off job)
docker compose -f docker-compose.bldg2.yml --profile manual up --build --abort-on-container-exit rasa-train

# Tail logs for a service (examples)
docker compose -f docker-compose.bldg2.yml logs -f --tail 200 rasa
```

## Extras overlay (optional)

Layer optional services (NL2SPARQL, GraphDB, Jupyter, Ollama, Adminer) on top of bldg2:

```powershell
docker compose -f docker-compose.bldg2.yml -f docker-compose.extras.yml up -d --build
# … later
docker compose -f docker-compose.bldg2.yml -f docker-compose.extras.yml down
```

Notes:
- `adminer` depends on MySQL in the base stack (present in bldg2 compose).
- `nl2sparql` and `ollama` are optional; set `NL2SPARQL_URL` / `SUMMARIZATION_URL` in the action server if you enable them.

## Load the dataset (Fuseki)

- Fuseki is at http://localhost:3030/
- The container mounts `./bldg2/trial/dataset` at `/fuseki-data`.
- Use the Fuseki UI to create/load a dataset from the TTL files in `bldg2/trial/dataset`.

## pgAdmin (Timescale)

- UI: http://localhost:5050/
- Pre-configured via `bldg2/servers.json`.
- Credentials (defaults; set in `.env`):
  - Username: `thingsboard`
  - Password: `thingsboard`
  - Database: `thingsboard`

Two useful connections:
- Inside Docker network: host `timescaledb`, port `5432`.
- From host: host `localhost`, port `5433`.

## Test Rasa and ThingsBoard

Rasa REST test:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:5005/webhooks/rest/webhook -ContentType 'application/json' -Body (@{
  sender = 'tester1'
  message = 'What is the average temperature last week in Zone A?'
} | ConvertTo-Json)
```

Send telemetry to TB (HTTP transport example):

```powershell
# Replace <DEVICE_TOKEN>
Invoke-WebRequest -Method Post -Uri "http://localhost:8081/api/v1/<DEVICE_TOKEN>/telemetry" -ContentType "application/json" -Body '{ "temperature": 23.7 }'
```

## Environment (.env)

Copy `.env.example` to `.env` and adjust for your environment. Relevant keys used in this stack include:
- `PG_THINGSBOARD_DB`, `PG_THINGSBOARD_USER`, `PG_THINGSBOARD_PASSWORD`
- `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD`
- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (MySQL legacy)
- `JWT_SECRET`, `FRONTEND_ORIGIN`, `ALLOWED_ORIGINS`
- Optional: `NL2SPARQL_URL`, `SUMMARIZATION_URL`, `JUPYTER_TOKEN`, `GRAPHDB_PASSWORD`

Security note: defaults are for local development—change them in shared or production environments.
