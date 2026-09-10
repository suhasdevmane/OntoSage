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

