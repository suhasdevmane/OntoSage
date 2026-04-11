---
name: ontosage-onboarding
description: Use when configuring a new building instance of OntoSage — covers TTL validation, GraphDB loading, ontology detection, adapter registration, and end-to-end query verification. Each step has a verification gate.
---

# OntoSage New Building Onboarding

You are configuring OntoSage for a new building. This is a complete, ordered process — every step has a verification gate that must pass before proceeding.

## Pre-conditions

- Docker stack is running: `docker-compose ps` (all services healthy)
- TTL file for the building is available in `input/`
- Building ID decided (e.g. `bldg2`, `office_a`, `hospital_north`)

## Step 1: Validate the TTL File

```bash
python -c "
import rdflib, sys
g = rdflib.Graph()
try:
    g.parse(sys.argv[1], format='turtle')
    print(f'Valid TTL: {len(g)} triples')
except Exception as e:
    print(f'INVALID: {e}')
    sys.exit(1)
" input/<BUILDING_ID>.ttl
```

**Gate:** Must print `Valid TTL: NNNN triples`. If it fails, use `rapper -i turtle input/<BUILDING_ID>.ttl 2>&1` for detailed error location. Fix all TTL syntax errors before proceeding.

## Step 2: Run Onboarding Script

```bash
python scripts/onboard_building.py --building-id <BUILDING_ID> --non-interactive
```

**Gate:** Script exits 0 with completion message. If it fails, check the script output for the specific upload error. For manual upload, use the GraphDB web UI at `http://localhost:7200`.

## Step 3: Verify GraphDB Loaded

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }" \
  | python -m json.tool
```

**Gate:** The `?n` value must be > 0.

## Step 4: Detect Ontology Schema

```bash
python -c "
import asyncio, json
from orchestrator.services.ontology_detector import OntologySchemaDetector
d = OntologySchemaDetector()
r = asyncio.run(d.detect_from_graphdb('http://localhost:7200', 'ontosage'))
print(json.dumps(r.to_dict(), indent=2))
"
```

**Gate:** `class_count > 0` and `schema` is identified (e.g. `brick`, `bacnet`, or `mixed`). If `schema` is `unknown`, the TTL may not use standard Brick/BACnet prefixes — use the `ontology-agent` to investigate.

## Step 5: Set Building Configuration

In `.env` (create from `.env.example` if it doesn't exist):

```bash
BUILDING_ID=<BUILDING_ID>
MODEL_PROVIDER=local    # or openai
```

Restart the orchestrator to pick up the new building ID:

```bash
docker-compose up -d orchestrator
```

## Step 6: Register Storage Adapter (if new DB backend)

File: `orchestrator/services/adapters/registry.py`

If this building uses a database not yet registered (e.g. a new PostgreSQL instance for Building 2), add the building ID → adapter mapping. If reusing the existing MySQL (Building 1) or default PostgreSQL, no change is needed.

## Step 7: End-to-End Query Test

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"What sensors are available in this building?\", \"session_id\": \"onboard-test-<BUILDING_ID>\"}" \
  | python -m json.tool
```

**Gate:** Response contains sensor types found in the TTL. If empty or error:
1. `docker-compose logs -f orchestrator` — look for startup errors
2. `curl http://localhost:8001/health` — rag-service must be running
3. Recheck Step 3 — GraphDB must have triples

## Step 8: Run Tests

```bash
pytest -m unit -x -q 2>&1 | tail -10
```

**Gate:** All unit tests pass (0 failed).

## Common Issues

| Symptom | Fix |
|---------|-----|
| TTL parse error | Use `rapper -i turtle input/file.ttl` for detailed error |
| GraphDB empty after script | Try manual upload via `http://localhost:7200` web UI |
| Schema `unknown` | TTL not using Brick/BACnet prefixes — check with ontology-agent |
| Response empty/error | Check `docker-compose logs -f orchestrator` |
| `BUILDING_ID` not recognized | Check `services/adapters/registry.py` mapping |
