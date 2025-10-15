# Abacws Building (bldg1)

This folder contains the Abacws testbed building configuration used by OntoBot. It packages the building knowledge base (Brick TTL), example datasets and notebooks, and notes on how this building integrates with the wider OntoBot stack (Rasa, analytics, and SPARQL via Apache Jena Fuseki).

> Purpose: Provide a reproducible, building‑specific bundle (ontology + data hints + model notes) that the platform can use to answer questions and run analytics.

## What lives here

- Brick ontology files for Abacws (TTL files)
- Sensor IDs/UUID mappings and helper CSV/JSON artifacts
- Notebooks and small scripts used to construct/inspect the TTL and datasets
- Example query outputs (CSV/JSON) and derived artifacts

Note: bldg2 and bldg3 will host other buildings (synthetic or real) with their own TTLs, sensor lists, and trained Rasa models. The core OntoBot flow supports multiple buildings with different schemas, sensor deployments, and databases.

## Data ingestion and storage

- Source: Telemetry is collected from building sensors and ingested into ThingsBoard
- Storage: ThingsBoard writes telemetry into a database (historically PostgreSQL). Your deployment may use PostgreSQL (default in TB) or another store; OntoBot’s demo stack also includes a MySQL example.
- Normalization: We transform the raw, denormalized telemetry into a canonical shape keyed by stable UUIDs. These UUIDs are cross‑referenced with the Brick TTL so downstream components can use a consistent vocabulary.

## Knowledge base (Brick TTL)

- The Brick model for Abacws is authored as TTL files in this folder (and subfolders)
- TTL construction: Python notebooks/scripts (using the Brick/rdflib ecosystem) generate and validate the ontology for this building
- Deployment: The resulting TTL is loaded into Apache Jena Fuseki as a persistent dataset; SPARQL queries from OntoBot hit Fuseki to resolve entities (sensors, equipment, spaces, relationships)

Minimal workflow:
1) Author/refresh the Abacws TTL here
2) Load it into Fuseki (see root README for the Jena service)
3) Run SPARQL queries from Rasa actions to resolve sensors/relationships

## Rasa model and NLU

- Sensor lists and canonical names are derived from the TTL and curated lists in this folder
- The Rasa model (intents/entities/stories) is trained using these canonical names so user queries map to the correct building entities
- The Actions server uses the TTL‑derived mappings and SPARQL results to:
  - Canonicalize user sensor names/areas
  - Retrieve time‑series IDs (UUIDs) for analytics
  - Build standardized analytics payloads (units, UK thresholds, anomaly options)

## SPARQL usage

- OntoBot issues SPARQL queries against Fuseki to answer metadata questions and to find timeseries UUIDs before analytics
- Quick example (conceptual): list humidity sensors on Level 5

```
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX bf: <https://brickschema.org/schema/BrickFrame#>
SELECT ?sensor ?space WHERE {
  ?sensor a brick:Zone_Air_Humidity_Sensor .
  ?sensor bf:isPartOf ?space .
  ?space a brick:Floor ; brick:label "Level 5" .
}
LIMIT 50
```

## Multi‑building support

The repository is structured to support multiple buildings side‑by‑side:

- bldg1 (this folder): Abacws (real/testbed)
- bldg2, bldg3: synthetic or other buildings (placeholders you can fill)

Guidelines:
- Keep each building’s TTL, mappings, and example notebooks inside its own folder
- Ensure sensor name → UUID mappings are unique per building
- Use dataset‑specific connection details (DB host, DB name, credentials) as environment variables consumed by the Actions service and/or analytics
- When switching buildings, update the dataset loaded into Fuseki and the model/mappings exposed to Rasa

## Typical end‑to‑end flow

1) User asks a question (e.g., “Show humidity trends in Level 5 last week”)
2) Rasa detects intent/entities; Actions canonicalize names via SPARQL on the Abacws TTL
3) Relevant timeseries UUIDs are looked up; SQL access retrieves telemetry for those UUIDs
4) A standardized analytics payload is constructed and sent to the analytics service
5) Analytics returns unit‑aware results (with UK thresholds when applicable); any artifacts (plots/CSV) are saved and served by the file server

## Notes and cautions

- Very large raw datasets are intentionally not versioned here; see the repository .gitignore and use external storage or Git LFS if needed
- Jupyter checkpoints are ignored by default; commit only curated notebooks you want to share
- Validate each TTL update in Fuseki before training Rasa or running analytics

## References

- Brick Schema: https://brickschema.org/
- Apache Jena Fuseki: https://jena.apache.org/documentation/fuseki2/
- SPARQL 1.1 (W3C): https://www.w3.org/TR/sparql11-query/
- ThingsBoard: https://thingsboard.io/
- Rasa: https://rasa.com/docs/rasa/

## See also

- Root `README.md` for architecture, services, environment variables, and quick start
- `rasa-ui/actions/actions.py` for the building‑aware action logic and payload contracts
- `docker-compose.yml` for the Fuseki and supporting services used during development