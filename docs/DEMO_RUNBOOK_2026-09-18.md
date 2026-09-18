# Demo runbook — Friday 2026-09-18, 14:00 (Open WebUI)

Everything here is building local time (BST). It is written to be followed step by step, on
the morning, by the person running the demo.

## Thursday 2026-09-17

| time | step |
|---|---|
| before 18:00 | Last code change lands. Run `python scripts/v12_coverage_audit.py` (must print OK) and `python scripts/check_building_literals.py` (must say clean). |
| 18:00 | **Code freeze.** Nothing under `orchestrator/`, `shared/`, `input/` or compose changes after this. |
| after 18:00 | ONLY on the owner's explicit approval: park bldg1, run `pytest -m unit -q` parked, commit + push (Workflow rule 8). Then "run bldg1" again. |
| 2026-09-17 decision | Freeze scope changed: only the narrow wording/routing fixes (BUG-730/731, BUG-679/699, footers) land after 18:00, each with tests + a flushed probe; then the demo script is rehearsed 3x streamed as facility01. |
| ~~evening~~ | ~~Sealed Gate A run~~ — **deferred to after the demo** (V12-29): a run-once evaluation that fails the night before leaves no time to act, and it would occupy the stack during the rehearsal. |

## Friday morning

1. **Host checks.** Ollama is running and `gpt-oss:20b` is loaded on the GPU (`ollama ps` shows
   100% GPU). Docker Desktop is up.
2. **Stack.** `docker compose ls` shows `ontosage_bldg1`. If it is not up: `docker compose up -d`,
   then poll `http://127.0.0.1:8000/health` until it returns 200 (~3 min; GraphDB warm-up can
   take longer).
3. **Last restart: no later than 12:30.** The anomaly sweep runs ~3 min after boot and takes
   ~5 min; answers are slower while it runs. **Do not restart after 12:30.**
4. **Data is fresh.** `docker compose ps data-publisher` is running. Ask
   *"What is the CO2 level in room 5.01 right now?"* — the answer's timestamp must be within the last
   few minutes, local time.
5. **Graph integrity.** `python scripts/certify_building.py --expect bldg1 --preflight-only`.
   Every line must say PASS, including "every sensor resolves to one timeseries id".
6. **Open WebUI.** http://127.0.0.1:3000, log in as **facility01@example.com**, which maps to the
   OntoSage `facility_manager` role (owner decision, 2026-09-17). NOT the owner's own email: that
   maps to admin, and admins see "how to fix this" remediation text under declines that the
   supervisor should not see. Start a **new chat** for each stakeholder section so no earlier
   turn gets carried into a later answer.

## Warm-up, 13:00–13:40

The response cache keeps an answer for 1 h, and its key includes the boot revision. (Until BUG-585, 2026-09-15, Open WebUI's streamed requests never read the cache at all; rehearse with `ask_questions.py --v1 --stream`.) Warm AFTER
the last restart and no earlier than 13:00, so the warm answers are still live at 14:00–14:45.

1. Flush BOTH caches once (CAVEAT-773 — the answer cache and the query-ROW cache have
   different keys, and flushing only the first serves pre-change rows):
   `docker exec redis-memory-store sh -c 'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL'`
   `docker exec redis-memory-store sh -c 'redis-cli --scan --pattern "cache:sparql*" | xargs -r redis-cli DEL'`
2. Ask the slow questions once each, through Open WebUI:
   - Which floor used the most energy yesterday?
   - can you provide energy saving suggestion?
   - Give me a report on the CO2 in room 5.01 yesterday.
   - Which floor is the warmest right now?
   - What is the average CO2 on each floor right now?
   - Which floor has the lowest humidity right now?
   - Which space in the building has the best conditions for focused work this afternoon?
   - What's the delta-T across the heating circuit, and is it healthy?

   "Right now" answers are cached too. A warm answer can be up to an hour old, and its timestamp
   says so. If someone asks why the value is from 13:20, that's the reason.
3. **Do not warm the boundary questions.** Their answers are fast and should be seen live.

## During the demo

- Question order and stakeholder framing: `docs/demo_script_questions.txt` (36 questions; pick
  a subset). Measured latencies: `docs/DEMO_REHEARSAL_2026-09-15.md`.
- **Talk while slow questions run.** The ~50 s questions are the report, energy per floor and
  energy suggestions. Say which lane is working: graph lookup → store fetch → computation.
- **Point at the evidence.** Every data answer ends with source chips and a coverage line. Do not
  describe the data as simulated, synthetic or fake (owner decision): the readings are placeholders
  for the building's own feeds and are replaced when those are connected.
- **Boundaries are the strongest part of the demo:**
  - privacy ("Is the professor in her office?");
  - actuation ("Open the windows on floor 3."), which declines;
  - absence ("radiation level in the atrium"), which says no such sensor exists;
  - report intake ("The toilet on floor 2 is leaking."), which files a report.
- **Unscripted stakeholder questions** are expected. If an answer declines honestly, say so. That
  is the design, not a failure. Never re-ask a question hoping for a different answer on stage.

## If something goes wrong

| symptom | action |
|---|---|
| An answer takes > 2 min | Keep talking; after ~3 min move to the next question (the longest rehearsed answer took 111 s). Do NOT restart. |
| A per-floor answer feels slow | Expected at 35-70 s. The narrow-table read was fixed on 16 Sep (20 s -> 2 s per read); what remains is the model writing the answer. The warm-up covers it. |
| "couldn't generate a response" / empty | Ask the next question. Note the question for the limitation register afterwards. |
| All answers failing | `docker compose logs --tail=50 orchestrator`. If Ollama is down, restart Ollama (not the stack). |
| Several answers in a row say "I found N records but couldn't summarise them" | The model runner has crashed (CAVEAT-619): `ADD_ID failed / CUDA error: an illegal memory access` in `%LOCALAPPDATA%\Ollama\server.log`. It is upstream of us and recovered on its own last time after ~10 min. **Restart Ollama** — the retry now waits out one crash, but not a repeating burst. The register answers themselves are correct; only the narration is lost. |
| Stale value from a cached answer | Expected within 1 h; explain the cache. |
| Open WebUI login lost | Log in again. Conversations are stored in MongoDB and survive. |

## After the demo

Log every failure or surprise as a `tasks/FIX_TRACKER.csv` row the same day, with the question
quoted, and state whether it was first pass or a retry.
