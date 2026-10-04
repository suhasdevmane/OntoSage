# Trial readiness plan — every answer carries its evidence, and nothing is lost

**Written 2026-10-02 (evening). Execution tracked in [`tasks/TRIAL_TRACKER.csv`](./TRIAL_TRACKER.csv) —
72 rows, 38.9 days (36.4 excluding the two deliberately deferred). ONE tracker: it supersedes the nine open rows of
[`tasks/PRODUCTION_TRACKER.csv`](./PRODUCTION_TRACKER.csv), each mapped below. Do not add a third.**

Built from a code inventory run on this tree with the live stack up: six readers, each followed by
an adversarial verifier whose standing assumption was that the gap was already built. That
assumption was right nine times. Every number and file:line below came from that inventory or from
a command run against the live system; nothing is quoted from a document.

---

## 1. The finding that reorders the whole plan

**W4-01 is not unbuilt. It is built, routed, and reachable by a user today.**

| piece | where | state |
|---|---|---|
| The evidence record — 40 fields: status, operation, sources with owner/authority/version/observed_at/calibration, completeness, spatial adequacy, conflicts, gates, omissions, remedy | `shared/models.py:590`, assembled at `services/evidence/assemble.py:1060`, called once at `workflow/_orchestrator.py:6126` | **Assembled on 200 of 200 live turns** |
| The renderer — prints kind of claim, operation, 8 sources with owner and version, observed vs retrieved, completeness, method, gates that fired, disagreements, omissions, and (admin only) the remedy | `services/answer_provenance.py:64` | **Complete** |
| The routing — "how do you know that?" → the renderer | `services/routing_contract.py:3455`, **parse rule #0 of 65** | **Live** |
| The lane — loads the previous turn's record from Redis and renders it | `agents/capability_agent.py:938-985` | **Live** |
| Per-answer source chips (`*Sources: Building model, Sensor data*`) | `services/provenance.py:161`, rendered at `_orchestrator.py:6864` | **Partial: 76 of 200 answers** |
| An inline evidence panel on every answer of one lane | `services/deliberation/dossier.py:475` | **20 of 20 deliberate turns.** This is the working precedent to copy |

So the owner's requirement — *users get the evidence every time* — is not a build. It is a
**delivery** problem with four measured mechanisms, and each is small:

1. **`provenance.build_tags` raises `TypeError: unhashable type: 'dict'`** on the dict-shaped
   sources `sparql_agent.py:1826` writes, inside a bare `except Exception` logged at DEBUG with
   DEBUG off. The entire footer **and** the structured `sources` array die on every register-lane
   turn, with no log trace, including correctly-recorded string keys in the same list.
   *Reproduced live in the container.*
2. **The capability lane writes 15 different provenance values and `BUILTIN_PROVENANCE` holds 5
   keys** — none of them matching. Every capability answer loses its chip silently, including the
   provenance lane's own answers.
3. **`DATASOURCE_TOGGLES_ENABLED` defaults to `false`** in `shared/config.py:578` *and* in
   `.env.example:506`. The `true` that makes footers appear exists only in the gitignored `.env`.
   **A fresh clone, CI, and any rebuilt deployment render no evidence at all.**
4. **The evidence record is never persisted.** `turn_memory` has no evidence column; only the
   latest turn's record survives, in Redis, with no turn index. Provenance for anything older than
   the previous turn is impossible.

And one fact that decides the shape of the whole wave:

> **Rendered text is durable; a response field is not.** Of 190 chats in Open WebUI's own store,
> **84 contain the rendered Sources footer and 0 contain any `ontosage_*` field** — the evidence
> record is returned on every `/v1` turn and discarded by the client. *Evidence every time* is only
> auditable if it is **rendered into the answer**, not exposed beside it.

---

## 2. Do not build these — they exist (this section is the plan's highest-value page)

Four earlier plan rows asked for capabilities that already existed (lessons #133, #136). The
inventory found nine more. Read this before writing code for any row.

| What a row might ask for | What already exists | Where |
|---|---|---|
| A provenance renderer / `evidence/record_details.py` | `answer_provenance.render()` — full read-back with the admin remedy gate | `services/answer_provenance.py:64` |
| A record-vs-record conflict detector | `register_facts._disagreement_lines` — *"Where a register contradicts itself about the same thing, say so instead of choosing"*, with a state-column allowlist, **already delivered to the reader** | `services/register_facts.py:1114` |
| A cross-source fact-conflict scanner | `scripts/fact_conflicts.py` — complete, with a standing test and **no orchestrator caller** | `scripts/fact_conflicts.py` |
| "Which record wins" for an asset | `asset_state_service` already answers a same-class status conflict with *disputed* prose (BUG-438) | `services/asset_state_service.py:398-474` |
| A headline-vs-table invariant harness | `narration_validators.validate_narration` — six pure validators, fixed point, per-edit accounting, on the answer path; `_numbers_elsewhere` is the exact primitive needed | `services/narration_validators.py:1131` |
| A cross-session memory store | Qdrant `user_memory`, **26,504 points**, retrieved on every `/v1` turn | `services/agent_memory.py`, gate at `_orchestrator.py:2116` |
| GDPR erasure for memory | `agent_memory.forget_user()` — docstring *"right to be forgotten"*, tested, **zero callers** | `services/agent_memory.py:416` |
| Turn-history erasure | `turn_memory.delete_user_turns()` — **zero callers** | `services/turn_memory.py:200` |
| A user-facing see/erase for preferences | The `preference_management` lane already answers *"forget my preferences"* and *"what are my preferences"* and names the count | `_orchestrator.py:10695-10760` |
| A turn↔analysis join key | `turn_memory` already holds **9,907 rows** keyed `owui_<chat id>:<username>` with the resolved user and the classified intent; it joins to `webui.db chat.id` | `services/turn_memory.py`, Postgres `ontobot` |
| A decline-outcome vocabulary | `retrieval_outcome.py:63-72` — seven states, **already stamped by producers** at `sparql_agent.py:502` and `sensor_binder.py:1578` | `services/retrieval_outcome.py` |
| A Redis residue purger | `scripts/redis_hygiene.py` with `--purge/--check` and a 60% gate | `scripts/redis_hygiene.py` |
| A backup/restore procedure | `docs/RUNBOOK.md:212-280`, **tracked in git** — and every identifier in it is wrong (see D-row C2) | `docs/RUNBOOK.md` |
| A freshness guard on stale readings | The freshness gate is the one **enforcing** gate in the policy and already downgrades a stale answer, with its reason on `gates_applied` | `config/evidence_policy.yaml`, `assemble.py:1277` |
| W4-02's own answer | `rec.source_tier` is **written on every multi-tier turn** (`assemble.py:775`) and has **zero readers anywhere** | one line to print it |

---

## 3. What is actually wrong, measured

### Evidence delivery
- 49 of 200 records carry **zero sources** — and 20 of those 20 are the `deliberate` lane, the one
  lane whose answer already shows the user a full dossier. Its `DossierEvidenceRow` already carries
  `sensor_uuid`, `stored_at` and `latest`; `_sources_from` never reads them.
- `_prov_stores`, `sources` and `claim_binding` are **not in `_PER_TURN_LANE_KEYS`**, so a resumed
  conversation can cite the previous turn's sources. A rendered panel over inherited sources is a
  fabrication carrying a citation — strictly worse than today's silence. **This must land first.**
- The spatial/calibration pass is **dead on 124 of 131 turns**: `contributing_uuids` reads only
  `results['uuids']` (nothing writes it) and `sensor_metadata` (only the SQL node writes it). Fix
  that and an **already-shipped** spatial-basis note starts firing by itself.
- `spatial_adequacy` defaults to `NONE`, the same value that means *"no sensor covers the space
  asked about"*. An ungraded record and a measured absence are indistinguishable. Nothing may key on
  this field until that is fixed.
- `PROVENANCE_RE` matches 7 of 15 natural phrasings, and **`session_recall` (rule #64, last wins)
  steals 2 of the 7**. Worse: *"what is the evidence behind your answer?"* is matched by
  `session_recall._ABOUT_MY_ANSWER` and **not** by `PROVENANCE_RE`. So standing session_recall down
  alone leaves that question with **no lane at all**. The two edits must land in one commit —
  and BUG-1397 (VERIFIED_LIVE) is the fix that put session_recall there, so this is a **conflict
  between two shipped fixes** and needs the owner's call.
- `claim_binder`: 5,918 claims over 200 turns, **2,046 unbound (34.6%)**, because only 3 of ~16
  lanes file their computed figures. Keep `CLAIM_BINDING_ENABLED=record` throughout; the deliverable
  is a lower unbound share, measured offline, not a flag flip (CAVEAT-769 is what enforcement cost).

### Privacy — the one P1 in this plan
**`openwebui_user` is a shared memory partition.** Any request without a recognised forwarded email
falls back to that identity (`main.py:3076`), and cross-session memory retrieval filters on
`user_id`. Measured: **1,742 Qdrant points and 1,702 `turn_memory` rows** in that one bucket. So
tester B's classification prompt can be primed with tester A's question *and answer summary,
figures included*. `answer_summary` is **not** redacted (`session_summary` is), and the render omits
the timestamp it stores. The `fresh_session` gate that would limit this is set at exactly one site,
inside `/chat/stream`, and never on `/v1`. This defeats the isolation `tests/test_privacy_t40.py`
pins.

Also: **`clear_user_history` deletes `conversations` and not `turn_memory`, and reports success.**
10,411 turn rows survive a user being told their history was cleared. That is worse than having no
erasure, because the user is told it worked.

### Durability — what a failure costs today
| Operation | What is lost |
|---|---|
| `docker compose restart` / `build` / `up -d` | **Nothing.** Redis runs `--appendonly yes` and Postgres is bind-mounted |
| Container recreate | **All 60 tester logins** — `WEBUI_SECRET_KEY` is empty, so Open WebUI regenerates its JWT key |
| `docker compose down -v`, or a `volumes/` loss | GraphDB (361,558 triples), every tester conversation, 10,411 turn rows, 1,088 reports, all 190 chats. `volumes/` is gitignored; `git ls-files volumes/` returns 0 |
| This disk failing | Additionally: `.env` (nowhere in git, no backup), `user_credentials_bldg1.csv` (60 passwords, single copy), **host MySQL `sensordb` — 9.02 GB, 22 tables, outside the repo, outside Docker, outside `volumes/`, never backed up**, and the 11 untracked files that are the entire trial apparatus |
| Rebuilding from the public repo alone | No `.env`, and `DATASOURCE_TOGGLES_ENABLED=false` → **no evidence footer on any answer** |

`docs/RUNBOOK.md` carries a tracked Backup/Restore section in which the Postgres role, the Postgres
database, the GraphDB repository and two container names are all wrong, and whose
*"All Volumes (Single Command)"* line produces a ~30 GB archive containing **zero sensor readings**
(23 GB of it is a dead `ollama` directory; the readings are on the host). Someone under pressure
runs the one-liner, sees 30 GB, and stops.

### Trial exposure
- `0.0.0.0:8000` and `0.0.0.0:3000` are published, cloudflared fronts
  `https://talk2futurebuildings.systems`, `ENABLE_SIGNUP=true`, `TRUST_FORWARDED_USER=true`, and
  `/v1/chat/completions` is gated **only** by the shared `PIPELINE_API_KEY` with no
  `require_permission`. The role header is therefore spoofable, which makes **every per-role number
  the trial is designed to produce unfalsifiable**. The one-line fix has a precedent in the same
  compose file (`127.0.0.1:6379:6379`).
- **`SECRET_KEY` is absent from `.env`**, so the live system signs with the published default — on a
  repo that is world-readable. `STRICT_SECRETS=false`, so the boot guard returns immediately.
- **`OLLAMA_NUM_PARALLEL=1` is inert.** It is set in the orchestrator container while Ollama runs on
  the host; no Python reads it; no `OLLAMA_*` variable is set at any scope on the host. CLAUDE.md's
  claim that *"two testers asking at once queue"* **is false** — Ollama 0.34.4 picks its own
  parallelism. The owner's decision is unimplemented.
- `readonly` **can** create alerts: the lane gates on `guest`/`anonymous` or an empty `user_id`, and
  on `/v1` both are always set. NOTE-1416's second claim is half wrong. There is no `alert:write`
  permission to check, so this needs two edits, not one.
- The open-access state (`readonly: '*'`) **is already committed at `ab6c081`**, so a fresh clone
  inherits it and no test would catch it. Only `occupant` and `readonly` need restoring.
- No log persistence: `json-file` with no options, ~30k lines/day, and **a rebuild destroys the
  trial's entire log history** — which every instrument reads.
- 1 feedback row against 319 assistant messages (0.3%), and the exporter's rating fallback
  mis-attributes (`meta.message_index` 40 points at index 39 in one ordering and a *user* message in
  the other).

---

## 4. The waves

Full detail — why, evidence, approach, acceptance, dependencies, risk — is in
[`tasks/TRIAL_TRACKER.csv`](./TRIAL_TRACKER.csv). This is the order and the reasoning.

| Wave | What | Days | Gate |
|---|---|---|---|
| **A — Capture** (5 rows) | Commit the apparatus. 11 untracked files, including every instrument three later rows depend on, exist on one disk | 0.9 | **Owner's push approval** |
| **B — Exposure** (5) | Secrets in one window, bind to localhost, settle signup and the spoofable role header, persist the log | 1.2 | Owner decides signup + role trust |
| **C — Durability** (8) | A backup that includes the 9 GB nobody is backing up, a restore that has been *run*, correct identifiers in the runbook, Redis capacity before Redis policy | 4.0 | A scripted restore passing its pinned constants |
| **D — Evidence every time** (14) | The owner's priority. Clearing → the dict crash → the key map → `/v1` fields → the flag → `source_tier` → the detector conflict → dossier sources → persistence → an endpoint → **the rendered panel** → uuid population → ungraded | 9.1 | A tester sees sources on every figure-bearing answer, and can ask why |
| **E — Which record wins** (7) | Route what exists before authoring triples; fix the one confidently-wrong path; then the graph | 5.6 | Two disagreeing records produce a disclosure, not a choice |
| **F — Memory and privacy** (11) | The shared partition first (P1), then redaction, then erasure that tells the truth, then the remembered location, then the 18-turn proof | 6.0 | No tester's figure can reach another tester; "cleared" means cleared |
| **G — Answer quality** (8) | The cheapest real gains: one missing lay term, one conditional frame, one condition change, one invariant — then the four open defects | 4.9 | Measured moves over the 4,060-question bank, both directions |
| **H — Operations** (8) | A watchdog that probes the runner, capacity made real, in-product guidance, feedback that arrives, a daily check | 2.8 | A day of unattended running with no manual recovery |
| **I — Close-out** (4) | Re-read the pack last (I1), restore access lists (I2), derive the open set (I3), measure evidence coverage (I4) | 1.8 | The committed tree is safe to hand to anyone |
| **X — Deferred** (2) | Cross-entity forecasting and weather correlation, each with its reason | 2.5 | Not trial-blocking |

**Hard ordering, and the reasons are not stylistic:**

1. **A before everything.** `scripts/count_gate_deletions.py`, `scripts/export_trial_turns.py` and
   `scripts/run_conversations.py` are untracked, and three rows' entire deliverable is a week of
   output from them. A `git clean -fd` destroys the measurement apparatus for three rows at once —
   and `scratchpad/memory_probe.py`, which an earlier plan row names as its starting point, **is
   already gone from this tree**. That loss has happened once.
2. **D1 (per-turn clearing) before any rendering.** A panel over inherited sources is a fabrication
   with a citation.
3. **D2 (the dict crash) before D5 (the flag).** Flipping the default first switches on a feature
   that silently fails on its two busiest lanes.
4. **Redis capacity before Redis policy.** 94% of the 1.27 GiB in use *is* the non-expiring
   `conversation:*` state. Switching to `volatile-lru` first converts silent eviction into refused
   writes. Raise the cap, purge harness residue, re-measure, then consider the policy.
5. **F1 (the shared partition) before F2 (redaction).** Redacting at the store leaves 26,504
   existing points retrievable; the partition is what makes them reach the wrong person.
6. **D13 (ungraded) before anything keys on `spatial_adequacy`**, and before any gate is promoted to
   enforcing. Promoting the spatial or calibration gate today would refuse answers on turns that
   were never graded.
7. **The 73-question pack is read last.** It is the set the system was tuned against; reading it
   earlier measures the tuning.

---

## 5. What needs the owner, and nothing proceeds without it

| # | Decision | Why it cannot be defaulted |
|---|---|---|
| 1 | **Push approval for Wave A** | Standing instruction: nothing is committed without it |
| 2 | **Is evidence rendering flag-gated at all?** | `DATASOURCE_TOGGLES_ENABLED=false` is the shipped default. If evidence must appear every time, the flag's default flips; if it stays opt-in, every deployment needs a startup assertion instead |
| 3 | **`answer_provenance` vs `session_recall`** | Both are shipped fixes. BUG-1397 put the recall lane last on purpose; BUG-1427 is the record of it giving the wrong answer. One must stand down |
| 4 | **`ENABLE_SIGNUP` during the trial**, and whether a spoofable role header is acceptable | It decides whether per-role results are defensible |
| 5 | **Concurrency**: implement one-at-a-time on the host, or make the queue visible | The current setting does nothing. Either is fine; the status quo is a false claim |
| 6 | **Which roles may create alerts** | Occupant personal alerts are a plausible feature; narrowing without asking could remove one |
| 7 | **`CONVERSATION_TTL`** for trial accounts | Retention of per-tester text is a policy choice |
| 8 | **Cross-session memory retention and visibility** | TODO-1022's standing objection: this is personal data |
| 9 | **Where the encrypted `.env` and credentials backup lives** | The passphrase must not be in the repo |

---

## 6. Mapping from `PRODUCTION_TRACKER.csv`

| Old row | Status there | Where it goes |
|---|---|---|
| W4-01 provenance intent | TODO | **Wave D** (D1–D14). Re-scoped: the lane exists; the work is delivery |
| W4-02 precedence as records | TODO | **Wave E** (E1–E7). Re-scoped: route what exists first |
| W5-03 cross-session memory | TODO | **Wave F** (F1–F6, F9). Re-scoped: it exists and runs; the work is isolation, redaction and honest erasure |
| W5-04 long-conversation proof | TODO | **F10**. Its named probe no longer exists on this tree |
| W2-03 cross-entity prediction | PARTIAL | **Deferred, with a reason** (row X1): a forecast comparison answers from current means and says so. Not trial-blocking |
| W3-01 outdoor weather | PARTIAL | **Deferred** (X2): the feed is live; the correlation question declines |
| W3-04 design occupancy | PARTIAL | **E6** absorbs it — two declared terms disagree for three rooms and `capacityBasis` has zero triples |
| W3-05 last-seen per sensor | DONE-PENDING-LIVE | **H6** absorbs the live check |
| W7-02 re-read the 73-question pack | PARTIAL | **I1**, last |

---

## 7. How to work this plan

- **One row at a time through the routing contract.** Every rule change goes alone, with the
  4,060-question bank measured before and after, the move count and direction pinned in the module,
  `tests/test_routing_contract.py::test_precedence_order_is_pinned` updated in the same commit, and
  the 51-case gate green before and after, **run alone** (CAVEAT-1193).
- **Advisory with a counter before enforcing.** Every guard added to the answer path has destroyed a
  correct answer at least once (lesson #135; BUG-873 deleted a completed forecast). The pattern that
  works is `scripts/count_gate_deletions.py`: count for a week, then decide.
- **Measure the lane, not the stage.** A stage measurement is not a route measurement (lessons #145,
  #174, #188). Three fixes this week were provably right offline and invisible live.
- **Weekly, during the trial:** `scripts/export_trial_turns.py` → `scripts/draw_weekly_tail.py` →
  hand-read the sample in full → `scripts/count_gate_deletions.py` → the gate alone → both suites.
  Two numbers only: the hand-read acceptable rate, and the count of confidently-wrong answers, which
  must stay zero.
- **Re-derive, never re-word.** Every hand-maintained count in this repo has gone stale within days.
  Print the routing-rule count, print the tracker's open set, print the suite figure.

## 8. What this plan does not promise

- **It does not make the system ready for an unsupervised open invitation.** The last unseen set read
  68.3% acceptable; roughly one question in three still gets a false refusal or a wrong-shape answer.
  Wave D makes the answers *auditable*, not correct. The quality work is Wave G and the weekly tail.
- **It does not reduce declines to zero, and should not.** Most declines in the last set were honest
  statements about what the building does not record.
- **It closes no measurement-apparatus row.** Eight of the open P1s are graders disagreeing with
  hand reads and with each other (CAVEAT-1346). No automatic grader supports a quality claim about
  answers it was not calibrated on; every percentage this project can defend comes from a hand read.
- **It does not address the supervisor-agent architecture** (`docs/plan/see if this improves or not.md`).
  Multi-week, and nothing in the trial data would be readable through it for weeks.
