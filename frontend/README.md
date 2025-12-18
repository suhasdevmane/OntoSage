# Rasa Frontend (React)

Chat UI for the OntoBot stack. Connects to the Rasa server and renders rich responses, links, and media served by the file server. For full platform architecture, deployment instructions, analytics payload formats, and NL→SPARQL details, see the root `README.md`.

All building stacks now share the SAME host ports (only one runs at a time):
- Frontend: http://localhost:3000
- Rasa: http://localhost:5005
- Action Server: http://localhost:5055/health
- Duckling: http://localhost:8000
- File Server: http://localhost:8080/health
- Rasa Editor: http://localhost:6080/health

If you later adopt a concurrent multi‑building isolation strategy you can reintroduce port offsets (e.g. +10, +20) via compose edits.

## Available Scripts

### `npm start`
Development mode; opens http://localhost:3000. Reloads on file changes and shows lint errors in console.

### `npm test`
Runs the test runner in watch mode.

### `npm run build`
Creates a production build in `build/` (minified, hashed filenames).

### `npm run eject`
One‑way extraction of all configuration (webpack, Babel, ESLint). Avoid unless deep customization is required.

## Configuration

Injected via Docker Compose environment:
- Rasa server URL: `http://localhost:5005`
- File server base URL: `http://localhost:8080`
- FRONTEND_ORIGIN / ALLOWED_ORIGINS: should match the frontend origin (`http://localhost:3000`)

SPARQL/ontology and analytics calls are indirect—handled by the Action Server and NL2SPARQL service; no direct config needed here.

## Customize for your building

- Update UI labels to reflect building‑specific sensor naming conventions.
- Add quick‑action buttons for frequent analytics queries (temperature trends, humidity anomalies, etc.).
- Keep intent and slot names aligned with the active Rasa project (`rasa-bldg1`, `rasa-bldg2`, or `rasa-bldg3`).

## End-to-end flow

1. User sends a message.
2. Rasa interprets intent/entities.
3. Action Server may query SPARQL (Fuseki), gather telemetry (SQL or Cassandra), call Analytics, and/or translate NL→SPARQL.
4. Generated artifacts (plots/CSV) saved to shared volume and exposed by File Server.
5. Frontend renders text plus rich cards & artifact links.

## Optional concurrent multi-building (future)

If you decide to run multiple buildings simultaneously (not default):
- Assign unique host ports (e.g. 3000/3010/3020, 8080/8090/8100, etc.).
- Add suffixes to container names for clarity.
- Adjust FRONTEND_ORIGIN / ALLOWED_ORIGINS per stack.

## CRA Reference

Standard Create React App docs:
- Code splitting: https://facebook.github.io/create-react-app/docs/code-splitting
- Bundle analysis: https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size
- Progressive Web App: https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app
- Advanced configuration: https://facebook.github.io/create-react-app/docs/advanced-configuration
- Deployment: https://facebook.github.io/create-react-app/docs/deployment
- Troubleshooting: https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify
