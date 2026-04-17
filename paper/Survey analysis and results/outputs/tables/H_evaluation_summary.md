# H-Phase: OntoSage Evaluation Summary

**N** = 5,916 questions drawn from the pre-development survey corpus (81 participants, Phases A–G classified)

## Headline Metrics

| Metric | Value | 95% CI |
|--------|-------|--------|
| Answer rate (Grounded + Informational) | 63.9% | [62.7–65.1%] |
| Data-grounded rate | 20.0% | [19.0–21.0%] |
| Disambiguation rate | 26.7% | — |
| Graceful refusal rate | 8.3% | — |
| Timeout/failure rate | 1.1% | — |
| Median latency | 5.33 s | — |
| P90 latency | 15.03 s | — |

## Outcome Definitions

- **GROUNDED** — response includes specific building data (sensor readings, tables, measured values)
- **INFORMATIONAL** — general domain knowledge without specific building data
- **DISAMBIGUATION** — system requested clarification with numbered options
- **BOUNDARY** — graceful refusal: data not available or out of scope
- **FAILED** — timeout (60 s limit) or empty response

## Output Files

| File | Description |
|------|-------------|
| H1_overall_metrics.csv | Overall outcome counts and rates |
| H2_answer_rate_by_domain.csv | Domain-level answer rates with CI |
| H3_answer_rate_by_query_type.csv | Query-type answer rates |
| H4_answer_rate_by_complexity.csv | L1/L2/L3 complexity analysis |
| H5_answer_rate_by_stage.csv | Stage S1–S4 answer rates |
| H6_latency_by_outcome.csv | Latency statistics by outcome |
| H7_domain_complexity_heatmap.csv | Domain × Complexity matrix |
| H8_domain_stage_heatmap.csv | Domain × Stage matrix |
| H9_answer_rate_by_role.csv | Role-based answer rates |
| H10_statistical_tests.csv | All statistical tests with effect sizes |
| H11_answer_rate_by_intent.csv | Intent-type answer rates |

| Figure | Description |
|--------|-------------|
| H1_outcome_distribution | Stacked proportion bar |
| H2_answer_rate_by_domain | Grouped horizontal bar |
| H3_outcome_by_query_type | Stacked bar by query type |
| H4_outcome_by_complexity | Stacked bar + latency overlay |
| H5_answer_rate_by_stage | Line plot with CI ribbon |
| H6_latency_analysis | Box plot + CDF |
| H7_domain_complexity_heatmap | Heatmap with annotations |
| H8_domain_stage_heatmap | Heatmap with annotations |
| H9_answer_rate_by_role | Horizontal bar with CI |
| H12_coverage_bubble | Coverage scatter |