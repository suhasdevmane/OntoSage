# Rasa Custom Actions (Building 1)

This directory contains the high‑leverage orchestration logic that turns a user question into:

Natural Language → (Optional) NL→SPARQL Translation → SPARQL (Fuseki) → Ontology Results → (Optional) Timeseries UUID Extraction → (Optional) Analytics Microservice → Local LLM Summarization (Ollama/Mistral) → Final Chat Response + Artifacts.

---
## 🚩 Recent Enhancements (Oct 2025)

| Area | Change | Rationale |
|------|--------|-----------|
| Sensor Mapping | Unified cached loader `_load_sensor_uuid_map()` with env override `SENSOR_UUIDS_FILE` | Eliminates duplicate loaders & silent file creation; predictable resolution order |
| Analytics Type Selection | Decider + heuristic fallback + validation against dynamic registry | Robust, extensible, avoids stale/unsupported analytics types |
| Message Verbosity | Frontend “Details” toggle + `emit_message(detail=True)` gating | Cleaner UX for non‑technical users while retaining deep logs on demand |
| Summarization | Minimal ontology‑only prompt when no timeseries UUIDs; enriched path only for analytics/timeseries flows | Reduces token noise & latency, improves relevance |
| SPARQL Reliability | Case normalization retry for `_sensor_` → `_Sensor_` + full prefixed query logging | Prevents silent false negatives due to naming inconsistencies |
| Error Visibility | Auto‑critical bypass for messages containing error/failure/timeout keywords | Ensures important failures still surface when details are hidden |
| Artifacts | Consistent per‑user artifacts directory with timestamped JSON dumps | Traceability & reproducibility of answers |

---
## 🔌 Core Responsibilities

1. Interpret intent & determine query type (listing vs metric vs unknown).
2. Optionally call NL2SPARQL translator (T5) to get a raw SPARQL skeleton.
3. Execute SPARQL against Fuseki, log raw + prefixed query, standardize bindings.
4. Extract timeseries UUIDs → decide whether to branch into analytics.
5. Decide analytics type (external Decider service OR fallback heuristics).
6. Fetch SQL telemetry (MySQL for Building 1) within the requested or inferred date window.
7. Build canonical analytics payload (collapsing or preserving sensor names depending on analysis type).
8. Call analytics microservice (optional) and merge/transform response.
9. Replace UUIDs with descriptive sensor names using cached mapping.
10. Summarize (ontology-only OR analytics-enhanced) via local Mistral model.
11. Emit gated progress + always-show critical outputs to frontend; save artifacts.

---
## 🧠 Analytics Type Decision Flow

Decision only proceeds if at least one valid timeseries UUID is extracted. Then:

1. External Decider (`DECIDER_URL`) → expects `{ perform_analytics: bool, analytics: <type> }`.
2. If absent/failure: fallback `_pick_type_from_context(question, sensor_types)` uses keyword groups:
	 - humidity → `analyze_humidity`
	 - temp/temperature → `analyze_temperatures`
	 - co2 → `analyze_co2_levels`
	 - pm/particulate → `analyze_pm_levels`
	 - correlate/correlation/relationship → `correlate_sensors`
	 - anomaly/outlier/abnormal/fault/failure → `detect_potential_failures`
	 - trend/time series/history/timeline/over time → `analyze_sensor_trend`
	 - default fallback → `analyze_sensor_trend`
3. “Structural / ontology” questions (keywords: label, type, class, category, installed, location, where is, which sensors, list sensors, show sensors) explicitly suppress analytics.
4. Candidate is validated against dynamic `_supported_types()` (remote registry + static fallback). Unsupported → fallback heuristic.
5. Final choice stored in slot `analytics_type`; passed to `ActionProcessTimeseries` which re-validates.

Special handling:
- `correlate_sensors` keeps full sensor instance names (no collapsing) to preserve distinct series.
- `analyze_humidity` retains specific instance keys (avoids merging rooms/zones and double counting).
- All other analytics collapse multiple instances to a base sensor key (e.g., `Zone_Air_Humidity_Sensor`).

---
## 🗂 Sensor UUID Mapping Loader

Implemented once at module level:
Resolution order → `SENSOR_UUIDS_FILE` (env path) → `./sensor_uuids.txt` → `./actions/sensor_uuids.txt`.

Features:
- Bidirectional dict (name→uuid and uuid→name).
- mtime + periodic reload (`SENSOR_UUIDS_RELOAD_SEC`, default 300s).
- No silent file creation; missing file logs warning (cached data reused if available).
- Logs: path, count, malformed lines, duplicate conflicts.

Environment overrides:
```
SENSOR_UUIDS_FILE=/app/shared_data/sensor_uuids.txt
SENSOR_UUIDS_RELOAD_SEC=120
```

Usage inside actions: `self.load_sensor_mappings()` delegates to the unified loader.

---
## 📨 Verbosity & Message Gating

Frontend sends a metadata flag (Details ON/OFF). The helper `emit_message(dispatcher, tracker, text=..., detail=True)` only sends when details are enabled unless the text is auto-classified critical (contains tokens like `error`, `failed`, `timeout`). This reduces UI noise while retaining actionable failures.

Rules:
- Empty text + no attachments are suppressed to avoid blank bubbles.
- Critical keywords bypass gating.
- Attachments (artifacts) are detail-gated announcements.

---
## 🧾 Summarization Modes

| Mode | Trigger | Prompt Contents | Exclusions |
|------|---------|-----------------|------------|
| Ontology-only | No timeseries UUIDs | Instructions + Question + Standardized JSON + note about no timeseries | Raw SPARQL, compact result list removed |
| Analytics-enriched | Timeseries path (post analytics or SQL fallback) | Instructions + Original Question + Analytics/merged JSON | N/A (can be extended later) |

LLM: Local Ollama (`mistral:latest`). Options tuned for concise summaries (max_tokens ~150–180). Prompt preview length & total chars logged for observability.

---
## 🧪 Standard Analytics Payload Shapes

1. Nested (default for most analytics):
```jsonc
{
	"analysis_type": "analyze_temperatures",
	"1": {
		"Zone_Air_Temp_Sensor": {
			"timeseries_data": [ { "datetime": "2025-02-10 05:31:59", "reading_value": 21.4 }, ... ]
		}
	}
}
```
2. Flat (correlation):
```jsonc
{
	"analysis_type": "correlate_sensors",
	"Zone_Air_Temp_Sensor_5.01": [ { "datetime": "2025-02-10 05:31:59", "reading_value": 21.4 } ],
	"Zone_Air_Temp_Sensor_5.02": [ ... ]
}
```

---
## 🗄 MySQL (Building 1 Telemetry)

Env-driven config with optional local override:

| Variable | Purpose | Default (container) |
|----------|---------|---------------------|
| USE_LOCAL_MYSQL | Switch host vs service DNS | false |
| DB_HOST / DB_PORT | MySQL service location | mysqlserver / 3306 |
| DB_USER / DB_PASSWORD | Credentials | root / mysql |
| DB_NAME | Database name | sensordb |
| DB_TABLE | Table queried for timeseries | sensor_data |
| LOCAL_DB_* | Alternative host credentials | host.docker.internal / 3306 / root / root |

Dynamic SQL selects only requested UUID columns plus `Datetime`. Single UUID queries add an `IS NOT NULL` predicate for efficiency.

---
## 🔐 Environment Variables (Selected)

| Variable | Category | Effect |
|----------|----------|--------|
| NL2SPARQL_URL | Translation | Enables NL → SPARQL; absent = direct SPARQL skip |
| DECIDER_URL | Analytics decision | External decision service for perform_analytics/type |
| ANALYTICS_URL | Analytics execution | When set, microservice call performed; else local summarization over SQL only |
| BASE_URL | Artifact hosting | Used to build download URLs in chat responses |
| SENSOR_UUIDS_FILE | Sensor mapping | Explicit mapping file path override |
| SENSOR_UUIDS_RELOAD_SEC | Sensor mapping | Cache reload window seconds |
| ANALYTICS_REGISTRY_URL | Dynamic analytics types | Remote registry union with static fallback |

---
## 🧷 Artifacts & File Handling

Per-user folder: `shared_data/artifacts/<sanitized_sender_id>/`

Artifacts saved:
- SPARQL standardized JSON (`sparql_response_<timestamp>.json`)
- SQL raw results (`sql_results_<epoch>.json`)
- Analytics nested payload (`analytics_payload_<epoch>.json`)

Each saved file triggers a gated attachment message with a direct link (BASE_URL + path).

---
## 🛠 Adding a New Analytical Skill (Extended)

1. Implement microservice handler & expose in registry (or static fallback set).
2. Update analytics service image & rebuild.
3. Extend heuristic keywords if needed (both `_pick_type_from_context` variants) until refactored to a shared util.
4. (Optional) Add domain slot mappings/intents for explicit user selection.
5. Rebuild action server; verify `_supported_types()` log includes new type.

---
## 🩺 Debugging Checklist

| Symptom | Check |
|---------|-------|
| No analytics executed | Were UUIDs extracted? Logs: Timeseries detection. Decider suppression? Structural keywords? |
| Empty summary | Inspect LLM prompt preview log; ensure analytics JSON not empty; confirm `mistral:latest` pulled |
| Sensors not recognized | Verify sensor mapping file path via startup logs; ensure naming case matches Brick TTL |
| “Case normalization retry” logged | Original SPARQL returned zero results with mixed `_sensor_` casing; normalization path executed |
| Attachments missing | BASE_URL set? File save errors in logs? Verbosity toggle off (user hid Details)? |

---
## 🧪 Testing & Validation

Minimal smoke workflow after changes:
1. Ask “List CO2 sensors”. Expect ontology-only summary (no analytics).
2. Ask “CO2 trend today in Room 5”. Expect analytics path + timeseries extraction + summary.
3. Toggle Details OFF → intermediate progress messages suppressed; final summaries visible.
4. Rename a sensor in query with lower-case `_sensor_` → verify retry logs & results appear.

---
## 🔄 Future Refactors (Planned)
- Consolidate duplicated `_pick_type_from_context` into shared helper.
- Optional plugin registry for summarization strategies.
- Add caching/ETag for artifacts to reduce frontend fetch bandwidth.
- Add test harness for SPARQL→standardization transformations.

---
## 🧩 Directory Notes
- `actions.py` – Core orchestration & summarization.
- `requirements.txt` – Python deps for action server environment.
- (Artifacts) `/app/shared_data/artifacts` – runtime generated outputs.

---
## 📜 Legacy Notes
Prior versions created empty `sensor_uuids.txt` files when absent; this is removed to avoid masking deployment issues.

---
## ✅ Quick Reference
```
Slot path (timeseries)  : Question → SPARQL → UUIDs → analytics_type → SQL → analytics (opt) → summary
Slot path (ontology)    : Question → SPARQL → (no UUIDs) → summary (minimal prompt)
Verbosity gating        : emit_message(detail=True) hidden unless user enabled Details
Sensor mapping override : SENSOR_UUIDS_FILE=/app/sensor_uuids_custom.txt
```

---
## 📝 Changelog (local to actions)
- 2025-10-07: Unified sensor UUID loader; removed silent file creation; expanded README.
- 2025-10-05: Added minimal prompt mode for ontology-only summarization.
- 2025-10-04: Case normalization retry for `_sensor_` → `_Sensor_` in SPARQL queries.
- 2025-10-03: Verbosity toggle + gated progress messaging.
- 2025-10-02: Dynamic analytics registry with caching.
- 2025-10-01: Initial analytics summarization refactor with Ollama prompt logging.

---
## 📎 See Also
- Root project overview: `../../README.md`
- Analytics details: `../../analytics.md`
- Buildings taxonomy: `../../BUILDINGS.md`

---
## 🔄 Full Action Server Lifecycle

High-level event chain when a user sends a message through the REST/Socket channel:

1. Rasa Core receives the user message → intent + entities are parsed.
2. Policies predict `action_question_to_brickbot` (for analytical / ontology queries) OR forms if slot collection needed.
3. `ActionQuestionToBrickbot.run()` executes a staged pipeline (instrumented by `PipelineLogger`):
	1. extract_user_message
	2. nl2sparql_translate (optional) → obtains raw SPARQL
	3. fuseki_query → executes prefixed SPARQL
	4. format_results → human-readable short form for debug
	5. standardize → produce normalized JSON structure
	6. summarize_without_timeseries OR branch to date / analytics selection
4. If timeseries UUIDs found → slots set (`timeseries_ids`, `analytics_type`) → follow‑up triggers `action_process_timeseries`.
5. `ActionProcessTimeseries.run()` stages:
	1. collect_slots → read required IDs/dates
	2. normalize_dates → accept many user formats
	3. mysql_fetch → dynamic SELECT by UUID columns
	4. analytics_call (optional) → microservice POST
	5. uuid_replace → user friendly sensor names
	6. summarize_timeseries → LLM summary
6. Final messages + artifacts are emitted back to Rasa → returned to channel (frontend) as an ordered list of bot messages.

---
## 🧵 Sequence (Ontology + Analytics Branch)

```
User → Rasa → action_question_to_brickbot
  ├─ (Intent/slots) → Heuristic query type
  ├─ (Optional) NL2SPARQL → raw SPARQL
  ├─ Prefix augmentation → full SPARQL
  ├─ Fuseki → JSON bindings
  ├─ Standardize → uniform results list
  ├─ Extract UUIDs?
  │    ├─ No → Ontology-only summarize → reply
  │    └─ Yes → Decide analytics (Decider / heuristic)
  │          ├─ Perform? = false → Ontology + minimal timeseries mention → reply (or ask dates)
  │          └─ Perform? = true → Set slots → FollowupAction(action_process_timeseries)
  └─ (If Followup) → action_process_timeseries
			├─ Date normalization
			├─ MySQL fetch
			├─ Build canonical payload
			├─ (Optional) analytics microservice
			├─ UUID→Name replacement
			├─ LLM summarization
			└─ Reply + artifacts
```

---
## 📂 Data & Document Sharing Model

| Data Type | Origin | Persistence | Exposure Path |
|-----------|--------|-------------|---------------|
| SPARQL standardized JSON | Fuseki query result | `shared_data/artifacts/<user>/sparql_response_<ts>.json` | HTTP file server (BASE_URL/artifacts/...) |
| SQL raw results | MySQL dynamic SELECT | `sql_results_<epoch>.json` | HTTP file server (link gated under Details) |
| Analytics payload (nested/flat) | Aggregated SQL (and possibly analytics microservice request body) | `analytics_payload_<epoch>.json` | HTTP file server (debug) |
| Analytics response (optional) | Microservice POST /analytics/run | In-memory only (truncated logs); attach if needed later | (Future: writable artifact) |
| Summaries | LLM output | Ephemeral (log lines only) | Chat message text |
| Mapping file | Host bind / env path | Not copied; cached in-process | Not exposed (internal only) |

Artifacts are strictly immutable once written (timestamped). Frontend can download them directly or display inline (JSON viewer) if implemented.

---
## 🧱 Caching Layers

| Layer | Mechanism | Invalidation | Notes |
|-------|-----------|--------------|-------|
| Sensor UUID map | In-memory dict with mtime & age check | File mtime change OR > reload window | Avoids repeated disk IO |
| Analytics registry | Remote fetch + TTL (not shown here but referenced via `_supported_types()`) | Time-based | Fallback static set ensures resilience |
| SPARQL results | None (fresh each query) | N/A | Could add per-question cache if needed |
| SQL results | None | N/A | Rely on DB indexes + narrow SELECT |
| LLM prompt/summary | None | N/A | Deterministic caching possible for identical structured inputs |

Potential future optimization: add a digest cache keyed by (question, sensor_types, date_window) → reuse analytics results when identical.

---
## 🚨 Error & Resilience Strategy

| Failure Point | Handling | User Feedback | Escalation |
|---------------|----------|---------------|------------|
| NL2SPARQL timeout / error | Sets translation_error; may prompt for sensor or abort | Template: `utter_translation_error` | Log correlation ID for trace |
| SPARQL execution error | Abort early, set `sparql_error` slot | “Error executing SPARQL query” | Retry attempt only for case normalization scenario |
| Empty SPARQL + metric intent | Prompt for `sensor_type` form | “I need to know which sensor type...” | None |
| No UUIDs found | Summarize ontology-only | Summary of entities/relationships | Suggest specifying sensor if user wants metrics |
| Decider unavailable | Fallback heuristics | None (transparent) | Log warning only |
| Analytics microservice error | Log + fallback to SQL-only summary | “Analytics error: …” or generic error | Consider marking in summary prefix |
| MySQL fetch error | Returns explicit message | “MySQL error: …” | None (user can retry) |
| LLM (Ollama) failure | Returns no summary (safe) | “Unable to generate summary.” | Log stacktrace |
| Missing mapping file | Warning + use UUIDs raw | No direct user error; names appear as UUIDs | Encourage deployment fix via logs |

Critical words (error/failure/timeout) bypass verbosity gating to avoid hiding actionable diagnostics.

---
## 🧩 Extension Points

| Goal | Where to Hook | Minimal Steps |
|------|---------------|---------------|
| Add new analytics type | Microservice + analytics registry + heuristic keywords | Implement endpoint → add keyword(s) → rebuild actions & microservices |
| Add new summarization mode | `summarize_response` (both classes) | Branch on marker key (e.g., `_correlation_summary`) before prompt assembly |
| Add alternate DB backend | New fetch method in `ActionProcessTimeseries` | Choose by env var (e.g., `DB_BACKEND`) then branch (MySQL / Timescale / Postgres) |
| Add caching for analytics | Wrapper around analytics call storing by (analytics_type, sensor_set, date_window) | Compute key digest; skip call if fresh |
| Export artifacts elsewhere | Post-save hook after writing JSON | Stream to object storage (S3/minio) or message queue |
| Structured telemetry diffs | Pre-summarization transformation | Create derived stats (rate of change, peak windows) before prompt |

---
## 🧪 Local Development Tips

1. Run only the Action Server service with dependencies (Fuseki + MySQL + Analytics) to speed iterative cycles.
2. Use `docker compose logs -f action_server` while issuing REST requests via curl/PowerShell to observe stage timings.
3. Temporarily set `SENSOR_UUIDS_RELOAD_SEC=5` when refining mapping files.
4. Use a fixed question & slot injection in a test script to profile summarization latency.
5. Add `DETAILS=off` metadata in frontend → confirm gating hides progress noise.

---
## 🔍 Observability & Logging Conventions

| Prefix / Pattern | Meaning |
|------------------|---------|
| `[QuestionToBrickbot][<corr>] START stage 'nl2sparql'` | Stage timing envelope start |
| `Ollama summarize invocation` | Summarization request meta (chars, mode) |
| `Loaded X sensor mappings from ...` | Cache refresh success |
| `Case-normalized SPARQL retry` | Retried due to `_sensor_` case issues |
| `Standardized JSON sample:` | Truncated preview for debugging prompt inputs |

Correlate multi-stage logs via the correlation ID present in each stage line.

---
## 🧪 Example End-to-End (Concrete)

User: “Correlate humidity and temperature for last week in Lab 5”
1. Intent classified as metric (keywords: correlate, humidity, temperature)
2. NL2SPARQL returns query referencing candidate sensors (may be empty entity list initially)
3. SPARQL executes; returns bindings with two UUIDs
4. Timeseries IDs extracted → has_timeseries True
5. Decider (if present) returns perform_analytics true & maybe suggested type; heuristics would map correlate → `correlate_sensors`
6. Slots set; FollowupAction triggers `action_process_timeseries`
7. Date phrases “last week” normalized to previous ISO week bounds
8. MySQL query selects `Datetime`, UUID1, UUID2
9. Build flat correlation payload: `{ analysis_type: correlate_sensors, <Name1>: [...], <Name2>: [...] }`
10. (Optional) Analytics microservice returns correlation coefficient & any lag stats (future enhancement)
11. UUIDs replaced with friendly names
12. Summarization prompt built (analytics-enriched mode)
13. Summary returned: “Humidity and temperature in Lab 5 moved together (r≈0.78) with no significant anomalies …”
14. Artifacts (SQL + payload) available via file server links for audit.

---
## 🧹 Housekeeping / Maintenance Checklist

| Frequency | Task |
|-----------|------|
| Weekly | Rotate / prune stale artifact JSONs (script forthcoming) |
| Weekly | Validate sensor UUID mapping freshness (diff against registry) |
| Monthly | Refresh analytics registry & retire unused analysis types |
| Monthly | Re-run NL2SPARQL evaluation set for drift detection |
| Quarterly | Review summarization prompt tokens & adjust max_tokens if needed |

---
## 🧭 Design Trade-offs

| Decision | Trade-off | Future Option |
|----------|-----------|---------------|
| Local LLM (Ollama) | Faster, no network cost; model limited to what’s locally pulled | Remote hosted model for improved reasoning |
| On-demand analytics microservice | Flexible modular pipeline; network hop overhead | Inline light analytics for trivial stats |
| Gated verbose messages | Clean UI; may hide some contextual breadcrumbs | Add “show last pipeline” button |
| Per-user artifact folders | Isolation & audit; more files over time | Zip rotation / archival job |

---
## 🔐 Security Considerations

- No user-supplied SPARQL is executed directly; queries pass through translator or curated patterns.
- File server serves static JSON only; no execution risk (enforce correct MIME types).
- Avoid leaking raw SPARQL in ontology-only summarization to reduce accidental prompt injection surface.
- Mapping file path controlled via env to prevent directory traversal injection.

---
<!-- End of actions README -->
