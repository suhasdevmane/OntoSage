# V10 review — independent verification

**Verified:** 2026-09-06 · bldg1 active, stack up, response cache flushed · local `gpt-oss:20b`
**Subject:** [`V10_REVIEW_AND_PLAN.md`](./V10_REVIEW_AND_PLAN.md), written by another model
**Method:** re-ran the contested probe questions through the live API; queried GraphDB and MySQL
directly; read every file:line the review cites.

---

## Verdict

**The review is substantially correct and worth acting on.** Every one of the five live failures
reproduced, and 29 of its structural claims check out at the file and line it names. Its ordering
principle — fix the routing and integrity defects before adding more registers — is right.

**Three things are wrong, and one of them matters a lot.** The CO₂ root cause is mis-located: the
file the review blames was already fixed and the fix it proposes would change nothing. The
"34 of 39 record classes have zero instances" claim is false for bldg1. And the headline "~800
hard-coded strings" is an unsupported number.

**Three things are worse than the review says**, most importantly the dangling-reference defect,
which it found as one lift and which is actually 22% of the building's asset statuses.

This session's own history is the reason for the re-verification, not distrust of the reviewer:
the measurement apparatus in this project has been wrong more often than the system, and a
review is measurement.

---

## 1. Confirmed — reproduced independently

### The five live failures (all reproduced, cache flushed, 2026-09-06)

| # | Question | What came back | Review right? |
|---|---|---|---|
| 2 | How many sensors are there in total? | "Sensors declared **2,720**", "reported in the last 24 h **2,763**", "**Floors: 8**" — in a six-storey building | ✅ |
| 5 | Which rooms are on floor 2? | intent `capability`, six rooms sourced from *"Cleaning Task Register, Public Event Register, Timetabled Sessions"*. GraphDB holds **48** | ✅ |
| 6 | Is the lift working? | *"This building has no lifts recorded in its model"* | ✅ |
| 10 | What is this building and who runs it? | intent `privacy_refusal` — *"The system explains the building; it never tracks individuals"* | ✅ |
| 11 | Which rooms are stuffy right now? | *"I don't have the live CO₂ or temperature readings…"* then a sensor-**count** table per space | ✅ |
| 9 | Compare avg CO₂ floor 1 vs floor 3 | **157 ppm vs 111 ppm** + *"Actionable recommendation: install or verify adequate ventilation"* | ✅ symptom, ✗ cause (§2.1) |

Outdoor air is ~420 ppm. An indoor average of 111 ppm is not a low reading; it is not a reading.

### Graph and data facts

```sparql
SELECT ?f WHERE { ?f a brick:Floor }
→ Floor0 … Floor5, Parking_Level_Ground, Rooftop          # 8, hence "Floors: 8"

SELECT ?p ?o WHERE { bldg:Lift_Main ?p ?o }
→ (empty)                                                  # the status points at nothing
```

`asset_state_service._status_query` opens with `?asset a ontosage:{class_local}`, so an untyped
asset cannot match however many statuses point at it. Mechanism confirmed exactly as described.

### Code claims — every one checked at the cited line

| claim | verdict |
|---|---|
| `INDIVIDUAL_PRESENCE_RE` contains a bare `(?:and\|but)\s+who` clause | ✅ `privacy/inference_classes.py` |
| `ontosage:` missing from `sparql_validator._PREFIX_INJECT` | ✅ (so is `hbco:`) |
| `floor_plan_service` invents rooms `f"{floor}.{n:02d}"` for n=1..14 when PDF text is empty | ✅ contract 3 **and** 4 |
| `anomaly/diagnosis.py` literal `stored_at: "plant_data"` | ✅ |
| `building_context.py` reads `building_prefix` / `building_timezone` | ✅ **and worse** — bldg1's `building.yaml` writes *neither* key, nor a timezone; bldg2/3/4 write `ontology_prefix`. The prefix always falls to the env default |
| `self_correction_engine.py:253` defaults the namespace to `http://example.com/building#` | ✅ |
| `adapters/registry.py` no-YAML path hardcodes `database1` / `database2` | ✅ |
| `shared/config.py` `BUILDING_ABOX_FILE` default `trial/dataset/bldg1_protege.ttl` | ✅ |
| `./data/bldg1:/staging:ro` survives every swap | ✅ **and worse** — present in `docker-compose.yml`, `.bldg2.yml`, `.bldg3.yml`, `.bldgtest.yml` |
| `check_building_literals.py` scans `orchestrator` + `shared` only | ✅ `SCAN_ROOTS = ("orchestrator", "shared")` |
| SPARQL prompt teaches `Room_5.01` / `CO2_Level_Sensor_5.08` / `CONTAINS "5.08"` | ✅ six sites in `sparql_agent.py` |
| `AlarmEvent` / `AnomalyEvent` / `AccessEvent` — declared, no mapping, no instances | ✅ 0 instances, no YAML in `ontology/record_documents/` |
| `SustainabilityTarget` has a mapping but is outside `_DISCOVER_QUERY`'s roots | ✅ absent from the discovered class list |
| `grep _deliberate_node tests/` returns nothing | ✅ **zero** files |
| `ONTOSAGE.md` never says "ARBITER" or "dossier" | ✅ 0 and 0 |
| `DELIBERATE_CLARIFY_OFF` / `CQIR_COMPILE_CACHE` in no `Settings`, no `.env*` | ✅ |
| `dialogue_response` checked **second**, above every computed lane | ✅ `_orchestrator.py:4189` |
| `input/_templates/` ships 5 files | ✅ |
| register documents 37 / 10 / 1 / 1 across bldg1-4 | ✅ exactly |
| `.env.example` lacks **31** settings the live `.env` uses | ✅ exactly 31 |
| `_heuristic_grade` never reads the question | ✅ its own docstring says so |
| `/new-building` calls `--building-id` (the script takes `--id`) and queries repository `ontosage` (real: `bldg`) | ✅ both |
| `CLAUDE.md` orientation says branch `main`, V6, 2,488 tests | ✅ reality: `development`, V7, 5,004 |

---

## 2. Wrong

### 2.1 The CO₂ root cause is mis-located — and the proposed fix is a no-op

The review blames `mysql_dummy_publisher.py:315-345`, the wide-table type fallback.

That code was already fixed on 2026-09-03. `_WIDE_RANGES` maps `"co2" → (400.0, 1200.0)` and
carries a comment explaining the exact failure the review is describing. Changing it does nothing.

The real path, traced end to end:

```
brick:CO2_Sensor  CO2_Level_Sensor_1.04
  → ref:storedAt bldg:database1_floors04        (narrow table sensor_data_floors04)
  → SELECT … FROM sensor_data_floors04 WHERE uuid=… AND datetime > NOW()-7d
       n=6,381  min=0.0  avg=74.1  max=150.0     ← still being written today
```

The generator is `input/bldg1_extended_narrow_uuids.json`:

| class in the publish map | rows | lo–hi | class in the graph |
|---|---|---|---|
| `Air_Quality_Sensor` | **174** | **0–150** | `brick:CO2_Sensor`, named `CO2_Level_Sensor_N.NN` |
| `Air_Temperature_Sensor` | 174 | 18–28 | ✅ agrees |
| `Humidity_Sensor` | 174 | 30–70 | ✅ agrees |

0–150 is an **AQI** band. Every floor 0–4 CO₂ sensor — 174 of them — has been emitting an AQI
number that the answer layer labels "ppm", continuously, and no gate anywhere notices.

This reframes the fix. It is not a range table typo. It is a **cross-source type disagreement**:
the graph and the publish map name different classes for the same UUID, and nothing compares
them. That is generically detectable and worth a validator, which is a better outcome than the
review's proposal would have produced.

### 2.2 "34 of 39 record classes have zero TTL instances in every building" — false for bldg1

Measured on the live graph: **36 of 40** discovered record classes carry instances on bldg1.
Only the three event classes are empty.

```
TimetabledSession 675 · ComplianceCheck 82 · StakeholderGroup 82 · AssetStatus 64 ·
ApprovalRecord 32 · FireSafetyAsset 30 · CleaningTask 30 · WorkspaceProfile 28 …
AlarmEvent 0 · AnomalyEvent 0 · AccessEvent 0
```

The underlying finding survives — the data is one building's hand-authored document set, and
bldg2/3/4 have 10/1/1 documents — but the sentence as written would send someone hunting a bldg1
defect that is not there.

### 2.3 Smaller factual errors

| review says | measured |
|---|---|
| `data/few_shot_library.json` | the file is `orchestrator/data/few_shot_library.json` |
| "60+ hardcode `Path("input")`" | **33** in `orchestrator/`+`shared/`, 44 including `scripts/` |
| "referent gate runs in 2 of ~18 lanes" | **one** call site in the whole orchestrator |
| "16 `and not` clauses" on the capability short-circuit | **21** |
| Q7 nearest accessible toilet → `planner` returned the floor 3 plan | reproduced as `spatial_query`: *"No toilet is reachable from 3.10 in the floor-plan adjacency data"* — still a non-answer, different lane and different failure |
| "~800 hard-coded strings" | **unsupported.** No method is given. Its own §2.4 audit found 141 raw hits and 15 real defects. 800 appears to count every string inside every regex and frozenset, which is not the same thing as a building literal — and conflating them makes the real finding (vocabulary coupling) harder to act on, not easier |

---

## 3. Understated — worse than the review says

### 3.1 The dangling reference is 22% of asset statuses, not one lift

```sparql
SELECT ?st ?asset WHERE {
  ?st a ontosage:AssetStatus ; ontosage:statusOf ?asset .
  FILTER NOT EXISTS { ?asset a ?t } }
→ 14 rows of 64 total statuses
```

`AccessibilitySummary` · `BikeStorage_Outdoor` · `Cafe_Ground` · `CybersecurityLab` ·
`Lift_Main` (twice) · `Makerspace` · `NursingRoom_F2` · `PrayerRoom_104` · `Reception` ·
`ShowerFacility_F1` · `StudyArea_F1F2` · `Toilets_AllFloors` · `TradingRoom`.

Every one is an amenity a visitor or an occupant would ask about, every one has a status record
written for it, and every one answers *"not recorded in this building's model"*. The review found
the lift because it asked about the lift.

### 3.2 The CO₂ defect is a whole modality on five floors

174 sensors, not a rounding problem. Any question about air quality on floors 0–4 — "is it
stuffy", "compare the floors", "is ventilation adequate" — has been answered from AQI numbers
presented as ppm, and #9 shows it terminating in a capital-expenditure recommendation.

### 3.3 `measurand_kinds.ttl` already exists

The review's A4 proposes creating `ontology/measurand_kinds.ttl` to hold physical bands. The file
is already there with 8 declarations (it exists to state what confusable Brick classes actually
measure). It needs `ontosage:physicalMin/Max` added, not creating — which makes A4 cheaper than
the review sizes it.

---

## 4. Where I disagree with the plan, not the findings

**A2 says "delete the 16 `and not` clauses."** There are 21, and each one is a measured incident
with a comment naming the question it protects. Deleting them wholesale trades six known-fixed
failures for one known-broken one. The right move is the *inversion* the same item proposes —
probe documents **after** classification, as a scored target — which makes the exception list
unnecessary rather than merely absent. That inversion must land with the regression probe
extended first to cover the shapes those 21 clauses protect, or the probe cannot tell success
from a silent trade.

**"Nothing in Phase C until A and B."** A6 and A7 are data-integrity fixes measured in hours that
each remove a live wrong answer. They should not queue behind a week of lexicon work.

**D2's "rename the lane or make it the brain."** Neither. The honest third option is to say in
`ONTOSAGE.md` what the lane actually is — a symbolic ranking and evidence layer reached by one
intent — and delete the "brain routes everything" claim. Renaming a directory to settle a
documentation error is churn.
