<div align="center">

# OntoBot

Abacws SmartBot platform: end‑to‑end IoT analytics, knowledge‑graph querying, and a Rasa‑powered conversational interface. It orchestrates data services (MySQL, Jena Fuseki), analytics microservices, Rasa (NLU + Actions), web frontends, and helper tools via Docker Compose.

</div>

This project is under active development. If you need access to trained HF models or dataset versions, please get in touch.

## Contents

- Overview
- Architecture & services
- Quick start (Docker)
- Analytics API (Flask microservice)
- Rasa stack and UI
- Data stores and semantics
- Development workflow (optional local Python)
- Health checks and testing
- Troubleshooting
- License

---

## Overview

OntoBot connects building/IoT telemetry and semantic data with a chatbot and analytics. You can:

- Visualise device/room signals in a UI (frontend),
- Query semantic stores (SPARQL on Jena Fuseki),
- Ask questions in natural language (Rasa) with custom actions,
- Run analytics on timeseries payloads (Flask microservice),
- Manage data and files via a lightweight file server/editor.

All services run together via Docker for a reproducible dev setup.

---

## Architecture & services

See `docker-compose.yml` for full definitions. Active services (default) are:

- microservices (Flask analytics)
  - Health: http://localhost:6001/health
  - Analytics runner: http://localhost:6001/analytics/run
- MySQL (sensordb)
  - Host: localhost:3307 (maps to container 3306)
- Jena Fuseki (RDF/SPARQL)
  - UI/Ping: http://localhost:3030/$/ping
- Rasa (core server)
  - Version: http://localhost:5005/version
- Rasa Action Server (custom actions)
  - Health: http://localhost:5055/health
- Duckling (NER for time/quantities)
  - Root: http://localhost:8000/
- File server (Flask) for assets and helpers
  - Health: http://localhost:8080/health
- Rasa editor (lightweight admin/UX tool)
  - UI: http://localhost:6080/
- Rasa frontend (React dev server)
  - UI: http://localhost:3000/
- Decider service (analytics routing)
  - Health: http://localhost:6009/health

Optional services (commented in compose) you can enable as needed:

- ThingsBoard (IoT) + pgAdmin
- GraphDB (RDF store)
- Jupyter Notebook
- Visualiser + API (3D and REST)
- NL2SPARQL (T5) and Ollama (Mistral)

All services share the `ontobot-network` for internal DNS.

---

## Quick start (Docker)

Prerequisites: Docker Desktop (Windows/macOS) or Docker Engine (Linux).

Start core services:

```powershell
# From the repo root
docker-compose up -d
```

Stop all:

```powershell
docker-compose down
```

Rebuild a single service (example: microservices):

```powershell
docker-compose up microservices --build
```

---

## Analytics API (Flask microservice)

Base: http://localhost:6001

Endpoints:

- GET `/health` → `{ "status": "ok" }`
- POST `/analytics/run` → runs a named analysis on provided payload

Request body schema:

- `analysis_type` (string, required): one of the functions listed below
- Sensor data: either flat `{ sensorName: [ {timestamp|datetime, reading_value}, ... ] }` or nested standard payload `{ groupId: { innerKey: { timeseries_data: [...] } } }`
- Optional params: specific to each analysis (e.g., `acceptable_range`, `thresholds`, `method`, `window`)

Example:

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

- Environmental: `analyze_temperatures`, `analyze_humidity`, `analyze_co2_levels`, `analyze_pm_levels`, `analyze_noise_levels`, `analyze_formaldehyde_levels`, `analyze_air_quality`, `compute_air_quality_index`
- HVAC/air: `analyze_supply_return_temp_difference`, `analyze_air_flow_variation`, `analyze_pressure_trend`, `analyze_air_quality_trends`, `analyze_hvac_anomalies`
- Generic analytics: `correlate_sensors`, `aggregate_sensor_data`, `analyze_sensor_trend`, `detect_anomalies`, `detect_potential_failures`, `forecast_downtimes`
- Ops/maintenance: `analyze_device_deviation`, `analyze_failure_trends`, `analyze_recalibration_frequency`

Input handling highlights:

- Flat or nested payloads are accepted; timestamps normalized; key detection is robust.
- Units and UK indoor defaults are included in results when relevant (e.g., °C, %RH, ppm, µg/m³).

Smoke tests:

- Run the bundled script to exercise all endpoints:

```powershell
python microservices/test_analytics_smoke.py
```

It prints per‑analysis status and a summary; useful for quick regressions. Ensure the microservices container is running first.

---

## Rasa stack and UI

- Rasa core server: Docker image `rasa/rasa:3.6.12-full` listening on 5005.
- Action server: builds from `rasa-ui/actions`; environment wired to talk to:
  - Analytics service via `ANALYTICS_URL=http://microservices:6000/analytics/run`
  - Decider service via `DECIDER_URL=http://decider-service:6009/decide`
- Duckling: NER for times/durations/quantities on port 8000.
- Rasa editor: lightweight UI (port 6080) to inspect/edit.
- Rasa frontend: React development server (port 3000).

Shared data and models are mounted from `rasa-ui/` into containers for live iteration.

---

## Data stores and semantics

- MySQL (`mysqlserver`)
  - Host: `localhost:3307` (maps to container port 3306)
  - Default root password: `mysql`
  - Default DB: `sensordb`
- Jena Fuseki RDF store
  - Ping: http://localhost:3030/$/ping
  - Data volume: `jena-data` (see compose)

Optional (commented): ThingsBoard, GraphDB, Jupyter, Visualiser/API. Uncomment in `docker-compose.yml` to enable and adjust ports/credentials as needed.

---

## Development workflow (optional local Python)

You normally don’t need a local env if using Docker. If you want to run utilities locally:

```powershell
python -m venv ./.abacws-venv
./.abacws-venv/Scripts/Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Download extra NLP models as needed, e.g.:

```powershell
python -m spacy download en_core_web_sm
```

---

## Health checks and testing

Quick health probes (open in browser or curl):

- Microservices: http://localhost:6001/health
- Rasa: http://localhost:5005/version
- Action server: http://localhost:5055/health
- Duckling: http://localhost:8000/
- Jena Fuseki: http://localhost:3030/$/ping
- File server: http://localhost:8080/health
- Decider service: http://localhost:6009/health

Analytics smoke test:

```powershell
python microservices/test_analytics_smoke.py
```

It posts a realistic sample payload to each `/analytics/run` analysis and reports success/failure.

---

## Troubleshooting

- Ports busy: adjust host ports in `docker-compose.yml` (e.g., MySQL maps to 3307 by default).
- Service not healthy: check logs: `docker-compose logs -f <service>` and hit the health URL directly.
- Network issues: all services share `ontobot-network`. Inspect with `docker network inspect ontobot-network`.
- Analytics errors: verify your payload matches flat or nested formats; check `/analytics/run` response `results` for `{ error: ... }`.

---

## License

See the repository’s LICENSE file. Third‑party components retain their respective licenses.
