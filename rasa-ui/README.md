# Rasa UI Stack

This workspace contains a Rasa Open Source bot, a custom action server, a simple HTTP file server for artifacts, Duckling, an editor, and a React frontend. It integrates with the analytics microservice and optional decider service.

## Services

- Rasa (5005): Core NLU/Dialogue engine
- Action Server (5055): Custom business logic; calls Analytics and Decider; generates artifacts under `shared_data/artifacts`
- Duckling (8000): Entity extraction for dates/times and others
- HTTP File Server (8080): Serves artifacts and supports streaming and forced downloads
- Rasa Editor (6080): Lightweight project editor and admin
- React Frontend (3000): Chat UI rendering media and links

## Run

The stack is dockerized.

```pwsh
# From repo root
docker-compose up --build
```

- Rasa: http://localhost:5005
- Actions health: http://localhost:5055/health (basic curl ok)
- File server: http://localhost:8080/health (returns {"status":"ok"})
- Editor: http://localhost:6080
- Frontend: http://localhost:3000

## Environment variables

Action server (see repo `docker-compose.yml`):

- BASE_URL: Public URL for file server; defaults to `http://localhost:8080`
- BUNDLE_MEDIA: `true|false` to bundle multiple media in one bot message
- DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT: MySQL connection (container-internal defaults set)
- ANALYTICS_URL: Analytics endpoint; defaults `http://microservices:6000/analytics/run` in Docker network
- DECIDER_URL: Decider endpoint; defaults `http://decider-service:6009/decide`

## Data & Artifacts

- Shared volume: `./shared_data` (mounted to action server, http server, and editor)
- Artifacts directory: `./shared_data/artifacts`
- Media links: `${BASE_URL}/artifacts/<filename>`

Handy utility:

```pwsh
# Move stray files in shared_data root into artifacts
./scripts/tidy_artifacts.ps1
```

## Development

- Actions code: `actions/actions.py` (mounted live into container)
- Frontend: `rasa-frontend` (Node dev server)
- Add or adjust NLU/Rules/Stories in `data/`

### Customize for different buildings

- Intents/entities: add building/location/device-specific vocabulary in `data/` and `domain.yml`.
- Sensor mapping: implement UUID→sensor name mapping in actions (stored under `shared_data/`), so analytics receive human-readable keys.
- Knowledge sources: connect to MySQL, Jena Fuseki, or others via actions; store credentials using env vars and secrets.

### End-to-end analytics flow

1) User asks a question in the frontend.
2) Rasa NLU detects intent/entities; a custom action is triggered.
3) Action queries DB/knowledge store, maps UUIDs→names, builds a standardized flat/nested payload.
4) Action optionally calls Decider to pick an analysis, then posts payload to Analytics.
5) Analytics returns results with units and UK defaults; action formats a user-facing message and media.
6) File server hosts generated artifacts; frontend renders content.

## Notes

- If MySQL isn’t available on the host, set DB_* envs accordingly or add a MySQL service to docker-compose.
- Remove/adjust large lookup lists if training becomes slow.
- The HTTP file server supports `?download=1` for forced downloads and Range requests for media streaming.
 - Use the Editor (6080) to quickly review and tweak NLU data during development.
