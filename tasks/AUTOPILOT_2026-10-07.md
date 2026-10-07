# Autopilot round, 2026-10-07 (overnight, owner asleep, 8 h budget)

Rules in force: commit LOCALLY only, never push. Park the building before every commit
(CLAUDE.md Workflow rule 8) and reactivate after. Regression gate runs ALONE. Hosted LLM only.
Credentials stay in .env; no rotation. Building-agnostic code. Owner decisions recorded below
are binding.

## Owner decisions (binding)
- E6 capacity: TTL first; drawing figure only when the TTL has no figure. (Done in merged tree.)
- BUG-1442 floor CO2: sensors selected by Brick CLASS, never by name. Never describe any sensor
  as simulated or synthetic in an answer. Floor 5 CO2 sensors are real; the rest are as they are.
- Owner's rule: class, not entity name, everywhere a quantity is chosen.

## State at start of round
- Merged round tree applied to the main checkout, parked as bldg1 (input/ -> bldg1/, .env -> .env1,
  docker-compose.yml -> docker-compose.bldg1.yml).
- Live checks on the merged code: doors OK, room 4.01 = 20 (TTL) OK, energy "yesterday" resolves
  to 6 Oct OK, floor-3 CO2 799 ppm with sampling note OK.
- Live FAILURES: BUG-1426 cafe follow-up returns building hours (07:00-22:00) instead of the cafe's
  16:30; "When was room 2.01 last comfortable?" routed to the AV readiness register.
- Energy "yesterday" total covers 14:02-22:53 only and is presented as the day total.
- .gitignore: scripts/outputs/ kept ignored (A2 exception reverted; evidence stays in docs/phase0).

## Waves
- W0 (now): parked unit suite (background) -> checkpoint commit "round: merged trial fixes".
- W1 (parallel worktrees, from the checkpoint): BUG-1426 follow-up referent; comfort-history
  misroute; energy partial-day disclosure; label-based selection left in too_broad_reply,
  aggregate_profile.py and is_headcount -> class-based; BUG-1442 count disagreement settled by a
  read-only per-uuid COUNT against MySQL.
- W2: integrate W1 onto the checkpoint, targeted tests, park, regression gate ALONE, parked suite,
  commit.
- W3: live re-asks of every row touched, H3 Open WebUI description applied, bldg1/datasources.yaml
  comment applied in the parked copy, TODO-1026 closed as BLOCKED with reason.
- W4: I1 hand re-read of the 73-question evidence pack; findings logged, fixes only if small.
- W5: final parked suite, final gate, final commit. Report to owner.

## Log
- [start] round tree merged; building parked; parked unit suite started (background).
- [park] stack stopped; bldg1 active set parked (input/ -> bldg1/, .env -> .env1, compose -> docker-compose.bldg1.yml).
- [gitignore] scripts/outputs/*.md exception REVERTED (109 generated files were exposed); evidence stays in docs/phase0/.
- [suite 1] parked `pytest -m unit`: 14679 pass, 186 skip, 5 xfail, 6 FAILED. Cause: C8 moved LLMManager.generate's
  body into a wrapper around _generate_attempts; four source-inspection tests read `generate` and found nothing.
  Fixed by pointing those tests at _generate_attempts (98 pass). One test pinned the old "full 1000 rows" wording
  that BUG-1448 changed on purpose; updated to "reached its row limit of 1000 rows".
- [suite 2] parked rerun started (background) to satisfy the commit rule.
- [diagnosis] BUG-1426 root cause: the coref rewrite is written to state.messages[-1] only; the capability lane reads
  state.user_message (still the un-rewritten question), so the Working Hours topic wins. Offline tests missed this.
  Narrow fix: capability_agent reads the coref rewrite; broader fix: set state.user_message in the coref block (gate).
  Also: dialogue_agent._labels bypasses the accent fold (dead BUG-1426 code on that path).
- [diagnosis] comfort misroute: no deterministic rule matches; the LLM classifier most likely picks readiness_check.
  Fix: a routing override after the classifier for comfort-history shapes; blast radius needs a classifier replay.
- [diagnosis] energy partial day: series_summary.summarise_energy_totals has no coverage check; the headline is written
  by the model. The 14:02 start may be the SQL fetch cap (newest-first, MAX_FETCH_ROWS) cutting the oldest rows.
  BUG-1437 (day choice) is fine; log the partial-total defect separately.
