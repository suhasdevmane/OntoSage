# IMPLEMENTATION PLAN V3 — Corpus-Driven Capability Completion

**Source of truth for the multi-session implementation effort.**
**Tracker:** [implementation_tracker.csv](implementation_tracker.csv) — one row per turn; mark `status` as you go.
**Evidence base:** `paper/Survey analysis and results/outputs/master table analysis/` (5,604 real user questions, classified two-axis by GPT-5.5, 0 data-quality violations).
**Scope exclusion:** general-knowledge questions (760) are OUT — already handled by the single-LLM-call path. This plan covers the remaining **4,844 building-data + hybrid questions**.

---

## 0. Session-resume protocol (read this first in every new session)

Claude sessions lose context when credits reset. To resume:

1. Read this file (§0–§2 minimum).
2. Open `tasks/implementation_tracker.csv`. Find the first row with `status=todo` whose `depends_on` turns are all `done`.
3. Each row is self-contained: objective, key steps, files, acceptance criteria, verify command.
4. On completion: run the verify command, set `status=done`, add a one-line note in the `notes` column (date + anything the next session must know).
5. If a turn is too big for one session, set `status=in_progress` and write exactly where you stopped in `notes`.
6. Never start a turn whose dependencies aren't `done`.

**Standing rules (apply to every turn):**
- **No building-specific logic in code.** Everything building-specific lives in `input/<id>/` (TTL, YAML, documents) or `config/`. The test: onboarding a new building = dropping files, zero code edits.
- All new agent nodes follow `.claude/rules/agent-patterns.md` (`_safe_node`, async, own `intermediate_results` key).
- Lint before finishing: `black --line-length 100`, `flake8 --select=F821,F823`.
- Run `pytest tests/ -m unit -q` after every code turn; targeted QA via `python scripts/ontosage_qa_suite.py --ids <relevant>`.
- After code fixes, flush Redis response cache: container is **redis-memory-store** (`docker exec redis-memory-store sh -c "redis-cli --scan --pattern 'resp_cache:*' | xargs -r redis-cli del"`).
- **Do not commit/push without explicit user approval.**

---

## 1. What the corpus says (summary of findings)

| Fact | Number | Implication |
|---|---|---|
| Non-GK questions | 4,844 | the implementation target |
| Answerable today (full+partial) | 786 = **16.2%** | the baseline to beat |
| Blocked by missing capability | 4,058 = 83.8% | almost all blocked by *data*, not *reasoning* |
| Iceberg effect (latent > surface) | 62.8% of corpus | users phrase architecturally huge asks as trivial questions |
| Closed-loop automation asks (latent L6) | 568 | need ECA rules + actuation, not retrieval |
| Autonomy mandates (surface L6) | 75 non-GK | need goal decomposition, not a pipeline |
| Long-tail rows (touch a niche gap) | **1,914 of 4,058** | no feature list ever covers them — only a generic onboarding mechanism does |

**Cumulative unblocking (computed from the master table, non-GK):**

| After phase | Fully answerable | % of non-GK |
|---|---|---|
| Baseline | 786 | 16.2% |
| B — input enrichment (TTL metadata + doc KB) | 822 | 17.0% |
| C — live streams floors 0–4 | 904 | 18.7% |
| D — external feeds (weather/calendar/tariff) | 978 | 20.2% |
| E — sensor modality expansion | 2,437 | **50.3%** |
| G — guarded actuation | 2,930 | **60.5%** |
| Remaining 1,914 | long-tail niche needs | addressed by the SAME mechanisms as config drops, case-by-case |

Two readings of this table:
1. **Phase E is the single biggest lever** (+30 points) — but it is hardware/data acquisition, mostly *enabled* by Phase D's adapter framework rather than new core code.
2. **The architecture phases (A, D, F, G) are what make every following building cheap.** They are the paper's contribution; the data phases are deployment work.

---

## 2. Architecture decisions (locked — do not relitigate in later sessions)

### D1. HBCO — Human-Building Conversation Ontology (Phase A)
A **building-independent** TTL layer extending Brick, loaded into GraphDB next to `Brick_v1.4.ttl`. It maps *how humans talk* to *what the system can query*:

```
hbco:Concept            a owl:Class .            # "stuffiness", "comfort", "busyness"
hbco:layTerm            (concept → skos literal: "stuffy", "stale air", "airless")
hbco:mapsToBrickClass   (concept → brick:CO2_Level_Sensor …)
hbco:requiresRecipe     (concept → recipe id in config/recipes.yaml)
hbco:componentOf        (composite concepts: comfort = temp + humidity + co2)
hbco:persona…           (optional depth hints per persona)
```

Why ontology and not YAML: it lives in the same graph, so one SPARQL hop resolves lay term → sensor class → instances → UUIDs; new buildings inherit it with zero work because Brick classes are building-independent; and per-building overlays (`input/<id>/concepts.ttl`) can ADD local vocabulary ("the fishbowl" → Room_3.14) without touching the core. **The 5,604-question corpus is the mining source for the vocabulary.**

### D2. Recipes registry (Phase A)
`config/recipes.yaml` — analytic recipes keyed by id: thresholds (CO2 1000 ppm, ASHRAE 55 comfort ranges), aggregations, correlation templates. Referenced from HBCO by id. Hybrid questions ("is it too warm?") = recipe norm + live reading. Per-building override file allowed (`input/<id>/recipes.yaml`).

### D3. Generic external-feed adapter (Phase D)
ONE framework class, instances declared per building in `input/<id>/feeds.yaml`:

```yaml
feeds:
  - id: weather_open_meteo
    type: rest_poll            # rest_poll | mqtt | csv_drop
    url: https://api.open-meteo.com/v1/forecast?latitude=51.48&longitude=-3.17&current=temperature_2m
    interval_s: 900
    field_map: {temperature_2m: outside_air_temp}
    brick_class: brick:Outside_Air_Temperature_Sensor
    storage: database1          # writes via existing adapter registry
```

The framework: polls/subscribes → normalises → writes to the configured time-series store → **auto-registers a Brick point + `ref:hasTimeseriesId` in the graph** (so SPARQL→SQL finds it like any sensor). This single mechanism converts the entire long tail (1,914 rows) from "engineering tasks" into "YAML + credentials".

### D4. ECA rule engine (Phase F)
`orchestrator/services/rules_engine.py` + `input/<id>/rules.yaml`. Rule = trigger (telemetry condition over UUIDs/concepts) + action (`notify` first; `actuate` only after Phase G). Conversational creation through the existing `alert` intent. This serves the 568 latent-L6 "can the building automatically…" questions with *truthful, capability-aware* answers and — where data exists — actual standing rules.

### D5. Guarded actuation (Phase G)
Driver interface with a **simulation driver first** (logs the would-be action, returns success) — bldg1 has no physical write-back, but the demo/paper needs the full loop demonstrable. RBAC `control:write`, approval workflow, audit table. The `control` intent upgrades from "always decline" to "execute when a driver is configured for this building, else explain what's missing" — config-driven, so buildings without actuation keep today's safe behaviour.

### D6. What stays out
- General-knowledge path: untouched (user decision).
- Physical hardware procurement (occupancy sensors etc.): the plan builds the *software path* and uses **synthetic feeds** for bldg1 so every pipeline is exercisable; real hardware is a swap of the feed URL.
- Routing-precedence refactors not driven by a failing test (demo stability rule).

---

## 3. Phase map (10 phases, 30 turns)

| Phase | Turns | Theme | Core deliverable | Unblocks |
|---|---|---|---|---|
| **A** Concept layer | T01–T06 | HBCO ontology + recipes + resolution wiring | `ontology/hbco_core.ttl`, `ontology/hbco_mappings.ttl`, `config/recipes.yaml`, resolver service | every hybrid question (1,164) gets a principled path; lay phrasing resolves for ALL later phases |
| **B** Input enrichment | T07–T09 | bldg1 metadata TTL, document KB, idempotent uploads | `input/bldg1/bldg1_enrichment_metadata.ttl`, `input/<id>/documents/` ingestion | +36 rows; doc KB also serves the 109 meta/ethical questions |
| **C** Live floors 0–4 | T10–T11 | connect modelled sensors to streams | data-publisher config | +82 rows (cum 904) |
| **D** Feed framework | T12–T15 | generic adapter + weather/calendar/tariff | `orchestrator/services/feeds/`, `input/<id>/feeds.yaml` | +74 rows directly; ENABLES Phase E and the long tail |
| **E** Modality expansion | T16–T19 | occupancy, energy, IAQ batch, long-tail playbook | feed YAMLs + TTL + recipes (synthetic for bldg1) | +1,459 rows (cum 50.3%) |
| **F** ECA rules | T20–T22 | rule engine + conversational alerts + honest capability answers | `rules_engine.py`, `input/<id>/rules.yaml` | the 568 automation questions |
| **G** Guarded actuation | T23–T25 | sim driver, RBAC+audit, control intent upgrade | `services/actuation/` | +493 rows (cum 60.5%) |
| **H** Goal planner | T26–T27 | goal→KPI decomposition + capability report | planner extension | the 75 autonomy mandates |
| **I** Verification | T28–T30 | corpus-replay harness, portability proof, docs/paper | `scripts/corpus_replay.py` | measured % for the paper |
| **J** Coverage extension | T31–T37 | capabilities the exhaustive architecture-column audit (§6) found uncovered: wayfinding, benchmarking, notification dispatch, what-if estimation, personalised preferences, CMMS/equipment condition, **onboarding validator** | see tracker | ~230 additional rows + the files-only contract enforced |

Dependency spine: A → (B, C, D in any order) → E → F → G → H → I. B/C/D are parallelizable across sessions. J turns slot in where their `depends_on` allows (T31 has no deps; T37 should land before T29's portability proof — T29 now depends on it).

---

## 4. Portability acceptance test (the definition of done for the whole plan)

After T29, this must hold: **onboard a synthetic `bldg2` using ONLY files** —

```
input/bldg2/
  building.yaml          # namespace, prefix, capability_routing
  *.ttl                  # topology + points (+ optional concepts.ttl overlay)
  capability.yaml        # off-ontology facts
  feeds.yaml             # external/sensor feeds   (Phase D)
  recipes.yaml           # threshold overrides      (optional)
  rules.yaml             # standing ECA rules       (optional)
  documents/             # policies, manuals        (Phase B)
  intents.yaml, personas/  (existing, optional)
```

then `python scripts/swap_building.py --to bldg2 --dry-run` passes and the QA suite answers data/capability/automation questions for bldg2 **with zero code edits**. If any step needs a code change, that step is a bug in this plan — fix the framework, not the building.

---

## 5a. Coverage audit (proof the full master table was used)

`paper/Survey analysis and results/scripts/L_architecture_coverage.py` exhaustively decomposes the
`architecture` + `pipeline_stages` + `data_sources` columns of ALL non-GK rows (4,844 questions,
~86,500 component mentions) and maps every fragment to a canonical component, each marked
EXISTING / PLANNED(turn) / NEEDED. Outputs (regenerate any time):

- `tasks/architecture_coverage_crosswalk.csv` — the full component × status × turn map with example questions
- `tasks/architecture_unmapped_fragments.csv` — the residual audit tail (6.5% of mentions; spot-checked = low-frequency wording variants of mapped components, max ~27 mentions each)

Result: **64,938 mentions EXISTING · 15,756 PLANNED · 223 NEEDED.** The NEEDED set became Phase J
(T31–T37): personalised preferences (68 rows), benchmarking vs peers (47), notification dispatch
(34–44), wayfinding (29), what-if estimation (6) — plus two structural turns the audit exposed:
CMMS/equipment-condition (referenced by 366 mentions previously routed vaguely to the playbook)
and the **onboarding validator (T37)**, without which "files-only onboarding" fails silently rather
than loudly. T29's portability proof now depends on T37 and covers every per-building file kind.

## 5. Risks and honest caveats

1. **Phase E numbers assume synthetic feeds count as "answerable".** For the paper, label them as pipeline-validated, data-simulated. Real-hardware claims need real sensors.
2. **The 60.5% ceiling is not 100%.** The remaining 1,914 rows each need a niche feed; the plan makes each one ~30 minutes of YAML (T19 playbook), but someone still has to do them per deployment. Say this plainly in the paper — it's the honest version of the contribution.
3. **HBCO mining quality** depends on the corpus; T01 keeps a human-review CSV in the loop before anything enters the TTL.
4. **Actuation safety**: simulation driver only in this plan. Wiring a real BMS is out of scope and needs a safety review beyond RBAC.
5. **LLM classifier labels** (the master table) are single-model; T28's replay harness measures *actual* system answers, which is the number that matters for the paper.
