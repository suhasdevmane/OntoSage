# Data-Quality Report — complexity_master_table.csv

Rows: **6157**  |  Invariants checked: 8  |  Total violating rows: **40** (0.65%)

| Invariant | Violations |
|---|---|
| Duplicate qid (same question twice) | 40 |
| `level` outside 1-6 | 0 |
| `latent_level` outside 1-6 | 0 |
| `level_name` does not match `level` | 0 |
| `latent_level_name` mismatch | 0 |
| general-knowledge but latent_level != 1 | 0 (of 779 GK rows) |
| general-knowledge but contains [NEW] | 0 |
| general-knowledge but answerability != full | 0 |
| requires_extension but NO [NEW] item | 0 |
| answerability=full but HAS [NEW] item | 0 |
| Empty required fields | {'architecture': 0, 'pipeline_stages': 0, 'data_sources': 0, 'answerability': 0} |
