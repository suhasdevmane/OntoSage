# Building Onboarding: The "Minimal Changes" Approach

**OntoSage** is designed to adapt to *your* building, not the other way around. This guide explains how to onboard a new building with **minimal changes** to your existing databases and ontologies.

## Philosophy: Zero-Knowledge Adaptation

Traditional systems require you to rewrite your data to fit their schema. OntoSage uses **Agentic AI** to understand your existing structure:
1.  **Ontology Ingestion**: It reads your RDF/Turtle files to learn your building's topology (Rooms, Assets, Sensors).
2.  **Schema Learning**: The RAG system indexes your specific class names (e.g., `brick:Temperature_Sensor` vs `rec:TempSensor`) so users can ask for "temperature" without knowing the underlying tag.
3.  **Dynamic Mapping**: It maps natural language concepts to your specific sensor UUIDs.

---

## Step-by-Step Onboarding

### 1. Prepare Your Ontology (No Rewrite Needed)
OntoSage supports any valid RDF format (Turtle `.ttl`, RDF/XML).
*   **Supported Schemas**: Brick, RealEstateCore (REC), Project Haystack (RDF), or custom proprietary ontologies.
*   **Requirement**: Ensure your sensors have unique identifiers (URIs) that can be linked to your time-series database.

### 2. Mount Your Data
Place your ontology file in the `data/` directory.
```bash
mkdir -p data/my_building/dataset
cp /path/to/your/building.ttl data/my_building/dataset/
```

### 3. Configure the System
Update `docker-compose.agentic.yml` to point to your data. You do **not** need to change the code.

```yaml
  graphdb:
    volumes:
      - ./volumes/graphdb:/opt/graphdb/home
      - ./data/my_building/dataset:/opt/graphdb/import:ro  # <--- Your file here
```

### 4. Ingest & Index (The "Learning" Phase)
Run the ingestion script. This process extracts metadata, relationships, and labels from your ontology and stores them in the Vector Database (Qdrant). This is how the system achieves "Zero-Knowledge" interaction.

```bash
# Initialize the Vector Index
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant

# Ingest and Learn Ontology Structure
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology --source /opt/graphdb/import
```

### 5. Connect Time-Series Data
OntoSage connects to your existing SQL database (MySQL/PostgreSQL).
*   **Configuration**: Set `MYSQL_HOST`, `MYSQL_USER`, etc., in `.env`.
*   **Mapping**: The system assumes the `sensor_id` in your SQL table matches the UUID or URI suffix in your ontology.
    *   *Example*: If Ontology URI is `http://example.org/bldg#sensor_123`, the SQL table should have `id='sensor_123'`.

### 6. Verification
Once onboarded, test the adaptation with natural language:

*   **Metadata Check**: "What kind of sensors are in the Conference Room?" (Tests if it learned the topology).
*   **Data Check**: "Show me the temperature for the last 24 hours." (Tests the SQL mapping).

## Advanced: Customizing the Mapping
If your database schema is highly non-standard (e.g., complex join tables), you can provide a `schema_map.json` to the SQL Agent, but for 95% of standard IoT schemas (Entity-Attribute-Value or Wide-Table), no configuration is needed.
