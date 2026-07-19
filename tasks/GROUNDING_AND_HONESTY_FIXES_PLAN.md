# Grounding & Honesty Fixes — Plan

**Owner:** OntoSage · **Created:** 2026-07-10 · **Tracker:** [`FIX_TRACKER.csv`](./FIX_TRACKER.csv)

Guiding principle (user preference, and the repo's own TTL-first rule): **every number in an
answer must be computed live from the ontology / floor plans — never a hardcoded literal that
can drift.** A fact that can be a triple lives in the graph, not in `capability.yaml`.

This plan tracks the fixes that enforce that principle. Statuses mirror `FIX_TRACKER.csv`;
update both when anything changes.

---

## Done & verified live (2026-07-10, post `docker-compose build orchestrator`)

- **FIX-001 — Nonexistent-zone fabrication (P0).** `ReferentResolver` gate in `_sparql_node`
  validates a named zone against the live ontology and returns an honest clarification with real
  nearby zones. Verified live: *"Zone 99.99"* → clarification (5.29/5.19/5.09…); *"Zone 5.28"* →
  normal answer (no regression).
- **FIX-002 — Hardcoded count/area in `capability.yaml` (P1).** `BuildingMetrics` computes counts
  (live SPARQL `COUNT`) and area (DWG manifests); `capability.yaml` de-hardcoded. Verified: 0
  frozen numbers in the container; live SPARQL returns 1,332 points / 1,314 sensors / 302 zones.
  **Caveat:** only covers count questions that route to the *capability* agent — see FIX-003.
- **FIX-003 — Count/inventory questions mis-route (P1).** ✅ DONE (2026-07-11). Deterministic routing
  override sends building-wide count/size questions to the capability node's live grounding. Verified
  live: *"How many sensors are there in the building?"* → 1,332 points / 1,314 sensors / 302 zones /
  20,370 m² (was "1 sensor"). Design retained below for reference.

---

## FIX-003 — Count/inventory questions mis-route (P1) — ✅ DONE (design retained)

### Symptom (found live)
> "How many sensors are there in the building?" → routed to the **sensor_data** pipeline →
> *"There is 1 sensor identified in the building."* (Truth: ~1,332 points / 1,314 sensors.)

Count/inventory questions currently scatter across three routes with three different results:
`sensor_data` (fetches one reading → wrong count), `discovery` (does a live `COUNT` → correct),
`capability` (was frozen `~680`, now de-hardcoded). No single authoritative path.

### Best solution for this scenario — one deterministic live-count path
A count question should **always** be answered by one handler backed by `BuildingMetrics`
(live SPARQL `COUNT`), regardless of phrasing or how the LLM classified it. This is the single
source of truth and matches the "always check the triples" preference.

Recommended implementation (mirrors the repo's existing override + node pattern; low risk):

1. **Detector** — promote/broaden the `_METRICS_RE` inventory-count pattern (already in
   `capability_agent.py`) into a shared helper, e.g. `building_metrics.is_inventory_count_question(q)`.
   Match: "how many {sensors|points|zones|rooms|floors|devices|cameras}", "sensor/point count",
   "number of …", "total number of …", "how big/large is the building", "total floor area".
2. **Node** — add `_building_metrics_node(self, state)` on `WorkflowOrchestrator` that calls
   `get_building_metrics().snapshot(building_id)` and returns `render_metrics_block(...)`.
3. **Routing override** — in `_route_from_dialogue`, add a high-precedence override: if the query
   is an inventory-count question, route to `building_metrics` **before** the registry route can
   send it to `sparql`/`sensor_data`. (Overrides are the established mechanism for exactly this
   class of LLM misclassification — see the floor_plan/compare overrides.)
4. **Keep** the capability-agent grounding (FIX-002) as a safety net for count questions that still
   land there.

Interaction with FIX-001: count questions name no specific zone, so the referent gate no-ops — no
conflict.

### Tests
- `tests/test_routing_accuracy.py` — add canonical cases: "how many sensors are there" →
  `building_metrics` node; "how big is the building" → `building_metrics`.
- Node unit test: snapshot mocked → response contains the live figures, provenance `live_metrics`.
- Live check after deploy: the three phrasings above all return the same live count.

### Effort
Small–medium. One new node method + one override + one shared helper + tests. No schema changes.

---

## Enhancements (lower priority)

- **CAVEAT-007 — declared vs live-streaming count (P2).** Extend `BuildingMetrics.snapshot()` with
  `sensors_with_live_data` (reuse `scripts/data_coverage_audit.py` logic: distinct UUIDs with rows
  per `ref:storedAt` backend). Render both: *"1,314 sensors declared; N streaming live (Floor 5)."*
  This makes the count honest about coverage without a separate question.
- **CAVEAT-005 — referent-gate precision (P3).** Optional ontology-backed allowlist of valid zone
  ids so a *bare* dotted id ("temp in 5.99", no "zone" word) can be validated without false-positives
  on threshold values.
- **CAVEAT-006 — sensor-type breakdown double-counts (P3).** De-dupe by most-specific declared class.

---

## ROADMAP-009 — Migrate structured capability facts to ontology triples (P3)

**Question raised:** should `capability.yaml` move to graphRAG triples? **Answer: partially — it's a
spectrum, not a binary.** The frozen-number bugs (FIX-002) came from storing *facts* as prose. The
end-state that removes that class of bug at the source:

| Capability content | Target home | Why |
|---|---|---|
| **Structured facts** — lift/prayer-room/café locations, CCTV count, accessibility, equipment, spaces | **Ontology triples** ✅ | Relational + countable → SPARQL-queryable, joinable, consistent with live counts. True TTL-first. |
| **Long-form prose** — fire procedures, power-outage narrative, governance | **Document KB** (Qdrant `documents_<bldg>`, already exists) | Forcing prose into triples is lossy; retrieve semantically. |
| **Operational config** — contacts, reception hours, thresholds | **Sidecar YAML** | Changes often; not a "fact about the building" worth modeling as RDF. |

Two caveats to keep honest:
- **"graphRAG" is a retrieval architecture, not just relocating text.** If facts become triples but
  users still ask in lay language ("where can I pray"), you still need embeddings / NL→SPARQL over the
  triples/labels — you relocate what semantic retrieval fetches, you don't delete it.
- The capability KB exists because **~50% of the survey corpus** (CAPABILITY 25.6% + OTHER 24%) had no
  SPARQL path. Migrating the structured subset shrinks that gap; genuinely off-ontology prose stays KB.

**Increment 1 — DONE & verified live (2026-07-11).** Building-agnostic vocab
(`ontology/ontosage_capabilities.ttl`) + 7 structured amenities as triples
(`input/bldg1_capabilities.ttl`, dual-typed `ontosage:Amenity`) + `CapabilityGraphResolver`
(templated SPARQL, conservative lay-term scoring) wired graph-first into the capability agent
with KB fallback (additive — zero risk to the working KB answers). Verified: 7 amenity triples
in GraphDB; *"prayer room"* → Floor 1 room 1.04 and *"nearest lift"* → full spec answered from
triples. Adding an amenity is now drop-a-triple, no code.

**Increment 2 — remaining.** Migrate the rest of the structured entries; index the amenity triples
into Qdrant so the semantic router still routes those questions to capability; then remove the
migrated duplicates from `capability.yaml` for true single-source. Long-form prose stays in the
document KB; operational config stays in sidecar YAML.

---

## Not code-fixable here (operational)

- **FIX-004 — data-coverage gap (P2).** ~1,314 sensors declared, only Floor 5 populated. The
  honesty fixes make this transparent at query time; closing it means populating the narrow tables
  and floors 0-4. Measure the exact gap any time with `python scripts/data_coverage_audit.py --live`.

---

## Working agreement
Whenever an item here is fixed or a new bug/caveat is found, update **both** this plan and
[`FIX_TRACKER.csv`](./FIX_TRACKER.csv) (Status, Date_Resolved, Verification). See the tracker rule
in `CLAUDE.md`.
