# CLAUDE.md

Guidance for Claude Code working in this repo. Keep it lean — deep detail lives in
[ONTOSAGE.md](./ONTOSAGE.md) and [docs/](./docs/). **Read the [Notes](#notes) at the bottom first — they govern how to work here.**

---

## New session orientation (read this first)

**Current branch:** `development` — last commit `a538bf6` (2026-09-18; before it a45bf47 and the three demo-path checkpoints 2292fd7, 8061c06, 19c4b1b — check `git log`
for what is pushed). **Everything from the 18 September evening (Stage 2 work, below) is UNCOMMITTED.** **Never commit or push without the user's explicit approval.**

**Three files every session must read** (in order):
1. `CLAUDE.md` (this file) — navigation index, debugging, workflow rules
2. `README.md` — architecture overview, stakeholder guide, data setup
3. `ONTOSAGE.md` — complete technical reference (source layout, all phases, config)

**Current state snapshot (2026-09-07):**

> This block said branch `main`, V6, and 2,488 tests for weeks after all three stopped being
> true, and carried its own "STALE BELOW" warning pointing at a handoff doc that had also
> aged. A snapshot nobody trusts is worse than none: it costs every session the time to
> discover it is wrong. **If you change the branch, the plan or the suite size, change this
> block in the same commit.**

- **LATEST (2026-09-23, second session) — Waves 1 and 2 of `tasks/PRODUCTION_TRACKER.csv`.
  W1-01/02/03/05, W2-01, W2-02 DONE; W1-04 PARTIAL. Nothing committed; the PARKED suite
  number is still owed.**
  **BUG-873 (P1) is FIXED** — the answer-relevance gate may no longer replace an answer with
  `_unanswered_response` when the turn produced visible evidence, because that text
  ("I couldn't answer that from <building>'s records") is FALSE exactly when a lane has just
  answered from them. It was destroying a `ranked=195 guard_violations=0` deliberation answer
  and a completed forecast. With no evidence visible it replaces as before.
  **BUG-883 (P1) fixed:** a forecast of ONE sensor was presented as a floor's or the
  building's — 1 room of 45, 1 meter of 6 — and for energy that is low by a factor of six.
  Forecasts now fold every bound sensor into one series and STATE the denominator; mean vs
  total comes from the QUANTITY, never the wording (lesson #139).
  Also fixed: BUG-881 (pack #27 said "No readings were found for Floor_2" of a floor with 42
  instrumented spaces), CAVEAT-882 (a rule reading resolved concepts sat in the parse stage,
  passed 11 offline tests and fired zero times live — lesson #138).
  **Routing rules are now 60 parse + 2 post + 5 concept.**
  **Third session, same day — W2-01/02 DONE, W2-03 PARTIAL. Suite 12,594 pass / 0 fail.
  Gate 50/51 (the one is BUG-866).**
  **BUG-884 (P1):** naming a floor bound the sensors NAMED for it, not the sensors ON it —
  "floor 3 vs floor 4" bound eight floor-3 METERS, nothing from floor 4, no temperature sensor
  at all. Now traverses floor → spaces → points, filtered by the resolved Brick class, and
  returns NOTHING when no class resolves (binding arbitrary points off a floor is worse than
  what it replaces). Verified against MySQL: 48 and 56 sensors, means 22.877 / 22.817.
  **THE HIGHEST-LEVERAGE OPEN ITEM IS NOW BUG-879** — the aggregate lane declines any question
  naming a place, which blocks W1-04's room case AND W2-03's interval comparison (BUG-885:
  "Floor 3 is warmer than Floor 4" asserted twice in bold from a 0.06 °C gap against a 3.9 °C
  spread). Fix BUG-879 and both rows become small.
  **The gate's own classifier was wrong three times** (BUG-876, BUG-886, CAVEAT-887): ONE
  question produced THREE honest decline wordings in a day. Every change to the marker list is
  now verified against all 73 stored answers by a test — an intermediate broader pattern moved
  two of them and was rejected for it. lessons #141.
  **The finding that should change how the next session reads the plan: four Wave-1 rows asked
  for something already built.** The multi-read lane (W1-01/02) was the deliberation lane, which
  already ranked on N modalities with coverage and a dossier; the "one SPARQL" for W1-05 was
  `deliberation/coverage_audit.py`, whose first documentation line is the question verbatim; the
  comparison arithmetic for W1-04 was `evidence/matched_comparison.py`, with one caller. Each
  time only the ROUTING to it was missing. **Ask the running system and grep by PURPOSE before
  building what a row names** — lessons #133, #136.
  Fixed and verified live: BUG-869 (a comfort constraint with no direction was refused although
  `_LAY_POLARITY` held the answer), BUG-870 (the word "both" kept two-modality questions out of
  the lane), BUG-868 (a tie at score 1.0 announced as "Best match … fits everything you asked
  for"), BUG-872 (an R² and a row count reported as impossible humidity readings — the fix
  existed and its caller passed 90 chars to a 320-char lookback, lesson #137), BUG-877B (a
  confident "all rooms have a temperature sensor" narrated from a TOTAL sensor count), BUG-878
  (the absence guard replacing a correct counted absence), plus two gate defects (BUG-876,
  CAVEAT-877).
  **Three guards destroyed a correct answer in one session (lesson #135): each detected
  correctly and ACTED too widely.** One is still open and needs the user: **BUG-873 (P1)** — the
  answer-relevance gate discards a successful forecast and leaves nothing.
  **Before sending the evidence pack, read CAVEAT-875**: pack question #1 answers about half the
  time, caused by BUG-873.
  W1-04 is **PARTIAL and says so** — the mechanism is proven live at building scope; a named
  room (BUG-879) and energy (BUG-880) still decline, each with a row.
- **(2026-09-20) — read [`docs/READINESS_2026-09-19.md`](./docs/READINESS_2026-09-19.md) first.**
  Committed 2026-09-20 with bldg1 PARKED. `-m unit` **12,314 pass / 0 fail** building active;
  **12,207 pass / 155 skip / 0 fail PARKED** (what a fresh clone and CI see — 117 tests had failed
  parked because their fixtures read `input/documents`; they now fall back to `bldg1/documents`). Unseen-question weird rate: **61 % → 26.6 %** (tails K+L, n=124; pooled D–J was
  41.2 %), 8.9 % confidently wrong. Register oracle **66/94 → 88/94 (93.6 %)**. Probe **59/60**.
  A local-model **answer-relevance gate** is ON by default (`ANSWER_RELEVANCE_GATE`, data lanes only);
  it once replaced a correct scripted answer, so `CONTRADICTORY` no longer replaces. **Draw a FRESH
  unseen set (tail M) before any verdict** — C–L are spent. Three rules learned today: routing rules
  ALL run and the LAST one wins (put a corrective rule AFTER the one it corrects); a bare `no` in a
  YAML list is `False`; a fail-open component needs a count of how often it *acted*. lessons #124–126.
- **Test suite: measured 2026-09-17 on `-m unit`, and the split depends on whether a building
  is active.** bldg1 up, late 2026-09-17 after the readiness wave: **7,394 pass / 48 skip /
  3 xfail / 1 fail** (13m50s) — the one failure was a source-string test pinning a call's old
  argument list, fixed and re-run 18/18. PARKED — what a fresh
  clone, CI and Workflow rule 8 see: **6,024 pass / 123 skip / 0 fail** (9m37s, 2026-09-16,
  RE-MEASURE OWED — the parked number is now ~1,370 tests behind the active one, and
  parked is the number that gates a commit).
  **DO NOT QUOTE A SUITE DURATION AS A PROPERTY.** The same suite ran **10m20s** and then
  **68m17s** the same afternoon, on identical work: both runs logged exactly 19
  timeout/connection lines and 44 adapter pool failures, every container was idle when checked
  immediately after, and both reported 0 failures. Unattributed, and folded into CAVEAT-500,
  which is the same shape one level down. Quoting one
  number as 'the' suite size is how a green run gets mistaken for a regression.
  **Do not pass `-p no:logging`** — it removes the `caplog` fixture and eight tests report as
  ERRORS that pass 92/92 with logging on (lessons.md #111).
  **Two rules learned the hard way (lessons.md #101, #107):** a long run PINS the tree —
  editing any `.py` mid-run makes every `inspect.getsource` test read the wrong lines; and
  `pytest … | tail -40` reports **tail's** exit code, so redirect to a file and echo `$?`.
  Never write Python source through a shell heredoc: the escapes arrive mangled (a regex
  word-boundary escape arrived as a literal BACKSPACE and silently matched nothing; this very
  sentence lost the escape it was describing, twice). **Live regression probe: 60/60 FIRST-PASS**
  (`python scripts/regression_probe.py`, **18.2 min** measured 2026-09-17 after BUG-663, with
  `resp_cache` flushed first — see below, that flush is not optional).
  **The probe now reports LATENCY PERCENTILES per lane** (nearest rank, no interpolation):
  ALL LANES p50 **12.4 s**, p95 **36.2 s**, slowest **73.8 s**, **0 timed out**. Re-run late
  2026-09-17 after the readiness wave (v17): **60/60 first-pass in 24.6 min**, p50 **16.7 s**,
  p95 **64.7 s**, slowest **167.9 s** — and the slowest is NOT query work: the host Ollama log
  shows a 136-token prompt generating 16,248 tokens until the context filled, empty content,
  retry in 5 s (CAVEAT-727; `OLLAMA_NUM_PREDICT` now caps it). The unit suite ran concurrently,
  so the rest of the slowdown is unattributed. Thirteen of
  sixteen lanes print `— (n<5)` instead of a number, and every p95 that IS printed carries `*`
  because no lane reaches n=20, so its nearest-rank p95 equals its slowest case. **The fix for
  that is more cases per lane, not a lower threshold.** This discharges the measurement half of
  CAVEAT-500; the 10x variance it was opened about did not reproduce.
  **FLUSH `resp_cache:*` BEFORE EVERY PROBE RUN (BUG-662).** The probe does not do it — grep it,
  there is no redis reference at all — so a question you asked by hand in the last hour is
  answered from cache: it reports PASS in 0.0 s, the lane is never exercised, and **a cached
  answer produced BEFORE your change will pass a case that your change has broken.** Observed
  2026-09-17: the lift case passed in 0.0 s having been asked by hand minutes earlier.
  An earlier run took **49.6 min**, and the cause is worth knowing: the publisher had been
  handed every narrow point including the correlated plant series, so it wrote continuously to
  the same MySQL the queries read. Excluding those points restored the time. **A doubling in
  probe wall-clock is a load question before it is a query question.** Four runs on 2026-09-16:
  60, 60, 59, 60 — the 59 was the PROVIDER, labelled `LLM-DEGRADED:empty_completion` by the
  harness itself and correct in 26 s on re-ask, and still counted as a first-pass failure
  (CAVEAT-500).
  **The probe was green THROUGHOUT the worst defect of the day (BUG-631, P1):** every
  floor-scoped SPARQL query was rejected as malformed, and the fallback answered about a
  different floor with a plausible number. Three verification layers saw nothing. It was found
  by asking a question whose answer could be checked by eye — "air quality on floor 3",
  answered from sensors named 5.02. lessons.md #112.
  Earlier the same day the probe DID earn its keep: the register stealing the deliberation lane
  (BUG-623) and a same-floor route counted as a floor pair (BUG-624) both showed up as other
  cases moving. **A probe that moves without the data moving is telling you something** — the
  circulation case answered "nine" and then "15 of 21" from the same 21 rows, because the
  comparison was left to the narration.
  **Per-floor coverage is measured with `scripts/floor_modality_matrix.py`**, which reads
  sensor → space → floor from the graph. `data_coverage_audit.py` parses the floor out of
  sensor NAMES and files ~4,000 of 5,874 under "F?", so its per-floor gaps cannot be trusted
  (TODO-624B found six gases on one floor only that it could not see).
  **What would falsify this line:** adding or removing a probe case, or any change to a routing
  rule. Re-run it, do not edit the number.
  Nothing since `b80c3de` is committed.
- **2026-09-18 evening — Stage 2 of `tasks/IMPROVEMENT_PLAN_2026-09-18.md` is done; READ
  [`docs/READINESS_2026-09-18_STAGE2.md`](./docs/READINESS_2026-09-18_STAGE2.md) and
  [`docs/RECORDING_RUNBOOK_2026-09-18.md`](./docs/RECORDING_RUNBOOK_2026-09-18.md) before any demo.**
  **The verdict: a scripted recording of the 44-question demo path is safe; unscripted questioning is
  not.** Final build, hand-read: demo script **37 good / 4 correct declines / 3 weird**; held-out
  unscripted tail B **21 of 38 weird (55%)**, and 19 of 38 on a repeat; **11 of 14 rewordings written
  after a failure were weird too**; regression probe **58/60**. One scripted question is wrong
  (BUG-835: refuge-point "who owns them" says there is no owner field; there is one). Unit suite
  (bldg1 active): **8,206 pass / 1 fail (a pinned-wording test, updated) / 48 skip / 3 xfail**; the
  PARKED number is still owed. **"Good" counts are an upper bound**: two labels were wrong until the
  source table was checked (`docs/phase0/demo_rehearsal_2026-09-18_corrections.md`, lessons.md #121).
  Open defects from this session: BUG-808..835 / CAVEAT-816, 817, 833, 834 (all owned in V12 `IMP-A`).
  Instruments added: `scripts/decompose_outcomes.py` (W03), `scripts/redis_hygiene.py` (W01),
  `ontosage_route` on every `/v1` turn (W04), `docs/phase0/CODEBOOK.md` (W06, SHA-pinned).
- **ACTIVE WORKSTREAM: V12 — the plan after the supervisor review.**
  Built from four sources and no others: the review
  (`docs/OntoSage_Architecture_Review_Corrected_v1.1.pdf`, 33 pp.), the V10 and V11
  leftovers, and `tasks/FIX_TRACKER.csv` — the live defect log, which V11 read only for the
  four rows marked `OPEN` and which also holds `PARTIALLY_FIXED`, `MITIGATED` and seven rows
  closed with a written admission that the live re-ask never happened.
  **Read in this order:** [`docs/V12_MASTER_PLAN.md`](./docs/V12_MASTER_PLAN.md) — scope,
  order, and what is deliberately not being done — then
  [`docs/V11_PHASE0_INVENTORY.md`](./docs/V11_PHASE0_INVENTORY.md), which is still the
  code-verified status of the review's nine risks and is NOT superseded.
  **Execution: [`tasks/V12_TRACKER.csv`](./tasks/V12_TRACKER.csv) — 34 rows, ONE file.**
  Counted from the file on 2026-09-12: `needs_gpu` is a column — `yes` (**8**) needs a live
  model throughout, `no` (**11**) needs none, `partial` (**14**) builds and tests offline then
  verifies on live turns. Total **43.5 days**. It was 31 rows / 42.0 days until 2026-09-12,
  when V12-32 and V12-33 were added for work the coverage audit refused to let go unclaimed —
  which is the audit doing its job, not scope creep.
  `gate_a`, `status`, `started`, `completed` and `evidence` are progress columns; **do not
  add a second tracker file** — two disagreeing V7 trackers is how a fresh clone got the
  stale one.
  **V5, V6 and V7 are OUT OF SCOPE** (user decision, 2026-09-09): their substance shipped and
  their trackers carry stale status, not open work — freshness/staleness,
  `answer_provenance.py`, `enablement_hint` declines and the baseline harnesses are all in the
  code. Two concepts from those plans had NO code when checked and are the only resurrection
  candidates: `CONFLICTED` as a verification state, and purpose-bound permission. **File
  either as a NEW `FIX_TRACKER` row** rather than reviving a status column.
  **Completeness is proved, not asserted:** `python scripts/v12_coverage_audit.py` re-derives
  the open set — including closed rows whose own text says work is owed — and fails if
  anything is unclaimed, claimed twice, or claimed but already done. Run it at session start.
  Currently **133 derived · 110 scheduled · 23 dispositioned · 0 uncovered** (2026-09-12).
  It went from 109 to 128 in one session because nine new defects were logged and each one
  had to find an owner before the audit would pass again.
  **Reconciliation:** [`tasks/V12_LEDGER.csv`](./tasks/V12_LEDGER.csv) and
  [`tasks/V12_WONTDO.csv`](./tasks/V12_WONTDO.csv) (23 items, a written reason each).
  **Target unchanged: Gate A — a defensible demonstration of bldg1 with a written supported
  scope.** Not a pilot, not portability.
  **Order:** the verification debt is paid before the routing work. V12-01 leads; no routing
  change lands without the probe green before AND after, one rule at a time.
  **ACTIVE SUBSET: the 17 rows flagged `gate_a=yes`, of which 12 are DONE and 8.5 days
  remain (2026-09-12).** Remaining, and **every one now needs a live model or live turns —
  no offline row is left**: **V12-05** (finish the series-catalogue probe), **V12-34** (one
  sensor, one authoritative timeseries reference — BUG-531), **V12-32** (re-ask the ELEVEN
  live checks now owed, before V12-29, because a sealed run over unverified fixes measures
  the fixes), **V12-25** (ARBITER end to end) and **V12-29 LAST** (the sealed set, run once,
  Gate A decided).
  This line used to say the subset was **V12-01 → V12-08, about 12 days**, and that was
  wrong: Gate A (review p. 22) additionally requires matching units and intervals (V12-09/10/11),
  zero privacy failures in scope (V12-17), rankings from ARBITER's dossier (V12-25), and the
  published cases and rubric (V12-29). Eight rows do not reach the gate they were said to reach.
  **V12-26 moved from order 26 to order 3** on 2026-09-09: the review makes T01 (the supported
  scope) a prerequisite for T03/T04/T05/T06, and writing it early can only shrink the 12 rows
  behind it. The 17 rows flagged `gate_a=no` (21.0 days) are the post-Gate-A backlog, not
  decoration.
  Superseded but kept for their reasoning: `docs/V11_IMPLEMENTATION_PLAN.md`,
  `tasks/V11_TRACKER.csv`, `tasks/V10_TRACKER.csv`, `tasks/V10_REMAINING_PLAN.md`.
- **W0-2 is done: the capability short-circuit is INVERTED (2026-09-08).** The document-KB
  probe no longer returns `intent=capability` before classification; it runs after the
  classifier and the routing contract, over weak intents only, and the nineteen `and not`
  escape clauses are thereby made unnecessary rather than deleted. Probe 50/50 including all
  17 capability-bypass cases recorded for exactly this change, so it is not a silent trade.
  **`metadata` and `discovery` are deliberately NOT overridable** even though the contract
  calls them weak — BUG-440 was a structural question losing to a register.
- **The report lane worked for the first time on 2026-09-07/08.** Six defects in one chain,
  all found by asking one question and none by the suite, which passed throughout:
  a workflow deadline SHORTER than one LLM call inside it (BUG-473); a SQL prompt naming all
  704 wide-table columns, 45,573 chars against a 16k context (BUG-474); an empty result
  narrated as "a critical monitoring gap … deploy a secondary CO2 device" for a room
  recording 77,088 readings a day (BUG-475); `_standardize_results` with **no return
  statement**, so every planned query silently lost its SPARQL results (BUG-476); the report
  agent reading rows one level too shallow, so no report had ever seen its data (BUG-477);
  and a report headed "Yesterday" describing today (BUG-478).
- **The ECA rules engine was live and inert, and now is not.** `settings.ONTOLOGY_NAMESPACE`
  never existed, and the AttributeError surfaced as "concept resolve failed" — blaming the
  concept resolver for a fault two calls away (BUG-481). Fixing it removed the error and not
  the failure: the query joined on `brick:hasExternalReference`, which exists twice in the
  whole repository, instead of `ref:` which has 2,860. And the value fetcher named
  `sensordb.sensor_data` outright, so every point in a narrow table was invisible to the
  whole feature (BUG-485). Concept rules now bind to reporting points across both store
  shapes.
- **The literal guard now covers five trees and the compose files** and passes at 0 ERROR /
  72 INFO. It scanned two directories and reported "clean" while 15 real literals sat outside
  its scope.
- **bldg1 is the active building.** Committed state = NO building active (Workflow rule 8).
- **V12-08/09/10/11/17 landed 2026-09-12, and every one found the SAME shape of defect:** two
  parts of the system holding their own answer to a question only one of them should own.
  `yesterday` had three answers, two of them the rolling-24-hours answer BUG-480 was fixed to
  stop giving — and in ARBITER `yesterday` and `today` were the SAME 24.0 hours, fetched from
  `utcnow()` with no upper bound (**BUG-517, P1**). A narrow-table report averaged 900 ppm of
  CO2 with 21.5 °C into `avg=590.5` because it grouped by column and the narrow column is
  called `value` (**BUG-521, P1**), while `units.aggregation_decision()` — built for exactly
  that in V12-04 — had never been imported by anything. Every report named its OLDEST reading
  the latest (**BUG-520**). A co-reference rewrite could swap the room the user named, and
  because the rewrite replaces the query everywhere downstream the existence gate could not
  catch it (**BUG-524**). **Nine of these fixes are FIXED-but-unverified-live; V12-32 owns
  that queue and is sequenced BEFORE V12-29**, because a sealed run over unverified fixes
  measures the fixes, not the system.
- **CLOCKS, corrected 2026-09-15: every store is UTC, and every reader must compare in UTC.**
  Adapters pin MySQL sessions to `+00:00` (BUG-403). `sensor_data.Datetime` is a TIMESTAMP that
  MySQL converts to the SESSION zone on read, so a hand measurement through a default (BST)
  connection makes it look local — that artefact produced three wrong "fixes" on 2026-09-12
  (BUG-518/519 and the ARBITER fetch fallback, all reverted, both bugs WITHDRAWN) and a withdrawn
  P1 on 2026-09-15 (BUG-538). Use `requested_interval.store_now()` against stored rows; choose the
  LOCAL day a word names, then convert its bounds with `to_store`; convert only for display with
  `to_local` (BUG-540, open). When measuring MySQL by hand, set `time_zone='+00:00'`. lessons.md #103.
- **Demo Friday 2026-09-18 14:00 via Open WebUI** (which uses `/v1/chat/completions`, not the
  `/chat` endpoint the probe uses). Schedule and autonomous-run todos: `tasks/V12_TRACKER.csv`
  `planned_day` column, rows DEMO-01..07 and RUN-01..14.
- **V12-13/15/19/20/27 landed 2026-09-12 — the five rows needing NO GPU are done.** The
  three that found the most: `Settings` reads 122 settings and `.env.example` named 69, two
  of the missing being values `STRICT_SECRETS` **refuses to boot on** (V12-27); `_safe_node`
  recorded every failure as `str(e)`, which on a message-less exception is the EMPTY STRING —
  now five typed outcomes, and CAVEAT-415 closed at the LOGGER so all 871 bare `{e}` sites
  are covered at once (V12-19); and adapter parity proved **against real servers**, identical
  statistics AND identical evidence through a Timescale hypertable and a Cassandra
  partitioned table (V12-13).
  **Two findings worth reading before trusting a measurement here.** The naive
  graph-shadowing sweep reports **11,145** subjects and every one is inference
  (explicit-only: zero — CAVEAT-530); and **BUG-531 (P1)**, 77 sensors carry two timeseries
  references, a synthetic store and a real one, and the SQL lane merges both into one
  answer's statistics — while the project's documented fan-out metric reads **1.00
  throughout**, because each reference has its own uuid. V12-34 owns the fix.
  **The owed-live-check queue now stands at eleven** and is owned by V12-32, sequenced
  BEFORE V12-29.
- **No P1 is open** except BUG-531, logged 2026-09-12 and owned by V12-34. Remaining: TODO-463 (BuildingLexicon built at boot, routing does not
  consume it), CAVEAT-467 (floor comparison slow), BUG-482 (a concept rule watches ONE point
  of however many carry the class — now logged and chosen for being live, but still one),
  TODO-484 (audit the other 49 probe cases for markers that decay with the calendar, as the
  overdue-calibration count did: 194 → 201 → 206 while the system stayed correct).

**Open issues / pending decisions:**
- **V5 is NOT the active workstream** — this bullet said it was, for three weeks after it
  stopped being true, while the snapshot above named a different one. Two active workstreams
  in one file is how a session spends its first hour on the wrong plan. V5, V6 and V7 are OUT OF V12 SCOPE
  (2026-09-09): their substance shipped. The multi-model benchmark is the one live remnant
  and it is BLOCKED on a paid plan, not on us — see docs/V12_MASTER_PLAN.md §6. V4 is DELIVERED (36/36, `tasks/V4_TRACKER.csv`). V5 design and
  handoff are kept as the record of how the pillars were defined:
  [`tasks/IMPROVEMENT_PLAN_V5_UNIVERSAL_COVERAGE.md`](./tasks/IMPROVEMENT_PLAN_V5_UNIVERSAL_COVERAGE.md),
  [`tasks/V5_HANDOFF.md`](./tasks/V5_HANDOFF.md) — user decisions logged there are still
  decisions; do not re-ask them.
- **Certified bldg2 scorecard (2026-08-19):** COVERAGE 26.2% data-backed / **80.6%
  combined** (237 graded, +3 quarantined) · PROTECT **0.0% leak** over 37 applicable
  traps with the PDP **enforced** · DETECT **96.9% recall** (31/32) · PREDICT **CI95
  0.92**. Artifact: `scripts/outputs/V5_SCORECARD_bldg2_*.md`. All on the LOCAL
  `gpt-oss:20b`, which BEAT the hosted 120B on coverage (80.6% vs 78.8%) — the quota
  exhaustion costs nothing scientifically.
- **The LLM provider is `local` (`gpt-oss:20b`) as of 2026-08-18.** The hosted trial ran on
  Ollama Cloud `gpt-oss:120b`, but its rolling ~5-hour call budget was **exhausted** during
  the T44 benchmark and every cloud call now returns HTTP 429 — so no real work can be done
  on cloud until the window resets. Embeddings were already `local`, so nothing needed
  reindexing. Switch with `MODEL_PROVIDER=` in `.env` **plus `docker compose up -d`** —
  `restart` silently keeps the old environment (CAVEAT-178). Only 7 of the 19 hosted models
  are reachable on this key at all: `gpt-oss:120b/20b`, `gemma4:31b`, `minimax-m3`,
  `nemotron-3-nano:30b/-super/-ultra`. deepseek-v4-*/qwen3.5/glm-5.x/kimi-*/mistral-large-3
  all return HTTP 403 "requires a subscription" — a **paid plan** is needed to benchmark
  those, which is the one open item that needs the user.
- **Live fix/caveat log + backlog: [`tasks/FIX_TRACKER.csv`](./tasks/FIX_TRACKER.csv)** — read it at session start to see what's OPEN vs fixed; keep it updated (Workflow rule 7). FIX-001/002/003 done (verified live). **TODO-010→011→012 DONE (2026-07-28):** `capability.yaml` is **removed** — capabilities are now `ontosage:Amenity` / `ontosage:KnowledgeTopic` **triples** (authored via the admin Capabilities GUI `POST /api/v1/admin/capabilities` or the OCBV TBox `input/ontosage_schema.ttl`), answered by the `CapabilityGraphResolver`. Routing is a single TTL-first path (the Qdrant capability-KB probe is gone). Migration: `scripts/migrate_capability_yaml_to_ttl.py`. **Remaining: `TODO-081`** — excise the now-dead capability-KB infra (`capability_indexer`, `semantic_router.classify`, `shared/capability_schema.py`); it no-ops harmlessly today. Design/why in [`tasks/TODO_012_CAPABILITY_YAML_REMOVAL_STEP.md`](./tasks/TODO_012_CAPABILITY_YAML_REMOVAL_STEP.md) + [`tasks/TTL_NATIVE_CAPABILITIES_PLAN.md`](./tasks/TTL_NATIVE_CAPABILITIES_PLAN.md).
- ALL changes need user review and explicit commit approval before any `git commit` or `git push`
- **Tracker: 223 rows as of 2026-08-22** (7 not closed). **Tracker: 193 rows as of 2026-08-19.** Fixed this session, in the order the evidence
  arrived: **BUG-189** (P1 FABRICATION — a room's reading attributed to a "public corridor"
  bldg2 does not have, because the referent gate matched FLOORS BEFORE SPACES so an existing
  floor let an unverified space through); **BUG-191** (P1 — the leak grader counted the "2"
  inside `bldg2` as a sensor reading, so refusals scored PASS and a run reported a spurious
  39/39); **BUG-188** (2.7% of local turns returned empty completions from a 29,705-char
  prompt against an 8192 context — `OLLAMA_NUM_CTX` now 16384, costing +200 MiB with the
  model still 100% on GPU); **BUG-194** (P1 — a GUI policy edit was SHADOWED by a stale copy
  in the default graph: file and named graph correct, API and enforcement using the OLD
  value, editor reporting success); **BUG-195** (P1 — the sparql lane could answer a reading
  question with NO PDP chokepoint, and "how many people" was not recognised as
  presence-adjacent so the k-check was skipped even when the PDP ran); plus BUG-186,
  CAVEAT-182/190/193.
- **The measurement apparatus was wrong more often than the system.** Four of the five P1s
  above were in graders/harnesses, and the same weak heuristic ("any digit means it
  answered") hid a fabrication one day and manufactured a perfect score the next. When a
  number looks perfect, read the rows behind it — see `tasks/lessons.md` #20-22.
- **This bullet used to list BUG-192, CAVEAT-193, CAVEAT-190 and TODO-181 as open. All four
  are closed** — as are BUG-147, TODO-143, KNOWN-008, KNOWN-153, CAVEAT-148 and CAVEAT-154,
  which the P1 bullet below still named. Checked against `tasks/FIX_TRACKER.csv` on
  2026-09-09. **Do not hand-maintain an open list here again** — it went stale within days
  every time. `python scripts/v12_coverage_audit.py --list` prints the real one, derived from
  the trackers, and `tasks/V12_LEDGER.csv` says where each item went.
- **BUG-184 — root cause found, fix landed, re-measure owed.** `plan_hash` is
  `sha256(plan_fingerprint | sorted candidate IRIs | fetch_window | time basis)`, and the
  candidate set excludes *currently-busy rooms* — so on a live building it MUST differ
  between runs by construction. It identifies what was computed, not how the system
  reasoned, and the T44 invariance probe was comparing it. A layered probe (host Ollama,
  temp 0, identical prompt, 6 repeats) showed the provider does return different text at
  temp 0, but the parser absorbs nearly all of it: CQ-IR fingerprints came out 1/6, 1/6,
  2/6 distinct. `cqir.plan_fingerprint()` — documented as "the determinism anchor" — was
  never surfaced; it is now published in the dossier and `plan_trace` alongside
  `plan_hash`, and the benchmark compares it. **Compare `plan_fingerprint` across runs;
  `plan_hash` is provenance.** Residual: one query still compiles two ways — shrink via the
  deterministic folds or a compile cache.
- **Remaining P1-class work, verified 2026-09-09:** TODO-072 (`FIXED_UNVERIFIED` — the cold
  GUI-only onboarding has 18 offline tests and no cold live run; verified by **G17**, not
  separately), BUG-218 (`PARTIALLY_FIXED` at 70.4% document precision → **N17**), CAVEAT-415
  (`PARTIALLY_FIXED` — 62 failures logged an empty message → **N15**). BUG-147, TODO-143,
  KNOWN-153, CAVEAT-148 and CAVEAT-154 are closed.
- **Routing overrides live in ONE contract**: `orchestrator/services/routing_contract.py`
  (**60** parse-stage + 2 post-stage + 4 concept-stage ordered rules, counted FROM THE MODULE
  again 2026-09-23; it said 43+2+3 and had gone stale a fourth time;
  2026-09-17 — this line said 17+1+1 for weeks after it stopped being true, then 36+1+3 for
  another nine days, which is the same failure twice. Count it, do not read it: `python -c
  "from orchestrator.services import routing_contract as r; print(len(r.PARSE_STAGE_RULES),
  len(r.POST_STAGE_RULES), len(r.CONCEPT_STAGE_RULES))"`; order
  pinned by `tests/test_routing_contract.py::test_precedence_order_is_pinned` — update that
  test in the SAME commit as any rule change). Add/change a routing rule THERE — never as a
  new inline override in `dialogue_agent`.
- `data/mysql-init/init.sql` creates `abacws` DB (legacy); live system uses `sensordb` — mismatch is inert (MySQL container is disabled; host MySQL used directly)
- Maintenance agent "report broken light" → generic fallback (tracked as KNOWN-008)
- **bldg1 `sensor_data` (wide) = REAL snapshot + INTENTIONAL dev-mode top-up — user-confirmed
  2026-08-13, BUG-144 resolved as by-design. Do not "fix", purge, or relabel.** The physical
  abacws sensors feed a separate real DB (3 years of readings, still collecting) that this
  dev machine does NOT receive; the user manually loaded a real snapshot (2025-01-01→
  2025-03-09) into local `sensor_data`, and `data-publisher` deliberately extends it with
  generated "latest" rows (`PUBLISH_WIDE=true` in compose) so real-time questions are
  testable during development. Everything else (all other modalities/buildings) is synthetic
  and live-generated, labeled as such. **End of development (user will do):** disable the
  generator (`PUBLISH_WIDE=false` / remove service) and repoint `database_registry.yaml`
  `database1` at the real/cloud DB. `nature: real` stays as-is throughout.

---

## Core design contract — what OntoSage IS (check every solution against this)

OntoSage is an **agentic conversational layer over one smart building's own data** — *"connect a
building's data, then ask it anything in plain English."* The points below are **non-negotiables**.
When you propose or write a solution, verify it honors every one — a solution that violates any of
these is wrong for this project even if it "works." Depth lives in `ONTOSAGE.md`.

1. **One building at a time.** v1 serves a single active building (`BUILDING_ID`). Multi-building is
   *forward-compat only* (registries keyed by `building_id`, per-building Qdrant collections + persona
   overlays) — never assume multiple live buildings, and never break the single-building path.

2. **TTL-first — the ontology is the source of truth.** If a fact can be an RDF triple, it belongs in
   the Brick/BACnet TTL, not a sidecar YAML or a code constant. Answer via SPARQL on GraphDB first;
   fall back to SQL / analytics / capability KB only for live time-series or computation RDF can't
   express. To add a capability, **extend the TTL before adding code.** Depth: the *TTL-first design
   principle* section below.

3. **No hardcoding → building-agnostic.** Core code and `shared/` carry **zero** building literals
   (namespaces, zone ids, sensor counts, areas, floor lists). Resolve everything from the active
   building: `_active_namespace()` / `bctx`, `input/database_registry.yaml`, floor-plan manifests. Any
   number in an answer is **computed live** (SPARQL `COUNT` / DWG geometry), never a frozen literal.
   Litmus test: *would this run unchanged for `bldg2`?* If not, it's wrong.

4. **Honest, grounded answers — never fabricate.** Every figure traces to live data (graph / DB / floor
   plan). If a referent doesn't exist or the data isn't loaded, **say so** (referent-existence gate,
   honest "no data") — never surface a plausible-but-wrong value. Grounding beats fluency.

5. **Any stakeholder, any purpose.** One NL interface serves facility managers, occupants, researchers,
   sustainability / safety officers, executives, visitors, students, admins. Personas bias
   *classification + response framing* only (**not** permissions). Build intent-routed, persona-framed
   features — never single-persona ones.

6. **Zero-knowledge → expert coverage.** Users need no SQL / SPARQL / schema knowledge — lay terms
   resolve via the HBCO concept resolver ("stuffy" → CO₂). The same system also serves experts (Brick
   classes, RDF types, the admin SPARQL browser). A solution must span that range and degrade gracefully.

7. **Admin-controlled access (RBAC).** Every data / config endpoint is gated by `require_permission()`;
   ontology CRUD and reindex require `system:admin`. Personas ≠ RBAC roles. **Never** add an
   unauthenticated data endpoint.

8. **Connect-data → get-answers.** A question is answerable when (a) the sensor is a triple in GraphDB
   **and** (b) its readings are rows in a registered DB, linked via `ref:hasTimeseriesId` +
   `ref:storedAt`. Both halves are required. Onboarding a source = drop TTL + register the DB + load
   rows — **no code change.**

9. **Multiple datasources, pluggable.** Time-series routes by `ref:storedAt` → adapter registry → the
   right backend. MySQL (wide/narrow), PostgreSQL, **TimescaleDB 2.11 and Cassandra 4.1 are live and
   test-covered** (TODO-143 — start them with `docker compose -f docker-compose.timeseries-backends.yml
   up -d`, seed with `scripts/seed_timeseries_backends.py`); Influx / Mongo / SQLite / Redis-TS adapters
   exist but are not yet exercised by a fixture. A new backend is **a new adapter**, never edits to the
   agents.

10. **Local or API models, independently.** `MODEL_PROVIDER` = `openai` / `local` (Ollama) / `cloud`;
    `EMBEDDING_PROVIDER` is independent. Never hardcode a provider or model — go through `llm_manager`
    + `shared/config.py`. Solutions must work under both local and API providers.

11. **`docker-compose up -d` is all you need.** The whole stack boots with one command; config lives in
    `.env` + `input/`. Don't add setup steps outside compose / `.env`, and don't assume host-installed
    tools.

---

## Commands

```bash
# Stack
docker-compose up -d                                   # start all services
docker-compose build orchestrator && docker-compose up -d orchestrator   # rebuild one
docker-compose logs -f orchestrator                    # live logs

# Health
curl http://localhost:8000/health   # orchestrator (8001 rag, 8002 code-executor)

# Tests
pytest tests/ -v                                       # all (live e2e need the stack up)
pytest -m unit            # fast / offline      pytest -m integration   # needs services
pytest tests/test_routing_accuracy.py -v               # single file
# CI deterministic suite = 423 tests (2 skipped) on 3.10/3.11/3.12 (see .github/workflows/ci.yml)

# Lint (run before commit)
black --line-length 100 orchestrator/ shared/ scripts/ tests/
isort --profile black orchestrator/ tests/
flake8 orchestrator/ shared/ scripts/ --select=F821,F823   # the only BLOCKING gate
bandit -r orchestrator/ shared/ -ll --exclude orchestrator/tests

# QA — the canonical end-to-end check (every persona × intent × flow)
python scripts/ontosage_qa_suite.py            # full battery → scripts/outputs/qa_run_<ts>.{json,md}
python scripts/ontosage_qa_suite.py --quick    # fast sample
python scripts/ontosage_qa_suite.py --ids RI05,VZ01 --convos CONV5   # targeted re-test
```

### Onboard / swap a building
```bash
python scripts/onboard_building.py --building-id bldg2 --non-interactive   # generate config
# Swap the ACTIVE building (v1 serves one at a time):
python scripts/swap_building.py --to bldg2 --dry-run    # validate (TTL @prefix bldg: ↔ ontology_namespace)
python scripts/swap_building.py --to bldg2 --archive    # apply: update .env, archive old, flush resp_cache
docker-compose restart orchestrator                     # TTL validator runs first; hard-fails on mismatch
```

### "Run building N" — the swap-by-rename procedure Claude executes on request

When the user says **"run building 1" / "run bldg2" / "switch to bldg3"** (any phrasing),
perform this EXACT sequence — never skip the down step, never guess identities:

1. **Identify the current active building** (if any): `grep BUILDING_ID input/env.building`.
   If `input/` doesn't exist, all buildings are parked — skip to step 3.
2. **Down the running stack FIRST** — renaming while up breaks the bind mounts
   (`/app/input` goes empty, CAVEAT-088/verified 2026-07-30):
   `docker compose -p ontosage_<oldN> down`. If the canonical `.env` is already gone,
   the BUILDING_ID guard blocks interpolation — pass the env explicitly:
   `docker compose --env-file .env<oldN> -p ontosage_<oldN> -f docker-compose.bldg<oldN>.yml down`
3. **Park the old active set** (names must match its OWN identity, read from
   `input/env.building` — never assume): `input/`→`bldg<oldN>/`, `.env`→`.env<oldN>`,
   `docker-compose.yml`→`docker-compose.bldg<oldN>.yml`
4. **Activate the target**: `bldg<N>/`→`input/`, `.env<N>`→`.env`,
   `docker-compose.bldg<N>.yml`→`docker-compose.yml`
5. **Sanity before boot** (all three must agree on bldg<N>): `.env BUILDING_ID` ==
   `input/building.yaml building_id` == `input/env.building BUILDING_ID`, and
   `.env COMPOSE_PROJECT_NAME` == `ontosage_bldg<N>`.
6. `docker compose up -d`, then poll `http://127.0.0.1:8000/health` until 200.
   Cold GraphDB warm-up can take minutes — ontology init self-heals (retry after TTL
   ingestion + ~7-min backstop, BUG-100). Then verify isolation: GraphDB triple count
   in the building's own namespace > 0 and other buildings' namespaces == 0;
   `data-publisher` env `MYSQL_DATABASE` matches the building's DB.
6b. **A building not booted in a while runs STALE IMAGES, and a source fix is not
   deployed until its image carries it** (BUG-343). Compose tags images per project
   (`ontosage_bldg<N>-<service>`), and neither `restart` nor a plain `up -d` rebuilds
   one that already exists. bldg3 booted a four-week-old rag-service and silently
   resumed the context-less ingestion that caused the 20M-triple bloat — source
   correct, suite green, deployed thing broken. Check with
   `docker compose images <service>` (the CREATED column), and rebuild anything older
   than the fix you rely on. Then measure the SYMPTOM rather than trusting the fix:
   `python scripts/certify_building.py --expect bldg<N> --preflight-only` reports
   timeseries reference fan-out, which must be ~1.00 copies/UUID. Above ~1.5 the graph
   holds duplicates: back up, prove the loss is zero with a **subject-level** diff
   (live IRI subjects vs everything `input/*.ttl` names — inference cannot confound
   that, type counts can), then drop, delete `volumes/<id>/artifacts/.ttl_uploads.json`
   so the SHA skip does not suppress re-upload, and restart the orchestrator.
7. **Flush the response cache** before any testing:
   `docker exec redis-memory-store sh -c 'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL'`

**Input layout — FLAT is canonical.** The active building's files sit directly under
`input/`: `input/building.yaml` + `input/*.ttl` (required — incl. `<id>_capabilities.ttl`
for `ontosage:Amenity`/`KnowledgeTopic` triples); `*.dwg`, `*.pdf`,
`intents.yaml`, `documents/` (uploaded manuals), `personas/` (optional). The nested form
`input/<id>/…` is still supported as a *fallback* (staging / future multi-building). All
per-building loaders resolve paths via `shared/building_paths.py`
(`resolve_building_file`/`resolve_building_dir` — nested first, then flat), so don't hardcode
either form. Swap exits non-zero if neither layout exists, `building.yaml` lacks required keys
/ `building_id` ≠ declared id, or a TTL prefix disagrees with `ontology_namespace`.

> **Sensor data belongs in a database, not in `input/`.** `input/` holds metadata/config only.
> Time-series readings live in a DB (MySQL/Postgres) and are referenced from the ontology via
> `ref:hasExternalReference → ref:TimeseriesReference (ref:hasTimeseriesId + ref:storedAt)`.
> Raw CSV sensor files in `input/` are deprecated — see
> `tasks/IMPLEMENTATION_PLAN_FLAT_LAYOUT_AND_DATA_PIPELINE.md` (Workstream B).

**V3 per-building optional files** (validators in `services/input_validators.py`):
`feeds.yaml` (live data sources), `recipes.yaml` (override/extend), `rules.yaml` (ECA alerts),
`channels.yaml` (notification dispatch), `benchmarks.csv`, `concepts.ttl` (lay-term overlay),
`documents/` (policy/manual KB). All optional — absent = feature silently skipped.

```bash
# Corpus replay — measure answerable share (requires live stack)
python scripts/corpus_replay.py                    # 240q stratified (40 per L1-L6)
python scripts/corpus_replay.py --sample 60        # quick smoke test
python scripts/corpus_replay.py --out-prefix <ts>  # resume a previous run
```

---

## Architecture

`orchestrator/workflow/` is a **LangGraph** state machine (package: `_orchestrator.py` = nodes
+ `_route_from_dialogue`; `_graph.py` = `_build_graph`/`_safe_node`; `_routing.py` = downstream
routes). Per request:

```
POST /chat (or /v1/chat/completions)
  → [co-reference rewrite]  → dialogue (intent + entities)  → route
  → sparql → sql → analytics/forecast → visualization        (data flows)
  → capability / floor_plan / spatial / report_intake / control / planner  (standalone)
  → response → [persist memory]
```

- **Nodes auto-register** from `orchestrator/intents/intent_definitions.yaml` (no graph edits to add an intent).
- **dialogue** (`agents/dialogue_agent.py`): LLM classifies intent + extracts entities; runs the
  co-reference rewrite and the capability semantic-router probe first.
- **sparql** (`agents/sparql_agent.py`): SPARQL gen+exec on GraphDB (7200), RAG fallback (8001); returns UUIDs.
- **sql** (`agents/sql_agent.py`): time-series by UUID via storage adapters (MySQL bldg1).
- **analytics** (`agents/analytics_agent.py`): LLM Python → sandboxed `code-executor` (8002).
- **forecast** (`agents/forecast_agent.py` + `services/forecasting/`): multi-model (ARIMA/ETS/linear), runs inside the `trend` pipeline.
- **floor_plan / spatial** (`agents/floor_plan_agent.py`, `spatial_agent.py`): PDF/DWG manifests; no LLM for spatial.
- **capability** (`agents/capability_agent.py`): single TTL-first chain — live metrics → ontology capability **triples** (`ontosage:Amenity`/`KnowledgeTopic` via `CapabilityGraphResolver`) → uploaded documents (Qdrant `documents_<bldg>`) → honest "no info". No `capability.yaml` / Qdrant capability-KB (removed, TODO-012).
- **report_intake** (`services/report_intake_service.py`): fault/complaint/safety/feedback/suggestion → `user_reports`.
- **sql adapters** (`services/adapters/`): `registry.py` routes by `ref:storedAt` key → `mysql_adapter.py` (wide `sensor_data` table) or `mysql_narrow_adapter.py` (narrow `(uuid, datetime, value)` per-modality tables — P0 addition).

**P0 additions** (all behind `system:admin` RBAC):
- **Admin endpoints** (`main.py` — 8 new routes under `/api/v1/admin/`): ontology CRUD + Qdrant reindex job queue.
- **Ontology manager** (`services/ontology_manager.py`): async GraphDB admin via httpx — list/validate/upload/drop named graphs + SELECT browser.
- **Reindex service** (`services/reindex_service.py`): background job queue for re-embedding capability/documents/floor_plans into Qdrant. Singleton `_reindex_service_instance` in `main.py`.
- **RBAC** (`middleware/rbac.py`): `require_permission(perm)` → `get_user_context` dependency chain; all data endpoints now return 401 without valid session.
- **Admin React portal** (`frontend/src/pages/AdminPortal.js`): 11-tab UI at `/admin` (Policies added by
  V5-T43; **Onboarding** added by TODO-072 and now the default tab); backed by the admin endpoints above.
- **GUI-only onboarding** (`services/onboarding_status.py`, `GET /api/v1/admin/onboarding/status`,
  `components/admin/OnboardingTab.js`): a building is onboarded end-to-end through the console —
  identity → TTL → datasource → documents → floor plans — with per-step readiness read from the LIVE
  system (spaces in the graph; declared sensors vs UUIDs that actually have rows; share of floor-plan
  spaces linked to an IRI), never from a checklist. `identity` and `ontology` are blocking; the rest
  narrow what can be answered rather than breaking it.

**V3 additions** (all config-driven, zero code for new buildings):
- **HBCO concept resolver** (`services/concept_resolver.py`): lay-term → Brick class + recipe via `ontology/hbco_core.ttl` + `hbco_mappings.ttl`; per-building overlay `input/<id>/concepts.ttl`. Injected into dialogue + SPARQL + analytics.
- **Feed framework** (`services/feeds/`): config-driven live data — `rest_poll`, `csv_drop` adapters; point auto-registration in GraphDB; `input/<id>/feeds.yaml`.
- **ECA rules engine** (`services/rules_engine.py`): standing event-condition-action rules evaluated against telemetry; `input/<id>/rules.yaml`; notification dispatch via `services/notification_service.py` + `input/<id>/channels.yaml`.
- **Actuation gateway** (`services/actuation/`): `ActuationDriver` ABC → `SimDriver` (log-only, Postgres `actuation_log`) → `ActuationRegistry`; `input/<id>/building.yaml` `actuation:` block.
- **Goal planner** (`services/goal_planner.py`): mandate decomposition ('make eco-friendly') → KPI sub-queries; `config/goals.yaml`; `GOAL_PLANNER_ENABLED` flag (default false).
- **Notification service** (`services/notification_service.py`): routes rule alerts and user requests to log/webhook/smtp channels from `input/<id>/channels.yaml`.
- **Recipe registry** (`services/recipe_registry.py`): threshold/range/aggregate/benchmark/estimate recipes; `config/recipes.yaml` + per-building overlay.
- **Document indexer** (`services/document_indexer.py`): SHA-idempotent ingestion of `input/<id>/documents/` into Qdrant `documents_<bldg>`.

Full design, all phases, and the floor-plan PDF+DWG pipeline: **[ONTOSAGE.md](./ONTOSAGE.md)**.

### Conversation memory & co-reference
- **Memory** (`services/turn_memory.py`): Redis `conversation:<id>` holds recent state, **count-bounded**
  to `CONVERSATION_MAX_MESSAGES` with **no time-expiry by default** (`CONVERSATION_TTL=0`). Postgres
  `turn_memory` keeps per-turn summaries + **carry-forward** of `forecast_result`/`analytics_result`
  (so "now plot that" works). Long-term context injected on `/v1/chat/completions`.
- **Co-reference**: `dialogue_agent.rewrite_to_standalone()` rewrites follow-ups
  ("…humidity *there*?") to self-contained queries before classification (`COREFERENCE_REWRITE_ENABLED`).

### Shared state
All nodes read/write one `ConversationState` (`shared/models.py`); `intermediate_results: Dict` is the
data bus. **Reserved keys — never overwrite another node's key:**
`intent`, `entities`, `time_range` (dialogue) · `sparql_result` (sparql) · `sql_result`, `sensor_metadata` (sql; **not** `uuids` — that name is a local, never a bus key)
· `analytics_result` (analytics — **not** `analytics_output`, which nothing writes; BUG-510) · `visualization_path` (visualization) · `concepts` (concept_resolver)
· `recipe_hints` (concept_resolver → analytics) · `control_result` (control) · `goal_plan` (planner)
· `error` (_safe_node on failure).

### Storage
| Store | Port | Purpose |
|---|---|---|
| GraphDB | 7200 | Brick/BACnet RDF ontology (SPARQL) |
| MySQL | 3306 | Sensor time-series (UUID-keyed) |
| PostgreSQL | 5433 | Users + RBAC + `turn_memory` + `user_reports` |
| Redis | 6379 | Conversation state (count-bounded) + `resp_cache:*` (1h) + `cache:embed:*` (24h) + async job queue |
| Qdrant | 6333 | `floor_plans`, `capability_<bldg>`, `user_memory` |
| MongoDB | 27017 | Full chat transcripts (OpenWebUI) |

### Providers & auth
- `shared/config.py` is the single source of truth. `MODEL_PROVIDER` = `openai` / `local` (Ollama) / `cloud`;
  `EMBEDDING_PROVIDER` = `openai` (1536-d) / `local` (MiniLM 384-d) — independent.
- `STRICT_SECRETS=true` refuses startup on default passwords; secrets masked in `Settings` repr.
- `auth_manager.py`: Argon2id + Redis sessions (7-day). RBAC (`middleware/rbac.py`): 6 roles × 20 perms;
  protect endpoints with `require_permission()`.

---

## Quick Navigation Index

First `Read` target for a task — go straight to the symbol (line numbers drift; search the symbol).

| Task | File · symbol |
|---|---|
| Intent routing (all branches + overrides) | `workflow/_orchestrator.py` · `_route_from_dialogue` |
| Register node / graph wiring | `workflow/_graph.py` · `_build_graph` |
| Intent classification + entity extraction + overrides | `agents/dialogue_agent.py` · `detect_intent`, `_parse_llm_response` |
| Co-reference rewrite | `agents/dialogue_agent.py` · `rewrite_to_standalone` |
| Capability / control / report-intake detection | `services/semantic_router.py` · `is_*`, `report_intake_intent` |
| SPARQL gen/exec + RAG fallback | `agents/sparql_agent.py` · `generate_query`, `_retrieve_context` |
| SQL time-series | `agents/sql_agent.py`; adapter routing `services/adapters/registry.py` |
| Analytics / forecast | `agents/analytics_agent.py`; `agents/forecast_agent.py` + `services/forecasting/` |
| Visualization | `workflow/_orchestrator.py` · `_visualization_node` |
| Floor plan / spatial | `services/floor_plan_registry.py`, `floor_plan_pipeline.py`, `dwg_pipeline.py`; `agents/spatial_agent.py` |
| Conversation memory | `services/turn_memory.py`; `redis_manager.py` · `save_state`/`load_state` |
| Capability triples (Amenity/KnowledgeTopic) | `services/capability_graph_resolver.py`; `agents/capability_agent.py`; author via `services/capability_admin.py` (`POST /api/v1/admin/capabilities`) / OCBV `input/ontosage_schema.ttl` |
| Document KB (policy/manual) | `services/document_indexer.py`; `agents/capability_agent.py` · `_search_documents` |
| Grounding guard (no unrelated content as answers) | `services/grounding_guard.py` · `is_on_topic`, `filter_on_topic`, `enablement_hint` |
| Referent existence gate (zones/floors/spaces/equipment/measurands) | `services/referent_resolver.py` · `detect_typed_referent`, `ReferentResolver.resolve` |
| Report intake | `services/report_intake_service.py` |
| Response formatting | `workflow/_orchestrator.py` · `_response_node` |
| Config / env vars | `shared/config.py` · `Settings` |
| State / models | `shared/models.py` · `ConversationState`, `FloorPlanManifest`, `Space`, `Block` |
| FastAPI app / endpoints / lifespan | `orchestrator/main.py` |
| Services / ports | `docker-compose.yml` |
| HBCO concept resolution | `services/concept_resolver.py` · `resolve`; `ontology/hbco_core.ttl`, `hbco_mappings.ttl` |
| Feed framework (live data) | `services/feeds/registry.py` · `FeedRegistry`; `input/<id>/feeds.yaml` |
| ECA rules engine | `services/rules_engine.py` · `RulesEngine`; `input/<id>/rules.yaml` |
| Notification dispatch | `services/notification_service.py`; `input/<id>/channels.yaml` |
| Actuation gateway | `services/actuation/registry.py` · `ActuationRegistry`; `sim_driver.py`; `approval_store.py` |
| Recipe registry | `services/recipe_registry.py` · `RecipeRegistry`; `config/recipes.yaml` |
| Goal planner | `services/goal_planner.py` · `GoalPlanner`; `config/goals.yaml` |
| Input validators | `services/input_validators.py` · `validate_building_input` |
| Per-building config validators | `scripts/swap_building.py` · `_check_optional_configs` |
| **P0 — Admin portal endpoints** | `orchestrator/main.py` · `list_named_graphs`, `validate_ttl_endpoint`, `upload_ttl_endpoint`, `drop_named_graph_endpoint`, `sparql_browser`, `trigger_reindex`, `list_reindex_jobs`, `get_reindex_job` |
| **P0 — GraphDB admin CRUD** | `services/ontology_manager.py` · `list_named_graphs`, `validate_ttl_text`, `upload_ttl`, `drop_named_graph`, `run_sparql_select` |
| **P0 — Qdrant reindex jobs** | `services/reindex_service.py` · `ReindexService`, `start`, `status`, `list_jobs`, `_run` |
| **P0 — Narrow MySQL adapter** | `services/adapters/mysql_narrow_adapter.py` · `MySQLNarrowAdapter`, `build_timeseries_query`, `get_columns` |
| **P0 — Sensor TTL generator** | `services/sensor_ttl_generator.py` · `generate_timeseries_ttl`, `parse_sensor_csv` |
| **P0 — RBAC auth dependency** | **`main.py`** · `get_user_context`, `require_permission` (the LIVE session→permission gate); `middleware/rbac.py` provides `UserContext` + `ROLE_PERMISSIONS` only — the rest of that module (`TokenManager`/`create_rbac_dependency`/`RBACMiddleware`) is unwired legacy, do not use |
| **P0 — Admin React portal** | `frontend/src/pages/AdminPortal.js` (11 tabs: Onboarding, Ontology, Capabilities, Policies, …) |
| **Onboarding readiness (GUI-only build)** | `services/onboarding_status.py` · `collect_status`; `main.py` · `onboarding_status`; `components/admin/OnboardingTab.js` |
| **P0 — Narrow table DDL** | `data/mysql-init/create_narrow_timeseries_tables.sql` (7 tables in `sensordb`) |
| **P0 — TTL extensions** | `input/bldg1_timeseries_extension.ttl` (19 sensors) · `input/bldg1_security_lighting_extension.ttl` (293 triples) |

---

## Intents & routing

Canonical list: `orchestrator/intents/intent_definitions.yaml` (per-building overlays:
`input/<id>/intents.yaml`). 29+ intents grouped `data` (sparql→sql→…), `standalone`, `meta`.
Families: sensor_data, analytics, metadata, discovery, report, anomaly, compare, export, recommend,
trend/forecast, compliance, floor_plan, spatial_query, capability, control, alert, planner,
report-intake (maintenance/complaint/safety_report/feedback/suggestion), general/greeting/clarification,
automation_capability, preference_management, lab_booking (bldg1 overlay).

**Routing precedence rules to preserve** (deterministic overrides in `dialogue_agent._parse_llm_response`
+ `_route_from_dialogue`):
- Fault/suggestion/safety **statements** ("the toilet is leaking", "Suggestion: …") → report-intake, **beating** the capability KB router. Questions ("is the lift broken?") are NOT reports.
- Comfort **questions** ("is it too warm?") → analytics, **not** complaint.
- Actuation/external-action ("open the windows", "email it") → `control` → **decline**; never floor_plan/maintenance.
- "show me floor N / where is room X" → floor_plan; "how many / area / adjacent" → spatial_query; data + floor N → data wins.

### Add an intent (2 steps, no graph edits)
1. Append to `orchestrator/intents/intent_definitions.yaml` (`pipeline_group`, optional `route_target`, `node_method`).
2. Implement `async def _my_node(self, state) -> ConversationState` on `WorkflowOrchestrator` in `workflow/_orchestrator.py`.

Restart — edges + routing auto-wire. A YAML intent with no `node_method` safely falls through to
`response`. Patterns to follow: `.claude/rules/agent-patterns.md`. SPARQL: `.claude/rules/sparql-patterns.md`.

---

## TTL-first design principle

**Goal:** answer the 6,117 questions in `paper/Survey analysis and results/` using OntoSage with minimum additional files. The Brick/BACnet `.ttl` files are the **primary source of truth** for everything a building knows about itself.

Rules to follow in every development decision:

1. **TTL before YAML.** If a fact about the building can be expressed as an RDF triple in the ontology, put it there — not in a sidecar file. Sidecar YAML is for *operational config* (thresholds, auth, routing overrides) that doesn't belong in the ontology. (Capabilities followed this to completion: `capability.yaml` was removed (TODO-012) and replaced by `ontosage:Amenity`/`KnowledgeTopic` triples authored via the admin Capabilities GUI or the OCBV TBox.)
2. **Extend the TTL, don't bypass it.** When OntoSage can't answer a survey question, the first fix is to add the missing triples (sensors, equipment, relationships, metadata) to the `.ttl` — not to add a hard-coded capability entry or a special-case code path.
3. **SPARQL is the query path.** New question types should be answerable via SPARQL against GraphDB. Only fall back to the capability KB (Qdrant), SQL adapters, or analytics when the question requires live time-series data or computation that RDF cannot express.
4. **Minimum additional files.** Each new capability should add at most one file: the enriched `.ttl`. New `feeds.yaml`, `rules.yaml`, `channels.yaml` entries are for live-data and alerting — not for answering static/structural questions.
5. **`T5_new_capability_gaps.csv`** (`paper/Survey analysis and results/outputs/master table analysis/`) is the engineering backlog. Each row that says `requires_extension` maps to a missing TTL property or an unmapped sensor. Fix it there before adding code.

This principle is grounded in the pre-design survey corpus (6,117 questions, 96 participants). The architecture coverage crosswalk (`tasks/architecture_coverage_crosswalk.csv`) shows which question clusters are already served by the existing TTL and which gaps remain.

---

## Workflow rules
1. **Plan first** for non-trivial work (3+ steps / architectural). Re-plan if it goes sideways.
2. **Subagents** only when the user asks; one focused task each.
3. **Self-improvement**: after any correction, capture the pattern in `tasks/lessons.md`.
4. **Verify before done**: run tests/QA, check logs, prove it. "Would a staff engineer approve?"
5. **Elegance, balanced**: ask for the cleaner way on non-trivial changes; don't over-engineer simple fixes.
6. **Autonomous bug-fixing**: given a bug/log/failing test, fix it directly.
7. **Fix tracker — always keep current**: [`tasks/FIX_TRACKER.csv`](./tasks/FIX_TRACKER.csv) is the
   living log of every bug/caveat/fix over time. **Whenever you fix a bug or resolve a caveat**,
   update its row (`Status` → `FIXED`/`DEPLOYED`/`VERIFIED_LIVE`, fill `Date_Resolved` +
   `Verification`). **Whenever you find a new bug/caveat**, add a row (next `FIX-`/`CAVEAT-` id,
   `Status: OPEN`). Non-optional — it is the single source of truth for what has been fixed.
   Design/why-notes for open items live in the matching plan (e.g.
   [`tasks/GROUNDING_AND_HONESTY_FIXES_PLAN.md`](./tasks/GROUNDING_AND_HONESTY_FIXES_PLAN.md)).
8. **PARK ALL BUILDINGS BEFORE EVERY COMMIT/PUSH** (non-negotiable). The repo's canonical
   committed state has **NO active building**: `input/`, `.env` and `docker-compose.yml` must
   NOT exist — only `bldg1|bldg2|bldg3/` + `.env1|.env2|.env3` (gitignored) +
   `docker-compose.bldg{1,2,3}.yml`. When the user says *"commit"* / *"push"*, do this FIRST:
   1. `docker compose ls` — if a stack runs, `docker compose -p ontosage_<N> down`
      (never rename while up: bind mounts break, CAVEAT-088).
   2. Read the active id from `input/env.building`, then park it by ITS OWN identity:
      `input/`→`bldg<N>/`, `.env`→`.env<N>`, `docker-compose.yml`→`docker-compose.bldg<N>.yml`.
   3. Verify: `ls -d input .env docker-compose.yml` all absent; all three parked sets present.
   4. Run `pytest -m unit -q` **in the parked state** (it must pass there — that is what a
      fresh clone and CI see), then commit + push.
   5. Tell the user which building was parked, so they can say *"run bldg\<N\>"* to resume.
   Rationale: the committed tree is then identical no matter who was testing what, a fresh
   clone has all three buildings intact and none half-active, and no `.env` (secrets) can
   ever ride along. Tests and code must therefore never require an active building.

---

## Debugging (common)
- **Orchestrator won't start** → `docker-compose logs --tail=50 orchestrator`; usually an ImportError (a
  module imported before it's defined, or a symbol missing from a package `__init__`).
- **Wrong intent/node** → check the routing-precedence rules above; inspect `intermediate_results["route_decision"]`; run `tests/test_routing_accuracy.py`.
- **SPARQL empty** → test GraphDB directly (`.claude/rules/sparql-patterns.md`); empty = ontology not loaded; results-but-empty = `sparql_agent._retrieve_context`.
- **Floor plan empty / `area_m2=null`** → DWG pipeline off (`dwg2dxf`/libredwg missing → PDF-only); manifest `schema_version` should be "2.0"; reingest `POST /api/v1/floor-plans/reingest`.
- **Capability not answering** → capabilities are triples now. SPARQL GraphDB: `SELECT ?a ?lay WHERE { { ?a a ontosage:Amenity } UNION { ?a a ontosage:KnowledgeTopic } ; ontosage:layTerms ?lay }` — empty = `<id>_capabilities.ttl` not loaded (check `ttl_uploader`). Match miss = the query's lay-term isn't in any `ontosage:layTerms`; add it via the admin Capabilities GUI. Prose manual not surfacing = document score below the 0.50 (local) honesty floor in `capability_agent._search_documents`.
- **Stale answers after a code fix** → flush `resp_cache:*` in Redis (`redis-cli --scan --pattern "resp_cache:*" | xargs redis-cli del`) before re-testing. Real container name: `redis-memory-store` (not `ontosage-redis`).
- **Feed not updating** → check `docker logs … | grep FeedRegistry` for `loaded=N`; missing feed = feeds.yaml absent or disabled flag.
- **ECA rule not firing** → check Redis keys `rules:breach_start:*` and `rules:fired:*`; verify `sensor_uuid` matches a UUID in MySQL `sensor_data`.
- **Concept not resolving** → SPARQL `SELECT ?c WHERE { ?c a hbco:Concept; hbco:layTerm "stuffy" }` against GraphDB; empty = hbco_mappings.ttl not uploaded.
- **Actuation decline unexpected** → check `building.yaml` `actuation.driver` value and `points_writable` list; user must have `control:write` permission (admin/facility_manager only).
- **Input validator fails on swap** → `python -c "from orchestrator.services.input_validators import validate_building_input, format_validation_report; from pathlib import Path; ok, r = validate_building_input('bldg2', Path('input')); print(format_validation_report(r))"` for full report.
- **Admin endpoint returns 401** → the endpoint uses `require_permission()` which chains through `get_user_context`. In tests: override `get_user_context` (not `get_current_user`). In live: ensure the `Authorization` header contains a valid Redis session token from `/auth/login`. Check `docker logs … | grep "401"` to see which endpoint is rejecting.
- **Admin portal upload TTL returns 500** → `services/ontology_manager.py` makes HTTP calls to GraphDB (port 7200). Verify GraphDB is healthy: `curl http://localhost:7200/rest/repositories`. Check `docker-compose logs --tail=30 orchestrator | grep ontology_manager`.
- **Reindex job stuck in `pending`** → `_reindex_service_instance` singleton in `main.py` must be initialized. Check `docker logs … | grep ReindexService` for `started`. If `None`, the lifespan didn't call `reindex_service.start()`.
- **Narrow table returns empty** → two-step check: (1) verify the sensor UUID exists in the TTL via SPARQL: `SELECT ?uuid WHERE { bldg:MySensor ref:hasTimeseriesId ?uuid }` — if empty, TTL not loaded; (2) verify rows exist in MySQL: `SELECT COUNT(*) FROM energy_data WHERE uuid='<uuid>'` in `sensordb`. If both exist but still empty, check `ref:storedAt` key in TTL matches the key in `database_registry.yaml`.
- **TTL auto-upload not loading a new TTL** → `ttl_uploader.py` discovers files matching `bldg1_*.ttl` in `input/`. File must be named `bldg1_<anything>.ttl`. Check `docker logs … | grep ttl_uploader` for `Uploading` or `Already up to date (SHA match)`. If the SHA matches, delete the named graph via Admin portal first then restart.
- **STRICT_SECRETS startup failure** → orchestrator refuses to boot if any password equals its default. Set real passwords in `.env`: `POSTGRES_USER_PASSWORD`, `MYSQL_PASSWORD`, `SECRET_KEY`, `GRAPHDB_PASSWORD`. Or set `STRICT_SECRETS=false` for local dev.

---

## Skills (`Skill` tool) & Sub-agents (`.claude/agents/`, only when asked)

| Task | Skill |  | Agent | When |
|---|---|---|---|---|
| Debug pipeline | `systematic-debugging` / `phase-gated-debugging` | | `ontology-agent` | SPARQL/TTL/GraphDB |
| LangGraph changes | `langgraph` | | `pipeline-agent` | routing / intents / state |
| RAG work | `rag-engineer` | | `infra-agent` | Docker / env / providers |
| FastAPI endpoints | `fastapi-pro` | | `test-agent` | tests / coverage |
| Docker | `docker-expert` | | `deploy-agent` | pre-deploy / auth hardening |
| Qdrant | `vector-database-engineer` | | | |
| Security review | `security-auditor` | | | |

---

## Notes:

Never agree with me by default. Your first instinct should be to stress-test what I've said, not validate it. If I present an idea, strategy, or opinion, your job is to find the weakest point before you affirm anything.
No glazing. Don't tell me something is "great," "brilliant," or "really smart" unless you can point to specific, concrete reasons why - and even then, lead with what's wrong or missing first. Compliments without substance are noise.
Don't echo my framing back to me. If I say "I think X is the move," don't start your response with "X is definitely the move" or "That makes a lot of sense." Instead, start by asking yourself: what am I not seeing? What's the counter-argument? What would someone who disagrees say, and are they right?
When you do agree, earn it. Agreement should come after you've genuinely pressure-tested the idea - not as a default starting position. If you agree, say why in a way that adds something I didn't already say.

Be direct and concise. Skip the warm-up sentences.
Don't pad responses with filler affirmations. Get to the point. If the answer is "no" or "this won't work," say that in the first sentence.
Call out bad logic, weak assumptions, and blind spots immediately — even if I seem confident or excited. Especially then. The more certain I sound, the more I need pushback.
If you catch yourself about to start a response with "That's a great point" or "You're absolutely right" - stop and rewrite. Start with the most useful thing you can say instead.

**DO NOT PUSH OR COMMIT TO GIT UNTIL I SAY SO EXPLICITLY.** Always wait for my approval before making any commits or pushing to the repository. I want to review and understand the changes before they are added to the codebase.
