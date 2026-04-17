---
name: sparql-for-brick
description: Use when developing a new SPARQL query for the OntoSage building graph — covers the full cycle: discover what classes/properties exist, draft a correct query, validate it against the live GraphDB, interpret empty results, and wire the result into the agent prompt. Do NOT use for debugging a broken query (use ontosage-debug.md instead).
---

# SPARQL Query Development Runbook — OntoSage Brick Graph

You are building a new SPARQL query against the live Brick/ASHRAE 223/BACnet ontology graph in GraphDB. Follow every step in order. Do not skip a step because it "looks right".

---

## Phase 1 — Discover What Exists in the Live Graph

Before writing a single triple pattern, find out what is actually in *this* building's graph. The classes and instance URIs differ per building.

### 1a. Discover all classes present (and instance counts)

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d '
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT DISTINCT ?class (COUNT(?inst) AS ?count) WHERE {
  ?inst a ?class .
  FILTER(STRSTARTS(STR(?class), "https://brickschema.org/") ||
         STRSTARTS(STR(?class), "http://data.ashrae.org/"))
} GROUP BY ?class ORDER BY DESC(?count) LIMIT 40
' | python -m json.tool
```

**Read the output.** Note the exact class URIs — e.g. `brick:Air_Temperature_Sensor`, `brick:CO2_Sensor`, `brick:HVAC_Zone`. Use these exact strings in your query.

### 1b. Discover available relationships for a class

Replace `brick:Air_Temperature_Sensor` with whichever class you need:

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d '
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?predicate (SAMPLE(?obj) AS ?example) WHERE {
  ?s a brick:Air_Temperature_Sensor .
  ?s ?predicate ?obj .
} GROUP BY ?predicate LIMIT 30
' | python -m json.tool
```

**What to look for:**
- `brick:hasLocation` — links sensor → zone/room/floor
- `brick:isPartOf` — structural containment
- `ashrae:hasExternalReference` / `ref:hasExternalReference` — timeseries UUID bridge
- `ref:hasTimeseriesId` — the UUID needed for SQL queries
- `ref:storedAt` — database backend for the UUID
- `rdfs:label` — human-readable name

### 1c. Discover the timeseries reference path for a specific sensor

This is the most important discovery — you must know the exact predicate chain to reach a UUID:

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d '
PREFIX ashrae: <http://data.ashrae.org/standard223#>
PREFIX ref:    <https://brickschema.org/schema/Brick/ref#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?sensor ?label ?uuid ?storage WHERE {
  ?sensor ashrae:hasExternalReference ?extRef .
  ?extRef ref:hasTimeseriesId ?uuid ;
          ref:storedAt ?storage .
  OPTIONAL { ?sensor rdfs:label ?label }
} LIMIT 10
' | python -m json.tool
```

**Gate:** If this returns results, the `ashrae:hasExternalReference` path is the correct one for *this* graph. If empty, try `ref:hasExternalReference` directly instead — the predicate varies by building TTL version.

---

## Phase 2 — Draft the Query Incrementally

**Rule: Start narrow, then broaden. Never write a complex query in one shot.**

### Step 1: Verify the entity exists

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?sensor WHERE {
  ?sensor a brick:Air_Temperature_Sensor .
} LIMIT 5
```

If this returns 0 rows → the class name is wrong. Go back to Phase 1a.

### Step 2: Add one property at a time

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?sensor ?label WHERE {
  ?sensor a brick:Air_Temperature_Sensor .
  OPTIONAL { ?sensor rdfs:label ?label }
} LIMIT 10
```

### Step 3: Add location join

```sparql
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?sensor ?label ?zone WHERE {
  ?sensor a brick:Air_Temperature_Sensor .
  OPTIONAL { ?sensor rdfs:label ?label }
  OPTIONAL { ?sensor brick:hasLocation ?zone }
} LIMIT 10
```

### Step 4: Add the UUID bridge (always OPTIONAL — not all sensors have a timeseries)

```sparql
PREFIX brick:  <https://brickschema.org/schema/Brick#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ashrae: <http://data.ashrae.org/standard223#>
PREFIX ref:    <https://brickschema.org/schema/Brick/ref#>
SELECT ?sensor ?label ?zone ?uuid ?storage WHERE {
  ?sensor a brick:Air_Temperature_Sensor .
  OPTIONAL { ?sensor rdfs:label ?label }
  OPTIONAL { ?sensor brick:hasLocation ?zone }
  OPTIONAL {
    ?sensor ashrae:hasExternalReference ?extRef .
    ?extRef ref:hasTimeseriesId ?uuid .
    ?extRef ref:storedAt ?storage .
  }
} LIMIT 20
```

---

## Phase 3 — Validate Against the Live GraphDB

### 3a. Execute via curl (the ground truth)

```bash
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d '<paste your SPARQL here>' | python -m json.tool
```

### 3b. Interpret the result

| Situation | What it means | Fix |
|-----------|--------------|-----|
| `"bindings": []` | Query is valid but matches nothing | Go back to Phase 1 — the class/property names are wrong |
| HTTP 400 | Syntax error | Run through `sparql_validator.py` (see below) |
| `"bindings"` has rows but no `uuid` | Sensor exists but has no timeseries | Cannot do SQL data query for this sensor |
| Results look right | ✅ proceed | Phase 4 |

### 3c. Validate syntax via OntoSage validator

```python
# Run inside the orchestrator container
from orchestrator.services.sparql_validator import sparql_validator
import asyncio

query = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
SELECT ?s WHERE { ?s a brick:Air_Temperature_Sensor } LIMIT 5
"""
asyncio.run(sparql_validator.validate_and_execute(query, executor=None, use_cache=False))
```

---

## Phase 4 — Diagnosing Empty Results

Go through this in order:

1. **Did Phase 1a show any instances of your class?** If `COUNT = 0` → the class does not exist in this graph. Use the closest alternative from the discovery output.

2. **Is the predicate correct?** Run Phase 1b for the actual class. Don't assume `brick:hasLocation` — it could be `brick:isPointOf`, `rec:containsElement`, or `s223:contains`.

3. **Is the UUID path correct?** Run Phase 1c. The predicate is either `ashrae:hasExternalReference` (newer TTLs) or `ref:hasExternalReference` (older TTLs). Never assume one.

4. **Is the data loaded at all?**
   ```bash
   curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
     -H "Content-Type: application/sparql-query" \
     -H "Accept: application/sparql-results+json" \
     -d 'SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }' | python -m json.tool
   ```
   If `n = 0` → data not loaded. Run: `python scripts/onboard_building.py --building-id bldg1`

5. **Is GraphDB reachable?**
   ```bash
   curl http://localhost:7200/rest/repositories
   ```

6. **SPARQL fallback to RAG**: `sparql_agent.py:285` automatically falls back to semantic RAG when results are empty. If the app gives a reasonable answer but GraphDB returns 0 rows, the RAG fallback has fired — data is missing, not the query.

---

## Phase 5 — Wire the Query into the Agent Prompt

Once the query works in GraphDB, decide where to place it:

### Option A: Add as a template in `sparql_agent.py`

File: `orchestrator/agents/sparql_agent.py:691` — `_template_sparql()`

Add a branch for deterministic queries (avoids LLM cost):

```python
# Example: find all CO2 sensors
if 'co2' in uq and ('sensor' in uq or 'list' in uq):
    return self._prefix_block() + """
SELECT ?sensor ?label ?uuid ?storage WHERE {
  ?sensor a brick:CO2_Sensor .
  OPTIONAL { ?sensor rdfs:label ?label }
  OPTIONAL {
    ?sensor ashrae:hasExternalReference ?extRef .
    ?extRef ref:hasTimeseriesId ?uuid .
    ?extRef ref:storedAt ?storage .
  }
} LIMIT 50"""
```

**When to use:** Only for queries that always return the same pattern. E.g. "list all X sensors in zone Y".

### Option B: Add as a few-shot example in `few_shot_library.json`

File: `orchestrator/data/few_shot_library.json`

Add an entry in the format `"persona|intent"`:

```json
"general|metadata": [
  {
    "q": "What CO2 sensors are in zone 5?",
    "a": "{\"intent\":\"metadata\",\"entities\":[\"Zone_5\"],\"required_analytics\":[]}"
  }
]
```

**When to use:** When you want the LLM to learn the correct intent/entity for a certain phrasing — not the SPARQL itself.

### Option C: Add to the SPARQL prompt context in `_generate_sparql()`

File: `orchestrator/agents/sparql_agent.py:430`

Add a mapping note in the `=== SPARQL GENERATION RULES ===` block in the prompt to guide the LLM:

```
- "CO2 sensor" → brick:CO2_Sensor (confirmed in this graph)
- "zone 5" → filter CONTAINS(STR(?zone), "Zone_5")
```

---

## Prefix Reference

These prefixes are pre-declared in `sparql_agent.py:44-72` (`_STANDARD_PREFIXES`):

| Prefix | URI |
|--------|-----|
| `brick:` | `https://brickschema.org/schema/Brick#` |
| `ref:` | `https://brickschema.org/schema/Brick/ref#` |
| `ashrae:` / `s223:` | `http://data.ashrae.org/standard223#` |
| `bacnet:` | `http://data.ashrae.org/bacnet/2020#` |
| `rdfs:` | `http://www.w3.org/2000/01/rdf-schema#` |
| `rdf:` | `http://www.w3.org/1999/02/22-rdf-syntax-ns#` |
| `xsd:` | `http://www.w3.org/2001/XMLSchema#` |
| `bldg:` | Read from `settings.BUILDING_NAMESPACE` (building-specific) |

**Always call `self._prefix_block()`** when building a template query — it injects `bldg:` with the correct namespace for the loaded building.

---

## Golden Rules

1. **Never write a query without running Phase 1 first.** Class names differ per building.
2. **Always use `OPTIONAL` for the UUID bridge.** Not all entities have timeseries.
3. **Always use `LIMIT`.** The Abacws graph has 10,000+ triples — unbounded queries will time out.
4. **Test with curl, not the app.** The app adds caching, fallbacks, and agents — curl gives the raw truth.
5. **Do not interpolate user text into SPARQL.** All entity binding comes from `_extract_entities()` or LLM-gen, never directly from user input.
