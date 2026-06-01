# `input/bldg2-example/` — How to add a new building

This directory shows the **complete** set of config files a new building
declares.  After Phases 1-8, dropping this kind of layout into `input/`
makes the system work for any building **with zero Python edits**.

## Activate this skeleton

1. Rename `bldg2-example/` → `bldg2/`
2. Drop your TTL files into `bldg2/*.ttl` (they auto-upload to GraphDB)
3. Drop floor plan PDFs at `bldg2/<your-pdf-prefix> floor N.pdf`
   (and DWG counterparts if you have them)
4. Set `BUILDING_ID=bldg2` in `.env`
5. `docker-compose restart orchestrator`

Done.  No Python edits required.

## File overview

```
input/bldg2/
├── README.md                    this file
├── building.yaml                identity, storage, zone regex, aliases
├── capability.yaml              building-specific KB (policies, amenities, contacts)
├── intents.yaml                 (optional) per-building intent overlay
├── *.ttl                        sensor ontology files (auto-uploaded)
├── *.pdf  *.dwg                 floor plan sources (auto-ingested)
├── personas/                    (optional) per-building persona overrides
│   ├── facility_manager.yaml   raises FIRE_SAFETY priority, tweaks thresholds
│   └── caretaker.yaml          building-specific caretaker domain priors
└── floor_plans/                 (optional) cached renders — auto-populated
```

## What each file controls

| File | Phase | Effect |
|------|-------|--------|
| `building.yaml: building_id` | 1 | Logical ID matched against `BUILDING_ID` env var |
| `building.yaml: storage.databases` | 2 | Which adapters to init (huge startup savings) |
| `*.ttl` | 3 | Auto-uploaded to GraphDB; SHA-256 skips unchanged files |
| `building.yaml: floor_plan_aliases` | 4 | Reconcile PDF slug ↔ logical ID |
| `building.yaml: zone_id_pattern` | 4 | Per-building zone ID regex (defaults to `\d+\.\d{2,3}`) |
| `personas/*.yaml` | 5 | Per-building persona priors/aliases |
| `capability.yaml` | 5 | Off-ontology Q&A (lifts, policies, contacts) |
| `intents.yaml` | 8 | Extend the LLM's intent taxonomy for this building |

## What still requires code work

Anything **outside** the `input/` directory:

- New storage adapter type (e.g. Cassandra) — must implement `DatabaseAdapter`
  protocol in `orchestrator/services/adapters/`
- New agent type (e.g. an HVAC scheduler agent) — needs a Python module
- LLM provider switch — set via `MODEL_PROVIDER` env var

For day-to-day onboarding of new buildings, only `input/` matters.
