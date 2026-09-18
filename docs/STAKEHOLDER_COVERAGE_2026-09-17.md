# Stakeholder coverage: what Abacws can answer today, and what is missing

**Measured 2026-09-17 against the live `bldg1` stack** (all 16 containers up, GraphDB repo `bldg`,
`gpt-oss:20b`). Analysis only — nothing in `orchestrator/`, `shared/`, `input/`, `ontology/`,
`tests/` or `tasks/` was changed, no container was restarted, and `scripts/regression_probe.py`
was not run.

Machine-readable gap rows: [`docs/stakeholder_coverage.csv`](./stakeholder_coverage.csv) (56 rows).
Script: [`scripts/analyse_stakeholder_coverage.py`](../scripts/analyse_stakeholder_coverage.py).
Captured supply evidence: `scripts/outputs/stakeholder_coverage_supply.json`.

> **No answer was graded in this exercise.** This is a supply-and-demand measurement, not a
> triage run. It says what the building holds and whether a question can reach it; it does not
> say whether the answer would be good. RUN1/RUN2/RUN3 did the grading and are not superseded.

---

## 1 · Extraction: 2,960 questions from 37 of 37 catalogues, 0 failures

    python scripts/extract_stakeholder_catalogues.py --dry-run
    → parsed 2960 questions from 38 catalogues
      !! 1 file did not yield 80 questions:  Talking_Abacws_Master_Technical_Report.pdf
      new questions to add: 0

38 PDFs sit in `QuestionBank/Talking_Abacws_37_Stakeholder_Catalogues/`. One of them is the Master
Technical Report, which is not a catalogue and correctly yields nothing. The other **37 each yield
exactly 80 questions — 2,960 in total, with no partial or failed parse**, and all 2,960 are already
in `docs/smart_building_questions.csv` (`Source = stakeholder_catalogue_37`; the file's other 1,100
rows are the `v5_synthetic_bank` and are excluded from everything below).

Confirmed independently from the CSV: 37 distinct `Stakeholder_Role` values, every one with exactly
80 rows.

**Every catalogue record carries its own declaration of what it needs** — `Sensors_Required`,
`Authoritative_Sources`, `Analysis_Required`, `Answer_Boundary`, non-empty on all 2,960 rows. Those
declarations, not the question text, are what the demand side of this analysis reads. A keyword read
of "which room did the marketing team use" lands on "team"; the declaration says "booking history".

---

## 2 · What the building actually holds (supply)

### 2.1 Registers — 43 declared, 40 populated, 3 empty

`docker exec ontosage-orchestrator python -c "... record_classes() ..."` and a SPARQL count over
`rdfs:subClassOf+ o:Record | o:IntervalRecord`:

| | |
|---|---|
| Record classes the ontology declares | **43** |
| Populated (≥1 instance) | **40** |
| **Zero instances** | **3 — `AccessEvent`, `AlarmEvent`, `AnomalyEvent`** |

Largest populated registers: `IntervalRecord` 1,027 · `TimetabledSession` 675 · `ComplianceCheck` 82 ·
`StakeholderGroup` 82 · `AssetStatus` 57 · `ApprovalRecord` 32 · `FireSafetyAsset` 30 ·
`CleaningTask` 30. Smallest: `RiskAssessment` 6 · `SustainabilityTarget` 5 · `Tariff` 4 ·
`ClosurePeriod` 3.

The three empty ones are all **event-shaped**: an alarm that fired, a door that was badged, an
anomaly that was detected. The building has plenty of *state* and almost no *history of things
happening*.

### 2.2 Measured quantities — 44 modalities declared, 6 with zero sensors

From `config/saturation_modalities.yaml` cross-referenced with `scripts/floor_modality_matrix.py`
(8 declared floors; 73 measurand classes carrying `ref:hasTimeseriesId`; 29 points have a
timeseries reference and no floor in the graph):

**Held and well distributed** (floors 0–5, room scope): temperature 650 · humidity 562 · CO₂ 554 ·
PM2.5 856 · air quality 835 · door/window contact 466 · occupancy 275 · occupancy status 243 ·
illuminance 275 · noise 234 · lighting CCT 235.

**Held at floor scope** (one node per floor, floors 0–5): CO 80 · NO₂ 41 · PM1 80 · PM10 80 ·
formaldehyde 40 · TVOC 82 · gas 210 · water flow 9 · water level 11 · energy submeter 6.

**Held at equipment scope**: supply-air temperature 12 · return-air temperature 6 · fan status 6 ·
filter ΔP 12 · supply-air flow 6 · leaving/entering water temperature 4 each (rooftop only).

**ZERO sensors, though the modality is declared in config:**

| modality | sensors | note |
|---|---:|---|
| `lift_state` | **0** | declared as `Availability_Status` / `Elevator_Status`; **neither class exists in the graph** |
| `damper_position` | **0** | no entity of any damper class exists |
| `waste_fill` | **0** | 24 `WasteCollectionPoint` records carry a static `o:fillPercent`; no timeseries |
| `waste_weight` | **0** | no weight point at all |
| `water_flow_hot` | **0** | no `Hot_Water_Meter` |
| `water_flow_chilled` | **0** | no `Chilled_Water_Meter` |

> **Caveat on these counts.** Where the config uses `label_contains` to split a shared Brick class
> (door vs window contact, parking vs footfall, lift vs generic status), the table above does not
> apply that filter, so `door_contact` and `window_contact` both report the same 466 and
> `parking_free` reports 258 where the config's own comment says exactly one is parking. The six
> zero rows are unaffected: their Brick classes are absent from the graph entirely.

### 2.3 Space, geometry, routes

| fact | measured value | source |
|---|---|---|
| Spaces in the graph | 247 (234 `brick:Room`) | SPARQL |
| Rooms with a capacity | **19 of 234 (8.1%)** `hbco:roomCapacity` | SPARQL |
| **Rooms with an area in the graph** | **0** — `brick:area` count 0; one `rec#area` triple in total | SPARQL |
| Floor-plan spaces (6 manifests, schema 2.0) | 354 | `/app/floor_plans/abacws/` |
| …with `area_m2` | 266 (75.1%) | manifests |
| …with `ontology_iri` | 235 (66.4%) | manifests |
| …with `adjacent_spaces` | 260 (73.4%) | manifests |
| …with `capacity` | **0** | manifests |
| Route records | 16 `AccessibleRoute` (routeFrom/routeTo/distance), 49 `nearestVerticalRoute`, 21 `CirculationTime` | SPARQL |
| Capability triples (`Amenity`/`KnowledgeTopic`) | 93 | SPARQL |
| Documents indexed | 39 markdown files in `input/documents/` | filesystem |

### 2.4 External feeds

`input/feeds.yaml` registers **three Open-Meteo feeds — current temperature, humidity and wind
only**. There is no forecast horizon anywhere in the configuration.

---

## 3 · The one number measured by the system itself

Every one of the 2,960 questions was put through the **live register lane's own scorer**
(`record_registry.held_record_class` / `rank_record_classes` / `absent_record_class`, in the
running container, no LLM involved):

> ### The register lane selects **no register at all** for **981 of 2,960 questions (33.1%)**.

This is not my classifier's opinion; it is the product's own vocabulary match returning empty.
For a question whose answer lives in a sensor stream that is correct behaviour. For a question
whose own declaration names a register the building holds, it is a dead end.

**Per role** (all 37 have exactly 80 questions):

| role | silent | % | | role | silent | % |
|---|---:|---:|---|---|---:|---:|
| BMS-HVAC operators | 43 | 53.8% | | Research staff | 25 | 31.2% |
| Researchers and data scientists | 43 | 53.8% | | Lecturers and tutors | 25 | 31.2% |
| People with mobility/sensory needs | 41 | 51.2% | | University estates & asset mgmt | 25 | 31.2% |
| Mechanical and electrical engineers | 41 | 51.2% | | Prospective students and family | 24 | 30.0% |
| Academic office occupants | 39 | 48.8% | | Accessibility, inclusion, well-being | 23 | 28.8% |
| Auditors and certification assessors | 37 | 46.2% | | Emergency coordinators | 22 | 27.5% |
| External maintenance contractors | 36 | 45.0% | | Timetabling team | 22 | 27.5% |
| Undergraduate students | 35 | 43.8% | | PhD students | 20 | 25.0% |
| Facilities managers | 35 | 43.8% | | Security officers | 20 | 25.0% |
| Architects and building designers | 34 | 42.5% | | Room-booking team | 17 | 21.2% |
| IT, network, server-infrastructure | 34 | 42.5% | | Waste-management teams | 15 | 18.8% |
| Energy, carbon, sustainability | 33 | 41.2% | | Access-control administrators | 14 | 17.5% |
| Space-planning teams | 32 | 40.0% | | Insurers and risk assessors | 14 | 17.5% |
| Professional-services staff | 31 | 38.8% | | Fire-safety personnel | 13 | 16.2% |
| Taught postgraduate students | 27 | 33.8% | | Finance and procurement teams | 12 | 15.0% |
| Teaching and AV support | 27 | 33.8% | | Health and safety officers | 11 | 13.8% |
| Cleaning and caretaking teams | 26 | 32.5% | | **Regulatory and compliance teams** | **7** | **8.8%** |
| Emergency responders | 26 | 32.5% | | | | |
| School/university leadership, owners | 26 | 32.5% | | | | |
| Visitors and event attendees | 26 | 32.5% | | | | |

**279 of those 981** (across **33 of 37 roles**) demand a **held** register per their own
declaration *and* name no measured quantity at all — so no lane can serve them. Those are the
purest vocabulary gaps in the corpus. Worst affected: Researchers and data scientists 24,
Cleaning and caretaking 18, Space-planning 16, Estates 14, Energy/carbon 14, Timetabling 14.

### 3.1 A second system-measured finding, unrelated to gaps

Of the 1,979 questions where the register lane **does** select something,
**`ApprovalRecord` wins 498 — 25.2% of every register selection.** One register out of 40 takes a
quarter of the corpus. The next is `PublicEvent` at 7.7%. This is the same shape as RUN1's pattern
#2 ("generic words claim a register", BUG-545) surviving that fix: the qualifier suppression stopped
`permitted`/`verified` counting, but `certificate`, `governance`, `proof`, `assurance`, `sign-off`
and `review due` are still enough to make the governance register the default answer to a quarter of
everything. **Not a gap — a routing risk, and a reason to distrust register-lane answers that come
back headed "approval".**

---

## 4 · The top 10 gaps, ranked by stakeholder groups blocked

Ranked by **roles blocked** (out of 37), not by question count — see §5 for why. "q" is questions,
"silent" is the subset where the register lane selected nothing at all.

| # | gap | kind | roles | q | silent | what specifically is missing |
|---:|---|---|---:|---:|---:|---|
| 1 | `CoordinationFunction` unreachable | **VOCABULARY** | 33 | 390 | 118 | 14 emergency-coordination records exist. Questions say *casualty, responder, fire appliance, assembly point, shelter, escalated, communication channel*; the register's lay terms carry none of those. |
| 2 | `PatrolCheckpoint` unreachable | **VOCABULARY** | 33 | 250 | 93 | 18 records. Wrongly implicated in office/desk/hybrid-working questions — see §5; the genuine half is security-round wording (*rounds*, *walk the building*) already present, plus *confidential*, *out-of-hours cover*. |
| 3 | `AssetEngineeringProfile` unreachable | **VOCABULARY** | 30 | 338 | 114 | 24 records. Questions say *HVAC, electrical, dampers, commissioned, operating mode, control strategy, pressure*; the register's terms are register-speak (*asset tag*, *parent asset*, *isolation point*). |
| 4 | `AccessPermission` unreachable | **VOCABULARY** | 31 | 239 | 75 | 20 records. Questions say *credentials, barriers, secure, personal preferences, journey, managed device*. |
| 5 | **`AlarmEvent` / `AnomalyEvent` / `AccessEvent` hold zero instances** | **DATA** | 25 / 21 / 20 | 65 / 162 / 68 | 19 / 77 / 15 | All three classes are declared in the TBox with lay terms and hold **no records**. Nothing in the building answers "what alarms fired", "what anomalies were detected", "who badged in and when" — and the lane names them as absent for only 24 questions, so the honest decline is itself mostly unreachable. |
| 6 | **Lift availability has no reachable point** | **DATA + VOCABULARY** | 26 | 130 | 0 | `Lift_1_Status_Sensor` exists with a timeseries reference, typed **`brick:Occupancy_Status`**. The `lift_state` modality declares `Availability_Status` / `Elevator_Status`, so it matches nothing; `Lift_2` has a power sensor and no status point at all. Blocks every step-free-route and "is the lift working" question. |
| 7 | **No traversable route graph** | **DATA (partial)** | 23 | 168 | 48 | 16 `AccessibleRoute` records, 49 `nearestVerticalRoute`, 21 `CirculationTime`, 260/354 spaces with `adjacent_spaces` in the manifests — but no joined, whole-building route graph. Itinerary and step-free-alternative questions cannot be computed, only looked up. |
| 8 | **Room capacity: 19 of 234 rooms** | **DATA** | 22 | 52 | 17 | 8.1% of rooms carry `hbco:roomCapacity`; **0 of 354** floor-plan spaces carry a capacity. Blocks "a room that seats N", every occupancy-vs-limit judgement, and space-planning density. |
| 9 | **No weather forecast** | **DATA (partial)** | 19 | 46 | 25 | Three Open-Meteo **current-value** feeds only. Every "next Wednesday / tomorrow / before my class" question — a large share of the student and events catalogues — has no weather input. |
| 10 | **Floor area is not in the graph** | **DATA (partial)** | 6 (direct) | 10 | 5 | 266/354 manifest spaces carry `area_m2`; `brick:area` count in the graph is **0**. `config/benchmarks.csv` normalises energy, heating, carbon and water intensity on `floor_area_m2` — so **five of the building's own benchmark rows cannot be computed**, which silently affects far more than the 6 roles that name area outright. |

Rows 11–20 by roles blocked, from the CSV: `Contract` (31), `Booking` (29), `ComplianceCheck` (29),
`WorkspaceProfile` (29), `ContinuityProvision` (28), `ApprovalRecord` (28), `AssetStatus` (27),
`WorkOrder` (26), `EventActivity` (26), `CostLine` (26) — all VOCABULARY — plus
**`damper_position` zero sensors** (DATA, 20 roles, 59 q) and **`waste_fill` zero timeseries**
(DATA, 11 roles, 20 q).

### 4.1 DATA versus VOCABULARY — the split you asked for

**VOCABULARY (the data exists; the words do not reach it).** Cheap, TTL-only, no new sensors,
no code: add `o:layTerms` to the class in `ontology/ontosage_schema.ttl` or via the admin
Capabilities GUI. Every one of these registers has instances today.

| register | instances | roles | candidate lay terms, taken from the questions that miss it |
|---|---:|---:|---|
| `CoordinationFunction` | 14 | 33 | casualty, fire appliance, responder, assembly point, shelter, escalated, communication channel, damaged |
| `PatrolCheckpoint` | 18 | 33 | confidential area, out-of-hours cover, night round *(see §5 — most of this row is a classifier false positive)* |
| `AssetEngineeringProfile` | 24 | 30 | HVAC asset, electrical asset, dampers, commissioned duty, operating mode, control strategy, pressure |
| `AccessPermission` | 20 | 31 | credentials, barriers, secure area, managed device, personal preferences, journey |
| `Contract` | 8 | 31 | waste contract, collection contract, station, stream, contamination, acceptance criteria |
| `Booking` | 16 | 29 | bookable space, three/four hours, quiet room, seminar slot, hold, release |
| `ContinuityProvision` | 12 | 28 | terminal, utility, heating/cooling dependency, single point of failure, priority service |
| `WorkOrder` | 24 | 26 | corrective action, defect, restoration, overdue job, blocked job, contractor attendance |
| `EventActivity` | 24 | 26 | cohort, seminar, lecture, practical, teaching peak, draft programme |
| `CostLine` | 24 | 26 | lifecycle cost, reuse, supplier, portfolio, replacement, intervention |
| `CompetencyRecord` | 7 | 25 | lone working, escort, controlled experiment, shift cover |
| `FireSafetyAsset` | 30 | 25 | leak, interface, escalation, immediate test |
| `TimetabledSession` | 675 | 24 | cohort, term, week, class, peaks, ventilated session |
| `Department` | 20 | 23 | backlog owner, duty officer, command, site team |

**DATA (no wording could reach an answer).** Needs new records, new points or a new feed.

| gap | what to add |
|---|---|
| `AlarmEvent`, `AnomalyEvent`, `AccessEvent` — 0 instances | three registers, or a lift of the alarm/anomaly/badge history that exists in the source systems |
| Lift availability | a point typed `Availability_Status` (or add `Occupancy_Status` to the `lift_state` modality — a **config** fix, not a sensor one), and a status point for `Lift_2` |
| `damper_position` — 0 entities | damper points from the BMS |
| `waste_fill` / `waste_weight` — 0 timeseries | fill/weight streams; 24 static `fillPercent` values exist and answer "is it full now" but not "how much did we throw away" |
| Room capacity | a capacity on the other 215 rooms (register or TTL) |
| Floor area in the graph | `brick:area` on rooms, or a manifest→graph lift; unlocks 5 benchmark rows |
| Weather forecast | a forecast feed alongside the three current-value ones |
| `water_flow_hot` / `water_flow_chilled` | hot and chilled water meters |

**The distinction in one line, counted from the CSV:** of all 56 gap rows, **39 are VOCABULARY
and 17 are DATA** — and of the **top 25 by roles blocked, 23 are VOCABULARY** (only `lift_state`
and `AlarmEvent` are DATA). The DATA gaps sit lower in the role ranking because fewer roles ask
about lifts, dampers and waste than ask about approvals, assets and continuity. So: **the cheapest
work is also the widest-reaching work**, and the most *visible* gaps — lifts, alarms, capacity,
forecast — are the DATA ones.

---

## 5 · What the classifier can and cannot tell apart

**Method.** Demand is matched against the catalogue's own declaration fields using the **system's
own register vocabulary** (`_ALL_CLASS_TERMS`, 707 terms over 43 classes) plus modality words for
each entry in `saturation_modalities.yaml`. Reachability is the **live product scorer**, not a
reimplementation. Three suppressions, each measured:

1. `Answer_Boundary` is excluded from demand. It states what the answer must *not* do; reading it
   as demand inverts it. UG-002's boundary says sound statistics "cannot … guarantee silence" — and
   including that field filed a study-space question as needing the **Warranty** register, 226 rows
   across 28 roles, almost all spurious.
2. **Boilerplate terms are dropped** (>10% declaration frequency): "owner" appears in 93% of the
   2,960 declarations, "evidence" 91%, "permission" 87%, "access" 68%. 23 terms removed, listed in
   the script output.
3. **Qualifier terms are dropped** — the words the TBox marks `o:qualifierTerms` (*approved*,
   *authorised*, *confirmed*, *permitted*, *verified*, *evidenced*), because BUG-545 stopped them
   selecting a register in the product.

**Measured error rate.** I hand-graded a seeded random sample of **24 rows** (`--sample 24`),
asking only: does the top-3 demand contain a register a careful reader would name?

| verdict | rows |
|---|---:|
| right register present, no spurious sibling | 12 |
| right register present, but a clearly spurious sibling in the top 3 | 5 |
| **right register missing** | **7 (29%)** |

So **roughly 3 questions in 10 are mis-attributed**, in both directions. Two failure shapes
dominate, and both are visible in the table above:

* **Wrong sibling.** Waste questions ("which bins …") demand `Contract` because the declaration
  names a service agreement — genuine demand, but the question is not about the contract. The
  same mechanism inflates `PatrolCheckpoint` with hybrid-working questions and `WasteCollectionPoint`
  with research-methodology ones. **Gap #2 is the row I trust least.**
* **Missed register.** "Which systems started late against today's approved schedule" needs
  `OperatingRegime`; the matcher missed it. "Since the equipment was serviced…" needs
  `ServiceSchedule`; missed.

**Consequence for how to read this report: role counts are robust, question counts are not.**
A 30% noise rate barely moves a count that saturates at 37 (a register touched by 33 roles would
still be touched by ~30 after removing a third of its rows at random), but it moves a raw question
count by roughly that much. **Treat every "q" column as ±30% and act on the role ranking.**

**Three things the classifier cannot do at all:**

* It has no notion of the **capability/amenity lane**. 93 `Amenity`/`KnowledgeTopic` triples answer
  questions like "is there a Changing Places toilet" and this analysis scores them as needing
  nothing. Amenity coverage is therefore **not measured here**.
* It cannot check **columns**. A register with instances counts as held; whether it has the field
  the question needs is unexamined.
* It counts a modality as supplied when points carry `ref:hasTimeseriesId`. It does **not** verify
  rows exist in the backing store, and **BUG-531 is unresolved**: 77 sensors carry two references,
  one synthetic and one real.

---

## 6 · What contradicts an existing assumption

1. **`config/saturation_modalities.yaml` declares four modalities the building has no sensor for.**
   `lift_state` (V5-T10), `damper_position` (V6-T26, "Master Package D"), `waste_fill` and
   `waste_weight` (V6-T43, written up as "the largest wholly-missing domain the category sweep
   found") all resolve to **zero points**. Declaring the modality was recorded as closing the gap;
   it opened a provisioning task that was never done. `waste_fill`'s comment in that file is
   explicit that waste was absent and is now covered — it is not.

2. **The `lift_state` modality cannot match this building's own lift.** `Lift_1_Status_Sensor`
   exists, carries a timeseries reference, and is typed `brick:Occupancy_Status`. The modality
   declares `Availability_Status` and `Elevator_Status`. The gap is a **two-line config edit**, not
   an instrument — and RUN1's item 25 ("step-free alternative") and RUN3's accessibility failures
   are consistent with it having been mis-diagnosed as missing data.

3. **The graph holds no floor area, and five of the building's own benchmarks depend on it.**
   `brick:area` count is 0. `config/benchmarks.csv` normalises `energy_intensity`,
   `heating_intensity`, `carbon_intensity`, `water_intensity` and the office variant on
   `floor_area_m2`. The areas exist — in the floor-plan manifests (266/354) — which means this is a
   **join that was never made**, not data that was never collected. Any benchmark answer produced
   today is either declining, or getting its area from somewhere undocumented.

4. **`docs/V7_demand_by_source_system.csv` reports `it_network` demand at 693 questions / 36 roles.**
   My stricter phrase set (network telemetry, wifi, switch port, server room, comms room, patch
   record) finds **25 questions / 11 roles**. Both are keyword passes over the same declarations and
   I cannot say which is right, but the V7 figure carries the loose token `it_service`, which matches
   ordinary prose. **If IT-network onboarding is being prioritised on the 693 figure, re-derive it
   before spending.** The same caution applies to V7's `space_inventory` 801/30, which does not
   notice that the inventory it counts as demanded has no areas and almost no capacities.

5. **The three empty event registers are nearly invisible as declines.** `absent_record_class`
   names `AlarmEvent` for 20 questions, `AnomalyEvent` for 3 and `AccessEvent` for 1 — 24 of the
   ~295 questions whose declarations demand them. The honest-absence path exists and is reached by
   about 8% of the questions that should reach it.

6. **`ApprovalRecord` takes 25.2% of all register selections.** BUG-545's qualifier fix is working
   (qualifiers no longer select), and the register still dominates. Any claim that the register
   lane routes well should be checked against this before the demo.

---

## 7 · Suggested order, cheapest first

1. **Config-only, minutes:** add `Occupancy_Status` to the `lift_state` modality. Unblocks 130
   questions across 26 roles with no new data. *(Gap 6.)*
2. **TTL-only, hours:** lay terms for `CoordinationFunction`, `AssetEngineeringProfile`,
   `AccessPermission`, `ContinuityProvision`, `WorkOrder`, `EventActivity` — the six vocabulary gaps
   with ≥26 roles and ≥75 silent questions each. Candidate terms are in
   `docs/stakeholder_coverage.csv`, column `candidate_lay_terms`. **Add them one register at a
   time and re-measure §3's 981**, because a register that swallows everything is the failure
   `ApprovalRecord` already demonstrates.
3. **Data lift, days:** floor area from the manifests into the graph (unblocks 5 benchmarks), then
   room capacity beyond the current 19/234.
4. **New records:** `AlarmEvent` / `AnomalyEvent` / `AccessEvent`.
5. **New feed:** a weather forecast horizon.
6. **New instruments (last, and the only items needing hardware):** damper positions, waste fill and
   weight, hot and chilled water meters.

**How to know any of this worked:** re-run
`python scripts/analyse_stakeholder_coverage.py` and watch the "register lane selects NOTHING for
N/2960" line and the per-role table in §3. Both are produced by the product's own scorer, so they
cannot be improved by improving the measurement.
