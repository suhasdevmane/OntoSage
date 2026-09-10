# Three defects whose fixes were refuted — what to do instead

**Written 2026-08-22.** Three items from the open-defect sweep had solid diagnoses and unsound
fixes. Adversarial review caught each one, so none was shipped. This is the re-plan.

The common shape is worth naming up front: **in all three cases the investigation was right
about what is broken and wrong about what to do.** A diagnosis is checked against the system;
a fix is checked against a system that does not exist yet, and that is a much weaker check.
Keeping the diagnosis and re-deriving the remedy is the cheap move — the expensive one is
shipping a plausible fix and discovering later that it addressed nothing.

---

## CAVEAT-160 — temp-0 CQ-IR compile wobble

### What is actually established

The metric that closed this is **structurally blind to it**.
`_orchestrator.build_plan_trace` publishes `plan_fingerprint` only when
`results["evidence_dossier"]` exists, and every clarify-or-decline turn returns from
`_deliberate_node` *before* a dossier is built. So the runs that flip to `clarify` — the exact
event the caveat describes — emit no fingerprint and drop out of the denominator.

Re-derived from two same-model repeat experiments already in the repo
(`scripts/outputs/v5_t44_rows_t44_fp_check.csv`, `..._t44_enforced_v2.csv`), 8 invariance
questions × 2 arms:

| | |
|---|---|
| answer↔clarify flips | **3 of 16 paired questions = 18.8%** |
| total plan disagreement | 7 of 16 = 43.8% |
| the caveat's own stated revisit threshold | "> ~5%" |

The trigger condition was met by evidence already on disk. BUG-184's published "5/6" was
computed on the blind metric, which removed the flipped rows as "lane downgrades".

### Why the proposed fix was refused

Two reasons, and the second is the serious one:

1. The load-bearing normalisation fold was called unsound as specified.
2. Half the measurement justifying the priority order was computed on `plan_hash` — the field
   **BUG-184 explicitly established must not be compared between runs**, because it includes
   the candidate set, which excludes currently-busy rooms and therefore differs by
   construction on a live building.

Using the field whose misuse caused the previous wrong conclusion, to justify the fix for that
wrong conclusion, is the failure repeating itself one level up.

### What to do instead

1. **Fix the metric before the defect.** Publish `plan_fingerprint` on clarify and decline
   turns too. Until the flipped runs appear in the denominator, no flip-rate number means
   anything, and any fix will be evaluated by the instrument that hid the problem.
2. **Re-measure** the flip rate on the repaired metric, over more than 8 questions. 16 paired
   observations is too thin to separate 18.8% from 5%.
3. **Only then** choose between the deterministic fold and a compile cache. Note the cache has
   an invalidation problem nobody has solved: a cached plan served after a TTL upload or a
   concepts change would be a *stale* answer, which is worse than a wobbling one.

**Do not touch the folds until step 1 lands.** They are being tuned against a broken gauge.

---

## CAVEAT-185 — the deliberative lane against a 120 s ceiling

### What is actually established

The diagnosis survived review; it is the fix that did not. Measured from the golden baseline's
`elapsed_s`, on the honest population (the 214 LLM-bearing turns — the 1,360 `capability` rows
are a non-LLM retrieval path at median 0.5 s and drag any aggregate down):

| population | p50 | p90 | p95 |
|---|---|---|---|
| all LLM-bearing turns | 40.7 s | 100.1 s | 105.6 s (88% of ceiling) |
| the `deliberate` lane (n=35) | **90.4 s** | 105.6 s | 108.7 s (91% of ceiling) |

**75% of the entire budget is consumed at the median** in the lane the caveat names, and 25.7%
of its turns exceed 100 s. The mechanism is real and reproduces on the current model.

### Why the proposed fix was refused — by all three reviewers

- **The arithmetic is wrong.** With `LLM_MAX_RETRIES=3` and backoff summing to 3 s, worst case
  is `3T+3`: at T=45 that is 138 s, at T=60 it is 183 s — both still overrunning
  `WORKFLOW_TIMEOUT_S=120`. The proposed invariant `LLM_TIMEOUT_S < WORKFLOW_TIMEOUT_S` is
  insufficient; the real constraint is `MAX_RETRIES × TIMEOUT + backoff < WORKFLOW_TIMEOUT_S`,
  which forces T ≤ 39 s.
- **The headline payoff does not follow.** It rests on the circuit breaker opening.
  `circuit_breaker.record_success()` zeroes `_failure_count` on any success, so it counts
  *consecutive* failures; with ~99% of turns succeeding it took ≥21 failures in 24 h and never
  opened. Adding scattered timeouts will not open it either.
- **An entire timeout layer was missing from the analysis**: `planner_agent._STEP_TIMEOUT = 45`,
  a hardcoded per-step limit that fired 21 times in 24 h, **19 of them inside the baseline
  capture window**.

### What to do instead

1. **Fix the retry arithmetic first.** Write the invariant as a startup assertion —
   `MAX_RETRIES × LLM_TIMEOUT_S + backoff_sum < WORKFLOW_TIMEOUT_S` — so an inconsistent
   combination cannot boot silently. That is a real defect independent of any tuning.
2. **Surface `_STEP_TIMEOUT`.** A hardcoded 45 s that fires inside measurement runs and appears
   in no timeout table is exactly the kind of thing that makes a capture unreproducible.
3. **Decide the breaker separately.** Consecutive-failure semantics may be the right design;
   if a rate-based breaker is wanted, that is its own task with its own justification — not a
   side effect of a timeout change.
4. **Then** consider the timeout values, with the deliberate lane's p95 (108.7 s) as the
   binding constraint.

The honest framing for the caveat itself: this is **not** "a slow model cannot serve the
pipeline". It is that the timeout layers are mutually inconsistent and one of them is invisible.

---

## TODO-072 — cold GUI-only onboarding, FIXED_UNVERIFIED

### What is actually established

The owed verification **cannot be run as specified**, because emptying `input/` does not
produce a cold system. Readiness is read from four independent state sources and clearing the
directory clears one:

| step | falls back to | cold verdict |
|---|---|---|
| identity | `settings.BUILDING_ID` / `NAME` / `NAMESPACE` from `.env` | green |
| ontology | the persisted GraphDB volume under `./volumes/<BUILDING_ID>/` | green |
| datasource | `config/database_registry.yaml` — returns **46 connections** | green |

**3 of 5 steps report green on a system where nothing has been configured.** A cold operator
would be told they have 46 datasources having registered none.

A reviewer then found a **fourth** source the investigation missed:
`shared.config._load_building_yaml` reads `config/building_config.yaml`, which is mounted into
every building's container — so identity survives even an empty `.env`.

### What to do instead

1. **Define "cold" precisely**, as a list of every state source that must be absent: `input/`,
   the per-building volume, `config/building_config.yaml`, and the identity variables in the
   environment. Until that list exists there is nothing to verify against.
2. **Make each readiness step name its source.** "ontology: green (233 spaces, from the
   persisted volume)" is honest; a bare green tick is not, and it is what makes the current
   state so easy to misread.
3. **Replace `> 0` smoke checks with equality targets.** The live graph returns **233** spaces
   for bldg1; a cold rebuild that yields 233 has demonstrated something, a rebuild that yields
   1 has not.
4. **Close the two real test gaps found**: zero tests exercise the request shape of either
   upload endpoint, and one test asserting it is a "totally offline probe" makes a live GraphDB
   call.

Only after 1–3 is the live cold-start run worth doing; today it would pass for the wrong
reasons.

---

## What the three have in common

Each was recorded with a root cause that turned out to be **incomplete rather than wrong**, and
in each case the missing part changes the remedy:

| item | recorded cause | what was actually missing |
|---|---|---|
| CAVEAT-160 | "the parser does not normalise enough" | the metric cannot see the failure |
| CAVEAT-185 | "the model is too slow" | the timeout layers contradict each other, and one is hidden |
| TODO-072 | "the live run is still owed" | the run cannot be cold, so it would pass falsely |

The order to work them in is therefore the same in all three: **repair the instrument, then
re-measure, then fix.** Every one of them currently has a fix proposal aimed at a target
measured by a broken gauge.
