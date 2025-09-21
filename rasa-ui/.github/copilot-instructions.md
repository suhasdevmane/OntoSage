# AI agent instructions for this repo

This workspace is a dockerized Rasa stack with five services and a shared artifacts volume. Read this before making changes.

## Architecture at a glance
- Services (see `docker-compose.yml`):
  - Rasa (5005): NLU/dialogue engine. Talks to custom actions at 5055 via `endpoints.yml`.
  - Action server (5055): Python (rasa-sdk). Generates files into `shared_data/artifacts/<username>/...` and returns URLs for the frontend.
  - Duckling (8000): Time/number entity extraction used by Rasa (date ranges, etc.).
  - HTTP file server (8080): Flask app serving `./shared_data` with CORS, Range streaming, and forced downloads via `?download=1`. Also exposes minimal auth/history APIs.
  - React frontend (3000): Chat UI that renders attachments (json/csv/pdf/audio/video/html) and syncs chat history.
- Shared volume: `./shared_data` is mounted into the action server at `/app/shared_data` and into the HTTP server at `/data`. The frontend receives links like `http://localhost:8080/artifacts/<username>/<file>`.

## Data flow and per-user storage
- Login/register happens against the HTTP server (`/api/login`, `/api/register`). Users are stored in SQLite at `/data/auth/users.db` with password hashing.
- Chat history persists per user:
  - Frontend keeps a Dexie cache and also syncs to `/api/get_history` and `/api/save_history`.
  - Server stores `shared_data/artifacts/<username>/chat_history.json`.
- Actions write all generated outputs under `shared_data/artifacts/<username>/` based on `tracker.sender_id` (username). URLs are constructed with `BASE_URL` (default `http://localhost:8080`).

## Important code locations
- Actions: `actions/actions.py`
  - Helpers: `get_user_artifacts_dir(tracker)` chooses the per-user folder, `sanitize_username` constrains folder names.
  - Key actions: `ActionQuestionToBrickbot`, `ActionProcessTimeseries`, and `ActionGenerateAndShareData` write files under the user directory and return attachments with URLs.
  - DB: Timeseries queries target MySQL via env DB_* (defaults to host.docker.internal). Duckling used for dates. Optional analytics via `ANALYTICS_URL` if set.
- File server: `file_server.py`
  - Serves `ROOT_DIR=/data`; routes `/<path>` with CORS, Range, and forced download. Health at `/health`.
  - Minimal APIs: `/api/register`, `/api/login`, `/api/get_history`, `/api/save_history` using SQLite and JSON files per user.
- Frontend: `rasa-frontend/src`
  - `components/Login.js` calls the HTTP APIs and sets `sessionStorage.currentUser`.
  - `components/ChatBot.js` posts to Rasa with `sender=<username>`, renders attachments, and syncs chat history with the server and Dexie (`src/db.js`).

## Conventions and patterns
- All artifacts live under `shared_data/artifacts/<username>`; never write directly to repo root.
- Attachment objects returned by actions should include: `{ type, url, filename }`. For bundling, send `json_message: { media: [...] }`.
- Media URLs must be built as `${BASE_URL}/artifacts/<username>/<filename>` where `BASE_URL` comes from env.
- Date handling: prefer DD/MM/YYYY or YYYY-MM-DD, convert to SQL `YYYY-MM-DD HH:MM:SS` before querying.
- Keep Duckling and MySQL optional via envs; handle absence gracefully and log.

## Build/run workflows
- Dev stack:
  - From repo root: `docker-compose up --build` (Windows PowerShell)
  - Rasa: http://localhost:5005, Actions: http://localhost:5055/health, File server: http://localhost:8080/health, Frontend: http://localhost:3000
- Live-mounts:
  - `actions/actions.py` is bind-mounted into the actions container; edits are hot-reloaded by the rasa-sdk server process.
  - `shared_data/` is a bind mount; generated files appear immediately under `shared_data/artifacts/...`.
- Training and tests:
  - Train models by running `rasa train` inside the Rasa container if needed.
  - Story tests live in `tests/test_stories.yml` (minimal). Use `rasa test` for dialogue evaluation.

## External dependencies
- Python libs for actions are in `requirements.txt` (rasa-sdk, SPARQLWrapper, mysql-connector-python, plotly, dateparser, ollama etc.).
- Frontend uses CRA; media rendering is custom in `components/MediaRenderer.js` and `components/Message.js`.

## Gotchas and tips
- Always pass the username from the frontend as the Rasa `sender` so the action server writes into the right user folder.
- When adding a new action that saves files, use `get_user_artifacts_dir(tracker)` and construct URLs with `BASE_URL`.
- The file server supports partial content. For downloads, append `?download=1`.
- Healthchecks are defined in compose; keep route contracts stable (`/health`).
- If you change ports or BASE_URL, update both compose env and frontend constants.

## Example: saving a new artifact in an action
```python
user_safe, user_dir = get_user_artifacts_dir(tracker)
name = f"result_{int(time.time())}.json"
path = os.path.join(user_dir, name)
with open(path, 'w') as f: json.dump(payload, f)
url = f"{os.getenv('BASE_URL', BASE_URL_DEFAULT)}/artifacts/{user_safe}/{name}"
dispatcher.utter_message(attachment={"type": "json", "url": url, "filename": name})
```
