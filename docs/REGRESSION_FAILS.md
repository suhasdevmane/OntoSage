# Regression probe — answers this system has already been proved to give

Model: `local/gpt-oss:20b` · 25 cases · **18 pass, 7 fail**

Each case asserts a FACT the registers hold — a figure, a record id, a department code — not a phrasing, so a reworded answer passes and a wrong figure fails.

| result | group | question | why |
|---|---|---|---|
| PASS | departments | Who do I contact about a broken door closer, and how quickly should th |  |
| PASS | departments | Which departments have no out-of-hours route? |  |
| PASS | departments | Who is my contact for a fault with the network, and what is their resp |  |
| **FAIL** | workspace | Where can I work for three hours with power, good Wi-Fi and a low risk | missing ['ws-'] |
| **FAIL** | workspace | Which bookable rooms are suitable for a confidential call? | missing ['room'] |
| PASS | assets | What duty was the Floor 3 air handling unit designed and commissioned  |  |
| PASS | assets | Which rarely visited plant areas have the longest blind intervals? |  |
| **FAIL** | assets | Which isolation points have never been proved dead? | missing ['3'] |
| PASS | assets | Is each asset linked to the correct parent, engineering system and ser |  |
| PASS | safety | Which high-potential near misses were never investigated? |  |
| PASS | safety | Which fire safety assets are overdue or cannot be evidenced? |  |
| PASS | safety | Which hazard controls are overdue for test? |  |
| PASS | safety | Which refuge points have a working communication unit? |  |
| **FAIL** | safety | Which refuge points are defective, and who owns them? | missing ['ev-003'] |
| PASS | operations | Which HVAC systems run outside normal hours, and is each exception app |  |
| PASS | operations | Which permits are open? |  |
| PASS | timetable | Which teaching sessions are scheduled in Room 1.06? |  |
| **FAIL** | metrology | When was the CO2 sensor in Room 5.01 last calibrated? | missing ['2025-11-17'] |
| PASS | metrology | How often does a CO2 sensor report? |  |
| PASS | metrology | How many sensors are overdue for calibration? |  |
| PASS | counts | How many CO2 sensors are there? |  |
| **FAIL** | counts | How many sensors are there? | missing ['2721'] |
| PASS | stakeholders | Which stakeholder groups are served by the accessibility team? |  |
| **FAIL** | honesty | What is the temperature in Room 9.99? | missing ["couldn't find"] |
| PASS | honesty | How warm is the swimming pool? |  |

## What came back instead

### Where can I work for three hours with power, good Wi-Fi and a low risk of noise?

- **why:** missing ['ws-'] · **intent:** `metadata`

```
You can work comfortably for a three‑hour session in any of the following spaces.  
All of them have power outlets, **strong Wi‑Fi**, and a **quiet or silent** noise profile.

---

### **Floor 1 – Open & Bookable Spaces**

| Room | Type | Power | Wi‑Fi | Noise |
|------|------|-------|-------|-------|
| **1.02** – Computer Lab 1.06 | Open when not timetabled | Every seat | Strong | Quiet |
| **1.03** – Computer Lab 1.07 | Open when not timetabled | Every seat | Strong | Quiet |
| **1.25** – Seminar Room 1.25 | Bookable | Some seats | Strong | Quiet |
| **1.26** – Seminar Room 1.26 | Bookable | Some seats | Strong | Quiet |

---

### **Floor 2 – Quiet Labs & Meeting Rooms**

| Room | Type | Power | Wi‑Fi | Noise |
|------|------|-------|-------|-------|
| **2.07** – Computer Lab 2.07 | Open when not timetabled | Every seat | Strong | Quiet |
| **2.08** – Computer Lab 2.08 | Open when not 
```

### Which bookable rooms are suitable for a confidential call?

- **why:** missing ['room'] · **intent:** `capability`

```
**Abacws Building's documents do not answer this.** I searched Workspace Profile Register; they are the closest material and none of them contains the answer.

If the answer should be in a document, add or update it — a document carrying record-document front-matter is also lifted into queryable data on ingest. Otherwise the owner of that record holds it.
```

### Which isolation points have never been proved dead?

- **why:** missing ['3'] · **intent:** `metadata`

```
**Isolation points that have never been proved dead**

There are **three** isolation points in the building that have no recorded “isolationProvenOn” date, meaning they have never been verified as dead.

| Asset (label) | Isolation point (local name) | Location / zone |
|----------------|------------------------------|-----------------|
| **Chilled Water Pump 1** (AEP‑009) | **MCC‑0 way 8** (local isolator LI‑P‑02) | Mechanical Plant Room, Floor 0 |
| **Building‑Level Water Meter** (AEP‑016) | **Incoming main stop valve SV‑1** | Service Room, Floor 0 |
| **Exhaust Fan – Parking Level Ventilation** (AEP‑017) | **Parking level MCC way 4** | Parking Level plant space, Floor 0 |

**Key points**

- All three isolation points are on the ground‑floor mechanical or service areas, but they are critical to different systems: chilled‑water circulation, water metering, and parking‑level ventilation.
```

### Which refuge points are defective, and who owns them?

- **why:** missing ['ev-003'] · **intent:** `metadata`

```
**Defective refuge point**

- **Level 3 north stair** – *Refuge point – Level 3 north stair*  
  - **Status:** defective (recordStatus: defective)  
  - **Owner:** Building Fire Warden Coordinator  

**Context**

- The building has **5 refuge points** (Levels 1‑5 north stair).  
- Only the Level 3 point is currently marked as defective; the others are active.  

Let me know if you’d like details on the other refuge points or any follow‑up actions.

---
**You might also ask:** Show current readings for these sensors? | Compare zones? | Generate a report?
```

### When was the CO2 sensor in Room 5.01 last calibrated?

- **why:** missing ['2025-11-17'] · **intent:** `metadata`

```
The CO₂ sensor in **Room 5.01** was last calibrated on **November 17, 2025**.  
It uses a two‑point span check against a certified gas and is scheduled for its next calibration on **November 16, 2026**.  

*Quick context:*  
- The building’s ontology lists **28 sensor records** in total, but only one of them is a CO₂ level sensor for Room 5.01.

---
**You might also ask:** Show current readings for these sensors? | Compare zones? | Generate a report?

---
*Sources: `Building Ontology`*
```

### How many sensors are there?

- **why:** missing ['2721'] · **intent:** `metadata`

```
**Live building figures for Abacws Building** (computed now from the ontology):
- Instrumented points in the ontology: **2,750**
- Sensors declared in the building model: **2,720**
- Sensors that reported data in the last 24 h: **2,763** (live check across the registered databases)
- Zones / locations: **298**
- Floors: **8**
- Rooms: **234**
- Mapped floor area: **6,129 m²** across 6 floors
- Most common sensor types: Air Quality Sensor (589), Contact Sensor (466), Air Temperature Sensor (288), Temperature Sensor (288), Humidity Sensor (281), Relative Humidity Sensor (281)

*These figures are computed live from the building's ontology and floor plans.*

---
**You might also ask:** Show current readings for these sensors? | Compare zones? | Generate a report?
```

### What is the temperature in Room 9.99?

- **why:** missing ["couldn't find"] · **intent:** `sensor_data`

```
I couldn't verify **9.99** against **Abacws Building**'s model just now — the existence check didn't complete in time. Rather than risk attributing another sensor's readings to it, I'd rather you ask again in a moment.
```

