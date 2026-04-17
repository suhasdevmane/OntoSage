# OntoSage++ Query Taxonomy v1

**Purpose.** A two-level taxonomy with four cross-cutting dimensions for classifying the 5,127 natural-language queries collected in the OntoSage++ pre-design survey. Drafted by inspecting a 200-question random sample (`taxonomy/sample_200.csv`, seed 42).

**Status.** v1 — to be validated by Phase B3 inter-rater reliability (target Cohen's Kappa ≥ 0.70).

---

## Level 1 — Domain (`domain_l1`)

The high-level *subject* of the query. Twenty domains aligned with the 20 topics presented to participants in the topic-ranking survey.

| Code | Domain | Typical concerns |
|------|--------|------------------|
| `THERMAL` | Thermal comfort & temperature | Temperature, setpoints, heating/cooling, comfort range |
| `AIR_QUALITY` | Indoor air quality | CO₂, VOC, PM2.5, humidity, ventilation rates |
| `ENERGY` | Energy use & efficiency | Power, kWh, peaks, sub-metering, cost |
| `LIGHTING` | Lighting & daylight | Lux, schedules, glare, dimming, daylight harvesting |
| `OCCUPANCY` | Occupancy & presence | Headcount, room utilisation, dwell time |
| `SAFETY` | Safety & emergency | Fire, evacuation, alarms, panic, lockdown |
| `SECURITY` | Security & access | Door access, badges, intrusion, cameras |
| `MAINTENANCE` | Maintenance & faults | Equipment status, faults, work orders, MTBF |
| `WATER` | Water use & plumbing | Consumption, leaks, hot-water temp |
| `WASTE` | Waste & recycling | Bin levels, sorting, collection schedules |
| `SUSTAINABILITY` | Sustainability & certification | LEED/BREEAM, carbon, green features |
| `WELLBEING` | Health & wellbeing | Noise, mental wellbeing, stress, biophilic features |
| `WAYFINDING` | Wayfinding & navigation | Room layout, directions, reservations, schedules |
| `CONTROL` | Control & personalisation | Setting changes, personal preferences, automation rules |
| `INFO_REQUEST` | General information | Building hours, ownership, contact, policies |
| `PRIVACY` | Privacy & data | What is recorded, retention, opt-out |
| `ACCESSIBILITY` | Accessibility | Ramps, lifts, sensory accommodations |
| `TRANSPORT` | Transport & parking | EV charging, parking, bike storage |
| `WEATHER_OUTDOOR` | Weather & outdoor environment | External temperature, outdoor air |
| `OTHER` | Out of scope / unclear | Off-topic, gibberish, unparseable |

**Coding rule.** If a query touches multiple domains, choose the one that the *answer* would primarily report on.

---

## Level 2 — Query Type (`query_type_l2`)

The *form of computation* the answer requires. Seven mutually exclusive categories.

| Code | Query type | Indicative pattern | Example |
|------|------------|---------------------|---------|
| `STATUS` | Current status / point reading | "What is …", "right now", "currently" | "What is the current CO2 level" |
| `HISTORICAL` | Historical lookup | "yesterday", "last week", "trend" | "Show me energy use for the last 7 days" |
| `COMPARISON` | Compare entities or periods | "compare", "which … is more", "vs" | "Which room has better air quality right now?" |
| `ANOMALY` | Out-of-range / anomaly detection | "any anomalies", "is X too high", "alert" | "Are any rooms outside ASHRAE 55 comfort range right now?" |
| `RECOMMENDATION` | Prescriptive recommendation | "what should", "how can I", "best place" | "How can seasonal allergens be managed with indoor quality?" |
| `DIAGNOSTIC` | Causal / explanatory | "why", "what is causing", "how does … work" | "Why is the meeting room warm?" |
| `CAPABILITY` | What is possible / what exists | "can you", "is there", "do you have" | "Can you control lights automatically?" |

**Coding rule.** Pick the *most computationally distinct* type — `ANOMALY` outranks `STATUS` when both apply; `RECOMMENDATION` outranks `DIAGNOSTIC` when both apply.

---

## Cross-cutting dimensions

Each query is also annotated on four orthogonal axes.

### `intent` — communicative intent

| Code | Meaning |
|------|---------|
| `INFORMATIONAL` | Request for fact / state retrieval |
| `DIAGNOSTIC` | Understand cause or root reason |
| `PRESCRIPTIVE` | Decide / change / recommend an action |
| `PREDICTIVE` | Forecast or predict future state |

### `temporal` — temporal scope of the answer

| Code | Meaning |
|------|---------|
| `REALTIME` | Current / live state |
| `HISTORICAL` | Past values within a defined window |
| `PREDICTIVE` | Future projection |
| `STATIC` | Time-invariant fact (e.g., square footage) |

### `spatial` — spatial scope

| Code | Meaning |
|------|---------|
| `POINT` | Single sensor or device |
| `ROOM` | One room or zone |
| `FLOOR` | One floor or wing |
| `BUILDING` | Whole building |
| `CAMPUS` | Multiple buildings / outdoor |
| `UNSPECIFIED` | Spatial scope not stated |

### `complexity` — expected query plan

| Code | Meaning | Indicative |
|------|---------|------------|
| `LOOKUP` | Single SPARQL or single SQL row | "What is the current temperature in Room 5.04?" |
| `AGGREGATION` | One groupby / mean / sum / count | "Average CO2 in Floor 5 yesterday" |
| `MULTI_STEP` | Multi-source join, planner, or analytics step | "Compare today's energy with the same day last week and tell me if it's anomalous" |

---

## Out-of-scope handling

Queries that contain no building-related content (e.g., "DO YOU LOVE YOUR COUNTRY?", "BAKING", "MEASUREMENT", "4") are coded as:

```
domain_l1 = OTHER
query_type_l2 = STATUS  (default placeholder)
intent = INFORMATIONAL
temporal = STATIC
spatial = UNSPECIFIED
complexity = LOOKUP
```

These rows are excluded from later phase analyses (C-G) but retained in the corpus deliverable.

---

## Open questions for Phase B3

1. Can `DIAGNOSTIC` and `ANOMALY` be reliably distinguished by two coders? (anomaly = "is X out of range"; diagnostic = "why is X out of range")
2. Should `CAPABILITY` queries be split into "can the system" vs "does the building"? Both are about *existence*, but the former tests system features and the latter tests building features.
3. Should `INFO_REQUEST` and `WAYFINDING` be merged when they overlap (e.g., "what are the hours of the cafe")?

These will be revisited after the IRR run in Phase B3.
