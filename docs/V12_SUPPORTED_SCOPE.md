# The supported scope

**What this version of OntoSage claims, what it does not, and what evidence stands behind each.**

Written 10 September 2026 as **V12-26**, which is the review's ticket **T01**. The review's
instruction (p. 15) is to replace *"the idea is finished"* as a project-management measure with a
capability matrix: supported question type, required building data, known limitations, evaluation
coverage and release status. *"A feature can be implemented but not sufficiently evaluated; another
can be safely supported only with a stated limitation."*

The claim this document supports is deliberately narrow, and is the one the review says is both
useful and auditable (p. 15):

> **This version passed these specified cases under these recorded conditions, and these
> unsupported situations are handled explicitly.**

It is **not** a claim that the system is accurate in general, that all 37 intents are equally
reliable because each routes, or that there is no unknown defect.

---

## 1 · Revision snapshot — what "this version" means

| | |
|---|---|
| Commit | `b80c3de` (2026-09-05) — **plus 286 uncommitted paths**, see the warning below |
| Building | `bldg1` (Abacws), the standing active building |
| Model | `local` / `gpt-oss:20b` · embeddings `local` |
| Graph | GraphDB repo `bldg` · 8 `brick:Floor` · 2,750 instrumented points · 2,720 declared sensors |
| Stores | 20 registered time-series backends (MySQL wide + narrow per modality) |
| Offline suite | 5,476 pass / 45 skip (5,521 collected) |
| Live probe | **57/59 first-pass**, 64.7 min, measured 2026-09-09 |

> **This snapshot is not reproducible from a clone.** 286 paths are uncommitted, and until
> 2026-09-10 the entire evidence register — the plan, the 498-row defect log, `lessons.md` —
> was gitignored (**CAVEAT-501**, now `PARTIALLY_FIXED`: `.gitignore` is corrected, no commit
> has yet been authorised). A capability claim tied to a revision nobody else can check out is
> weaker than it looks. **Nothing here should be cited externally until a baseline commit exists.**

Deployed image ages matter independently of source, because compose builds an image per building
and `restart` never rebuilds one (**BUG-343**): orchestrator **9 days**, rag-service **12 days**,
code-executor **6 weeks**. Python source is bind-mounted, so a `.py` fix takes effect on restart;
a dependency change does not.

---

## 2 · Capability matrix

Status vocabulary, chosen so "works" and "evidenced" cannot be confused:

- **Supported** — in the demonstration scope, with at least one probe case asserting its *output*.
- **Supported with a stated limitation** — usable, but the limitation must be said aloud.
- **Implemented, not evaluated** — the lane runs; nothing in the probe asserts what it returns.
- **Out of scope** — deliberately excluded; see §5.

| Capability | Status | Required building data | Evidence | Limitation |
|---|---|---|---|---|
| Structural questions (rooms, floors, zones, counts) | **Supported** | Brick TTL only | probe `counts`, `w0` | Floor count is 8 for a six-storey building; the answer must carry the explanation (rooftop + parking) |
| Amenity / wayfinding (nearest toilet, routes) | **Supported** | amenity TTL + floor-plan manifests | probe `circulation`, `w0` | Measured in floors, not a surveyed route; ignores walking distance, door types, lift status |
| Floor plans | **Supported** | PDF + DWG manifests | probe `capability-bypass`, `w0` | **0 of 17–38 floor-plan spaces link to an ontology IRI** on every floor — the plan and the graph are not joined |
| Registers / record documents (18 classes, 822 records) | **Supported** | register TTL | probe `departments`, `safety`, `assets`, `operations` | A held register matched by a generic shared word can outrank an absent one (**BUG-489**) |
| Honest refusal for an unmeasured quantity | **Supported** | — | probe `portability`, `honesty` | — |
| Honest refusal for a nonexistent room | **Supported with a stated limitation** | — | probe `honesty` (Room 9.99) | Some phrasings **time out at 180 s instead of declining** (**BUG-499**) |
| Live readings for a named room | **Supported with a stated limitation** | TTL + `ref:hasTimeseriesId` + `ref:storedAt` + rows | probe `capability-bypass` | Only where both halves of the join exist; a missing `storedAt` reads as absence |
| Comparison across floors | **Supported with a stated limitation** | as above, both floors | probe `w0` | Physically impossible readings are excluded **and disclosed**; 63–182 s, has exceeded a 121 s client timeout (**CAVEAT-467**, **CAVEAT-500**) |
| Asset status (lifts, plant) | **Supported with a stated limitation** | asset TTL + status records | probe `assets`, `w0` | **Counts describe the retrieved set, not the declared set** — "1 of 1 lift(s)" where the graph declares three (**BUG-497**) |
| Deliberation / ranking (ARBITER) | **Supported with a stated limitation** | TTL + readings across candidates | probe `deliberate` (2 cases, output only) | The ranker now resolves evidence origin and can exclude simulated candidates before ranking (V12-04). This building declares `evidence_policy: all_connected_readings`, so it does **not** — a ranking on floors 0–4 rests on placeholder readings and is **not evidence about the physical building**. Floor 5 (37 rooms, real instruments) is where a ranking rests on measurements. See §5. |
| Reports | **Implemented, not evaluated** | as live readings | none asserting content | The lane's six-defect chain was fixed 2026-09-07/08; nothing pins it |
| Document / manual answers | **Supported with a stated limitation** | `input/documents/` | probe `capability-bypass` | One incidental shared word can let an unrelated document answer (**BUG-218**, `PARTIALLY_FIXED`, 70.4% precision) |
| Forecasting | **Implemented, not evaluated** | history in a registered store | none | A request about future hours must say it uses current conditions only |
| Actuation | **Supported with a stated limitation** | `building.yaml` `actuation:` block | probe asserts the **lane**, not the outcome | **Not a flat decline.** `driver: sim` (log-only to Postgres `actuation_log`; nothing physical moves) with exactly **three** writable points — `VAV-501-SP`, `LIGHTING-3F-SP`, `AHU-F5-SP`. A request resolving to one of those is **queued for human approval** with a 15-minute expiry and needs `control:write` (admin / facility manager); anything else declines. See the correction note below. |
| Portability to another building | **Out of scope for this claim** | — | 2 building-agnostic probe cases, **never run elsewhere** | **R9 untested on this revision** |

---

## 3 · Where a language model runs — the call-site inventory

**35 call sites.** The often-repeated summary *"one neural step, then arithmetic"* is **true of the
ARBITER lane only**, and is false at system scope. Stating it unqualified is the inconsistency the
review flagged as **R6** (p. 9).

**Three lanes generate an artifact that is then executed:**

| Lane | Generates | Executed by | Control (verified) |
|---|---|---|---|
| `sql_agent` | SQL | storage adapter | `validate_query()` — first token must be `SELECT`/`WITH`, forbidden-keyword regex, called in **all six** adapters |
| `sparql_agent` | SPARQL | GraphDB | `sparql_validator.enforce_limit()` |
| `analytics_agent` | Python | `code-executor` | sandbox: `cap_drop: ALL`, `read_only`, `no-new-privileges`, 2 GB/CPU cap, `internal: true` network, secrets blanked |

The Python sandbox was verified **live**, not read from a compose file: internet DNS, host MySQL and
GraphDB are all unreachable from inside it. Generated Python can compute and can reach nothing.

The generated-SQL path is the **fallback**, taken only when no UUID group was resolved; the primary
path is the deterministic `_build_uuid_union_query`.

**The other 27 sites** are closed-vocabulary interpretation validated in code (intent classification,
CQ-IR compilation, multi-intent detection, disambiguation, co-reference rewrite) or narration of
already-computed numbers (report, analytics, SQL/SPARQL summary, anomaly, capability, visualisation,
persona framing).

**Not claimed:** that a test would fail if any of these controls were removed. That test does not
exist yet (review case **B16**).

---

## 4 · Intent manifest — 37 intents, and what the probe actually asserts

| Group | Count | Routing |
|---|---|---|
| `data` | 12 | shared pipeline: sparql → sql → analytics → visualization |
| `standalone` | 20 | one node answers, collected by `_response_node` |
| `meta` | 5 | answered directly |

Twelve intents carry no `node_method`; for the `data` group that is correct by design — they flow
through the shared pipeline. Routing is corrected by a **40-rule deterministic contract**
(36 parse + 1 post + 3 concept), whose precedence order is pinned by
`tests/test_routing_contract.py::test_precedence_order_is_pinned`.

> **The honest coverage statement: the probe asserts a LANE for 7 of 37 intents**
> (`control`, `diagnosis`, `floor_plan`, `observability`, `privacy_refusal`, `sensor_data`,
> `spatial_query`) and forbids a lane for 2. **Thirty intents have no lane assertion.** Every intent
> routing is *not* evidence that every intent answers well — review p. 15 says this explicitly, and
> it is the single easiest overclaim to make about this system.

---

## 5 · Out of scope — named, not quietly included

The review's rule (p. 17): *"For a demo, restrict or disable capabilities whose release-gate risks
remain unresolved. That is preferable to either hiding limitations or delaying every supported
feature."*

1. **Ranking answers as operational recommendations — RESOLVED BY DECISION, 2026-09-12.**

   V12-04 landed. `scorer.py` now takes a provenance verdict per candidate and excludes
   simulated-origin evidence *before* ranking, stating the exclusion; 685 points declare measured
   (`isSimulated false`), 1,409 declare simulated, and silence no longer reads as measurement.
   Wiring it in immediately caught the live instance the review predicted: a floor-3 ranking
   headed *"Best match: Room 3.27"* whose noise, illuminance and occupancy all came from
   SATURATE placeholders (**BUG-515**).

   **The owner then decided the protection should not be applied to this building.**
   `input/building.yaml` declares `provenance.evidence_policy: all_connected_readings`: every
   attached reading is authoritative and an answer does not distinguish simulated from measured.
   The reasoning is that floors 0–4 are placeholders **standing in for** instruments to be
   connected later, so refusing them would answer *"I cannot tell you about floor 3"* about a
   floor whose data is present and correct for what it represents. The origin is documented once,
   in `README.md`.

   **State this accurately rather than as a closure.** R4 is **accepted**, not resolved: the
   control exists, is tested, and is switched off here on purpose. A ranking on floors 0–4 rests
   on placeholder readings and is not evidence about the physical building. Floor 5, with 37 rooms
   of real instruments, is where a ranking rests on measurements.

   **What reopens it:** a supervised pilot, or any deployment where someone acts on an answer. Set
   `evidence_policy: measured_only` and the enforcement is already there.
2. **Any claim whose verification failed.** `grounded` is read in exactly one place and only chooses
   a memory bucket; it gates publication **not at all**. Until **V12-03**, a failed verifier changes
   nothing the user sees. This is **R1**, and it is why a fabricated "install a CO₂ sensor" report
   shipped carrying `grounded=False, confidence=0.20`.
3. **Physical actuation.** Out of scope in the sense that matters: the driver is `sim`, so an
   approved command is written to a Postgres log and **nothing in the building moves**. What *is*
   in scope is the approval workflow itself.

   > **Correction, made while writing this document (10 Sep 2026).** The first draft of this row
   > said actuation was out of scope and "declines by design", because that is what CLAUDE.md's
   > routing-precedence note says and what the probe case's own annotation claims. Asking the
   > system refuted it: *"Fix the temperature in here"* returns **"Command queued for approval
   > (ID 688bc706). Target `urn:bldg1:AHU-F5-SP`"**, because that point is in `points_writable`.
   > *"Open the windows on floor 3"* declines only because no window point is writable.
   >
   > The probe case for the windows asserts `expect_intent: control` and nothing about the
   > outcome, while carrying the note *"must reach the control lane and be declined there, with a
   > reason"* — so it passes whether the request is declined or queued, and its note describes
   > behaviour it does not check. **A safety-relevant capability was documented from a comment
   > instead of from the system.** Logged as **BUG-503**; the case needs an outcome assertion on
   > both sides of the writable/non-writable boundary.
4. **Portability / second-building onboarding.** No run on this revision.
5. **Occupancy or presence at a resolution the PDP would refuse.** Policy applies, but has not been
   tested on every output channel or as more than one identity (**V12-17**).
6. **Answers served from cache after a fix.** The cache key carries no revision, so an answer from
   older code stays servable for the 1 h TTL (**BUG-498**).

**Bounded composition is not supported.** A request needing observations *and* a documented
procedure gets the observations only, and the procedure half is currently neither attempted nor
mentioned. Until **V12-06**, the unserved half must be stated by the person demonstrating.

---

## 6 · The evidence, and its limits

- **Offline suite:** 5,476 pass. Establishes that the code does what its tests say. Every serious
  defect of the last week passed straight through it — they live in the seam between model, graph
  and store.
- **Live probe:** 57/59 first-pass. Establishes that these 59 questions returned these facts on this
  build, this model, this building, once.
- **The uncomfortable one:** *all 59 probe cases have been used to tune the implementation*, so by
  the review's definition (p. 14) **none of them is held-out evidence**, and adding cases to that set
  cannot fix it. **V12-29** draws a sealed set and runs it once. **No coverage or accuracy percentage
  should be published before that.**
- **Not measured:** latency percentiles per workload. The "typical answer 14 s" figure does not
  survive a measured spread of 10.7 s → 61.1 s → past 121 s on identical input (**CAVEAT-500**), or
  a multi-minute total API outage (**CAVEAT-502**).

## 7 · Open items that bound this scope

### 7.1 · Nine fixes from 2026-09-12 are NOT yet verified live

This section leads with them because they are the newest and the least proven, and because
the previous version of this document had no equivalent — which is how an owed queue grows.
Each is FIXED in code with offline tests and carries `LIVE RE-ASK OWED`; **V12-32 discharges
them, and it is sequenced before V12-29**, since a sealed evaluation run over unverified
fixes measures the fixes rather than the system.

| Row | What it claims to have fixed | Why it is not yet scope |
|---|---|---|
| BUG-517 | ARBITER resolved "yesterday" and "today" to the SAME rolling 24h window, in UTC | P1. The deliberation lane's window is repaired offline; no live turn has been read back |
| BUG-518 | A room booked in the next hour could be reported free (booking window built from `utcnow()`) | An availability answer has not been re-asked |
| BUG-519 | Freshness advice reported every reading an hour younger than it was | The recheck line's stated age has not been checked against the store |
| BUG-521 | A narrow-table report averaged CO₂ ppm with temperature °C into one number | P1. No live narrow-table report has been generated since |
| BUG-524 | A co-reference rewrite could swap the room the user named | No live two-turn switch |
| BUG-525 | Carried-forward analytics were injected into a turn about a different room | No live two-turn switch |
| BUG-183 | "yesterday" turning a valid question into a clarification | Its own row was REFUTED on live re-ask once already. The deterministic half is rebuilt; the 279.5 s timeout that accompanied the refutation is untouched |

Two remain OPEN by choice rather than by omission: **CAVEAT-523** (the census overlap probe
costs one extra SPARQL round trip — accepted, latency unmeasured) and **BUG-526** (a room
label that prefixes several real ids resolves to "exists" with no record of the ambiguity —
P3, owned by V12-33 with the shape of the fix written down).

### 7.2 · Longer-standing items

Fifteen rows are not closed. Four are P1-class: **BUG-218** (document precision 70.4%),
**CAVEAT-415** (62 failures logged an empty message, hiding an 11% silent quality gap),
**CAVEAT-501** (the register was outside version control), **TODO-072** (cold GUI-only onboarding
never run live). The rest are listed in `tasks/FIX_TRACKER.csv`; `python scripts/v12_coverage_audit.py`
re-derives the set and fails if anything is unclaimed.

---

*Falsified by: any probe case added or removed, any routing-rule change, any new building, any model
change. Re-measure — do not edit the numbers.*
