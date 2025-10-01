# Synthetic Building 2 (bldg3)

This folder contains a synthetic building configuration used to validate OntoBot’s multi‑building workflow. It mirrors the Abacws pattern but uses Cassandra for telemetry storage and focuses on Brick 1.4 TTLs created with Protégé/Brickly and Python brickschema utilities.

> Purpose: Provide a reproducible synthetic building bundle (ontology + datasets + notes) backed by Cassandra.

## What lives here

- Brick 1.4 ontology files (TTL) for the synthetic building
- Sensor lists and UUID mappings for this building
- Example datasets and notebooks/scripts used to construct and validate the TTL
- Rasa training artifacts derived from the building’s canonical sensor names

## Data ingestion and storage (Cassandra)

- Source: Synthetic telemetry representing sensors/devices
- Storage: Telemetry is stored in Cassandra tables designed for timeseries queries
- Normalization: Partitions/primary keys include a stable sensor UUID aligned with the Brick TTL; clustering keys support time‑range queries

## Knowledge base (Brick 1.4 TTL)

- TTLs are authored using:
  - Protégé and/or the Brickly package for interactive modeling
  - Python brickschema/rdflib for scripted generation/validation
- Reference: Brick 1.4 vocabulary → https://ontology.brickschema.org/
- Deployment: Load TTLs into Apache Jena Fuseki and expose a dataset for SPARQL queries

## Rasa model and NLU

- Canonical sensor names (from TTL) are used to train intents/entities in Rasa
- Actions perform SPARQL lookups to resolve entities and retrieve timeseries UUIDs
- Analytics payloads are built with units and UK guidelines when applicable

## SPARQL usage

- SPARQL queries resolve building metadata (spaces, equipment, sensors) and back references for timeseries
- Fuseki endpoints are shared across buildings; swap the dataset to target bldg3

## Typical workflow

1) Build/refresh the Brick 1.4 TTL with Protégé/Brickly or Python scripts
2) Load it into Fuseki and validate basic queries
3) Ensure Cassandra contains the synthetic telemetry keyed by the UUIDs referenced in TTL
4) Train the Rasa model with the canonical names
5) Ask questions; Actions resolve entities via SPARQL and run analytics against Cassandra

## Notes

- Large raw datasets are not versioned; prefer small samples or external storage/LFS
- Jupyter checkpoints remain ignored; commit only curated notebooks
- Keep building‑specific mappings unique to avoid cross‑building collisions

## References

- Brick Schema 1.4: https://ontology.brickschema.org/
- Apache Jena Fuseki: https://jena.apache.org/documentation/fuseki2/
- Rasa: https://rasa.com/docs/rasa/
- Apache Cassandra: https://cassandra.apache.org/doc/latest/

## See also

- Root `README.md` for stack and quick start
- `bldg1/README.md` for the Abacws example (PostgreSQL/ThingsBoard)
- `bldg2/README.md` for the MySQL synthetic variant
