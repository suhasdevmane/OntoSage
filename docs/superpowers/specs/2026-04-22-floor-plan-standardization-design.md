# Floor Plan Standardization — Design Spec

**Date:** 2026-04-22
**Author:** OntoSage team
**Status:** Approved for implementation
**Scope:** All 4 phases (P1 → P4), end-to-end
**Supersedes:** Ad-hoc `FloorPlanService` + inline `_floor_plan_node` logic

---

## 1. Problem Statement

The current floor plan integration works only when the user types an explicit floor
number and a well-formed zone ID (e.g. *"Show me zone 5.12"*). It cannot answer:

- *"Where is the server room?"* (no floor specified)
- *"Which floor has the meeting rooms?"* (cross-floor)
- *"Show me what's on each floor."* (building overview)
- *"I'm on floor 3 — show me the layout."* (needs an interactive view, not a PDF link)

It is also **not portable**: filename pattern, zone-ID regex, ontology namespace, and
response copy are hard-coded to the Abacws building. Adding a new building today
requires code edits.

## 2. Goals

G1. **Standard representation** — every floor-plan PDF produces a canonical
    `FloorPlanManifest` JSON that downstream code consumes instead of raw PDFs.

G2. **Automatic ingestion** — drop PDFs into `/app/input/`, system picks them up,
    renders, extracts, classifies, links to ontology, and publishes a manifest.

G3. **Interactive conversation** — user sees a clickable image of the floor plan,
    taps a space, and the system answers using the corresponding ontology entity.

G4. **Building-agnostic portability** — switching buildings requires only dropping
    new PDFs (plus an optional `building.yaml`). Zero code changes.

G5. **Production-grade** — idempotent pipeline, file watcher, auth-protected API,
    persistent storage, unit + E2E tests, graceful degradation.

## 3. Non-Goals

- 3D modelling, BIM (IFC) ingestion — out of scope.
- OCR of scanned image-only PDFs in P1–P4 (text-rich PDFs assumed; OCR is a future phase).
- Editing / authoring floor plans in the UI.
- Real-time collaboration (multiple users annotating the same plan).

## 4. The Standard Representation: FloorPlanManifest

One JSON document per floor, on disk and in Qdrant/Redis.

**Path:** `/app/input/.floor_plans/<building_id>/floor_<N>.manifest.json`

**Schema version:** `1.0` (the `schema_version` field enables forward-compatible
migrations — readers reject unknown versions they can't handle).

```json
{
  "schema_version": "1.0",
  "building_id": "abacws",
  "building_name": "Abacws",
  "floor": 3,
  "floor_label": "Floor 3",
  "source_pdf": "Abacws floor 3.pdf",
  "source_sha256": "b1946ac92492d2347c6235b4d2611184…",
  "generated_at": "2026-04-22T10:00:00Z",
  "generator_version": "1.0.0",
  "page_count": 1,
  "rendered_image": {
    "png_url": "/floor-plans/abacws/floor_3.png",
    "thumbnail_url": "/floor-plans/abacws/floor_3_thumb.png",
    "width_px": 2400,
    "height_px": 1600,
    "dpi": 200
  },
  "pdf_url": "/floor-plans/Abacws%20floor%203.pdf",
  "bounding_box": { "width_pt": 842, "height_pt": 595 },
  "spaces": [
    {
      "id": "abacws.3.01",
      "zone_id": "3.01",
      "label": "Office 3.01",
      "aliases": ["Room 3.01", "Office 3-01"],
      "type": "office",
      "tags": ["office", "staff"],
      "centroid": { "x": 0.23, "y": 0.41 },
      "bbox": { "x": 0.18, "y": 0.36, "w": 0.10, "h": 0.10 },
      "polygon": null,
      "sensor_uuids": [],
      "ontology_iri": "https://abacws.example/zones/3-01",
      "source": "text_extraction",
      "confidence": 0.92
    }
  ],
  "facilities": {
    "toilet": ["3.05"],
    "meeting_room": ["3.12"],
    "staircase": ["3.00a", "3.00b"],
    "lift": ["3.00c"]
  },
  "ontology_links": {
    "3.01": "https://abacws.example/zones/3-01"
  },
  "warnings": []
}
```

**Coordinate convention:** all `centroid`, `bbox`, `polygon` values are **normalised
to [0, 1]** relative to the rendered image. The UI scales them to the displayed
size. This keeps manifests independent of render resolution.

**Space `id`:** `"<building_id>.<zone_id>"` — globally unique across buildings.

**Space `type` vocabulary (closed set, v1.0):**
`office | lab | meeting_room | classroom | lecture | toilet | kitchen | server_room | storage | staircase | lift | reception | corridor | utility | unknown`.

Unknown types fall back to `"unknown"` with the raw label preserved in `label`.

## 5. Ingestion Pipeline

New module: `orchestrator/services/floor_plan_pipeline.py`.

Ten sequential steps. Each step is a pure-ish function with clear inputs/outputs,
testable in isolation.

```
 PDF in /app/input/
   │
   ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 1. discover(pdf_dir)        → List[PdfSource]                │
 │ 2. fingerprint(path)        → sha256 + skip-if-unchanged     │
 │ 3. render_pages(pdf)        → List[PageImage] (PyMuPDF@200dpi)│
 │ 4. extract_text_layer(pdf)  → List[TextBlock with bbox]       │
 │ 5. detect_spaces(blocks)    → List[RawSpace] (regex + NER)   │
 │ 6. classify_types(spaces)   → spaces annotated with type      │
 │ 7. normalise_ids(spaces)    → consistent zone_id format       │
 │ 8. link_ontology(spaces)    → match to GraphDB IRIs           │
 │ 9. embed_and_index(spaces)  → Qdrant upsert (per-space chunks)│
 │10. write_manifest(floor)    → JSON + Redis cache              │
 └──────────────────────────────────────────────────────────────┘
   │
   ▼
 Ready to serve
```

**Idempotency:** step 2 short-circuits if the SHA-256 matches the existing manifest's
`source_sha256`. Re-running the pipeline on unchanged inputs is a no-op.

**Failure handling:** step failures populate `manifest.warnings[]` instead of raising.
A manifest with warnings is still published and usable. The only fatal step is
step 1 (no PDF found) and step 3 (cannot render) — these skip the floor with a log
warning.

**Dependencies added:**
- `pymupdf` (a.k.a. `fitz`) — PDF rendering + coordinate-aware text extraction.
- `watchfiles` — async file watcher.

`pdfplumber` stays for backwards compatibility with `document_ingestion.py`.

### 5.1 Step 5 — Space detection

Two-layer extractor:
1. **Regex layer** — zone IDs matching the building's `zone_id_pattern`
   (default: `r"(\d+)\.(\d+)"`).
2. **LLM layer** — for each text block unmatched by regex, classify
   whether it is a space label (e.g. *"Open Plan Office"*, *"Kitchen"*,
   *"Server Room"*). Uses a cheap model (`gpt-4o-mini` or the local
   equivalent) and is batched per page.

LLM layer is opt-in via `FLOOR_PLAN_LLM_EXTRACT=true` (default on; falls
back to regex-only if LLM is unavailable).

### 5.2 Step 6 — Type classification

Rule-based first (keyword match against the closed-set vocabulary from §4).
LLM fallback for ambiguous labels. Results cached in Redis by `(label, building_id)`.

### 5.3 Step 8 — Ontology linking

Query GraphDB:
```sparql
SELECT ?zone WHERE {
  ?zone a brick:HVAC_Zone .
  ?zone rdfs:label ?label .
  FILTER(STR(?label) = "3.01" || STR(?label) = "Zone 3.01")
}
```

Match by exact label, then by `zone_id` stripped of prefixes. Misses are
logged to `manifest.warnings[]` so operators can see which spaces have no
sensor data available.

## 6. File Watcher

New module: `orchestrator/services/floor_plan_watcher.py`.

```python
async def watch_forever(pipeline: FloorPlanPipeline, directory: Path):
    async for changes in awatch(directory):
        for change, path in changes:
            if path.endswith(".pdf"):
                await pipeline.ingest_file(path)
```

Started as a background task in `main.py`'s lifespan hook. Non-fatal on failure —
startup still completes; a warning is logged. Watcher is **opt-out** via
`FLOOR_PLAN_WATCHER=false` (useful for CI / tests).

## 7. Agent Architecture

### 7.1 `orchestrator/agents/floor_plan_agent.py` (NEW)

Promotes the current inline `_floor_plan_node` to a proper agent class, mirroring
`SPARQLAgent` / `SQLAgent` conventions.

```python
class FloorPlanAgent:
    async def resolve(self, query: str, state: ConversationState) -> FloorPlanResult:
        # 1. detect building_id (from state, query, or default)
        # 2. detect floor (explicit → state.floor_context → None)
        # 3. detect space (zone_id regex → manifest search → LLM resolver)
        # 4. branch:
        #    A) space known     → result with selected_space populated
        #    B) floor known     → result with candidates populated (disambiguation)
        #    C) nothing known   → cross-floor search OR building overview
        # 5. set floor_context for downstream SPARQL
```

Output: a structured `FloorPlanResult` (see §8), not just markdown.

### 7.2 Workflow integration

`workflow.py`:
- `_floor_plan_node` becomes a thin wrapper that calls `FloorPlanAgent.resolve()`
  and writes the result to `state.intermediate_results["floor_plan_result"]`.
- `_response_node` reads `floor_plan_result` and renders it differently depending
  on whether a UI-capable client is connected (WebSocket clients get structured
  JSON; REST clients get markdown).
- `_response_node` also **injects a mini floor-plan card** at the end of any
  response that resolves to a specific zone — regardless of intent — so every
  sensor / analytics / compliance answer has a "see on floor plan" link.

### 7.3 Dialogue agent

Expand floor_plan intent keywords:

> navigate, directions, office, lab, meeting room, server room, toilet, bathroom,
> staircase, lift, elevator, find, locate, where can I find, building directory,
> which floor has, which floor is, show me the building

## 8. New Pydantic Models

Added to `shared/models.py`:

```python
class Point(BaseModel):
    x: float = Field(..., ge=0, le=1)
    y: float = Field(..., ge=0, le=1)

class BoundingBox(BaseModel):
    x: float; y: float; w: float; h: float  # all normalised [0,1]

class Space(BaseModel):
    id: str
    zone_id: str
    label: str
    aliases: List[str] = []
    type: SpaceType  # Literal[…vocabulary from §4…]
    tags: List[str] = []
    centroid: Optional[Point] = None
    bbox: Optional[BoundingBox] = None
    polygon: Optional[List[Point]] = None
    sensor_uuids: List[str] = []
    ontology_iri: Optional[str] = None
    source: Literal["text_extraction", "llm", "manual"] = "text_extraction"
    confidence: float = 1.0

class RenderedImage(BaseModel):
    png_url: str
    thumbnail_url: str
    width_px: int
    height_px: int
    dpi: int

class FloorPlanManifest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    building_id: str
    building_name: str
    floor: int
    floor_label: str
    source_pdf: str
    source_sha256: str
    generated_at: datetime
    generator_version: str
    page_count: int
    rendered_image: RenderedImage
    pdf_url: str
    bounding_box: Dict[str, float]
    spaces: List[Space] = []
    facilities: Dict[str, List[str]] = {}
    ontology_links: Dict[str, str] = {}
    warnings: List[str] = []

class FloorPlanResult(BaseModel):
    building_id: str
    floor: Optional[int]
    selected_space: Optional[Space]
    candidates: List[Space] = []
    manifest_url: Optional[str]
    interactive: bool = True
    markdown: str             # fallback text rendering
```

## 9. REST API

All new endpoints live under `/api/v1/floor-plans/` and require `metadata:read`
(guest/readonly role suffices). Rendered PNGs are served statically by the
existing nginx `file-server` container — no auth, same as the PDFs today.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/floor-plans` | List buildings + floors + manifest status |
| GET | `/api/v1/floor-plans/{building}/{floor}/manifest` | Full manifest JSON |
| GET | `/api/v1/floor-plans/{building}/{floor}/image.png` | Rendered PNG (nginx) |
| GET | `/api/v1/floor-plans/{building}/{floor}/thumb.png` | Thumbnail (nginx) |
| GET | `/api/v1/floor-plans/search?q=…&building=…` | Cross-floor space search |
| GET | `/api/v1/floor-plans/overview?building=…` | Per-floor summary cards |
| GET | `/api/v1/floor-plans/facilities?type=toilet&building=…` | Facility locator |
| POST | `/api/v1/floor-plans/reingest` | Admin-only; force regeneration (needs `system:admin`) |

Existing endpoints (`/floor-plans/` and `/floor-plans/floor-{N}.pdf`) are kept as
redirects for one release, then removed.

All responses follow the standard envelope defined in `.claude/rules/api-contracts.md`.

## 10. Frontend — Interactive Viewer

New component: `frontend/src/components/FloorPlanViewer.js`.

Three tiers — all ship in scope:

### T1 — Image + invisible hotspots (baseline)
PNG background + absolutely-positioned `<button>` per space at the space's
normalised `centroid`/`bbox`. Click → emits `selectSpace(space)` which the chat
container forwards as a user message: *"Tell me about {space.label}"*.

### T2 — SVG polygon overlay (default)
Replaces hotspots with `<svg>` polygons. Adds hover tooltip showing `label`,
`type`, and live sensor reading (fetched on mount from `/api/v1/sensors/latest`
keyed by `space.sensor_uuids`). Colour-coded by sensor status (green/amber/red).

### T3 — Side panel
Scrollable list of all spaces; filter by `type`; click a row → scrolls/highlights
on the plan. Search box at the top maps to `/api/v1/floor-plans/search`.

### Chat integration
When the orchestrator returns a `FloorPlanResult` with `interactive=true`, the chat
client renders the `FloorPlanViewer` inline as a message. Falls back to markdown
PDF link if the client doesn't support the component (e.g. Open WebUI).

## 11. Building-Agnostic Portability

Switching to a new building:

1. Drop `<building_slug> floor <N>.pdf` into `/app/input/`.
2. (Optional) Add `/app/input/<building_slug>/building.yaml`:
   ```yaml
   building_id: cardiff_eng
   building_name: Cardiff Engineering
   zone_id_pattern: "R{floor}{nnn}"           # default: "{floor}.{nn}"
   ontology_namespace: "https://cardiff.example/zones/"
   default_dpi: 200
   display_name: "Cardiff School of Engineering"
   ```
3. Restart the orchestrator (watcher also picks it up live).

No code changes. No UI changes. The manifest schema, API, agent, and viewer
are all parameterised by `building_id`.

Registry: `orchestrator/services/building_registry.py` (NEW) — loads all
`building.yaml` files at startup and exposes `get_building(building_id)`.
Default building is `abacws` (back-compat).

Configuration knobs centralised in `shared/floor_plan_config.py`.

## 12. Storage & Caching

| Store | What | Why |
|---|---|---|
| Filesystem | `/app/input/.floor_plans/<bid>/*.manifest.json`, `*.png` | Source of truth; survives container restart if volume-mounted |
| Qdrant | `floor_plans` collection — per-space embeddings | Semantic cross-floor search |
| Redis | `floor_plan:manifest:<bid>:<N>` (TTL 1h) | Fast repeat reads from agent |
| In-memory | `FloorPlanService._manifest_cache` | Hot path within a single request |

Docker-compose: add a named volume `floor_plan_artifacts:/app/input/.floor_plans/` so
generated artefacts survive container recreation.

## 13. Phased Rollout

Each phase is a separate PR; each independently useful.

### Phase 1 — Standardization core
- `FloorPlanManifest` Pydantic model
- `floor_plan_pipeline.py` steps 1–4, 7, 10 (regex-only, no LLM, no ontology link)
- `GET /api/v1/floor-plans/{building}/{floor}/manifest`
- Generate manifests for Abacws floors 0–5
- Tests: unit (each step), golden manifest for floor 3

### Phase 2 — Smart extraction
- LLM space detector (step 5 layer 2)
- LLM type classifier (step 6)
- Ontology linker (step 8)
- Qdrant embedding + semantic search (step 9)
- `search`, `overview`, `facilities` endpoints
- Cross-floor search in `FloorPlanAgent`
- Tests: E2E (ingest → query "where is server room?" → correct result)

### Phase 3 — Interactive UI
- `FloorPlanViewer` component (T1 + T2; T3 if time)
- Chat integration — inline rendering of `FloorPlanResult`
- `_response_node` floor-plan cards on every zone-resolved response
- Dialogue keyword expansion

### Phase 4 — Hardening
- File watcher
- `POST /api/v1/floor-plans/reingest`
- `building.yaml` + `building_registry.py`
- Multi-building integration test (synthetic second building fixture)
- Admin dashboard view of manifest status + warnings
- Remove deprecated endpoints

## 14. Testing Strategy

### Unit tests (per pipeline step)
`tests/test_floor_plan_pipeline.py` — one test per step with fixture inputs.

### Golden manifest test
`tests/fixtures/floor_plans/abacws_floor_3.pdf` → run pipeline → diff against
`tests/fixtures/floor_plans/abacws_floor_3.manifest.golden.json`. Regenerate
the golden with `pytest --update-golden` when extraction improves.

### E2E test
`tests/test_floor_plan_e2e.py` — starts a reduced stack (no GraphDB/MySQL),
ingests fixture, queries *"where is the meeting room?"*, asserts the returned
`FloorPlanResult` contains the expected floor + zone.

### Portability test
`tests/fixtures/floor_plans/synthetic_building_*.pdf` — proves a second
building works without code changes.

### Linting
Pipeline and agent modules pass `black`, `isort`, `flake8`, `bandit` at the
project defaults.

## 15. Observability

Every pipeline run emits structured logs:
```
[floor_plan_pipeline] building=abacws floor=3 step=render duration_ms=312 ok=true
```

Metrics exposed via existing Prometheus endpoint:
- `floor_plan_ingestion_total{building,floor,outcome}`
- `floor_plan_ingestion_duration_seconds{building,floor,step}`
- `floor_plan_manifest_warnings{building,floor}`
- `floor_plan_api_requests_total{endpoint,status}`

Trace IDs (already injected by middleware) propagate through the pipeline.

## 16. Security & Privacy

- Rendered PNGs are public like the PDFs are today (served by nginx).
- Manifest endpoint requires `metadata:read` — consistent with other ontology data.
- `POST /reingest` requires `system:admin`.
- Uploaded `building.yaml` files are **not user-uploadable** via API — operators
  place them on disk. This prevents config-injection attacks.
- No user input is interpolated into SPARQL; ontology linker uses parameterised
  queries.

## 17. Migration / Backwards Compatibility

- `FloorPlanService` keeps its existing public methods (`detect_floor_from_query`,
  `get_pdf_url`, etc.) — they now delegate to the manifest where applicable.
- The existing `floor_plan` Qdrant collection is preserved for one release, then
  deleted during the P2 migration.
- Existing `/floor-plans/` endpoints return `301` to the new `/api/v1/floor-plans/…`
  equivalents for one release.
- No database migration needed (manifests are filesystem + Qdrant).

## 18. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM extraction returns garbage labels | Regex layer runs first; LLM results require confidence ≥ 0.6 or fall through to `unknown` |
| PyMuPDF licence (AGPL) conflicts with project licence | Project is not redistributed as a library; AGPL compatible with internal deployment. Revisit before open-sourcing. Alternative: `pypdfium2` (Apache-2) as drop-in for rendering-only |
| Ingestion slows startup | Pipeline runs in a background task; API returns 503 for manifest endpoints until the first ingest completes, with clear error |
| File watcher leaks FDs or crashes | Run in a supervised task; on exception, log and restart with backoff; non-fatal |
| Manifest schema evolves | `schema_version` field; readers reject unknown versions cleanly |
| Second-building zone pattern doesn't fit default regex | `building.yaml.zone_id_pattern` is fully configurable |

## 19. Open Questions

None blocking. Post-launch considerations:

- Should manifests be versioned per-change so we can diff plan updates over time?
- OCR support for scanned-only PDFs — defer until needed.
- Should we expose a manual "edit spaces" admin UI? Probably yes, post-launch.

## 20. Success Criteria

- [ ] Dropping Abacws floor 0–5 PDFs produces 6 manifests with ≥ 10 recognised spaces each
- [ ] *"Where is the server room?"* returns the correct floor without user specifying it
- [ ] *"Show me floor 3"* renders an interactive viewer in the web frontend
- [ ] Every sensor-data response for a known zone includes a floor-plan card link
- [ ] Synthetic second-building fixture passes the portability E2E test
- [ ] All new modules have ≥ 80% line coverage
- [ ] `pytest -m integration` passes in CI

---

**Next step:** invoke `writing-plans` skill to produce the phased implementation plan.
