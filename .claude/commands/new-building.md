# Onboard New Building to OntoSage

Building: $ARGUMENTS

Follow every step. Each has a verification gate — do not proceed past a failing gate.

## Step 1 — Validate TTL file

```bash
python -c "
import rdflib, sys
g = rdflib.Graph()
try:
    g.parse('input/$ARGUMENTS.ttl', format='turtle')
    print(f'Valid TTL: {len(g)} triples — OK')
except Exception as e:
    print(f'INVALID: {e}')
    sys.exit(1)
"
```

**Gate:** Must print `Valid TTL: NNNN triples — OK`. Fix TTL syntax errors before continuing.

Tip: If TTL parse fails, use `rapper -i turtle input/$ARGUMENTS.ttl 2>&1` for detailed error location.

## Step 2 — Run onboarding script

```bash
python scripts/onboard_building.py --building-id $ARGUMENTS --non-interactive
```

**Gate:** Script exits 0 with onboarding complete message. If it fails, check script logs for the specific upload error, then try the GraphDB web UI at `http://localhost:7200` for manual upload.

## Step 3 — Verify GraphDB loaded

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT (COUNT(*) as ?n) WHERE { ?s ?p ?o }" | python -m json.tool
```

**Gate:** `?n` value > 0.

## Step 4 — Detect ontology schema

```bash
python -c "
import asyncio, json
from orchestrator.services.ontology_detector import OntologySchemaDetector
d = OntologySchemaDetector()
r = asyncio.run(d.detect_from_graphdb('http://localhost:7200', 'ontosage'))
print(json.dumps(r.to_dict(), indent=2))
"
```

**Gate:** `class_count > 0` and `schema` identified (e.g. `brick`, `bacnet`, or `mixed`). If schema is `unknown`, the TTL may not use standard Brick prefixes — use the `ontology-agent` to investigate.

## Step 5 — Set building configuration

In `.env` (create from `.env.example` if missing):
```
BUILDING_ID=$ARGUMENTS
```

Restart orchestrator:
```bash
docker-compose up -d orchestrator
```

## Step 6 — Register storage adapter (if new DB backend)

File: `orchestrator/services/adapters/registry.py`

If this building uses a new database (not the default MySQL), add the building ID → adapter mapping. If reusing the existing MySQL or PostgreSQL, no change needed.

## Step 7 — End-to-end query test

```bash
# Test via HTTP (start stack first: docker-compose up -d)
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"What sensors are available?\", \"session_id\": \"onboard-$ARGUMENTS\"}" \
  | python -m json.tool
```

**Gate:** Response contains sensor types found in the TTL. If empty or error, check:
1. `docker-compose logs -f orchestrator` — look for startup errors
2. `curl http://localhost:8001/health` — rag-service must be running
3. GraphDB triple count from Step 3 — data must be loaded

## Step 8 — Run onboarding tests

```bash
pytest -m unit -x -q 2>&1 | tail -10
```

**Gate:** All unit tests pass (0 failed).
