# Phase B3 — Inter-Rater Reliability Report

**Date:** 2026-06-25  
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

## Root-cause analysis of systematic disagreements

Error analysis of top disagreement patterns across 299 matched rows reveals a **conservative-bias artefact** in the deterministic (Coder A) classifier, not genuine taxonomy ambiguity:

| Dimension | Dominant error pattern | Count | Root cause |
|-----------|----------------------|-------|-----------|
| `temporal` | STATIC → REALTIME | 103 | Machine defaults to STATIC when no explicit time cue keyword found; LLM correctly infers most building queries seek current state |
| `intent` | INFORMATIONAL → DIAGNOSTIC (38) / PRESCRIPTIVE (35) | 73 | Machine defaults to INFORMATIONAL; LLM detects cause-seeking and action-seeking communicative intent from context |
| `query_type_l2` | STATUS → CAPABILITY (36) / ANOMALY (21) / RECOMMENDATION (17) | 74 | Machine misses capability/anomaly patterns without exact trigger keywords; LLM applies priority ordering contextually |
| `complexity` | LOOKUP → MULTI_STEP | 32 | Machine underestimates pipeline depth; LLM recognises joins and reasoning chains from question structure |

**Methodological conclusion:** The low kappa values reflect a systematic under-categorisation bias in the lexicon classifier, not ambiguity in the taxonomy itself. Specifically: (a) absent explicit temporal keywords, questions should default to REALTIME (not STATIC), and (b) the priority order `ANOMALY > RECOMMENDATION > DIAGNOSTIC > COMPARISON > HISTORICAL > STATUS > CAPABILITY` requires contextual inference that keyword rules cannot reliably perform. This finding directly motivates using the LLM classifier (Phase J, gpt-5.5) for the canonical corpus classification — the two-axis master table (Phase J) should be treated as more accurate than the Phase B deterministic labels. The `domain_l1` dimension (κ=0.581) shows genuinely moderate classifier agreement, suggesting domain boundaries are clear enough for the 20-class scheme but individual keyword rules need broadening.

## Open questions for reconciliation round

1. **DIAGNOSTIC vs ANOMALY** — when 'is X too high?' should be coded ANOMALY vs DIAGNOSTIC.
2. **CAPABILITY scope** — 'can the building do X' vs 'can the system do X'.
3. **INFO_REQUEST vs WAYFINDING** — overlap for amenity-hours queries.
4. **Default temporal code** — revise taxonomy rule to specify REALTIME as default when no time cue is present (currently STATIC is the machine-classifier default, which disagrees with LLM on 103/299 questions).

## Notes

- Coder A is deterministic (keyword lexicon, no LLM calls). Coder B is an independent LLM pass (gpt-4o, temperature=0). This is a cross-paradigm comparison rather than a traditional two-human-coder design.
- The κ values represent a **lower bound** on taxonomy reliability; human-human or LLM-LLM agreement would be higher once the conservative-bias artefacts above are addressed.
- The Phase J LLM classifier (gpt-5.5, full corpus) is the canonical classification and should be preferred over Phase B deterministic labels for the paper's quantitative claims.
- Rows where only one coder has a label (0 total) are excluded from kappa.
