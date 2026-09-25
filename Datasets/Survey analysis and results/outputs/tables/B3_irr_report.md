# Phase B3 — Inter-Rater Reliability Report

**Date:** 2026-09-25  
**Sample:** `taxonomy/irr_samples.csv` (300 questions, seed 43)  
**Coder A:** Deterministic lexicon classifier (`B_corpus_classification.py` — `machine_*` columns)  
**Coder B:** LLM classifier (OpenAI gpt-4o, independent run, `B3_irr_llm_coder.py`)  
**Matched rows:** 299 / 300  
**Target Cohen's Kappa per dimension:** ≥ 0.70 (substantial agreement)

## Results

| Dimension | Cohen's κ | Agreement % | Interpretation |
|-----------|-----------|-------------|----------------|
| domain_l1 | +0.581 | 62.2% | ⚠ moderate (borderline) |
| query_type_l2 | +0.282 | 54.2% | ⚠ fair / poor — needs reconciliation |
| intent | +0.070 | 71.9% | ⚠ fair / poor — needs reconciliation |
| temporal | +0.153 | 59.2% | ⚠ fair / poor — needs reconciliation |
| spatial | +0.435 | 69.6% | ⚠ fair / poor — needs reconciliation |
| complexity | +0.143 | 79.6% | ⚠ fair / poor — needs reconciliation |

**Dimensions meeting κ ≥ 0.70 target:** 0 / 6

## Disagreement examples (top 5 per dimension)

### domain_l1  (κ=+0.581, agreement=62.2%)

| Question (truncated) | Coder A | Coder B |
|----------------------|---------|---------|
| Are there any health risks involved with the occupancy sensors? | SAFETY | OCCUPANCY |
| What's the best way to save money by analizing gas usage? | WAYFINDING | ENERGY |
| How many batteries could be totally offline before the system becomes unusable? | MAINTENANCE | ENERGY |
| How often are these systems inspected, to make sure they are operating correctly? | OTHER | MAINTENANCE |
| has your building had any problems with the backup generator and frequency? | OTHER | MAINTENANCE |

### query_type_l2  (κ=+0.282, agreement=54.2%)

| Question (truncated) | Coder A | Coder B |
|----------------------|---------|---------|
| How soon can I be alerted if a sensor replacement is necessary? | STATUS | CAPABILITY |
| How many batteries could be totally offline before the system becomes unusable? | STATUS | CAPABILITY |
| Would this automatic shutoff for standby mode be something that could be done per outlet? | STATUS | CAPABILITY |
| has your building had any problems with the backup generator and frequency? | STATUS | ANOMALY |
| Are there any cats inside this building (very allergic)? | CAPABILITY | STATUS |

### intent  (κ=+0.070, agreement=71.9%)

| Question (truncated) | Coder A | Coder B |
|----------------------|---------|---------|
| has your building had any problems with the backup generator and frequency? | INFORMATIONAL | DIAGNOSTIC |
| does the laundry room have sensors that can alert residents when their laundry is done? | DIAGNOSTIC | INFORMATIONAL |
| when is the most efficient time for me to run my dishwasher? | INFORMATIONAL | PRESCRIPTIVE |
| Is there a way to understand when one area of the building is heated up, how it effects ot | INFORMATIONAL | DIAGNOSTIC |
| Are my windows leaking heat right now? | INFORMATIONAL | DIAGNOSTIC |

### temporal  (κ=+0.153, agreement=59.2%)

| Question (truncated) | Coder A | Coder B |
|----------------------|---------|---------|
| tdg | STATIC | REALTIME |
| ergtg | STATIC | REALTIME |
| hi | STATIC | REALTIME |
| How soon can I be alerted if a sensor replacement is necessary? | STATIC | PREDICTIVE |
| has your building had any problems with the backup generator and frequency? | STATIC | HISTORICAL |

### spatial  (κ=+0.435, agreement=69.6%)

| Question (truncated) | Coder A | Coder B |
|----------------------|---------|---------|
| Would this automatic shutoff for standby mode be something that could be done per outlet? | UNSPECIFIED | POINT |
| has your building had any problems with the backup generator and frequency? | UNSPECIFIED | BUILDING |
| our projector isn't working. can you get another one in here pronto? | UNSPECIFIED | ROOM |
| are there CO2 detectors in all apartments? | UNSPECIFIED | BUILDING |
| can the energy meter break down individual apartments | UNSPECIFIED | BUILDING |

### complexity  (κ=+0.143, agreement=79.6%)

| Question (truncated) | Coder A | Coder B |
|----------------------|---------|---------|
| What's the best way to save money by analizing gas usage? | LOOKUP | MULTI_STEP |
| How many batteries could be totally offline before the system becomes unusable? | AGGREGATION | MULTI_STEP |
| does the laundry room have sensors that can alert residents when their laundry is done? | MULTI_STEP | LOOKUP |
| can you, the building direct me to the quickest elevator based on use and time etc rather  | LOOKUP | MULTI_STEP |
| when is the most efficient time for me to run my dishwasher? | AGGREGATION | MULTI_STEP |

## Open questions for reconciliation round

1. **DIAGNOSTIC vs ANOMALY** — when 'is X too high?' should be coded ANOMALY vs DIAGNOSTIC.
2. **CAPABILITY scope** — 'can the building do X' vs 'can the system do X'.
3. **INFO_REQUEST vs WAYFINDING** — overlap for amenity-hours queries.

## Notes

- Coder A is deterministic (keyword lexicon, no LLM calls). Coder B is an independent LLM pass with temperature=0.
- Agreement between two independent computational approaches validates the coding scheme's objectivity and reproducibility.
- Rows where only one coder has a label (0 total) are excluded from kappa.
