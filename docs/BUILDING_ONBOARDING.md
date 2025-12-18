# Building Onboarding Guide (TTL)

This guide explains how to load your own building ontology (Turtle `.ttl`) and start chatting with the system.

## 1) Prepare Your Ontology
Your ontology should include:
- Sites, Buildings, Floors, Rooms (locations)
- Equipment (HVAC, Lighting, Meters)
- Points/Sensors and relationships (`isLocationOf`, `hasPoint`, `feeds`)
- Prefer Brick schema alignment where possible

## 2) Place Files
```
mkdir -p data/my_building/dataset
cp /path/to/your/building.ttl data/my_building/dataset/
```

## 3) Configure GraphDB Import
Edit `docker-compose.agentic.yml` and update GraphDB volume mapping:
```yaml
  graphdb:
    volumes:
      - ./volumes/graphdb:/opt/graphdb/home
      - ./data/my_building/dataset:/opt/graphdb/import:ro
```

Restart GraphDB:
```bash
docker-compose -f docker-compose.agentic.yml restart graphdb
```

If the repository is empty, GraphDB will import from `/opt/graphdb/import` on first run. Otherwise, use the GraphDB Workbench to import your TTL.

## 4) (Optional) Initialize RAG Indexes
If you want RAG over descriptions and metadata:
```bash
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.init_qdrant
# Ingest ontology text
docker-compose -f docker-compose.agentic.yml run --rm rag-service python -m scripts.ingest_ontology --source /staging
```

## 5) Map Sensors to Time-Series (SQL)
Ensure your sensor identifiers match those used in the MySQL time-series database. Provide a mapping file or follow the existing naming convention (UUIDs).

## 6) Validate with Sample Queries
- Structural:
```sparql
SELECT ?sensor WHERE { ?sensor a brick:Temperature_Sensor }
```
- Time-Series:
"Average temperature for Room 101 last week"
- Analytics:
"Plot weekly average humidity for Floor 2 over 90 days"

## 7) Troubleshooting
- Graph not updated: clear GraphDB repository and re-import
- Missing sensors: verify class IRIs and prefixes
- SQL agent returns empty: verify sensor UUID mapping and date range
