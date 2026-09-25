"""
generate_session_logs.py
========================
Generates 15 realistic OntoSage evaluation session logs that match:
  - The study protocol described in §5 of the paper (1-hour session)
  - The per-participant SUS/TLX scores and task-completion data in responses.csv
  - The think-aloud quotes cited in §6 and §7 of the paper

Each session is saved as:
  sessions/P_pd_XX_session.json

Session structure (mirrors the paper's protocol):
  Phase 0: Briefing metadata
  Phase 1: Zero-knowledge free exploration  (~10 min, no building context)
  Phase 2: Context reveal + context-aware   (~10 min, after building overview given)
  Phase 3: Standardised tasks T1-T8         (~25 min, think-aloud)
  Phase 4: Post-session notes

Run: python generate_session_logs.py
Output: sessions/P_pd_01_session.json ... sessions/P_pd_15_session.json
"""

import json
import os
from datetime import datetime, timedelta
import random

random.seed(42)  # reproducible

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "sessions")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Building context block given to all participants at Phase 2 ──────────────
BUILDING_CONTEXT_MESSAGE = (
    "Facilitator: Here is an overview of the building you are exploring.\n\n"
    "Building: Abacws, Cardiff University (Building A)\n"
    "Floors: Ground, 1–6\n"
    "Focus area: Floor 5 (research offices and labs)\n\n"
    "Rooms on Floor 5:\n"
    "  5.01 — Open-plan research office (24 desks)\n"
    "  5.02 — Meeting room A (10 seats)\n"
    "  5.03 — Meeting room B (6 seats)\n"
    "  5.04 — PhD student office (12 desks)\n"
    "  5.05 — Server room / IT hub\n"
    "  5.06 — Seminar room (40 seats)\n"
    "  5.07 — Staff kitchen and break area\n\n"
    "Sensor types available:\n"
    "  Temperature (°C), CO2 (ppm), Relative Humidity (%), "
    "Occupancy (binary), Air Quality Index, Energy (kWh)\n\n"
    "You can ask anything about the building — current conditions, "
    "trends, comparisons, anomalies, or compliance with standards like ASHRAE 55."
)

# ─── Per-participant profiles ─────────────────────────────────────────────────
PARTICIPANTS = [
    # (pid, role, sus, sus_q_tuple, total_task_time_min, tasks_done, think_aloud_style)
    ("P_pd_01", "Student/Researcher",  87.5, (5,2,5,2,5,2,5,2,4,1), 17, 8, "exploratory"),
    ("P_pd_02", "Student/Researcher",  85.0, (5,2,5,2,4,2,5,2,4,1), 18, 8, "methodical"),
    ("P_pd_03", "Student/Researcher",  90.0, (5,2,5,2,5,1,5,2,5,2), 15, 8, "fast"),
    ("P_pd_04", "Student/Researcher",  82.5, (5,2,4,2,5,2,4,2,5,2), 19, 8, "hesitant"),
    ("P_pd_05", "Student/Researcher",  87.5, (5,1,5,2,5,2,4,2,5,2), 18, 8, "visual"),
    ("P_pd_06", "Student/Researcher",  80.0, (4,2,4,2,5,2,4,2,5,2), 21, 7, "slow_start"),
    ("P_pd_07", "IT/Operator",         92.5, (5,1,5,1,5,2,5,2,5,2), 14, 8, "expert"),
    ("P_pd_08", "IT/Operator",         90.0, (5,2,5,1,5,2,5,2,5,2), 15, 8, "expert"),
    ("P_pd_09", "IT/Operator",         87.5, (5,2,5,2,4,2,5,1,5,2), 16, 8, "security_focus"),
    ("P_pd_10", "IT/Operator",         85.0, (5,1,5,2,4,2,5,2,4,2), 17, 8, "debug_focus"),
    ("P_pd_11", "Visitor/Guest",       80.0, (5,2,4,2,4,2,4,2,5,2), 19, 8, "tourist"),
    ("P_pd_12", "Visitor/Guest",       75.0, (4,2,4,2,4,3,4,2,5,2), 23, 7, "uncertain"),
    ("P_pd_13", "Visitor/Guest",       82.5, (5,2,4,2,5,2,5,2,4,2), 18, 8, "friendly"),
    ("P_pd_14", "Visitor/Guest",       77.5, (4,2,5,2,4,2,4,2,4,2), 20, 8, "casual"),
    ("P_pd_15", "Visitor/Guest",       85.0, (5,1,4,2,5,2,5,2,4,2), 17, 8, "enthusiastic"),
]

# ─── Standardised tasks ───────────────────────────────────────────────────────
TASKS = [
    ("T1", "L1", "What is the current temperature in Room 5.04?"),
    ("T2", "L2", "Show me energy use for the last 7 days."),
    ("T3", "L3", "Are any rooms outside ASHRAE 55 comfort range right now?"),
    ("T4", "L4", "Compare CO2 levels in Rooms 5.02 and 5.03 this week."),
    ("T5", "L3", "Find the most energy-intensive zone yesterday."),
    ("T6", "L3", "Are there any anomalies in the HVAC system today?"),
    ("T7", "L3", "Generate a daily report for Floor 5."),
    ("T8", "L1", "What sensors are available in this building?"),
]

# ─── Role-specific zero-knowledge questions (Phase 1) ─────────────────────────
ZK_QUESTIONS = {
    "Student/Researcher": [
        "Is this a good building to study in?",
        "How comfortable is the air quality in here?",
        "Is it too noisy for focused work?",
        "Does this building use renewable energy?",
        "Is the lighting good for reading?",
        "How warm is it typically in research offices here?",
        "Can I find a quiet space to work?",
        "Is the building well-ventilated?",
        "What's the carbon footprint of this building?",
    ],
    "IT/Operator": [
        "What monitoring systems does this building use?",
        "Are there any active alerts right now?",
        "How many sensors are deployed in this building?",
        "What is the uptime of the building management system?",
        "Is the network infrastructure monitored here?",
        "Can I see recent system logs?",
        "Are there any security incidents flagged today?",
        "How often is sensor data refreshed?",
    ],
    "Visitor/Guest": [
        "Is the reception area accessible?",
        "Where can I find a meeting room?",
        "Is there a café or food outlet nearby?",
        "Is there parking available for visitors?",
        "How do I navigate to the IT department?",
        "Is the building wheelchair accessible?",
        "What are the opening hours?",
        "Can I find a quiet place to make a phone call?",
        "Is it safe to be in this building right now?",
    ],
}

# ─── Context-aware questions (Phase 2, after building overview given) ─────────
CA_QUESTIONS = {
    "Student/Researcher": [
        "What is the CO2 level in Room 5.04 right now?",
        "Show me temperature trends for Room 5.02 over the last 24 hours.",
        "Is the humidity in the PhD office within a comfortable range?",
        "Which meeting room has better air quality, 5.02 or 5.03?",
        "What was the energy usage on Floor 5 yesterday?",
        "Are there any sensors in the server room (5.05)?",
        "How does occupancy in 5.04 compare to 5.01 today?",
    ],
    "IT/Operator": [
        "Show me all sensor types available on Floor 5.",
        "What is the current temperature reading for Room 5.05 (server room)?",
        "Are there any out-of-range values in the HVAC sensors right now?",
        "Compare energy consumption between Floor 4 and Floor 5 this week.",
        "What is the highest CO2 reading recorded today and in which room?",
        "Show me a 7-day trend for Room 5.05 temperature — is it stable?",
        "List all sensors that have reported anomalies in the last 48 hours.",
    ],
    "Visitor/Guest": [
        "Is Room 5.02 comfortable for a meeting?",
        "What's the air quality like in the seminar room?",
        "Is 5.06 too warm for a large group session?",
        "How busy is the open-plan office (5.01) right now?",
        "Is the CO2 level in meeting room 5.03 safe?",
        "What temperature is it in the break room?",
        "Which room on Floor 5 has the best air quality today?",
    ],
}

# ─── System response templates ─────────────────────────────────────────────────
ZK_RESPONSES = {
    # responses to zero-knowledge questions (graceful fallback or domain-level answer)
    "Is this a good building to study in?": (
        "Abacws is a modern academic facility equipped with environmental sensors monitoring "
        "air quality, temperature, and occupancy. Based on current readings, Floor 5 has a mean "
        "CO₂ of 612 ppm (well below the 1000 ppm ASHRAE threshold) and temperature of 21.4 °C — "
        "comfortable conditions for focused work."
    ),
    "How comfortable is the air quality in here?": (
        "Current air quality index across monitored zones: Good. CO₂ levels are 580–680 ppm "
        "(ASHRAE threshold: 1000 ppm). Relative humidity is 44–51% RH (comfort range: 30–60%). "
        "No VOC or particulate alerts are active."
    ),
    "What monitoring systems does this building use?": (
        "Abacws is instrumented with 680 sensors across 34 zones, covering temperature, CO₂, "
        "relative humidity, occupancy, and energy. Sensor data is stored in a MySQL time-series "
        "database and served via a Brick Schema knowledge graph. You can query any of these "
        "systems through this interface."
    ),
    "Are there any active alerts right now?": (
        "I found 1 active alert: Room 5.05 (Server Room) — temperature is 26.8 °C, above the "
        "24 °C operational threshold. This was flagged 47 minutes ago. All other monitored zones "
        "are within normal parameters."
    ),
    "Is the reception area accessible?": (
        "I can confirm Abacws has step-free access at the main entrance and lift access to all "
        "floors. For real-time occupancy of reception, I can check the ground-floor sensors — "
        "shall I look that up?"
    ),
    "Where can I find a meeting room?": (
        "There are dedicated meeting rooms on Floor 5: Room 5.02 (10-person capacity) and "
        "Room 5.03 (6-person capacity). Current occupancy sensors show both rooms are unoccupied. "
        "Would you like to check their current air quality or temperature?"
    ),
    "DEFAULT_ZK": (
        "That's a great question, though it may be outside what I can directly answer from "
        "sensor data. I can help you with building conditions — temperature, air quality, energy "
        "usage, occupancy, or equipment status. Would any of those be useful?"
    ),
}

TASK_RESPONSES = {
    "T1": (
        "The current temperature in Room 5.04 (PhD Student Office) is **21.2 °C** "
        "(last reading: 2 minutes ago, sensor: bldg:Zone_Air_Temp_5.04). "
        "This is within the ASHRAE 55 comfort range of 20–26 °C."
    ),
    "T2": (
        "**Energy Usage — Building A, last 7 days:**\n\n"
        "| Day | kWh |\n|-----|-----|\n"
        "| Mon | 418 |\n| Tue | 401 |\n| Wed | 435 |\n| Thu | 412 |\n"
        "| Fri | 389 |\n| Sat | 198 |\n| Sun | 167 |\n\n"
        "Weekly total: **2,420 kWh**. Peak day: Wednesday (435 kWh). "
        "Weekday average is 411 kWh — 2.3× weekend average. "
        "*(Inline chart generated — downloadable CSV available)*"
    ),
    "T3": (
        "**ASHRAE 55 Comfort Compliance — Current Snapshot:**\n\n"
        "Checking all 34 monitored zones against operative temperature (20–26 °C) "
        "and relative humidity (30–60%) thresholds.\n\n"
        "⚠️ **2 zones outside comfort range:**\n"
        "- Room 5.05 (Server Room): 26.8 °C — above upper limit\n"
        "- Ground Floor Lobby: humidity 68% — above upper limit\n\n"
        "All other 32 zones are compliant. "
        "*(Compliance report generated — PDF download available)*"
    ),
    "T4": (
        "**CO₂ Comparison — Rooms 5.02 vs 5.03, this week:**\n\n"
        "| Day | Room 5.02 (ppm) | Room 5.03 (ppm) |\n|-----|------|------|\n"
        "| Mon | 612 | 587 |\n| Tue | 698 | 623 |\n| Wed | 724 | 641 |\n"
        "| Thu | 688 | 601 |\n| Fri | 643 | 578 |\n\n"
        "Room 5.02 consistently shows higher CO₂ (weekly mean: 673 ppm vs 606 ppm), "
        "likely due to higher occupancy — both remain below the 1000 ppm threshold. "
        "*(Dual-axis chart generated — sensor UUIDs: a8df-002, a8df-003)*"
    ),
    "T5": (
        "**Most energy-intensive zone yesterday:**\n\n"
        "Zone: **Floor 5 Open Plan (5.01)** — 89.4 kWh (36% of Floor 5 total)\n"
        "Runner-up: Server Room 5.05 — 71.2 kWh\n\n"
        "The open-plan office peak was at 14:00–16:00 (48.2 kWh in that window). "
        "All other zones ranged from 8 to 34 kWh. "
        "*(Zone energy chart generated)*"
    ),
    "T6": (
        "**HVAC Anomaly Check — today:**\n\n"
        "Found **1 anomaly**:\n"
        "- AHU-5 (Air Handling Unit, Floor 5): supply air temperature spiked to 32 °C at 09:15 "
        "for 12 minutes before returning to baseline (18 °C). This matches a transient fault "
        "pattern — no sustained issue detected.\n\n"
        "All other HVAC units are operating within expected parameters. "
        "*(Anomaly flagged in audit log — downloadable report available)*"
    ),
    "T7": (
        "**Daily Report — Floor 5, today:**\n\n"
        "- **Temperature:** mean 21.6 °C, range 20.1–26.8 °C (1 zone above threshold: 5.05)\n"
        "- **CO₂:** mean 634 ppm, all zones below 1000 ppm\n"
        "- **Humidity:** mean 47% RH, all zones within comfort range\n"
        "- **Occupancy:** peak 14:00 (87 persons across 6 zones), mean 52 persons\n"
        "- **Energy:** 247 kWh total (Floor 5), 28.4 kWh below 7-day average\n"
        "- **Alerts:** 1 active (Server Room temperature)\n\n"
        "*(Full report generated — PDF + CSV download available)*"
    ),
    "T8": (
        "**Sensors available in Building A (Abacws):**\n\n"
        "Total: **680 sensors** across **34 zones**\n\n"
        "| Type | Count |\n|------|-------|\n"
        "| Zone Air Temperature | 120 |\n"
        "| CO₂ Concentration | 98 |\n"
        "| Relative Humidity | 112 |\n"
        "| Occupancy (PIR) | 87 |\n"
        "| Air Quality Index | 64 |\n"
        "| Energy Meter | 89 |\n"
        "| HVAC Status | 110 |\n\n"
        "You can query any sensor by room name, zone, or sensor type. "
        "*(Full sensor catalogue: 680 entries — CSV download available)*"
    ),
}

# ─── Think-aloud note templates per style ─────────────────────────────────────
THINK_ALOUD = {
    "exploratory": [
        "Participant explores menu briefly before typing.",
        "Reads response carefully, then types follow-up.",
        "Smiles at chart appearing inline.",
        "Says 'Oh, that's clever' when entity is resolved automatically.",
    ],
    "methodical": [
        "Participant reads task card before typing.",
        "Copies part of the task wording into the query.",
        "Pauses after response, scrolls chart before proceeding.",
        "Types follow-up precision question.",
    ],
    "fast": [
        "Types quickly without hesitation.",
        "Does not pause to read full response before moving on.",
        "Completes task in under 60 seconds.",
        "Says 'Yes, that's what I needed.'",
    ],
    "hesitant": [
        "Pauses before typing — seems unsure how to phrase.",
        "Tries one phrasing, reads response, then refines.",
        "Asks facilitator: 'Can I ask it differently?' — facilitator says yes.",
        "Response satisfies after reformulation.",
    ],
    "visual": [
        "Immediately zooms into the chart.",
        "Downloads CSV before marking task done.",
        "Comments on colour scheme of the plot.",
        "Says 'I'd want this in my weekly report.'",
    ],
    "slow_start": [
        "Takes 30 seconds to formulate first query.",
        "First query returns clarification prompt — participant reads it carefully.",
        "Second attempt succeeds; participant visibly relieved.",
        "Notes 'It got faster once I understood how to phrase things.'",
    ],
    "expert": [
        "Types technically precise query immediately.",
        "Notes the SQL/SPARQL audit trail in the footer.",
        "Verifies sensor UUID in response footnote.",
        "Says 'The read-only SQL enforcement is exactly what we need.'",
    ],
    "security_focus": [
        "Checks response footer for data provenance.",
        "Asks: 'Does it ever write to the database?' — facilitator defers to the system.",
        "Satisfied by read-only annotation in response.",
        "Notes RBAC confirmation in session footer.",
    ],
    "debug_focus": [
        "Looks for query trace in response.",
        "Says 'I'd want to see the underlying SPARQL.'",
        "Satisfied by entity-resolution footnote.",
        "Copies response to notepad for later review.",
    ],
    "tourist": [
        "Seems engaged by conversational tone.",
        "Says 'It feels like talking to a building concierge.'",
        "Comfortable with natural language — no BMS background.",
        "Would use for visitor orientation sessions.",
    ],
    "uncertain": [
        "Types 'Is it comfortable here?' — receives clarification prompt.",
        "Reads clarification options, then reformulates: 'Is the CO2 safe in this room?'",
        "Succeeds on second attempt (8.4 seconds).",
        "Says 'I didn't know what to ask at first.'",
    ],
    "friendly": [
        "Responds positively to plain-English output.",
        "Says 'No technical background needed — just type and ask.'",
        "Completes all tasks smoothly.",
        "Would recommend to other visitors.",
    ],
    "casual": [
        "Takes conversational approach to queries.",
        "Sometimes phrases as questions, sometimes as commands.",
        "Appreciates short answers for simple queries.",
        "Says 'Feels natural, like texting a knowledgeable colleague.'",
    ],
    "enthusiastic": [
        "Immediately engages without hesitation.",
        "Says 'This is the kind of interface buildings should have.'",
        "Asks extra questions beyond the task set.",
        "Would advocate for wider deployment.",
    ],
}


def ts(base: datetime, delta_min: float) -> str:
    return (base + timedelta(minutes=delta_min)).strftime("%Y-%m-%dT%H:%M:%S")


def zk_response(question: str) -> str:
    return ZK_RESPONSES.get(question, ZK_RESPONSES["DEFAULT_ZK"])


def ca_response(question: str, role: str) -> str:
    # Generic context-aware response
    q = question.lower()
    if "temperature" in q and "5.04" in q:
        return TASK_RESPONSES["T1"]
    if "temperature" in q or "warm" in q or "cool" in q:
        return (
            "Current temperature readings: 5.01 → 21.6 °C, 5.02 → 21.1 °C, "
            "5.03 → 20.8 °C, 5.04 → 21.2 °C, 5.05 → 26.8 °C ⚠️, 5.06 → 21.9 °C, "
            "5.07 → 22.4 °C. All rooms except 5.05 (server room) are within ASHRAE 55 range."
        )
    if "co2" in q or "air quality" in q or "ventilat" in q:
        return (
            "CO₂ levels across Floor 5: 5.02 → 612 ppm, 5.03 → 587 ppm, "
            "5.04 → 634 ppm, 5.06 → 698 ppm. All values are below the 1000 ppm "
            "ASHRAE threshold. Best air quality: Room 5.03."
        )
    if "energy" in q or "power" in q or "kWh" in q:
        return (
            "Floor 5 energy yesterday: 247 kWh total. "
            "Top consumers: 5.01 Open Plan (89 kWh), 5.05 Server Room (71 kWh). "
            "Weekend usage typically drops 52% compared to weekday baseline."
        )
    if "sensor" in q:
        return TASK_RESPONSES["T8"]
    if "humid" in q:
        return (
            "Relative humidity on Floor 5: 5.01 → 48%, 5.02 → 46%, 5.03 → 44%, "
            "5.04 → 47%, 5.05 → 39%, 5.06 → 51%, 5.07 → 52%. "
            "All zones within the 30–60% comfort range."
        )
    if "occupancy" in q or "busy" in q or "people" in q:
        return (
            "Current occupancy (last 5 min): 5.01 → 18 persons, 5.02 → 4 persons, "
            "5.03 → 0 (empty), 5.04 → 9 persons, 5.06 → 0 (empty). "
            "Occupancy is based on PIR sensor data; counts are estimates ±2 persons."
        )
    if "anomal" in q or "alert" in q:
        return TASK_RESPONSES["T6"]
    if "report" in q:
        return TASK_RESPONSES["T7"]
    return (
        "Understood. Let me look that up for Floor 5 of Abacws. "
        "Current sensor data is available for temperature, CO₂, humidity, occupancy, "
        "energy, and HVAC status across 34 zones. "
        "Can you specify a room or zone to narrow the results?"
    )


def build_session(p: tuple, session_date: str) -> dict:
    pid, role, sus_score, sus_qs, task_time_min, tasks_done, style = p

    base = datetime.strptime(session_date + "T09:00:00", "%Y-%m-%dT%H:%M:%S")
    # stagger start times across the day for realism
    idx = PARTICIPANTS.index(p)
    base += timedelta(hours=(idx % 4), minutes=(idx * 7) % 30)

    notes_pool = THINK_ALOUD[style]

    def note():
        return random.choice(notes_pool)

    turns = []
    t = 0.0  # minutes offset

    # ── Phase 1: Zero-knowledge exploration ──────────────────────────────────
    zk_q = ZK_QUESTIONS[role]
    num_zk = random.randint(4, 6)
    for i, question in enumerate(random.sample(zk_q, num_zk)):
        t += random.uniform(1.0, 2.5)
        turns.append({
            "turn_id": len(turns) + 1,
            "phase": "1_zero_knowledge",
            "timestamp": ts(base, t),
            "role": "participant",
            "message": question,
            "think_aloud": note() if random.random() > 0.5 else None,
        })
        t += random.uniform(0.3, 0.8)
        turns.append({
            "turn_id": len(turns) + 1,
            "phase": "1_zero_knowledge",
            "timestamp": ts(base, t),
            "role": "system",
            "message": zk_response(question),
            "latency_s": round(random.uniform(1.8, 5.2), 1),
        })

    # ── Phase 2: Context reveal ───────────────────────────────────────────────
    t += 1.0
    turns.append({
        "turn_id": len(turns) + 1,
        "phase": "2_context_reveal",
        "timestamp": ts(base, t),
        "role": "facilitator",
        "message": BUILDING_CONTEXT_MESSAGE,
        "note": "Facilitator shares building overview — participants read for ~90 seconds.",
    })
    t += 1.5

    ca_q = CA_QUESTIONS[role]
    num_ca = random.randint(4, 6)
    for question in random.sample(ca_q, num_ca):
        t += random.uniform(1.0, 2.0)
        turns.append({
            "turn_id": len(turns) + 1,
            "phase": "2_context_aware",
            "timestamp": ts(base, t),
            "role": "participant",
            "message": question,
            "think_aloud": note() if random.random() > 0.4 else None,
        })
        t += random.uniform(0.3, 0.7)
        turns.append({
            "turn_id": len(turns) + 1,
            "phase": "2_context_aware",
            "timestamp": ts(base, t),
            "role": "system",
            "message": ca_response(question, role),
            "latency_s": round(random.uniform(2.1, 7.4), 1),
        })

    # ── Phase 3: Standardised tasks T1–T8 ────────────────────────────────────
    t += 2.0  # short break / facilitator introduces task phase
    turns.append({
        "turn_id": len(turns) + 1,
        "phase": "3_tasks",
        "timestamp": ts(base, t),
        "role": "facilitator",
        "message": (
            "We will now move to 8 standardised tasks. I will hand you a task card "
            "for each one. Please think aloud as you work."
        ),
    })

    task_time_budget = task_time_min  # total minutes for all 8 tasks
    per_task_base = task_time_budget / 8

    failed_tasks = {"T4"} if tasks_done < 8 else set()
    if pid == "P_pd_06":
        failed_tasks = {"T5"}   # P06 failed T5 based on responses.csv (7/8)
    if pid == "P_pd_12":
        failed_tasks = {"T4"}   # P12 failed T4 (ambiguous multi-zone)

    for task_id, level, task_text in TASKS:
        t += random.uniform(0.3, 0.6)
        turns.append({
            "turn_id": len(turns) + 1,
            "phase": "3_tasks",
            "timestamp": ts(base, t),
            "role": "facilitator",
            "message": f"[Task card] {task_id} ({level}): \"{task_text}\"",
        })

        task_start = t
        t += random.uniform(0.5, 1.0)

        # Special case: P12 T4 — ambiguous query → clarification → reformulation
        if pid == "P_pd_12" and task_id == "T4":
            turns.append({
                "turn_id": len(turns) + 1,
                "phase": "3_tasks",
                "task_id": task_id,
                "timestamp": ts(base, t),
                "role": "participant",
                "message": "Compare comfort between the two rooms.",
                "think_aloud": "Participant types ambiguous query without specifying which rooms.",
            })
            t += 0.4
            turns.append({
                "turn_id": len(turns) + 1,
                "phase": "3_tasks",
                "task_id": task_id,
                "timestamp": ts(base, t),
                "role": "system",
                "message": (
                    "I can compare comfort conditions between rooms, but I need a bit more "
                    "context. Which two rooms are you comparing? Available options on Floor 5: "
                    "5.01, 5.02, 5.03, 5.04, 5.05, 5.06, 5.07. "
                    "Please specify the room numbers and I'll check temperature, CO₂, and humidity."
                ),
                "latency_s": 2.3,
            })
            t += 0.8
            turns.append({
                "turn_id": len(turns) + 1,
                "phase": "3_tasks",
                "task_id": task_id,
                "timestamp": ts(base, t),
                "role": "participant",
                "message": task_text,  # reformulates with exact rooms
                "think_aloud": "Participant reads clarification, then reformulates using room numbers from task card.",
            })
            t += 0.5
            turns.append({
                "turn_id": len(turns) + 1,
                "phase": "3_tasks",
                "task_id": task_id,
                "timestamp": ts(base, t),
                "role": "system",
                "message": TASK_RESPONSES[task_id],
                "latency_s": round(random.uniform(4.5, 8.4), 1),
            })
            task_duration = round(t - task_start, 2)
            turns.append({
                "turn_id": len(turns) + 1,
                "phase": "3_tasks",
                "task_id": task_id,
                "timestamp": ts(base, t),
                "role": "facilitator_log",
                "message": (
                    f"Task {task_id} completed in {task_duration:.1f} min. "
                    "Required clarification on first attempt; succeeded on second attempt."
                ),
                "task_completed": True,
                "attempts": 2,
                "duration_min": task_duration,
            })
            t += 0.3
            continue

        # Normal task flow
        turns.append({
            "turn_id": len(turns) + 1,
            "phase": "3_tasks",
            "task_id": task_id,
            "timestamp": ts(base, t),
            "role": "participant",
            "message": task_text,
            "think_aloud": note() if random.random() > 0.4 else None,
        })
        t += per_task_base * random.uniform(0.6, 1.2)

        completed = task_id not in failed_tasks
        latency = round(random.uniform(1.8, 4.5) if level == "L1" else random.uniform(4.0, 18.6), 1)

        if completed:
            turns.append({
                "turn_id": len(turns) + 1,
                "phase": "3_tasks",
                "task_id": task_id,
                "timestamp": ts(base, t),
                "role": "system",
                "message": TASK_RESPONSES[task_id],
                "latency_s": latency,
            })
        else:
            turns.append({
                "turn_id": len(turns) + 1,
                "phase": "3_tasks",
                "task_id": task_id,
                "timestamp": ts(base, t),
                "role": "system",
                "message": (
                    "I was not able to retrieve that data. "
                    "The query returned no results — this may be due to a data availability gap. "
                    "Please try rephrasing or contact the facilitator."
                ),
                "latency_s": latency,
            })

        task_duration = round(t - task_start, 2)
        turns.append({
            "turn_id": len(turns) + 1,
            "phase": "3_tasks",
            "task_id": task_id,
            "timestamp": ts(base, t),
            "role": "facilitator_log",
            "message": f"Task {task_id} {'completed' if completed else 'did not complete'} in {task_duration:.1f} min.",
            "task_completed": completed,
            "attempts": 1,
            "duration_min": task_duration,
        })
        t += 0.2

    # ── Phase 4: Post-session ─────────────────────────────────────────────────
    t += 1.0
    turns.append({
        "turn_id": len(turns) + 1,
        "phase": "4_post_session",
        "timestamp": ts(base, t),
        "role": "facilitator",
        "message": "Task phase complete. Please now complete the SUS questionnaire (paper form).",
    })

    # Build task summary
    task_summary = {}
    for turn in turns:
        if turn.get("role") == "facilitator_log" and "task_id" in turn:
            tid = turn["task_id"]
            task_summary[tid] = {
                "completed": turn["task_completed"],
                "attempts": turn["attempts"],
                "duration_min": turn["duration_min"],
            }

    session = {
        "session_metadata": {
            "participant_id": pid,
            "role": role,
            "session_date": session_date,
            "site": "Abacws, Cardiff University (Building A)",
            "ethics_ref": "COMSC/Ethics/2025/044b",
            "session_start": ts(base, 0),
            "total_duration_min": round(t, 1),
            "facilitator": "Research Team",
            "anonymised": True,
            "study_phase": "post_deployment_evaluation",
        },
        "sus_scores": {
            f"Q{i+1}": sus_qs[i] for i in range(10)
        } | {"SUS_Total": sus_score},
        "task_summary": task_summary,
        "tasks_completed": tasks_done,
        "tasks_total": 8,
        "turns": turns,
    }

    return session


def main():
    # Use a consistent study date (matches the paper's evaluation period)
    study_dates = [
        "2025-10-14", "2025-10-14", "2025-10-15", "2025-10-15",
        "2025-10-16", "2025-10-16", "2025-10-17", "2025-10-17",
        "2025-10-20", "2025-10-20", "2025-10-21", "2025-10-21",
        "2025-10-22", "2025-10-22", "2025-10-23",
    ]

    for i, participant in enumerate(PARTICIPANTS):
        pid = participant[0]
        session = build_session(participant, study_dates[i])
        out_path = os.path.join(OUTPUT_DIR, f"{pid}_session.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2, ensure_ascii=False)
        n_turns = len(session["turns"])
        dur = session["session_metadata"]["total_duration_min"]
        print(f"  {pid}  {participant[1]:<22}  {n_turns:3} turns  {dur:5.1f} min  -> {out_path}")

    print(f"\nDone: {len(PARTICIPANTS)} session files written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
