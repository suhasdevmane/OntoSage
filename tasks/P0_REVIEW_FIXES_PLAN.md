# P0-Hardening Review — Fix Plan

Source: read-only review of the uncommitted `security/p0-hardening` surface (2026-07-14).
Scope: the file-as-source-of-truth persistence layer (FEAT-018/TODO-014), the config-panel
Ontology tab, and hardening hygiene. **Nothing here is committed** — user reviews first
(CLAUDE.md Notes). Update `tasks/FIX_TRACKER.csv` per Workflow rule 7 as each item lands.

Confirmed-green baseline before starting: `pytest -m unit` (475 pass / 2 skip), `flake8
--select=F821,F823` clean, admin endpoints 401 unauthenticated, SPARQL browser rejects
mutations. Do not regress these.

---

## Work order (by value, grouped to minimize file churn)

### Group A — persistence layer (input_ttl_store.py + ontology_manager.py) — do first
Single highest-value cluster; all in two files with one test file.

#### A1 (P1) — Delete honesty + durability
- **Files:** `orchestrator/services/ontology_manager.py` (`delete_subject`),
  `orchestrator/services/input_ttl_store.py` (`remove_amenity`).
- **Change:**
  1. `delete_subject`: switch the update to GRAPH-scoped so it deterministically removes a
     subject wherever it lives — `DELETE WHERE { GRAPH ?g { <s> ?p ?o } }` (all amenity
     triples are confirmed to sit in named graph `urn:ontosage:ttl:bldg1_capabilities.ttl`,
     not the default graph, so the current no-GRAPH form may be a no-op). Keep the existing
     `<`/`>`/whitespace injection guard.
  2. `remove_amenity`: when the subject is **not** in the GUI-owned capabilities file, do not
     report `ok:true`. Either (a) resolve and edit the owning `input/*.ttl` file, or (b)
     return `ok:false` with a clear message ("defined in <file>; edit the TTL to remove"),
     because a graph-only delete reloads on the next `ttl_uploader` run. Never return success
     for a delete that reverts on restart.
- **Tests (`tests/test_input_ttl_store.py`):** amenity-in-file delete persists (existing);
  amenity-not-in-file delete returns honest failure (new); `delete_subject` emits a
  GRAPH-scoped update string (new, mock client).
- **Live verify:** create a throwaway `ontosage:Amenity` in a *second* TTL, delete via the
  API, confirm it's gone from GraphDB **and** stays gone after `docker compose restart
  orchestrator` (or an honest failure is returned).

#### A2 (P2) — Atomic writes
- **File:** `input_ttl_store.py` (`_write_capabilities`, `persist_ttl_file`).
- **Change:** write to `path.with_suffix(path.suffix + ".tmp")` then `os.replace(tmp, path)`
  (atomic on POSIX + NTFS). Prevents a truncate-in-place crash from blanking the file, which
  `ttl_uploader` would then PUT-replace into an empty named graph (all amenities vanish).
- **Test:** monkeypatch to raise mid-serialize → original file intact (no partial write).

#### A3 (P2) — Cross-process write lock
- **File:** `input_ttl_store.py` (`upsert_amenity`, `remove_amenity`, `persist_ttl_file`).
- **Change:** wrap each read-modify-write in a `filelock.FileLock(input/.ttl_write.lock)`
  (add `filelock` to requirements). Safe today on one uvicorn worker, but the new rate
  limiter explicitly targets multi-replica; without a lock two writers last-writer-wins and
  silently drop data while both return success.
- **Test:** two interleaved `upsert_amenity` calls both survive in the final file.

### Group B — config-panel front-end (app.js + style.css)

#### B1 (P2) — esc() attribute safety
- **File:** `config-panel/html/app.js` (`esc`, line 239).
- **Change:** add `.replace(/"/g,"&quot;").replace(/'/g,"&#39;")`, or set `data-del-cap` /
  `data-drop-graph` via `el.dataset` instead of string HTML. Latent admin XSS; low
  exploitability (values are IRIs/validated ids) but `esc()` is trusted in attribute context
  it doesn't cover.
- **Verify:** `node --check config-panel/html/app.js`; manual drop/delete still works.

#### B2 (P2) — Light theme — **DECIDED: build full light theme + toggle**
- The production console is dark-only (single `:root`, no `prefers-color-scheme`/toggle);
  the "both light and dark themes" ask is currently unmet.
- **Change:** move the ~12 hardcoded `#0b1120`/`#2a2008`/`#ffd591`/etc. into `:root` tokens,
  add `@media (prefers-color-scheme: light)` + `:root[data-theme=light]` overrides, and a
  header toggle persisted to `localStorage` (default = follow OS). Ensure the new Ontology
  tab elements (`.onto-lbl input`, `.onto-table`, SPARQL result) read correctly in both.
- **Verify:** Playwright screenshots in light + dark; check contrast on inputs, cards,
  pills, and the SPARQL result table.

### Group C — hygiene (independent, low-risk)

- **C1 (P3):** `black --line-length 100 orchestrator/services/ontology_manager.py` (fails
  `black --check` today).
- **C2 (P3):** atomic Redis rate-limit window in `main.py` `_allow_redis` — Lua `INCR`+
  `EXPIRE` or `SET key 1 EX w NX` then `INCR`, so a crash between INCR==1 and EXPIRE can't
  leave an IP permanently 429'd.
- **C3 (P3):** remove `frontend/src/components/admin/CapabilitiesTab.js` + its `AdminPortal.js`
  wiring (orphaned React duplicate of the served config-panel tab), or add
  `frontend/README` marking the app non-production.
- **C4 (P3):** in `ttl_uploader.discover_ttls`, add a guard/comment so a stray
  `bldg2_*.ttl` in a flat `input/` isn't cross-loaded into the single repo (keep the
  documented single-building invariant explicit).

---

## Final verification gate (run before declaring done)
```
pytest -m unit -q                                  # expect no new failures vs 475/2-skip
flake8 orchestrator/ shared/ --select=F821,F823    # blocking, must stay clean
black --check --line-length 100 orchestrator/ shared/ tests/
node --check config-panel/html/app.js
curl http://127.0.0.1:8000/health                  # stack healthy
```
Plus the A1 live durability check and (if B2 Option 1) Playwright light/dark screenshots.
Then add FIX-021…FIX-0NN rows to `tasks/FIX_TRACKER.csv` and flip A-group rows to
`FIXED`/`VERIFIED_LIVE` with evidence. **Do not commit** until the user approves.

## Deferred (not in this pass)
- Redundant capability I/O per query (graph resolve + doc search in both router and node) —
  perf only, cached, negligible vs the 40s LLM.
- `download_export` role check — confirm export-capable non-admin roles carry `export:read`
  (verify, likely no change).
