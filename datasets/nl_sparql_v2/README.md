# NL→SPARQL Dataset v2

Action Plan Refs: #6 (Dataset Extension), #17 (Release Packaging)

## Goals
- Add building-agnostic paraphrases
- Include reasoning-dependent queries (multi-hop location inference, property chains)
- Introduce advanced SPARQL operators: GROUP BY, HAVING, FILTER EXISTS, OPTIONAL, COALESCE
- Negative controls (nonexistent sensor types / classes)

## File Inventory (planned)
| File | Purpose |
|------|---------|
| `train.jsonl` | Training pairs (NL, SPARQL, metadata) |
| `dev.jsonl` | Development/validation split |
| `test_reasoning.jsonl` | Queries requiring reasoning for correct bindings |
| `STATS.md` | Distribution metrics (operator frequency, token lengths) |
| `GENERATION_METHOD.md` | Prompt templates & filtering criteria |

## JSONL Record Schema
```jsonc
{
  "id": "q_000123",
  "nl": "List all rooms on Floor 3 with both temperature and humidity sensors",
  "sparql": "PREFIX brick: <https://brickschema.org/schema/Brick#> ...",
  "operators": ["GROUP_BY", "FILTER_EXISTS"],
  "requires_reasoning": true,
  "building_agnostic": true,
  "neg_control": false
}
```

## Planned Metadata Aggregates
- Total samples per split
- % requiring reasoning
- Operator frequency table
- Distinct Brick classes referenced

## Roadmap
1. Scaffold (this commit)
2. Add generator script under `scripts/augment_dataset_v2.py`
3. Populate initial reasoning subset
4. Compute statistics → write `STATS.md`
5. Release packaging with license (CC-BY 4.0)

## License (Planned)
Creative Commons Attribution 4.0 International (CC-BY 4.0)
