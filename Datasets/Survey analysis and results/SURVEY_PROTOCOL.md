# Survey protocol — the instrument as administered

**Source of record for what participants were actually shown and asked.** Recorded 2026-09-24
from the study team. Everything the paper says about the formative study's design must agree
with this file; where the paper and this file disagree, this file is right.

**Why this matters.** Two errors in the paper were caused by not having this written down:
the study was described as having _four_ stages (it has five), and the corpus was described as
collected from people "unaware of what the building measures" (true of Stage 1 only — Stages
2–4 progressively disclose sensors, live data and themes, which is the entire point of the
design).

---

## Shape of the study

| Stage | Name                       | Disclosure                                        | Produces                                    |
| ----- | -------------------------- | ------------------------------------------------- | ------------------------------------------- |
| 1     | Open Minded                | **none**                                          | free-text questions                         |
| 2     | Sensing & Semantics        | 43 sensors + plain-language descriptions          | questions                                   |
| 3     | Scenario-Based             | 8 spaces + **live 3D view with real sensor data** | questions                                   |
| 4     | Goal-Oriented              | 10 sustainability / well-being themes             | questions                                   |
| 5     | Rankings & Recommendations | — (no chat)                                       | topic ranks, question ranks, written vision |

Stages 1–4 produced the **7,151 questions** analysed in the paper (S1 1,904 · S2 2,003 ·
S3 1,705 · S4 1,539), a mean of 74.5 per participant against a per-stage minimum of 60.
Stage 5 produced the **topic rankings** (Borda), the **within-topic question rankings**, and
the **written vision responses**.

---

## Stage 1 — Open Minded

_"Ask anything — let your curiosity lead."_

**Shown:** a scenario only — _imagine you are inside a smart building (an office, university or
public space) with a built-in AI that can answer anything about it, such as energy,
temperature, air quality, occupancy and security._ Prompt: _based on your own role and daily
experience, what would you ask the building's AI?_

**Deliberately withheld:** sensor lists, examples, hints of any kind.

**Asked for:** roughly 10–25 questions. Not enforced.

> This is the only unprompted stage, and therefore the only one that records what people ask
> before being told what is measurable. Every claim in the paper about "zero-context" or
> "unaware of what the building measures" refers to Stage 1 and to no other stage.

## Stage 2 — Sensing & Semantics

_"Discover what the building can sense."_

**Shown:** a clickable list of **43 sensors and terms**, grouped as:

| Group       | Terms                                                                                                   |
| ----------- | ------------------------------------------------------------------------------------------------------- |
| Environment | Temperature, Humidity, CO₂, VOC, PM2.5/PM10, Ozone, NO₂                                                 |
| Occupancy   | Occupancy, Motion, People Count, Door and Window sensors                                                |
| Lighting    | Lux, Ambient Light, Glare Index                                                                         |
| Acoustics   | Sound Level, Noise Events                                                                               |
| Energy      | kWh, kW, Voltage, Current, Power Factor, Frequency                                                      |
| Utilities   | Gas, Water, Flow Rate                                                                                   |
| HVAC        | Status, Setpoint, Supply/Return Air Temp, Fan Speed, Chiller, Boiler, Pump                              |
| Other       | Air Quality Index, Pressure, Wind Speed, Vibration, Equipment Health, Battery, Smart Plug, Standby Load |

Clicking a sensor revealed a plain-language description — what it measures, why it matters,
how smart buildings use it — ending with a nudge to think of questions. Participants were told
they need not review every sensor, only those that looked interesting or familiar.

**Asked for:** explore what interests you, then roughly 10–25 questions. Not enforced.

## Stage 3 — Scenario-Based

_"Explore real building spaces."_

**Shown:** a carousel of **8 spaces** — Open-Plan Office · Meeting Room · Server Room / Data
Centre · Lobby & Reception · Café & Break Area · Rooftop & External Plant · Car Park & EV
Charging · Stairwells & Corridors. Each card carried a description, what that space monitors,
and three _"picture yourself here"_ hints (e.g. _"Picture yourself in a 2-hour meeting — how
would the air feel after the first hour?"_).

**Also shown:** a **live 3D building view carrying real sensor data**. Participants were
directed to select Floor 5 and click sensor nodes to see historical data charts. A reminder
appeared if the 3D view had not been opened at least once, but it did not prevent
them continuing. **No per-stage target gated progress**: the minimums were encouragements, shown as a prompt with the participant's count, and only Stage 5 had to be completed. This was deliberate on ethics grounds. See `SURVEY_INSTRUMENT_AS_ADMINISTERED.md` for the full account.

**Asked for:** explore some spaces and the 3D view, then roughly 10–25 questions. Not enforced.

> Stage 3 is a stronger manipulation than "spatial context": participants saw _actual
> historical readings_ from the deployment building, not a floor plan.

## Stage 4 — Goal-Oriented

_"Sustainability & well-being goals."_

**Shown:** a carousel of **10 themes** — Energy Efficiency · Thermal Comfort · Lighting ·
Indoor Air Quality · Acoustic Comfort · Data Analysis & Insights · Indoor Transport · Indoor
Pollution · Water Usage · Land Use & Ecology. Each carried a description, keywords (PMV/PPD,
baseload, glare, VOCs, leak detection) and three example "ideas".

**Asked for:** explore some themes, then roughly 10–25 questions or goals. Not enforced.

## Stage 5 — Rankings & Recommendations

No chat. Three tasks; the Finish button stayed locked until all three were complete.

### Task 1 — Rank 20 topics

Temperature · Air Quality · Lighting · Noise · Energy · Security · Occupancy · Fire Safety ·
Water · Waste · Solar/Renewables · Green Spaces · Health & Well-being · IoT & Data Analytics ·
Lifts & Internal Transport · Parking & EV Charging · Automation & AI · User Apps & Digital
Interaction · Maintenance & Faults · Carbon & Net Zero.

All 20 ranked by importance for future smart buildings, by clicking or dragging.
→ **This is the source of the Borda scores.**

### Task 2 — Rank example questions within their top 10 topics

Four example questions per topic, one at each complexity level:

| Level | Instrument name     | Definition given to participants                                      |
| ----- | ------------------- | --------------------------------------------------------------------- |
| L1    | 🟢 **Basic**        | a simple fact or current reading (_"What is the current CO₂ level?"_) |
| L2    | 🔵 **Intermediate** | comparisons across zones or spaces                                    |
| L3    | 🟠 **Advanced**     | trends and patterns over time from sensor data                        |
| L4    | 🔴 **Expert**       | reports, visualisations, recommendations and alerts                   |

Ranked most to least helpful, for all 10 topics — 40 rankings per participant.
→ **This is the source of the within-topic complexity preferences.**
**Use the instrument's own names (Basic/Intermediate/Advanced/Expert) in the paper**, not
invented glosses such as "lookup / aggregation / forecast".

### Task 3 — "Your Vision for a Talking Building"

Imagine a ChatGPT-like building assistant anyone can use, with or without technical knowledge.
Five open-ended prompts, ≥ 20 words each:

1. **Real Scenarios & Unmet Needs** — a real time you wished you could ask the building something
2. **Interaction & Response Preferences** — how answers should come back (text, charts, alerts, dashboards, voice)
3. **Trust, Privacy & Concerns** — what would make them trust it, and what would stop them using it
4. **Success Criteria & Impact** — what would make it useful for their role, and how to measure that
5. **Current Tools & Pain Points** — what frustrates them about today's dashboards or BMS

**FOUND 2026-09-24** — `inputs/recommendations.csv` and `.json`. **59 of 96** participants
completed it: 295 responses, 9,396 words. Analysed by `scripts/Z_stage5_vision_analysis.py`
→ `outputs/tables/Z_stage5_vision_themes.csv`, and reported in the paper at §3.15 (`sec:vision`).

Two things the analysis found that must travel with any use of this data:

1. **Non-response is not random.** Accountable roles (facility management, ownership, health
   and safety, sustainability and energy) completed it at **34%** against **79%** for
   occupant-side roles, Fisher exact _p_ < 0.0001. Sustainability and energy: 2 of 12. They
   did **not** disengage earlier — their S1–S4 question counts are indistinguishable from
   everyone else's (Mann-Whitney _p_ = 0.28). They engaged with structured elicitation and
   declined open reflection.
2. **Nine participants, all Student/Researcher, submitted near-identical trust statements.**
   Report frequencies with that cluster removed; the paper does. Removing it changes no
   ordering and moves no reported figure by more than 9.1 points.

---

## Completion and quality control

- Confirmation prompt, then a unique reference number.
- **The study team reviewed and validated all participant submissions before approving payment, ensuring high response quality, coherence, and genuine engagement.** This manual quality control guarantees that every question in the corpus represents authentic participant input.
- Optional 1–5 star rating of the survey experience.

---

## Canonical Corpus, Data Protection & Research Artifacts

### 1. Canonical Master Corpus
- **`corpus/classified_corpus.csv`** is the **single master corpus of record** received from the **96 participants**.
- It contains **7,151 records** annotated across the 6-tuple taxonomy (`domain_l1`, `query_type_l2`, `intent`, `temporal`, `spatial`, `complexity`), along with participant identifier, persona category, elicitation stage (1–4), timestamp, and verbatim question text.

### 2. Participant Anonymisation Protocol
- In compliance with institutional research ethics and privacy standards, raw survey platform identifiers and usernames were stripped and mapped to stable anonymous identifiers: **`P01` through `P96`** (ordered chronologically by first participation timestamp).
- The mapping is maintained separately in `outputs/intermediate/username_to_pid.csv` for data provenance and is excluded from public supplementary materials.

### 3. Survey Instruments and Associated Artifacts
| Artifact Path | Instrument / Source | Description |
| ------------- | ------------------- | ----------- |
| `corpus/classified_corpus.csv` | Stages 1–4 (Master Corpus) | 7,151 question records from 96 participants (P01–P96) with 6-tuple taxonomy classifications. |
| `inputs/questions_by_user_unique.csv` | Stages 1–4 (Deduplicated) | 6,117 unique questions produced by deterministic canonical de-duplication (`scripts/clean_duplicate_questions.py`). |
| `inputs/topic_rankings.csv` / `.json` | Stage 5 Task 1 | 91 participants ranking 20 smart building domains (input for Borda counts and Kendall's $W$). |
| `inputs/question_rankings.csv` / `.json` | Stage 5 Task 2 | 760 rankings of 4 within-topic depth levels (Basic, Intermediate, Advanced, Expert). |
| `inputs/recommendations.csv` / `.json` | Stage 5 Task 3 | 59 participants providing 295 open-ended vision responses (9,396 words) across 5 qualitative prompts. |
| `inputs/topics_reference.csv` | Survey Metadata | Master definitions of the 20 smart building domains. |
| `inputs/questions_reference.csv` | Survey Metadata | Master definitions of the 4 depth levels per domain. |

---

## Checklist for the paper

- [x] Five stages, not four — four question-eliciting plus one ranking
- [x] "Unaware of what the building measures" applies to **Stage 1 only**
- [x] Stage 2 disclosed **43** sensors across 8 groups
- [x] Stage 3 included a **live 3D view with real readings**, not just floor plans
- [x] Stage 4 offered **10 named themes**
- [x] Complexity levels are **Basic / Intermediate / Advanced / Expert**
- [x] Borda scores and complexity preferences both come from **Stage 5**
- [x] Responses were **screened for authenticity** before payment
- [x] Task 3 vision responses located (`recommendations.csv`), analysed, and in the paper
- [x] Canonical master corpus confirmed as `corpus/classified_corpus.csv` (7,151 records, 96 participants, P01–P96)
- [x] Unique deduplicated corpus created at `inputs/questions_by_user_unique.csv` (6,117 questions)

---

## What was compulsory, and what was not

Nothing in Stages 1-4 was enforced. Moving on with fewer questions raised a prompt showing the
running count and inviting more; the participant could continue or skip at will. Compelling a
response would not have been consistent with the consent given.

Participants were asked for roughly **10 to 25 questions per stage** - the range the MTurk
bonus was scaled to. The per-stage figures that earlier versions of this file described as
targets were design intent and were never enforced.

**Only Stage 5, the ranking task, was compulsory.** The Finish button stayed locked until its
three parts were done.

Counts in the corpus should therefore be read as what people chose to contribute, not as a
quota met.
