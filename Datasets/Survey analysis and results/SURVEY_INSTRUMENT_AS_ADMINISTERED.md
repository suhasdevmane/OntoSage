# The survey as participants experienced it

What each screen showed, what was asked for, and what came back. This is the fullest account
of the instrument; `SURVEY_PROTOCOL.md` is the condensed version used to check the paper.
Where the two differ, this file is the more detailed and should be preferred.

Participants went through three phases: onboarding, five guided stages, and a completion step.
In Stages 1–4 they typed questions to the building into a chat box. **The chat did not answer
anything; it only saved the questions.** Stage 5 had no chat — it asked them to rank topics and
questions and write longer answers.

---

## Landing page

**Given.** A welcome message and an overview of the five stages, and a note that they would be
chatting with a smart building, imagining they were inside it. The chat would not answer yet,
because we were collecting their questions in order to build a system that could answer them
later.

**Expected back.** Nothing. They clicked "Start Survey".

---

## Onboarding: three steps on one screen

### Step 1 — Study information

**Given.** The study title, *A Survey-Based Study to Develop a Corpus of Natural Language
Queries for Smart Building Interaction*; the ethics reference; and a contact email for help. A
warning box stated that participants should **not use AI-generated text** (such as ChatGPT)
because we wanted their own words, and that the survey takes about **90 minutes**.

**Expected back.** Download or view the full Participant Information Sheet (PDF).

### Step 2 — Consent form

**Given.** Nine consent statements covering: that they had read and understood the information
sheet; that participation is voluntary and they may withdraw at any time with their data
deleted; who can access the data and how it is protected; that anonymised quotes may be
published; and agreement to take part.

**Expected back.** Every statement ticked (or "Select All") and their name typed. This produced
a signed consent PDF with typed e-signatures and a timestamp, and saved the consent record.

### Step 3 — Login / Register

Unlocked only after consent.

**Given.** A list of **14 user profiles**: Facility Managers / Building Maintenance Teams ·
Building Owners / Property Managers · Occupants / Tenants / Employees · Health and Safety
Officers · Sustainability and Energy Management Teams · Compliance and Regulatory Bodies ·
Insurance Companies · Architects / Building Designers · Students / Researchers / Academics ·
IT / Data Scientists · Ontology Experts · Vendors / Service Providers · Real Estate Developers ·
Guests / Visitors.

**Expected back.** One or more profiles (at least one required) and a username. There was no
password.

> The sign-up list offered **Ontology Experts**. In the analysis that participant was merged
> into *Sustainability and Energy Management Teams*, which is why the reported persona count is
> eight rather than fourteen.

---

## Stage 1 — Open Minded
*"Ask anything — let your curiosity lead."*

**Given.** A scenario only: imagine you are inside a smart building (an office, university or
public space) with a built-in AI that can answer anything about it, such as energy,
temperature, air quality, occupancy and security. The prompt asked what they would ask the
building's AI, *based on their own role and daily experience*. No hints, sensor lists or
examples — this stage was deliberately unprompted.

**Expected back.** Free-text questions typed into the chat. Target: **at least 15 questions**.

---

## Stage 2 — Sensing & Semantics
*"Discover what the building can sense."*

**Given.** A clickable list of **43 sensors and terms**:

| Group | Terms |
|---|---|
| Environment | Temperature, Humidity, CO₂, VOC, PM2.5/PM10, Ozone, NO₂ |
| Occupancy | Occupancy, Motion, People Count, Door and Window sensors |
| Lighting | Lux, Ambient Light, Glare Index |
| Acoustics | Sound Level, Noise Events |
| Energy | kWh, kW, Voltage, Current, Power Factor, Frequency |
| Utilities | Gas, Water, Flow Rate |
| HVAC | Status, Setpoint, Supply/Return Air Temp, Fan Speed, Chiller, Boiler, Pump |
| Other | Air Quality Index, Pressure, Wind Speed, Vibration, Equipment Health, Battery, Smart Plug, Standby Load |

Clicking a sensor showed a plain-language description — what it measures, why it matters, how
smart buildings use it — ending with a nudge to think of questions. Participants were told they
need not review every sensor, only those that looked interesting or familiar.

**Expected back.** Questions inspired by the sensors. Targets: **15 sensors explored, 20
questions**.

---

## Stage 3 — Scenario-Based
*"Explore real building spaces."*

**Given.** A carousel of **8 building spaces**: Open-Plan Office · Meeting Room · Server Room /
Data Centre · Lobby & Reception · Café & Break Area · Rooftop & External Plant · Car Park & EV
Charging · Stairwells & Corridors. Each card carried a description, what that space monitors,
and three *"picture yourself here"* hints — for example, *"Picture yourself in a 2-hour meeting
— how would the air feel after the first hour?"*

Also shown: a **live 3D building view carrying real sensor data**. The quick guide directed
participants to select Floor 5 and click sensor nodes to see historical data charts.

**Expected back.** Questions tied to specific spaces. Targets: **5 scenarios explored, 15
questions**, and the 3D view **opened at least once** — if it had not been, a reminder appeared
before they could move on.

---

## Stage 4 — Goal-Oriented
*"Sustainability & well-being goals."*

**Given.** A carousel of **10 themes**: Energy Efficiency · Thermal Comfort · Lighting · Indoor
Air Quality · Acoustic Comfort · Data Analysis & Insights · Indoor Transport · Indoor Pollution
· Water Usage · Land Use & Ecology. Each carried a description, keywords (PMV/PPD, baseload,
glare, VOCs, leak detection) and three example "ideas".

**Expected back.** Questions or goals supporting a sustainable, healthy building. Targets:
**4 themes explored, 10 questions**.

---

## Stage 5 — Rankings & Recommendations

No chat. Three tasks; the Finish button stayed locked until all three were done.

### Task 1 — Rank 20 topics

Temperature · Air Quality · Lighting · Noise · Energy · Security · Occupancy · Fire Safety ·
Water · Waste · Solar/Renewables · Green Spaces · Health & Well-being · IoT & Data Analytics ·
Lifts & Internal Transport · Parking & EV Charging · Automation & AI · User Apps & Digital
Interaction · Maintenance & Faults · Carbon & Net Zero.

**Expected back.** All 20 ranked by importance for future smart buildings, by clicking or
dragging.

### Task 2 — Rank example questions within the top 10 topics

Four example questions per topic, one at each complexity level:

| Level | Shown as | Definition given to participants |
|---|---|---|
| L1 | 🟢 Basic | a simple fact or current reading (*"What is the current CO₂ level?"*) |
| L2 | 🔵 Intermediate | comparisons across zones or spaces |
| L3 | 🟠 Advanced | trends and patterns over time from sensor data |
| L4 | 🔴 Expert | reports, visualisations, recommendations and alerts |

**Expected back.** The four ranked most to least helpful, for all ten topics — 40 rankings in
total. This records which level of complexity each person values.

### Task 3 — "Your Vision for a Talking Building"

**Given.** Imagine a ChatGPT-like building assistant anyone can use, with or without technical
knowledge. Five open prompts:

1. **Real Scenarios & Unmet Needs** — a real time you wished you could ask the building something
2. **Interaction & Response Preferences** — how answers should come back (text, charts, alerts, dashboards, voice)
3. **Trust, Privacy & Concerns** — what would make them trust it, and what would stop them using it
4. **Success Criteria & Impact** — what would make it useful for their role, and how to measure that
5. **Current Tools & Pain Points** — what frustrates them about today's dashboards or BMS

**Expected back.** A written answer to **all five prompts, at least 20 words each**.

---

## Completion

**Given.** A confirmation prompt, a unique **reference number**, and instructions to submit
that number on the participation portal (MTurk) to claim the reward. The team reviewed answers
first to check they were genuine and not AI-generated.

**Expected back.** An optional 1–5 star rating of the survey experience, and the reference
number submitted on MTurk.

---

## How the rules actually worked

These four points matter for interpreting the counts, and none of them is visible in the data
files.

**The per-stage minimums were encouragements, not hard blocks.** Clicking "Next" below a target
raised a pop-up showing the participant's count and encouraging more, but they could continue
regardless. The only genuine requirement was Stage 5, which had to be completed before
finishing.

**The chat's own guidance disagreed with the stage targets.** Most replies were just
"✅ #N saved." At question 10 the reply said *"we're looking for around 20–25 questions in this
stage"*, and at 20 it praised them and suggested adding more for extra credit. The 20–25 figure
does not match the per-stage targets of 15 / 20 / 15 / 10. Some participants will have read the
chat's number as the real goal, so the targets above describe the design, not necessarily what
each participant believed they were being asked for.

**Questions were tagged by username and stage.** Participants could leave and return later with
the same username.

**The persona list was collapsed for analysis.** Fourteen sign-up profiles became eight reported
personas, with Ontology Experts merged into Sustainability and Energy Management Teams.
