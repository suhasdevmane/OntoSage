<div align="center>

# OntoBot

A production‑ready, end‑to‑end platform for human–building conversation: Rasa (NLU + Actions), robust analytics microservices, SQL/SPARQL knowledge stores, and a web UI—all orchestrated with Docker Compose.

</div>

> Last updated: 2025‑09‑28

This README consolidates the ground‑truth docs from each service into a single guide.

## Contents

- What is OntoBot?
- Architecture and services
- Install and run (Docker)
- Configuration and environment
- Data and payloads
- Analytics API (microservices)
- Rasa actions and Decider flow
- Customization for new buildings
- Testing and operations
- Troubleshooting
- License

---

## What is OntoBot?

OntoBot connects building/IoT telemetry and semantic data to a conversational interface and analytics.
You can:

- Ask questions in natural language (Rasa) and get unit‑aware answers.
- Run time‑series analytics via a standardized payload (Flask microservice).
- Query semantic data (SPARQL on Jena Fuseki) and SQL telemetry.
- Serve artifacts (plots/csv) through a file server for the frontend.

All services are containerized and wired together for repeatable local dev.

---

## Architecture and services

See `docker-compose.yml` for definitive configuration. Default services:

- Analytics microservices (Flask)
  - Health: http://localhost:6001/health
  - Runner: http://localhost:6001/analytics/run
- MySQL telemetry
  - Host: localhost:3307 → container 3306, DB `sensordb` (root: mysql)
- Jena Fuseki RDF/SPARQL
  - Ping: http://localhost:3030/$/ping
- Rasa (core server)
  - Version: http://localhost:5005/version
- Rasa Action Server
  - Health: http://localhost:5055/health
- Duckling NER
  - Root: http://localhost:8000/
- HTTP File server
  - Health: http://localhost:8080/health
- Rasa Editor
  - UI: http://localhost:6080/
- Rasa Frontend (React)
  - UI: http://localhost:3000/
- Decider Service
  - Health: http://localhost:6009/health

Optional (commented) services:
- ThingsBoard + pgAdmin
- GraphDB
- Jupyter Notebook
- Abacws API + Visualiser
- NL2SPARQL (T5) and Ollama (Mistral)

All services share the `ontobot-network` for internal DNS.

---

## Install and run (Docker)

Prereqs: Docker Desktop (Windows/macOS) or Docker Engine (Linux).

Start everything:

```powershell
# From repo root
docker-compose up -d
```

Rebuild a service (example: analytics microservices):

```powershell
docker-compose up microservices --build
```

Stop all:

```powershell
docker-compose down
```

Health URLs (open in a browser):

- http://localhost:6001/health (analytics)
- http://localhost:5005/version (rasa)
- http://localhost:5055/health (actions)
- http://localhost:8080/health (file)
- http://localhost:3030/$/ping (fuseki)
- http://localhost:6009/health (decider)

---

## Configuration and environment

Action Server environment (see `docker-compose.yml`):

- BASE_URL: Public URL for the file server; default http://http_server:8080 (internal) / http://localhost:8080 (host)
- DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT: MySQL connection (defaults set for container)
- ANALYTICS_URL: http://microservices:6000/analytics/run (internal)
- DECIDER_URL: http://decider-service:6009/decide (internal)
- BUNDLE_MEDIA: Optional; bundle multiple media into one bot message (true/false)

Volumes:
- `./shared_data` is mounted to actions, file server, and editor.
- Artifacts (plots/csv) are placed under `./shared_data/artifacts` and served via the file server.

---

## Data and payloads

Standardized payloads are accepted by analytics:

- Flat: `{ sensorName: [ { timestamp|datetime, reading_value }, ... ] }`
- Nested: `{ groupId: { innerKey: { timeseries_data: [ { datetime, reading_value }, ... ] } } }`

Notes:
- UUID → Sensor name mapping is done in actions before analytics.
- Timestamps are normalized server‑side; keys are matched robustly (e.g., temperature vs temp but not attempt).
- Units and UK indoor guidelines are included in results (where applicable): °C, %RH, ppm, µg/m³, dB(A), etc.

---

## Analytics API (microservices)

Base: http://localhost:6001

Endpoints:
- GET `/health` → `{ "status": "ok" }`
- POST `/analytics/run`
  - Body:
    - `analysis_type` (string, required)
    - Sensor data (flat or nested payload)
    - Optional params per analysis (acceptable_range, thresholds, method, window)
  - Returns: `{ analysis_type, timestamp, results }`

Example request (nested):

```json
{
  "analysis_type": "analyze_temperatures",
  "1": {
    "Air_Temperature_Sensor": {
      "timeseries_data": [
        {"datetime": "2025-02-10 05:31:59", "reading_value": 22.5},
        {"datetime": "2025-02-10 05:33:00", "reading_value": 23.0}
      ]
    }
  }
}
```

Available analyses (selection):
- Environmental: temperatures, humidity, CO2, PM, HCHO, noise, AQI metrics
- HVAC/air: supply/return delta‑T, airflow variation, pressure trend, quality trends, HVAC anomalies
- Generic: correlation, aggregation, trend, anomalies (zscore/iqr), potential failures, downtime forecast
- Ops: device deviation, failure trends, recalibration frequency

Smoke test:

```powershell
python microservices/test_analytics_smoke.py
```

This exercises all registered analyses using dummy data and reports a summary.

---

## Rasa actions and Decider flow

- Actions query SQL/SPARQL/files and build standardized payloads.
- UUIDs are replaced with human‑readable sensor names prior to analytics.
- Actions optionally call the Decider service first to choose an `analysis_type` for the user question.
- Actions post to `/analytics/run`, then format a user‑facing message including units and thresholds, and save any artifacts to `shared_data/artifacts`.

Internal endpoints (Docker network):
- Analytics: http://microservices:6000/analytics/run
- Decider: http://decider-service:6009/decide
- File server: http://http_server:8080

---

## Customization for new buildings

- Extend Rasa intents/entities with site‑specific devices/locations.
- Prepare and load sensor UUID→name mappings; use descriptive keys in analytics.
- Override thresholds in analytics requests (acceptable_range/thresholds) to match building standards.
- Connect to your MySQL/Fuseki instances via env vars and secrets.
- Optional Visualiser/API can be enabled and pointed at your data via API_HOST.

---

## Testing and operations

Health probes:
- Analytics: /health; Rasa: /version; Actions: /health; File: /health; Fuseki: $/ping; Decider: /health.

Logs:
- `docker-compose logs -f <service>`

Networking:
- All services share the `ontobot-network`. Inspect with `docker network inspect ontobot-network`.

CI hooks (optional):
- Run the analytics smoke test in PRs to guard regressions.

---

## Troubleshooting

- Port conflicts → adjust host ports in `docker-compose.yml` (MySQL maps to 3307 by default).
- Service unhealthy → check logs; hit health URLs directly.
- Analytics errors → verify flat/nested payloads; inspect the `results` object for detailed errors.
- Missing media → confirm files exist under `shared_data/artifacts` and the file server is reachable at the expected BASE_URL.

---

## License

See LICENSE in this repository. Third‑party components retain their respective licenses.
