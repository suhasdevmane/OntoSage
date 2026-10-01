# Lessons — patterns to avoid repeating

## 2026-06-11 — V3 verification audit findings

1. **"Tests pass" ≠ "it works".** 121 unit tests were green while the feed write path
   (`write_records`) was not implemented on ANY adapter — every feed record was silently
   dropped for the entire V3 build. Unit tests injected a fake writer, so nothing caught it.
   Lesson: every "data lands in store X" acceptance criterion needs at least one live check
   that reads the store back (`SELECT COUNT(...)`), not just a green unit suite.

2. **Run `flake8 --select=F821` on the WHOLE tree, not just touched files.** Three F821s
   (undefined `state` in `analytics_agent._generate_code`, `_user_query_raw` used before
   definition in the preference detector, missing `List` import) shipped across multiple
   turns. Each crashed a feature at runtime. The blocking gate exists — it was just run
   per-file instead of repo-wide.

3. **Derived identifiers must have exactly one source of truth.** Feed UUIDs were derived
   in `feeds/registry.py` (full 8-4-4-4-12 format) but hand-copied into migration SQL
   (8-char prefix) and TTL (`hasTimeseriesId`, 8-char). All three must match for
   SPARQL → SQL joins. Generate migrations/TTL FROM the code (`_derive_uuid()`), never
   transcribe by hand.

4. **`data/mysql-init/*.sql` does not run on existing volumes.** It is docker-entrypoint
   init only. Host MySQL (or any existing volume) needs migrations applied manually.
   Also: `ADD COLUMN IF NOT EXISTS` is MariaDB-only — MySQL 8 rejects it.

5. **InnoDB hard limit: 1017 columns per table.** The wide-format `sensor_data` (681 cols)
   cannot hold the 522 floor-0-4 sensor columns + feeds. The floors 0-4 wide-column plan is
   structurally dead; needs a long-format (uuid, ts, value) table or partitioned design.
   Decision deferred to user.

6. **Container uptime lies about code freshness.** The orchestrator was "Up 22 hours
   (healthy)" while the image predated several turns of code; the rebuilt image then
   crash-looped on a TTL validation error nobody saw because the old container kept serving.
   After any code/config change, check the image build time, not the container status.

7. **Don't trust invented UUIDs in seed config.** `rules.yaml` shipped with made-up sensor
   UUIDs; the rules engine polled a nonexistent column every 60s. Seed config referencing
   runtime identifiers must be cross-checked against the live store (or sensor_uuids.json).

8. **URL-encode the whole query-param token.** `?context=<urn:...Brick+extensions.ttl>`:
   the `+` decodes as a space server-side → "Invalid IRI". Use `urllib.parse.quote(..., safe="")`.

## 2026-06-12 — full-system verification findings

8. **Deterministic overrides must reach routing, not just state.** T22/T34/benchmark
   overrides wrote `intermediate_results["intent"]` but `_route_from_dialogue` reads
   `state.current_intent`, set by a legacy local-variable chain — every override was dead
   live while all unit tests passed (they set current_intent directly). When two
   representations of the same fact exist (local var, intermediate_results, current_intent),
   every write site must update the one routing actually reads.

9. **A registry is only as data-driven as its dumbest consumer.** Intents auto-register
   from YAML, but the dialogue node's legacy if/elif chain didn't know `alert` /
   `preference_management` / `automation_capability` and defaulted them into the sparql
   pipeline — "list my alerts" listed power sensors. New YAML intents silently broke.
   Generic mechanisms must not funnel through hand-enumerated dispatch.

10. **State contracts need a producer, not just consumers with defaults.** Agents read
    `user_role` with `.get(..., "readonly")` for months while NO endpoint ever wrote it —
    every RBAC-gated conversational feature was a permanent decline, masked by the default
    looking like a legitimate value. If a key gates behaviour, assert its presence (or log
    loudly on default) instead of silently defaulting.

11. **Embedding-provider switches invalidate similarity thresholds.** building.yaml
    documents this contract, but nothing enforces it: thresholds calibrated on MiniLM
    (0.56/0.60) ran against OpenAI vectors and the capability KB hijacked plain data
    questions at 0.684. Either pin the provider in config next to the thresholds or add a
    startup check that the calibration provider matches the active one.

12. **LLM-extracted structures need shape-tolerant readers.** Entities arrive as dicts OR
    bare strings depending on the model's mood; `e.get("type")` on a str crashed every
    control command. Any code consuming LLM-emitted JSON must tolerate both shapes.

13. **Validators must fail on absent subjects.** `validate_building_input` on a
    nonexistent building returned PASS (all files "absent — skipped"). A validator that
    can't tell "everything optional is absent" from "the thing doesn't exist" silently
    blesses typos (`--to bldg2` vs `--to bld2`).

14. **Mocks must mirror the real interface, or they bless broken code.** Three Redis
    stores called accessors that never existed on RedisManager (`get_client()`,
    `_ensure_client()`, `.redis`) — every approval write, alert list and preference scan
    silently failed in production while their unit tests passed, because the test mocks
    exposed the same phantom methods. When mocking a manager, mock the attribute the real
    class defines (`.client`) — better, add one canonical accessor and test against it.

15. **"Auto-wired" must mean wired, end to end.** Registry intents got nodes auto-registered
    but no outgoing edge to response — they ran, produced an answer, and the answer was
    dropped (user saw their own message echoed). A node is only wired when input routing
    AND output edges both exist; the wiring test now inspects the compiled graph's edges,
    not the source text.

16. **Any regex over user phrasing must survive the co-reference rewriter.** "approve
    606ba770" was expanded to "Can you please approve the command with ID 606ba770 …"
    before the control agent saw it, so `approve\s+<hex>` never matched. Either exempt
    short command patterns from rewriting or write rewrite-tolerant patterns.

17. **When behaviour changes by design, update the QA expectations in the same change.**
    T25 changed control from always-decline to guarded-approval, but the QA suite still
    asserted a decline — the correct new behaviour graded as WARN for a day. A feature
    flip is not done until the canonical QA battery encodes the new contract.

18. **A benchmark's code version is part of the experiment — freeze it before the first
    arm.** Mid-run through the 6-arm T44 model benchmark I fixed BUG-170 in
    `dialogue_agent.py`. The orchestrator bind-mounts `orchestrator/`, and each arm swap
    does `docker compose up -d` (a real recreate, because `.env` changed), so the
    container re-imports Python and arms 3-6 would have run *different code* than arms
    1-2 — in the exact path the benchmark measures (intent classification, hence whether
    a question reaches the deliberative lane). No error, no warning; the results table
    would simply have been quietly invalid. Killed and re-ran the whole thing on a frozen
    tree. This is the same class as CAVEAT-173 (`docker compose up -d` mid-benchmark) but
    subtler: the earlier version mutated the *stack*, this one mutated the *source* under
    a stack that reloads on each arm. Rule: once a multi-arm run starts, no edits to
    anything the container imports — do offline work (tests, docs, tracker) or stop the
    run first. Corollary: killing the run skips the harness's `finally`, so `.env` is left
    on whichever arm was live — always restore it from the backup the harness wrote, and
    restore only the keys it owns so later unrelated edits are not rolled back.

19. **When a parameter is used twice, check it means the same thing both times.**
    BUG-170: `top_k=5` is the RAG retriever's *entity* budget, and the caller then reused
    it to slice the *returned context* (`contexts[:top_k]`) — so a 5-entity retrieval that
    produced 1078 triples was cut to the summary plus four, discarding what had just been
    fetched at full cost. Everything looked healthy: the call succeeded, the log said
    "Retrieved 1079 context items", answers came back. `sparql_agent` had it right all
    along (`top_k=10  # Entity retrieval limit` plus a separate `triples[:50]`), which is
    the tell — when two call sites treat the same field differently, one of them is wrong.

20. **A guard that fails open must never fail silently.** The CAVEAT-190 referent check
    was written to fail OPEN (run the trap rather than drop it) — correct, because a skip
    mechanism that quietly shrinks a certification denominator is worse than the problem
    it solves. But it failed open *in silence*: `except Exception: return ""`. Since ""
    also means "nothing to skip", a completely disabled check was indistinguishable from
    a check that found nothing, and it sat dead through a full 39-trap certification run.
    The actual cause was mundane — `scripts/leak_benchmark.py` never put the repo root on
    `sys.path`, so `import orchestrator…` raised ModuleNotFoundError when run as
    `python scripts/leak_benchmark.py`. Rule: every fail-open path prints why it gave up.
    "Couldn't check" and "checked, found nothing" must never render identically.

21. **Testing a function is not testing the program.** My verification of that same check
    passed — because the test did `sys.path.insert(0, '.')` before importing. The function
    was fine; the *invocation* was broken, and the test had quietly repaired the exact
    thing that was broken in production. Verify through the real entry point (same cwd,
    same argv, same sys.path) at least once, or the test is measuring the harness rather
    than the system.

22. **One weak heuristic can move a headline number in both directions.** The leak
    grader's `expected=answer` rule was "if any number appears, it PASSed", with an
    unbounded number regex. That single line scored a genuine fabrication as PASS
    (BUG-189: a room's reading attributed to a corridor that does not exist) and, days
    later, scored three honest refusals as PASS (BUG-191: the "2" inside "bldg2" counted
    as a reading), producing a spurious 39/39 certification. When a metric looks perfect,
    inspect the rows behind it before reporting it — a green number is a claim about the
    grader as much as about the system.

23. **A number that lands on exactly one half, on every partition, is a structure — not a
    measurement.** The floor-plan join rate read 50.0% on floor 0, floor 1 *and* floor 2 of
    bldg2. A genuine partial-join failure produces a noisy fraction that differs per floor;
    a clean 50.0% repeated three times can only come from something built in twos. It was:
    every room existed as two half-records — CAD geometry with no identity, PDF identity
    with no geometry — because the merge paired them on `zone_id` and the two sources mint
    ids from different things, so the id spaces never intersected. Rule: when a rate is
    suspiciously round or identical across independent partitions, stop reading the rate
    and read the rows. The shape of a number is evidence about its cause.

24. **The fix looked like it worked because a later stage repaired the symptom.** After the
    merge fix, the first re-ingestion reported 100% linked — and the space count had not
    changed at all. The merge had not run; the endpoint's own follow-up linking pass had
    simply given *both* copies of every room an IRI. The headline metric said "fixed" while
    the defect was untouched, and closing on it would have been a false positive on the
    very bug I had just spent the session diagnosing. Rule: verify the mechanism you
    changed, not only the metric it was supposed to move. Here that meant asserting the
    space *count* fell, not just that the rate rose.

25. **A guard that is too blunt destroys the thing it protects.** To stop a re-ingestion
    feeding the merged manifest back in as its own input, I first dropped every CAD-sourced
    space from the PDF side. Its own idempotence test failed immediately: correctly merged
    records are CAD-sourced too, and they are the ones carrying the ontology IRI, so a
    second re-ingestion would have silently stripped identity building-wide. The precise
    rule — drop a CAD-sourced space only when another space in the same list also claims
    its label — keeps merged records and removes only leftovers. Rule: when writing a guard
    against bad input, name the *signature* of the bad input, not the category it belongs
    to; the good data usually belongs to the same category.

26. **A routing rule is dead if something returns before the contract runs.** The fix for
    CAVEAT-201 was a new parse-stage rule; 18 unit tests went green and the live query was
    completely unchanged. `dialogue_agent` has a capability short-circuit that returns
    `intent="capability"` *before* the LLM call — and `apply_contract(stage="parse")` runs
    inside `_parse_llm_response`, which that return never reaches. The rule was correct and
    unreachable. The real fix was a public predicate in `routing_contract` consulted by BOTH
    the rule and the short-circuit's bypass chain, so the two cannot drift. Rule: before
    adding a routing rule, find every path that can produce an intent WITHOUT running the
    contract; a rule only governs the paths that reach it. Corollary: when a change is
    unit-green but live-unchanged, suspect an earlier return, not a caching problem.

27. **Pick the question a guard asks by what it returns on real data, not by what it sounds
    like it should catch.** The BUG-203 guard began as "what lives outside every named
    graph?" — a precise statement of the failure and a useless check: it returned 1,576,783
    findings, because GraphDB materialises inferred superclass types and Brick ships a
    million SHACL rule nodes, none of which is a defect. Rephrasing it as "is anything typed
    with a class that NOTHING declares?" — scoped to the namespaces this system mints into —
    returned exactly the 56 real ones and nothing else. Same underlying bug, same data, a
    guard that went from unusable to actionable. Rule: run a candidate guard against the
    live system before shipping it, and judge it by its signal-to-noise on that run. A
    warning at 1.5M teaches people to ignore warnings, which costs more than the bug.

28. **Audit where the gap actually is before building the fix.** TODO-072 read as "build cold
    GUI onboarding", implying missing backend. Grepping the console for callers of each
    onboarding endpoint showed the opposite: every one of the five steps already had a
    working endpoint, and three of them — identity, documents, floor plans — had no control
    anywhere in the UI. The claim "a building is onboarded entirely through the Admin
    Console" was true of the API and false of the product. Ten minutes of `grep -rln
    "<endpoint>" frontend/src/` redirected the whole task from backend work to a screen plus
    one readiness endpoint. Rule: for any "feature X is missing" item, first map which layer
    is missing it. The row's framing is a hypothesis, not a finding.

29. **"Implemented and dispatched" is not "works".** TODO-143 recorded that the TimescaleDB and
    Cassandra adapters were implemented and wired into the registry, so the capability was
    "defensible in code" — only the fixture was missing. Standing the backends up found that
    `cassandra-driver` was not in requirements and not in the image, so `connect()` could only
    ever have raised ImportError; and the first test to construct a Postgres/Timescale adapter
    from a partial config hit `settings.PG_PORT`, an attribute that does not exist (BUG-204).
    Neither would have been found by reading the code — both live in paths nothing ever took.
    Rule: a capability with zero tests and zero callers is unproven regardless of how complete
    the source looks. Run it against the real thing before claiming it in a paper.

30. **Measure the fix candidate before believing it — including your own.** BUG-218's tracker
    row proposed a proportional-overlap rule. Swept against 377 hand-labelled answers it flagged
    70% of off-topic ones and 44% of correct ones: 51.0% precision against a 39.3% base rate,
    i.e. chance. I then proposed my own rule ("the question names a term absent from the
    corpus") and it was worse — 97% of off-topic but **99% of correct**, useless. The only
    candidate that beat chance was the one both of us had reasons to doubt (per-corpus document
    frequency, 70.4%). Rule: when a fix has a knob, sweep the knob against labelled data before
    shipping. Two experienced guesses in a row were both wrong, and thirty minutes of
    measurement settled it.

31. **"Costs nothing" is a claim, and it is usually false.** I justified hedging weak document
    matches by saying it costs no recall, unlike dropping them. True as far as it went — but
    when I measured a broader hedge that would catch 80% of off-topic answers, it also hedged
    **47% of correct** ones. The hedge says "I could not find a passage that directly addresses
    this"; on an answer that did address it, that sentence is false. Hedging is not free, it
    just spends a different currency: dropping costs coverage, hedging costs *accuracy about
    your own output*. Rule: name the currency a mitigation spends, then measure how much.

32. **Verify the agent's numbers, not just its reasoning.** A subagent's BUG-218 investigation
    was excellent and reported DF("clean") = 4 of 5 documents. The real corpus has **1**. That
    single wrong number was the entire justification for the fix catching its own motivating
    example — which, measured, it does not. The diagnosis, root cause, code references and
    line numbers were all exactly right; one derived statistic was not. Rule: re-derive every
    quantitative claim you intend to act on, even from a report whose qualitative work is
    demonstrably careful. Correctness is not transitive across a report.

33. **A number you computed can be an artifact of your own query.** Auditing sensor
    connectivity I reported "522 UUIDs carry no storedAt". That was a property of my SPARQL,
    not of the graph: I selected `DISTINCT ?s ?u ?store` with `OPTIONAL`, so a UUID with two
    reference nodes — one carrying storedAt, one not — produced two rows and landed in the
    "missing" bucket. The correct question ("no storedAt on ANY of its reference nodes")
    returns **0**. Caught only because 522 exactly equalled another number on the same screen.
    Rule: before reporting a surprising count, write the negation as its own query. And treat
    a suspicious coincidence between two figures as a bug report about your method.

34. **grep is not a parser.** Counting UUIDs in the TTL files with
    `grep -o 'hasTimeseriesId[^;]*'` gave 2,693 against the graph's 2,598 — a 95-link gap that
    read as data loss from a deletion performed an hour earlier. Re-parsing the same files with
    rdflib gave 2,584, every one present in the graph, **zero missing**. The grep was counting
    quoted strings that were not UUIDs. Rule: when a discrepancy would imply damage, re-derive
    it with a real parser before raising it — and especially before raising it with the person
    who authorised the deletion.

35. **Connecting the data is only half of making it answerable.** Ninety points were described
    in the ontology and backed by no database; linking them and seeding declared-synthetic
    streams took coverage to 100%. The very next probe showed the questions still could not
    reach them: "what is the power draw of the EV charging stations?" was answered with the
    building's transport-and-parking blurb, because `is_data_query()` recognises a measurement
    question only when it names a ROOM or FLOOR, and these sensors measure equipment. Rule:
    after connecting a data source, ask a question that needs it. Coverage measured at the
    storage layer says nothing about reachability at the routing layer (BUG-225).

36. **An offline replay of a live system is a different system, and its findings are about
    that one.** Sizing what was left of BUG-231, I replayed the routing contract over the
    baseline questions offline and concluded that 83% of the remaining capability population
    carried no structural cue and was unroutable. It was an artifact of the harness: I called
    `apply_contract` with `stage="parse"` and `stage="post"` and an empty `concepts` list, but
    the rule that routes capability→data is a CONCEPT-stage rule that reads `concepts`, which
    the HBCO resolver fills at runtime. The replay was measuring the system with the concept
    resolver switched off, which is why it "discovered" hundreds of unrouted data questions
    ("What's the CO2 in the lecture theatre right now?") that the live system already routes
    correctly. Fifth measurement-apparatus bug in this project's history. Rule: when an
    offline replay disagrees with a live capture, the replay is wrong until proven otherwise —
    and before trusting one, check that every stage the real pipeline runs is a stage the
    harness runs, with the same inputs.

37. **Re-derive the size of a problem before writing the fix, not after.** BUG-231 was carried
    as P1 on the strength of "746 questions, 48% of the corpus" — a figure measured before the
    routing fixes landed and never recomputed once they had. Re-measured on the live
    post-routing capture, the misrouted slice was about twelve questions, roughly 4%. Three
    signals had already been designed and rejected against the stale figure. A number that
    justifies a priority has to be as current as the code it is about; otherwise the work is
    aimed at a system that no longer exists.

38. **A lay term is a corpus-wide change, so measure it corpus-wide.** The obvious fix for
    presence questions was to add "anyone", "someone", "free", "people", "crowded" to the HBCO
    mapping. Every one failed when checked against all 1,562 answered questions: "someone" is
    0-for-13 (it means people-as-agents — protocols, complaints, wheelchair assistance),
    "anyone" 1-for-6, and "free" is worst of all, because 62 questions contain it and they are
    dominated by booking availability and by STEP-FREE accessibility routes, which a
    word-boundary match happily catches. Rule: for anything that changes how every question is
    interpreted, the test is not "does this word mean X" but "of all the questions containing
    it, how many mean X".

39. **`docker exec python -c "import settings"` does not tell you what the server is running.**
    I checked that the new retrieval floor was live by exec'ing into the container and printing
    `settings.document_score_floor`. It said 0.55, so I started an 85-minute capture. But
    `./shared` and `./orchestrator` are BIND-MOUNTED: a new Python process inside the container
    reads the current host file regardless of what the long-running server loaded at start-up.
    The check confirmed the file on disk, which I already knew, and told me nothing about the
    process answering requests. The real deploy landed 48 minutes into the capture, so half the
    rows ran on the old floor and half on the new one — and every row was individually valid, so
    the harness reported `--resume` and no error. Verify a deploy by asking the RUNNING service
    through its own API (or compare the container's `StartedAt` against the edit), and treat a
    mid-run container recreate as invalidating the whole run, not just the rows that errored
    (CAVEAT-173 again, third time).

40. **A gate whose input nothing populates is worse than no gate.** `gates.py` had four fully
    implemented, unit-tested gates — freshness, completeness, spatial adequacy, calibration —
    and not one was ever called: the chokepoint reads `results["gate_verdicts"]` and no lane
    writes it. Three V6 turns were marked done on the strength of the modules, with acceptance
    criteria stated about live behaviour. Compounding it, the freshness gate's input
    (`latest_evidence_at`) was itself documented, read, and never written. Two halves of a
    feature owned by different turns, with the wiring belonging to neither, and a parameter
    that defaults to empty so the gap raises nothing. Rule: an acceptance criterion phrased as
    "the system does X" is not met by a function that could do X. Probe the running system.

41. **Aggregating over a result set that spans two stores re-creates the bug you just fixed.**
    `latest_evidence_at` took the maximum timestamp over every row returned. A CO2 answer
    resting on a two-day-old narrow-table row was recorded as forty seconds old, because a
    wide-table row for an UNRELATED sensor shared the result set — one live sensor certifying a
    dead one, which is CAVEAT-233's per-table illusion arriving through a third door, and the
    same shape as BUG-234's single-store validation. Rows are attributable in both shapes
    (narrow carries a `uuid` column; in wide the uuid IS the column name), so the fix was per-
    sensor attribution plus judging freshness on the OLDEST contributor: an answer is only as
    current as its stalest ingredient.

42. **A fix can pass its own tests and do nothing in production, when the tests assume a shape
    the system does not use.** My first per-sensor attribution keyed on sensor UUIDs and every
    test tagged sources that way. Live, the lanes tag provenance by STORE (`store:co2_data`),
    so no source ever matched, the gate fell through to the maximum, and the fix was inert
    while fully green. Caught only by a live probe. When a fix depends on the shape of data
    another component produces, read that component's real output before writing the test —
    and pin the real shape as a test of its own.

43. **The same identifier arrives in three notations.** A Brick class reaches the evidence code
    as a full IRI (from the HBCO mapping), as a CURIE `brick:CO2_Level_Sensor` (from the concept
    resolver), and as a bare local name (from the modality config). Stripping only `#` and `/`
    left the CURIE intact, nothing matched, and every modality silently fell back to the DEFAULT
    freshness limit — CO2 judged at 15 minutes instead of its configured 5. A per-modality
    policy that never selects a modality is not a policy, and it fails quietly because the
    default is plausible.

44. **Two adjacent keys on one payload, and the reader took the wrong one for weeks.** `/chat`
    returns `evidence` (the older dossier, no gates on it) and `evidence_record` (the V6-T02
    record, which has them). The capture read `evidence`, so `gates` and `answer_status` were
    empty on 309 of 309 and 306 of 306 rows — every capture ever taken. The regression gate's
    only discriminator is "worse + a gate fired = tightening; worse + no gate = REGRESSION", so
    the second branch was unconditionally true and **no intended tightening could ever be
    recognised**. It surfaced only because a change I expected to produce tightenings produced
    eight regressions instead, and the mismatch between prediction and verdict was worth
    chasing. Third instance in two days of the same shape: an interface where one side's
    absence yields a legal-looking value rather than an error (BUG-236's renamed alias, V6-T03's
    never-written field, this). When a measurement column is uniformly empty across every row,
    that is a bug report about the instrument, not a property of the system.

45. **When the result contradicts the prediction, suspect the instrument before the system.**
    The sweep predicted ~2.6 removed-wrong per removed-right, all classified as tightenings.
    The gate returned zero tightenings and eight regressions. I could have read that as "the
    floor is worse than predicted" and reverted a correct change; the actual cause was that the
    gate had never been able to see a tightening at all. A prediction that fails in a
    structurally impossible way — zero of a category, not few — is evidence about the measuring
    apparatus.

46. **A duck-typed `getattr` against a private name fails silently and looks like a decision.**
    `MySQLNarrowAdapter` keeps its table in `self._table`. Two probes asked
    `getattr(adapter, "table", None)` to decide narrow-vs-wide, got None, and took the wide
    branch — which intersects the WIDE table's uuid-shaped column names with a narrow store's
    uuid values. Disjoint by construction, so the answer was a confident zero for every narrow
    store, and I published it as "every narrow table has 0 live streams". Nothing raised,
    because `None` is also what the wide adapter legitimately means. Corrected figure: 1254 of
    2796 live, not 683 — one whole store (522 streams) had been counted as nothing. Rule: when
    a probe's answer is uniform across a whole class of inputs, check the discriminator before
    believing the result; and expose the attribute an interface depends on rather than letting
    callers reach for a private name.

47. **The number that survives a bug is not evidence the bug was small.** CAVEAT-233's headline
    (100% coverage against ~24% liveness) was dominated by one genuinely-wide store, so it read
    as plausible while every narrow line beneath it was fabricated by the defect. A correct
    aggregate can sit on top of wholly wrong components. When a breakdown is published, the
    breakdown needs its own check — the total agreeing with expectation is not one.

48. **A corrected document is not a verified one.** `agent-patterns.md` carries a warning, added
    days ago, that its reserved-key list once named `sparql_results` and `sql_data` — strings
    that appear nowhere in the pipeline — and that the evidence assembler was written from the
    list rather than the code, so the two main data lanes could never be identified. Directly
    below that warning sat `uuids`, also never written by anything. Three readers believed it:
    `_sources_from` created no per-sensor sources at all, and both per-source fields added this
    week had nothing to attach to. Fixing the entries that were known to be wrong did not
    prompt anyone to check the rest of the list. Rule: when a list is found to be wrong, verify
    every entry, not the ones that were noticed.

49. **Wire a gate and then ask the running system, because "correctly wired" and "produces a
    verdict" are different claims.** The spatial gate passed 11 unit tests, was wired at the
    chokepoint, and emitted nothing at all on a live probe — its input guard read the phantom
    key above and returned before doing any work. The tests were right about the logic and
    silent about the plumbing, which is the same gap that let three V6 turns be marked done
    while nothing invoked them.

50. **Audit the whole tracker the way you audited the one row.** Finding T13/T16/T17 unwired
    (BUG-237) was treated as a three-row correction. A reachability audit of every module a
    week later found the same defect in TEN more turns — history, sensor_health, narration,
    conflict, aggregation, access_tiers, causal_guard, omissions, time_windows,
    trend_integrity — plus a second systemic gap the row-by-row work never surfaced: the
    entire V6 TBox has zero ABox instances, so the schema half of "TTL-first" was done and the
    data half was never scheduled. A defect found N times by hand is a class; the response to
    a class is one sweep with a mechanical check (does the pipeline import it; does the
    property have instances), not N+1 spot fixes. The tracker's done-count fell from 30 to 20
    under that sweep, and the honest number is the useful one.

51. **A patch script that edits a file black has since reformatted will match nothing — or
    worse, half-match.** The zone-validation patch asserted against the one-line dict literal
    it had written earlier; black had reflowed it to seven lines after an intervening patch,
    so the init replacement silently targeted a stale form, left `"loc"` beside the new
    `"locs"`, and the fetcher raised KeyError on its first real row — returning {} through its
    own safety net, which read as "no facts" rather than as a crash. Two rules: re-read the
    exact current text immediately before writing an old_string against it, and when a
    function's failure mode is a silent empty result, test the non-empty path live after
    every edit that touches it.

52. **Git Bash rewrites container paths.** `docker exec c python /tmp/x.py` arrived inside the
    container as `/app/C:/Users/.../Temp/x.py` — MSYS path conversion mangles `/tmp` on the
    way through. Several diagnostic runs silently produced nothing before the cause surfaced.
    Route container commands through `sh -c '...'` so the path crosses as written.

53. **Row order is not a fact about the building.** A sensor with two asserted locations was
    graded on whichever location SPARQL returned first — the grade changed with join order.
    When a graph property is multi-valued, collect all values and let the DECISION pick
    (exact target match wins); first-wins is a hidden dependency on the store's iteration
    order, the same class of accident as BUG-184's plan_hash.

54. **A test with an unknown key passes everything and proves nothing.** The first draft of
    `test_identifier_digits.py` called `implausible_values(text, "noise")` when the registered
    measurand key is `"sound"`. An unrecognised key makes the function return `[]` for every
    input, so all seven assertions passed — including the ones meant to fail. Only the control
    ("a genuinely impossible reading is STILL caught") exposed it, by being the one assertion
    that expected a non-empty result. Rule: every guard test needs a positive control in the
    same file. A suite of negative assertions cannot distinguish a working guard from a
    disabled one, or from a lookup that silently missed.

55. **`\b` through a bash heredoc becomes a backspace — five times now.** The report-intake
    space resolver's `\b(room|zone|...)` reached disk as `\x08(room|zone|...)`, compiled
    cleanly, and could never match, so every report stored an unbound space while the pieces
    all worked in isolation. Lessons #30-35 already say to use the Write tool for anything
    containing a regex escape; I used a heredoc anyway because the edit looked small. There is
    now a repo-wide test asserting no control character appears in any service module, so the
    sixth occurrence fails at commit rather than in a live probe.

56. **Read the message by ROLE, not by index.** The permission guard silently passed every
    entitlement question because it read `state.messages[-1]` for the user's text. Elsewhere
    in the same file the question is correctly read as `messages[-2]` — the assistant's reply
    has been appended by that point, but not at the chokepoint. Both indices are "the last
    message" and neither is "the question". Positional access to a list whose length depends
    on where you are in the pipeline is a bug waiting for a refactor to trigger it.

57. **A config map keyed on invented vocabulary is dead policy that reads as live.**
    `consequence.by_shape` used shape names — `compliance_verdict`, `standards_check`,
    `control_command`, `booking_query` — that the router never emits. Every question therefore
    resolved to `informational`, so no claim ever required calibration or an authoritative
    source, and the whole of T32's consequence scaling had been inert since it was written. It
    surfaced only when T34's gate was wired and refused to fire on an obvious compliance
    question. Same family as BUG-241 (a reserved bus key nothing writes): a mapping written
    from an idea of the vocabulary rather than from the code that produces it. There is now a
    test asserting every key in the map is a real intent or a declared alias.

58. **A negative-only test suite cannot tell a guard from a no-op.** Seven assertions in the
    identifier-digits file passed while proving nothing, because they all called
    `implausible_values(text, "noise")` and the registered measurand key is `"sound"` — an
    unknown key returns `[]` for every input. Only the positive control ("a genuinely
    impossible reading is STILL caught") exposed it. Every guard test needs at least one
    assertion that expects the guard to FIRE.

59. **The shadow-mode report earns its keep the first time it is read.** Seven gates advisory,
    three producing verdicts, and the very first impact report exposed two defects: a gate the
    report could not describe (its label map predated the gate) and six false positives from
    freshness judging wayfinding answers — geometry that has no measurand and cannot be stale.
    Enforcing on the uncorrected figure would have started refusing "how do I get to the
    seminar room" for insufficient freshness. The number was wrong in the safe direction only
    because nothing was enforcing yet, which is exactly the argument for advisory-first: the
    blast radius is reviewable before it is felt (D-9).

60. **An empty interpolation in a generated string is a signal, not a cosmetic flaw.**
    "the newest  reading is 1839 minutes old" and "no  observation is available" both carried a
    double space where the modality should have been, in two separate investigations. Both
    times it meant the same thing — the measurand never resolved — and both times it was
    visible in output I had already read without registering it. A template that renders an
    empty variable should be treated as a failed lookup, because that is what it is.

61. **Three layers can each be right while the feature is broken.** T24's joined ticket view
    failed live three times for three unrelated reasons: the question never reached the events
    lane (the capability probe answered from a document matching on the word "open"); the lane
    read zero reports (the intake singleton had no database, because only one caller ever hands
    it one); and the answer was then refused wholesale (the numeric guard found figures in the
    prose that the payload did not carry). The routing contract, the merge logic and the guard
    were each behaving correctly. A live probe is the only thing that exercises the seams
    between them, and each failure looked like success from inside its own layer.

62. **A singleton that receives its dependency from one caller is a hidden ordering
    contract.** `get_report_intake_service()` was only ever handed a Postgres connection by the
    report-intake node, so every other reader got a working object that returned `[]`. Empty
    from misconfiguration is indistinguishable from empty because the building has none — and
    here it was silently reporting "no reports" on a store holding 154. Prefer lazy acquisition
    over hoping the right caller runs first.

---

## 59. A triple that is present, correct, and INVISIBLE (2026-08-24, V6-T26)

Three times in one generator, in one session, I emitted a fact in a convention nothing
downstream reads:

| wrote | building actually uses | cost |
|---|---|---|
| `brick:isPartOf bldg:Floor5` | `brick:hasLocation` (what the floor template walks) | the right points resolved, then a template that could not locate them returned 0 rows |
| `brick:hasUnit "Pa"` | `qudt:hasUnit <unit:PA>` (875 triples vs 101) | a Pascals reading answered as **"152.5 psi"** — a 6,895× error |
| `ref:storedAt bldg:plant_data` | key must ALSO be in `building.yaml storage.databases` | registry silently served the WIDE adapter, which reads a uuid as a column name |

Each triple was factually correct and validated clean. Each was ignored by the exact machinery
it existed to feed, and each failure surfaced far away as something else: "0 results", "no
current value is provided", `Unknown column '2532e981-…'`.

**Rule: before emitting a predicate, ASK THE GRAPH which predicate this building already uses
for that fact.** One query:
`SELECT ?p (COUNT(*) AS ?n) WHERE { ?s ?p ?o FILTER(CONTAINS(LCASE(STR(?p)),"unit")) } GROUP BY ?p`
would have shown 875 `qudt:hasUnit` against 101 `brick:hasUnit` in three seconds. Inventing a
second convention for an existing fact is the same defect as the duplicate-store one in BUG-210,
one layer down.

Corollary for units specifically: **a missing unit is safe, a wrong one is not.** Once the QUDT
IRI landed the model stopped inventing "psi" and said "the exact unit isn't specified" — still
incomplete, no longer wrong. Prefer the shape that degrades to silence.

## 60. A lane nothing routes to is not "working" — it is untested in production (2026-08-24)

The V5-T20 diagnosis lane held two defects that had never once been seen:

* `resolve_referent` stripped `.` from the QUESTION token (`5.01` → `501`) but not from the LABEL
  it compared against (`Room 5.01`). That comparison could never succeed for **any** label
  spelling, so every room-scoped why-question silently fell through to a whole-building average —
  a wrong-scope answer that reads exactly like a right one.
* The same explanation was listed as reasons 1, 2, 3 **and** 4 (one per overlapping episode).
  Repetition reads as corroboration; it was one fact four times.

Neither had ever fired, because **nothing reached the lane**: the pre-LLM capability probe
answered why-questions from documents in 1.3 s, and anything surviving that was converted to
`sensor_data` by a concept-stage rule. Fixing the routing exposed both instantly.

When wiring feature X into lane Y, **first prove a real question reaches lane Y**. I wired plant
state into diagnosis, unit-tested it, and only afterwards discovered the lane was unreachable —
the tests passed the whole time. Same family as the reachability lesson (#38) but the inverse
direction: there the wiring was absent, here the *traffic* was.

## 61. The honesty mechanism can destroy an honest answer (2026-08-24)

The numeric guard suppressed **"I have no co2 readings for Room 5.01"** — a correct, useful,
maximally honest sentence — and replaced it with "a number in the text could not be traced back
to the underlying data". The unbacked "number" was `5.01`: the room's NAME.

Third instance of *identifier judged as measurement* (BUG-242: report id `REP-571188`; BUG-191:
the `2` inside `bldg2`). The guard compares prose numbers against the payload's own fields, and
the early-return no-data payload carried only `success` + `formatted_response` — the success path
already carried `referent`.

**A guard's failure path needs the same evidence its success path carries.** When adding an early
return, copy the identifying fields, not just the message. And when a guard fires, check whether
the "number" is an identifier before assuming the narration is at fault.

## 62. `getattr(obj, "method", None)` makes an interface optional by accident (2026-08-24)

`fetch_series` resolves its query builder with `getattr(adapter, "build_timeseries_query", None)`
and skips a missing one with a log line. Every adapter implemented it **except the wide MySQL
one** — so the entire deliberative stack (diagnosis, ranking, prediction) read **zero rows** for
every sensor whose `ref:storedAt` points at a wide table. On a retrofitted building that is all
of the physically-installed hardware.

It surfaced as *"I have no temperature readings for Room X over the last 24 hours"* about a
sensor holding **581,572 values current to that minute** — a sentence indistinguishable from the
truth about an uninstrumented room.

Why it survived: the narrow adapter DID implement it, and the narrow stores hold the **synthetic**
data the tests use. The feature worked for everything demonstrated and failed for the real data.

**When an interface is optional-by-getattr, assert the implementers.** A one-line test —
"every registered adapter type exposes `build_timeseries_query`" — would have caught this the day
the deliberative stack was written.

## 63. My own degrade-to-a-legal-value bug, in the module I wrote to prevent them (2026-08-24)

`plant_state.for_space` was written against `run_sparql_select` → `{"ok", "rows"}` and
unit-tested against it. The diagnosis lane passes `sparql_exec` → raw SPARQL-JSON. The call
raised inside a broad `except` I had added *to protect the answer*, and the caller got an empty
context that rendered as:

> "No equipment is declared as serving this space, so plant state cannot be consulted."

Fluent, plausible, and **false** — about a room served by an AHU and a VAV with seven connected
points. Every test passed the whole time, including the ones I wrote specifically about honest
absence.

Two rules earned:

* **A broad `except` around a wiring call converts a bug into a confident false statement.** It
  cannot tell "this building has no plant" from "I called you wrongly". If the honest-absence
  message is reachable from an exception handler, the handler must say *which* it is.
* **When two conventions for the same thing exist in one codebase, anything touching them must be
  tested against BOTH.** Two SPARQL executor shapes are live here. I tested one.

Sibling of #59 (a triple in a convention nothing reads) at the function-call layer: same defect,
different interface.

## 64. Correct the record when the diagnosis was wrong, not just the code (2026-08-24)

I logged BUG-255 as "the schema picks a stale sensor when a fresh one exists", citing a room's
CO2. Investigation showed the fresh sensor is **deliberately excluded** from that modality by
`label_excludes` because it reports an index rather than ppm — an owner-confirmed split
(CAVEAT-207) that exists to stop exactly the kind of nonsense mixing the two scales produces. The
"no readings" answer I set out to fix was **honest and correct**.

The real blockers were two different defects (#62 above, and a zone-nesting direction). Both were
found only because the first hypothesis was tested rather than assumed.

The tracker row was **corrected in place** rather than quietly closed: a fix log whose entries
record the wrong cause is worse than no log, because the next person searches it and believes it.
State what was originally claimed, what was actually true, and why the difference matters.

## 65. A caveat an LLM may reword is a caveat that can vanish (2026-08-24, V6-T27)

The meter-boundary line was appended to the answer *before* the persona formatter. The code ran,
the line was produced, no error was raised — and the formatter rewrote the prose without it. The
caveat was a **suggestion to the model**, not a guarantee to the reader.

Moving the append after the last generative step fixed it. The general rule:

> Anything whose exact wording carries a guarantee — a boundary, a refusal, a provenance note, a
> "this is an estimate" — belongs AFTER the final LLM pass. Anything the model is free to
> paraphrase belongs before it.

This is the mirror of #63: there a broad `except` turned a bug into a confident false statement;
here a generative step turned a true statement into no statement at all. Both are silent, and
both look fine from outside.

## 66. Placement is not boundary (2026-08-24, V6-T27)

`brick:hasLocation` and `brick:isPartOf` say where a meter **sits**. Neither says what it
**measures**, and this building proves the gap: `Building_Water_Meter brick:isPartOf Floor0` — a
whole-site water meter installed on the ground floor. Read as a metering boundary, the site's
water total would be published as floor 0's consumption, with a real number attached.

The first version of the topology provisioner made exactly that mistake and reported **34 of 34
meters resolved, 0 undeclared** — a 100% success rate that should have been the tell. Nothing in
this estate is 100% declared.

Three rules came out of it, each generalisable beyond meters:

1. **Rank a vocabulary declaration above an instance inference.** `brick:Building_Water_Meter` is
   a statement in the shared ontology that this meter's scope is the building — stronger than any
   guess from where the hardware is, and it CONTRADICTS the placement here, which is the point.
2. **Carry the provenance into the answer.** A boundary derived from placement is written with
   `boundarySource "placement"` and says so in the sentence: *"inferred from where the meter sits,
   not a declared metering boundary"*. Presenting a proposal and a declaration identically is how
   a guess acquires the authority of a fact.
3. **Write nothing when nothing settles it.** An absent boundary makes the answer say "not
   declared", which is true. A guessed one makes it state a scope it does not have.

## 67. A refusal must say what CAN be measured, not only what cannot (2026-08-24)

"How much energy did I use this month?" was answered **22.06 kWh** — the sum of six floor meters
presented as one person's consumption. "Which employee uses the most electricity?" answered
"Energy Meter Floor4", substituting a meter for a person.

The refusal that replaced them explains the *physics*, not just the policy: a meter measures a
boundary, so no reading belongs to one person, and splitting a shared total by headcount would
invent a number rather than measure one — then it names the questions that ARE answerable.

The guard that mattered most was the one preventing over-refusal: **per-capita is an aggregate.**
"Energy per capita" divides a total by a headcount and identifies nobody. Refusing it would deny a
standard sustainability metric while protecting no one — the cost of a lazy pattern is paid by
every legitimate question it swallows.

## 68. Two dormant defects in series look exactly like one working feature (2026-08-25, V6-T07)

`history.py` computed effective-dated locations correctly and did nothing, behind **two**
independent gaps:

1. Nothing wrote the `_config_periods` bus key that `assemble._configuration_periods` reads.
2. That reader constructed `ConfigurationPeriod(subject=...)` against a dataclass with **no
   `subject` field** — a `TypeError` its own broad `except` would have swallowed.

Either alone was enough to make the feature inert. Together they were worse than that: gap 2 was
**undetectable** while gap 1 existed, because the constructor could never be reached. Anyone
fixing gap 1 in isolation would have seen no change and concluded their fix had failed.

**When wiring a dormant feature, drive the whole path with real data before believing either
half.** A unit test on the producer and a unit test on the consumer can both pass while the
join between them has never executed once.

## 69. The measurement apparatus was wrong for the fifth time (2026-08-25)

The regression gate compared a baseline with 15 timeouts against a run with 14 and returned
**FAIL — 10 blocking findings**, on a run that answered one question *more* than its baseline
(302 OK vs 301). The ten "dropped" and eleven "added" rows were two halves of the same
background flakiness.

Root cause: both sides were filtered to `status == OK`, and OK-then-not-OK was classed as
`DROPPED`, which blocks. But a **TIMEOUT is not a dropped answer** — the request never
completed. At a ~5% background timeout rate, that gate fails essentially every run, and a gate
that always fails is a gate nobody reads.

The fix keeps the real signal rather than deleting it: transport failures quarantine the row on
either side, the per-run failure *rate* is printed in the report, and it blocks only on a
material worsening. **The stack degrading is a finding — just a different finding from a
behavioural regression, and conflating them destroys both.**

Fifth apparatus defect after BUG-176/177, BUG-219, BUG-238/239. The pattern is stable enough to
state as a rule: **when a verdict surprises you, audit the instrument before the system.**

## 70. A plausible-sounding diagnosis of nothing is worse than no diagnosis (2026-08-25)

The plant lane's leading explanation for a warm room was:

> "AHU_F5's supply fan ran for only 39.6% of the window — the space was barely being ventilated"

39.6% of 24 hours is roughly one working day. The system had diagnosed a **normal schedule** —
fluent, specific, numerically exact, and about nothing. Worse than silence, because a confident
explanation stops the search.

The signal that means something is **coincidence, not runtime**: the fan off *while the room was
above its own average for the window*. Overnight downtime never triggers it, because the room is
not elevated then.

Generalisation worth keeping: **a threshold on a quantity that varies for innocent reasons is not
a finding.** Before raising anything as a cause, ask what the NORMAL case scores. If normal
operation trips it, the rule measures the schedule rather than the fault.

## 71. Two steps to add an intent, three to deliver one (2026-08-25)

`.claude/rules/agent-patterns.md` says adding an intent is two steps: the YAML entry and the node
method. That is true for **routing** and not for **delivery** — a standalone lane must also be
collected by the response node's dispatch.

The observability lane routed correctly, ran, computed the right answer, wrote it to
`observability_result`, and every question returned *"I processed your request, but couldn't
generate a response."* Its own tests passed; the node was fine; nothing collected the result.

Same shape as every wiring gap this workstream has found — the half nobody demonstrates. The
checklist in that rules file should say three steps, and a new lane's first live probe should be
treated as part of the implementation rather than as confirmation of it.

## 72. The repair tool had the defect it was written to repair (2026-08-25)

`refresh_narrow_table.py` exists because a table stopped writing while its neighbours kept going
(CAVEAT-207). Its own docstring promises that "each series continues from that sensor's own last
value". It did not. It read the table's **global** `MAX(datetime)` and topped up only the uuids
that wrote at that exact timestamp — so **one** still-reporting sensor made the whole table look
current and hid every other one.

Measured on this building after running the tool and believing it:

| store | sensors fresh in 24h |
|---|---|
| noise_data | **1 of 236** |
| light_data | **1 of 242** |
| temperature_data | **1 of 67** |
| occupancy_data | 6 of 280 |

The visible consequence was three lanes away: "find me a quiet room" answered *"I couldn't rank
any spaces for this request — 51 spaces were excluded"*, because the deliberate lane correctly
refused to rank on stale noise. Nothing anywhere connected the two.

This is **CAVEAT-233's exact lesson — per uuid, never per table — inside the tool written to
clean up after it.** Knowing a rule and encoding it in the one place it matters are different
acts. When a tool aggregates over a population, check whether the aggregate can be satisfied by
a single member.

## 73. My own verification command reported success regardless (2026-08-25)

I had been running:

```bash
flake8 ... --select=F821,F823 | tail -3; echo "GATE=$?"
```

`$?` there is the exit status of **`tail`**, not of flake8 — so it printed `GATE=0` whatever
flake8 found. It printed `GATE=0` on the very run where flake8 reported `F821 undefined name
'datetime'` in code I had just written, and I only noticed because the error text scrolled past
above the reassuring `GATE=0`.

That undefined name would have raised inside a `try/except` and produced **no recheck line at
all** — silent, and indistinguishable from "this answer has no advice to give".

Sixth measurement-apparatus failure in this project, and the first one that was mine in the
shell rather than in the code. **A pipeline's exit status is the last command's.** Check the
thing you mean to check, and prefer letting the tool's own non-zero exit fail the command over
formatting a status by hand.

## 74. Wiring a module is the moment its assumptions get tested (2026-08-25)

Two modules were wired into live lanes tonight, and both immediately exposed a defect that no
unit test could have found — in the code they were being wired *into*:

* the matched comparison (T41) revealed that `_series_for` widens its window to reach back seven
  days and then fetched with a 500-row cap, which at ten-minute cadence covers 83 hours. The
  fetch had always succeeded; the rows were simply the wrong ones, so the "same window a week
  earlier" line had never once appeared for a fine-cadence sensor.
* the recheck advice (T37) revealed that the dossier carries no evidence timestamp at all —
  the recommendation lane genuinely could not say when its readings were taken.

Neither module was wrong. Both were correct against inputs the pipeline could not actually
supply. **A module's unit tests describe what it does with the data it is given; only wiring it
tells you what data exists.** Budget for the wiring finding a bug elsewhere, and treat the first
live probe as part of building the feature rather than as a formality after it.

## 75. A Brick class is not a population, and this building proves it four ways (2026-08-25)

Three separate P1s tonight were one mistake wearing different clothes: **code that identified a
set of sensors by their Brick class, on a building where the class holds more than one quantity.**

* `brick:Particulate_Matter_Sensor` is the parent of PM1, PM2.5 and PM10 — and here the TVOC
  sensors carry it too. The coverage audit answered a PM2.5 question with a **PM10** reading.
* `brick:Occupancy_Count_Sensor` covers entry counters and parking bays, so the absence guard
  announced "this building **does** have 257 parking_free sensor(s)" — in a sentence beginning
  *"To be accurate about one thing"*. There is one.
* The same class ambiguity is why parking still cannot return a number: the concept resolves to a
  class holding 257 sensors and nothing can narrow it.

The config had the right primitive all along (`label_contains` / `label_excludes`, added for
CAVEAT-207). What kept failing was **every new consumer reading only the class half** —
`modality_classes()` existed and returned classes; no one had written the function that returns
the other half, so three call sites independently did the wrong thing while looking correct.

**When an identity has two parts, never expose an accessor for one of them.** The fix was to add
`modality_label_filters()` next to `modality_classes()` — after which the wrong call site is the
one that *looks* incomplete.

And the corollary, twice tonight: a discriminator that matches nothing is worse than one that
errors. `label_excludes: [pm1_]` was inert because the matcher read `label OR local name` and
every sensor had a label, so the IRI form was never seen. It sat in config looking enforced.
**A rule that silently does nothing is invisible; make the matcher see every form a rule can be
written in.**

## 76. Measure the thing you blamed before you fix it (2026-08-25)

Parking questions were timing out at 120s. The store had **19.2M explicit triples** and a 13.4×
blank-node duplication — an obvious culprit, and I was one step from a destructive cleanup of the
user's live graph to "fix performance".

Then I timed an actual query: the class-scoped lookup that answers the question returns in
**0.06s** against that same bloated store. The timeout was an unbounded `?s ?p ?o` scan in the
SPARQL fallback — 29.98s per attempt, three attempts. Bounding the scan fixed it: **0.61s, 49×**.
The bloat is real and worth cleaning, but it was **not the cause**, and cleaning it would have
"fixed" the timeout by coincidence while leaving the unbounded scan waiting for the next store.

The seductive part was that the wrong theory *explained the symptom* — a huge store does make
scans slow. **A hypothesis that explains the symptom is not evidence; the measurement is.** One
timing run separated them, and it cost less than the cleanup would have.

## 77. The capability existed, the data did not, and honest declines hid it (2026-08-25)

The whole institutional half of the question bank — bookings, work orders, footfall — was
unanswerable on this building. Not because anything was unimplemented: `synthetic_events.py`
generates all three event types, `backfill_events.py` was written to seed them, and the events
lane, the adapter and the query service all worked. **Nobody had ever run the seeder.** The
store held 14,200 anomaly episodes and zero bookings.

What made it invisible is the thing this project is proudest of. An empty event type produces an
honest decline, and an honest decline is indistinguishable from a building that genuinely has no
bookings. The system was behaving *correctly* the entire time, which is exactly why nobody looked.

**A capability is not delivered until its data is loaded on the building you are demonstrating.**
When a whole question family only ever declines, check the store before checking the code — and
add a coverage probe that distinguishes "this building has none" from "nobody loaded any",
because the answer text cannot.

## 78. The guard was right and the answer was thin (2026-08-25)

"How many room bookings are there today?" returned the suppression text: the numeric guard had
found thirteen figures in the narration it could not trace. My first instinct was that the guard
was over-firing on clock times — it decomposes "09:30" into `09` and `30`, and `30` is not
obviously backed — and I got as far as designing an exemption for minute components.

Then I read the branch. `bookings_list` **prints** up to ten booking time-ranges and attendee
counts, and **returns** only `{room, window, count}`. The numbers were real; the payload just did
not carry them. Its sibling branch, `availability_check`, had done this correctly all along by
returning its `clashes`.

Exempting clock minutes would have "fixed" the symptom and blinded the guard to invented times in
every lane, permanently, to spare one branch a one-line change.

**When a guard fires on a correct answer, the first hypothesis is that the answer under-reports
its evidence — not that the guard is too strict.** The guard's whole value is that it cannot be
argued with; every exemption is a permanent hole bought to avoid a local fix.

## 79. Unit tests prove a component works; only wiring proves it runs (2026-08-25)

V6-T25 delivered the institutional-source adapter — parser, strict space resolution, ingest
report, its own test file, all correct. It was marked done. Connecting a timetable to it today
found, in order:

* **Nothing called it.** `read()` had no caller outside its own tests. The polling loop cannot
  invoke it (these are one-shot file reads, not pollers) and no other entry point existed.
* **Declaring it broke everything else.** The registry *maps* the adapter, so `run_forever`
  called `poll_safe()` on a class that has none, the AttributeError escaped the loop, the task
  died — and the building's weather feeds stopped with it. One misdeclared source, blast radius
  of every feed.
* **Its ids did not fit the table.** `event_id` is `CHAR(36)`; the adapter minted a readable
  42-character string. MySQL truncated it, distinct sessions collapsed onto one primary key, and
  `INSERT IGNORE` dropped 234 of 675 records without raising anything.
* **Nothing could route to it.** The answer vocabulary had no word for "timetable".

Its own docstring says it is *"deliberately shaped like the other feed adapters so the registry
dispatches it identically"*. It is not a `FeedAdapter`, has no `poll()`, and the registry cannot
dispatch it. **A docstring is a claim, and an unwired component is where claims go unchallenged.**

The pattern to take away: a component is not done when its tests pass. It is done when something
in the running system calls it, with real data, and you have watched the result. Everything above
was invisible for weeks and took one afternoon of wiring to surface.

## 80. Ask the ontology, not the name (2026-08-25)

The first timetable generator picked teaching rooms by sampling every `brick:Location` subclass,
and scheduled "Advanced Systems Architecture" into `FireExit_F1_North`.

The tempting fix is a name filter — skip anything containing "FireExit", "Corridor", "Stair".
That works on this building and needs rewriting for the next one, which is the definition of the
thing this project forbids.

The right fix was already in the graph: Brick distinguishes `Classroom`, `Lecture_Hall`,
`Conference_Room` and `Laboratory` from plain `Space`, and the fire exit is typed `Space`. Asking
the ontology gave a correct answer on this building and a correct answer on any building, with no
vocabulary of mine in it.

It also surfaced something a name filter never would: one room carries `Common_Space` **without**
`brick:Room`, so the coverage audit cannot see it at all. **Choosing by class does not just avoid
a heuristic — it makes the ontology's own inconsistencies visible.**

## 81. A rule in the contract is not a rule in the path (2026-08-25)

The new `asset_state_query` rule was correct in isolation — six of six questions routed to
the lane — and did absolutely nothing live. Same query, same rule, opposite outcome.

The cause was one log line: `[ttl-route] capability via document KB — skipping LLM intent call`.
The capability probe claims a question **before** the LLM runs, and that path never executes the
parse stage. So no parse-stage rule can reach any question the probe claims, at any position in
the order. The rule was registered, pinned in the precedence test, and unreachable.

This is the eighth member of BUG-231's family, and the pattern is now unmistakable: **the
short-circuit bypass list is the real precedence contract for anything the capability probe can
claim.** Adding a lane means adding it in two places, and the routing contract's own
documentation — which presents itself as the single ordered home for every override — does not
say so.

The general lesson is about *where* a correct-looking unit test can lie: it exercised
`apply_contract` directly, which is a path production sometimes does not take. **Test the rule,
then watch the question.**

## 82. Provisioning data is not delivering a capability (2026-08-25)

`ontosage:AssetStatus` triples had been written for weeks — 21 of them, each with a value, an
observation time and an assistance contact. `grep -rn AssetStatus orchestrator/` returned
nothing. Not one line of the answering system had ever referred to them.

So "are the lifts working?" answered *"this building does not have lift sensors"* — a sentence
that is both false and, from the system's own point of view, unfalsifiable: no code path existed
that could have discovered otherwise.

This is the third distinct form of the same failure found in two days:

1. a sensor described in the ontology and backed by no database (contract 8's classic case),
2. a file declared in config that nothing ingests (BUG-296),
3. **data in the graph that nothing queries** (this one).

All three look identical from the outside — an honest decline — and all three are invisible to
tests that only exercise the producing side. The check that would have caught every one of them
is the same: **for each kind of data this system stores, name the query that reads it back.** If
there isn't one, the data is decoration.

## 83. Measure the building before building the feature for it (2026-08-26)

The task was "a lift outage must invalidate dependent step-free routes". The obvious plan is
to write the exclusion, wire it up, and demonstrate it on the live building.

Measuring first changed the plan. The route graph has **344 nodes across six floors and zero
typed as lift or staircase** — twelve space types, none of them vertical circulation. Only 4
cross-floor edges exist in the whole building, and floor 0 to floor 3 returns no route at all,
with or without the step-free requirement. The graph knows about a lift and two staircases; the
floor plans do not.

So the feature is correct, necessary, and **undemonstrable on this building**. Two temptations
follow, both wrong:

* *Synthesise the lift shafts.* Floor-plan geometry is one of the few things here measured from
  real DWG. Inventing a shaft position to make a demo work would be fabricating spatial data —
  precisely what the rest of the system refuses to do.
* *Quietly skip it and call the criterion met.* The code would be untested and the claim false.

What I did instead: implement it, pin it on a fixture that states in its own docstring why a
fixture was necessary, and log the data gap with the numbers. **A feature that cannot be
demonstrated on the live building is a finding about the building, and it belongs in the tracker
rather than being smoothed over in either direction.**

## 84. Threading beats promoting when the callers are synchronous (2026-08-26)

The availability lookup is async; the wayfinding method that needed it is not. The reflex is to
make the method `async` and await it — three signatures, done.

Checking the callers first showed the cost: tests call `_answer` and `_answer_wayfinding`
directly and synchronously, and promoting them would have broken those tests, which would then
have been "fixed" by adding `await` everywhere — churn in test files that exist to pin behaviour
I was not changing.

The alternative was to compute the value at the one point in the chain that is *already* async
and pass it down as an optional parameter defaulting to `None`. Every existing caller keeps
working untouched, and the sync methods stay sync.

**Before promoting a function to async, look at who calls it.** The async boundary usually
already exists somewhere above; passing a value down from it is smaller than dragging the
keyword down to it.

## 85. Find the writer before you clean the data (2026-08-26)

The graph held 20.3M triples for a building with ~11k IRI subjects, and the authorised task
was to clean it. The tempting first move is a `CLEAR DEFAULT`.

Measuring instead showed it was still **growing**: timeseries references had gone 38,449 →
55,706 for the same 2,872 UUIDs in one day, purely from development restarts. A cleanup would
have been undone within a week and I would have concluded the cleanup "didn't hold".

Following the growth found the writer in four steps — refs by named graph (only ~5,500 of
55,706 were in one), then which code POSTs to `/statements` without a context, then the
commented-out `X-GraphDB-Context` header, then the unconditional `create_task` at rag-service
startup. A second ingestion path over the same directory, append-only and unscoped.

**A cleanup is a treatment; the writer is the disease.** When something is too big, measure
whether it is still growing before deciding what to do about it — the answer changes the task
entirely, and the leak is nearly always cheaper to fix than the mess.

## 86. A safety check that cannot see inference is not a safety check (2026-08-26)

With the leak stopped, clearing the default graph looked safe: every legitimate file is
ingested into a named graph, so the unnamed one should be pure duplication.

The check I ran was `brick:Room` anywhere versus inside `GRAPH ?g {}`. It came back **233 and
0**. Read one way that means every room typing would be destroyed by a clear; read another it
means the typings are inferred, and GraphDB does not attribute inferred triples to any named
graph, so the query cannot see them either way.

Both readings fit the number. **The measurement could not distinguish "safe" from
"catastrophic", and I could not tell which by looking harder at it.** So I did not run the
delete — an authorisation to clean is not an authorisation to run an operation whose blast
radius is unknown, and the urgency had already gone once the leak was fixed.

The safe route is a rebuild-and-compare rather than a clear: drop, re-ingest deterministically,
verify entity counts against the pre-drop numbers. Slower, and it fails loudly instead of
silently.

## 87. Four capabilities in one day that nothing called (2026-08-26)

Today's tally of code that existed, was correct, and had no invoker:

1. the institutional feed adapter — a declared timetable could never be read,
2. `ontosage:AssetStatus` triples — "are the lifts working?" said the building has no lifts,
3. `ontosage:ServiceSchedule` triples — cleaning schedules unreadable,
4. `link_to_work_order()` — the two ticket universes can never join.

Every one presents identically from outside: an honest decline. Every one passes its own unit
tests. Every one was marked done.

The check that finds them takes seconds: **for each kind of data this system stores, grep for
the code that reads it back.** `grep -rn AssetStatus orchestrator/` returning nothing is the
whole diagnosis. Worth running across the remaining stores rather than waiting to trip over
number five.

## 88. I verified a fix three times that had never once run (2026-08-26)

The most-specific-class check asked the graph which candidate was a subclass of the other. It
never worked. `_execute_query` raised `[Errno -2] Name or service not known` from a Fuseki
fallback path, the `except` logged at DEBUG — below the running level — and the function
returned `candidates[0]`.

That default is what made it invisible. Roughly half the time `candidates[0]` **is** the right
answer, so the function looked correct whenever the set happened to iterate that way. I checked
it three times. Twice it agreed with me for the wrong reason.

What finally exposed it was adding a log line *after* the call and seeing it never print, while
the log line after the function's return printed every time. **An exception handler that logs
below the running level converts total failure into a plausible default**, and a plausible
default is much harder to spot than a crash.

The fix was not to make the query work. It was to remove the need for it: an `ontosage:` class
exists precisely because Brick lacked one and is declared a subclass of the nearest Brick
parent, so the choice can be made from the CURIE alone. A pure function has no fallback path to
hide in.

## 89. One shortener, two vocabularies (2026-08-26)

`_brick_local` turns a class IRI into a CURIE. It handled `brickschema.org` and returned
everything else unchanged — written when Brick was the only vocabulary, and never revisited when
the project deliberately added its own.

So an OCBV class arrived downstream as a bare `http://ontosage.org/capabilities#...`, and two
separate things broke without a word: a prefix check that could never match it, and — had it
been selected — a generated SPARQL query in which a bare IRI is a syntax error, because an IRI
needs angle brackets where a CURIE does not.

Combined with a missing prefix declaration in the query agent, the effect was that **the entire
conversational vocabulary this project invented was unreachable from the query lane**, and had
been for as long as it existed. The symptom was one wrong number: 294 free parking spaces, which
is the building's room count.

**When a codebase grows a second vocabulary, grep for every place that special-cases the first.**
A function named for one of them — `_brick_local` — is a good place to start looking.

## 90. The audit found a fifth one in about ninety seconds (2026-08-26)

Lesson #87 proposed a check: for each kind of data this system stores, grep for the code that
reads it back. Running it took one command — extract every `ontosage:` term the schema declares
(213 of them), grep each against `orchestrator/` and `scripts/`.

Most unread terms are legitimately declarative: `Intent_*`, `Role_*`, `Src_*` are annotation
vocabulary, and `*Shape` are SHACL. The signal is in terms that represent *answerable data*, and
there the audit found **Module P — "Amenity service status and potability", marked done, with
all six of its terms unread and the word "potability" appearing nowhere in the codebase.**

Two corrections the audit itself needed, both worth noting because they show how to read its
output:

* `ServedZone` looked unread by class name but two of its four properties *are* read. A class
  name absent from code proves nothing on its own — check the properties.
* `PotabilityStatement` is deliberately a subclass of `KnowledgeTopic` **so the existing
  capability resolver answers it with no new code**. That half was a data gap, not a code gap.
  The schema said so; I had to read it to find out.

What survived both corrections was the real defect: `amenityStatus` had no reader, so an
out-of-service drinking fountain was recommended exactly as though it worked — and the schema
had written down, a year earlier, precisely why that is a wrong answer rather than a missing one.

**The cheapest audit in this codebase is "who reads this?", and it keeps paying.** Worth running
against the SQL tables and the Postgres columns next.

## 91. Read the schema before believing the grep (2026-08-26)

The audit reported six unread terms in one module and I was ready to call the whole module dead.
The module's own comment block explained that one of those terms is unread *by design*: a
`PotabilityStatement` is a `KnowledgeTopic` subclass precisely so the existing resolver picks it
up through inference, with no code naming it anywhere.

So half the finding was real (nothing filters amenities by status — a wrong answer) and half was
me not reading the design (potability needs instances, not code).

**A well-commented schema is evidence, and in this repo it is often better evidence than the
code.** When a static check says something is dead, the design document that introduced it is
the first place to check whether "dead" means "unfinished" or "working exactly as intended".

## 92. The reader audit generalises to every store, and the sixth was in Postgres (2026-08-27)

#90 ended with a note: *worth running against the SQL tables and the Postgres columns next.*
Doing it took an afternoon and found `actuation_log` — a row written on every approved setpoint
change since T23, on a building that ships with actuation enabled and three writable points,
and not one `SELECT` against it anywhere in the repository. The accountability record for a
system that changes setpoints was write-only. Sixth instance of the pattern.

The general form is worth stating, because it is not about RDF:

> For every kind of data this system stores, find the code that reads it back. If there is
> none, the feature is externally identical to not having been built.

Two things made the mechanised version usable rather than noisy:

**Grade the confidence instead of overstating it.** The first run reported the seven narrow
modality tables as unread — the tables that serve *every sensor question in the system* — because
they are reached through `f"{modality}_data"` and have no literal `FROM` to find. A report that
confidently names the busiest tables in the building as orphaned is a report nobody will read
twice. Splitting the finding into "named nowhere else" (strong) and "no literal read but named
in these files" (weak, with the files listed) took the output from fifteen hits to one real one.

**Say what the scan cannot see.** 54 files build table names at runtime. Listing them as the
blind spot is what makes the rest of the output trustworthy — same reason the multi-model
benchmark now prints `_not run_` instead of `0 / 0` (#lessons on measurement apparatus).

And the detector confirmed its own fix: after `audit_log.py` landed, `actuation_log` dropped off
the list because something now reads it. A test plants the defect in a fixture rather than
asserting the current tree is clean, so the check fails when it should.

## 93. An artefact with no producer drifts, and nothing compares them (2026-09-06)

Two of the day's three worst defects were the same shape, and neither was a code bug.

`bldg1_synthetic_amenity_state.ttl` was the OLD generator's output. The amenity set it
statused had since been replaced wholesale, so 13 of the building's 64 asset statuses named
IRIs with zero triples -- the reception, the cafe, the makerspace, the prayer room, the
showers -- and every one answered *"not recorded in this building's model"*. The generator
had been fixed months earlier; the file had never been re-run.

`bldg1_extended_narrow_uuids.json` had **no generator at all**. It was written once, by
hand, and typed 174 CO2 sensors by a Brick SUPERTYPE (`Air_Quality_Sensor`, which covers
CO2, TVOC and particulates alike) with a 0-150 air-quality-index range. Seven weeks of
floor 0-4 CO2 data was an index labelled ppm, and the building answered a comparison with
"157 ppm vs 111 ppm" -- outdoor air is 420 -- and recommended an HVAC upgrade.

The rule: **a derived file needs a generator, and something must compare the two.** Not a
comment saying "regenerate after changing X"; a `--check` mode that exits non-zero, or a
test that reads the artefact and the source and asserts they agree. Both defects are now
caught by an offline test that would have failed on the pre-fix tree.

The corollary is the one that keeps costing this project: the generator's fix and the
artefact's regeneration are two events, and only the first leaves a diff.

## 94. Two bands, and confusing them is the whole failure (2026-09-06)

Adding plausibility checking looked like one decision and was two.

**Possibility**: what a reading CAN be. 350-40,000 ppm of CO2. A value outside it is not a
measurement -- almost always the stream is carrying a different quantity's scale.

**Comfort**: what a reading SHOULD be. ASHRAE 62.1's 420-1,500 ppm.

A guard built on the second would delete the 2,400 ppm reading that means a room needs
ventilating now. It would suppress exactly the readings a building most needs to report,
which is a worse failure than the one it prevents. The bands are now separate properties in
`measurand_kinds.ttl` with separate names and separate justifications, and a test asserts
the generation band sits inside the possibility band.

The same split appeared again immediately, in the generator: `typicalMin/Max` says what to
GENERATE and `physicalMin/Max` says what to ACCEPT. One number could not serve both, and
the original defect was precisely that two hand-written tables tried.

## 95. The fifth time a fix nearly broke the apparatus measuring it (2026-09-06)

`purge_implausible_readings.py`, as first written, deleted every row outside its quantity's
physical band. `grade_anomalies.py inject` plants labelled faults by writing **777.7**
(stuck), **99999** (spike) and **value+500** (drift) -- precisely because they are
implausible. Run as written, the purge would have deleted the faults, left the labels, and
reported every detector as having missed everything. 7,590 rows across five tables.

The fix is a rule worth generalising: **a band tells you a value is not a measurement; it
does not tell you whether that is a scale error or an event, and only the first is safe to
delete.** So the criterion is a SHARE, per stream. Nearly all out of band means the
instrument never measured that quantity on that scale. A minority out of band means events.

And the threshold has to be **per stream, not per quantity**. On the group it read 72.8%
for six CO2 sensors and touched nothing; per sensor, four were 96.9% (a clean scale error)
and two were 39.5% (wrong until a date). One average, two entirely different situations,
and the group figure described neither.

## 96. Three vocabularies for one relation, and 106 sensors that did not exist (2026-09-06)

A join that should have returned 628 sensors returned 522, and the missing 106 looked like
orphan references with no sensor attached. They were not orphans. The sensor-to-timeseries
link is written three ways in this graph:

    s223:hasExternalReference    2,763 sensors    <- the superset
    ref:hasExternalReference     2,727 sensors    <- what the code queries, 43 times
    brick:hasExternalReference       2 sensors

Design contract 8 broken in the subtlest available way: both halves present -- the sensor in
the graph, its rows in a registered database -- and the join written in a vocabulary the
reader does not speak. Nothing errors. The sensors simply do not exist as far as most of the
system is concerned.

The fix ASSERTS the canonical predicate rather than teaching 43 query sites an alternation,
because both vocabularies are legitimate and 2,727 references already carry both. Teaching
the readers would leave the 44th, written next month, wrong again. Normalise the data to the
rule; do not widen the rule to the data.

## 97. Declaring one thing properly exposes what was never declared at all (2026-09-06)

Adding measurand declarations for 52 sensor classes did not just fix the CO2 range. It made
an existing validator -- written for CAVEAT-286, and passing ever since -- start finding
things:

* six occupancy points typed as BOTH `Occupancy_Count_Sensor` and `Occupancy_Sensor`, which
  in Brick 1.4 are siblings, not a class and its subclass: presence and a count, so either
  question could be answered with the other's reading;
* four colour-temperature points generating 18-28 because they had been given the air
  temperature band -- correlated colour temperature is measured in KELVIN, so a lighting
  question would have answered "22 K", three degrees above absolute zero;
* smoke and leak detectors, binary devices, generating 0-100.

The validator was right the whole time and had nothing to reason with. **A check is only as
good as the declarations it can consult, and a passing check over an empty vocabulary is
indistinguishable from a passing check over a correct one.**

## 98. A vocabulary is not a literal, and the guard cannot see the difference (2026-09-07)

`check_building_literals.py` reported clean while the routing layer carried:

    _ROOM_ID_RE   = r"\b(room|rm)[_\s]?\d+(\.\d+)?\b"
    _ZONE_ID_RE   = r"\bzone[_\s][\d]+\.[\d]+\b"

Neither contains a building name. Both encode ONE building's room grammar. A building
numbering rooms `RM-204` matches neither -- the hyphen alone defeats the first -- and the
symptom is not an error: the question fails a bypass check, takes another lane, and comes
back plausibly wrong.

**Two different problems wear the same label.** Literals are ordinary bugs: grep, delete,
done. Vocabulary has to be DERIVED from the active building, and deleting it outright makes
things worse -- "temperature" and "last week" are domain English, and a building whose graph
is still loading would lose the ability to recognise a trend question at all. The lexicon
augments; the constants stay as the floor.

## 99. Learning a convention: the description is not the identifier (2026-09-07)

Generalising this building's space names produced TWENTY distinct shapes:

    \d+\.\d+                                    (235)
    \d+\.\d+ - [A-Za-z]+ [A-Za-z]+              (194)
    \d+\.\d+ - [A-Za-z]+ [A-Za-z]+ [A-Za-z]+    (6)
    ...

Twenty shapes reads as "this building has no naming convention", which is the opposite of
the truth: it numbers every room `N.NN` and then appends a DESCRIPTION that varies. Stripping
the tail collapsed twenty to six.

**The lesson generalises past this module: when a learner reports that data has no pattern,
check what you fed it before believing the data.**

## 100. The guard against one false positive created a worse false negative (2026-09-07)

`Floor 4` generalises to `[A-Za-z]+ \d+`, which matches "over the last 7 days", "Windows 10"
and "COVID 19". Six floors would have made every sentence containing a word and a number
look like a room reference, so it had to be excluded.

The exclusion was "skip when stripping the type word leaves a bare number" -- and `rm` is a
type word, so `RM-204` left `204`, and the entire `RM-\d+` grammar silently lost its shape.
The one building this module exists to support was the one it stopped supporting.

The fix distinguishes a type word standing as its OWN WORD (`Floor 4`) from a glued prefix
(`RM-204`). Both cases are now fixtures, because each was found only by running the other.


## 101. Editing the code while measuring it invents fifteen failures (2026-09-12)

A full unit run came back **15 failed, 5691 passed**. Every one of them was a source-shape
test asserting on `inspect.getsource(SomeClass.some_method)` — and the source it got back
was a DIFFERENT method:

    assert "await self._gate_referent_once(state)" in src
    E  assert ... in '    async def _generate_title_bg(self, state) -> None:\n ...'

`inspect.getsource` locates a method by LINE NUMBER in the file on disk. The suite had
imported `_orchestrator.py` at collection; I then added ~40 lines to it while the run was in
flight. From that moment every method object in memory pointed at line offsets that no
longer meant anything, and the tests read whatever now sat there.

Nothing was broken. All 61 of those tests passed when run against a stable tree seconds
later. But for several minutes the honest-looking conclusion available to me was "my change
broke the referent gate, the document probe and the capability menu" — three unrelated
subsystems at once, which was the tell: **a change that appears to break three unrelated
things has usually broken the measurement, not the things.** (#20-22, again.)

Two rules from it:

* A long test run pins the tree. Do documentation, tracker and CSV work while it runs — not
  edits to anything under `orchestrator/`, `shared/` or `tests/`.
* `python -m pytest ... | tail -40` reports **tail's** exit code, not pytest's. Two runs this
  session were recorded as "exit code 0" while failing. Redirect to a file and echo `$?`
  separately, or read the summary line — never trust the pipeline's status.

## 102. A source-text guard that matches its own rationale (2026-09-12)

Three times in one session a guard asserting something about the source failed on PROSE
rather than code, and every time the prose was the comment explaining why the guard exists:

* `assert "str(e)" not in src` — caught `_safe_node`'s own comment saying *why* `str(e)`
  was wrong.
* `assert "prerequisite" in readme` — PASSED, on an unrelated feature table at line 1030,
  while the README had no prerequisites section at all. A guard passing for the wrong reason
  is worse than one failing for the wrong reason: nothing brings you back to look.
* `assert "retry" not in block` — caught the drift check's own comment, *"it reports and
  never retries"*.

The shape is specific and recurring: **the more carefully a piece of code explains itself,
the more likely a substring guard over its source will match the explanation.** Good
comments make these guards worse.

Three rules, in order of preference:

1. **Assert on structure, not text.** `ast.parse` and walk for a Call node. This is what
   the V12-08 formatter guard and the V12-15 shadowing audit ended up doing, and neither
   has a prose problem.
2. **Strip comments first** when a full parse is not available — the block being checked is
   often a fragment, not a statement.
3. **Assert the ASSIGNMENT, not the word**: `= str(e)` and `"error": str(e)` are code;
   `str(e)` is also English.

And the corollary that catches the second bullet: when a source guard PASSES, check it can
fail. A guard written against a tree that already satisfies it has never been observed doing
anything.

## 103. A session's timezone changed what the data "was" — and three fixes were built on it (2026-09-12 → 15)

On 2026-09-12 I moved three comparisons against stored rows from `utcnow()` to building-local
time, on the stated premise "the stores hold local stamps". On 2026-09-15 I measured again,
found the wide table "local" and the narrow tables "UTC", and logged a P1 about two clocks
in one database. **Both conclusions were wrong, for one reason.**

`sensor_data.Datetime` is a MySQL `TIMESTAMP`. MySQL stores it as UTC and **converts it into
the reading session's `time_zone` on the way out**. My measuring connection used the server's
SYSTEM zone (BST), so the wide table looked local. The orchestrator's adapters pin every
session to `+00:00` (BUG-403, fixed weeks earlier, with a comment saying exactly this). Read
that way, every table was UTC to within a minute.

What made it expensive: the first wrong premise produced three "fixes" and a test file that
asserted the wrong behaviour; the second produced a user decision (option a) about a problem
that did not exist. The code comment explaining BUG-403 was sitting in the publisher the whole
time.

Rules:
* **Measure a store the way the system reads it** — same driver, same session settings. For
  MySQL here that means `init_command="SET time_zone='+00:00'"`, not a bare connection.
* Before changing a clock, **grep for the prior decision** (`time_zone`, `utc`, `BUG-403`).
  A convention with a written reason is evidence, not an assumption to overwrite.
* A "fix" that contradicts an earlier documented fix needs its measurement repeated from a
  second angle before it lands.

## 104. An edit made during a live run reached the running container half-way (2026-09-15)

**What happened.** While the stakeholder re-ask ran against a restarted orchestrator, I added
a constant to `routing_contract.py` and an import of it to `event_query_service.py`. `/app` is
bind-mounted and the events service is imported LAZILY, on its first events turn. That turn
came after the edit, so the container loaded the NEW `event_query_service.py` against the
`routing_contract` it had imported at boot — without the constant. Every events question
answered "I couldn't read the events store just now", and the re-ask recorded two failures
that no deployed version of the code has.

**Rules.**
* uvicorn without `--reload` does not mean edits are invisible: **any module imported lazily
  after the edit is the new version**, alongside eagerly imported old ones. Lesson #101 (the
  pytest tree) applies to the live container too.
* Either edit nothing under `orchestrator/` or `shared/` while a live run measures the stack,
  or restart before the run and discard any turn that ran across an edit.
* When a live answer is "couldn't read … try again", read the traceback before counting it:
  `ImportError: cannot import name` against a file you just changed is this, not a bug.

## 105. A short-circuit placed before a contract skips the contract's first rules too (2026-09-15)

**What happened.** `dialogue_agent` claims a question for a held record class BEFORE the
LLM call and BEFORE the routing contract, to stop registers being swallowed by prose. The
contract deliberately runs its privacy rule FIRST. So "Can my manager see when I badge in and
out?" never reached the privacy rule: the access-permission register answered "Yes". The same
bypass sent "where's the coolest place to work?" to a register that records no temperature
(BUG-557); readiness questions had already needed their own exception (V12).

**Rules.**
* Every early exit in front of a rule set must re-apply that rule set's **precedence-critical**
  rules (privacy, control/safety, deliberation of measured conditions) — or be moved after it.
* When adding an exception to a short-circuit, look for the others it is missing: three of
  them were found by one stakeholder run, none by the suite.
* Unsafe defaults on side-effecting lanes are the same class of defect: a command with no
  target, an alert with no threshold and a report from a question each wrote something
  (BUG-548, BUG-552). A write path needs its inputs present, not defaulted.

## 106. 108 of 108 "OK" held two misrepresentations — the status code grades delivery, not truth (2026-09-15)

The 36-question demo script ran 3x through /v1 with no failure, timeout or decline marker. Reading
the answers against the source registers found: a work-order count that changed every run and once
declared all 9 "overdue" from a register holding no due date (BUG-581); an evacuation chair listed as
a defective refuge point; a "WHO threshold" and three different "standard comfort ranges" for one
question (BUG-582). The rows handed to the model were right every time.

**Rules.**
* A rehearsal result is graded by reading each answer against the store, and by comparing the
  runs with each other: the same question giving different facts is a failure even if every run
  "looks right".
* Counting, filtering by kind and date judgements over handed-over rows belong in code; the prompt
  gets the computed facts. An instruction ("never re-derive status from dates") is not enforcement.
* A narration prompt that asks "is this compliant with standards?" without supplying any standard
  asks the model to invent one.

## 107. Two scripted edits broke code the tests then had to catch (2026-09-15)

(1) Python source written through a Bash heredoc lost its escapes: `\n` inside string literals
became real newlines (a SyntaxError) and `\b` in a regex became a BACKSPACE character, so the
pattern silently matched nothing. (2) A module-level helper spliced in by string index landed
INSIDE `DialogueAgent`, after `rewrite_to_standalone`: every later method became unreachable
code nested in the helper, and `detect_intent` vanished from the class. The running container was
unaffected only because it had been restarted before the edit.

**Rules.**
* Write Python source with the Edit/Write tools, never via heredoc string literals; when a
  script must write code, build backslashes with `chr(92)` and scan for `chr(8)` afterwards.
* After any structural splice, import the module and assert the class still has its public
  methods, then run the WHOLE unit suite — a subset chosen by filename did not include the
  contract tests that noticed.

## 108. Three "wrong lane" answers were missing DATA, not broken routing (2026-09-16)

Stakeholder run #3 logged "answered from the wrong register" three times. Two of them had no
right register to reach: nothing recorded what a door does when power is lost, and the estate
carried zero water temperatures, so "which doors fail open?" and "what is the delta-T across
the heating circuit?" had nowhere correct to land. The lane the answer came from was the
symptom; the building's model was the cause. Adding the records and the points — one ontology
class with its lifting rules, one register document, eight generated points on plant the graph
already held — turned both into correct answers, and only then did a routing guard matter.

**And a subclass inherits a band that may be wrong for it.** A Leaving_Water_Temperature_Sensor
is a Temperature_Sensor, which declares the AIR band of -30..70 degC, so the first delta-T
answer announced 1,035 readings of an ordinary 72 degC heating flow as "physically impossible".
The loader had been SAMPLEing whichever declaring class the store returned first.

**Rules.**
* Before blaming routing for a wrong source, ask what the right source WOULD be and check the
  building holds it. If it does not, the fix is data, and the honest answer until then is "not
  recorded" — never a different register's rows.
* Where a property is declared up a class hierarchy, resolve it from the MOST SPECIFIC class
  that declares it, and never by sampling one of the matches.
* A generated pair that a question compares (flow and return, in and out) must come from one
  seed, or the difference between them is noise with a plausible shape.

## 109. A stray line truncated the defect log, because `open(path, "w")` runs before the failure (2026-09-16)

A tracker-writing script carried a leftover line — `csv.DictWriter(open(p, "w", ...)).writerows([])`
— which raised TypeError for a missing argument. The exception was irrelevant: `open(p, "w")`
had already emptied `tasks/FIX_TRACKER.csv`, 603 rows of defect history, before the call
failed. Recovery cost nothing only because the file is tracked and the last commit was an hour
old; the night's nine uncommitted rows had to be re-applied from the script that wrote them.

**Rules.**
* Never write a data file in place. Write a temporary file in the same directory and
  `os.replace()` it — the swap is atomic, and a failure anywhere before it leaves the original
  intact.
* Make re-application idempotent (add a row only when its id is absent), so recovery is a
  re-run rather than a reconstruction.
* Verify after writing: row count, no duplicate ids, and the audit. The truncation announced
  itself as "0 rows" only because the next command counted them.

## 110. A fix for a cause you have not measured buys a new defect at full price (2026-09-16)

A register's narration kept failing. The register was 23 columns wide, the prompt was large,
and oversized prompts had caused empty completions twice before (BUG-433, BUG-474). The
inference was immediate and wrong: I capped the handover at 12 columns, watched the log say
`projected to 12 of 23`, and watched it fail again.

Measurement, when it finally happened, took ten minutes and said something else entirely. The
provider's own log:

```
new prompt, n_ctx_slot = 16384, task.n_tokens = 155
ggml_cuda_compute_forward: ADD_ID failed
CUDA error: an illegal memory access was encountered
llama-server terminated  error="exit status 0xc0000409"
```

**A 155-token prompt crashed it.** Direct calls at 14k, 47k, 117k, 211k and 351k characters —
same `num_ctx`, same `keep_alive` — all answered normally, as did concurrent pairs. Prompt
width had nothing to do with it. The runner was dying of a CUDA fault upstream of this project
and recovering on its own ten minutes later.

The cap then caused a **worse** defect than the one it was invented for. Asked which spaces
suit quiet focused work, the projection dropped `noiseProfile`, `quietestPeriod` and
`seatCount`, and the answer said the records "do not contain any field that records whether a
space is quiet" — a building denying its own data, confidently, because of a fix for a cause
that was never there (BUG-622). And the rows counted in code were taken AFTER the projection,
so the system's most authoritative figures were computed from data it had just discarded.

**Rules.**
* Before fixing a failure, get the failing component's OWN log. Three layers of our logging
  said "LLM formatting failed"; only Ollama's said why, and it said something no amount of
  reasoning about our code would have produced.
* A plausible cause with prior form is the easiest thing in the world to confirm by accident.
  Falsify it instead: if width were the cause, a wider prompt would fail — so send one.
* When a fix survives its own cause being disproved, re-derive its justification from scratch
  or take it out. The cap stayed, at a width that trims nothing real, for a reason it can now
  actually support: provenance stamps are not content.
* Never compute a figure from data narrowed for a different purpose. Trim what you SHOW; count
  from everything.

## 111. `-p no:logging` removes `caplog`, and eight tests "error" (2026-09-16)

A full-suite run reported `6180 passed, 8 errors`, and the eight looked alarming until read:
`fixture 'caplog' not found`. I had passed `-p no:logging` to keep the output readable. The
same files pass 92/92 with logging enabled. The suite was green; the flag was not.

**Rule.** Quieting the harness changes what the harness provides. Before reporting a failure
count, re-run the failures WITHOUT the convenience flags — this is the measurement apparatus
being wrong again (#20-22), in its cheapest possible form.

## 112. A query that does not parse becomes a confident answer about something else (2026-09-16)

"What is the air quality on floor 3?" was answered from sensors labelled 5.02 and 5.03, with a
figure and a spread, and nothing in the answer or the logs said the floor had been lost. The
cause was four words in a comment:

```python
# ref: prefix is not in the standard block — declare it explicitly.
```

It had been true. The prefix was later added to the shared block, so the floor-scoped template
emitted it twice and GraphDB rejected the whole query — `MALFORMED QUERY: Multiple prefix
declarations for prefix 'ref'`. Every floor-scoped question had been failing since, and the
fallback takes the first 40 instances of the class **with no spatial constraint**, which on
this building are the densely instrumented floor's.

**Rules.**
* **Ask the shared thing what it contains; do not remember what it used to contain.** The code
  now reads `if "PREFIX ref:" not in block`. A comment asserting the state of another module is
  a fact with no test behind it, and it rots silently.
* **A failed query must not be answerable.** The damage was not the malformed SPARQL — it was a
  fallback willing to substitute an unconstrained instance list for a constrained query and
  narrate the result as though the constraint had held. When a specific query fails, the honest
  answers are "no data" or a stated widening, never a silent one.
* **The offline parser is not the store.** rdflib ACCEPTS a duplicated prefix; GraphDB rejects
  it. A green `prepareQuery` proves the grammar, not that any server will run it — so the test
  that has teeth here is the explicit duplicate check, and that asymmetry is now written into
  the test file rather than assumed.
* Three verification layers passed throughout: unit suite green, probe 59-60/60, and the
  per-floor answers *looked* right because a plausible number came back. It took asking a
  question whose answer I could check by eye — floor 3, sensors named 5.x — to see it.

## 113. A repair may widen the CLASS it looks for, never the PLACE it looks in (2026-09-16)

"What is the air quality on floor 3?" was answered from sensors labelled 5.27 and 5.32. The
retrieval was correct — 107 rows, every one on floor 3 — and a later stage threw them away:

```
[modality_repair] want=air_quality rows=107 miss=True under_populated=False
[modality_repair] no air_quality sensors from retrieval (107 rows); replaced with 400
```

Two faults in one log line, and both are general.

**A concept with two definitions.** The saturation catalogue said air quality is
`Air_Quality_Sensor`; the HBCO concept said it is CO2 + PM2.5 + TVOC + that. So 107 genuine
air-quality readings registered as a *total miss*. Whenever two structures define the same
word, one of them will eventually be consulted by code that does not know about the other.

**A repair that changes the question.** `build_modality_query` is building-wide by
construction, and it REPLACES the result — so the fix for "wrong modality" silently became
"wrong floor". Widening the class you look for is a repair. Widening the *place* is a
different question, answered confidently.

**Rules.**
* A stage that replaces another stage's result must preserve every constraint the question
  carried. If it cannot, it must decline rather than substitute.
* When you generalise a catalogue term, pass what the *resolver actually resolved to* rather
  than teaching a second module the same vocabulary. Generosity scoped to a deliberate
  resolution can only prevent a wrongful replacement; generosity in the general matcher would
  let "air" from `Air_Quality_Sensor` match every air temperature sensor.
* The same day, the same shape twice more: a fallback with no floor filter (#112) and a
  publisher band taken from a shallow class (BUG-638, where a 69 °C boiler flow was published
  at 22.5 °C because `Temperature_Sensor` describes a *room*). **Ask the most specific
  declaring class, and keep the scope you were given.**

## 114. Describing the shape of an answer is not the same as writing it (2026-09-17)

CAVEAT-604 gave the narration a clear instruction: where a question's word is also a recorded
status, *"answer with the total and give the split; never report the status count alone as the
total."* It held overnight, and the next probe answered *"There are 6 scheduled sessions
recorded for this room"* — from a room holding 23.

The counted facts were right both times. `Records held: 23. By recorded status: completed 17,
scheduled 6.` Only the wording moved, and the wording was the part left open.

The fix was to stop describing and start dictating: *OPEN with this sentence, filled in from
the counts above: "The room holds 23 records in total — completed 17, scheduled 6."* Same
facts, no new computation. Three consecutive asks then opened with it.

**Rules.**
* Where an answer must contain a specific figure, hand the model the SENTENCE, not a
  description of the sentence. BUG-581 moved the *counting* into code; this moves the
  *claim* into code and leaves the model only the prose around it.
* A defect that appears in one run of three is not fixed by one passing run. Ask it three
  times before believing it, and say so in the evidence.
* This is the third time a question with two defensible readings has been settled by whichever
  reading the model reached for first. When both readings are defensible, the answer carries
  both — and "carries both" has to be literal.

## 115. Four "open" defects were already fixed, and one was fixed except for the part that mattered (2026-09-17)

Working the open list one row at a time, four of the first five had already been repaired in
earlier sessions and nobody had gone back to close them:

* **BUG-487** — the vocabulary is 43 classes discovered from the ontology, not the 20-odd
  hardcoded tuple the row describes.
* **TODO-494** — "79 undocumented settings" was 26 by the time it was measured, and 0 of them
  were `Settings` fields.
* **TODO-490** — both code changes it specifies were in place.
* **CAVEAT-593** — three pairs still "disagreed", and every one is complementary.

A status column is not evidence. Re-measuring cost minutes per row and changed the answer
every time; two of the four would have been "fixed" a second time by anyone who trusted the
description.

**But TODO-490 is the one to remember.** Both of its code changes were done, the lay terms
were declared, the tie-break worked — and the question it was written for still failed:
*"Have there been any alarms this week?"* was answered by the alert-CREATION lane with a
configuration form. **The row described two changes; the defect was a third thing nobody had
asked about.** Closing it on the strength of "both changes are present" would have been
literally true and completely wrong.

**Rules.**
* Re-measure before repairing. The row tells you what someone believed months ago.
* Close a row on the QUESTION it was written about, asked live, not on the diff it proposed.
  A fix that is present and does not fix the question is not a fix.
* When an audit reports a number nobody can act on, make the audit say what the number is
  made of. `2,114 disagreements` was unusable for months; `label x2,093` settles it in a
  second — and a real conflict on `ontosage:area` would now stand out instead of hiding in
  the same total.

## 116. Two type systems, one crash, and a gate that failed open into silence (2026-09-17)

**What happened.** `SPARQLAgent.answer_semantically` returns `results` as a **list** —
`[{"answer": "..."}]`, annotated in its own source as *"Mock results for compatibility"*.
The verifier's two binding readers dug `result["results"]["results"]["bindings"]` behind an
`isinstance(result, dict)` guard on the **outer** value only. The outer value *is* a dict, so
the guard passed; the second `.get` then ran against the list and raised `AttributeError`.

The exception escaped `verify()` into `logger.debug(f"Verifier skipped: {_ve}")`. No
verification record was attached, and `publication_gate` — which fails open by design —
reads a missing record as *"the check did not run"* and publishes.

So the one lane whose output is ungrounded LLM prose over retrieved text was the **only**
lane with no grounding check, on every turn it fired, invisibly (BUG-643).

**Rules.**
* **A type hint two levels down is not a guard.** `Dict[str, Any]` says nothing about
  `result["results"]`. Guard the level you actually dereference, or write one reader that
  returns the empty value for every shape that is not the one you want.
* **"Mock results for compatibility" is a promise to readers you have not enumerated.** If
  a lane fakes another lane's envelope, something must fail loudly when the fake diverges.
  Here a test now reads `answer_semantically`'s source and fails if it stops returning a
  list — otherwise a later tidy-up leaves the guard passing while guarding nothing.
* **A fail-open gate must be loud when its input is missing.** Failing open is right —
  a verifier outage must not become a system outage — but `DEBUG` turned "the gate was
  removed" into "the gate decided to allow it". The same file already logs the evidence
  record's failure at `WARNING` with a traceback, twelve lines earlier, for exactly this
  reason. Two swallows in one function, one loud and one silent, and only the silent one
  hid a defect for months.
* **Find the FIRST crash, not the reported one.** The audit named `_sparql_returned_data`;
  `_extract_sensor_ids` ran first and raised first. Same consequence, but a fix applied only
  to the named line would have left the bug intact and the tests green.

## 117. A comma in the Edit tool is a column in the CSV (2026-09-17)

**What happened.** `tasks/FIX_TRACKER.csv` holds prose fields. BUG-497's `Verification` read
`PENDING live re-ask after restart (the probe is mid-run).` — no commas, so it was stored
**unquoted**. Replacing it with a sentence containing commas, through the Edit tool, split
one field into three: the row went to 14 columns against a 12-column header. Nothing
complained. It was caught only because the next script asserted every row's width before
writing.

**Rules.**
* **Edit tool for code; `csv` module for CSV.** A text edit does not know about quoting.
  Write the change through `csv.writer`, which quotes what needs quoting, then `os.replace`
  (#109).
* **Assert the shape after every tracker write.** `len(row) == len(header)` for every row,
  every time. It costs two lines and it is the only thing that catches this.
* A ragged CSV does not raise — `csv.reader` returns the wrong number of cells happily, and
  the damage surfaces later as a field that has silently lost its tail.

## 118. An inference hazard is a claim about the reasoner, so measure the reasoner (2026-09-17)

**What happened.** An agent reported a P2 load-blocker: the alarm data used `ontosage:priority`,
whose `rdfs:domain` is `MaintenanceIssue`, so "under the repository's RDFS reasoning" all 271
alarms would be inferred maintenance issues and leak into amenity answers. The reasoning was
textbook RDFS, the fix was cheap, and I started widening it — a general test then found the same
pattern in `effectiveFrom`, `effectiveTo` and `aboutEquipment`, apparently graph-wide.

Then I counted. 1,321 subjects already use `effectiveFrom` without being `ConfigurationPeriod`,
and `ConfigurationPeriod` counts 2,175 with inference and 2,175 in the explicit graph. The bldg
repository runs `rdfsplus-optimized`, which does not derive types from domain axioms. Nothing was
mis-typed. The "P2 load-blocker" was a prediction about a reasoner nobody had checked.

**Rules.**
* **Compare inferred and explicit before believing an inference effect.** In GraphDB, count the
  class with and without `FROM <http://www.ontotext.com/explicit>`. Equal counts mean the axiom
  is not firing, whatever the textbook says.
* **Name the ruleset in the claim.** "Under RDFS" and "under this repository's ruleset" are
  different statements; only the second is a defect report.
* **A general test that fails everywhere is telling you about the test first.** When a check
  written for one bug fails on 1,321 pre-existing subjects, either the whole graph is broken or the
  premise is — find out which before fixing either.
* **Keep what is true at its true size.** The domains ARE too narrow for how the predicates are
  used, and a full-RDFS deployment would suffer — that stays recorded, as a strict xfail and a P3
  modelling note, not as a P2 blocking tonight's load.


## 119. A slow case is a claim about the provider until its log says otherwise (2026-09-17)

**What happened.** Probe v17 was green but its slowest case took 167.9 s, and the unit suite had
been running alongside it. The tempting reading was load: CLAUDE.md itself says a doubling in
wall-clock is a load question first. The orchestrator log only showed an LLM call that took
161 s and came back empty. The host Ollama log said what it was: a 136-token prompt generated
16,248 tokens at 101 tok/s until the context was full (`truncated = 1`). Not load, not a hang,
a runaway, and the runner being single-slot put the next request 2m46s behind it. Nothing
capped local generation, while every hosted client had carried `max_tokens` for months.

**Rules.**
* **Read the provider's own log for any single slow call.** The orchestrator sees duration; only
  the runner sees tokens generated and why it stopped.
* **Size a cap from the distribution, not from the incident.** 7,167 completions in the same log
  gave p99 3,880 and 6 above 8,192, so 8,192 cuts almost nothing real and halves the stall.
* **A setting in one client and not its sibling is a defect in the sibling.**
* **Check the template for a key assigned twice.** `.env.example` set OLLAMA_NUM_CTX to 16384 and
  then to 8192; the last one wins, so the documented fix was undone for every fresh clone.


## 120. The guard that blanks an honest answer, and a stash inside a compound command (2026-09-18)

**What happened.** Two unrelated slips on the same afternoon, both worth keeping.

The deliberation lane had just gained a sentence naming values it had EXCLUDED as physically
impossible — minus seven people, minus 261 ppm of CO2. That sentence necessarily quotes numbers
that are, by construction, not in the ranking: they were popped out of it. `numeric_guard`
requires every number in the prose to exist in the dossier, and its remedy on violation is to
replace the entire answer with "I computed a ranking but its narration failed the evidence
check". So the ranking that was honest about a broken reading was the one that could not ship,
and the silent one passed. The new out-of-band sentence would have done the same. Both lists are
now in the guard's allowed text.

Separately, a `git diff` was appended to a test command with `&&` and a `git stash push -q`
slipped in with it. The rule in force said no stash. The routing rules written that afternoon
went into a stash silently — `-q` means no output, and the test command's output scrolled past.

**Rules.**
* **A guard whose remedy is to discard the whole answer must be taught every sentence that
  exists to be honest.** Otherwise it punishes exactly the disclosure it was built to protect,
  and the failure looks like a narration bug rather than a policy one.
* **Any number a system prints ABOUT a value it rejected is still dossier content.** Excluded
  values, band edges, thresholds not met — all of them, or the disclosure cannot be written.
* **Never put a state-changing git command in a compound shell line.** It runs whether or not
  you meant it to, and `-q` hides that it did. Check `git stash list` immediately if one does.
* **Verify a restore by looking for the work, not for the absence of an error.** `git stash pop`
  printed a two-hundred-line status; the only lines that mattered were a grep for the two rule
  names and an empty `git stash list`.


## 121. A "good" label is a claim about the data, and a plausible answer is not evidence (2026-09-18)

**What happened.** Three rehearsals of the 44-question demo script were hand-read and two answers
were labelled GOOD that were wrong. *"Which refuge points are defective, and who owns them?"* said
the register has no ownership field, in all three runs; `evacuation_and_peeps.md` has an `owner`
column and EV-003 reads "Building Fire Warden Coordinator". *"Compare this week's electricity use
with last week"* reported a 34–36% fall in both rehearsals; it was a Friday, so week 38 held five
days and week 37 seven, and the label noticed that week 36 was excluded and missed that week 38 was
itself partial. Both were found only by opening the source table and asking which ISO week was
partial. Six other register answers checked the same way were right, so the check is cheap.

A related slip, the same evening: `pytest ...; echo "exit=$?"` inside a script whose echo also had a
`$(date ...)` reports the substitution's status, not pytest's. The suite log said `exit=0` beside
"1 failed".

**Rules.**
* **Check every absence claim ("the register has no X") and every comparison figure against the
  source before labelling GOOD.** Parse the table: counts by status, the column list. Twenty lines.
* **A label that was accepted twice is not thereby checked.** Re-reading three runs found nothing
  because each read used the same shortcut. Change what you look at, not how many times.
* **Report "good" counts as an upper bound** unless every answer was checked against data; keep the
  old label in `relabelled_from` and write the reason in a corrections file. Never edit history.
* **A workaround written after seeing a failure is a hypothesis.** Of 14 rewordings written after
  their siblings failed, 11 failed too. Do not put an untested rewording in a runbook.
* **Read the exit code from the command that produced it:** `cmd > out; rc=$?; echo "exit=$rc"`.
  Never `$?` after a command substitution in the same line (see also #101, #107).
* **A long live run needs to be resumable.** Docker Desktop restarted the whole stack at 22:09 and
  killed the run at question 22 of 44; running only the remaining 22 and saying so was cheap
  because the harness took a question file.


## 122. Every routing rule runs, and the LAST one wins (2026-09-19)

**What happened.** Two probe cases regressed together: "How many work orders are open?" was
answered from the events store's 520 generated rows instead of the register's 24, and "Which
teaching sessions are scheduled in Room 1.06?" came back "This building doesn't keep a record of
that" while 675 session rows sat in the register. Neither lane had changed — the LLM classifier
simply chose `events` that day, having chosen `metadata` the day before.

The fix was a contract rule sending both shapes to the register. It was placed BEFORE
`event_store_query`, on the assumption that the first matching rule wins. Deployed, it changed
nothing at all: `apply_contract` runs EVERY rule in the stage and each one SETS the intent, so
`event_store_query` overwrote the correction a few rules later. `apply_contract` returns the list
of rules that fired — both names were in it, which is what made the mistake visible.

**Rules.**
* **A corrective routing rule goes AFTER the rule it corrects**, not before. Read the returned
  rule list, not just the final intent: two names in it means both fired and the later one won.
* **A lane's vocabulary must not claim a question the lane cannot serve.** `EVENTS_RE` claims
  timetable questions and the events lane has no timetable kind at all, so every one of them was
  answered "this building doesn't keep a record of that" — a false absence manufactured by routing.
* **When two stores hold the same kind of record, name which one answers.** The events store holds
  520 generated work orders and the register holds 24 authored ones with ids a person can act on.
  Whichever is chosen, the answer must say — and it must not be the classifier's mood that decides.
* **Verify a routing fix live before believing it.** The offline guard harness reported 0 moves and
  0 violations for a rule that was doing nothing whatsoever.


## 123. A bare `no` in a YAML list is the boolean false (2026-09-19)

**What happened.** "Which departments have no out-of-hours route?" answered "None of the 20 records
lacks a recorded out-of-hours route — every one of them has it", over a register whose own closing
sentence reads "Eight have no out-of-hours route at all". Those eight record the VALUE "No cover,
next working day", which is a present field that says the thing is absent.

The composition handled both readings correctly. The vocabulary did not: `absent_values` began with
a bare `no`, YAML 1.1 parses that as the boolean **false**, and the pattern built from it was
`\s*false\b` — which matches nothing. Every other word in the list worked, so the feature looked
implemented and tested while its most important word was silently missing.

**Rules.**
* **Quote `no`, `yes`, `on`, `off`, `y`, `n` in YAML lists**, and add a test that fails when any
  list in a config file holds a boolean. The value looks right in the file and is wrong in memory.
* **A predicate built from config deserves a test with the real value from the real data**, not
  just a synthetic one: "None" passed all along, so a test using it proved nothing about "No cover".
* **"Which X have no Y" has two readings** — the field is empty, and the field says none. Answer
  from whichever yields records and say which reading was used; they are different facts.
* Found by the regression probe, not by a unit test: the pinned case asserted a department name in
  the answer, which no amount of green unit tests could have supplied.


## 124. A gate that fails open can be dead and look healthy (2026-09-20)

**What happened.** The answer-relevance gate was built, unit-tested (50 tests), documented and
deployed. On its first live run it judged 32 answers and replaced none. It had failed open, exactly
as designed, on every call: `llm_manager.generate_structured` sent the local reasoning model a JSON
schema as `format`, the constrained decoder and the model's thinking shared one token budget, and
every completion came back EMPTY. Three retries, a tripped circuit breaker, and an answer left
untouched — indistinguishable in the output from "the judge thought everything was fine".

The offline experiment that justified the gate had used the raw chat API with `think: low`, so it
worked there. Nothing in the unit tests could see the difference: they faked the client.

**Rules.**
* **A fail-open component needs a liveness check** — a count of how often it actually *acted* — and
  the first live run must be read for it. "0 replacements from 32 judged" is the signal; a healthy
  gate on these lanes replaces roughly one answer in six.
* **Test a new model call with the real model before trusting any test of it.** A one-question
  probe inside the container (`gate_probe.py`-style) took two minutes and found the bug.
* **Measure the thing you deploy, not its cousin.** The experiment and the product reached the model
  by different paths; only one of them worked.
* **A heuristic that warns is still information.** "prompt carries an EMPTY question slot" fired on
  every gate call (the label `QUESTION:` alone on a line), and would have hidden the next real one.

## 125. The heredoc trap, again: backspaces and newlines in generated source (2026-09-20)

Twice in one day Python written through a shell heredoc was silently corrupted: a regex `\b` became a
literal backspace (the lay-quantity pattern matched nothing; found only by five failing tests), and
`"\n\n"` became real newlines inside a string literal (a SyntaxError at collection). lessons #101
and the CLAUDE.md notes already say never to do this; the cost was two debugging detours.

**Rules.** Write source with the Write or Edit tools. If a script must be generated, check
`s.count(chr(8))` and compile it before running. `tests/test_no_source_file_contains_a_backspace_
character.py` now fails on any 0x08 in `orchestrator/`, `shared/` or `scripts/`.

## 126. Measure a model-judged change paired, on the same questions (2026-09-20)

Six waves of per-answer fixes left the unseen-question weird rate near 40% because the tail is long.
Class-level gates (an answer-shape guard, an absence rewrite, lane-misfire rules, a relevance judge,
and replacing a machine-shaped refusal with an honest decline) finally moved it: 41.2% pooled over
seven earlier sets against 26.6% on the last two (z = 3.2, p about 0.002).

The relevance gate's own share was measured *paired*: tail K was run with the gate silently off, then
on. It fixed 3 of 17 weird answers, replaced 0 good ones and swapped 6 declines for other declines.
An offline estimate (−11 points) and an out-of-sample one (−11) were both larger than the live gain
(−5), because live answers vary run to run and the estimate was selected on its own best case.

**Rules.** Quote the live paired figure. Treat a lane allowlist chosen on the data it is scored on as
an upper bound. Draw a fresh set before every verdict; brief agents on classes, never on questions.

## #127 — Grep the schema and the graph before declaring a term (2026-09-21)

Adding room schedules, I declared `ontosage:TimetabledSession` with `dayOfWeek`, `startTime`,
`endTime` and `inSpace`. All of it already existed: the class was declared at schema line 1701, it
had **675 instances across 44 rooms**, and those instances used `timeProfile`, `startsAt`, `endsAt`
and `locationText`. The feature was not "no timetable"; it was "nothing reads the timetable".

The same mistake then cost an accessibility answer. I wrote `ontosage:isWheelchairAccessible true`
on twelve accessible toilets. `amenity_proximity` decides accessibility from
`ontosage:accessibilityVerified`. Six floors of accessible toilets were recorded, uploaded and
parsed — and the live answer still sent a wheelchair user one floor up, because nothing reads the
name I invented.

**A duplicate term is worse than a missing one.** A missing term fails loudly. A duplicate splits a
register in two and each half looks complete: my query found 11 sessions and reported success while
675 sat beside them, and the graph reported 686 `TimetabledSession` subjects, which is how I noticed.

**Before declaring any class or property:** grep the schema for the name, grep it for the *concept*
(`session`, `toilet`, `accessible`), and ask the live graph `SELECT (COUNT(DISTINCT ?s)) WHERE { ?s a
o:<Class> }`. If instances exist, read one and use ITS property names.

Corollary: deleting data has references. Removing the placeholder toilets left 22 `statusOf` triples
pointing at nothing, which `tests/test_dangling_references.py` caught — a reasoner types an
undeclared subject from the property's range, so the graph looks complete while the status describes
an amenity the building does not have.

## #128 — A truncated menu does not make a model cautious, it makes it wrong (2026-09-21)

Building the semantic concept matcher I capped the candidate list at 40 concepts, sorted
alphabetically. The building has 99. The menu stopped at "busy", so `too_warm` and `too_cold` were
never offered, and the model answered NONE to "where is it coolest" — **correctly, for the menu it
was given.** Nothing in the reply said the menu was short. I only found it by printing the menu.

When a model is asked to choose from a list, the list is part of the question. A bug in it looks
exactly like a considered refusal.

**And a model asked to choose will reach.** With the full menu it mapped "what is the radiation
level" to *solar irradiance* and "is there smoke in the lab" to an *emergency exit*: honest-sounding
answers to a question nobody asked. Prompt hardening fixed three of five traps and left two.
Selecting from ninety options is recall, which it is good at; declining is precision, which it is
not. The fix was a second, narrow yes/no on the one pair it chose — *is this the quantity that was
asked about?* — which it answers reliably. 8/8 after. **Where a model must be allowed to say no,
split the choosing from the confirming.**

## #129 — The browser does not send the apostrophe you typed (2026-09-21)

"Where's the coolest place to work" reached the deliberate lane from the CLI and the workspace
register from Open WebUI. Open WebUI sends a typographic apostrophe; every pattern in
`routing_contract.py` is written with the ASCII one, so `DELIBERATE_RE` matched one and not the
other. The route depended on where the question was typed, and the browser is where the users are.

I found it only because I *opened the screenshot* and saw an answer the CLI had not given me
minutes earlier. A CLI check is not a check of what the user sees. Normalising quotes once when the
rule context is built fixes every rule at once, which is where that repair belongs.

## #130 — Typographic punctuation bites twice (2026-09-22)

Lesson #129 was a curly apostrophe changing which lane a question took. Three days later the same
class of bug hid inside the regression gate: the marker `"there is no air-pressure sensor data"`
never matched its own recorded answer, because the text carried a NON-BREAKING hyphen (U+2011) and
the marker an ASCII one. The gate therefore reported a stable question as REGRESSED.

Both times the symptom was a comparison that should obviously have matched and did not, and both
times the text looked identical on screen. **Any string a model generated, a browser typed or a
renderer produced must be punctuation-normalised before it is matched against a pattern written by
hand.** Doing it at one edge — where the text enters the comparison — fixes every pattern at once.

## #131 — A verdict must be re-read against the answer it is filed beside (2026-09-22)

The 73-question evidence pack shipped with one verdict describing an answer that was not the one
stored: #69 was marked GOOD with a note about a defensible chiller answer, while the stored answer
and its screenshot were "I found nothing in Abacws Building's records". The verdict had been written
from an earlier run, and the merged pack kept a later run's answer.

Nobody would have noticed by reading the README — the count simply said 52. It was found by the
regression gate on its first full run, because the gate derives its expectation from the STORED
ANSWER rather than from the verdict, so the two disagreeing was immediately visible.

**Where a judgement and its evidence are stored separately, something must check they still refer to
each other.** This is lesson #121 (check labels against source data) in a second form: there, a label
disagreed with the source table; here, with the answer beside it.

## #132 — Two prompt edits that trade precision for recall mean the MENU is wrong (2026-09-23)

The semantic concept matcher let "is there smoke in the lab?" resolve to `emergency_exit`. I fixed
it in the prompt. The next run fixed smoke and broke "which room is least noisy". I fixed the
wording again; that run fixed noisy and broke smoke a different way. Two edits, no net gain, and
each one a plausible-sounding rule about how to read a question.

The menu was the bug. `fire_safety` and `emergency_exit` were on it because they carry
`brick:Smoke_Detector`, which IS a sensor class in the schema — and of which this building holds two
instances with **zero readings between them**. The model was being asked to decline an option that
should never have been offered, and no wording makes "choose the best of these" reliably answer
"none of these".

The filter that fixes it is four lines and asks the graph, not the schema: a concept is a candidate
measurand only if one of its classes has an instance here that carries a timeseries reference.
Sound, temperature and CO2 answer 233/233, 296/296, 280/280. Smoke and fire answer 2/0 and 6/0. It
removed 7 of 92 concepts, all five traps passed at once, and the prompt got SHORTER.

**When a second prompt edit trades one failure for another, stop editing the prompt.** The model is
usually doing the task it was given; check what it was given. And prefer a question the data can
answer ("does anything here report this?") over a rule about language ("point at the word that names
this quantity") — the first is building-agnostic and the second is a guess about English.

## #133 — Ask the lane that exists before building the one the plan names (2026-09-23)

Wave 1 of the production plan was five rows about building a multi-read lane: route a question
naming two measurands, fetch N modalities, combine their meaning. Estimated days.

Before writing any of it I asked the live system four cross-modal questions. One of them —
"is anywhere both hot and noisy at the moment?" — came back with the rooms ranked on temperature AND
noise, per-modality values, the band each was scored against, 195 of 234 spaces considered, 39
excluded and listed, and an evidence dossier naming the source table per reading. The lane was
already there and already correct.

Of the other three, one was refused by the compiler because the model had omitted a direction the
polarity table already held (BUG-869), and two never reached the lane: one because the word "both"
sat between the verb and the adjective, one because "where is it cool and quiet" matched no routing
branch (BUG-870). Total fix: two regex widenings and an 8-line function.

**A plan written from the outside describes what looks missing, not what is missing.** Four
questions and ten minutes reclassified two days of building as two small defects — and the
difference was visible only from the ANSWER, not from reading the code, because the code for a lane
that works and a lane nobody can reach looks the same.

## #134 — A probe that reuses one chat measures the co-reference rewrite too (2026-09-23)

"Where is it cool and quiet enough to work?" routed to `deliberate` asked alone, and to `sparql`
asked as turn four of the same chat. I spent a cycle looking for the routing rule that failed. None
had: the rewrite had resolved "it" against the previous answer's room, changing the question's SHAPE
so it no longer matched the pattern — correct behaviour for a real follow-up, and silent corruption
of a measurement.

**Send a distinct chat id per question in any harness not deliberately testing follow-ups.** The
class is wider than this one rewrite: anything that legitimately depends on conversation state turns
a batch of independent questions into one conversation, and reports the difference as a defect in
whatever you happened to be changing. Related: CAVEAT-871, and #126 on pairing measurements.

## #135 — Three guards destroyed a correct answer in one session (2026-09-23)

Each was built to stop a specific dishonesty, each was right to exist, and each replaced a
correct answer with a worse one:

* **BUG-868** — the ranking lane suppressed "Best match" when every score tied at the BOTTOM of
  the band (row 58) and said nothing when every score tied at 1.0, so a 22.6 °C room in a 20–26
  band was announced as "score 1 out of 1, fits everything you asked for".
* **BUG-873** — the answer-relevance gate discarded a successful forecast (`MAE=0.473%RH`,
  `success=True`) as OFF_TOPIC and left "I couldn't answer that". Its own `except` branch is
  commented "the gate must never cost an answer"; the success path does exactly that.
* **BUG-878** — the absence guard replaced "1 of 234 spaces have no noise sensor, 233 have one"
  — verified against the graph — with "this building does have 235 noise sensor(s)". True, and
  an answer to a question nobody asked.

The shape is identical every time: **a guard detects correctly and then acts too widely.** The
detection was right in all three. What was wrong was the SCOPE of the replacement — bottom of
the band but not the top, any OFF_TOPIC verdict rather than a wrong referent, any sentence
rather than an unscoped one.

**When a guard fires, ask what it is allowed to do, not only what it is allowed to notice.** And
prefer narrowing the ACTION to narrowing the detection: a guard that notices less is blind, a
guard that acts more carefully is still watching. Two of these three were fixed by scoping the
action and neither lost any of the cases it was built for — pinned by re-testing the original
failure verbatim in each case.

## #136 — Four plan rows in two sessions asked for something already built (2026-09-23)

* **W1-01/W1-02** "build a multi-read lane" — the deliberation lane already ranked on N
  modalities with coverage, exclusions and a dossier.
* **W1-05** "one SPARQL: spaces minus spaces that have a sensor of the class" —
  `deliberation/coverage_audit.py`, whose first line of documentation is the question verbatim
  ("which spaces lack which sensor modalities?"), and which additionally separates "no sensor"
  from "a sensor reporting nothing", which the proposed query would have collapsed.
* **W1-04** "compare two periods" — the WINDOW half was genuinely missing, but
  `evidence/matched_comparison.py` had done the comparison arithmetic since V6, with covariate
  matching and confidence intervals, and had one caller.

In every case the plan was written from the outside, from what the system FAILED to answer.
That is a true observation and a bad inference: a lane that works and a lane nobody can reach
produce the identical symptom, and the code for both looks the same from a distance.

**Before building what a plan names, ask the running system the question and grep for the
capability by its PURPOSE rather than its name.** Ten minutes of four questions reclassified two
days of building as three small defects. The corollary is uncomfortable and worth stating: this
repository's real deficit is not missing capability, it is capability nothing routes to — which
means a routing or surfacing fix is usually worth more than a new module, and a new module
built over a working one is worse than nothing, because now two things answer the question.

## #137 — A constant is not in force until its caller lets it be (2026-09-23)

`plausibility.py` defines `_METRIC_LOOKBACK = 320`, with a comment explaining the number:
"the R² column header was about 130 characters before its value, because the whole table renders
as tab-and-newline separated tokens". The function that uses it looks back `_METRIC_LOOKBACK`
characters. The call site passed it **90**.

So the fix written for the CO2 case, with six passing tests, was dead on arrival — and the same
defect reappeared on a humidity forecast, where an R² of -0.029 and a row count of 193 were
reported as "the recorded humidity value (193, -0.029) is outside the range this quantity can
take in %... the sensor's scaling should be checked before this reading is relied on", over a
series that is a clean 30–70 %RH with zero impossible values.

The six existing tests passed throughout because their sample text was SHORTENED: the R² sat
within 90 characters of its header, which never happens in the answer the system renders.

**A test built from a convenient approximation of the real artefact tests the approximation.**
The new test uses the verbatim rendered answer, and a second one pins the lookback by DISTANCE
so the constant cannot be silently under-fed again. Related: #101, and the whole of the
measurement-apparatus family.

## #138 — A test that builds the input can build an input the pipeline never produces (2026-09-23)

The new routing rule `one_quantity_judged_against_another` needs two of the building's
quantities, and one of them arrives as a resolved lay concept ("ventilation" → CO2). I put it in
`PARSE_STAGE_RULES`. Eleven unit tests passed — they constructed the normalized dict themselves,
concepts included. On a live turn it fired **zero** times: concepts are resolved *after* the
parse stage, so the field it read was always empty and its guard could never be satisfied.

The tests were not wrong about the rule. They proved its LOGIC and said nothing about whether
the data it reads exists at the point it runs. A test that hands a function its input has, by
construction, no opinion on where that input comes from.

**When a unit test constructs the input, something else must prove the pipeline produces it
there.** The cheapest something else is one live question — which is how this was caught, after
the offline suite was fully green in the wrong stage. Where a stage boundary exists, the rule of
thumb is blunt: a rule reading a field belongs in the stage that fills it, and the pinned-order
comment is where to say so, because that test is the only place a reader reliably looks.

## #139 — One sensor standing in for a floor, with every digit correct (2026-09-23)

    "Predict the average CO2 on floor 3"        -> forecast of ONE room, of 45 instrumented
    "What will the building's energy use be?"   -> forecast of ONE floor's meter, of six

Both answers were internally perfect: real history, proper model selection, hold-out validation,
confidence intervals. Both answered a question nobody asked. And the energy one was additionally
*low by roughly a factor of six*, because energy SUMS across meters.

The substitution was not even hidden — the chosen sensor is named in the heading. But a reader
who asked about floor 3 has no reason to read "Forecast: CO2 Level Sensor installed-node 3.58"
as a correction of their question; they read it as the system's name for the thing they asked
about.

**Naming what you actually measured is not the same as saying you measured something else.**
The fix is one sentence — "averaged over 50 sensors" — and the general rule is that wherever a
lane narrows a question's scope to make it answerable, the narrowing belongs in the answer, in
words, not only in a label the reader must decode.

The second half is worth its own line: **mean or total is a property of the QUANTITY, not of the
question's wording.** "Total CO2 on floor 3" must still average — summing forty-five rooms of
concentration gives 33,000 ppm — while "the building's energy" must sum whether or not anyone
said "total". A system that took the aggregate from the phrasing would be wrong in exactly the
cases where the phrasing is loosest.

## #140 — Replacing a name match with a structure query can reintroduce the name match (2026-09-23)

"Will floor 3 be warmer than floor 4 tomorrow?" bound eight floor-3 METERS — access reader,
entry counter, HVAC meter — nothing from floor 4, and no temperature sensor at all. The resolver
matched a floor by TEXT, so it found what was *named* for the floor rather than what was *on*
it. The graph had held floor → spaces → points the whole time; asked structurally, floor 3 gives
48 temperature sensors and floor 4 gives 56.

**The fix reintroduced the bug one layer down, and the answer stayed confident throughout.** The
structural query returns 400 points, so I narrowed them with the existing scorer — which ranks by
overlap with the QUESTION's words. Every candidate was already on floor 3, so "floor 3" was pure
noise, and `Floor3_General_Waste_Bin_Fill` outscored forty-eight temperature sensors. The system
then compared floor 3's waste bins against floor 4's temperatures and reported degrees.

**When you narrow a set that is already scoped, the words that did the scoping are noise, and
they will score highest.** The filter has to be the thing the scoping did not already use — here
the resolved Brick class. And where no class resolves, the honest move is to return nothing and
let the old path run: binding eight arbitrary points off a floor is worse than the behaviour
being replaced, not better.

**Second trap, same fix: a floor's mean is not eight of its rooms.** A default `limit=8` that
exists to stop a unit name dragging in every point on an AHU truncated 104 floor sensors to 8 —
all from floor 3 — while the answer went on quoting floor-4 numbers. A limit written for one
question shape silently becomes a sampling decision in another.

Both were found by reading the resolution log against the answer, not by any test, and both
produced fluent wrong answers rather than errors. Related: #121 (check labels against source
data) — the closing check here was querying MySQL directly for both floors' means.

## #141 — A fix to a measuring instrument is wrong in BOTH directions, and they cost differently (2026-09-23)

The answerability gate scored an honest decline as an answer, because the system had reworded
it: the marker is the literal "there is no air-pressure sensor DATA" and the answer said "no
air-pressure sensor INSTALLED IN Room 2.01". A decline recognised by one fixed string is a
decline recognised in one phrasing.

Fixing it took three attempts, and the two failures were in the OPPOSITE direction:

* `there (is|are) no .{0,40} sensors?` also matched **"there are no GAPS IN SENSOR COVERAGE"** —
  a completeness answer asserting the exact opposite of an absence.
* keying on `installed` alone matched the LABEL **"CO2 Level Sensor installed-node 3.07"**.

Both would have called real answers declines. **The two errors are not symmetric.** A decline
scored as an answer HIDES a regression — the gate goes quiet while something is broken. An
answer scored as a decline MANUFACTURES one — and a gate that cries wolf gets switched off,
after which it hides everything. So the second is cheaper to notice and more expensive to leave.

What caught both was refusing to accept the fix until every one of the 73 stored answers
classified exactly as before. The broad pattern moved two of them (57/14 → 55/16), and that
number was the whole signal. **A classifier change silently rewrites the baseline the gate
compares against**, because the expected kind is DERIVED from the stored answer by that same
classifier — so "did anything move?" is the only question worth asking, and it is now a test.

## #142 — A generated top-up on top of a LIVE source is a fabrication wearing the data's clothes (2026-09-29)

Tracker row W3-01 said outdoor-weather questions decline and was blocked waiting for the owner to
say whether a real weather API exists. All three halves of that were wrong. `input/feeds.yaml`
already declared three Open-Meteo `rest_poll` feeds; the feeds polled; the rows landed; the points
were registered in GraphDB with their Brick classes; `services/outdoor_readings.py` already bound
them by class; and the question answered rather than declining. That is the fourth and fifth time a
row asked for something already built (#133, #136) — but the new part is what was actually broken.

`data-publisher` reads the wide table's columns from `information_schema` and invents a value for
**every** one of them. Three of those columns belong to a live feed. So every 30 seconds it wrote
over a real measurement:

```
15:26:15 UTC   21.90 degC / 71.00 % / 19.40 km/h   <- the feed; Open-Meteo said 22.0 / 70 / 19.4
15:26:41 UTC   24.06      / 56.80   /  7.08        <- the publisher
15:27:11 UTC   24.15      / 56.92   /  7.02        <- the publisher
```

Ten samples in eleven were fabricated. A "right now" question read whichever landed last, so it
almost always read a number nobody measured — and "23.8 °C in Cardiff this afternoon" is exactly
plausible enough that no guard objected.

**Generating a value for a sensor with no live source is this service's job (BUG-144). Generating
one on top of a source that IS live is not a top-up, it is a fabrication.** The difference is
invisible from inside the publisher, because a column is a column; it is only visible where the two
facts meet — `feeds.yaml` says what is live, `information_schema` says what exists, and nothing was
comparing them.

Three things this changes about how to look:

* **"The rows are landing" is not "the answer is from the feed."** `write_records` logged success
  every five minutes throughout. The write path was never the problem; the *other* writer was. When
  a store has more than one writer, check the cadence of the values, not the presence of them —
  a 30-second series where a 300-second one is expected is the whole tell.
* **A plausible generator hides longer than a crude one.** These three UUIDs were named in the
  publisher's own `sensor_uuids.json`, so `get_realistic_value` produced weather-shaped weather. Had
  it fallen through to the type-based fallback and written `1`, CAVEAT-410 would have caught it
  years earlier.
* **Check a live reading against the world, not against itself.** Every internal check passed. What
  found this was one `curl` to `api.open-meteo.com` and one `SELECT ... ORDER BY Datetime DESC LIMIT
  5` side by side. For any value that claims an external source, the source is the oracle.

The fix derives the protected set from the building's own `feeds.yaml` using the same UUID
derivation as `FeedRegistry`, and a test asserts the two derivations are equal — because if they
ever drift, the exclusion set matches no column, nothing is protected, and **nothing fails**. It
also reports the count it actually removed and warns on zero, since a wrong `BUILDING_ID` derives
well-formed UUIDs that match nothing and would otherwise read as success (#126).


## #143 — A denylist scope can turn a whole register off, and the fallback then denies it exists (2026-09-29)

Two phrasings of one question, routed **identically** (`intent=metadata -> metadata node=sparql
overrides=[]`), disagreed about whether the building records calibration at all:

    "How many sensors are overdue for calibration?"
        -> 268 overdue, of the 1,929 sensors that have a calibration regime recorded.
    "How many sensors are overdue for calibration, and what does that mean for the answers
     you give me?"
        -> "it does not contain any field that records whether a sensor is overdue for
            calibration, nor does it record a calibration schedule or status."

The tracker row called this "two calibration registers". There was one: three predicates,
1,929 subjects each, one generated file. **The disagreement was two LANES, and the losing one was
reached by accident.**

`_measurand_tokens` scopes a query by taking every word in the question that is *not* in a
hand-written stopword set. "mean", "answers", "you" and "give" are not in it, so the lane filtered
sensor names by those four words, got zero rows, returned `None`, and handed the question to a
generated query that cannot see the properties — which then denied they exist.

* **A denylist over English cannot be finished.** The stopword set already had ~90 entries and
  four ordinary words got through. The next phrasing finds the next gap, and the failure is silent
  every time: an over-narrow scope and an empty register are the same empty result set.
* **"I scoped it wrongly" must not fall back to a lane that can answer "it doesn't exist."**
  This is #135 one level down. The guard detected correctly (no rows) and acted too widely
  (abandon the question) — and the fallback's confident denial is worse than the decline it
  replaced, because nothing signals it is wrong.
* **Let the data decide what scopes.** The fix asks the active building's own register which of
  the candidate tokens name something it holds, in one query, and drops the rest. Building-agnostic,
  no word list, and a token list that matches nothing means *unscoped* — answer building-wide from
  the same register — never *abandon*.
* **Pin it with a test that restores the defect.** `test_the_defect_returns_the_moment_the_check_is_removed`
  puts the denylist back in charge and asserts the lane goes dark again. Without it, a later session
  could delete the scope check as "an extra round trip" and every acceptance test would still pass.

The reproduction came first and was worth the twenty minutes: the tracker's own Evidence column
named the wrong pair of pack answers (#40/#49 — both correct), and building from it would have
produced a fix for a defect that does not exist. **Ask the running system which two answers
actually disagree before believing the row that says they do.**

---

## #144 — The term already existed TWICE, and the two disagreed (2026-09-29)

W3-04 asked for `ontosage:designOccupancy` on spaces. Lesson #127 says to look before inventing a
term. Looking found two:

    <building>:maxOccupancy   29 spaces
    hbco:roomCapacity         19 spaces

That alone is #127 again. The part worth a new number is what the overlap showed. Six spaces carry
both, and **three of the six disagree** — Room 1.04 at 50 and 25, Room 4.01 at 25 and 20, Room 5.01
at 25 and 20 — while `ontosage:capacityBasis`, the property that would say where a figure came
from, has **zero triples** in the live graph.

* **A resolver that picks one is deciding by accident.** Which number answers a fire-safety or a
  booking question would have been settled by the order the query returned rows in. So the module
  keeps every declaration and says "the building states 50 under maxOccupancy, 25 under
  roomCapacity; nothing says which is authoritative, so I will not pick one." That is a true and
  actionable answer. "The design occupancy is 50" is a coin toss wearing a fact's clothes.
* **Grepping for the TERM would have missed the conflict.** `maxOccupancy` appears in one TTL and
  the disagreement is only visible by JOINING the two properties in the live graph. Grep found the
  term; only the running system found that it had a rival.
* **Discover the predicate, do not name it.** Matching any property whose local name normalises to
  a design-occupancy word, on a subject the ontology types as a location, with a numeric value,
  found exactly the two — and correctly excluded `capacityLitres` on 24 bins, `alternativeCapacity`
  on 8 continuity plans and `rec:capacity`'s "about 500 people" on the building. A substring match
  on "capacity" would have reported a 1,100-litre bin as a room for 1,100 people.

The same session's W3-05 is the mirror image: the pieces to compute a sensor's last-seen time all
existed (a narrow-adapter `latest_by_uuid`, an admin endpoint, a freshness count) and **no lane
joined them**, so the live answer to "which sensors stopped reporting" was "none of them appear to
have stopped reporting" — a confident all-clear over a sensor twelve days dead. **A window of
readings cannot evidence silence.** A sensor that stopped is absent from the window by definition,
so any lane reasoning from readings can only ever conclude that everything is fine. Route the
question to something that asks the store, or do not answer it.

## #145 — A hand-run query that differs from the one the code sends verifies the intent, not the code (2026-09-29)

CAVEAT-892 was logged FIXED, same day, with this verification in the tracker:

> The class-preferred SPARQL run by hand against the live graph returns exactly
> `bldg:feed_outside_weather_temp` — the Open-Meteo point — where the label path returned
> `GreenRoof_Ambient_Temp_Sensor`.

Every word of that is true, and the fix did not work. The live re-ask afterwards still bound the
green-roof sensor. **The query I ran by hand carried one class. The query the code sent carried
eight**, because `class_hints` is every Brick class of every resolved concept flattened together,
so it held the specific class *and its parents*. `Outside_Air_Temperature_Sensor` has one
instance; `Air_Temperature_Sensor` has the roof sensor too. I had typed the query I meant and
checked that my reasoning was sound, which it was — about a query that never ran.

* **Reconstruct the query from the code, or log the query the code sends.** Not from the design.
  The two diverged at the one place a summary would never look: a list comprehension upstream.
* **The log told me and I could not read it.** It printed `_hint_classes[:2]` while the query used
  `[:8]`, so the two broad classes that caused the bug were never on screen. *A truncated log of
  the input to a decision is a log of a different decision.* If a value is what the code acted on,
  print what it acted on or say how much you cut.
* **The fix made it worse before it made it better**, which is the part worth remembering. Adding
  the broad classes to a `VALUES` widened the candidate set, and the token filter — which required
  the word "outdoor" — then *excluded the correctly typed point*, whose label says "outside", and
  *kept* the mistyped one, whose label says "outdoor reference". Two mechanisms, each defensible,
  composing into a worse answer than either alone.
* A resolved class that is narrow enough to be the answer should not also have to pass a word
  match. **The extracted tokens restate the class** ("Outdoor_Temperature_Sensor"), so they add no
  information and can only lose points to a vocabulary difference.

## #146 — Lifting a gate proves nothing until you have shown it was the gate that was shut (2026-09-29)

BUG-879's log line names its own cause, which is why it was believed:

    [aggregate] not claimed: measurand=co2 place=True per_sensor=False readings=True

`place=True` looks like the reason, so the veto on named places was lifted — carefully, behind a
keyword-only caller flag, with a regrouping so the label follows the scope, and thirteen tests.
Measured afterwards: `summary_ok=True` and the lane **still** declined, for both window sizes.

The flag fed `summary_ok`, and `summary_ok` reaches exactly one of `wants_lane`'s six cases — the
one that fires when the question parses to *no statistic in particular*. "Compare the **average**
CO2 in room 5.01 this week against last week" parses cleanly to `stat=mean, group=building`, so it
skipped that case, matched none of the other five, and was declined by a branch the flag never
touched. **The log line printed a true fact that was not the cause.** It prints
`names_a_place(question)` unconditionally, so it could not have revealed whether the flag was
honoured even in principle.

* **Falsify the gate before moving it:** call the decision function directly with the flag set and
  check the return. Four lines. It would have cost less than the thirteen tests written for a fix
  that did nothing.
* A diagnostic that reports *inputs* cannot distinguish the condition that fired from a condition
  that merely held. Log the branch taken, not the values available to it.
* The test that now matters most in that file asserts **the premise**: that the question parses,
  so `wants_lane`'s summary case is unreachable for it. If that ever stops being true, the second
  half of the fix is dead code and the test says so.

## #147 — A memory feature can be inert at BOTH ends, and each end reports the other as healthy (2026-09-29)

W5-01 asked for a rolling session summary and W5-02 for it to be carried on every entry point.
Reading first (lessons #133, #136) found the feature already built — and broken in four separate
places, none of which any test could see.

    TurnMemoryService constructed:  1 function  (openai_chat_completions)
    save_turn called:              2 sites     (both inside it)
    get_older_context called:      1 site      (likewise)

* **The write end.** `/chat`, `/chat/stream` and the `/stream` websocket stored no turn at all, so
  their read would have returned `""` forever even if they had had one. Open WebUI uses `/v1`; the
  regression probe uses `/chat`. The feature was live on the endpoint that is demonstrated and
  absent from the endpoint that is measured.
* **The read end.** `/v1` built its block and prepended it as a `system` message at index 0. Nothing
  in `orchestrator/` matches on `role == "system"`, and both readers of `state.messages` take the
  **last** five or six entries. A block at index 0 is dropped by every reader as soon as the
  conversation is longer than three turns — which is exactly when long-term memory is the point.
* **The window.** `OFFSET 20 LIMIT 30` drops turns 1-10 at turn 60, which is the acceptance
  criterion verbatim, failing by construction.
* **The units.** `skip_recent=CONVERSATION_MAX_MESSAGES` passes a count of MESSAGES where an offset
  in TURNS is wanted, while the raw history that reaches a prompt is six messages — three turns.
  Turns 4 through 20 were in neither window.

Each half reports the other as fine. An empty read looks like "no history yet". An unread injection
looks like a successful injection. **A feature with a producer and a consumer needs one test that
crosses the boundary** — here, sixteen that drive the real routes and assert what the *workflow was
handed*, not what `main.py` says.

And the same shape, one file up: BUG-655 was `prune_inherited` running on `/v1` only. Its comment
says *"four routes, one helper, because a copy per route is how three of them came to be missing
it."* That was written four weeks ago in the same file, about the same four routes, and the memory
feature had the identical hole at the same moment. **Reading the comment above the code you are
about to extend is cheaper than rediscovering what it says.**

## #148 — A remembered number is a fabrication, and a test had pinned it as correct (2026-09-29)

`get_older_context` carried `result_summary[:150]` per older turn into the prompt, and
`_extract_result_summary` fills `result_summary` from the analytics lane's `formatted_response` —
the answer, verbatim, measurements included. The existing test *required* it:

    assert "22.3" in ctx          # row: "Room 5.02: 22.3 deg C current reading"

So a figure produced twenty turns earlier was reinjected with no time basis and no statement that it
was stale, one paraphrase away from being restated as current. Design contract #4.

* **Redaction is the second line, not the first.** A redactor can have a hole. The structure cannot:
  `TurnNote` has no field for the answer, and the only thing an answer may contribute is one token
  from a closed three-word vocabulary. The test that matters asserts the *dataclass shape*.
* **The hole was there.** `_CLAIM_NUMBER` was `\d{1,3}(?:,\d{3})*`, so a fourth digit needed a comma:
  `1,240 ppm` was a measurement and `1200 ppm` was not (BUG-904). That is the commonest CO2 value in
  this building, and `publication_gate.evaluate` publishes anything it finds no claim in — so an
  unverified four-digit reading went out unchanged on a FAILED verification, which is the one thing
  that module exists to prevent. Every fixture in the gate's own tests wrote the separator.
* **A guard's tests inherit its blind spot when they are written from the same intuition as the
  guard.** This one was found by a different feature feeding it plain integers.

## #149 — Identical filler questions make a memory probe measure nothing, silently and fast (2026-09-29)

The session-summary work (W5-01/W5-02) shipped with 64 offline tests and no live conversation,
so I wrote a probe: name a room in turn 1, ask six filler questions, then ask a question only
turn 1 can answer. The filler was `f"What is the temperature on floor {i % 5}?"`.

Second run, the filler turns came back in **0.0, 0.0, 0.0, 0.0, 0.0, 0.1 seconds**. They were
`resp_cache` hits from the first run. A cached answer is returned *before the workflow runs*,
so those turns never reached the classifier, never reached a lane, and — the part that matters —
**never saved a turn to `turn_memory`**. The probe built a conversation of length two and then
asked it to remember across eight.

* **A probe whose steps can be cached measures the cache.** BUG-662 already says flush before
  every probe run; this is the sharper form — flushing is not enough if the probe reuses its own
  questions across runs. Make every step unique per run (a timestamp in the text is enough).
* **The tell is the timing, and it is easy to skim past.** 0.0 s next to a question that took
  31 s the run before is not a speed-up, it is a turn that did not happen.
* Anything that short-circuits ahead of the pipeline — a response cache, a decline gate, a
  template — removes the side effects of the stages it skips, not just their cost. When a
  feature's whole job IS a side effect (saving a turn, updating a summary), a short-circuit
  upstream turns it off without any component reporting a fault.

## #150 — Re-keying a cache does not move the work above it (2026-09-29)

BUG-889 fixed a classifier cache that hit 0 times in 38 calls, by keying it on the decision's
real inputs — the question, the building, the persona. Verified: 2 hits in 1 call. What that
did NOT do is change *where the lookup sits*.

`detect_intent` still runs, in order: a GraphDB RAG fetch, a conversation-summarisation LLM
call, message pruning, and an 18k-character prompt build — and only then computes a cache key
that depends on **none of them** and returns. Measured by the latency agent on a question that
hit the cache in all four rounds: dialogue stage 9.5 / 10.4 / 8.8 / 10.6 s, of which the RAG
fetch alone is 4.27 s. Every cache hit paid full price for work it threw away, and the fix that
made hits possible is what made that visible.

* **A cache lookup belongs immediately after its key's last input**, not wherever the value
  happens to be needed. If the key is cheap and the lookup is late, the hit rate is irrelevant
  to the cost.
* Making a broken cache work can *reveal* a cost without reducing it, and the metric that
  improves ("hit rate") is not the metric anyone cares about ("time").
* **Moving it is not free, and that is the real lesson.** The skipped block also assigns
  `state.summary`, which a second reader in `_orchestrator.py` uses. A lookup moved above a
  side effect silently stops that side effect happening on the hot path. Find every reader
  before moving it — two greps, and the second one is the one that bites.

## #151 — A source-reading test that pins a SUBSTRING pins the formatter too (2026-09-29)

Three assertions broke today without a single behaviour changing, all the same way.

`test_the_hook_is_wired_into_the_response_node` asserts that `_orchestrator.py` contains
`"absence_second_chance import apply_to_answer"`. The hook was wired the whole time — the
import is there, `_second_chance` is called — but `black` wrapped the import:

```python
from orchestrator.services.absence_second_chance import (
    apply_to_answer as _second_chance,
)
```

and the substring stopped being contiguous. My own two were the same shape: one assertion
windowed at `block[:600]`, then `[:1200]`, broke twice as the explanatory comment above the
code grew, which tells you nothing about the code.

Source-reading tests are worth having in this repo — they are how `_TRACE_STAGE_MARKERS` and
`analytics_output` were finally caught. But:

* **Assert on whitespace-normalised text** (`" ".join(source.split())`) unless the layout is
  the point. A formatter is allowed to reflow anything.
* **Never window by character count.** `block[:1200]` is a bet on how much prose precedes the
  code. Slice to the next structural boundary, or search the whole block.
* If an assertion fails, check whether the BEHAVIOUR moved before changing the code. Here it
  had not, three times out of three, and "fixing" the source to satisfy the string would have
  been the wrong direction entirely.

## #152 — The same suite ran 67 minutes and then 16, on the same work (2026-09-29)

`pytest -m unit`, twice on one evening, no meaningful change between them:

    12,879 passed / 3 failed    1h07m15s
    12,905 passed / 1 failed    16m21s

The first ran while an eight-turn live probe held the stack and a single turn took 3,102
seconds (CAVEAT-942); the second ran alone. Same tree, four times the wall clock. This is
CAVEAT-500's shape for the third recorded time, and the standing instruction holds: **do not
quote a suite duration as a property.**

The failure counts differ too, and that matters more. All three of the first run's failures
were in one new file, passed 11/11 alone and 226/226 in a slice, and **did not recur** in the
second run. They were order-dependent flakiness, not defects — and the captured output held
only its tail, so the tracebacks were lost and an hour was nearly spent chasing a hypothesis
(a leaked `time` patch) that a two-minute grep disproved. **Redirect a long run through `tee`,
not `>`**, so a failure that does not recur still leaves its evidence behind.

## #153 — A guard test that fails your fix is doing its job; do not edit it to suit you (2026-09-29)

Hand-reading tail M found seven false declines, and one had a beautifully small cause: the
register term matcher compiles `\b<term>\b`, so a trailing "s" ends the match.

    "what is the escalation route"    -> Department (32.0)
    "what are the escalation routes"  -> NOTHING RANKS

The Department register declares "escalation route", "duty officer", "who do i contact" and
"out of hours". It is well written for the question that failed. One character defeated it,
and people write plurals constantly, so the cost is far more than the question that exposed it.

The fix is obvious and I wrote it, and it was wrong twice:

* `(?:e?s)?` on every term broke **two tests that exist for exactly this**. "A lift is
  officially unavailable. Which bookings no longer have a verified route…?" began ranking
  `WorkspaceProfile` — which `test_the_terms_rejected_for_over_capture_stay_rejected` rejects
  **by name**, from a measurement someone already made.
* Narrowing it to multi-word terms took 6 failures to 5. The over-capture survived.

The tempting third move is to update the guard tests. **That is overriding a measured decision
with an unmeasured one.** Those names are in the test because someone watched the system answer
the wrong thing. Over-capture is the worse direction here (BUG-893), so the trade on offer was a
known false decline for an unknown wrong answer — which is not an improvement, it is a
different defect with less evidence behind it.

* **Revert, and log the attempt.** BUG-948 now carries the reproduction, both failed
  approaches and the reason each failed. The next session starts where this one stopped instead
  of re-deriving it.
* The most useful thing the failures revealed was incidental:
  `test_precompiled_scores_equal_the_inline_scorer` also went red, so **there are two scorers**
  pinned to agree, and any real fix has to change both. I would not have found that by reading.
* A harness that cannot reach the data looks exactly like the defect. From the host,
  `record_classes()` returns **0** held classes because GraphDB resolves to a container
  hostname — the same "NOTHING RANKS" symptom, for an entirely unrelated reason. Run the probe
  where the code runs.

## #154 — Two gates, and widening one looks like a fix if you only check the route (2026-09-30)

"What kind of data is collected?" is the first question anyone asks a system like this, and it
declined: *"I don't have that specific information on record for Abacws Building. For
building-specific queries please contact your building's facilities / estates management team.
Abacws Building does keep Waste collection point records, which I can read for you."*

The system holds 44 record classes and 45 measured modalities, and the reach lane answers "what
can you measure in this building?" by naming every one.

The gap was one verb. `CAN_MEASURE_RE` alternates over measure|monitor|track|sense|detect|read|
report|tell me, with no "collect", and the passive "what kind of data IS COLLECTED" names no
actor at all. I added it, restarted, and asked. The route was right — `intent=observability` —
and the answer was **"Which space did you mean?"**, because the branch that lists the
building's measurands is gated on a *different* pattern, `OPEN_QUESTION_RE`.

Had I checked only the route, I would have logged this fixed. It was better than the false
decline it replaced and still not the answer the system had.

* **When a lane has an entry test and an internal branch test, a vocabulary fix needs both.**
  Grep for every gate between the question and the sentence you want, not just the first.
* **Ask the question. Every time.** The route, the log line and the tests all agreed with me.
  Only the answer disagreed.
* The narrowing that made it safe is worth copying: "collect" is also what happens to WASTE
  here — 24 collection points and a schedule — so `collect` is admitted only as a verb the asker
  attributes to the SYSTEM ("do you collect"), and every added alternative keeps the word "data"
  in it. **A widening needs a negative case list as much as a positive one**, and "when is the
  recycling collected?" answering from the waste register is now pinned by a test.

## #155 — A ranking that ties falls back to alphabetical, and nobody reads it as alphabetical (2026-09-30)

`"why is pl 2.5 increasing"` declined with *"the nearest things I can answer are … the readings
of air quality, carbon monoxide, co2 and damper position."*

Those are the first four modalities in alphabetical order. The building holds **210 PM2.5
sensors**, and the resolver had already identified the measurand — the same sentence prints
**PM2.5** in bold. Nothing in the question overlapped anything, every score tied, and
`nearest_holdings` breaks ties on the building's own order.

* **A tie-break is a silent claim.** "Nearest" that degenerates to "first" tells the reader the
  opposite of the truth, and there is no way to see it from the answer. If a ranking can tie
  across the whole set, say so or order by something the reader would accept.
* **The asker's words are not the building's** — that is the whole reason a resolver exists, and
  then the resolver's output was not passed to the ranking that needed it most. Look for the
  place that already knows the answer before adding a way to work it out.
* `_close("pm2.5", "pm25")` was False. **Punctuation made a measurand unrecognisable as
  itself.** PM2.5, PM 2.5, pm-2.5 and pm25 are one thing; NO2, CO2 and PM10 are waiting to be
  the same bug.

## #156 — Narrowing a window correctly can break a downstream rule that depended on it being too wide (2026-09-30)

`"Compare energy use this week against last week"` fetched a fixed 30 days, which the
per-sensor row cap then cut to the newest **12.1 days** (measured against `sensordb.energy_data`
with the session pinned to `+00:00`: 1,000 rows per meter reaches back to 18 September, out of
7,455 rows in the 30 days). The obvious fix is to fetch the two weeks named.

That fix breaks the answer. `series_summary._bucket_size` chooses its bucket unit from the span
of the **rows**, and needs 1.5 units before it will bucket by that unit. Two weeks, ending at
NOW because rows cannot reach further, is **9.2 days on a Wednesday** — under the 10.5 days the
rule requires. So the comparison would have been bucketed by DAY and computed between two
partial days, which is the 291.7% rise BUG-936's fix exists to prevent. The over-wide fetch was
accidentally satisfying a threshold, and the correct window removed the accident.

* **Before narrowing a window, find out who measures it downstream.** The wrong window was load
  bearing. Nothing said so, and the three tests that would have caught the regression were about
  bucketing, not about fetching.
* The margin that fixes it (reach one whole period further back, so the span is always at least
  two units and two clears 1.5 for every unit and every weekday) is now **pinned by a test that
  calls `_bucket_size` on the span the new bounds produce**, nine (question, unit, weekday)
  combinations. An accidental dependency you have found is a dependency you can assert.
* The same shape appeared twice more in one session: a calendar boundary computed on the
  **store's** clock. `time_windows` matches "overnight" as `HOUR(datetime) >= 22` over a UTC
  column, and `series_summary._bucket_of` labels ISO weeks from the stored stamp. Both are an
  hour out for a building on UTC+1, and the fix for one is the fix for all three.

## #157 — A marker on the bus with one reader is not a disclosure (2026-09-30)

`rows_capped` has been written by the SQL lane since BUG-479, with a comment explaining that
"whoever states a count must be able to see that it is capped". Exactly **one** module ever read
it: `report_agent`. Grepped 2026-09-30.

So every other answer narrated the cap as completeness, and one said so in as many words:
*"The most recent reading … was 23.1 °C. **Across all 1,000 readings** taken between 21 Sep
21:36 …"* — from a turn whose log carries
`[sql] group temperature_data returned exactly its 1000-row limit — the set is TRUNCATED and its
size is not a count of what exists`, two lines above.

* **Recording a fact is half a disclosure; the other half is an appender on the path the reader's
  text actually takes.** The sentence was written into the SQL lane's own `formatted_response`,
  which is only shown when that prose WINS the response dispatch. The observed failure came from
  the narration, where it never appeared. The window-substitution disclosure already knew this:
  it is appended **twice**, once in the lane and once in `_response_node`, guarded on the note's
  own text.
* **A fail-open component needs a count of how often it acted** (lesson #126) has a twin: a
  marker needs a count of how many lanes read it. One reader for four years looks identical to
  none.

## #158 — Two answers wrong by the same factor on the same quantity need not share a cause (2026-09-30)

BUG-954 said "two rooms are occupied" against a store with ~380 non-zero occupancy series.
BUG-898 said a seminar room held 4,401.86 occupants. Same quantity, same order of magnitude,
logged a day apart. The obvious move is to look for one cause. There were two, and they are not
related:

* **BUG-954** — the aggregate lane *declined*. `parse_intent` needs a statistic word and
  "occupied" is not one, so `wants_lane` returned None and the count fell to the narrator, which
  named the five rooms it could list under a headline of five, **beside its own statistics saying
  131 of 234 read zero**. Every figure it quoted was real and correctly fetched. Only the headline
  was invented.
* **BUG-898** — the analytics template read `/app/outputs/data/current_data.json`, a file in the
  code-executor last written **2025-12-17**, holding 119 rows of an *oxygen* sensor. The rows the
  turn actually fetched were handed to the same code as `raw_data_json` and never looked at.

What separated them was one measurement that cost nothing: **ask the question twice and compare
the digits.** BUG-898 came back byte-identical to two decimal places a day later, on a series
written to every minute. A model inventing a number does not repeat it; a file does. BUG-954's
figures moved between asks, which is what a real fetch with a bad headline looks like.

* **Repeatability is the cheapest discriminator between a fabrication and a stale read**, and it
  is one extra ask. Run it before building a theory.
* **A shared default filename is a shared mutable global with none of the warnings.** The default
  was `current_data.json`; one caller wrote a per-conversation file and another wrote nothing, so
  the second read whatever the last process left. It survived nine months because a plausible
  number is not a crash.
* **When a figure has a denominator, measure the denominator before the figure.** "234" and "467"
  looked like symptoms of the same confusion. They are the count of *spaces* with an occupancy
  series and the count of *series placed in a space* — both correct, both correctly fetched, and
  neither one the thing being counted. lesson #139's rule applies to diagnosis as well as to
  answers.

## #159 — `from X import y` binds the object, so a reload detaches every prior importer (2026-09-30)

Three tests passed alone, passed in a 42-test pair, and failed in the full 13,000-test suite:
they patched `settings.OUTPUT_DATA_DIR` to a `tmp_path` and the product wrote to the real
output directory anyway.

`tests/test_strict_secrets.py` calls `importlib.reload(shared.config)` — correctly; it is
testing boot-time validation. Demonstrated directly rather than inferred:

    analytics_agent.settings is shared.config.settings   before reload: True
    analytics_agent.settings is shared.config.settings   AFTER  reload: False

Every module that did `from shared.config import settings` at import time still holds the OLD
object. A test that then imports `settings` fresh and patches it is patching something the
product no longer reads.

* **Patch where it is used, not where it is defined.**
  `monkeypatch.setattr(module_under_test.settings, "FIELD", value)` patches whatever object that
  module currently holds, and is right whether or not a reload has happened.
* **The three that FAILED were the lucky ones.** A patch that silently does nothing usually
  leaves the test running against the REAL setting, which often still satisfies the assertion —
  a vacuous pass. **25 such patch sites across 8 files are unaudited.** For each the question is:
  does the assertion still hold when the patch does nothing? If yes it proves nothing; if no it
  is order-dependent and will fail the day the suite reorders.
* This is the third time in two days that the apparatus was the bug — five memory tests pinning a
  parameter their own fake ignored (CAVEAT-1025), a grader gate passing the regression that
  decided a freeze (BUG-987), and now this. **When a test fails only in a full run, suspect the
  test before the code**, and when it passes only in a full run, suspect it harder.

## #160 — A metric can be arithmetically correct and structurally blind (2026-09-30)

BUG-531 sat open as the project's only P1 for eighteen days with a note attached saying the
fan-out metric "reads 1.00 throughout, because each reference has its own uuid". That sentence
is *true*, and it is why the bug survived: fan-out counts **copies per UUID**, and 71 sensors
each carrying two references to two *different* uuids scores a perfect 1.00. The metric was
answering "is any series duplicated?" while the question was "does any sensor resolve to more
than one series?" — a different question about a different object.

The query that finds it in one line is a count of **distinct uuids per subject**:

```sparql
SELECT ?s (COUNT(DISTINCT ?u) AS ?n) WHERE { ?s ?p ?r . ?r ref:hasTimeseriesId ?u } GROUP BY ?s
```

`{1: 3473, 2: 71}` before, `{1: 3544, 2: 0}` after. **Before trusting a green metric, say out
loud what it counts and what you wanted counted.** If those are different sentences, the metric
cannot clear the thing you are worried about — no matter how long it has been green.

## #161 — Bind a variable for a relation your data spells more than one way (2026-09-30)

The linker asked `FILTER NOT EXISTS { ?p ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?u }`.
This one building spells that relation **three** ways: `ref:hasExternalReference` (3,515 triples),
`ashrae:hasExternalReference` (3,640) and `brick:hasExternalReference` (2). So 71 points that
carried only a non-`ref:` form looked unlinked, and the script gave each a second series in a
different store. Same shape as BUG-481: a query blind to a predicate that is in active use.

The fix is not a list of two predicates — that only waits for a fourth. It is to ask what
"linked" **means**: `FILTER NOT EXISTS { ?p ?anyRefPred ?r . ?r ref:hasTimeseriesId ?u }`.
Reaching a timeseries id is the property that matters; which predicate got you there is not.

## #162 — A balance check proves you did what you intended, not that the intention was whole (2026-09-30)

The removal script printed `retired 70 of 70 — BALANCED` and it was telling the truth. The graph
then reported **1** remaining duplicate, not 0. The target list had been built by intersecting
the duplicated sensors with the linker's output file, so it could only ever contain duplicates
*the linker created* — and one of the 71 had been created by something else. The list was 70 of
71 **by construction**, and every internal check agreed with it because they were all derived
from the same list.

**Close the loop against the world, not against your input.** The balance check was worth having
— it caught an earlier run that removed 38 blocks for a delta of 37 — but only the re-query said
the job was incomplete. A self-consistent script is consistent with its own premise.

Two smaller things from the same hour, both cheap to re-learn the hard way:

* **A room number contains a dot.** `bldg:<name>[^.]*?ashrae:hasExternalReference` silently
  failed on 32 of 70 subjects because they carry `brick:isPartOf bldg:Room1.25`, and `[^.]`
  cannot cross that. One match ran past its own subject. Parse TTL structurally.
* **Read the CSV header before writing the CSV.** Inventing two column names made
  `csv.DictWriter` raise *after* it had written every real row; the tracker survived only
  because the bad row happened to be last.

## #163 — I had it backwards until I measured, and the measurement took two minutes (2026-09-30)

Retiring one of two duplicate references means choosing which survives. The story was obvious:
`bldg1_enhancements.ttl` authored these points, `link_unlinked_sensors.py` came later and added
a second series it had no business adding, so the linker's additions are the intruders and go.

The data says the exact reverse. All 71 pre-existing references stopped being written on
2026-09-16 (328 hours stale); all 71 of the linker's twins were being written within the minute;
and the 37 references on the same store that have **no** twin are 36/37 live, so the store was
never the problem. Retiring the "intruders" would have replaced 71 live series with 71 dead ones
and called it a fix for a P1.

The check was one `MAX(Datetime)` per uuid. **When a fix requires choosing between two things
that both look plausible, the cost of asking which one is alive is almost always smaller than
the cost of guessing** — and a plausible history is not evidence about the present.

## #164 — A harness that cannot authenticate looks exactly like a stack that is down (2026-09-30)

I re-ran the 51-case gate after a restart and it produced nothing: no output, and — the part
that misled me — **zero requests in the orchestrator log**. Health returned 200. My first
reading was that the restart had broken the endpoint, which would have been a serious
regression from the change I had just made to the ontology.

It was the invocation. `scripts/regression_answerability.py` takes `--token` and **defaults it
to the empty string**, while `/v1/chat/completions` is gated by `_oai_auth`, which accepts only
a non-default `PIPELINE_API_KEY`. Every question returned `{"detail":"Invalid API key"}` in
milliseconds, so nothing reached a lane and nothing was logged as a turn. Supplying the key
made case 1 pass in 185 s.

Two things worth keeping:

* **A 401 at the door produces the same silence as a dead service**, because the request never
  reaches the code that logs. When a harness goes quiet, check the *response body* of one call
  by hand before concluding anything about the system. `curl` with no `Authorization` header
  and `curl` with `Authorization: Bearer ` return **different** errors — "Missing Authorization
  header" versus "Invalid API key" — and that difference is the whole diagnosis.
* **Run one case before running fifty-one.** `--only 1` would have shown this in three minutes
  instead of forty, and the same applies to any long harness with a default that can be wrong.

Related: I also started `capture_golden_baseline.py` believing it produced the gate's set. It
walks the full 2,960-question catalogue — 16 rows in about forty minutes. **Check what a
harness enumerates before you wait on it**, especially when a smaller harness with a similar
name exists.

## #165 — A harness that times out creates the contention that times out the next case (2026-09-30)

The regression gate recorded case 9 of 51 as `REGRESSED  answered -> empty  420.0s`. The number
is the diagnosis: **420.0 is the harness's own `--timeout` default**, to the tenth of a second.
The system had not failed. The orchestrator was still working on that turn thirteen minutes
after the harness had given up on it, and its log shows where the time went — one
`coverage_audit` step enumerating **39,119 located points over 13m15s**.

Two things follow, and the second is the one I had not thought about.

**A verdict whose elapsed time equals the timeout is a timeout.** Read the seconds column
before believing the verdict. A regression and an abandonment look identical in a pass/fail
table and are opposite findings — one says the system got worse, the other says the harness got
impatient.

**Abandonment is not cancellation, and on a single-slot runner that compounds.**
`OLLAMA_NUM_PARALLEL=1`, so the local model serves one request at a time. When the client walks
away the turn keeps running and keeps the slot, so the *next* case starts behind it and is more
likely to time out too — which leaves more abandoned work, and so on. **A run that degrades case
by case may be measuring that feedback loop rather than anything about the cases.** I stopped the
run at 9/51 rather than collect verdicts produced under it.

The control that makes all of this legible already existed and I had it: the same 51 cases, same
build, **earlier the same day — median 30.3 s, max 108.1 s, 27.8 minutes total.** Against that,
#12 going 48.3 s → 3,412 s and #13 going 28.1 s → timeout are obviously environmental. Without
it I would have spent the afternoon looking for a regression in an ontology change that removes
triples. **Keep the previous run's timings, not just its pass count** — a pass count cannot tell
you the machine changed underneath you.

Corollary for this repo: **run the gate alone.** Not as hygiene — its verdicts, not merely its
latencies, are unreliable with a unit suite or agents sharing the host.

## #166 — A range over a series' whole life is not a statement about the series now (2026-09-30)

I logged BUG-1150 after measuring a booking-status point at "0..189.48, mean 9.38" against a
label reading "available=0 / booked=1". Both numbers are real. Both are useless for the claim I
made with them, which was that the point is *currently* carrying the wrong quantity.

Broken down by day, the same uuid reads:

```
days with any value > 1 : 26, first 2026-08-22, last 2026-09-16
LAST 48 HOURS           : 1,088 rows, 0 above 1, range 0.000..1.000
```

A dated block of bad history, ending at the instant the publish map was regenerated — not a live
defect. The aggregate hid the boundary because **an aggregate over an interval that spans a
change describes neither side of it.** I had written exactly this failure into BUG-936 nine days
earlier (a comparison silently drifting to the wrong two weeks) and then made its mirror image.

**When a measurement supports a claim in the present tense, measure the present.** Group by day
before quoting a range; if the daily rows fall into eras, the eras *are* the finding. And it
cost nothing — the per-day query took one round trip and turned a P2 "live wrong quantity" into
a P3 "dated block, already stopped, do not re-seed."

The same row was wrong a second way, and it is the older lesson: I inferred the class-to-modality
mapping **from the values I saw** rather than asking the mapper. One call to the script's own
`class_to_modality()` returns `Occupancy_Status -> occupancy_status` (profile `binary: 1`), so
the component I blamed had always been right. **Ask the running system what it does before
writing down what it does** (#133, #136) — including when the data seems to prove it for you,
because data downstream of four writers over two months proves nothing about any one of them.

## #167 — Measure the process before you explain its behaviour (2026-09-30)

I spent an afternoon explaining why one LLM call took 3,239 seconds. I eliminated, with real
evidence: runaway generation (the completion was 385 characters), a retry storm (one POST),
machine sleep (Kernel-Power showed a 13-second suspend, an hour later), a host-wide freeze (the
data-publisher wrote rows in 55 of the 75 minutes), CPU starvation (nothing else was running),
and a missing async path (`_agenerate` is native). I wrote a careful P1 saying the mechanism was
undetermined and listing what it was not.

Then the orchestrator stopped answering, and I measured it:

```
CPU 3210.31%              MEM 40.02 GiB / 46.64 GiB
docker ps: "Up 3 hours (healthy)"
after restart:            1.33 GiB, 6.4%
```

**Every candidate I eliminated was about the request. None was about the process making it.** An
event loop on a machine at 86% memory may never reach its timer callbacks, which explains a
180-second `asyncio.wait_for` not firing without anything being wrong with the timeout code or
with the model server. It was the cheapest available explanation and I never tested it, because
`docker ps` said `healthy` and I believed it.

**The health status was frozen.** The check had stopped completing, so the last PASS simply
stayed, and `docker ps` renders a stale PASS identically to a fresh one. The tell is in
`docker inspect`: `FailingStreak: 2` beside `Status: healthy`, with `last check` an hour old.

Three rules, in the order they would have saved time:

1. **`docker stats` before `docker logs`** when something is slow or unresponsive. One command,
   and it would have reframed the day.
2. **Sample resource use alongside every gate or probe run.** Latency numbers are not
   interpretable without it — this is CAVEAT-500's complaint with a mechanism attached at last.
3. **A first error can be a symptom of something three layers away.** The visible failure was
   `Login Postgres probe failed: TimeoutError`, and Postgres was healthy on 42 MiB. Exactly
   BUG-481's shape — "concept resolve failed" for an AttributeError two calls away. A timeout
   names the thing that was waited on, never the thing that was wrong.

## #168 — A performance number measured on a sick process will size your fix wrong (2026-09-30)

I logged BUG-1192 after measuring `coverage_audit` at **13m15s to enumerate 39,119 located
points** inside one turn, and proposed bounding the candidate set: a seat-choice question does
not need all 39,119 points. Reasonable, and it would have shipped.

Re-measured on a healthy process, same graph, same 39,119 points, no code change:

```
10.6 s     14.7 s     17.8 s
```

**~75x.** The enumeration was never expensive; the process was — a container at 40 GiB and
3210% CPU (BUG-1194). Had I bounded the scan, the bound would have been sized from a degraded
process, shipped, and then been **credited with a 75x speedup that was really a restart.** The
next person would have inherited a number nobody could reproduce and a design constraint nobody
could justify.

This is CAVEAT-500's rule — never quote a duration as a property — but one level deeper, because
the duration here wasn't in a report, it was about to become a *design decision*. The same
suspicion is now owed to CAVEAT-942's 3,102 s and to every latency figure taken during that
window.

**Before optimising anything, measure the process, then measure the thing.** `docker stats`
costs one command. And when a row already contains its own counter-evidence — mine said "the
earlier run's numbers show the lane can do this work in seconds" — that sentence is the finding,
not a caveat to note and move past.

Corollary, from the same session: two independent `asyncio.wait_for` deadlines — the 180 s LLM
timeout and the 420 s workflow deadline, nested — were **both silent on the same 3,412 s turn**.
One `wait_for` failing is a bug worth hunting. Two failing together is not two bugs; it is
evidence about the loop they both depend on.

## #169 — Typing a flag is not evidence the flag was used (2026-09-30)

I ran a 60-question quality measurement and reported it as "asked as
facility01@example.com (facility_manager)". It was asked as **`admin@ontosage`, on a different
endpoint**. `scripts/ask_questions.py` reads `--email` only inside its `if args.v1:` branch;
without `--v1` the flag is parsed and silently discarded, and the script authenticates through
`capture_golden_baseline._login()`, whose docstring is *"Session token for /chat"* and whose
credentials are `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

So the measurement described **`/chat` as an admin**. Real users get **`/v1/chat/completions`
as a non-admin, streaming**. Two differences at once, in the number I had just offered as the
basis for a release decision.

What makes this worth writing down is what I *did* check. I verified the container had not
restarted mid-run (captured `StartedAt` before and after), that the question corpus was the real
survey rather than our own synthesised catalogue, that the draw excluded every spent tail, and
that the process was healthy throughout. **I never checked who the harness logged in as** —
because I had typed the flag, and a typed flag feels like a configured fact.

Three rules:

- **An argument parser that accepts a flag is not an argument parser that honours it.** A CLI
  can take `--email`, validate it, print it back, and use it in one branch of two. Read the
  branch.
- **Confirm identity from the SERVER's log, not the client's command.** The orchestrator prints
  `[forwarded-user] '<email>' → '<user>' (role=<role>)` on every `/v1` turn. That line is
  evidence; the shell history is not.
- **Role changes the answer, so it is part of the measurement.** Five of the twenty-eight
  failures were an admin being shown how to onboard data — correct behaviour for that reader,
  and not a defect at all for anyone else. The number moved from 46.7% to 38.3% on that alone.

Same family as #145 (verified with a query the code does not send) and #153's harness lessons:
**the apparatus was the bug, for the ninth time in this project.** The finding that survived
untouched is the one that never depended on the apparatus — zero fabricated figures.

## #170 — One word in a keyword list swallowed 3.8% of everything real users ask (2026-09-30)

"What is the average sound level?" was answered *"I couldn't answer that from Abacws Building's
records"* — about a building holding 235 sound sensors. Six lines of container log give the
whole thing:

```
[sparql] class from HBCO concept 'noisy': ontosage:Sound_Level_Sensor   <- 233 instances
Using template SPARQL (entities=[]):
  SELECT ?floor ?label WHERE { ?floor a brick:Floor ... }
GraphDB query returned 8 results                                        <- eight FLOORS
[analytics] No UUIDs found - no specific sensor type detected           <- it WAS detected
[response] relevance gate replaced a analytics answer: OFF_TOPIC
```

`floor_words = [..., "level", "levels"]`, and **"sound LEVEL" matched it.** The branch that
fired never looked at `concept_class` — which is passed into the same function and had been
resolved and logged one line earlier.

**Measured before changing anything: 284 questions say "<quantity> level(s)", 269 of them in the
real survey corpus — 3.8% of everything 96 participants asked. That corpus contains zero
"level <n>" storey questions.** A single word in a six-item list was eating a twenty-fifth of
real usage, and it had been there long enough that nobody questioned it.

Three things worth carrying:

**Key the fix on the resolved thing, not on more words.** A stop-list ("sound level", "VOC
level", …) needs extending for every quantity and still misses the lay terms — "noisy",
"stuffy" — that the concept resolver exists to handle. The class was already computed, already
passed in, and merely ignored. Using it also freed "Which floor is the warmest?", which nobody
had reported.

**A resolved value that is logged and then discarded is the easiest defect to miss.** The log
line `class from HBCO concept 'noisy': ontosage:Sound_Level_Sensor` reads like success. It is
the last moment that information exists. Whenever you see a resolution logged, ask what consumes
it — the answer here was "nothing".

**The guard was right for the third time today.** Eight floors genuinely do not answer a question
about sound, and the relevance gate rejecting it was correct. Three separate investigations this
session ended with "the gate is the messenger; the defect is upstream". **When a guard keeps
firing, the hypothesis to test is that it is right** — twice I set out to fix the guard and both
times the evidence sent me upstream instead.

And my own two wrong hypotheses, both killed by one query: that the concept had resolved into
the wrong namespace (`ontosage:` vs `brick:` — it had not, 233 instances), and that the wording
fix I had already shipped was the cure (it was not; it fixed a real false-absence path this
question never reached). **Check the cheap thing first: does the class the log names actually
have instances?**

## #171 — I read a quality measurement off a terminal that was cutting every answer at 400 characters (2026-09-30)

I hand-read 60 live answers to decide whether this system is fit for users, and labelled them
from `ask_questions.py`'s stdout. That line is:

```python
print("   " + answer[: args.show].replace("\n", "\n   "))   # --show defaults to 400
```

**The maximum answer length in my own log is exactly 400.** Twenty-two of the sixty sat at that
boundary. At least one label was wrong because of it: "Can the building harvest rainwater?" I
marked WEIRD — "a sustainability blurb, none of which is rainwater" — and the full answer is 649
characters ending *"(6) Rainwater harvesting for toilet flushing"*. The deciding clause was at
character 450.

**The full text was in the harness the whole time.** `rows` carries it and writes it to
`{--out}.jsonl` — but only when `--out` is passed, and I did not pass it. So the evidence was
constructed, held in memory, and discarded, because a flag has to be remembered.

Three things:

- **A flag that must be remembered to avoid losing evidence will be forgotten.** Fixed by always
  writing the full answers, to a temp path when `--out` is absent, and printing the destination.
  Preserving data should not be opt-in.
- **State your instrument's limits by MEASURING them, not by estimating.** I did flag truncation
  — as "roughly ten of the longer answers". It was 22. I underestimated my own known limitation
  by more than half, in the same breath as claiming to be careful about it.
- **A length distribution that piles up on a round number is a truncation, not a property of the
  data.** `max = 400` with 22 answers in the 380–402 band should have been visible the moment I
  looked at the numbers instead of the text.

This is the fourth correction to ONE measurement: the identity it ran as (#169), the cause of its
largest cluster (#170's neighbours), the tense of one of its findings (#166), and now the text I
read. **The system under test was never the least reliable thing in the room.** The one finding
that has survived every correction is the one that never depended on the apparatus: zero
fabricated figures.

## #172 — Quote lift, never precision: a bucket is easy to hit where its class is common (2026-09-30)

CLAUDE.md said, for two weeks, *"Only the WEIRD bucket is trustworthy (89.1% precision)."* The
figure reproduces exactly. It is also **in-sample** — measured on the bank the grader was
calibrated on — and the line never said so.

Audited over 2,868 stored answers and 1,997 hand labels:

| era | WEIRD precision | hand base rate | **lift** | kappa |
|---|---|---|---|---|
| phase0 bank (FITTED) | 89.1% | 67.7% | **+21.4 pp** | +0.314 |
| held-out tails C–L | **35.4%** | 39.7% | **−4.3 pp** | **−0.046** |

GOOD_ANSWER −3.6 pp, GOOD_DECLINE −12.5 pp. **All three buckets carry negative lift out of
sample**, and a kappa of −0.046 is below chance: on the held-out set, picking at random would
beat the grader's WEIRD bucket.

**Precision alone hid it, and the reason generalises: a bucket is easier to hit where its hand
class is common.** 89.1% against a 67.7% base rate is a real +21.4 pp of information. 35.4%
against 39.7% is less than none. Two figures that look an order of magnitude apart in quality
differ by *sign* once you subtract the prior. **Report lift, or report nothing.**

Two more things from the same audit:

- **Four implementations of "is this a decline" agree on nothing.** 0 of 2,868 answers are
  called a decline by all four; 43.1% are contested; one pairwise kappa is negative. The right
  answer was **not** to unify them: measured against hand labels they sit at different points on
  a recall/false-decline trade-off, and three are at the right point for their purpose. One is
  not — `grade_answers_rubric` calls **162 of 535** hand-confirmed *answers* declines, and 128 of
  those rest on a single pattern. **"Four things disagree, so merge them" was the wrong instinct;
  "measure each against ground truth and see which one is wrong" was the right one.**
- **The durable fix is not a better grader.** Nothing the server returns says whether a turn
  declined, so all four classifiers are reading prose and guessing. A lane that recorded its own
  outcome on the bus would make every one of them unnecessary. That was filed months ago
  (CAVEAT-887) and is still unbuilt, while four approximations of it were written.

This sits directly on #20-22 ("the measurement apparatus is usually the bug") and on today's
#169 and #171. The count for this session alone: the identity a measurement ran as, the cause
of its largest cluster, the tense of a finding, the 400-character truncation of the text I read,
and now the in-sample/out-of-sample split of the grader that scored it. **Five defects in the
apparatus; the system under test was never the least reliable thing in the room.**

## #173 — Fabricate a relationship instead of a figure and no guard sees it (2026-10-01)

A question that had been **5 of 5 wrong** — inventing "six active issues" from a static taxonomy,
and once a five-step recovery order telling someone to "Restore power to both chargers" — came
back **0 of 5** after a deterministic guard landed. Decisive, because the pre-fix rate was 100%.

Then two of the five answers said this:

```
ask 1:  DEP-07 -> DEP-05 -> DEP-06 -> DEP-16 -> DEP-03
ask 3:  DEP-05 -> DEP-06 -> DEP-03 -> DEP-07 -> DEP-16
```

Same five records, two different orders, each presented as *the* dependency-aware recovery order.
Checked against the graph: those records carry label, contact, opening hours, status, owner,
version — **no ordering predicate of any kind.** The arrows are the fabrication, and the
disagreement between asks proves the order is arbitrary rather than derived.

**It slipped a guard built for exactly this class of defect, because every family in that guard
matches nouns and verbs, and an arrow is neither.** "Overcrowded", "crowd control", "alert
security", "safe capacity" — all lexical. A relationship asserted with punctuation, or with
"first / then", or with a numbered list, carries no keyword to catch.

Two things follow.

**A relationship is more dangerous than a figure.** A number invites checking — someone asks where
21.4 °C came from. An arrow reads as *structure*, as though the system had consulted a dependency
graph. It is the same contract-#4 violation with better camouflage.

**The fix must be measured before it is written, and this cluster has already proved why twice.**
The obvious rule — "do not emit an ordered list unless the rows carried an order field" — would
hit every legitimate numbered list: a register's fields, a floor list, ranked results with scores.
In the same cluster, BUG-1302's one-line prescription would have cost **26 hand-read GOOD
answers** (including a scripted demo question, on the noun `evacuat\w+`), and the guard's own
first draft **destroyed two correct refusals** because `overcrowd\w*` reads identically inside a
claim and inside its denial.

Which is the third rule, and the one I keep relearning: **a scan can triage, only a reading can
judge.** My own scan counted a refusal as a claim today, having counted a quotation as a claim
yesterday. Both times the answer was fine and the instrument was not.

---

## #174 — A measurement of the stage I changed said nothing about the path the question takes (2026-10-01)

I fixed the capability lane's subject test so that `"What happens during a power outage?"` would
no longer be refused by a preposition. Then I measured the fix over 4,060 questions and the
instrument printed, among its ten gains:

```
'DROPPED'  ->  'ANSWERS:Fire Safety'   'The fire alarm is sounding. What should I do?'
```

I asked it live. The reader got a decline about an overdue weekly test on a control panel,
followed by the model's own generic advice. The route explains why:

```
[ttl-route] metadata via held record class: FireSafetyAsset (30 instances) — skipping LLM intent call
Final intent for routing: metadata
```

**The capability lane never ran.** My measurement replicated `_is_subject` exactly and faithfully
— and `_is_subject` is a function that is only reached if the question gets to that lane. The
instrument answered "would this stage permit the answer?" while I read it as "would the reader get
the answer?" Those are different questions and only one of them matters to a user.

This is #145 one layer out. There I verified a fix with a hand-written SPARQL query that was not
the query the code sent; here I verified a fix with a hand-built replica of a stage that the
question does not reach. Both times the replica was correct. Both times the correctness was
irrelevant.

What makes it insidious is that the measurement was *good*. It covered the whole catalogue, it
printed moves in both directions, it carried the BUG-601 controls with their baseline verdicts, and
it caught a variant that would have shipped a wrong answer. An instrument can be careful, honest,
well-controlled and still be scoped one stage too narrow. Rigour inside the wrong boundary reads
exactly like rigour.

**The rule: a stage measurement predicts a stage. Before quoting it as an outcome, ask the running
system the same question and read the route line.** Where the two disagree, the disagreement is
itself the finding — it was BUG-1393 here, a life-safety question answered with invented
procedure, and I would not have found it by fixing what I set out to fix.

And the cheap version of that rule: my ten "gains" are nine predictions and one verified answer.
Only the power-outage case was asked live. I have written the other nine down as predictions in
BUG-1392, not as results, because the one I did check was wrong.

## #175 — My test passed against a fixture I invented, which is a test of the fixture (2026-10-01)

Writing the regression test for the preposition fix, I needed the fire-safety topic's lay terms.
I typed what they obviously would be:

```python
fire = ["fire", "alarm", "evacuate", "evacuation", "emergency", "escape route"]
assert _is_subject("The fire alarm is sounding. What should I do?", fire)
```

It passed. It would have kept passing forever. The building declares something else —
`bldg1_capabilities.ttl` line 22 lists sixteen phrases including `smoke detector`, `sprinkler`,
`fire warden`, `extinguisher`, `fire door`, `fire suppression` — and my list had neither the
phrases nor the shape of the real one.

As it happens the verdict is the same under both lists, so the test was not *wrong*. It was
**unfalsifiable by the thing it claimed to be about**: edit the TTL to remove every fire term and
my test still goes green, because the data it asserts over lives in the test file. A test like that
cannot fail when the building changes, which is the only time this assertion has any work to do.

This is the same family as the paper's fabricated inter-rater values and invented participant
quotes — not dishonesty, but a plausible stand-in for a real artefact, written because the real
artefact was one grep away and I did not do the grep. The giveaway is identical in both cases: the
fixture reads cleaner than real data ever does. Six tidy terms, no `fire suppression`, no
`muster point`.

**The rule: a fixture that stands in for the building's own declarations must be copied from them,
with the file and line in the docstring.** If it is too long to copy, read it at test time. If it
is read at test time, keep a counterfactual that fails when the file is empty — otherwise an
absent declaration and a satisfied one look the same.

## #176 — The third truncation artefact in two days, and this one I inherited (2026-10-01)

An agent reported a live-visible wording defect: a decline that ended mid-air.

```
Abacws Building does keep
```

A sentence with no register named — exactly the kind of thing a user would photograph. It came
from a real failing test, and the agent had read it off that test's own assertion message:

```python
assert hit, f"Power resilience baseline regressed: {resp.response_text[:200]}"
```

The prefix is 172 characters. `\n\n` makes 174. `"Abacws Building does keep "` is 26. **200.** The
register name begins at character 201. Asking the live stack returned the whole sentence,
correctly terminated: *"…does keep Door and shutter hardware records, which I can read for you."*

Three times now in two days a window has been mistaken for the data: I read sixty quality labels
off a terminal cutting answers at 400 characters (#171), I had to re-read tail N because of it,
and now an agent reported a defect that is a slice boundary. The failure survives being warned
about, because the truncation is in the *instrument's* code and the output looks like prose that
simply stops.

What is different here is that I nearly fixed it. I had `compose_boundary_pointer` open and a
guard half-written for a case that cannot occur — `labels` is filtered on a truthy label and
`and_list` strips, so the only way to render empty is a whitespace-only label, and a probe found
**0 of 44** classes like that. A guard against an impossible state, added to satisfy a
misread, in a module whose whole job is to not say things the data does not support.

**The rule: before fixing text a tool printed, print it again without the tool.** For an answer,
ask the stack and read the whole string. And when a reported string ends suspiciously close to a
round number — 100, 200, 400, 500 — count the characters before reading anything into where it
stops.

## #177 — I measured a new defect against a corpus that predates it, and "rare" was an artefact of that (2026-10-01)

BUG-1391 is a fabricated ordering: five records rendered as `DEP-07 → DEP-05 → DEP-06 → DEP-16 →
DEP-03`, a different order on the next ask, over records carrying no ordering predicate. The row
said to measure the proposed guard over the stored answers before landing it, because numbered
lists are common and most are legitimate. So I did, over 2,861 de-duplicated answers:

```
answers containing an arrow : 58 of 2861 (2.03%)
place -> place              : 128 of 289 arrow occurrences (44%)
record-id -> record-id      : 1 of 289 (0.3%)
```

Two useful things fell out and one trap closed behind me.

The useful things. First, **an arrow in this system almost always means *from X to Y*, not *X
before Y*** — "Level 0 → 1", "Reception → Level 3 laboratories", "Abacws Building → Floor 0" are
routes and containments the graph genuinely holds. A guard keyed on arrows would put 58 correct
answers at risk to catch approximately none. Second, the one `record-id → record-id` hit was
`effective 2026-08-30 -> 2026-09-02` — a date range my own classifier mis-typed. True count of
the defect's shape in 2,861 answers: **zero**.

The trap is what I nearly concluded from that zero. For a few minutes I had written *"this shape
occurs in 0 of 2,861 stored answers, so it is rare"*. It is not rare. Those 2,861 answers are
responses to the questions we have **already been asking** — tails C through N, the demo path, the
probe cases. BUG-1391 was found by a stakeholder question about dependency-aware recovery order,
a shape that barely appears in the corpus at all. **The corpus does not contain the defect because
it does not contain the questions that produce it.**

This is survivorship applied to a bug log. A historical corpus can bound a *regression* — "would
this change damage answers we have already given?" is exactly what 2,861 stored answers are good
for, and that is the question the BUG-1392 measurement asked and answered well. It cannot bound a
*frequency*, because the sampling frame was never the question space; it was whatever we happened
to ask.

**The rule: a stored corpus answers "what would this fix break?" and never "how often does this
happen?"** Frequency needs questions drawn from the population you care about, asked now. And
when a scan over history returns zero for a defect you have in your hand, the first hypothesis is
that the scan is looking in the wrong place — not that you got lucky.

Corollary worth keeping: the 2.03% arrow figure is a frequency *for arrows*, and it would read
perfectly well in a report as a frequency for this defect. Label a measurement with what it
counted, not with what you went looking for.

## #178 — A guard that defers to another component must use that component's own test (2026-10-01)

The regression gate went 49/51 after a day of fixes that each measured clean on their own. Case
#4, reproduced deterministically:

```
Q  "Project the noise level in the atrium for the next 12 hours and show the error of each
    candidate model."
[ttl-route] capability via ontology triples: ['Working Hours']
[routing-contract] capability_measurand_is_data stood down: 1 amenity triples match
[capability] topics ['Working Hours'] match words but are not the subject — not answering
A  "I could not find this in <building>'s documents."
```

Read those three log lines together. The routing contract **stopped** sending a forecast question
to a data lane, on the grounds that the building's own amenity triples claimed it. One stage
later the lane holding that claim **discarded it** as not being what the question is about. The
forecast lane never ran, and the reader was told the building has no documents about it.

'Working Hours' had matched the word "hours" inside "the next 12 hours".

The stand-down was keyed on `len(resolver.resolve(q))` — a count of amenities whose *vocabulary
the question's words touched*. Its premise, written in its own comment, is that *the building's
own triples know what this question is about*. Those are different claims, and the second one was
already being computed — by `capability_agent._is_subject`, one stage too late to change the lane.
Measured over the 4,060-question bank: of the 2,022 questions that match an amenity and ask for no
value, **30** have an amenity as their subject. The premise was false for 98.5% of the set the
rule keyed on.

**The rule: when component A stands down in favour of component B, A must ask the question B will
ask, not a cheaper proxy for it.** A proxy that is *correlated* with B's answer is the dangerous
case, because it works until the day it doesn't and the failure looks like neither component's
fault — the contract logs a reasonable decision, the lane logs a reasonable decision, and the
answer is wrong.

The fix was to delete the proxy and move B's test somewhere both can call: `topic_is_the_subject`
now lives beside `leftover_content_words`, and the closure was **removed** rather than copied. A
copy would have recreated BUG-947 exactly — the decline pointer and the register selector
disagreed for months because each had its own matcher, and the pointer was the more capable one,
so declines named the register their own selector could not reach. A test now fails if
`def _is_subject(` reappears in the lane.

Two other things this cost, both worth keeping:

**I measured and rejected two fixes before this one, and rejecting them was most of the work.**
Adding a forecast test to the "asks for a value" set moved 107 bank questions, many of them
amenity and availability questions — the exact class the stand-down exists to protect. Widening
the forecast regex with a bare `project\w*` matches **projector**, of which this building keeps
records. Neither would have failed a test; both would have shipped.

**Three of my own test failures were the guards being right, and one was about me.** The
building-literal guard caught me writing the building's name into a *comment* in the routing
contract — it scans comments on purpose, because that is how a building-specific assumption gets
copied into code. And I verified the fix by curl with `X-Forwarded-User: facility01`, got a
permission decline, and nearly logged it as a routing failure; the server said
`role 'readonly' lacks access to 'noise'`. The header I typed was not the identity I got
(lesson #169, second time in two days). The gate's own harness, which logs in properly, returned
`#4 ok, answered -> answered, 20.4 s`.

## #179 — A counted fact in the prompt is not a fact in the answer, and that is still worth doing (2026-10-01)

The building was asked for a room for 12 and said there wasn't one:

```
| Rooms that can seat 12 people | 0 |
| Rooms that have a projector   | 3 (Room 1.06, Room 2.01, Room 3.01) |
... Because no workspace has a seat count of 12, there is no room that meets the capacity
requirement.
```

"No workspace has a seat count **of** 12" was literally true. The `seatCount` values are 6, 8,
10, 16, 18, 20, 22, 24, 26, 28, 30, 48 — **none is exactly twelve** — and eighteen of the
twenty-eight are twelve or more, three of them the very rooms that answer had just named as
having projectors. A request for 12 is satisfied by a room for 30. An exact seat count is a
coincidence, so an equality reading returns nothing for almost any party size.

The rows were already in the prompt — the lane logged `whole-register fetch: WorkspaceProfile
(28 instances, 23 fields)`. Nothing was missing. The *arithmetic* was left to the narration,
which is the exact thing `register_facts` was built to stop (BUG-581), and it had no line for a
numeric floor.

So I added one, and verified it reaches the prompt:

```
- THE SIZE IN THE QUESTION IS A MINIMUM, NOT AN EXACT VALUE. 18 of 28 records with a
  recorded seatCount are 12 or MORE: WS-01 (48), WS-26 (30), ... A record of 48 satisfies a
  request for 12. NEVER say none meets it because no value equals 12 exactly.
```

**Then measured what the reader actually gets, three asks, cache flushed before each. The
fabricated "no" is gone 3 of 3. The right answer appears 1 of 3.** The other two decline
honestly and never use the count.

The temptation is to call that a failure, and the opposite temptation is to call it a fix. It is
neither. The defect moved from *confidently wrong* to *inconsistently useful*, and those are not
the same severity: a wrong "no" is acted on, a missing answer is asked again. This project's own
framing — a visible failure beats an invisible one — makes that a real gain, and saying so
honestly requires also saying the question is still only answered a third of the time.

**The rule: a deterministic fact in the prompt bounds what the answer can CLAIM, not what it will
SAY.** Putting the arithmetic in code reliably removes the fabrication, because the narration can
no longer compute a contradicting number. It does not reliably produce the answer, because
nothing compels the narration to read the line. Measure both — the claim and the use — and quote
them separately. A fix reported as "verified live" on the strength of one good ask would have
been an overclaim, and the first post-fix ask I ran was in fact one of the declines; I nearly
attributed that decline to my own change before checking that the counted line was present in
the prompt regardless.

Corollary for anything written into a facts block: it is competing for attention with everything
else in a 4,632-character handover. The win is in what it forbids.

## #180 — Sixty-one tests passed every time I ran them and guarded nothing (2026-10-01)

I wrote three test files today, ran each one, and watched 61 tests pass. They were outside the
suite that gates a commit the entire time.

The `unit` marker in this repo is explicit. `pytest.ini` declares it and `--strict-markers` is on,
but strict-markers only rejects *unknown* markers — it cannot require that a file carry one, and
no conftest applies it by filename. So an unmarked file is silently absent from every
marker-selected run, including `pytest -m unit`, which Workflow rule 8 runs before a commit and
which is what CI sees.

**The tell was sitting in the summary line of two consecutive runs:**

```
13742 passed, 76 skipped, 1336 deselected    <- before adding 21 tests
13742 passed, 76 skipped, 1357 deselected    <- after adding 21 tests
```

`passed` did not move. `deselected` rose by exactly 21. I only noticed because I was comparing the
two numbers for an unrelated reason — I expected the count to go up and it hadn't.

This is the same family as the settings-patch finding (a test that patched an object the product
no longer read) and the vacuous-guard findings before it, and the common shape is the one worth
naming: **the dangerous half of a test defect is the half that never goes red.** A test that fails
tells you something. A test that cannot run tells you nothing, and tells it convincingly, because
the file passes whenever you check it by hand — which is exactly when you check a file you just
wrote.

**Two rules.**

First, after adding tests, read the pass count, not the word "passed". If it did not rise by the
number you added, find out where they went. A green run is not evidence that your new tests ran.

Second, the durable fix is derived, not remembered: a test that fails when any file under
`tests/` contributes zero tests to `-m unit`. The repo already has the right precedent in
`test_reserved_keys_have_writers.py`, which parses the source to find documented keys with no
writer rather than trusting the prose that lists them. A note in each new file saying "the marker
is not automatic" is what I did today, and it is the weaker fix, because it relies on the next
author reading a file they are about to copy from.

## #181 — A guard can only catch what the answer admits to (2026-10-01)

Asked "What is the barometric pressure in the building?", the system answered:

> **Across the building pressure is averaging 19.1 Pa**, ranging from 0.0 to 51.5 Pa

with a tidy per-floor table of six sensors. The six are all *"Air Handling Unit — Floor N filter
differential pressure"*, typed `Filter_Differential_Pressure_Sensor` — the pressure drop across
an air-handling unit's filter, which tells you the filter is clogging. Barometric pressure is
about **101,325 Pa**. The building holds no barometric sensor at all.

The lane had already noticed. Before answering it logged:

```
[aggregate] qualifier 'barometric' not carried by all 6 bound sensor names — keeping 'pressure'
```

It detected the mismatch, dropped the reader's qualifier, and said nothing about having done so.
The reasoning written beside that branch was that the coarse name is "at least not a claim about
a quantity nobody measured" — which is true of the *name* and irrelevant to the *figures*.

What interests me is why the answer-relevance gate, which exists to catch exactly this, stayed
silent. It was not broken and it was not mis-tuned. **The answer called itself "pressure", and
"pressure" is not off-topic for a question about pressure.** The gate was reading an honest label
on dishonest contents.

So the fix was not a new guard. It was to make the answer name the quantity the *sensors* carry —
the words every bound label shares — instead of the coarse word. One restart later:

```
[aggregate] ... naming what they DO carry: 'AHU Filter DP pressure'
[response] relevance gate replaced a sensor_data answer: OFF_TOPIC
           (Provides AHU filter pressure, not barometric pressure.)
```

The gate declined on its own, and the decline correctly states that the records *were* read.

**The rule: before adding a guard, check whether an existing one is being lied to.** A guard
reads what the answer says about itself. Upstream mislabelling makes it blind without making it
wrong, and the symptom — "the guard didn't fire" — points at the guard, which is the one place
the defect isn't. Today that misdirection was one layer deep; the general form is that every
suppressor in a pipeline is only as good as the honesty of the stage that labels its input.

Two smaller things from the same fix, both of which cost me a probe each:

**The labels a component judges may not be the labels the graph holds.** The graph's `rdfs:label`
is the full phrase; the lane receives `metadata[uuid]["label"]`, which live is `'AHU F5 Filter
DP'` — "differential pressure" abbreviated to "DP". My first version read leftwards from the word
"pressure" and found nothing, so it changed the behaviour not at all while passing its own tests
on the labels I had assumed. **A decision log that records its verdict without its inputs cannot
be diagnosed** — I added the labels to that log line and the cause was obvious in one read.

**And a test I wrote caught me widening it too far.** The fallback "use the words every label
shares" is meaningless for a single label, where it is just that label's own words — so one
sensor named for a different quantity would have been read as naming this one. The test asserting
the old fall-back behaviour failed, correctly, and the guard became "at least two labels".

## #182 — The provider died and the system kept answering honestly, which hid the outage from the measurement (2026-10-01)

Tail O's first pass read 45% acceptable. The second pass, after one fix to the environment, read
60%. Nothing about the system changed between them.

Ollama had died. The host restarted Docker, took the local model server down with it, and it did
not come back — `ollama.exe` absent from the process list, `127.0.0.1:11434` returning nothing,
and the orchestrator logging `circuit breaker is OPEN — the ollama provider has been
unresponsive` **134 times**. Fourteen of sixty answers were provider failures.

Here is what makes it a lesson rather than an anecdote. **The system did not error.** It returned

> *"I wasn't able to generate an answer just now. Please try asking again in a moment."* (×6)
> *"Here are the readings themselves. The readings could not be summarised. No conclusion has
> been drawn from them."* (×8)

Every one of those is honest, well-worded, and correct behaviour for a component whose model is
unreachable. The circuit breaker worked. The lane fallbacks worked. And that is precisely why the
outage was invisible in the artefact: **from the answer alone, "the model is down" is
indistinguishable from "the building cannot answer that."** I labelled fourteen answers against a
dead provider and would have published the number if I had not noticed that eight of them shared
a suspiciously specific phrase.

Two rules, and the second is the one I will actually need again.

**Check the provider before and after any quality run, not just the stack.** `/health` returning
200 says the orchestrator is up; it says nothing about the model behind it. The two cheap checks
are `curl 127.0.0.1:11434/api/tags` and
`docker logs --since <run> | grep -c "circuit breaker is OPEN"`. A non-zero breaker count
invalidates the run. Both take a second and neither was in my procedure.

**And when a quality number moves, suspect the apparatus before the system — including the parts
of the apparatus that are not instruments.** This project has recorded the measuring apparatus
being wrong about a dozen times now: a grader, a truncating terminal, a mislabelled identity, an
in-sample precision figure. The provider is a new member of that family and the widest one yet,
because it degrades *gracefully*. A broken grader produces an obviously odd number. A dead model
produces a plausible one.

The corollary worth building: a provider outage currently reaches the reader as fourteen separate
honest non-answers rather than one visible "the model is unavailable" state. For a trial that
distinction decides whether a user retries or concludes the building knows nothing. The breaker
already has the fact; nothing the reader sees carries it (CAVEAT-1409).
