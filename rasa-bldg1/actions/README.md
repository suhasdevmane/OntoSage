# Rasa Custom Actions

Custom business logic that powers the conversational flow, integrates data sources, and calls analytics.

## Key responsibilities

- Query data sources (MySQL, SPARQL/Jena Fuseki, files) based on user intents/entities.
- Replace UUIDs with human-readable sensor names before analytics.
- Build standardized payloads for analytics (flat or nested) and call the appropriate `analysis_type`.
- Summarize results with units and thresholds; generate artifacts for the chat UI.

## Standard analytics payload

Accepted by analytics service `/analytics/run`:

- Flat form: `{ sensorName: [ {datetime|timestamp, reading_value}, ... ] }`
- Nested form: `{ groupId: { key: { timeseries_data: [ {datetime, reading_value}, ... ] } } }`

Either form is accepted; analytics normalizes timestamps and merges groups where needed.

## Service endpoints

- Analytics: `http://microservices:6000/analytics/run` (Docker internal)
- Decider: `http://decider-service:6009/decide`
- File server: `http://http_server:8080` for hosting artifacts

These are configured via env vars in repo-level `docker-compose.yml` and should not require change for local dev.

## MySQL connection modes (bldg1)

This building uses MySQL only. Two modes are supported by `actions.py`:

- Docker MySQL (default): DB_HOST=mysqlserver, DB_PORT=3306, DB_USER=root, DB_PASSWORD=mysql
- Local laptop MySQL: set `USE_LOCAL_MYSQL=true` and optionally provide `LOCAL_DB_HOST`, `LOCAL_DB_PORT`, `LOCAL_DB_USER`, `LOCAL_DB_PASSWORD`.
	- Defaults for local mode: host.docker.internal:3306, user=root, password=root

Environment variables honored:

- USE_LOCAL_MYSQL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
- LOCAL_DB_HOST, LOCAL_DB_PORT, LOCAL_DB_USER, LOCAL_DB_PASSWORD

Table name defaults to `sensor_data` and can be overridden via `DB_TABLE`.

## UUID → Sensor name mapping

- Maintain mapping tables under `shared_data/` or query your device registry.
- Perform the replacement in actions before building the payload.
- Prefer descriptive keys (e.g., `Air_Temperature_Sensor` instead of UUID) to improve analytics matching and end-user clarity.

## Adding a new analytical skill

1) Check available `analysis_type`s in `microservices`.
2) If needed, add a new function there and expose it via `/analytics/run` registry.
3) Add a new custom action that constructs the payload and calls analytics.
4) Update NLU (intents/entities) and stories/rules to trigger your action.

## Customizing for a new building

- Expand intents/entities with building-specific devices/locations.
- Update sensor mapping files and database connectors.
- Override thresholds in analytics calls (e.g., pass `acceptable_range` or `thresholds`) to meet your site standards.

## Testing

- Unit-test actions with Rasa test harness or small scripts.
- End-to-end: start the stack via `docker-compose up` and use the frontend; monitor action logs for calls to analytics and decider.

<!-- Intentionally left building-agnostic. Each building model should carry its own training data and domain config. -->
