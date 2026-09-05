# Regression probe — answers this system has already been proved to give

Model: `local/gpt-oss:20b` · 25 cases · **24 pass, 1 fail**

Each case asserts a FACT the registers hold — a figure, a record id, a department code — not a phrasing, so a reworded answer passes and a wrong figure fails.

| result | group | question | why |
|---|---|---|---|
| PASS | departments | Who do I contact about a broken door closer, and how quickly should th |  |
| PASS | departments | Which departments have no out-of-hours route? |  |
| PASS | departments | Who is my contact for a fault with the network, and what is their resp |  |
| PASS | workspace | Where can I work for three hours with power, good Wi-Fi and a low risk |  |
| PASS | workspace | Which bookable rooms are suitable for a confidential call? |  |
| PASS | assets | What duty was the Floor 3 air handling unit designed and commissioned  |  |
| PASS | assets | Which rarely visited plant areas have the longest blind intervals? |  |
| PASS | assets | Which isolation points have never been proved dead? |  |
| PASS | assets | Is each asset linked to the correct parent, engineering system and ser |  |
| PASS | safety | Which high-potential near misses were never investigated? |  |
| PASS | safety | Which fire safety assets are overdue or cannot be evidenced? |  |
| PASS | safety | Which hazard controls are overdue for test? |  |
| PASS | safety | Which refuge points have a working communication unit? |  |
| PASS | safety | Which refuge points are defective, and who owns them? |  |
| PASS | operations | Which HVAC systems run outside normal hours, and is each exception app |  |
| PASS | operations | Which permits are open? |  |
| PASS | timetable | Which teaching sessions are scheduled in Room 1.06? |  |
| **FAIL** | metrology | When was the CO2 sensor in Room 5.01 last calibrated? | transport TIMEOUT |
| PASS | metrology | How often does a CO2 sensor report? |  |
| PASS | metrology | How many sensors are overdue for calibration? |  |
| PASS | counts | How many CO2 sensors are there? |  |
| PASS | counts | How many sensors are there? |  |
| PASS | stakeholders | Which stakeholder groups does DEP-13 serve? |  |
| PASS | honesty | What is the temperature in Room 9.99? |  |
| PASS | honesty | How warm is the swimming pool? |  |

## What came back instead

### When was the CO2 sensor in Room 5.01 last calibrated?

- **why:** transport TIMEOUT · **intent:** ``

```

```

