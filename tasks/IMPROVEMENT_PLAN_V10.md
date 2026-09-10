# Improvement Plan V10 — stop the wrong answers, then make them impossible

**Written:** 2026-09-06 · **Supersedes nothing** — extends the 17 open V7 rows and the 3 open
FIX_TRACKER rows. **Evidence base:** [`docs/V10_REVIEW_VERIFICATION.md`](../docs/V10_REVIEW_VERIFICATION.md),
which re-verified every claim in the external `V10_REVIEW_AND_PLAN.md` against the live system.

---

## The organising judgement

The external review's central claim is right: **the system is a bldg1 system**. But its framing —
"~800 hard-coded strings" — points at the wrong remedy. There are two genuinely different
problems wearing the same label, and they need different fixes:

**Problem 1 — literals.** `Path("input")`, `stored_at: "plant_data"`, `data/bldg1:/staging`,
`bldg1_protege.ttl`, `Room_5.01` in a prompt. 15 real sites. These are ordinary bugs. Find them
with a widened guard, delete them, done. *A day.*

**Problem 2 — vocabulary.** `_DATA_ANALYTIC_WORDS` is bldg1's modality set. `_ROOM_ID_RE` assumes
`N.NN`. `_SPATIAL_BYPASS_PHRASES` is British English. `REGISTER_RE` names `legionella` and
`LOLER`. None of these is a *literal* — no grep finds them — and deleting them breaks the system.
They have to be **derived from the active building's own graph** and cached per `building_id`.
*A week, and it is the actual work.*

Confusing the two is why `check_building_literals.py` reports "clean" on a tree that answers
`Room 2.01` to a building that has no such room.

**The severity order is not the phase order.** Seven questions return wrong answers on the
development building today. Each has a verified single root cause and costs hours. They go first,
regardless of which phase they belong to, because a wrong answer is worse than an absent feature
and because the regression probe cannot protect work it cannot see.

---

## W0 — the seven live wrong answers (target: 2 days)

Every row here reproduced on 2026-09-06 with the response cache flushed, and every root cause is
verified at a file and line. **Each lands with a regression-probe case in the same commit**, or it
will come back.

| id | the wrong answer | verified cause | fix | agnostic? |
|---|---|---|---|---|
| **W0-1** | *"Is the lift working?"* → **"no lifts recorded"**, and 13 more amenities the same way | 14 of 64 `ontosage:statusOf` objects are IRIs with **zero triples**; `_status_query` opens `?asset a ontosage:{class}` | declare the 14 missing assets in `bldg1_synthetic_status.ttl` / `_amenity_state.ttl`, **and** fix the generator that wrote a status for an asset it never declared | yes — generator fix, no literals |
| **W0-2** | *"Which rooms are on floor 2?"* → **6 rooms from the Cleaning Task Register**; the graph holds 48 | the pre-LLM capability short-circuit in `dialogue_agent` fires before classification and has 21 `and not` escape clauses, none of which covers a structural spatial question | **invert it**: probe documents *after* classification as a scored target. See W1-1 — this is not a 22nd clause | yes |
| **W0-3** | *"Compare CO₂ floor 1 vs floor 3"* → **157 / 111 ppm** (outdoor is 420) + an HVAC capex recommendation | 174 floor 0–4 sensors are `brick:CO2_Sensor` in the graph and `Air_Quality_Sensor` **0–150 AQI** in `bldg1_extended_narrow_uuids.json`; still being written today | regenerate the map from the graph's own class; **and** W1-2, because the disagreement is the detectable thing | yes — map is generated |
| **W0-4** | *"How many sensors?"* → **"Floors: 8"** in a six-storey building; and 2,763 reporting > 2,720 declared | `Rooftop` and `Parking_Level_Ground` are typed `a brick:Floor` | retype to `brick:Roof` / `brick:Parking_Structure`; separately reconcile the two sensor counts, which measure different populations and are presented as if they measured one | yes |
| **W0-5** | *"What is this building and who runs it?"* → **privacy refusal** | `INDIVIDUAL_PRESENCE_RE` carries a bare `(?:and\|but)\s+who` alternative | require a presence predicate near the `who`; add a governance allow-list (`who runs/manages/owns/is responsible for`) that routes to the StakeholderGroup register | yes |
| **W0-6** | *"Which rooms are stuffy?"* → *"I don't have live CO₂ readings"* then a **sensor-count** table | the generated SPARQL returned counts per space, and the model narrated the shortfall to the user | meta-answer guard in `_response_node`: an answer that describes its own inputs is not an answer — re-route to the honest-decline path | yes |
| **W0-7** | *"Nearest accessible toilet to 3.10?"* → *"no toilet is reachable"* | floor-plan adjacency is absent or unbuilt for that pair; the lane declines rather than falling back to the AccessibleRoute register, which holds the answer | fall back to the register lane before declining (closes **V7-T23**) | yes |

---

## W1 — make each defect class impossible (target: 3 days)

W0 fixes seven answers. W1 stops the eighth.

**W1-1 · Invert the capability short-circuit.** Documents become a scored *target* after
classification and the contract, never a pre-LLM veto. The 21 `and not` clauses are then
unnecessary rather than merely deleted — the distinction matters, because each clause is a
measured incident and dropping them wholesale trades six known-fixed failures for one
known-broken one. **Gate:** extend `regression_cases.json` with one case per clause *first*, so
the probe can tell the inversion from a silent trade.

**W1-2 · Reference-integrity validator.** Every `statusOf` / `servesSpace` / `locatedIn` /
`hasPart` object must be a typed subject in the building's own namespace. HARD_FAIL on swap, WARN
in the admin Ontology tab. Would have caught the lift, the other 13, and the same class of defect
in any building. Extend it with the **cross-source type check**: a UUID's class in the graph must
match its class in the publish map. That single check catches W0-3 generically.

**W1-3 · Plausibility bands everywhere.** `DEFAULT_ANCHORS` lives in the deliberation scorer, so
only one lane of eighteen can tell 111 ppm from a reading. Move the bands to
`ontology/measurand_kinds.ttl` as `ontosage:physicalMin/Max` — **the file already exists**, this
is 8 declarations extended, not a new file — and apply them in `sql`, `compare`, `analytics` and
`deliberate`. A value outside its band is reported as implausible: never averaged, never rounded
into a recommendation.

**W1-4 · Universal referent gate.** `apply_referent_gate` has exactly **one** call site in the
whole orchestrator. Every lane that names a space, floor or zone must run it; it must fail
**closed** on timeout ("could not verify" beats a 46-second wait that blames the clock); and the
space-IRI set is cached per request. Merges with and closes **V7-T21**, and fixes the timing half
of **V7-T39**.

**W1-5 · Never invent a referent.** `floor_plan_service` fabricates rooms `{floor}.01`…`.14` when
the PDF yields no text. It invents in one building's grammar and it invents at all. Return empty
and say the plan could not be read.

**W1-6 · Meta-answer guard.** Reject narration matching *"the data you've provided"*, *"if you
can run a query"*, *"I don't have access to"* and route to `_unanswered_response`. Developer
chatter reaching a user is a contract-4 failure dressed as politeness.

---

## W2 — derive vocabulary and identity from the active building (target: 1 week)

**This is the user's explicit constraint made structural: no building information in core code or
agents.**

**W2-1 · `BuildingLexicon`, built once per `building_id`.**

| replaces | derived from |
|---|---|
| `_DATA_ANALYTIC_WORDS` (~60 measurands), `_DATA_KW` (17) | modality config + HBCO `layTerms` |
| `_ROOM_ID_RE`, `_ZONE_ID_RE` (`\d+\.\d+`) | learned from the actual `brick:Room` labels and IRIs — `5.01`, `RM-204`, `L2-East` all work |
| `_SPACE_NOUNS` (`lab`, …) | Brick subclasses that have instances |
| `_MODALITY_STOPWORDS` (hand-tuned to bldg1 names) | the same modality config |
| the nouns inside `EVENTS_RE`, `_READINESS_RE`, `REGISTER_RE` | `layTerms` of classes that **have instances** in this building |

`metered_vocabulary()` and `_plant_measurand_re()` already do this. They are the pattern; there
are two of them and there need to be eight.

**Acceptance is a second fixture, not a grep.** `test_contract_is_building_agnostic` greps six
strings and cannot see any of the above. Replace it with a two-fixture test that boots the lexicon
on two different room grammars and asserts routing works on both.

**W2-2 · Fix the 15 literal sites**, then widen `check_building_literals.py` to `frontend/`,
`rag-service/`, `scripts/` and the compose files, and add rules for room-id grammars, `cardiff`,
`example.com` and table names. **The guard must fail on the current tree before it passes** — a
guard that has never failed has never been tested.

**W2-3 · One path resolver.** 33 sites in `orchestrator/`+`shared/` hardcode `Path("input")` or
`/app/input`; ten use `shared/building_paths`. Six services re-implement the nested/flat search,
each supporting only the nested form (`rules.yaml`, `channels.yaml`, `recipes.yaml`, `goals.yaml`,
actuation, feeds) — which under the flat layout means those six files are never found. Same logic
written seven ways, six of them wrong.

**W2-4 · Fix `building_context`.** It reads `building_prefix` and `building_timezone`. bldg2/3/4
write `ontology_prefix`; bldg1 writes **neither**, and no timezone at all. Every building silently
runs on the env default. Read both spellings, and make the swap validator reject a `building.yaml`
that declares neither.

**W2-5 · Generate the SPARQL few-shot from the live graph** at boot — one real room IRI, one real
sensor IRI, one real record class. Delete the `5.01` / `5.08` exemplars from the six prompt sites.
Add `ontosage:` and `hbco:` to `sparql_validator._PREFIX_INJECT`; the project's own vocabulary
currently fails its own pre-flight.

**W2-6 · Response dispatch order.** `dialogue_response` is checked second, above every computed
lane, so any node that writes a draft pre-empts a richer result computed in the same turn. Move it
below the computed lanes.

---

## W3 — a second building gets what bldg1 has, by construction (target: 1–2 weeks)

The honest statement of the data gap: **bldg1 has 37 lifted register documents; bldg2 has 10;
bldg3 and bldg4 have 1 each.** `input/_templates/` ships 5 files against 39 TTLs. A new building
receives identity and storage routing and nothing else, and no validator says so.

**W3-1 · Ontology-layer readiness report.** For each `ontosage:` class with layTerms: instance
count in this building. For each record mapping: whether a document of that type exists. Per lane:
GREEN or EMPTY. Nothing fails; the report is simply the answer to *"why does bldg4 decline
everything"*. Surfaced in `certify_building.py --preflight-only` and the admin Onboarding tab.

**W3-2 · Register scaffolder.** `scripts/scaffold_registers.py --building bldgN` writes one
empty, front-mattered register per mapping — columns from the mapping, `simulated: true`, building
name from `building.yaml` — plus `--synthetic N` for demo rows. This is the generator that built
bldg1's registers, made building-agnostic.

**W3-3 · Templates for the 24 TTLs that have neither template nor generator**, and
`onboard_building.py` writes them **flat**, sets all 7 per-building env settings, and is what
`/new-building` actually calls (that command passes `--building-id`, which the script rejects, and
queries repository `ontosage`, which does not exist — the repository is `bldg`).

**W3-4 · Close the three unfillable record classes.** `AlarmEvent`, `AnomalyEvent`, `AccessEvent`
are declared and lay-termed with no mapping, no instances and no reader: they can only produce a
confident silence. Give them mappings or remove their layTerms. Put `SustainabilityTarget` under
a discovery root — it has a mapping and is undiscoverable. Script the RDF half of the unread-store
audit (`audit_unread_stores.py` covers SQL only).

**W3-5 · Deployment truth.** MySQL is a host prerequisite documented nowhere. `.env.example` is
missing exactly 31 live settings. `container_name`s and host ports are fixed, so one building per
host. `PUBLISH_WIDE=true` ships. bldg4 has no tracked compose file or `.env4.example`. Then run
the cold start in `COLD_START_VERIFICATION.md` **on bldg4** and close TODO-072 with evidence
rather than assertion.

---

## W4 — say what is true (target: 2 days, do it last, do not skip it)

**W4-1 · The deliberation lane.** Zero tests exercise `_deliberate_node` end to end — every
deliberation test injects fakes, and V4-T26 is marked done. `ONTOSAGE.md` contains zero
occurrences of "ARBITER" or "dossier". `build_plan_trace` emits a constant six-step list whatever
ran. Fix: one end-to-end test with a fake LLM and a seeded graph; `deliberate_result` added to
`_LANE_KEYS_FOR_DIAGNOSIS` so its failures can be named; `DELIBERATE_CLARIFY_OFF` and
`CQIR_COMPILE_CACHE` become real `Settings` (they are in no config file today); and **describe the
lane accurately in `ONTOSAGE.md`** — a symbolic ranking and evidence layer reached by one intent.
Do not rename the package to settle a documentation error.

**W4-2 · Refresh `CLAUDE.md`'s orientation block.** It says branch `main`, V6, 2,488 tests.
Reality: `development`, V7, 5,004 tests.

**W4-3 · The grader.** `_heuristic_grade` never reads the question — its own docstring says so.
`has_counted_records` is `\b\d+\s+[a-z]{3,}`. 572 of 2,960 baseline rows carry
`provider=model=unrecorded`. Land these before **V7-T41** (the 4,060-question re-capture), because
a re-capture under a grader that ignores the question measures the grader.

**W4-4 · Regression probe gains the seven W0 questions as permanent cases**, and a bldg3 leg. No
coverage number is published from a run that has not passed them.

---

## What not to do

- **Do not fix W0-3 by editing `_WIDE_RANGES`.** The external review's recommendation. That table
  was already corrected on 2026-09-03 and maps `co2 → 400–1200`; the bad data comes from the
  extended narrow map. The proposed fix is a no-op, and it would have been reported as done.
- **Do not add a 22nd `and not` clause, a 37th contract rule, or another `N.NN` regex.** Every one
  of those is the disease presenting as its own cure.
- **Do not delete the 21 clauses without the probe cases first.** Each is a measured incident.
- **Do not add registers before W0/W1.** W0-2 is a live demonstration that a new register can
  *lower* accuracy by feeding the short-circuit.
- **Do not publish a coverage number until W4-3.**
- **Do not delete bldg1's hand-built data.** Make it reproducible (W3-2, W3-3).

---

## Sequencing against the open V7 rows

| V7 row | disposition |
|---|---|
| V7-T21 answerability precheck | **merges into W1-4** (universal referent gate) |
| V7-T23 spatial lane raises instead of answering | **becomes W0-7** |
| V7-T39 refusal's remedy times out | timing half fixed by **W1-4**; remainder stays |
| V7-T41 full 4,060-question re-capture | **blocked on W4-3**, and the user has already deferred it to last |
| V7-T02, T03 carryover; T12–T16 evidence grammar; T22, T24; T35, T38, T44 | unchanged, run after W1 |
