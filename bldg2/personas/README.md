# Persona configuration (Phase 5 — 2026-05-29)

YAML files in this directory **override or extend** the hardcoded persona
defaults baked into `shared/persona_registry.py`.

When this directory is empty, the system falls back to the 10-persona legacy
registry — the orchestrator continues to boot with identical behaviour.

## How to add or modify a persona

1. Create `<name>.yaml` in this directory.
2. Restart the orchestrator (or wait for the next process recycle).
3. Persona is now available via the `persona` field on API requests.

## YAML schema

```yaml
name: facility_manager        # MUST match the filename (without .yaml)
description: Free-form description of who this persona is

# Optional: alternative spellings that map to this persona
aliases:
  - facilities
  - facility manager
  - fm

# Top L1 domains (in priority order) — drives sensor selection ordering
top_domains:
  - ENERGY
  - THERMAL
  - OCCUPANCY
  - FIRE_SAFETY

# Fraction of queries that are LOOKUP rather than analytical (D3 stat)
lookup_share: 0.62

# Expected complexity: SIMPLE | MODERATE | COMPLEX
default_complexity: MODERATE

# 0=never ask for clarification, 1=always — tunes round-trip frequency
clarification_threshold: 0.5

# Topics ordered by Borda rank — used for retrieval prioritisation
borda_topics:
  - Energy
  - Temperature
  - Occupancy
  - Fire Safety
```

## Per-building overrides

Drop a file at `input/<BUILDING_ID>/personas/<name>.yaml` to override a global
persona for a specific building.  Per-building YAML wins over global YAML wins
over hardcoded defaults.

## What this replaces

Pre-Phase-5, adding a persona required editing three places:
1. The Literal type in `shared/models.py:236`
2. The `_REGISTRY` dict in `shared/persona_registry.py:50`
3. The `_ALIASES` dict in `shared/persona_registry.py:144`

After Phase 5, you only need this YAML file.
