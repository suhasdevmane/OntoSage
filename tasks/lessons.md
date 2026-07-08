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
