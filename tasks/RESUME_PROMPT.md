# Resume Prompt — Implementation Plan V3

Copy everything inside the block below into a NEW Claude Code conversation (repo root:
`c:\Users\suhas\Documents\GitHub\OntoSage`) whenever you want to continue the implementation.
Re-paste it after every credit reset — each session picks up exactly where the tracker says.

---

```
Continue executing IMPLEMENTATION PLAN V3 for OntoSage. Work autonomously and complete as many
tracker turns as possible this session.

READ FIRST (in this order, before any other action):
1. tasks/IMPLEMENTATION_PLAN_V3.md       — §0 resume protocol, §2 LOCKED architecture decisions, §4 portability contract
2. tasks/implementation_tracker.csv      — the 37 turns (T01–T37); columns: turn, phase, title, status, depends_on, effort, objective, key_steps, files, acceptance_criteria, verify, notes
3. tasks/architecture_coverage_crosswalk.csv — reference only (which corpus capability each turn serves)

EXECUTION LOOP (repeat until the session must end):
1. Parse the tracker. Eligible turns = status "todo" (or "in_progress" — finish those FIRST) whose
   depends_on turns are all "done". Work them in ascending turn order.
2. Plan the session with TodoWrite: list every eligible turn you intend to attempt, broken into
   its key_steps. Attempt the MAXIMUM number of turns that fit; do not stop after one.
3. For each turn:
   a. Implement EXACTLY what objective + key_steps describe. The plan is decided — do not
      redesign it, do not relitigate the locked decisions in IMPLEMENTATION_PLAN_V3.md §2.
   b. Create any required input/config/dummy files yourself (synthetic CSV data, YAML configs,
      TTL files, template documents). Realistic synthetic data is the default for bldg1 —
      invent it; do not ask me for data.
   c. Test it: run the row's "verify" command AND check every acceptance_criteria item.
      Code changes require: black --line-length 100 + flake8 --select=F821,F823 on touched files,
      pytest tests/ -m unit -q, then docker compose build orchestrator && docker compose up -d
      orchestrator, wait for /health, flush the response cache
      (docker exec redis-memory-store sh -c "redis-cli --scan --pattern 'resp_cache:*' | xargs -r redis-cli del"),
      then end-to-end curl checks against http://127.0.0.1:8000 (NEVER localhost — wslrelay
      intercepts ::1 and resets connections).
   d. Update the tracker row IN tasks/implementation_tracker.csv: status=done plus a dated note
      (YYYY-MM-DD: what was built, test result, anything the next session must know). Preserve
      CSV quoting — edit programmatically (python csv module) if in doubt.
   e. If a turn cannot finish this session: status=in_progress, and write in notes EXACTLY where
      you stopped (file, step number, what remains). If truly blocked: status=blocked + reason.
4. Before the session ends: make sure the tracker is saved and consistent, then give me a short
   summary: turns completed, turns in progress, what the next session starts with.

DECISION POLICY:
- Do NOT ask me questions unless you are genuinely blocked on something only I can provide
  (a real credential, a destructive/irreversible choice, or a contradiction between the plan and
  the code that you cannot resolve). For everything else: follow the tracker's recommendation,
  pick the conventional option, note the choice in the notes column, and keep moving.
- NEVER git commit or git push. I review and commit myself.
- General-knowledge answering logic is OUT of scope — do not touch it.
- Building-specific content goes ONLY in input/<id>/ or config/ files — never hardcode building
  facts in Python. That rule is the whole point of the plan.
- Follow .claude/rules/agent-patterns.md for any new LangGraph node, and the routing-precedence
  rules in CLAUDE.md.
- If docker compose is not running, start it (docker-compose up -d) and wait for health before
  end-to-end tests.
- If a previous session left the tracker mid-turn, trust the notes column over your assumptions.

START NOW: read the three files, report which turns are eligible, then execute.
```

---

**Tips**
- If you only want specific turns done, append e.g. `This session: only do T01 and T04.`
- If credits die mid-session, just re-paste — `in_progress` notes make resume lossless.
- After T29/T30 complete, ask for a commit plan; review it; only then approve committing, otherwise do not commit until approved.
