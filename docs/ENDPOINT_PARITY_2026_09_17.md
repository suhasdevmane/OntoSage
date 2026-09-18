# Endpoint parity — the probe measures `/chat`, the demo runs `/v1/chat/completions`

**2026-09-17** · harness `scripts/endpoint_parity_probe.py` · tests `tests/test_endpoint_parity_probe.py`

> **Nothing in this document is a live measurement.** The 60-case regression probe was
> running against the same local GPU throughout this session (`conv_baseline-*` conversations
> in the orchestrator log, one workflow start every ~20 s), and CLAUDE.md records what happens
> when two measurements share a model — a lane measured at 170 s under load answered in 20.1 s
> alone. Every finding below is read from the source and carries a file and a line. The harness
> is built, formatted, linted and unit-tested offline; **33 tests pass**; it has not asked the
> live system a single question. The live sample it is waiting to run is named at the end.

---

## 1. What the gap actually is

Both endpoints run the same LangGraph pipeline. They do **not** share what happens around it.

| | `/chat` (`main.py:2363`) | `/v1/chat/completions` (`main.py:3572`) |
|---|---|---|
| auth | session token; the caller's **own** role | shared pipeline key; role pinned `readonly` unless `TRUST_FORWARDED_USER` resolves the forwarded identity (`main.py:3687`) |
| conversation id | `conv_<session_id>:<user>` | `owui_<X-Chat-Id>:<user>`, else SHA of the first message |
| prior turns | server-side Redis state, restored whole (`main.py:2413` → `redis_manager.load_state`) | the client's `messages` array **plus** server-side rehydration (`main.py:3666`) |
| carry-forward from Postgres `turn_memory` | never loaded | every turn (`main.py:3710`) |
| `prune_inherited` — the V12-11 context-switch guard | **never runs** | every turn (`main.py:3736-3751`) |
| older-turn summaries injected | never | as a system message at position 0 (`main.py:3767-3771`) |
| `turn_memory.save_turn` | never called | stream (`main.py:3894`) and non-stream (`main.py:3975`) |
| response body | `intent`, `sources`, `evidence_record`, `plan_trace`, `llm_degraded` | message text, `ontosage_evidence_record`, `ontosage_llm_degraded` — **no `intent`** |

`/chat/stream` (`main.py:2619`) and the websocket (`main.py:3152`) match `/chat`: Redis only,
no `turn_memory`, no prune.

So "60/60 on the probe" is a claim about an endpoint the demo does not use. That much was
already established. What the code says next is more interesting, and it points the other way.

---

## 2. The headline: the demo endpoint is **better** protected against BUG-524, not worse

BUG-524 has two mechanisms, and `context_switch.py`'s own docstring names them both. They are
guarded in different places, and only one of those places is endpoint-specific.

**Mechanism 2 — the co-reference rewrite swaps the referent.** Guarded in
`dialogue_agent.py:668` (`rewrite_is_safe`), called from `_orchestrator.py:1283` — **inside the
workflow**. Both endpoints get it. This is not an endpoint risk at all.

**Mechanism 1 — inherited state is about the old place.** Guarded by `prune_inherited`, which
lives in `main.py` and is wired on `/v1` **only**. And `/chat` is the endpoint that inherits
more:

- `/v1` builds a **fresh** `ConversationState` with `intermediate_results={}` (`main.py:3679`)
  and then adds back exactly two keys — `forecast_result`, `analytics_result` — which are then
  passed through `prune_inherited`.
- `/chat` calls `redis_manager.load_state`, and `save_state` serialises the **whole**
  `intermediate_results` dict (`redis_manager.py:56`). Whatever survived the previous turn is
  inherited verbatim, and nothing prunes it.

What survives a turn is the complement of the response node's cleanup list
(`_orchestrator.py:5649-5669`). That list pops `sparql_result`, `sql_result`,
`analytics_result`, `sensor_metadata`, `floor_plan_result`, `spatial_result` — good. It does
**not** pop these, every one of which is in `context_switch.PLACE_BOUND_KEYS`
(`context_switch.py:53-65`):

```
forecast_result   anomaly_result   deliberate_result   evidence_record   visualization_path
```

Five place-bound keys, carried across every `/chat` turn, never pruned. `PLACE_BOUND_KEYS`
lists them with the note *"the rest are listed because the same rule applies if they are ever
carried."* They are carried — on the endpoint the guard was never wired to.

**So the probe's own endpoint is the one with the unguarded carry-forward.** That inverts the
premise this investigation started from, and it is the finding I would most want confirmed by a
live run before Friday.

Practical severity is lower than it sounds, because the `/chat` path that would exploit it is
narrow: the stale key has to be one of those five, and a later turn has to read it rather than
recompute. But "narrow" is an argument, not a measurement, and `visualization_path` and
`forecast_result` are exactly the keys a "now plot that" follow-up reaches for.

---

## 3. The guard on `/v1` has a hole this harness is built to find

`prune_inherited` is called with the **immediately preceding user message** as `previous`
(`main.py:3738-3744`), and `switched()` returns `None` unless **both** messages name a place
(`context_switch.py:100-110`). That is correct and deliberate for a two-turn exchange.

It is not enough for three turns. Consider:

1. "What is the temperature in room A?" → names a place
2. "How has that changed over the last week?" → names **no** place; produces `forecast_result`
3. "And in room B?" → names a place

On turn 3 the guard compares turn 2 with turn 3. Turn 2 names no place, so `switched()` returns
`None`, so **nothing is pruned** — and the artifact inherited from turn 2 is about room A.
The guard compares adjacent turns; the subject changed across a gap.

This is a prediction from reading the code, not a measurement. The `followup-change`
conversation in the harness is exactly this sequence, and it runs on both endpoints, which is
the cheapest way to find out whether the prediction holds.

---

## 4. Where `/v1` is genuinely riskier

**4.1 No `intent` in the response body — the demo endpoint is unobservable by lane.**
18 of the 60 regression cases are in the `capability-bypass` group, and several assert a lane
via `expect_intent` / `forbid_intent`. The regression probe's own docstring says why: *"a
question answered from the wrong lane comes back fluent and plausible… no marker over the text
can tell the lanes apart."* `/v1` returns no lane, so on the demo endpoint those assertions
cannot be evaluated at all.

The harness **skips** them there rather than passing them (`evaluate_case`, `intent=None`), and
the report states the count — because silently passing an unevaluable check would make the demo
endpoint look better precisely by telling us less. That is the CAVEAT-500 trap in a new place.

This matters beyond the harness. BUG-631 — every floor-scoped SPARQL query rejected, the
fallback answering about a different floor with a plausible number — is the exact defect class
a lane check catches and a text marker does not. On Friday, through Open WebUI, there is no
lane to check.

**4.2 Role resolution can silently differ from what the probe measured.**
The probe logs in as `admin@ontosage` (role `admin`). `/v1` pins `readonly` unless
`TRUST_FORWARDED_USER` is on **and** the forwarded email resolves to an account
(`main.py:3687`). It is on in `.env`, and `facility01@example.com` / `viewer01@example.com`
both exist in Postgres with the expected roles — so the mechanism should work. But BUG-542 is
on record for exactly this lookup failing silently, and a demo user whose Open WebUI email does
not resolve gets `readonly` answers with no error anywhere. The harness therefore forwards, **by
default, the same account `/chat` logs in as**, so a divergence is attributable to the wiring
and not to two different roles; `--forwarded-user facility01@example.com` measures the role
deliberately, as a separate question.

**4.3 `/v1` builds a larger prompt than the probe ever measures.**
Server-side rehydration (`main.py:3666`) plus `older_context` injected as a system message
(`main.py:3767`) plus the client's own `messages` array all land in the same context. BUG-474
was a 45,573-char prompt against a 16k window, and BUG-188 was 2.7% of local turns returning
empty completions from a 29,705-char prompt. None of that growth exists on the probe's path.
A long Open WebUI conversation on demo day is the untested end of this.

---

## 5. What I could not test, and why

| | why |
|---|---|
| **Anything live** | The 60-case probe was running on the same GPU for the whole session. Contending would have produced two garbage measurements instead of one good one. |
| **The streaming path** | Open WebUI streams by default, and `/v1`'s stream branch (`main.py:3781-3907`) is a *different* code path — it extracts the final state by walking `last_step.items()` and looking for a `ConversationState`, then saves Redis, Postgres and `turn_memory` from that. The harness sends `stream:false`. **The demo's actual path is the one neither the probe nor this harness exercises.** Adding a streaming mode is the single highest-value extension. |
| **`/chat/stream` and the websocket** | Same wiring as `/chat` (verified by reading), so they add no third behaviour — but that is a code read, not a measurement. |
| **Lane assertions on `/v1`** | The endpoint does not report one. Not a harness limitation — an observability gap in the product. |
| **Whether the five unpruned `/chat` keys are ever *read* on a later turn** | Requires a live multi-turn run, or a static trace of every reader of `forecast_result` / `visualization_path` / `evidence_record`. |

## 6. What was reused, and what could not be

- **The corpus is reused, not forked.** The harness loads `scripts/regression_cases.json` —
  the probe's own file. A test asserts the path and asserts that no case question has been
  copied into the harness.
- **The marker semantics are reused.** `_matches` is imported from `scripts/regression_probe.py`
  (number words, thousands separators, en dashes), so a marker means the same thing in both.
- **The evaluation *loop* could not be imported.** It lives inline in the probe's `main()`, and
  importing it would mean running the probe. It is re-expressed in `evaluate_case` using the
  imported `_matches`. No case text and no marker rule is duplicated — this is the one place
  reuse was genuinely impossible, and it is stated rather than hidden.
- **`_login` and `_active_model`** come from `capture_golden_baseline.py`, **`_env_or_dotenv`**
  and the pipeline-key convention from `corpus_replay.py` — the same sources the probe uses.

Nothing in the harness names a room, a floor or a building. The conversations are templates
(`{room_a}`, `{floor_b_token}`); the places are resolved at run time from a plain Brick SPARQL
query for rooms that hold a temperature sensor with a fetchable timeseries reference, one per
floor. A unit test fails the build if a literal place ever appears in a template.

## 7. Honest read on demo risk

**The demo endpoint is not obviously riskier than the probe endpoint, and on the carry-forward
axis it is safer.** I would not raise an alarm about `/v1` memory behaviour on the strength of
what I can see.

Three things I would still not call measured:

1. **Nobody has run a multi-turn conversation through either endpoint under test.** The probe
   asks 60 independent questions. The demo is a conversation. That is the real gap, and it is
   larger than the endpoint difference.
2. **The streaming path is untested by everything.** The demo streams; the probe does not; this
   harness does not yet.
3. **The lane is invisible on `/v1`.** Whatever the demo does wrong on Friday, the one signal
   that distinguishes a wrong-lane answer from a right one will not be in the response.

## 8. The run this is waiting for

When the GPU is free (roughly 12 model calls for the conversations, plus 2 per sampled case):

```bash
python scripts/endpoint_parity_probe.py --dry-run            # resolves places, asks nothing
python scripts/endpoint_parity_probe.py --multiturn-only     # 4 conversations, both endpoints
python scripts/endpoint_parity_probe.py --sample 6           # + 6 cases spread across groups
```

It exits non-zero on any divergence or any carried referent, and writes
`docs/ENDPOINT_PARITY_RUN_<date>.md` with the answers side by side.

**Priority order if there is only one window: `--multiturn-only`.** Single-turn parity is the
part the existing probe already half-covers. The conversations are the part nothing covers.

## 9. Orchestrator fixes this suggests — described, not made

None were applied; `orchestrator/` was not touched.

1. **Add `intent` to the `/v1` response.** One field, same extension-field convention as
   `ontosage_evidence_record` (which was added for exactly this reason: *"this is the endpoint
   Open WebUI and every OpenAI-compatible client actually use"*). It makes the demo endpoint
   observable by lane. Lowest cost, highest value, and it is additive — an OpenAI client ignores
   unknown fields.
2. **Either prune on `/chat` too, or stop carrying the five place-bound keys.** Adding
   `forecast_result`, `anomaly_result`, `deliberate_result`, `evidence_record` and
   `visualization_path` to the response node's cleanup list would close it in the shared path
   for every endpoint at once — but it would also break "now plot that" on `/chat`, so the
   correct fix is to call `prune_inherited` on `/chat` as `/v1` does. **Not before Friday**: it
   is a shared-path change with no green probe on either side of it, which is precisely what
   V12-01's ordering rule forbids.
3. **Let `prune_inherited` look back past the previous turn** — compare against the last message
   that named a place, not merely the last message. Same objection: after the demo.
