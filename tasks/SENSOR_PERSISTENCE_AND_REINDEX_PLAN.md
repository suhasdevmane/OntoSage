# Plan — Persist GUI-registered sensors to `input/` + correct RAG reindex

**Status:** proposed (awaiting approval — no commits per CLAUDE.md)
**Date:** 2026-07-16
**Branch:** `security/p0-hardening`

---

## 0. Problem & corrected model

The DatabasesTab **"Register Sensors"** button (`/api/v1/admin/databases/{key}/sensors[/csv|/ttl]`)
routes through `db_ontology.register_points` / `register_ttl`, which PUT generated Brick TTL
**straight into a GraphDB named graph** (`urn:ontosage:db:<key>`). It never writes a file, so:

- a GraphDB volume reset / `docker-compose down -v` loses the sensors, and
- `ttl_uploader` has no `input/` file to reload them from on restart.

This is the **only** GUI write path that bypasses the source-of-truth layer. The OntologyTab
upload (`persist_ttl_file`) and Capabilities tab (`upsert_amenity`) already persist to `input/`.

**Corrected reindex model (critical):** two separate indexes exist.
- `ReindexService` (`/api/v1/admin/reindex`, targets `capability`/`documents`/`floor_plans`) →
  **Qdrant only. Zero effect on sensor retrieval.**
- **GraphDB Similarity Index** `bldg_index` (`GRAPHDB_SIMILARITY_INDEX`) → the index the sensor
  RAG retriever (`graphdb_retriever.retrieve_entities`) queries. Rebuilt **only** by manually
  running `rag-service/graphdbRAG/create_graphdb_index.py`. **Nothing rebuilds it on restart or
  after registration today.**

So "auto-enqueue a reindex" MUST mean a **GraphDB similarity-index rebuild**, not the
`ReindexService`. New sensors are already answerable live via (a) the LLM→SPARQL path for
type-level queries and (b) the retriever's identifier-search fallback; the rebuild restores
**semantic/fuzzy** entity retrieval.

---

## Decisions locked (from user)

1. **Merge/append** — re-registering adds new triples, never deletes old ones
   (`persist_ttl_file(merge=True)`, rdflib union). Caveat accepted: re-registering the same
   `local` id with a *changed* class/uuid leaves both old and new triples about that subject.
2. **Auto-enqueue a reindex after registration + reindex on restart** — the *similarity index*
   rebuild. Admin sees "triples added — reindexing; when done, ask your new questions."
3. **One-shot backfill script** to dump existing `urn:ontosage:db:*` graphs to
   `input/db_<key>_sensors.ttl` so nothing is lost in any scenario.

---

## Workstream A — Durable persistence (the core fix)

**File:** `orchestrator/services/db_ontology.py`

- `register_points`: build TTL (already via `build_points_ttl`), then persist through the
  source-of-truth layer instead of `_put_named_graph`:
  ```python
  from orchestrator.services.input_ttl_store import persist_ttl_file
  filename = sensors_filename(db_key)          # e.g. "db_<sanitized_key>_sensors.ttl"
  res = await persist_ttl_file(filename, ttl, merge=True, client=client)
  ```
  This writes `input/<filename>` atomically (locked, backed up to `.trash/`), PUT-syncs its file
  graph `urn:ontosage:ttl:<filename>`, and refreshes the SHA cache so restart treats it as
  already-loaded.
- `register_ttl`: same, but merge the admin-supplied TTL.
- Add `sensors_filename(db_key)` — sanitize `db_key` (alnum/`_`/`-`), ensure it does **not** hit
  `_looks_like_schema` tokens (`brick`/`rec`/`s223`/`schema`); if it would, prefix to neutralize
  (e.g. `db_<key>_points.ttl`). File must match the flat-layout discovery (`input/*.ttl`,
  non-schema) so `ttl_uploader` reloads it on restart — **no other wiring needed**.
- Keep `_put_named_graph` for now (used by nothing else after this change) or delete if unused.

**Restart behavior after A:** `ttl_uploader.run_idempotent_uploads` (orchestrator lifespan,
`main.py:822`) discovers `input/db_<key>_sensors.ttl` and loads it into
`urn:ontosage:ttl:db_<key>_sensors.ttl` — the same graph `persist_ttl_file` synced live. No drift.

---

## Workstream B — Fix the sensor-count readouts + connection removal

The DatabasesTab "Sensors in GraphDB" column reads `urn:ontosage:db:<key>`; sensors now live in
the file graph. Update:

- `db_ontology.graph_triple_count(db_key)` → count `urn:ontosage:ttl:<sensors_filename(key)>`.
- `db_ontology.graph_triple_counts()` → group over `urn:ontosage:ttl:db_*_sensors` (adjust the
  `STRSTARTS` filter / mapping back to `db_key`).
- `clear_graph(db_key)` (called when a connection is removed) → must now **trash the file** and
  drop its file graph. Delegate to `input_ttl_store.trash_ttl_file(sensors_filename(key))`
  instead of only deleting `urn:ontosage:db:<key>`, otherwise the file reloads the sensors on the
  next restart (the exact bug the delete path in `input_ttl_store` was built to prevent).

---

## Workstream C — The real reindex: GraphDB similarity-index rebuild

**New helper — `orchestrator/services/ontology_manager.py`:**
```python
async def rebuild_similarity_index(client=None) -> Dict[str, Any]:
    """POST /rest/similarity/indexes/<GRAPHDB_SIMILARITY_INDEX>/rebuild (auth-aware).
    On 404 (index missing) optionally create it from create_graphdb_index config.
    Non-fatal; returns {ok, index, status, error}."""
```
- Use `settings.GRAPHDB_USER/PASSWORD` (the create script used none — must be auth-aware).
- Respect `GRAPHDB_USE_SIMILARITY`; if False, no-op with a clear status.

**Wire into `ReindexService` so it reuses the existing job/polling UX** —
`reindex_service.py::_run_target`, add:
```python
if target == "ontology_similarity":
    return await ontology_manager.rebuild_similarity_index()
```

**Auto-enqueue after registration** — in `main.py` register endpoints, on success:
```python
job_id = _get_reindex_service().start(["ontology_similarity"], building_id=...)
# return job_id in the APIResponse data so the GUI can poll /api/v1/admin/reindex/{job_id}
```

**Restart-time rebuild** — in the orchestrator lifespan, right after the `ttl_uploader` block
(`main.py:~835`), enqueue `start(["ontology_similarity"])` as a background job (non-blocking,
non-fatal). This is the restart-time reindex the admin expects — it does not exist today.

> Note: GraphDB rebuild is async (202 + background build). "Done" = poll GraphDB similarity
> status (`GET /rest/similarity/indexes`) until the index reports ready. v1 may report "rebuild
> initiated" and treat job `done` on 202; a follow-up can add true completion polling if the
> "ask now" UX needs a hard ready signal.

---

## Workstream D — One-shot backfill (no triple lost)

**New script — `scripts/backfill_db_sensor_ttls.py`:**
1. `list_named_graphs()` → find every `urn:ontosage:db:<key>`.
2. For each, `CONSTRUCT { ?s ?p ?o } WHERE { GRAPH <graph> { ?s ?p ?o } }` → serialize Turtle.
3. Write to `input/db_<key>_sensors.ttl` via `persist_ttl_file(merge=True)` (dedup-safe).
4. `--drop-old` flag (default off): after successful file write, `drop_named_graph` the old
   `urn:ontosage:db:*` so counts don't double.
5. `--dry-run` prints what it would write.

Run once against the live stack; after that the GUI path keeps everything in `input/`.

---

## Workstream E — Frontend UX (`frontend/src/components/admin/DatabasesTab.js`)

- After a successful register, read `job_id` from the response, poll
  `GET /api/v1/admin/reindex/{job_id}`, and show:
  - while running: *"Added N sensors and saved to input/. Rebuilding the similarity index —
    please wait…"*
  - on done: *"Reindex complete. Your new sensors are now part of OntoSage — ask your questions."*
- Make explicit in copy that persistence (input/ + GraphDB) is immediate and survives restart;
  only the semantic-search rebuild is what the wait is for.

---

## Testing

- **Unit** (`tests/`, offline, mock httpx):
  - `db_ontology.register_points` calls `persist_ttl_file(merge=True)` and returns the file path.
  - `sensors_filename` sanitization never yields a schema-looking name.
  - `clear_graph` trashes the file + drops the file graph.
  - `ontology_manager.rebuild_similarity_index` builds the correct URL + auth; handles 202/404/off.
  - `ReindexService` `ontology_similarity` target dispatch.
- **Integration / live** (stack up):
  - Register a sensor via CSV → assert `input/db_<key>_sensors.ttl` exists + triples in file graph.
  - Register a *second* sensor → assert both present (merge, not replace).
  - `docker-compose restart orchestrator` → sensors still in GraphDB (reloaded from file).
  - Trigger rebuild → semantic query for the new sensor surfaces it in `/graphdb/retrieve`.
- Full `pytest -m unit -q` stays green (423/2-skip baseline).

---

## Rollout order

A → B → D (backfill existing) → C → E. A+B+D make persistence correct and lossless first;
C+E add the honest reindex + UX on top.

## Risks / call-outs

- **Merge accumulates contradictory triples** on re-register with changed class/uuid (accepted per
  decision 1). If this bites, add an opt-in per-subject upsert mode later.
- **Similarity rebuild cost/time** — full-index rebuild on every single-sensor add may be heavy at
  scale. Mitigation option: debounce (coalesce rapid registrations into one rebuild) — note only.
- **Two GraphDB load paths** already coexist (`import_ontology` → default graph; `ttl_uploader` →
  named graphs). Pre-existing, harmless for union SPARQL; out of scope here.

## Addendum (post-live-test) — debounce + admin visibility

Live testing surfaced two things beyond the original plan:

1. **REST similarity API is HTTP 405 here** → rebuild uses the SPARQL `similarity:rebuildIndex`
   trigger (verified 204), and status is read via `<index> similarity:status ?s`
   (`REBUILDING`/`BUILT`). `ontology_manager.get_similarity_index_status()`.
2. **Rebuild-per-register is expensive** (full-graph Lucene rebuild = minutes) and, worse, a naive
   trigger while a rebuild is in flight is dropped ("already running") → the just-added triples
   could miss the current rebuild.

Fix: **`services/similarity_reindex.py::SimilarityRebuildDebouncer`** — one process-wide singleton
(`get_similarity_debouncer()`), the single similarity-rebuild gateway:
- **Collapses a burst** of requests into ONE eventual rebuild (trailing debounce, `delay≈3s`).
- **Re-runs once** if triples arrive WHILE a rebuild is in progress (dirty-during-run).
- **Polls GraphDB's real status** until `BUILT`, so "ready" is honest, not guessed.
- All paths funnel through it: sensor registration + manual TTL upload (`_enqueue_similarity_rebuild`),
  startup, and the admin reindex endpoint's `ontology_similarity` target.

Admin visibility (the "when can I ask OntoSage" signal):
- **`GET /api/v1/admin/reindex/similarity-status`** → `{state: idle|pending|rebuilding, ready,
  graphdb_status, completed_count, …}`.
- **DatabasesTab**: a persistent "Semantic search index" banner (rebuilding vs up-to-date), a
  **Rebuild now** button, and post-register polling that tells the admin exactly when their new
  sensors are searchable. Exact name/type questions work immediately (live SPARQL); only semantic
  search waits for the rebuild.

## FIX_TRACKER

FEAT-041 (VERIFIED_LIVE) covers the whole feature incl. the debounce + admin visibility;
CAVEAT-042 (FIXED) covers the reindex-gateway / doc_indexer fix.
