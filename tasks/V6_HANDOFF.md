# V6 handoff — read this first (updated 2026-08-24, end of Wave C)

Written for a cold session on a different model. Everything here is verifiable in the repo;
where a claim rests on a live probe, the probe is named so it can be re-run.

## Read in this order

1. **`tasks/V6_AUDIT_2026_08_23.md`** — why the tracker's done-count was wrong and how it was
   re-derived. The single most important document; it explains the failure shape that recurs.
2. **`tasks/V6_TRACKER.csv`** — 65 rows. Status vocabulary now includes
   `logic_done_not_wired`, meaning the module exists and passes tests but nothing imports it.
3. **`tasks/IMPROVEMENT_PLAN_V6_EVIDENCE_AND_OBSERVABILITY.md`** — the plan. Audited and found
   sound; D-1..D-13 are the design decisions and their rejected alternatives. Do not rewrite it.
4. **`tasks/FIX_TRACKER.csv`** (241 rows) and **`tasks/lessons.md`** (#30-53 are this workstream).

**CLAUDE.md's "current state snapshot" is stale** — it describes 2026-08-22 morning, before the
audit and both waves. Trust the trackers.

## Where the work stands

- V6: **37 done · 5 in_progress · 1 logic_done_not_wired · 22 todo**
- Unit suite: **2,718 pass, 2 skip, 0 fail**
- Active building **bldg1**, provider **local `gpt-oss:20b`**
- **Nothing is committed.** A very large body of uncommitted work. Never `git commit`/`push`
  without the user saying so explicitly, and park all buildings first (CLAUDE.md workflow rule 8).

## What is live, and how to re-verify it in one probe each

All gates are **advisory**: they record a verdict and change no answer. That is deliberate
(plan D-9/T55); switching one to enforcing is the user's decision, made from
`scripts/gate_impact_report.py`, never taken unilaterally.

| Capability | Re-verify with |
|---|---|
| Evidence record on every lane (T02/T03) | any `/chat` call → `data.evidence_record` |
| Freshness gate (T16) | "What is the CO2 level in the lecture theatre right now?" → advisory names the age and the per-modality limit |
| Spatial adequacy, all four grades (T13) | "What is the temperature in zone 5.16?" → `served_zone`; zone 5.28 → `in_room` |
| Completeness (T17) | "average noise in room 3.18 between August 10 and August 22" → `completeness: 0.333` + advisory |
| Recurring windows (T40) | "Show noise levels on floor 5 overnight" → log line `window 'overnight': N of M rows inside it` |
| Conflict (T18) | comparable sensors in the SAME space disagreeing; a cross-room comparison must NOT fire |
| Sensor health (T08) | `GET /api/v1/admin/sensors/health` → ~2,035 assessed |
| Proxy naming (T14) | a proxy-only room question → `> **Spatial basis:** …` in the answer text |

## The one thing to internalise

Ten V6 turns were marked done while nothing in the live pipeline imported their module, and the
entire T06 TBox had zero instances. Every instance has the same shape: **an interface whose
absent side degrades to a legal value** — an empty default, a missing dict key, a `getattr`
fallback, a TBox term with no ABox, a DictWriter filling a blank column. Nothing raises.

So the standing rule, already applied to Waves A and B:

> A turn whose acceptance criteria describe live behaviour cannot be marked done from unit
> tests. It needs a **reachability test** (does the pipeline import this?) plus a **live probe**,
> and the probe's output goes in the tracker note.

`tests/test_wave_a_wired.py` is the pattern to copy.

## Wave C (2026-08-24) — what landed

| Turn | State |
|---|---|
| **T20** | Acceptance scenarios 2 + 4 automated *through the live chokepoint*, each with a control |
| **T21** | Source precedence — 3 tiers keyed on source kind; disagreement reported, never resolved |
| **T22** | Never-infer-permission — 4 chains, matched on the QUESTION; live |
| **T23** | Reports bound to space + time; live (`space=...#Room5.16`), queryable via `reports_for_space` |
| **T34** | Calibration gate live; 142 declared dev calibration instances, all three states verified |
| **T36** | Independent backup — wired and verified on real dependency data, **not yet observed end to end** |

Two defects found in *other* turns while doing these:

- **T32's consequence map was keyed on invented shape names** the router never emits, so every
  question resolved to `informational` and consequence scaling had been inert since it was
  written. Re-keyed on the router's own intents; a test now pins it.
- **BUG-242** — a report ID's digits (`REP-571188`) were judged as a sound reading. Third of a
  family with BUG-191 and BUG-230.

**All gates now have real inputs.** `_GATES_AWAITING_INPUT` is empty for the first time; the
mechanism is kept so the next gate without an input must declare itself.

## Next, in order

1. **V6-T09** Question-to-Observability Matrix — the Master Report's central artefact, and
   the deliverable that makes the 6/63/31 readiness split legible. Unblocked, Large.
2. **V6-T24** one ticket universe (now unblocked by T23), then **T25→T26/T27** — the R2
   adapters, which are 63% of the supervisors' catalogue.
3. **V6-T07** location history: the fetch half plus `effectiveFrom/To` instances (T65).
4. **P12** synthetic provisioning against the tiered catalogue.

**Owed measurement, and it has grown:** Waves A, B and C are all unmeasured against the
baseline. One re-capture + `baseline_regression_gate.py` now scores three waves at once, and
`gate_impact_report.py` will for the first time have advisory verdicts from seven gates to
report. Do this before starting T09 if a number is wanted for a supervisor.

Owed measurement (not blocking): a re-capture + `scripts/baseline_regression_gate.py` against
`baseline_20260823_075206.csv` to score Waves A/B; then `gate_impact_report.py` for the
enforcement conversation.

## Waiting on the user — do not decide these alone

- **Calibration records** → unblocks V6-T34 (no building declares a calibration state).
- **Three declared dev pilots now exist**, each in its own named graph, each replaceable by
  dropping that graph: `urn:v6:t65:cadence:bldg1` (1,994 measured — real, not invented),
  `urn:v6:t65:zone-validation-dev` (7 VAV zones), `urn:v6:t65:calibration-dev` (142 points,
  deliberately mixed calibrated/expired/undeclared so the gate's branches are exercisable).
  Whether these extend beyond floor 5, and whether real calibration records exist, is yours.
- **TODO-072 cold build** — scripted (`scripts/cold_start_verification.py`,
  `tasks/COLD_START_VERIFICATION.md`) but takes the stack down for ~1.5 h.
- **Enforcing any gate.**

## Traps that have already cost time

- **Verify a deploy through the RUNNING service.** `docker exec … python -c "from shared.config
  import settings"` reads the bind-mounted file, not what the server loaded — it invalidated a
  two-hour capture (lesson 39).
- **`docker exec <c> python /tmp/x.py` needs `sh -c '…'`** in Git Bash, or MSYS rewrites the path
  to `/app/C:/Users/…` (lesson 52).
- **Flush `resp_cache:*` on `redis-memory-store`** before any probe, or you measure yesterday.
- **A mid-run container recreate invalidates the whole capture**, not just its error rows — the
  healthy-looking rows straddle two configurations (CAVEAT-173 pattern, seen again 2026-08-22).
- **`intermediate_results["uuids"]` does not exist.** Use
  `evidence.assemble.contributing_uuids(results)`; the docs named a key nothing writes (BUG-241).
- **Never mint new `ref:hasTimeseriesId` carriers** when authoring TTL — bind to existing point
  IRIs. Blank-node refs are the CAVEAT-039 duplication shape (1.2M triples deleted once already).
