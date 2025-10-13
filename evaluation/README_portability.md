# Portability Evaluation Harness (T0/T1/T2)

This harness runs the cross-building portability evaluation described in the paper and computes the Stage × Class metrics (SV, EX, EG, SI, MS).

It supports two modes:
- Dry-run (default): offline simulation using probe gold annotations
- Live: calls your running services (Rasa, T5 NL→SPARQL, Fuseki, Analytics)

## Files
- `evaluation/portability_harness.py` — main runner
- `evaluation/config/portability.buildingB.yaml` — example config for Building B
- `evaluation/config/alias_rules.sample.json` — sample T2 alias rules
- `evaluation/probes/sample_probes.json` — minimal probe suite (C1–C4)

## Quick start (dry-run)
Run the harness with the sample assets. This does not require any services to be running.

```pwsh
python evaluation/portability_harness.py `
  --config evaluation/config/portability.buildingB.yaml `
  --probes evaluation/probes/sample_probes.json `
  --stage ALL `
  --output-dir evaluation/portability_results `
  --export-latex --export-json
```

Outputs:
- `evaluation/portability_results/portability_metrics_aggregated.csv`
- `evaluation/portability_results/portability_metrics_all.csv`
- `evaluation/portability_results/portability_table.tex` (optional)
- `evaluation/portability_results/portability_logs.json` (optional)

## Live mode
Update `evaluation/config/portability.buildingB.yaml` with your endpoints and run with `--live`.

```pwsh
python evaluation/portability_harness.py `
  --config evaluation/config/portability.buildingB.yaml `
  --probes evaluation/probes/sample_probes.json `
  --stage ALL `
  --output-dir evaluation/portability_results `
  --live --export-latex --export-json
```

Notes:
- Rasa: `POST /model/parse` (text) should return entities
- T5 service: expects `POST { text } -> { sparql }`
- Fuseki: set dataset query URL (e.g., http://localhost:3030/ds/query)
- Analytics: set `analytics_base_url`; probes define `path`, `method`, `payload`

## How stages affect evaluation
- T0 (Zero-Shot): ontology ingestion only. No aliasing; entity extraction uses current NLU and lexicon fallback.
- T1 (+Entity Enrichment): regenerate NLU synonyms/lookups. In live mode, Rasa entities should improve; in dry-run, we simulate via lexicon matching.
- T2 (+Harness Repairs): applies alias rules to the question text prior to extraction to resolve remaining mismatches.

## Integrating with the manuscript table
Use `portability_metrics_aggregated.csv` to update Table `tab:portability-metrics` values. You can also directly include the generated `portability_table.tex` if desired.

## Extending the probe suite
Add more items to `evaluation/probes/*.json` with fields:
```json
{
  "id": "C2_010",
  "class": "C2",
  "question": "Which rooms contain PM10 sensors?",
  "gold": {
    "entities": ["pm10 sensor"],
    "sparql": "SELECT ?room WHERE { ?s a brick:PM10_Level_Sensor ; brick:hasLocation ?room . }",
    "result_nonempty": true,
    "si": true
  }
}
```

## Troubleshooting
- If YAML/JSON parsing errors occur, check file paths and syntax
- For live mode failures, verify service URLs and that CORS/firewall aren’t blocking
- EG F1 depends on `gold.entities` vs extracted entities; ensure consistent casing/spacing

## License
This harness is provided under the repository’s LICENSE.
