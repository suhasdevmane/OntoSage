# Phase C — Stage comparison statistical tests

All tests are non-parametric. Effect sizes accompany every p-value.

## Question word count
- Kruskal-Wallis H = 185.453, p = 5.859e-40, epsilon^2 = 0.0259 (n = 7151)
- Per-stage means:
  - Stage 1: mean = 8.54, median = 8, n = 1904
  - Stage 2: mean = 10.03, median = 9, n = 2003
  - Stage 3: mean = 10.34, median = 10, n = 1705
  - Stage 4: mean = 10.48, median = 10, n = 1539

### Dunn's post-hoc (Bonferroni)

| group_a | group_b | z | p_raw | p_bonferroni | significant_05 |
| --- | --- | --- | --- | --- | --- |
| S1 | S2 | -9.254 | 0.0 | 0.0 | True |
| S1 | S3 | -11.761 | 0.0 | 0.0 | True |
| S1 | S4 | -11.172 | 0.0 | 0.0 | True |
| S2 | S3 | -2.911 | 0.0036 | 0.02159 | True |
| S2 | S4 | -2.559 | 0.01049 | 0.06294 | False |
| S3 | S4 | 0.261 | 0.79393 | 1.0 | False |

## Complexity rank (1=Lookup, 2=Aggregation, 3=Multi-step)
- Kruskal-Wallis H = 14.518, p = 0.002279, epsilon^2 = 0.0020

### Dunn's post-hoc (Bonferroni)

| group_a | group_b | z | p_raw | p_bonferroni | significant_05 |
| --- | --- | --- | --- | --- | --- |
| S1 | S2 | -1.429 | 0.15289 | 0.91733 | False |
| S1 | S3 | 0.616 | 0.53757 | 1.0 | False |
| S1 | S4 | 0.143 | 0.88597 | 1.0 | False |
| S2 | S3 | 2.012 | 0.04419 | 0.26514 | False |
| S2 | S4 | 1.495 | 0.13499 | 0.80993 | False |
| S3 | S4 | -0.445 | 0.65646 | 1.0 | False |

## Intent proportions across stages (Chi-squared)
- Chi^2(9) = 78.016, p = 4.001e-13, Cramer's V = 0.0603
- Contingency (counts):

| Stage | DIAGNOSTIC | INFORMATIONAL | PREDICTIVE | PRESCRIPTIVE |
| --- | --- | --- | --- | --- |
| 1 | 67 | 1755 | 16 | 66 |
| 2 | 115 | 1836 | 21 | 31 |
| 3 | 49 | 1590 | 15 | 51 |
| 4 | 49 | 1377 | 31 | 82 |

