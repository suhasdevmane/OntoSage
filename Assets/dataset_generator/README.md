# Brick NL→SPARQL Dataset Generator

This tool reads A-Box TTL snippets (Brick-modeled individuals) and emits a dataset of (question, entity, sparql) pairs as a JSON array to the `Assets/` folder.

Key properties:
- Generates Type A (metadata) and Type B (timeseries id retrieval) queries.
- Uses SPARQL 1.1 features including aggregates when appropriate (COUNT/AVG/MIN/MAX/SUM, GROUP BY, HAVING, FILTER EXISTS).
- Does not include PREFIX declarations in the generated SPARQL per spec.
- Targets individuals in the `bldg:` namespace and assumes `brick:hasLocation`, `ref:hasExternalReference`, `ref:TimeseriesReference`, `ref:hasTimeseriesId`, and `ref:storedAt` when present.

Usage (example):
1. Place your TTL snippet in `Assets/snippets/example.ttl`.
2. Run the generator pointing at the snippet and desired output file.

Outputs will be written as a single JSON array to `Assets/<name>.json`.

Limitations/Assumptions:
- The generator infers candidate questions from discovered triples and known Brick/REF patterns. Provide realistic labels/locations to improve NL quality.
- Timeseries references are emitted only if `ref:TimeseriesReference` triples exist for an entity.
