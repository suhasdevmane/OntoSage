# V4-T35 — The 10-minute demo script (with fallbacks)

_Pre-flight and beats are automated in `scripts/demo_rehearsal.py` — run it once
before any live demo; every beat below maps 1:1 to a rehearsal assertion._

## Pre-flight checklist (5 minutes before)

1. **Stack warm**: `docker compose ps` — all services Up; `curl http://127.0.0.1:8000/health` → 200.
   The ACTIVE building is the demo building (any of the three works — the script is
   building-agnostic; bldg1 shows real+simulated mix, bldg2/bldg3 show pure saturation).
2. **Cache flushed**: `docker exec redis-memory-store sh -c 'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL'`
   (stale cached answers are the #1 demo killer).
3. **Rehearsal green**: `python -X utf8 scripts/demo_rehearsal.py` → ALL BEATS PASS.
4. **Pre-captured results open in tabs** (fallback material): `scripts/outputs/V4_RESULTS.md`,
   the bldg3 gate outputs, `tasks/figures/v4_pipeline_before_after.png`.
5. **Provider**: local (gpt-oss:20b) by default; the determinism story
   (same plan fingerprint on OpenAI) is a TALKING point backed by archived runs — do NOT
   flip providers live.

## The beats (≈10 min)

| # | Beat | Say | Do | Fallback if it misbehaves |
|---|---|---|---|---|
| 1 | The problem (1 min) | "Ask a building anything — including questions that need reasoning, not lookup." | Show the before/after pipeline figure | — (static) |
| 2 | Flagship (2 min) | "Quiet, good air, near water, tomorrow — four constraints, one answer, with proof." | Ask the flagship question in OpenWebUI; open the dossier `<details>` | Pre-captured flagship answer in V4_RESULTS/meeting brief |
| 3 | Proof spelunk (1.5 min) | "Every number exists in the evidence — a guard suppresses any narration that invents one." | Point at dossier rows: values, source tables, `simulated: yes`, excluded rooms + reasons | Show `dossier.py` `numeric_guard` code instead |
| 4 | Clarify → resume (1.5 min) | "Ambiguity costs ONE question, never an interrogation — and the plan resumes, not restarts." | Ask "Which room on floor 99 is the quietest right now?" → pick option 1 (nonexistent floor = deterministic schema-validation ask with real floor options) | If it answers directly (phrasing drift): show clarify_battery CSVs |
| 5 | Honesty (1 min) | "What it can't sense, it says so — and tells you what it CAN." | Ask "Which room has the lowest radiation right now?" | Any unanswerable from the L7 bank |
| 6 | Brain routes everything (1 min) | "Even simple lookups carry a machine-checkable plan trace now." | Show `plan_trace` in the API response for "How many rooms are on floor 2?" | `scripts/demo_rehearsal.py` output shows both trace kinds |
| 7 | The ablation kicker (1.5 min) | "Same model, no architecture: 0/15 correct and it invents numbers. The structure is the contribution." | Show ablation table in V4_RESULTS.md | — (static) |
| 8 | Portability close (0.5 min) | "Three buildings, zero code differences, zero fabricated values." | Show the 3-building certification table | — (static) |

## Known demo risks

- **Cold GraphDB after a fresh boot**: ontology init self-heals but takes minutes
  (BUG-100) — boot the stack ≥15 min before the demo.
- **Compile wobble (CAVEAT-160)**: temp-0 local runs can rarely flip an answer to a
  clarify. It is SAFE behavior (never fabricates) — narrate it as the honesty design if
  it happens, or re-ask with slightly different phrasing.
- **Live drift**: the publisher ticks every few minutes; identical questions minutes
  apart can rank neighbors differently when rooms are close — the dossier's
  "top choice stable under ±25% weight changes" line covers exactly this.
