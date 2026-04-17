# GraphDB Setup Guide

GraphDB is the RDF triple store at the heart of OntoSage's knowledge layer. This guide covers creating a repository, loading ontologies, and — most importantly — creating the **text similarity index** that enables semantic search over your building's knowledge graph.

---

## Prerequisites

- OntoSage stack running: `docker compose up -d`
- GraphDB accessible at `http://localhost:7200`
- Building ontology file (`.ttl`) prepared (see [Building Onboarding](BUILDING_ONBOARDING.md))

---

## Step 1: Access the GraphDB Workbench

Open your browser and navigate to:

```
http://localhost:7200
```

The first time you open the Workbench, you will be prompted to agree to the licence (free edition is included). There is no login by default in the free edition.

---

## Step 2: Create a Repository

Before you can load data, you need to create a repository.

### Via the Workbench

1. Click **Setup** (gear icon in the left sidebar)
2. Click **Repositories**
3. Click **Create new repository**
4. Select **GraphDB Repository** (not RDF4J)
5. Fill in the form:
   - **Repository ID**: `ontosage` (must match `GRAPHDB_REPOSITORY` in your `.env`)
   - **Repository title**: `OntoSage Building Ontology` (human-readable label)
   - **Ruleset**: `rdfsplus-optimized` (recommended for Brick Schema reasoning)
6. Click **Create**

### Via the REST API

```bash
curl -X POST http://localhost:7200/rest/repositories \
  -H "Content-Type: application/json" \
  -d '{
    "id": "ontosage",
    "type": "graphdb",
    "title": "OntoSage Building Ontology",
    "params": {
      "ruleset": {
        "name": "ruleset",
        "value": "rdfsplus-optimized"
      },
      "storage-memory": {
        "name": "storage-memory",
        "value": "false"
      }
    }
  }'
```

Expected response: `HTTP 201 Created`

### Verify

```bash
curl -s http://localhost:7200/rest/repositories | python -m json.tool
```

You should see `"ontosage"` in the list.

---

## Step 3: Load Your Building Ontology

### Via the GraphDB Workbench

1. Select the `ontosage` repository from the dropdown in the top right
2. Navigate to **Import → RDF**
3. Click **Upload RDF files**
4. Select your building TTL file (e.g., `bldg1_protege.ttl`)
5. Click **Import** → Keep default settings → **Import**
6. Optionally, also import the Brick Schema TBox (`Brick.ttl`) for full reasoning

For large files (> 50 MB), use **Server files** import instead:

1. Copy the TTL into the GraphDB container:
   ```bash
   docker cp bldg1_protege.ttl graphdb:/opt/graphdb/home/userdata/imports/
   ```
2. In the Workbench: **Import → Server files** → select the file → **Import**

### Via the REST API

```bash
# Load ABox (building instances)
curl -X POST \
  "http://localhost:7200/repositories/ontosage/statements" \
  -H "Content-Type: text/turtle" \
  --data-binary @bldg1_protege.ttl

# Load TBox (Brick Schema vocabulary — optional but recommended)
curl -X POST \
  "http://localhost:7200/repositories/ontosage/statements" \
  -H "Content-Type: text/turtle" \
  --data-binary @data/Brick.ttl
```

### Verify the Load

```bash
# Count all triples
curl -s -X POST \
  "http://localhost:7200/repositories/ontosage/sparql" \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
```

Expected output shows the total triple count. A Brick-annotated building with 500+ sensors typically has 5,000–100,000+ triples.

```bash
# Count sensor instances
curl -s -X POST \
  "http://localhost:7200/repositories/ontosage/sparql" \
  -H "Content-Type: application/sparql-query" \
  -H "Accept: application/sparql-results+json" \
  -d "SELECT (COUNT(*) AS ?count) WHERE {
    ?s a ?type .
    FILTER(STRSTARTS(STR(?type), 'https://brickschema.org/'))
  }"
```

---

## Step 4: Create the Text Similarity Index

The similarity index is what enables OntoSage to answer questions like *"temperature sensors near the lobby"* without exact keyword matching. It creates a vector space over your ontology's entity labels, types, and names using **semantic vectors** backed by the GraphDB Similarity Plugin.

### Prerequisites

GraphDB's Similarity Plugin must be enabled. It is included in the free edition — no additional installation is required.

### Via the GraphDB Workbench

1. Ensure the `ontosage` repository is selected (top right dropdown)
2. Navigate to **Explore → Similarity**
3. Click **Create similarity index**
4. Click **Create text similarity index**
5. Fill in the form:

**Index Name:**
```
bldg_index
```
This must match `GRAPHDB_SIMILARITY_INDEX` in your `.env` file.

**Data Query (What to Index):**

Paste the following SPARQL query exactly:

```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX brick: <https://brickschema.org/schema/Brick#>

SELECT ?documentID ?documentText {
    ?documentID rdf:type ?type .
    FILTER(ISIRI(?documentID))

    OPTIONAL { ?documentID rdfs:label ?label }

    BIND(REPLACE(STR(?type), "^.*[#/]([^#/]+)$", "$1") as ?typeName)
    BIND(REPLACE(STR(?documentID), "^.*[#/]([^#/]+)$", "$1") as ?entityName)

    BIND(CONCAT(
        COALESCE(?label, ""), " ",
        COALESCE(?typeName, ""), " ",
        COALESCE(?entityName, "")
    ) as ?documentText)
}
```

This query generates a rich text document for each RDF resource by combining:
- The human-readable `rdfs:label` (if present)
- The local name of the entity's class (e.g., `Temperature_Sensor`)
- The local name of the entity itself (e.g., `sensor_001`)

6. Click **More options (show)** and set:

**Analyzer Class:**
```
org.apache.lucene.analysis.en.EnglishAnalyzer
```

**Stop words** (optional, reduces noise):
```
a,an,the,and,or,of,to,in,for,with
```

**Semantic Vectors create index parameters:**
```
-termweight idf -dimension 300 -minfrequency 2
```

These parameters control:
- `-termweight idf` — weight terms by inverse document frequency (more discriminative)
- `-dimension 300` — 300-dimensional semantic vectors (good balance of quality and speed)
- `-minfrequency 2` — ignore terms that appear only once (likely typos or unique IDs)

7. Click **Create**
8. The index will appear in the list with a spinning indicator while building
9. Wait for the build to complete — typically 1–10 minutes depending on ontology size

### Monitoring Index Build Progress

Watch the GraphDB logs:

```bash
docker compose logs -f graphdb | grep -E "similarity|bldg_index"
```

Or check the Workbench: **Explore → Similarity** — the spinning indicator stops when complete.

---

## Step 5: Verify the Similarity Index

### Test a Semantic Search via SPARQL

```sparql
PREFIX inst: <http://www.ontotext.com/graphdb/similarity/instance/>
PREFIX sim:  <http://www.ontotext.com/graphdb/similarity/>

SELECT ?entity ?score WHERE {
    ?search a inst:bldg_index ;
            sim:searchTerm "temperature sensor zone 5" ;
            sim:documentResult ?result .
    ?result sim:value ?entity ;
            sim:score ?score .
}
ORDER BY DESC(?score)
LIMIT 10
```

Expected: The top 10 RDF resources most semantically similar to "temperature sensor zone 5", ordered by relevance score. If results are empty, the index did not build correctly.

### Test via the RAG Service

```bash
curl -s -X POST http://localhost:8001/graphdb/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "query": "temperature sensors in Zone 5",
    "top_k": 5,
    "hops": 2
  }' | python -m json.tool
```

Expected: A JSON response with `entities`, `triples`, `prefixes`, and a `summary`. If this returns empty, check that `GRAPHDB_SIMILARITY_INDEX` in `.env` matches the index name exactly.

---

## Step 6: Configure the Environment

Ensure these variables are set in your `.env`:

```bash
GRAPHDB_HOST=graphdb                  # Docker service name
GRAPHDB_PORT=7200
GRAPHDB_REPOSITORY=ontosage           # Must match repository ID created in Step 2
GRAPHDB_SIMILARITY_INDEX=bldg_index   # Must match index name created in Step 4
```

Restart the orchestrator and RAG service to pick up the settings:

```bash
docker compose restart orchestrator rag-service
```

---

## Rebuilding the Index After Ontology Updates

After loading new data into GraphDB, rebuild the similarity index to include the new entities:

### Via SPARQL Update

```sparql
PREFIX similarity-index: <http://www.ontotext.com/graphdb/similarity/instance/>
PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/>

INSERT DATA {
    similarity-index:bldg_index similarity:rebuildIndex "" .
}
```

Execute this in the Workbench under **SPARQL → Update** tab, or via curl:

```bash
curl -X POST "http://localhost:7200/repositories/ontosage/statements" \
  -H "Content-Type: application/sparql-update" \
  -d 'PREFIX similarity-index: <http://www.ontotext.com/graphdb/similarity/instance/>
      PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/>
      INSERT DATA {
        similarity-index:bldg_index similarity:rebuildIndex "" .
      }'
```

### Full Recreate (if index is corrupted)

1. In the Workbench: **Explore → Similarity** → click the delete (trash) icon next to `bldg_index`
2. Recreate following Steps 4–5 above

---

## Multiple Buildings / Multiple Repositories

For each building, create a separate repository and similarity index:

| Building | Repository ID | Similarity Index |
|----------|--------------|-----------------|
| Building 1 | `ontosage` or `bldg1` | `bldg_index` or `bldg1_index` |
| Building 2 | `bldg2` | `bldg2_index` |
| Building 3 | `bldg3` | `bldg3_index` |

Update `.env` to point to the active building's repository:

```bash
GRAPHDB_REPOSITORY=bldg2
GRAPHDB_SIMILARITY_INDEX=bldg2_index
```

For true multi-building support with simultaneous queries, consider loading all buildings into a single repository using named graphs — each building gets its own named graph, and SPARQL queries can use `GRAPH <uri> { ... }` to scope queries.

---

## Memory and Performance

### JVM Heap Size

For large ontologies (> 500K triples), increase the GraphDB heap in `.env`:

```bash
GDB_HEAP_SIZE=8g     # Java heap (-Xms)
GDB_MAX_MEM=10g      # Max memory (-Xmx)
```

### Index Build Time

Approximate build times by ontology size:

| Triple Count | Estimated Build Time |
|-------------|---------------------|
| < 10,000 | < 30 seconds |
| 10,000 – 100,000 | 1–5 minutes |
| 100,000 – 500,000 | 5–20 minutes |
| > 500,000 | 20+ minutes |

### Similarity Dimension

The default `-dimension 300` produces high-quality vectors. If memory is constrained, reduce to `-dimension 100` (faster, slightly lower quality). If you need the highest precision for complex ontologies, increase to `-dimension 500`.

---

## Troubleshooting

### "Similarity plugin is not available"

The Similarity Plugin is disabled or not licensed. Check:
```bash
curl -s http://localhost:7200/rest/info | python -m json.tool
```

Look for `"plugins"` in the response. The free edition includes the plugin for repositories up to 10 million triples.

### "Index bldg_index not found"

The RAG service cannot find the index. Verify:
1. `GRAPHDB_SIMILARITY_INDEX=bldg_index` in `.env`
2. The index exists: check **Explore → Similarity** in the Workbench
3. The correct repository is selected: `GRAPHDB_REPOSITORY=ontosage`
4. Restart the RAG service: `docker compose restart rag-service`

### Similarity Search Returns Empty Results

1. Verify the data query returns results:
   ```bash
   # Run the index Data Query directly in the Workbench SPARQL tab
   ```
2. If the query returns results but the index is empty, the index may have failed to build silently — delete it and recreate
3. Check for `rdfs:label` annotations in your TTL — unlabelled entities are indexed by URI fragment only

### High Memory Usage During Indexing

The semantic vector indexing is memory-intensive. If GraphDB OOMs during index creation:
1. Increase `GDB_HEAP_SIZE` and `GDB_MAX_MEM`
2. Reduce `-dimension` parameter (e.g., 100 instead of 300)
3. Load ontology in smaller batches (split TTL file)
