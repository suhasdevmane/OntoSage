# OntoSage — Improvements Roadmap (2026-07-19)

Prioritized backlog captured after the model benchmark + coverage measurement session.
Live per-item status lives in [`FIX_TRACKER.csv`](./FIX_TRACKER.csv); this doc gives the
prioritized narrative and the "why". Update both when items move.

**Context set this session:**
- Primary model switched to **`gpt-oss:20b`** (fits 16 GB GPU 100%, ~6× faster than CPU-offloaded 26b, higher coverage). See [`scripts/outputs/model_benchmarks.md`](../scripts/outputs/model_benchmarks.md).
- Coverage on gemma4:26b (240q) = **82.9%** (up from 63.8% in June). Authoritative gpt-oss:20b 240-run in progress.
- BUG-046 (analytics 120s timeouts) resolved by the model switch.
- FIX-047 (corpus harness auto-loads `PIPELINE_API_KEY` from `.env`) done.

---

## Tier 1 — close the loop / quick wins

| # | Item | Tracker | Status |
|---|---|---|---|
| 1 | **Authoritative coverage on gpt-oss:20b** — 240-run for the real current number (the 82.9% was on 26b). | — | in progress |
| 2 | **Harness auth auto-load from `.env`** — no more silent 401s. | FIX-047 | ✅ done |
| 3 | **Ollama keep-alive** — model unloads on idle → ~16 s cold reload on the next question. Set `OLLAMA_KEEP_ALIVE`. | TODO-049 | open |
| 4 | **Set gpt-oss:20b as the always-default** (config + compose + env.example). | FEAT-048 | ✅ done |

## Tier 2 — correctness & honesty (the differentiator: grounded, never fabricate)

| # | Item | Tracker |
|---|---|---|
| 5 | **Sensor-type breakdown double-counts** — e.g. "Humidity 215 / Relative Humidity 215" in a live answer; dedup the COUNT. | CAVEAT-006 |
| 6 | **Counts conflate *modelled* vs *live-streaming* sensors** — "210 temperature sensors" may overstate what is actually readable; split declared vs has-data. | CAVEAT-007 |
| 7 | **Referent gate misses bare dotted IDs** → false "no data". | CAVEAT-005 |
| 8 | **Generalize routing into a question-shape → intent contract** — replace ad-hoc overrides (BUG-045 was one) with a principled, tested map. | TODO-050 |
| 9 | **Maintenance "report broken light" → generic fallback.** | KNOWN-008 |

## Tier 3 — coverage (the project goal: answer the survey corpus, TTL-first)

| # | Item | Tracker |
|---|---|---|
| 10 | **Categorize the corpus fails** → genuine gaps vs *correct* control-declines vs timeouts → a real backlog. | — (this session) |
| 11 | **Work `T5_new_capability_gaps.csv` TTL-first** — extend triples, not code, per the TTL-first rule. | — |
| 12 | **Finish TTL-native capabilities** — migrate `capability.yaml` → ontology triples; enable + verify `CAPABILITIES_TTL_FIRST`; retire the YAML. | ROADMAP-009, TODO-012, TODO-013 |

## Tier 4 — production readiness

| # | Item | Tracker |
|---|---|---|
| 13 | **Security-behavior test matrix + extended audit** (still unwritten). | PRODUCTION_READINESS_AUDIT #11–12 |
| 14 | **Reconcile the stale audit doc** — its P0 blockers are already fixed. | TODO-051 |
| 15 | **Split monolith `main.py`** (merge/review risk). | PRODUCTION_READINESS_AUDIT #9 |
| 16 | **Fix stale `credential-manager-core` git config** (noisy on every push). | — |

---

## Suggested execution order
Tier 1 #1 + Tier 3 #10 first (authoritative coverage on the fast model, then turn fails into a gap
list) → Tier 2 correctness bugs (they undermine the core value proposition) → Tier 3 #11–12 to push
coverage → Tier 4 before any production traffic.
