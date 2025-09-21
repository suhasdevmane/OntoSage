# Rasa UI Stack

This workspace contains a Rasa Open Source bot, a custom action server, a simple HTTP file server for artifacts, Duckling, and a React frontend.

## Services

- Rasa (5005): Core NLU/Dialogue engine
- Action Server (5055): Custom business logic, generates artifacts under `shared_data/artifacts`
- Duckling (8000): Entity extraction for dates/times and others
- HTTP File Server (8080): Serves artifacts and supports streaming and forced downloads
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
- Frontend: http://localhost:3000

## Environment variables

Action server accepts the following (see `docker-compose.yml`):

- BASE_URL: Public URL for file server; defaults to `http://localhost:8080`
- BUNDLE_MEDIA: `true|false` to bundle multiple media in one bot message
- DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT: MySQL connection (defaults target host.docker.internal)
- ANALYTICS_URL: Optional analytics service endpoint; if unset, analytics step is skipped

## Data & Artifacts

- Shared volume: `./shared_data` (mounted to action and http server)
- Artifacts directory: `./shared_data/artifacts`
- Media links use: `${BASE_URL}/artifacts/<filename>`

Handy utility:

```pwsh
# Move stray files in shared_data root into artifacts
./scripts/tidy_artifacts.ps1
```

## Development

- Actions code: `actions/actions.py` (mounted live into container)
- Frontend: `rasa-frontend` (Node dev server)
- Add or adjust NLU/Rules/Stories in `data/`

## Notes

- If MySQL isn’t available on the host, set DB_* envs accordingly or add a MySQL service to docker-compose.
- Remove/adjust large lookup lists if training becomes slow.
- The HTTP file server supports `?download=1` for forced downloads and Range requests for media streaming.
