# Capability → TTL Migration & Routing Unification — Execution Plan

**Created:** 2026-07-12 · **Tracker:** [`FIX_TRACKER.csv`](./FIX_TRACKER.csv) (TODO-010→014) ·
**Design/why:** [`TTL_NATIVE_CAPABILITIES_PLAN.md`](./TTL_NATIVE_CAPABILITIES_PLAN.md),
[`GROUNDING_AND_HONESTY_FIXES_PLAN.md`](./GROUNDING_AND_HONESTY_FIXES_PLAN.md)

## Goal
Answer **all** Abacws capability questions from ontology triples (SPARQL), and retire the fuzzy
Qdrant capability-KB router that causes misrouting — then remove `capability.yaml`. Prove parity
before deleting anything.

## Namespace contract (per your instruction — enforced everywhere)
- **Base URL:** `bldg:` = `http://abacwsbuilding.cardiff.ac.uk/abacws#`
- **Schema:** `ontosage:` = `http://ontosage.org/capabilities#` (already in `ontology/ontosage_capabilities.ttl`)
- Capability facts live in **`input/bldg1_capabilities.ttl`**, co-loaded with `bldg1_enhancements.ttl`
  and the other `bldg1_*.ttl` into the same GraphDB repo. Extend the `ontosage:` vocab (e.g.
  `ontosage:Service`, `ontosage:Facility`) only for genuinely new categories — reuse Brick where it fits.

## The structural / prose split (non-negotiable — from the design plan)
- **Structural facts** (locations, counts, features: prayer room, lift, toilets, CCTV, occupancy,
  access points, EV chargers…) → **triples**, SPARQL-answerable.
- **Prose / policy** (fire procedures, GDPR, IT support, complaints, visitor policy) → **document KB**
  (`input/documents/`, already indexed) — *not* forced into triples (lossy). 24 already moved.
- End state: `capability.yaml` is **gone**; every entry is either a triple or a document.

---

## Phase 1 (P1) — Complete triples + SPARQL-first routing  ← the misrouting fix
1. **Audit & classify** every remaining `capability.yaml` entry: structural → triples, prose → docs
   (most prose already in `building_reference.md`). Produce a one-line disposition per entry.
2. **Migrate remaining STRUCTURAL entries** → `bldg1_capabilities.ttl` on `bldg:` + `ontosage:`
   (access points, EV/occupancy/security facts that aren't already in `bldg1_enhancements.ttl`,
   key labs, accessibility summary). Extend the `ontosage:` vocab minimally if needed. Validate parse.
3. **Bridge routing to the triples** (the key step): extend `capability_indexer.py` to index the
   `ontosage:Amenity` triples (label + `ontosage:layTerms`) into the **capability Qdrant collection**,
   so `semantic_router.py` still recognises capability questions once `capability.yaml` shrinks.
4. **Flag-gated routing flip** `CAPABILITIES_TTL_FIRST` (default **false**): capability node order
   becomes graph resolver → document KB → capability KB (fallback). When on, routing relies on
   triples+docs, not `capability.yaml` prose. Touches `capability_agent.py`, `semantic_router.py`,
   `workflow/_routing.py`, `shared/config.py`.
5. **Tests:** routing-flip unit tests; graph-resolver coverage for the new amenities.

**Phase-1 exit:** with the flag ON, amenity/facility questions answer from triples, prose from
documents, and no capability query misroutes — `capability.yaml` still present as the safety net.

## Phase 2 (P2) — Measure, then remove capability.yaml
6. **Measure (TODO-011):** A/B `CAPABILITIES_TTL_FIRST` off vs on on the capability strata
   (`scripts/corpus_replay.py` + `scripts/ontosage_qa_suite.py`, capability/amenities/policy). Record
   deltas in the tracker. **Gate:** pass rate ON ≥ OFF.
7. **Flip default to true** once green.
8. **Remove `capability.yaml` (TODO-012):** delete the file; rewire `capability_indexer.py`,
   `semantic_router.py`, `capability_agent.py` (drop `_load_kb`), `capability_schema.py`,
   `building_paths.py`, `swap_building.py`; update ~11 tests + docs. Full suite + corpus green.

## Phase 3 (P3) — Polish
9. Any remaining structural entries (TODO-013). 10. Guided capability-triple GUI (TODO-014, optional).

---

## How you verify it's working (at each phase)
- **SPARQL:** `SELECT (COUNT(?a)) WHERE { ?a a ontosage:Amenity }` grows to cover all structural
  capabilities; `bldg1_capabilities.ttl` loads into the repo with the others.
- **Live `/chat`:** amenity/facility questions → *"Answered live from the building ontology (triples)"*;
  prose questions → document-sourced; a known data query (e.g. "how many sensors") does **not** get
  hijacked by capability.
- **Corpus:** capability/amenity/policy pass rate with flag ON ≥ baseline.
- **Tests:** full unit suite green throughout; nothing removed until Phase 2 gate passes.

## Guardrails
- Nothing is deleted until Phase-2 measurement passes (KB stays as fallback).
- Every flip is flag-gated + reversible (named-graph writes, `CAPABILITIES_TTL_FIRST`).
- All new triples: `bldg:` base + `ontosage:` schema. No building literals in code.
- I stop for your review at each phase boundary before proceeding.
