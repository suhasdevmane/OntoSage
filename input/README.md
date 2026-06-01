# `input/` — The mutable surface

After Phases 1-8 of the production-hardening plan, **everything that varies
between deployments lives in this directory**.  The orchestrator boots,
discovers what's here, and adapts.  No Python edits required to:

- Onboard a new building
- Add a new persona
- Add or tune intents
- Switch storage backends
- Ingest new TTL ontologies

## Directory layout

```
input/
├── README.md                       this file
├── intents.yaml                    (optional) global intent overlay
│
├── personas/                       global persona overlays
│   ├── README.md                   persona YAML schema docs
│   ├── caretaker.yaml              demo: persona added with zero Python edits
│   └── auditor.yaml                demo: a 2nd persona
│
├── <BUILDING_ID>/                  one directory per building
│   ├── building.yaml               identity + storage + zone regex + aliases
│   ├── capability.yaml             off-ontology Q&A KB
│   ├── intents.yaml                (optional) per-building intent overlay
│   ├── personas/                   (optional) per-building persona overrides
│   │   └── facility_manager.yaml   demo: domain priors tweaked for this site
│   ├── *.ttl                       sensor ontology files (auto-uploaded)
│   └── floor_plans/                (legacy: PDFs at top of input/ also work)
│
├── bldg2-example/                  complete skeleton for a 2nd building
│   └── README.md                   how to activate
│
├── <BuildingName> floor N.pdf      legacy flat layout — still supported
├── <BuildingName> floor N.dwg
└── Brick_v1.4.ttl                  shared schemas — auto-uploaded once
    Brick+extensions.ttl
```

## Override resolution

| Concern | Resolution order (later wins) |
|---------|--------------------------------|
| Intents | `orchestrator/intents/intent_definitions.yaml` (shipped) → `input/intents.yaml` → `input/<bldg>/intents.yaml` |
| Personas | `shared/persona_registry._REGISTRY` (shipped) → `input/personas/*.yaml` → `input/<bldg>/personas/*.yaml` |
| Building config | hardcoded defaults → `input/<bldg>/building.yaml` |
| Storage adapters | every entry in `config/database_registry.yaml` → filtered by `input/<bldg>/building.yaml: storage.databases` |
| Floor-plan registry key | derived from PDF filename slug → matched against `input/<bldg>/building.yaml: floor_plan_aliases` |

## How startup ingests the directory

1. **Config layer** (`shared/config.py`): reads `BUILDING_ID` env var and `config/building_config.yaml`.
2. **BuildingRegistry**: pre-scans `input/*/building.yaml` for declared buildings + aliases.
3. **AdapterRegistry**: loads `config/database_registry.yaml` filtered by the active building's `storage.databases`.
4. **TTL uploader**: SHA-256-cached upload of `input/*.ttl` and `input/<bldg>/*.ttl` to GraphDB.
5. **FloorPlanPipeline**: scans `input/*.pdf` and `input/*.dwg`, slugifies the building name, reconciles via aliases.
6. **CapabilityIndexer**: embeds `input/<bldg>/capability.yaml` into Qdrant `capability_<bldg>` collection.
7. **IntentRegistry**: merges shipped + global + per-building intent definitions, exposes to dialogue agent.
8. **PersonaRegistry**: merges shipped + global + per-building persona priors.

## What's NOT yet config-driven

These still require Python changes:

- New storage adapter type (e.g. Cassandra) — implement `DatabaseAdapter` protocol
- New agent class (e.g. an HVAC scheduler) — write a Python module
- Workflow node wiring — `workflow.py` still has imperative if/elif routing (Phase 6D deferred)
- Typed pipeline state — `intermediate_results` is still a dict (Phase 7 deferred)
