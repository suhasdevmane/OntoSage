# Phase C — Stage comparison statistical tests

All tests are non-parametric. Effect sizes accompany every p-value.

## Question word count
- Kruskal-Wallis H = 51.132, p = 4.585e-11, epsilon^2 = 0.0086 (n = 5916)
- Per-stage means:
  - Stage 1: mean = 8.54, median = 8, n = 1595
  - Stage 2: mean = 9.64, median = 8, n = 1726
  - Stage 3: mean = 9.81, median = 9, n = 1388
  - Stage 4: mean = 10.40, median = 9, n = 1207

### Dunn's post-hoc (Bonferroni)

| group_a | group_b | z | p_raw | p_bonferroni | significant_05 |
| --- | --- | --- | --- | --- | --- |
| S1 | S2 | -4.381 | 1e-05 | 7e-05 | True |
| S1 | S3 | -4.967 | 0.0 | 0.0 | True |
| S1 | S4 | -6.765 | 0.0 | 0.0 | True |
| S2 | S3 | -0.836 | 0.40322 | 1.0 | False |
| S2 | S4 | -2.822 | 0.00477 | 0.0286 | True |
| S3 | S4 | -1.925 | 0.05423 | 0.32535 | False |

## Complexity rank (1=Lookup, 2=Aggregation, 3=Multi-step)
- Kruskal-Wallis H = 1.989, p = 0.5747, epsilon^2 = 0.0003

### Dunn's post-hoc (Bonferroni)

| group_a | group_b | z | p_raw | p_bonferroni | significant_05 |
| --- | --- | --- | --- | --- | --- |
| S1 | S2 | -0.344 | 0.73121 | 1.0 | False |
| S1 | S3 | 0.436 | 0.6626 | 1.0 | False |
| S1 | S4 | 0.111 | 0.91129 | 1.0 | False |
| S2 | S3 | 0.775 | 0.43824 | 1.0 | False |
| S2 | S4 | 0.431 | 0.66629 | 1.0 | False |
| S3 | S4 | -0.299 | 0.76497 | 1.0 | False |

## Intent proportions across stages (Chi-squared)
- Chi^2(9) = 37.037, p = 2.592e-05, Cramer's V = 0.0457
- Contingency (counts):

| Stage | DIAGNOSTIC | INFORMATIONAL | PREDICTIVE | PRESCRIPTIVE |
| --- | --- | --- | --- | --- |
| 1 | 62 | 1461 | 16 | 56 |
| 2 | 85 | 1604 | 16 | 21 |
| 3 | 46 | 1294 | 10 | 38 |
| 4 | 42 | 1099 | 22 | 44 |

