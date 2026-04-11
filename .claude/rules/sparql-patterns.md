# SPARQL Query Patterns — OntoSage

These patterns apply when writing or reviewing SPARQL queries for the OntoSage building knowledge graph (Brick Schema / BACnet / RDF).

## Always Include These Prefixes

```sparql
PREFIX rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:    <http://www.w3.org/2002/07/owl#>
PREFIX brick:  <https://brickschema.org/schema/Brick#>
PREFIX bacnet: <http://data.ashrae.org/bacnet/#>
PREFIX xsd:    <http://www.w3.org/2001/XMLSchema#>
PREFIX s223:   <http://data.ashrae.org/standard223#>
```

## Standard Patterns

### Discover sensors of a type

```sparql
SELECT ?sensor ?label WHERE {
    ?sensor a brick:Temperature_Sensor .
    OPTIONAL { ?sensor rdfs:label ?label }
} LIMIT 50
```

### Find sensors in a zone or room

```sparql
SELECT ?sensor ?zone ?label WHERE {
    ?sensor a brick:Temperature_Sensor .
    ?sensor brick:isPartOf ?zone .
    ?zone a brick:HVAC_Zone .
    OPTIONAL { ?sensor rdfs:label ?label }
} LIMIT 50
```

### Get UUID for time-series database lookup

```sparql
SELECT ?uuid WHERE {
    ?sensor rdfs:label "Zone 3 Temperature" .
    ?sensor brick:hasExternalReference ?ref .
    ?ref brick:hasTimeseriesId ?uuid .
} LIMIT 1
```

### Discover all available sensor classes

```sparql
SELECT DISTINCT ?class (COUNT(?inst) as ?count) WHERE {
    ?inst a ?class .
    FILTER(STRSTARTS(STR(?class), "https://brickschema.org/"))
} GROUP BY ?class ORDER BY DESC(?count) LIMIT 30
```

### Find all equipment in a building

```sparql
SELECT ?equip ?type ?label WHERE {
    ?equip a ?type .
    ?type rdfs:subClassOf* brick:Equipment .
    OPTIONAL { ?equip rdfs:label ?label }
} LIMIT 100
```

### Relationship traversal (hasPart hierarchy)

```sparql
SELECT ?floor ?room ?sensor WHERE {
    ?building a brick:Building .
    ?building brick:hasPart ?floor .
    ?floor a brick:Floor .
    ?floor brick:hasPart ?room .
    ?room a brick:Room .
    ?room brick:hasPart ?sensor .
    ?sensor a brick:Temperature_Sensor .
} LIMIT 50
```

## Rules

- **Always use LIMIT** — never unbounded queries against a large graph (can return 10k+ results)
- **Use OPTIONAL** for properties that may not exist on all instances
- **Prefer `rdfs:label`** over URI parsing for human-readable names
- **Fall back to RAG** when SPARQL returns empty results — `services/hybrid_retrieval.py` handles this automatically
- **Validate before executing** — `services/sparql_validator.py` checks syntax
- **Never interpolate user input** directly into SPARQL strings — the LLM generates the query, users provide only natural language

## GraphDB Endpoint

```bash
# SPARQL Query (HTTP)
curl -s -X POST http://localhost:7200/repositories/ontosage/sparql \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT ?s WHERE { ?s a brick:Building } LIMIT 5"

# Health check
curl http://localhost:7200/rest/repositories

# Web UI
open http://localhost:7200
```

## Debugging Empty Results

1. Test directly against GraphDB (bypassing the agent) using the curl above
2. If empty: data not loaded — run `python scripts/onboard_building.py --building-id bldg1`
3. If syntax error: check prefixes — all must match exactly
4. If results exist in GraphDB but not in the app: check `_retrieve_context()` in `sparql_agent.py:313`
5. If RAG fallback triggered: check rag-service health at `http://localhost:8001/health`
