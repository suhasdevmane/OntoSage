# TODO-010→012: Concrete `capability.yaml` removal — the resolver chain as the single path

**Status:** draft (execution not started) · **Date:** 2026-07-28 · **Depends on:** TODO-010 (done, flag-gated), TODO-011 (done, 0 regressions)
**Goal:** collapse the two competing capability paths (Qdrant KB router + `capability.yaml` KB answering) into **one** source-agnostic resolver chain — `live-metrics → ontology triples → documents → honest no-info` — and delete `capability.yaml`.

This is the finish line for the TTL-first capability work, not a fresh migration. Read the honest state below before touching anything.

---

## 0. Where we actually are (so we don't re-do done work)

| Piece | State | Evidence |
|---|---|---|
| Resolver chain in the capability node | **Built & correct** (post BUG-076/078: every source is KB-independent, no source gates another) | `capability_agent.answer()`; `tests/test_capability_bare_building.py` (5 guardrail tests) |
| Amenities as `ontosage:Amenity` triples | **Working** — answered via SPARQL regardless of the flag | `capability_graph_resolver.py`; TODO-010 verification |
| Documents (`documents_<bldg>`) as prose source | **Working** — surfaces with no `capability.yaml` present | BUG-078 fix; bldg2 wifi @0.671 live |
| `CAPABILITIES_TTL_FIRST` flag | **Exists, default `false`** | `shared/config.py:501` |
| Corpus parity OFF vs ON | **Measured, 0 regressions** | TODO-011; `scripts/measure_capability_routing.py`, `scripts/measure_capability_corpus.py` |
| A building running with **no** `capability.yaml` | **Already real** — bldg2 ships without it | `input/` has only `bldg2_capabilities.ttl` |
| `capability.yaml` KB actually being hit | **Never**, under bge-large + flag ON | TODO-012 verification ("safety net NEVER hit → DORMANT") |

**Conclusion:** `capability.yaml` is already dormant, not load-bearing for *answers*. Two things still reference it:
1. **Routing** — when `CAPABILITIES_TTL_FIRST=false` (the shipped default), `dialogue_agent` still runs the Qdrant capability-KB probe (`dialogue_agent.py:713`) to *route* to the capability intent. This is the last real coupling.
2. **Dead-weight code + tests** — `_load_kb`, `CapabilityKB`, indexer/validator/path resolution, ~11 tests.

---

## 1. The go / no-go gate (do NOT skip — this is the one real risk)

The only thing `capability.yaml` still buys is a **retrieval safety net for weak local embeddings**. On MiniLM (384-d) prose like wifi scored **0.248** — below the document floor — so the KB caught it. On **bge-large (1024-d)** the same query scores **0.671** and documents catch it directly.

**Gate:** removal is safe **iff** the deployment's `EMBEDDING_PROVIDER` yields reliable document retrieval for prose capabilities. Concretely, before deleting anything:

```bash
# With the target embedding provider active, flag ON, cache flushed:
CAPABILITIES_TTL_FIRST=true python scripts/measure_capability_corpus.py   # ~41 Q
# PASS criterion: 0 answers whose provenance == "capability_kb" (the safety net).
#                 Every prose Q answered from "document_kb"; every amenity from "capability_graph".
```

- **bge-large / OpenAI:** expected PASS → proceed. (Current bldg2 deployment.)
- **MiniLM-only deployments:** if any prose Q falls back to `capability_kb`, **stop** — either (a) raise embedding quality, (b) add per-topic documents for the gap, or (c) keep `capability.yaml` as an *optional, lowest-priority* source and only remove the *router* coupling (steps 2–3), not the file (steps 4–6).

Encode the gate as an assertion in the measurement script so it's a hard stop, not a judgement call.

---

## 2. Step-by-step (each step independently shippable + reversible)

Ordered so the system is always working. Steps 2–3 retire the *router* coupling; 4–6 delete the *file*; 7 removes the now-dead flag.

### Step 1 — Lock the invariant first (DONE)
`tests/test_capability_bare_building.py` already asserts the resolver chain answers from each source with `kb=None`, and that no source is a precondition. This is the safety net for every step below — keep it green throughout.

### Step 2 — Make TTL-first the default (routing flip)
- `shared/config.py`: `CAPABILITIES_TTL_FIRST` default `false → true`.
- Run the Step-1 guardrail + `scripts/measure_capability_routing.py` (OFF vs ON already 0-regression; this just makes ON the shipped state).
- **Ship this alone first.** It's the highest-value, lowest-code change: the graph+document router (`dialogue_agent.py:777+`) becomes the live path; the Qdrant KB probe stops firing. Bake it for a QA cycle before deleting code.

### Step 3 — Delete the legacy KB router branch
Once Step 2 is proven, the `not settings.CAPABILITIES_TTL_FIRST` branch is dead:
- `dialogue_agent.py:713-770` — remove the Qdrant capability-KB probe block (the `and not settings.CAPABILITIES_TTL_FIRST` path). Keep only the graph+document router.
- `services/semantic_router.py` — remove the capability-KB `classify()` path + `capability_<bldg>` collection query. Keep the intent-registration / floor_plan / spatial probes (those are unrelated).
- Verify: `test_semantic_router*`, `test_capability_routing_config`, routing-accuracy suite.

### Step 4 — Drop `capability.yaml` from the answering chain
- `capability_agent.py`:
  - Remove `_load_kb`, the `kb`/`matches`/`pre_fetched` machinery, and the `capability_kb` branch (lines ~242-267, ~306-328).
  - The chain becomes exactly: `live_metrics → capability_graph → documents → honest no-info`. Display name always from `resolve_building_context()` (already the `kb is None` path — now the *only* path).
  - `building_name = resolve_building_context(building_id).name` unconditionally.
- `capability_indexer.py` — stop indexing `capability.yaml`; index amenity triples + documents only (documents already handled by `document_indexer.py`, so this may reduce to deletion).
- Keep the Step-1 guardrail green (it already runs with `kb=None`, so it becomes the *primary* spec for this node).

### Step 5 — Remove the file + its plumbing
- Delete `input/capability.yaml`, `bldg1/capability.yaml`, and per-building `capability.yaml` fixtures no longer used.
- `shared/capability_schema.py` — delete `CapabilityKB`/`CapabilityEntry` (or reduce to whatever `capability_graph_resolver` still needs — it uses its own `_Amenity`/`CapabilityFact`, so likely full deletion).
- `shared/building_paths.py` — drop `capability.yaml` from `resolve_building_file` lookups.
- `scripts/swap_building.py` — drop `capability.yaml` from `_check_optional_configs`.
- `services/building_metrics.py` — update the stale "never from capability.yaml" comment (it's now vacuously true).
- Grep sweep: `rg -i "capability\.yaml|CapabilityKB|_load_kb|capability_matches"` → zero hits in non-test code.

### Step 6 — Fix the ~11 coupled tests
Per TODO-012's audit: `test_capability_indexer`, `test_semantic_router*`, `test_capability_e2e`, `test_survey_aligned_phases`, `test_capability_routing_config`, `test_multi_tenant_fixture`, `test_capability_flat_layout`, `test_building_paths`, `test_flat_layout_loaders`.
- Retarget each from "assert `capability.yaml` loads/indexes" to "assert amenity-triple + document path answers." Many collapse into the bare-building guardrail's model — reuse its fixtures.
- Do **not** just delete failing assertions; convert them to the triples/documents equivalent so coverage doesn't drop.

### Step 7 — Retire the flag
Once there's a single path, `CAPABILITIES_TTL_FIRST` guards nothing:
- Remove the field from `shared/config.py`, the `.env` docs, and the two `dialogue_agent` references.
- Update `README.md`, `ONTOSAGE.md`, `CLAUDE.md` (drop the flag from the open-issues list; state capabilities = triples + documents, single path).

---

## 3. End state (before → after)

```
BEFORE (two paths, flag-dependent):
  route:  [flag off] Qdrant capability-KB probe ─┐
          [flag on]  graph + document router ────┴─→ capability intent
  answer: [flag off] KB matches → documents → no-info
          [flag on]  metrics → graph → documents → KB(safety net) → no-info

AFTER (one path, no flag):
  route:  graph(amenity triples) + strong-document match ─→ capability intent
  answer: live-metrics → ontology triples → documents → honest no-info
          (every source optional; NONE is a precondition for the next — locked by the bare-building guardrail)
```

New building onboarding after this: **drop TTL (+ optional documents). No `capability.yaml`, no code.** Exactly the "connect data → get answers" contract.

---

## 4. Verification (each step)

- **Every step:** `pytest tests/test_capability_bare_building.py -q` stays green (the invariant).
- **Steps 2–3:** `scripts/measure_capability_routing.py` (16-Q) + `tests/test_routing_accuracy.py`.
- **Steps 4–6:** `scripts/measure_capability_corpus.py` with the Step-1 gate assertion (0 `capability_kb` provenance) + full `pytest -m unit -q`.
- **Final:** `scripts/corpus_replay.py` capability strata ≥ pre-removal pass rate; live QA on bldg2 (no `capability.yaml`) + bldg1 (had one) — both answer amenities from triples, prose from documents.

## 5. Rollback
- Steps 2–3 revert = flip the default back + restore the branch (pure code, no data loss).
- Steps 4–6 revert = restore `capability.yaml` from git + the schema/paths. Because the file is deleted only in Step 5, everything through Step 4 is reversible without touching data.

## 6. What NOT to do
- **Don't delete the file before Step 2 is baked.** The router still needs the KB collection when the flag is off; deleting first breaks routing.
- **Don't force prose into triples** to avoid documents (WS-1 bucket rule). Wifi/GDPR/policy stay as documents.
- **Don't remove the `capability_graph` or `documents` sources** thinking "one path" means "one source." One *path*, still multiple *sources* — that's the whole point of the resolver chain.
- **Don't skip the MiniLM gate** (§1). It is the single thing that makes this unsafe if ignored.
```
