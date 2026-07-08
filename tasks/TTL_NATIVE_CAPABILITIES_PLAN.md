# TTL-Native Capabilities + Guided Triple GUI — Plan

**Status:** proposed (do AFTER the current admin-console phases) · **Date:** 2026-07-06
**Owner intent:** move capabilities out of the Qdrant KB and into the ontology as
first-class triples so they're answered via SPARQL, and add a guided GUI to author
those capability triples with built-in relationships. Resolves the
"question wrongly routes to `capability`" problem and honours the repo's TTL-first
principle.

---

## 0. Two corrections that shape the whole plan (read first)

The naive framing — "put capabilities in the TTL and it's fixed" — is wrong in two
ways. Both must be designed in from the start or the workstream fails.

1. **Storing knowledge in TTL does not change routing.** The misrouting is caused by
   `services/semantic_router.py` running *before* the data pipeline and claiming any
   query that matches the capability KB. Loading triples while that router still fires
   changes nothing. The fix is two-part: (a) capabilities become SPARQL-answerable
   triples **and** (b) the two competing routers collapse into one SPARQL-first path
   (RAG/doc fallback for prose). Workstream 4 below is therefore not optional.

2. **Not every capability is a triple.** Split them:
   - **Structural facts** → triples, SPARQL-answerable. "Fire exit on floor 3",
     "room 3.12 capacity = 40", "building has a bike shed", "lift serves floors 0–5".
   - **Procedural / policy prose** → stays as text (document KB, or an `rdfs:comment`
     / annotation on the relevant node). "If you find it too warm, the HVAC is
     zone-controlled; contact estates." Forcing prose into triples is lossy and
     produces nonsense triples.
   The GUI and migration must classify each capability into one of these buckets.

---

## 1. Goal & success criteria

- Structural capabilities live in a named graph `urn:ontosage:capabilities:<bldg>` as
  Brick/RDF triples, discoverable by SPARQL.
- A guided GUI lets an admin author a capability as triples **without hand-writing
  Turtle**: pick subject (from the ontology), pick a relationship (from a curated,
  ontology-valid list), enter/pick an object (type-aware, validated).
- Capability-style questions that have a structural answer are answered via SPARQL,
  not intercepted by the capability router.
- Existing prose capabilities keep working via the document KB / RAG fallback (no
  regression on the capability corpus).
- **Done =** the demo-DB temperature question (and the capability corpus) route
  correctly, and a newly GUI-authored capability is answerable via SPARQL without a
  code change — matching the "add one TTL file, no code" principle.

## 2. Workstreams

### WS-1 — Capability ontology model
- Decide the vocabulary. Prefer **reusing Brick + the existing HBCO overlay**
  (`ontology/hbco_core.ttl`, `hbco_mappings.ttl`) and standard predicates
  (`brick:hasPart`, `brick:feeds`, `rdfs:label`, `rdfs:comment`) before inventing new
  terms. Only define a small `cap:` vocabulary for genuinely missing relationships
  (e.g. `cap:providesAmenity`, `cap:hasPolicy`).
- Define a SHACL shape (or a lightweight validator) for a valid capability triple set,
  so the GUI can reject malformed input.
- Deliverable: `ontology/capabilities_vocab.ttl` + a shapes file.

### WS-2 — Migrate existing capabilities
- Convert `input/capability.yaml` (~32 entries) + any per-building overlay:
  - structural entries → triples in `urn:ontosage:capabilities:<bldg>`,
  - prose entries → `rdfs:comment` on the nearest node, or leave in the document KB.
- Script: `scripts/migrate_capabilities_to_ttl.py` (idempotent, SHA-guarded like the
  document indexer). Emits a report of what became triples vs stayed prose.
- Keep the Qdrant capability KB as a **fallback during transition** — do not delete it
  until the SPARQL path is proven on the capability corpus.

### WS-3 — Guided capability-triple GUI (the admin-console layer)
- New "Capabilities" tab in the admin console. **Reuse the existing sensor-registration
  pattern** (`Databases → Register sensors` already does points/CSV/TTL → triples into a
  named graph, with validation and a cache flush). This is the proven template.
- Guided form ("triple builder"):
  - **Subject**: autocomplete from existing ontology individuals (query GraphDB), or
    "new individual" with a Brick class picker.
  - **Relationship**: dropdown of curated, ontology-valid predicates (grouped:
    spatial / structural / amenity / policy), each with a human label and a hint.
  - **Object**: type-aware — another individual (autocomplete), a literal (typed:
    string/int/decimal/bool with unit), or a class.
  - Live preview of the Turtle it will emit; **SHACL/ontology validation before commit**.
  - Advanced mode: paste Turtle (validated) — same as the existing TTL upload.
- Backend: `POST /api/v1/admin/capabilities` (validate → write to
  `urn:ontosage:capabilities:<bldg>` → flush cache). `GET` to list/edit/delete.
  Mirror `databases/.../sensors` handlers.
- Guardrails: constrained vocabulary only (no arbitrary predicate free-text in guided
  mode); SHACL validation; system:admin only; writes to a named graph (reversible).

### WS-4 — Routing unification (the part that actually fixes misrouting)
- Make SPARQL the primary path for capability-style questions. Options, in order of
  preference:
  1. **Demote the capability semantic-router**: run SPARQL first; only fall to the
     capability KB when SPARQL returns empty. (Closest to TTL-first; biggest win.)
  2. Reorder precedence so a query with a structural SPARQL answer beats the capability
     router; keep the router only for prose-only questions.
- Preserve the RAG/document fallback for prose capabilities (WS-1 bucket 2).
- This touches `agents/dialogue_agent.py` (router probe order), `workflow/_routing.py`,
  and `services/semantic_router.py`. **High-blast-radius** — gate behind a flag
  (`CAPABILITIES_TTL_FIRST`) and measure on the capability corpus before defaulting on.

### WS-5 — Validation & tests
- Extend the corpus replay / QA suite: assert capability-corpus questions still answer
  (no regression) and that structural ones now route through SPARQL.
- Unit tests: the triple-builder validation, the migration script, the new endpoints.
- A/B the router change on the 6,117-question survey subset for capability strata.

## 3. Sequencing
Do **after** the current admin-console phases (1–3). Within this workstream:
WS-1 → WS-2 (migrate + keep KB fallback) → WS-3 (GUI) → WS-4 (routing flip, flagged)
→ WS-5 (measure, then default the flag on, then retire the Qdrant KB).

## 4. Risks / traps
- **Freeform triples → invalid ontology.** Mitigate: constrained vocab + SHACL; guided
  mode never exposes raw predicate entry.
- **Prose that doesn't triple-ify.** Mitigate: the structural/prose split (WS-1); don't
  force prose into triples.
- **Router change regresses capability answers.** Mitigate: flag + RAG fallback +
  corpus measurement before defaulting on.
- **Migration lossiness.** Mitigate: keep the Qdrant KB until SPARQL parity is proven;
  migration report shows exactly what converted.
- **Scope creep into a general ontology editor.** Keep it scoped to *capabilities*;
  don't build a full Protégé-in-the-browser.

## 5. Open questions to resolve at kickoff
- Which existing capability entries are structural vs prose? (audit `capability.yaml`.)
- Is HBCO's vocabulary enough, or is a small `cap:` namespace needed?
- Does the disambiguation problem (a demo/new sensor competing with many existing
  sensors of the same class) need addressing here, or is it a separate concern?
