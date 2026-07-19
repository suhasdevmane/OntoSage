# Improvement Plan — TTL-native knowledge, gate fix, floor routing, health & LLM

Status: PROPOSED (2026-07-15). Nothing here is built yet. Sequenced; WS-1 unblocks WS-2/3/4.
Grounded in a live pre-push verification battery (see FIX_TRACKER; battery in scratchpad).

## Why (evidence from the battery)
- "How do I make a complaint?" → *"enable the Student Complaint System"* (wrong).
- "The toilet on floor 2 is leaking" → *"enable the Water Metering System"* (wrong).
- "How many rooms on floor 3?" → floor-plan dump, not a count.
- `/health` shows `ontology_valid:false` even though 15.4M triples + 6,850 namespace
  entities are loaded (stale startup flag).
- Every LLM question failed because Ollama was down (env, not code).

## Design decisions (pressure-tested — read before building)

1. **The complaint/leak wrong answers are a ROUTING bug first, a data gap second.**
   `_route_from_dialogue` runs `_check_locked_capability` **first** ([_orchestrator.py:3213]),
   before any intent handling, so it intercepts *any* query containing a disabled-datasource
   keyword ("complaint", "leak"/water) — including informational/policy/report questions.
   **New triples do nothing until this gate stops intercepting them.** WS-1 is the unblocker.

2. **Extend the proven Amenity pattern — do NOT invent free-form `subject predicate object`
   triples.** Your examples ("complaint→how-to→url", "leakage→is-a→maintenance issue→report-to→url")
   mix TBox (class membership) and ABox (instance facts). Free-form triples are neither reliably
   SPARQL-answerable nor GUI-authorable with dropdowns. Instead: a small **constrained vocabulary**
   (a few classes + a few properties) with per-building **instances** — exactly what makes
   `ontosage:Amenity` work today (lift/prayer room answered live). This keeps it SPARQL-first,
   building-agnostic, and dropdown-authorable.

3. **Source the facts from what already exists — don't fabricate.** The informational content is
   already written in `input/documents/cap_*.md` (complaints, lost property, wifi, GDPR, reception
   hours, transport, …) with real Cardiff/Estates contacts (`estates@cardiff.ac.uk`, ext 76026).
   Migrate the **structured** bits (topic, lay-terms, contact, URL, report-to, category, one-line
   answer) into triples; keep the prose in the docs for depth. No invented URLs/contacts —
   honesty contract. (Same migration pattern as ROADMAP-009.)

4. **Curated, not "huge."** A focused set (~20–40 topic instances covering the common
   informational/procedural/maintenance questions in the survey corpus) beats a giant list nobody
   maintains. Model what people actually ask (drive from `paper/Survey analysis and results/`).

5. **Maintenance statements still go to report_intake.** "The toilet is leaking" is a *report*
   (log a ticket), not just an info lookup. After WS-1, it routes to `report_intake`; the new
   `MaintenanceIssue` triples **enrich** the acknowledgement ("logged — for urgent leaks contact
   Estates …"). Questions ("is the lift broken?") stay informational. Preserve the existing
   statement-vs-question precedence.

6. **Floors/rooms ARE in the graph** (verified live: `brick:Floor`=8, `brick:Room`=233, 637
   `brick:hasPart`). So floor/room counts are pure SPARQL — no dependence on DWG manifests.

---

## Workstreams

### WS-1 — Make the locked-capability gate intent-aware (UNBLOCKER) · P0
**File:** `orchestrator/workflow/_orchestrator.py` (`_check_locked_capability`, ~3101; caller ~3213).
- Only intercept when the query genuinely needs the **live datasource** — i.e. a data/metric/
  analytics/trend/anomaly intent (or an explicit "show me the <X> data" phrasing). Let
  informational / capability / report_intake / general intents pass through to normal routing.
- Concretely: gate fires only if `intent ∈ {sensor_data, analytics, trend, anomaly, compare,
  comparison, visualization, forecast}` **and** the query maps to a disabled source; otherwise
  return `None`. Keep it flag-gated + conservative.
- **Tests:** "how do I make a complaint" / "what are the occupancy limits" → NOT locked;
  "show me occupancy data" / "occupancy trend this week" (source off) → locked. Add to the
  routing tests. Closes CAVEAT-017.

### WS-2 — Knowledge-topic vocabulary (TBox) + curated instances (ABox) · P1
**Files:** `ontology/ontosage_capabilities.ttl` (vocab), new `input/bldg1_knowledge.ttl` (instances).
- **TBox — add to the vocab** (siblings of `Amenity` under a shared top):
  - `ontosage:KnowledgeTopic` (class) with subclasses `ontosage:InformationTopic`,
    `ontosage:Procedure`, `ontosage:MaintenanceIssue`.
  - Properties: reuse `ontosage:layTerms`, `ontosage:capabilityCategory`, `ontosage:note`; add
    `ontosage:answerText` (one-line canonical answer), `ontosage:infoUrl`, `ontosage:contactEmail`,
    `ontosage:contactPhone`, `ontosage:reportTo`, `ontosage:steps` (numbered how-to),
    `ontosage:relatedTopic` (link to another topic/amenity).
- **ABox — curated instances** dual-typed (`a ontosage:Procedure, ontosage:KnowledgeTopic`) so a
  `?t a ontosage:KnowledgeTopic` query resolves without inference, mirroring the Amenity pattern.
  Seed from `input/documents/cap_*.md`: complaints, lost property, wifi/IT, GDPR/data privacy,
  reception & hours, transport/parking, printing/scanning, accessibility, emergency contacts,
  smoking policy, visitor policy, room booking, + maintenance issues (leak, broken light, broken
  lift, heating/cold, no hot water, blocked toilet, broken door/access).
- Loaded at startup by `ttl_uploader` (already loads every `input/*.ttl`). SHA-idempotent.

### WS-3 — Resolve knowledge topics from triples · P1  (depends on WS-2)
**File:** `orchestrator/services/capability_graph_resolver.py`.
- Broaden the fetch from `?a a ontosage:Amenity` to also include `?t a ontosage:KnowledgeTopic`
  (single UNION query), carrying the new fields.
- Render per type: Amenity → location/spec (today); InformationTopic/Procedure → `answerText` +
  URL/contact + numbered `steps`; MaintenanceIssue → `answerText` + `reportTo`/contact.
- Keep the conservative lay-term scoring (multi-word/distinctive match only) so it defers to the
  KB/documents when unsure. Provenance tag: `capability_graph`.

### WS-4 — Routing so these questions reach the graph · P1  (depends on WS-1, WS-3)
**Files:** `orchestrator/agents/dialogue_agent.py`, `orchestrator/agents/capability_agent.py`.
- The TTL-first router (flag `CAPABILITIES_TTL_FIRST`, already on) already routes to `capability`
  when the graph resolver matches — extending the resolver (WS-3) makes complaint/lost-property/etc.
  match automatically. Verify statements still beat the KB router into `report_intake`.
- In `report_intake`, look up a matching `MaintenanceIssue` topic and append its `reportTo`/contact
  to the ticket acknowledgement (grounded enrichment, no fabrication).

### WS-5 — GUI: dropdown-authored knowledge triples · P2  (depends on WS-2)
**Files:** `orchestrator/services/capability_admin.py`, `orchestrator/main.py` (`CapabilityCreate`),
`config-panel/html/{index.html,app.js}`.
- Extend the guided authoring beyond amenities:
  - **"Kind" dropdown**: Amenity / Information / Procedure / Maintenance issue → sets the class.
  - **"Type" dropdown**: filtered by Kind (amenity subclasses, or the knowledge subclasses).
  - Conditional fields per Kind: answerText, infoUrl, contactEmail, contactPhone, reportTo,
    steps (repeatable rows), relatedTopic — added to `build_amenity_ttl` (rename → `build_topic_ttl`)
    and the `CapabilityCreate` model.
- Keep the whitelist-constrained approach (no free-predicate paste) so every field maps to a known
  property. Writes go through `input_ttl_store` (now atomic + locked) into `input/bldg1_knowledge.ttl`.
- List/delete already generic (`?a a ontosage:Amenity` → broaden to `KnowledgeTopic` too).

### WS-6 — Floor/room counts via SPARQL (fix floor-N routing) · P2
**Files:** `orchestrator/services/building_metrics.py` (or a small `spatial_metrics` helper),
`orchestrator/workflow/_orchestrator.py` routing, `agents/spatial_agent.py`.
- Add SPARQL-backed counters (graph verified to support them): total floors
  (`COUNT(DISTINCT ?f WHERE ?f a brick:Floor)`), rooms per floor (via `brick:hasPart`/floor id),
  total rooms.
- Route floor/room **count** questions ("how many rooms on floor 3", "how many floors",
  "how many rooms in total") to a spatial COUNT that returns a **number + short list**, not the
  floor-plan PDF dump. "show me floor N" / "where is room X" stays floor_plan.
- Add a `is_spatial_count_question()` detector (floor/room + count phrasing) as a routing override,
  mirroring the existing `is_inventory_count_question` override (#0).
- **Tests:** the four phrasings above return counts; "show me floor 3" still returns the plan.

### WS-7 — `ontology_valid` lazy re-validation · P2
**Files:** `orchestrator/services/ontology_validator.py`, `orchestrator/main.py` (health).
- Re-validate on demand: if `last_result` is not ok (or older than N seconds), re-run `validate()`
  when `/health` is hit (bounded, cached ~30s) so a cold-start where GraphDB lagged the orchestrator
  self-heals instead of showing a permanent false. Optionally also re-validate after the startup
  `ttl_uploader` completes. Keep it non-blocking.
- **Test:** simulate first-call failure then success → health flips to valid.

### WS-8 — Bring the LLM up with the stack · P2
**Files:** `docker-compose.yml`, `.env.example`, `README`.
- The battery failed only because host Ollama was down. Options (pick one):
  - **(a) Startup preflight + warmup:** orchestrator lifespan pings `OLLAMA_BASE_URL` and issues a
    tiny warmup generate for `OLLAMA_MODEL`; logs a clear, actionable error if unreachable (so
    `docker-compose up` fails loudly, not silently degrading). Lowest blast radius.
  - **(b) Optional `ollama` compose service** (profile-gated) that runs the model in a container so
    `docker-compose up` is truly self-contained — at the cost of image size / GPU passthrough config.
- Recommend (a) now (fast, honors "native host Ollama"), (b) as a later opt-in profile. Either way,
  document the one-liner (`ollama serve` + `ollama pull gemma4:26b`).

### WS-9 — Measurement (no-regression) · P2
- A focused QA set (~25 Q) over the new informational/procedural/maintenance + floor-count
  questions, plus the existing amenity/sensor/metrics set, run before → after each WS. Reuse
  `scripts/ontosage_qa_suite.py` / the battery. Requires Ollama up.

---

## Sequence & dependencies
1. **WS-1** (gate) — unblocks the wrong answers immediately, independent of new data.
2. **WS-2 → WS-3 → WS-4** (vocab → resolver → routing/enrichment) — the TTL-native knowledge core.
3. **WS-5** (GUI) after WS-2 (needs the vocab).
4. **WS-6, WS-7, WS-8** — independent, can run in parallel.
5. **WS-9** — gates the push (needs Ollama up).

## Contract check (every WS must honor)
TTL-first (facts as triples, not YAML/code) · building-agnostic (vocab has zero building literals;
instances live per-building) · honest grounding (facts sourced from existing docs, no fabricated
URLs/contacts) · admin-gated GUI (`system:admin`) · one active building.

## Explicitly out of scope / deferred
- Free-predicate / arbitrary-relation authoring (keep the constrained vocab).
- Reasoner-dependent inference (dual-type instances so plain SPARQL resolves them).
- Multi-building knowledge overlays (nested-layout, later).
