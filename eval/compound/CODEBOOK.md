# Compound-question codebook — T-REAL, its supplement, and T-CAT

**Frozen 2026-10-07**, before any v2 code was committed. Written before the candidate pools were
read, then applied in one pass by the isolated agent that built the sets. Section 9 lists every
rule that had to be made more precise while coding, so a reader can see what was decided after
contact with the items; none of it was decided after seeing any v1 or v2 answer. The same rules
were applied to all three pools, and to every item in each pool (§5).

The examples in this file are either quoted from `tasks/V2_COMPOUND_PLAN.md` (already seen by the
developer) or invented for this file. **No example is a test item.**

The codebook decides three things for each candidate, in this order:

1. **Eligibility** — is it a question the building's own data could answer at all? (§1)
2. **Compoundness and shape** — does the answer need at least two facets combined by one of the
   six operations C1–C6? (§2–§3)
3. **Answerability for bldg1** — FULL / PARTIAL / NONE, against the facet inventory in §6. (§4–§6)

The decisions are frozen in `LABELS.json`, keyed by a hash of the question (never its text), with
the codes in §8. `LABELS.json` is **sealed** with the test files, because it shows each held-out
item's shape and facets; `build_sets.py` and this file carry no item-level information.

---

## 1. Not eligible (decided first; one code)

| Code | Rule | Invented example |
|---|---|---|
| `NC:CAPABILITY` | Asks whether the building or system *can* do something, or asks it to act: alert, notify, control, adjust, book, configure, integrate. | "Can the system warn me when CO2 gets high?" |
| `NC:PROCEDURE` | How-to, procedure, rule, policy, responsibility or contact. | "What should I do if a lift breaks down?" |
| `NC:OPINION` | Advice, suggestions, design or policy opinion, "how could X be improved/reduced", satisfaction or perception asked of the system. A recommendation that reduces to ranking or filtering the building's own entities on its own data is *not* this code — score it as C1/C3. | "How could the building become more sustainable?" |
| `NC:GENERIC` | General knowledge, not about this building. | "What CO2 level is healthy?" |
| `NC:HYPOTHETICAL` | What-if, counterfactual, simulation, or the saving from a change not yet made. | "How much would we save by switching lights off at 6 pm?" |
| `NC:EXPLAIN` | An open "why"/diagnosis that names no second series or event to relate to. | "Why is it always hot in here?" |
| `NC:OFFTOPIC` | Not about this building or its operation (personal matters, public transport, other sites). | |
| `NC:UNCLEAR` | Cannot be read as a definite request (fragment, two questions merged by the PDF extraction, garbled). | |

"Can you show / tell / give me …" is a request for data and is eligible; "Can the building /
system [do X]" is a capability question.

## 2. Compound means at least two facets combined by one operation

A **facet** is one thing that can be known about one kind of entity: a sensed quantity, a register
field, a TTL property, a structural or spatial relation (room-in-floor, route), or an event stream
(bookings, timetabled sessions, alarms, access events, cleaning shifts, outdoor weather). A time
window is a qualifier, not a facet — except in C4, where two named periods are the point.

`NC:SINGLE` — the answer needs **one** facet: a lookup, list, count, a single aggregate, a trend
over one period, a forecast of one series, an anomaly scan of one series, a threshold check of one
quantity against a generic standard, or a ranking of individual entities by their own value of one
facet (including a time-average of it, and a comparison of two named rooms on one quantity).
**Length and wording do not change this.** A composite lay term ("comfortable", "healthy", "good
for studying") is one criterion unless the question names the facets separately.

## 3. The six shapes (the first rule that matches wins)

| Order | Shape | Rule | Example |
|---|---|---|---|
| 1 | **C6 multi-part** | Two or more separable asks in one message whose answers do not depend on each other and which need different **sources** (§9.6): several sensor modalities read together for one place, or two lookups in the TTL, are one source (`NC:SINGLE`); two different registers, or a sensor and a register, are two. If one ask filters or uses the other's result, it is not C6. | Plan: "What's the temperature on floor 2, and when is the next service?" |
| 2 | **C5 series/event relation** | How one series relates to another series, or to events the building records (occupancy, bookings, timetable, cleaning, alarms, access events, outdoor weather): co-movement, correlation, "when X rises does Y", "after/during". The answer is co-occurrence statistics, never a cause. | Plan: "Do VOC levels spike after night-shift cleaning?" |
| 3 | **C4 period comparison** | One quantity — for one entity or per group — compared across two or more named calendar periods: this vs last week, weekday vs weekend, peak vs off-peak hours, before vs after a date. Periods defined by a *recorded event* make it C5. | Plan: "This week's electricity vs last week's, by floor" |
| 4 | **C1 multi-criteria selection** | Choose, filter or rank a set of entities on two or more criteria that use two or more distinct facets. Two sensed modalities are two facets. Also C1: choosing entities by a criterion and reporting for them a content facet from a different source — a join (§9.5). Fields of ONE record describing ONE named entity are a record lookup (`NC:SINGLE`, §9.7). | Plan: "Find a quiet room for 12 with a projector, free this afternoon, step-free from reception" |
| 5 | **C2 cross-source comparison** | Two facts about the same entity, from different sources or systems, set against each other: measured vs declared (capacity, setpoint, target, budget, design duty, a benchmark row the system holds), sensor vs register, commanded vs measured. Applying such a comparison as the only criterion of a filter (entities whose measured value passes their own declared limit) is C2. A derived quantity of one system from one source kind (supply-minus-return temperature, a filter's upstream-vs-downstream concentration) is `NC:SINGLE` (§9.6). | Plan: "What is the real-time occupancy versus the evacuation capacity?" |
| 6 | **C3 group → aggregate → rank** | One quantity aggregated over a **structural** group — floor, zone, wing, room type or function, system, a set of meters — and the groups compared, ranked, or their spread/evenness described. The structure facet is what forms the groups; per-room rankings are `NC:SINGLE`. | Plan: "Which floor has less crowd now?" · "How evenly is air distributed across areas?" |

Comparisons against a generic external standard (WHO, ASHRAE, a "safe level") are a threshold on
one facet: `NC:SINGLE`. Comparisons against a value the building or system *holds* (its own
setpoint, capacity, target, budget, tariff, or a row of `config/benchmarks.csv`) are C2.

## 4. Answerability for bldg1

`facets_needed` lists short facet names; each is checked against §6.

| Label | Rule |
|---|---|
| **FULL** | Every facet the question needs is held for bldg1, at the granularity and over the span the question asks for. |
| **PARTIAL** | At least one needed content facet is held and at least one is not — or is held only at a coarser granularity or a shorter span than asked. |
| **NONE** | No needed content facet is held. Structure facets used only to group or locate (the floor list, room-in-floor) do not count toward PARTIAL. |

Rules applied the same way every time:

* **Granularity.** A quantity held per floor (energy and end-use sub-meters, electric power, water
  flow, CO, NO2, formaldehyde, TVOC, PM10, PM1, gas) asked per room is held only coarsely →
  PARTIAL.
* **Span.** bldg1 holds weeks of readings for most series (rolling generated history), plus a real
  January–March 2025 snapshot for part of the room sensors. A question needing seasons,
  year-on-year or multi-year history is PARTIAL for that facet ("span").
* **Pattern vs live.** Typical busiest/quietest periods are a register field
  (`WorkspaceProfile`); live occupancy is a sensor. Each satisfies only what it is.
* **Privacy.** Individual-level location, identity or behaviour is not held (policy forbids it);
  a facet that needs it is not held.
* **Derived facets** count as held when every input is held: carbon = energy × the held grid
  carbon-intensity factor; cost = energy × tariff; intensity per m² = energy ÷ floor area.
* A facet "held" means present in the files listed in §6 — the codebook does not certify that a
  given lane can reach it today. That is what separates *missing data* (NONE/PARTIAL) from
  *planning failure*, which is what the evaluation measures.

## 5. Selection rules (applied by `build_sets.py`, not by judgement)

* **The codebook was applied to every item of every pool** — no prefix, no sample. The builder
  refuses to run if any pool item lacks a label.
* **T-REAL** (pre-registered pool: MULTI_STEP + AGGREGATION rows that survive §7): compound items
  only, at most 2 per participant (PID), target 80, stratified across C1–C6 — equal shares, a
  shape with fewer available items gives its remainder to the others, the scarcest shape is
  filled first so a plentiful one cannot use up a participant it needs. Within a shape, items are
  taken in the order of `sha256(seed | key)`. A shape is never padded with a non-compound item.
* **T-REAL-SUPPLEMENT** (added at freeze time, filed separately): the specified pool yields far
  fewer than 80 compound items, because most MULTI_STEP/AGGREGATION rows had already been asked
  (§7). The corpus's complexity label is an LLM classification and does not keep compound
  questions out of LOOKUP, so LOOKUP rows that survive §7 and contain a compound signal word
  (`SUPPLEMENT_SIGNAL` in `build_sets.py`, fixed before any LOOKUP row was read; it decides which
  rows are screened, never how they are labelled) were screened under this same codebook. Its
  items continue T-REAL's participant cap (≤ 2 per PID across both files) and its shares are
  balanced over the union. **It is not part of the pre-registered T-REAL**: the owner decides,
  before any v2 commit, whether the primary analysis uses T-REAL alone or T-REAL + supplement.
* **T-CAT**: compound items only, from catalogue questions that match a canonical text in the
  4,060-question bank (so no two-column PDF merge or header fragment is a test item), at most 2 per
  persona, target 60: one per persona first, then a second for personas in seeded order, each pick
  preferring the shape least represented so far.
* Answerability is **not** used to select. It is recorded so the primary hypothesis can be tested
  on FULL + PARTIAL items, as the plan pre-registers.
* **DEV** is every remaining extracted catalogue question, minus any that would show a test item
  (token-set Jaccard ≥ 0.8 with one, or holding half of a test item's 4-word sequences).

## 6. bldg1 facet inventory (read from files on 2026-10-07)

bldg1 was the ACTIVE building at freeze time, so its files were read from `input/`; in the parked
state the same files are under `bldg1/`.

**Sensed — 45 modalities with readings** (`config/saturation_modalities.yaml`):

* per room: temperature, humidity, CO2, occupancy count, noise, illuminance, door contact, window
  contact, PM2.5, motion, occupancy status, air-quality index, lighting CCT, waste-bin fill and
  weight;
* per floor: energy sub-meter (kWh), electric power (kW), water flow (cold, hot, chilled), water
  flow rate, water level, CO, NO2, formaldehyde, TVOC, PM10, PM1, gas (a **concentration** in ppm,
  not gas-meter consumption);
* building: water usage, solar irradiance, runtime hours, soil moisture, rainfall, actuator
  position, parking free bays, lift state;
* plant equipment: supply/return air temperature, fan state, entering/leaving water temperature,
  damper position, filter differential pressure, supply air flow.

**Other metered/sensed points** (`bldg1_enhancements.ttl`, `bldg1_meter_topology.ttl`): building
electrical and water meters; per-floor electric/energy meters and end-use sub-meters (HVAC,
lighting, plug loads); PV generation (two array power sensors and an export meter); entry counts
(main entrance and floors 1–5); EV charging station power and charger state; lift power and
status; leak detectors; fire-exit door contacts; pump and lift vibration. Outdoor air temperature,
outdoor humidity and wind speed come from the weather feed (`input/feeds.yaml`, enabled).

**Events:** booking register (16) plus the simulated events store (bookings, work orders, access
events); timetabled sessions (675); public events (17) and their activities (24); alarm events
(270: condition, priority, equipment, space, time, acknowledgement); door access events (679:
kind, denial reason, space, time, role); planned and other closures (10); compliance checks (82);
configuration history (2,175).

**Registers** — 38 record classes (`ontology/record_documents/*.yaml`), documents in
`input/documents/`: workspace profile (seats, bookable, power, network rating, daylight aspect,
noise profile, calls, group use, access, hours, busiest/quietest period, set-up/recovery minutes,
nearest vertical route); AV readiness; accessible routes (step-free, distance, minutes, lift);
circulation times between floors; cleaning tasks (zone, area, standard, frequency, shift, last
done, next due); service schedules; maintenance work orders; fire-safety assets; evacuation
provisions; door hardware; hazard controls (COSHH/LEV); risk assessments; permits to work;
incidents and near misses; contracts; warranties; handovers; condition survey (grade, remaining
life); asset engineering (design/commissioned/observed duty, criticality, serves area); stock;
cost lines (budget, actual, committed, accrued); energy tariffs (unit rate, standing charge);
sustainability targets (metric, target, baseline); waste collection points (capacity, fill
threshold, next collection); waste returns (monthly tonnes per stream, diverted %); department
directory (hours, response times, escalation); stakeholder groups; coordination functions;
continuity provisions; approval evidence; competency requirements; access permissions; patrol
checkpoints; HVAC operating regimes (occupied/unoccupied setpoints, operating window).

**TTL properties:** room capacity (67 rooms, estimated, with basis); space → floor structure (six
floors, ~350 spaces); space function; quiet zones; amenities (washrooms with cubicle counts and
provision, accessible toilets, water points, café, showers, first-aid points, two lifts);
accessibility features; AV / lift / Wi-Fi status; building facts (year built, architect,
construction type, roof type); description (function, owner, operator, address); EPC rating; grid
carbon-intensity factor; mould-risk humidity threshold; distance to the main entrance (10 spaces);
meter topology (which meter serves which floor); sensor metrology (sampling interval, calibration
dates); HVAC zone ↔ room links; plant (AHU per floor, VAVs, boilers, chiller, heat pump); security
devices (CCTV, intrusion detectors, coverage); lighting systems; a potability statement.
**Floor plans:** room areas, adjacency, layout. **Config:** benchmark rows
(`config/benchmarks.csv`: energy and heating intensity, average occupied CO2 and temperature,
average humidity, occupancy utilisation, energy per student, carbon intensity, water intensity).
**Text reports:** a complaints source (student complaint reports).

**Not held** (recurring in the survey): occupant satisfaction or comfort votes; productivity,
performance or health outcomes; battery state of charge (the battery is an entity with no
readings); gas-meter consumption; water-quality measurements beyond the one potability statement;
individual-level location or identity; external comparators beyond the benchmark rows; per-desk
occupancy; outdoor air quality or noise; cost per asset beyond the cost-line register; occupant
demographics; traffic or public transport.

## 7. Integrity exclusions (applied before the codebook)

A candidate is removed before it is read for the codebook if any of these holds. All of them were
computed by `build_sets.py --rescan` at freeze time and frozen in `EXCLUSION_SNAPSHOT.json`.

1. **Stated rule** — its lowercase, whitespace-collapsed text is the value of a `question` / `q` /
   `query` key anywhere in `docs/**/*.json(l)` or `scripts/outputs/*.json(l)`.
2. **Punctuation variant** of (1).
3. **Shown to the developer** — the 20 MULTI_STEP questions `scratchpad/unseen_compound.py` printed
   while the plan was written (`random.seed(1)`, reproduced exactly).
4. **Exposed** — its text (or, for a question of at least 14 tokens, its first 12 tokens, since a
   display may truncate) occurs in a development artefact: any text file in the repository and
   its worktrees (code, tests, ontology, building documents, trackers, plans, logs, run outputs,
   the paper sources, and `outputs/query_results/`, which is the orchestrator's own log of every
   question it has answered — 18,169 files at freeze time, a record the stated rule's globs do not
   reach), any session scratchpad or background-task output for this project, any session
   transcript message or persisted tool result, the project memory, or the uncompressed live
   stores (Postgres data and WAL files, Open WebUI's SQLite).
   * A unit holding **500 or more** distinct source questions is a bulk copy (the corpus file and
     its analysis tables, the 4,060-question bank, a whole-corpus reach dump) and says nothing
     about any one question, so it is ignored.
   * Files inside a `Survey analysis and results/` tree — the survey-analysis pipeline's own
     working files: taxonomy coding samples, inter-rater logs, duplicate reports, wherever a copy
     of that tree sits — are recorded but **do not exclude**. They were read to classify the
     survey, not to build or test the system, and every corpus question was read by its
     authors at some point; what has to be excluded is a question the *system* was developed or
     tested against, or that a development session displayed. The snapshot lists the candidates
     this exception kept (`real_candidates_seen_only_in_survey_analysis`).
5. **Near-duplicate** (token-set Jaccard ≥ 0.8) of anything in 1–4, of any `user_query` in the
   query log, of a quoted example in the plan, or of any of the 4,060 bank questions.

Two things the scan cannot see, stated rather than assumed away: compressed live stores (Redis,
MongoDB, GraphDB, Qdrant), and terminal output that was never written to a file or a transcript.
The one known instance of the latter — the parent session's planning peek — is reproduced as
rule 3. The builder's own working folder and its own transcript are left out of the scan: they
hold the pools it had to read in order to label them, and nothing in them reached a developer.

For the catalogue, the 210 spent items (and their near-duplicates) are removed, and the same
exposure scan applies. **Every catalogue question is in the 4,060-question development bank**
(`tasks/smart_building_questions.csv`), which development tools scan in bulk; T-CAT items were
never asked, quoted or printed, but they are not pristine in the way T-REAL items are.

## 8. Label codes

`decision` is `C1`…`C6`, or one of `NC:SINGLE`, `NC:CAPABILITY`, `NC:PROCEDURE`, `NC:OPINION`,
`NC:GENERIC`, `NC:HYPOTHETICAL`, `NC:EXPLAIN`, `NC:OFFTOPIC`, `NC:UNCLEAR`, plus two integrity codes
added while coding (§9.2, §9.3): `NC:DUPLICATE` and `NC:PLAN_EXAMPLE`.
Compound items also carry `answerability` (FULL / PARTIAL / NONE), `facets_needed`, and — for
PARTIAL and NONE — an `answerability_note` naming each facet that is missing, coarse or short.

## 9. Clarifications made while coding

Each was needed to decide items consistently, and each was then applied back over every item
already labelled. None changes §1–§4; they say how §1–§4 meet real wording. They are stated
abstractly on purpose: an example drawn from a pool item could describe a test item.

1. **Groups vs entities.** Words naming the building's own divisions (areas, parts, sections,
   zones, floors) are structural groups — C3 when one quantity is aggregated over them and
   compared, ranked or broken down. Words naming individual places (rooms, spaces, desks,
   workspaces, offices) are entities — `NC:SINGLE` when ranked by one facet. A division is
   satisfied at the granularity at which the building meters it; a quantity metered more coarsely
   than the division asked for is PARTIAL (an HVAC zone is smaller than a floor).
2. **`NC:DUPLICATE`.** An item asking for the same computation as an earlier pool item — same
   quantity, same grouping, same operation, direction (most/least) aside — is not used, so no
   test counts one question twice. This applies within each pool, and across T-REAL and its
   supplement (the T-REAL item wins).
3. **`NC:PLAN_EXAMPLE`.** An item asking the same thing as an example quoted in
   `tasks/V2_COMPOUND_PLAN.md` §1 is not used: the developer wrote and reads those examples. (The
   examples that are verbatim corpus rows were already excluded by §7.)
4. **Mixed asks.** When one part of a message is ineligible (advice, a capability, an open "why")
   and another part asks for data, the ineligible part is set aside and the rest is judged.
5. **Select-then-report is C1.** Choosing entities by one criterion and reporting for them a
   content facet held by a different source is a join, and is C1.
6. **Different sources.** For C6 and C2 a "source" is one sensor read for one place (any number of
   modalities read together), one record class, the TTL description, or one event stream. Several
   quantities read together for one place are one read (`NC:SINGLE`); two different registers are
   two sources. A derived quantity of one system from one source kind (a difference or ratio
   across one unit) is one facet (`NC:SINGLE`). C1 is not restricted this way: two sensed
   modalities are two criteria, as the plan's own "C1, sensed criteria only" row says.
7. **One record, one entity.** Several fields of one record about one named entity are a record
   lookup (`NC:SINGLE`). A filter or ranking over a SET of entities using criteria from two or
   more sources is C1.
8. **Baselines are periods.** Comparing a current value with the same quantity's usual or recent
   past is a comparison across two periods: C4.
9. **Observational vs hypothetical relations.** Asking how one held series bears on another is an
   observed relation: C5. Asking whether something could happen, or what would happen if, is
   `NC:GENERIC` or `NC:HYPOTHETICAL`.
10. **Prioritisation reducible to data.** A "what first" prioritisation that can be ranked from
    held dates, schedules and calendars is C1, not `NC:OPINION`.
11. **Proxies do not hold a facet.** A quantity available only through a proxy is not held:
    PARTIAL when the measured quantity contains the asked one, NONE when it does not measure the
    asked quantity at all.
12. **Coverage within a held facet type** (whether every specific room or asset has a row) was not
    audited row by row: a facet type that is held counts as held unless the question's entity type
    is plainly absent from it.
