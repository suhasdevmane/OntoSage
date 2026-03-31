# GraphDB Similarity Index Setup Guide

## Manual Index Creation via GraphDB Workbench

Since GraphDB's Similarity Plugin is designed to be configured via the Workbench UI, follow these steps to create the index for your `bldg` repository:

### Step 1: Access GraphDB Workbench
1. Open your browser and navigate to: `http://localhost:7200`
2. Select the `bldg` repository from the repository dropdown (top right)

### Step 2: Create Text Similarity Index
1. Navigate to **Explore** → **Similarity** → **Create similarity index**
2. Click **Create text similarity index**

### Step 3: Configure the Index

#### Index Name
```
bldg_index
```

#### Data Query (What to Index)
Paste this SPARQL query:
```sparql
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX brick: <https://brickschema.org/schema/Brick#>

SELECT ?documentID ?documentText {
    ?documentID rdf:type ?type .
    FILTER(ISIRI(?documentID))
    
    # Get Label (optional)
    OPTIONAL { ?documentID rdfs:label ?label }
    
    # Get Type Name (strip namespace)
    BIND(REPLACE(STR(?type), "^.*[#/]([^#/]+)$", "$1") as ?typeName)
    
    # Get Entity Name (strip namespace)
    BIND(REPLACE(STR(?documentID), "^.*[#/]([^#/]+)$", "$1") as ?entityName)
    
    # Combine into a rich document text
    BIND(CONCAT(
        COALESCE(?label, ""), " ", 
        COALESCE(?typeName, ""), " ", 
        COALESCE(?entityName, "")
    ) as ?documentText)
}
```

#### Advanced Settings (Click "more options")
1. **Analyzer Class**: `org.apache.lucene.analysis.en.EnglishAnalyzer`
2. **Stop Words**: `a,an,the,and,or,of,to,in`
3. **Semantic Vectors create index parameters**:
   ```
   -termweight idf -dimension 300 -minfrequency 2
   ```

### Step 4: Create the Index
1. Click the **Create** button
2. Wait for the index to build (may take several minutes for 93,237 triples)
3. You'll see a spinning icon next to `bldg_index` while it builds

### Step 5: Verify the Index
Once complete, `bldg_index` will appear in the "Existing Indexes" list with icons to:
- View SPARQL query
- Edit query
- Rebuild index
- Delete index

## Alternative: SPARQL-based Rebuild (if index already exists)

If you manually create the index via UI first, you can rebuild it via SPARQL:

```sparql
PREFIX similarity-index: <http://www.ontotext.com/graphdb/similarity/instance/>
PREFIX similarity: <http://www.ontotext.com/graphdb/similarity/>

INSERT DATA {
    similarity-index:bldg_index similarity:rebuildIndex "" .
}
```

## Testing the Index

Once the index is built, test it via SPARQL:

```sparql
PREFIX : <http://www.ontotext.com/graphdb/similarity/>
PREFIX inst: <http://www.ontotext.com/graphdb/similarity/instance/>

SELECT ?entity ?score WHERE {
    ?search a inst:bldg_index ;
           :searchTerm "temperature sensor" ;
           :documentResult ?result .
    ?result :value ?entity ;
           :score ?score .
}
ORDER BY DESC(?score)
LIMIT 10
```
