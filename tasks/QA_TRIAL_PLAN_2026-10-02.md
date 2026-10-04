# QA trial plan — learning from real users, not from a question bank

**Written 2026-10-02, after commit `ab6c081` (main = development).** The sixty-question tails
(C–Q) are spent as a development instrument: every one was drawn from the 2024 survey corpus,
single-shot, and read by one person. A trial with users and supervisors produces something the
tails cannot — conversations, follow-ups, impatience, misreadings of the UI — and the system
has **no way to see any of it today**. That is the first gap, and the plan is ordered by it.

**The number to quote going in:** 65–68% acceptable on unseen single questions, zero fabricated
figures across six sets of ~60. One question in three gets an honest-but-unhelpful decline or a
wrong-shape answer. One user at a time (`OLLAMA_NUM_PARALLEL=1`).

---

## Phase 0 — instrument the trial BEFORE anyone is invited (1–2 days, no routing changes)

Nothing in this phase changes an answer. All of it changes what we learn per answer.

| # | item | why | where |
|---|---|---|---|
| 0.1 | **Per-turn outcome record** | `/v1` returns `ontosage_route` (the lane) but nothing says whether the turn ANSWERED, DECLINED, CLARIFIED or was DELETED by a gate (CAVEAT-887). Every grader guesses from prose. Write `turn_outcome` + the decline producer's name onto the bus and into the `/v1` response; persist both. | `_response_node`, `main.py` /v1 |
| 0.2 | **Transcript export** | Open WebUI stores every chat in Mongo; no script reads it. `scripts/export_trial_turns.py`: user, role, question, answer, lane, outcome, latency, timestamp → one JSONL per day. Hand reads work from this. | new script |
| 0.3 | **In-UI feedback** | No rating or comment reaches OntoSage. Open WebUI's thumbs-up/down hits its own API; add a `/api/v1/feedback` endpoint and the WebUI webhook (or a nightly pull from Mongo's `feedback` collection) keyed on the same chat/turn id. Ask one question on thumbs-down: *wrong / refused / slow / didn't understand me*. | `main.py`, WebUI settings |
| 0.4 | **Side-effect quarantine** | A question can file a maintenance ticket (BUG-1418) or create an alert rule. Tag every `user_reports` and `rules` row created by a trial account; nightly report of them; admins ignore. | `report_intake_service`, alert lane |
| 0.5 | **Provider watchdog** | Ollama died mid-run on 2026-10-01 (CAVEAT-1409) and the breaker opened 134 times. A host-side loop that restarts `ollama serve` when `/api/tags` fails for 60 s, and a `/health` field that says the model is reachable. | host script + health |
| 0.6 | **Daily hand-read ritual** | Every trial day: export (0.2), read EVERY thumbs-down and a random 20 of the rest IN FULL (never a 400-char window — CAVEAT-1293), label with the tail codebook, file rows. The number reported each day is the hand read, never a grader (CAVEAT-1346). | `docs/phase0/CODEBOOK.md` |

## Phase 1 — the failure classes the tails already show, which a trial will multiply (3–5 days)

Ordered by how often a *conversation* will hit them, not by tail count.

| # | class | evidence | approach |
|---|---|---|---|
| 1.1 | **Questions treated as actions** | BUG-1417 (control refusal), BUG-1418 (a ticket from a question), BUG-1241/BUG-200 history | A question is never a command or a report: `is_question` must win when the sentence is interrogative ("if … do the lights turn off?", "can you clean … by yourself?"). Measure over the 4,060 bank + the 7,151 survey questions; the precedence rule has been tuned twice, so the test set for it is the three prior incidents plus these two. |
| 1.2 | **Multi-turn: clarification follow-ups** | Every "which room do you mean?" is a dead end unless the next turn ("2.01") resolves it. Never measured — all tails were single-shot. | A 20-conversation script (`ask_questions.py --conversation`): clarification → answer; answer → "and yesterday?"; "there"/"it" rewrites. Hand-read. BUG-940/941's family. |
| 1.3 | **"Here / nearest / this room" without a location** | BUG-1419 assumed reception; the clarification lane refuses "here" but the spatial lane guesses | One rule: no anchor → ask once, then remember the answer for the session (a per-conversation `where_i_am` fact the rewrite reads). This is the single most common thing an occupant will type. |
| 1.4 | **Relevance-gate deletions** | BUG-1252: four pinned shapes; the gate deletes grounded answers it judges the wrong shape | Count them from 0.1 (`outcome=DELETED_BY_GATE`) for a week before touching the gate again — the last two "fixes" to it were measured and reverted. |
| 1.5 | **Cross-quantity questions** | "empty rooms with lights on" (occupancy ∧ illuminance), "zones heated with zero occupancy" | The deliberation lane already ranks on N modalities; the routing to it from a two-quantity plain question is what is missing (lessons #133/#136). Measure how many bank questions name two measurands. |
| 1.6 | **Vocabulary the building declares and the question doesn't use** | "bathrooms" ≠ ToiletFacility lay terms; "rooftop terrace" ≠ green roof | TTL-first: lay terms on the class, measured over the bank each time (the "resilience" lesson: generic words hijack). Source these from the trial export, not from guesses. |

### Phase 1 status (2026-10-02, evening; nothing committed)

| # | status | what landed | evidence |
|---|---|---|---|
| 1.1 | DONE, verified live | a question is neither a command nor a ticket: `_AUX_BARE_SUBJECT_QUESTION_RE`, `_SUBORDINATE_LEAD_NO_COMMA_QUESTION_RE`, rule `question_is_not_a_report` | BUG-1417/1418 VERIFIED_LIVE; 17 unit tests; real report and real command still behave |
| 1.2 | DONE, verified live on the battery | six deterministic resolvers over the reply being replied to / the user's own turns, run BEFORE the follow-up gate; "which of the three?" when the reply named several; the concept-stage rescue spares a raised clarification; a REP id routes to the status lookup | BUG-1420/1421/1422; `docs/phase0/conversations_2026-10-02_read.md` (before 14/27 acceptable follow-ups; after: see the read doc's re-ask section) |
| 1.3 | DONE in the "state it" form; "remember it" form NOT built | the assumed start is the answer's first line; "I am in room X" straight after re-asks from there | BUG-1419 VERIFIED_LIVE. A per-session `where_i_am` fact is not built: the trial will say whether testers answer the prompt or type the room. |
| 1.4 | DONE as a counter | `scripts/count_gate_deletions.py` tabulates the gate's replacements by day/lane/verdict from the log; run it weekly beside the export | TODO-1431; 4 replacements on 2026-10-02 (24 h) |
| 1.5 | DONE, verified live for routing | rule `two_quantities_over_spaces`: >=2 distinct quantities in a which-rooms shape -> deliberate, counted with both lanes' vocabularies | BUG-1423; the lane's own answer quality is BUG-1424 |
| 1.6 | NOT STARTED, by design | the trial export holds 177 turns, all from the gate's own 51 cases and this session's batteries — no tester question yet. "bathrooms" IS a declared ToiletFacility lay term (`ontology/ontosage_schema.ttl` line 213); tail Q #55's decline is not a vocabulary gap and still needs a live probe. | `scripts/export_trial_turns.py`; `scripts/draw_weekly_tail.py` |

## Phase 2 — what the trial itself will tell us (ongoing, weekly)

- **Weekly: re-draw the live week's questions as the new tail.** Not the survey corpus — the
  actual questions testers typed, de-duplicated, read in full. That is the first set that
  measures what users do rather than what a 2024 survey said they would.
- **Weekly: the two numbers** — hand-read acceptable rate on the week's sample, and the count of
  confidently-wrong answers (the only number that must stay at zero).
- **Weekly: gate + both suites** before any change lands; `cache:intent:*` is retired by the
  restart (CAVEAT-1413), the other two caches are flushed by hand.
- **Weekly: the datasource map** stays open (NOTE-1416) until the owner closes the trial; the
  per-role lists are in the file header.

## What is deliberately NOT in this plan

- **Concurrency** (`OLLAMA_NUM_PARALLEL`, a second runner): owner decision, one user at a time.
  If the trial shows queueing complaints, that is a hardware/host decision, not a code one.
- **The supervisor-agent architecture** (`docs/plan/see if this improves or not.md`): a
  multi-week change; nothing in the trial data will be readable through it for weeks.
- **Re-tuning on tails O–Q.** They are spent. Any new tuning set comes from Phase 2.

## Order of work

0.1 → 0.2 → 0.4 → 0.5 (one day, offline-testable), then invite; 0.3 and 0.6 run from the first
trial day; Phase 1 items are taken in the order the trial export ranks them, not this order.
