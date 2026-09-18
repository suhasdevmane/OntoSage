# Readiness plan — 2026-09-17 (demo Fri 2026-09-18 14:00)

Goal set by the user: a supervisor can ask anything and never get a weird answer, an instruction
to "add data", or an incomplete answer. Vocabulary must be BUILDING-AGNOSTIC — carried by the
OntoSage schema (OCBV) and Brick, not by one building's instances or by code.

User decisions (2026-09-17 ~14:05):
- Measure first; add REAL SYNONYMS only. The stakeholder sweep's `candidate_lay_terms` are
  co-occurring words ("four; three; quiet" for Booking) and must NOT be loaded.
- No cutoff. Quality bar still applies: a batch is done only with probe + demo script + guard set green.
- Declines: plain honest decline + what IS available for everyone; remediation ("how to add it")
  only for admins. The decline itself never disappears (design contract 4).
- DEMO LOGIN (user, ~15:50): Open WebUI as facility01@example.com -> OntoSage role facility_manager (TRUST_FORWARDED_USER=true, X-OpenWebUI-User-Email). NOT the owner's own account, which is OntoSage admin and would show remediation text. Every live check runs as facility01.
- ROOM IDENTITY (user, ~16:40): the architect's DRAWINGS are authoritative for what a room is; Room 0.01 is a 120-person lecture theatre (not Main Reception). Room IRIs stay unchanged; cascade inventory before any data move.
- Provision placeholder data for: alarm events, anomaly events, access events (door/role level
  only, never individuals), room capacity.

## Why "missing vocabulary" is not what the sweep said

- The top "vocabulary gap" registers already declare 16-45 class-level `ontosage:layTerms` each.
- ApprovalRecord takes 25.2% of register selections; its terms include `evidence`, `verified`,
  `owner`, `certificate` — over-capture, not under-capture.
- "33% selected no register" measured the register scorer in ISOLATION; a question answered well
  by the sensor / workspace / deliberation lane counts as "nothing selected" there.
- 55 of 99 OCBV classes carry no `layTerms`, but only some should: amenity kinds yes (their
  synonyms live on bldg1 INSTANCES today, so they do not transfer); measurement classes via HBCO
  concepts; report-intake and meta classes NO (terms would route "the toilet is leaking" into a
  register lookup instead of report intake).

## Phases

- **Phase 0 (GPU, running):** 147-question stakeholder bank (`docs/phase0/phase0_bank.jsonl`,
  3 per role x 37 roles + categories + survey levels) through `/v1` streaming as facility01.
  Output `docs/phase0/phase0_baseline.md`. Graded into: answered / honest decline /
  add-data instruction / wrong lane / incomplete / invented.
- **Phase 1 (parallel agents, OFFLINE, no GPU):** table below.
- **Phase 2 (GPU, serial, owned by the lead):** load data, restart, probe (flushed), demo script
  streaming, Phase 0 re-run, before/after.

## Ownership — an agent touches ONLY its files

| Agent | Work | Owns |
|---|---|---|
| VOCAB | Class-level synonyms (registers + amenity kinds), narrow over-broad terms, offline reach+precision harness with a MECHANICALLY derived guard set | `ontology/ontosage_schema.ttl`, `scripts/register_reach.py`, `docs/phase0/guard_set.jsonl`, `tests/test_register_reach*.py`; `orchestrator/services/capability_graph_resolver.py` ONLY if class-level amenity terms are not read today |
| HBCO | Measurement lay terms for Brick/OCBV sensor classes that lack a concept | `ontology/mining/concept_terms_raw.csv`, regenerated `ontology/hbco_mappings.ttl`, `tests/test_hbco_*` new file |
| DECLINES | Role-aware decline wording; no "upload a TTL" for non-admins | `orchestrator/services/observability.py`, `grounding_guard.py`, `retrieval_outcome.py`, the decline text in `orchestrator/agents/capability_agent.py`, role plumbing in `orchestrator/workflow/_orchestrator.py`, new test file |
| DATA | Alarm/anomaly/access event placeholder records + room capacity, discovered not hardcoded, declared `ontosage:isSimulated`; PREPARE ONLY, do not load | new `scripts/provision_event_and_capacity_data.py`, new `input/bldg1_*` files it emits, new test file |
| SPARQL | BUG-667 floor scope via `brick:feeds` -> zone -> floor, and no room sensor answering a plant quantity; CAVEAT-654 empty result must not fall into RAG prose for data intents | `orchestrator/agents/sparql_agent.py`, new test file |
| ENDPOINT | TODO-657 `intent` in `/v1` body; BUG-655 inherited-state pruning on `/chat`, `/chat/stream`, `/stream`; BUG-662 probe flushes resp_cache; CAVEAT-656 `--stream` in the parity harness | `orchestrator/main.py`, `scripts/regression_probe.py`, `scripts/endpoint_parity_probe.py`, new test files |
| SQL | BUG-660 empty-window fallback goes through the group's own adapter; a failed fallback degrades to no-data, not a failed turn | `orchestrator/agents/sql_agent.py`, new test file |
| GRADER | Six-bucket answer grader, built on the 2026-09-15 stakeholder run outputs, used on Phase 0 | new `scripts/grade_stakeholder_answers.py`, new test file |

Lead owns: `tasks/*.csv`, `CLAUDE.md`, `tasks/lessons.md`, all live runs, all restarts, all loads.

## Rules for every agent

- NO GPU / live calls: no `regression_probe.py`, no `ask_questions.py`, no HTTP to `/chat` or
  `/v1`, no `docker compose` up/build/restart, no Redis flush, no TTL upload, no MySQL/GraphDB
  WRITES (reads are fine). The Phase 0 baseline is running on the single GPU.
- No git commit or push. Do not edit `tasks/*.csv`, `CLAUDE.md`, `tasks/lessons.md`.
- Never write Python source through a shell heredoc (lessons #107) — use Write/Edit.
- Building-agnostic: no building literals in orchestrator/, shared/ or script LOGIC. Would it run
  unchanged for bldg2?
- User-visible text never calls data synthetic, simulated or fake. Generated points DO declare
  `ontosage:isSimulated true` (internal provenance; `tests/test_provenance_honesty.py` enforces).
- Tests: `pytest.mark.unit`; redirect output to a file and echo `$?`; never `-p no:logging`;
  write tests that fail before the change; negative cases as well as positive; run the existing
  tests for anything you touch. black -l 100, isort --profile black, flake8 --select=F821,F823.
- If you need a file you do not own, STOP and report what and why.
- Report: files changed, measured test counts, what you did NOT do and why, new defects found
  (suggest a severity), and any premise in your brief that turned out wrong.
