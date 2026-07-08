# Phase G4 — Gap Analysis

The capability matrix (G2) lists what the corpus demands of a smart-building NL
interface. This file enumerates the *gaps* — query types that current commercial
or research systems cannot serve fully — split into three categories.

## 1. Data-availability gaps

| Gap | Evidence | Implication |
|-----|----------|-------------|
| Off-ontology requests | 1467 questions (20.5%) classified as OTHER (Phase B2). | Brick / 223 schemas do not yet model amenity, wayfinding, or hospitality concepts that occupants and guests routinely ask about. |
| Cross-system fusion | RECOMMENDATION (128) and ANOMALY (160) queries assume joined sensor + standards + occupancy data. | Storage adapter routing must federate at least three back-ends transparently. |

## 2. Reasoning gaps

| Gap | Evidence | Implication |
|-----|----------|-------------|
| Multi-step reasoning | 248 MULTI_STEP questions (3.5%) require chained retrieval, computation, and synthesis. | Single-shot SPARQL or single-shot SQL is insufficient; an orchestrator with intermediate state is required (OntoSage++ uses LangGraph). |
| Diagnostic causation | 123 DIAGNOSTIC queries ask "why" rather than "what". | Need a causal model layer (rule-based or ML) on top of telemetry. |

## 3. Integration gaps

| Gap | Evidence | Implication |
|-----|----------|-------------|
| Persona-aware response | Phase D shows distinct domain mixes per persona; Phase F shows distinct level preferences per persona. | The response generator must consult a persona registry, not just template strings. |
| Standards-aware answers | RECOMMENDATION queries reference comfort, energy, and air-quality thresholds. | The system must surface ASHRAE / WELL / BREEAM thresholds inline, not buried in references. |
| Live state vs. historical | Mix of INSTANT, RECENT, HISTORICAL_RANGE temporal labels. | Caching and freshness policies must vary by intent (status = sub-second; historical = minutes is fine). |

## Future work hooks

1. Replace the deterministic Phase B2 classifier with an LLM-backed labeller and
   re-validate Kappa on the same IRR sample to compare gains.
2. Expand the Brick / 223 alignment layer to absorb the OTHER bucket (mostly
   amenity, wayfinding, and policy queries from guests and occupants).
3. Add a closed-loop feedback log so production responses feed Phase B-style
   corpus statistics, allowing the priority tiers in G2 to drift with usage.
