# Phase G1 — OntoSage++ Query Classification Framework

## Inputs and outputs

- **Input:** raw natural-language question text (English, 1-50 words)
- **Output:** a six-tuple
  - `domain_l1` ∈ {20 codes; see `taxonomy_v1.md`}
  - `query_type_l2` ∈ {STATUS, HISTORICAL, COMPARISON, DIAGNOSTIC, ANOMALY, RECOMMENDATION, CAPABILITY}
  - `intent` ∈ {INFO_REQUEST, ANALYSIS, ACTION, WAYFINDING}
  - `temporal` ∈ {INSTANT, RECENT, HISTORICAL_RANGE, NONE}
  - `spatial` ∈ {POINT, ZONE, FLOOR, BUILDING, CAMPUS, NONE}
  - `complexity` ∈ {LOOKUP, AGGREGATION, MULTI_STEP}

## Pipeline

1. **Lexical pre-pass.** Lower-case, normalise unicode, expand common
   smart-building abbreviations (CO2, IAQ, HVAC, AHU, VAV).
2. **Domain & query-type classifier.** A deterministic regex + lexicon
   stack (Phase B2) provides a strong baseline. The lexicon is the
   evidence base for the LLM-driven classifier; replacement with an
   Anthropic Batch API run is a drop-in upgrade.
3. **Intent classifier.** Cue-word lookup (recommendation verbs,
   diagnostic verbs, comparators) decides the four-way intent label.
4. **Temporal & spatial taggers.** Simple regex over time expressions
   ("last week", "yesterday", "today") and space references ("zone",
   "floor", "room", "building").
5. **Complexity router.** Counts the number of independent clauses and
   the presence of aggregation operators (avg, total, max, min, trend)
   to assign LOOKUP / AGGREGATION / MULTI_STEP.

## Validation

- Phase B2 deterministic baseline classifies the full N=5,127 corpus.
  Coverage of on-topic domains (excluding OTHER) is **79.5%**
  (5684 of 7151 questions).
- Phase B3 inter-rater reliability gate is the substantive Kappa floor
  (target ≥ 0.70 per dimension). The IRR sample (`taxonomy/irr_samples.csv`)
  is ready; two independent coders annotate it before publication.
