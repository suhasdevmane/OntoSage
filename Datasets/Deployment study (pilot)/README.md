# Post-Design Evaluation Survey

This folder contains anonymised responses from the post-deployment user evaluation of OntoSage++. Participants used the deployed system for a guided session before completing the instruments below.

## Study summary

- **Participants:** 15 (6 Student/Researcher, 4 IT/Operator, 5 Visitor/Guest)
- **Recruitment:** Cardiff University academic and IT staff plus building visitors
- **Ethics:** SREC reference COMSC/Ethics/2025/044b (Cardiff University)
- **Site:** Building A (Abacws, Cardiff University)
- **Session length:** ~25 minutes per participant (system walkthrough + 8 tasks + questionnaires)
- **Anonymisation:** participants mapped to `P_pd_01..P_pd_15`; the Username→PID map is held offline by the research team and not stored in this folder

## Files

| File | Description |
|------|-------------|
| `responses.csv` | Per-participant: role, SUS items 1-10, SUS score, NASA-TLX 6 dimensions, task completion, time on tasks, three open-ended responses |
| `summary_stats.csv` | Aggregate statistics cited in the paper (mean SUS, mean TLX, completion rate, role breakdown) |

## Instruments

**SUS (System Usability Scale, Brooke 1996):** 10 items, 5-point Likert (1 = Strongly Disagree → 5 = Strongly Agree). Score = 2.5 × (sum over odd items of (response − 1) + sum over even items of (5 − response)). Range 0-100.

**NASA-TLX (Hart & Staveland 1988):** 6 dimensions (Mental Demand, Physical Demand, Temporal Demand, Performance, Effort, Frustration), 0-100 each. For all dimensions except Performance, lower is better; for Performance higher indicates self-reported success.

**Open-ended:**
- Q1: "What did you find most useful about OntoSage++?"
- Q2: "What did you find most frustrating?"
- Q3: "Would you use this in your daily work? Why / why not?"

## Tasks (8 total)

T1 — "What is the current temperature in Room 5.04?"
T2 — "Show me energy use for the last 7 days."
T3 — "Are any rooms outside ASHRAE 55 comfort range right now?"
T4 — "Compare CO2 levels in Rooms 5.02 and 5.03 this week."
T5 — "Find the most energy-intensive zone yesterday."
T6 — "Are there any anomalies in the HVAC system today?"
T7 — "Generate a daily report for Floor 5."
T8 — "What sensors are available in this building?"

## Key descriptive findings

- Mean SUS: **84.5** (above the 80.3 "Excellent" threshold; Bangor et al. 2009)
- 100% of participants scored OntoSage++ at or above the 68 "Above Average" threshold
- 73% (11/15) rated the system as "Good" or "Excellent" (SUS ≥ 80)
- IT/Operators reported the highest usability (mean 88.75), reflecting comfort with technical tooling
- Visitor/Guests, who had no prior building knowledge, still reported high usability (mean 80.0), supporting the zero-knowledge design goal
- 98.3% of tasks were completed successfully (118/120)
- 93.3% of participants (14/15) said they would adopt the system in their daily work; the remaining participant ("Maybe") cited a desire for clearer prompt suggestions
