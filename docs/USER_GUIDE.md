# User Guide

This guide is for anyone who uses OntoSage to ask questions about a building — facility managers, sustainability teams, occupants, IT staff, and researchers. No technical knowledge of databases, ontologies, or sensor IDs is required.

---

## Getting Started

### Accessing the Chat Interface

Open your browser and navigate to:

```
http://localhost:3000
```

If your administrator has deployed OntoSage on a server, they will give you the URL.

### Creating an Account

1. Click **Sign Up** on the login page
2. Enter your name, email, and a password
3. The first user to register automatically becomes an **admin**
4. Subsequent users are assigned the **occupant** role by default; an admin must promote them

### Starting a Conversation

1. Click **New Chat** in the sidebar
2. Type your question in the message box at the bottom
3. Press **Enter** or click the send button
4. OntoSage will respond within a few seconds

---

## What You Can Ask

OntoSage understands 14 different types of building-related questions. Here is what each type does and example questions.

### Current Sensor Readings

Ask for the current value of any sensor or device.

> "What is the CO₂ level in Zone 5 right now?"
> "What is the temperature in the conference room?"
> "What is the humidity on Floor 3?"
> "Is the AHU-01 fan running?"

**What you get:** The most recent sensor reading with units, timestamp, and the sensor's location in the building.

---

### Historical Data and Trends

Ask about sensor values over a time period.

> "Show me the temperature trend in Zone 5 for the last 7 days."
> "What was the CO₂ level in the lab yesterday afternoon?"
> "How did energy consumption change over the past month?"
> "Was the humidity above 70% at any point last week?"

**What you get:** A time-series chart and summary statistics (min, max, mean, standard deviation) for the requested period.

---

### Analytics and Statistics

Ask for computed analysis across one or more sensors.

> "What is the average temperature across all zones on Floor 3?"
> "Which zone has the highest CO₂ concentration right now?"
> "Calculate the correlation between outdoor temperature and chiller energy load."
> "How many hours was Zone 2 above 25°C this week?"
> "What is the 95th percentile CO₂ level in Meeting Room A?"

**What you get:** A computed result with the Python analytics code used, a chart where applicable, and a plain-English interpretation.

---

### Anomaly Detection

Ask OntoSage to identify unusual sensor behaviour.

> "Are there any CO₂ sensors showing abnormal readings right now?"
> "Has any temperature sensor spiked unusually in the past 24 hours?"
> "Which sensors are outside their normal operating range?"
> "Alert me to any HVAC equipment that looks like it's failing."

**What you get:** A list of anomalous readings, how far they deviate from expected values, and the time of the anomaly.

---

### Building Discovery

Ask what sensors, equipment, and spaces exist in the building.

> "What sensors are available in the building?"
> "Which floors have CO₂ sensors?"
> "List all the zones on Floor 5."
> "What HVAC equipment serves Zone 3?"
> "Show me the sensors in Meeting Room B."

**What you get:** A structured list of the building's assets derived directly from the ontology, including their types, locations, and relationships.

---

### Comparisons

Compare multiple zones, floors, sensors, or time periods against each other.

> "Compare the energy usage of Floor 2 and Floor 3 this week."
> "Which conference room has the best air quality today?"
> "How does current CO₂ compare to the same time last week?"
> "Show me temperature differences between the east and west wings."

**What you get:** A side-by-side comparison table or chart with statistical highlights.

---

### Reports

Request a structured summary report of building conditions.

> "Give me a daily building performance report."
> "Summarise the air quality conditions across all zones for this week."
> "Generate a monthly energy consumption report."
> "Create an environmental comfort report for Zone 5."

**What you get:** A formatted multi-section report covering the requested metrics, with charts and summary statistics.

---

### Forecasting

Ask for predictions of future sensor values (if historical data is available).

> "What will the temperature in Zone 3 be tomorrow afternoon?"
> "Forecast energy consumption for the next 7 days."
> "Will CO₂ levels be acceptable during Friday's conference?"

**What you get:** A multi-model forecast — OntoSage automatically selects the best-fitting model (ARIMA, exponential smoothing, or linear), parses your horizon from plain language ("next week", "tomorrow afternoon"), and reports the model used and its accuracy (RMSE / R²) alongside the chart. Forecasts are honest about confidence rather than presented as certainty. See the [Forecasting](FORECASTING.md) guide for details.

---

### Data Export

Ask for raw data in a downloadable format.

> "Export the last 30 days of temperature data for all zones as CSV."
> "Give me a JSON file of all CO₂ readings from yesterday."
> "Download the sensor data for Zone 5 this week."

**What you get:** A downloadable file link in the chat response (CSV or JSON).

---

### Recommendations

Ask OntoSage for actionable advice based on building data.

> "Which zones should we prioritise for ventilation improvements?"
> "Are there any zones where we can reduce HVAC energy without affecting comfort?"
> "What changes would most improve the air quality in Zone 4?"

**What you get:** Evidence-based recommendations derived from actual sensor data and building topology.

---

### Alerts and Threshold Queries

Ask about threshold breaches or set up threshold checks.

> "Have any sensors exceeded their alert thresholds today?"
> "Which CO₂ sensors went above 1000 ppm this week?"
> "Were there any temperature alerts last Monday?"
> "List all sensors that breached their limit in the last 24 hours."

**What you get:** A filtered list of events where readings crossed defined thresholds, with times and values.

### Floor Plans and Spatial Queries

Ask to see a floor or query room geometry.

> "Show me floor 3"
> "Where is room 3.01?"
> "How many meeting rooms are on floor 4?"
> "Which rooms are adjacent to the server room?"
> "What is the total area of the building?"

**What you get:** A floor plan image (PDF render or DWG-rendered SVG) plus structured room data — area in m², adjacency lists, sensor block counts.

### Capability Questions (v3.1) — Off-Ontology Q&A

Ask about building features, policies, amenities, fire safety, IT — anything that isn't a sensor reading or analytics question. Answered from the per-building **Capability KB** (Qdrant-backed semantic search) in **under 50 ms** when the system is confident.

> "What are the fire evacuation procedures?"
> "Where can I park my bike?"
> "What happens during a power outage?"
> "Is there a prayer room?"
> "When does reception close?"
> "How does access control work?"
> "Is there a quiet room?"
> "Can I bring my dog into the building?"

**What you get:** A structured answer drawn directly from the building's knowledge profile, with citation of the source document (e.g. `fire_safety_management_plan`). If the KB has no record, you'll get an **explicit boundary message** — never a hallucinated answer:

> "I don't have that specific information on record for **Abacws Building**. For building-specific queries please contact facility management at estates@cardiff.ac.uk or call the estates helpdesk (029 2087 6026)."

**Why this matters:** corpus analysis of 5,916 survey questions shows that ~50% of real building queries are off-ontology — they can't be answered from sensor data or SPARQL alone. The capability KB closes that gap honestly. See [Capability Routing](CAPABILITY_ROUTING.md) for the technical pipeline.

---

### Reporting Issues — Faults, Complaints, Safety, Feedback

Report a problem or share feedback in plain English — no forms, no categories to pick. OntoSage classifies and prioritises it automatically and gives you a tracking ID.

> "The light in room 3.01 is broken."
> "There's a gas smell near the kitchen on floor 2."  *(→ flagged URGENT)*
> "The meeting room is always too cold in the mornings."
> "Suggestion: add more bike racks by the south entrance."
> "Great job fixing the lift so quickly!"

**What you get:** An acknowledgement with a tracking reference. Safety hazards (gas, fire, smoke) are escalated to **URGENT**; broken equipment to **HIGH**. Each report is stamped with your role and stored for the facilities team, who triage them through admin views. Be specific (location + what's wrong) for the fastest routing.

---

## Interaction Tips

### You Do Not Need to Know Sensor Names or IDs

OntoSage understands natural language. You never need to know a sensor's UUID, database identifier, or ontology class name.

| What you say | What happens internally |
|---|---|
| "the conference room" | OntoSage finds the zone via semantic search of the ontology |
| "CO₂ levels" | OntoSage resolves this to `brick:CO2_Sensor` instances in the graph |
| "this week" | OntoSage computes the date range from the current date |
| "temperature sensor near the window" | Semantic similarity search in the ontology finds the closest match |

### Context Is Preserved Within a Conversation

You can ask follow-up questions without repeating context. OntoSage remembers the conversation and resolves references like *"there"*, *"that"*, and *"the same"* to what you meant earlier:

> **You:** "What is the CO₂ level in Zone 5?"
> **OntoSage:** "The current CO₂ level in Zone 5 is 842 ppm (measured at 14:23)."
>
> **You:** "What about yesterday?"
> **OntoSage:** *(fetches yesterday's data for Zone 5 automatically)*
>
> **You:** "And how does that compare to Zone 3?"
> **OntoSage:** *(compares Zone 5 vs Zone 3, yesterday)*
>
> **You:** "and what about humidity there?"
> **OntoSage:** *(resolves "there" → Zone 3 and answers humidity — no need to restate the zone)*

It also **carries results forward**: after a forecast or analysis you can say *"now plot that"* or *"show it as a table"* and OntoSage reuses the previous result. See [Conversation Intelligence](CONVERSATION_INTELLIGENCE.md) for how this works.

### Be Specific About Time Ranges When Needed

OntoSage defaults to "right now" for simple readings and "last 24 hours" for trend questions. Be explicit when you need a different range:

- "in the last 15 minutes"
- "between 8am and 6pm today"
- "last Monday"
- "over the past 30 days"
- "this month compared to last month"

### You Can Ask Complex Multi-Part Questions

> "Which zones had CO₂ above 1000 ppm for more than 2 hours yesterday, and what was the occupancy like at those times?"

OntoSage will break this down internally and return a combined answer.

### Charts Are Automatic

When you ask for historical data, trends, or comparisons, OntoSage automatically generates a chart (line plot, bar chart, or scatter plot as appropriate). The chart appears inline in the response.

---

## Understanding Responses

### Response Format

Each answer includes:

1. **Direct answer** — a plain-English sentence stating the result
2. **Supporting data** — the numbers, timestamps, and sensor details behind the answer
3. **Visualisation** (where applicable) — an inline chart
4. **Confidence indicator** (where applicable) — whether the answer is based on direct data or statistical inference
5. **Suggested follow-up questions** — related questions you might want to ask next

### When OntoSage Asks for Clarification

If your question is ambiguous — for example, if multiple zones match "the conference room" — OntoSage will ask a follow-up question to narrow the scope:

> "I found three spaces matching 'conference room': Meeting Room A (Zone 3.01), Meeting Room B (Zone 3.02), and the Board Room (Zone 4.05). Which one did you mean?"

### When OntoSage Cannot Answer

If OntoSage cannot find the data you are asking about, it will explain why rather than inventing an answer:

- **"No sensors found"** — The building ontology does not have sensors matching your description. Check with your facility manager.
- **"No data in that time range"** — The time-series database does not have readings for that period. Data may not have been collected.
- **"I need more information"** — The question is too vague to resolve unambiguously.

OntoSage never fabricates sensor readings or analytics results. If data is unavailable, it says so.

---

## Example Conversations

### Facility Manager: Comfort Investigation

> **Facility Manager:** "Which zones on Floor 3 are currently outside their temperature comfort range of 20–24°C?"
>
> **OntoSage:** "Three zones on Floor 3 are currently outside the 20–24°C comfort band:
> - Zone 3.01 (Open Plan East): 26.2°C (2.2°C above upper limit)
> - Zone 3.04 (Server Room Corridor): 18.1°C (1.9°C below lower limit)
> - Zone 3.07 (South Meeting Room): 25.6°C (1.6°C above upper limit)
>
> The remaining 5 zones are within range. Would you like to see the temperature trend for any of these zones over the past 24 hours?"

---

### Sustainability Team: Energy Reporting

> **Sustainability Team:** "What was the total energy consumption on Floor 2 last week, and how does it compare to the previous week?"
>
> **OntoSage:** "Floor 2 energy consumption last week (Mon 07 Apr – Sun 13 Apr): **14,820 kWh**
>
> Previous week (Mon 31 Mar – Sun 06 Apr): **16,205 kWh**
>
> **Change: −8.5% (↓ 1,385 kWh)**
>
> This is primarily driven by reduced consumption in the east wing on Wednesday and Thursday, which may correspond to lower occupancy. Would you like a breakdown by zone or by day?"

---

### Health & Safety Officer: CO₂ Audit

> **H&S Officer:** "Have any CO₂ sensors exceeded 1000 ppm for more than 15 minutes this week?"
>
> **OntoSage:** "Yes — 4 CO₂ threshold breach events this week:
>
> | Zone | Peak ppm | Duration | Date/Time |
> |------|----------|----------|-----------|
> | Zone 4.02 (Training Room) | 1,340 ppm | 47 min | Tue 08 Apr 14:00–14:47 |
> | Zone 4.02 (Training Room) | 1,210 ppm | 22 min | Thu 10 Apr 15:30–15:52 |
> | Zone 2.05 (Workshop) | 1,120 ppm | 31 min | Wed 09 Apr 10:15–10:46 |
> | Zone 5.01 (Open Plan) | 1,005 ppm | 18 min | Mon 07 Apr 09:00–09:18 |
>
> Zone 4.02 has had 2 separate incidents this week. Would you like me to generate a full CO₂ compliance report for this zone?"

---

### Data Scientist: Statistical Query

> **Data Scientist:** "Calculate the Pearson correlation coefficient between outdoor temperature and HVAC energy consumption across the last 90 days."
>
> **OntoSage:** "Pearson correlation coefficient (outdoor temperature vs HVAC energy, last 90 days): **r = 0.84** (strong positive correlation, p < 0.001)
>
> This means that as outdoor temperature increases, HVAC energy consumption increases significantly — explaining approximately 71% of the variance (R² = 0.71).
>
> [Scatter plot with regression line attached]
>
> The relationship appears to be linear for temperatures below 20°C, with some non-linearity above 25°C, possibly due to cooling system saturation."

---

### Occupant: Comfort Query

> **Occupant:** "It's really cold in my office today — what's the temperature supposed to be versus what it actually is?"
>
> **OntoSage:** "I can see you're in Zone 3.04. Here's the current situation:
>
> - **Current temperature:** 17.8°C (measured 5 minutes ago)
> - **Setpoint:** 21°C
> - **Deviation:** −3.2°C below setpoint
>
> The zone has been below setpoint since 07:30 this morning (about 4.5 hours). This may indicate an HVAC issue. I've flagged this for your facility manager."

---

## Role-Based Access

Different users see different capabilities based on their role:

| Role | What they can do |
|------|-----------------|
| **Admin** | All capabilities + user management, system configuration |
| **Facility Manager** | All sensor queries, analytics, reports, anomaly detection, recommendations |
| **Analyst** | All data queries, analytics, exports, reports |
| **Operator** | Sensor readings, anomaly alerts, basic reports |
| **Occupant** | Comfort queries, current conditions for accessible zones |
| **Read-only** | Discovery queries only — can see what sensors exist, not their values |

If you receive a "permission denied" response, ask your administrator to upgrade your role.

---

## Keyboard Shortcuts

When using the Open WebUI interface:

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift+Enter` | New line within message |
| `↑` (in input box) | Recall previous message |
| `Ctrl+/` | Open keyboard shortcut help |

---

## Frequently Asked Questions

**Q: Can I ask about a sensor that I don't know the name of?**
Yes. Describe it in plain English: "the sensor near the entrance", "the CO₂ sensor in the boardroom", "the energy meter for the kitchen". OntoSage uses semantic search to find the closest match.

**Q: Can I ask questions that span multiple buildings?**
If your administrator has onboarded multiple buildings, yes. Include the building name in your question: "Compare CO₂ levels in Building A and Building B."

**Q: How fresh is the data?**
Sensor data freshness depends on how frequently your building management system writes to the database. For most BMS systems, this is every 1–15 minutes. OntoSage always queries the live database — there is no caching of sensor readings.

**Q: Can I ask questions in languages other than English?**
Currently optimised for English. If your Ollama model supports your language (e.g., LLaMA 3.1 has multilingual support), you can try other languages, but accuracy may be lower.

**Q: What happens to my conversation history?**
Conversation state is stored in Redis with a 1-hour TTL — this means the AI remembers the context of your current conversation for up to 1 hour. Full message history is stored in MongoDB for audit purposes and retained according to your administrator's retention policy.

**Q: Can I export my conversation?**
Not directly from the chat UI. Your administrator can export conversation logs from MongoDB.

**Q: Why did OntoSage give me a different answer to the same question?**
Most responses are deterministic (temperature = 0.0–0.1 for SPARQL generation and analytics). Small variations can occur if the LLM is running with non-zero temperature, or if sensor data changed between queries. If you see a significantly different answer, ask a follow-up to confirm.
