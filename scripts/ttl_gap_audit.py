#!/usr/bin/env python
"""
TTL Gap Audit — OntoSage
========================
Tests a representative sample of survey questions and pipeline test questions
against the live OntoSage system, then produces a structured gap-analysis
document noting which questions would be answerable if specific BrickSchema
triples were added to the input TTL file.

Run:
  python scripts/ttl_gap_audit.py

Output:
  scripts/outputs/ttl_gap_analysis.md
  scripts/outputs/ttl_gap_audit_raw.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import httpx

    def _post(url, payload, timeout=45):
        with httpx.Client(timeout=timeout) as c:
            r = c.post(url, json=payload)
            return r.status_code, r.json()

except ImportError:
    import urllib.error
    import urllib.request

    def _post(url, payload, timeout=45):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read())
        except Exception as e:
            return 0, {"error": str(e)}


BASE_URL = os.environ.get("ONTOSAGE_URL", "http://localhost:8000")
CHAT_URL = f"{BASE_URL}/v1/chat/completions"
OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# CURATED TEST QUESTIONS  — 50 questions, covers all 20 survey topic domains
# Each dict: id, topic (1-20), domain_label, question, source, expected_data,
#   ttl_note (what BrickSchema triples would be needed for a gap)
# ---------------------------------------------------------------------------
QUESTIONS: List[Dict[str, Any]] = [
    # ── TOPIC 1: Indoor Temperature Control ──────────────────────────────
    {
        "id": "T01a",
        "topic": 1,
        "domain": "Indoor Temperature Control",
        "question": "What is the current temperature in Zone 5.28?",
        "source": "pipeline_test",
        "expected": "numeric temperature reading with units",
    },
    {
        "id": "T01b",
        "topic": 1,
        "domain": "Indoor Temperature Control",
        "question": "How does the building prevent cold or hot spots in large areas?",
        "source": "survey",
        "expected": "explanation of temperature management strategy",
    },
    {
        "id": "T01c",
        "topic": 1,
        "domain": "Indoor Temperature Control",
        "question": "Are there noticeable temperature differences between floors?",
        "source": "survey",
        "expected": "comparison of per-floor temperature readings",
    },
    # ── TOPIC 2: Air Quality & Ventilation ───────────────────────────────
    {
        "id": "T02a",
        "topic": 2,
        "domain": "Air Quality & Ventilation",
        "question": "What is the current CO2 level in the office area?",
        "source": "pipeline_test",
        "expected": "CO2 reading in ppm",
    },
    {
        "id": "T02b",
        "topic": 2,
        "domain": "Air Quality & Ventilation",
        "question": "How does the building respond to sudden increases in indoor pollutants?",
        "source": "survey",
        "expected": "explanation of ventilation/alert response",
    },
    {
        "id": "T02c",
        "topic": 2,
        "domain": "Air Quality & Ventilation",
        "question": "If CO2 rises in a meeting room, what should the building do automatically?",
        "source": "survey",
        "expected": "automated ventilation response details",
    },
    # ── TOPIC 3: Lighting & Daylight ─────────────────────────────────────
    {
        "id": "T03a",
        "topic": 3,
        "domain": "Lighting & Daylight",
        "question": "What is the current light level in the open-plan office?",
        "source": "pipeline_test",
        "expected": "lux reading",
    },
    {
        "id": "T03b",
        "topic": 3,
        "domain": "Lighting & Daylight",
        "question": "Are there any zones where lighting is too dim for work right now?",
        "source": "survey",
        "expected": "zones with low lux levels",
    },
    {
        "id": "T03c",
        "topic": 3,
        "domain": "Lighting & Daylight",
        "question": "Are adaptive lighting systems used to support circadian rhythms?",
        "source": "survey",
        "expected": "information about lighting schedule or control strategy",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Circadian_Lighting_Control entity, brick:Luminaire with hasProperty brick:Color_Temperature_Setpoint, lighting schedules linked to time-of-day",
    },
    # ── TOPIC 4: Noise & Acoustics ────────────────────────────────────────
    {
        "id": "T04a",
        "topic": 4,
        "domain": "Noise & Acoustics",
        "question": "What is the current noise level in the open-plan office?",
        "source": "pipeline_test",
        "expected": "decibel reading from noise sensor",
    },
    {
        "id": "T04b",
        "topic": 4,
        "domain": "Noise & Acoustics",
        "question": "Are there any areas where noise levels suddenly increased?",
        "source": "survey",
        "expected": "noise anomaly report",
    },
    {
        "id": "T04c",
        "topic": 4,
        "domain": "Noise & Acoustics",
        "question": "Are there systems to reduce echo or sound disturbances in open offices?",
        "source": "survey",
        "expected": "acoustic treatment or management info",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Acoustic_Panel or brick:Sound_Masking_System entities, no sound absorption / reverberation properties linked to rooms",
    },
    # ── TOPIC 5: Energy Consumption ───────────────────────────────────────
    {
        "id": "T05a",
        "topic": 5,
        "domain": "Energy Consumption",
        "question": "What is the current energy demand compared to typical usage?",
        "source": "survey",
        "expected": "energy comparison with baseline",
    },
    {
        "id": "T05b",
        "topic": 5,
        "domain": "Energy Consumption",
        "question": "How is energy distributed across different systems like HVAC, lighting, and equipment?",
        "source": "survey",
        "expected": "sub-metered energy breakdown",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Electrical_Meter instances for each subsystem (HVAC, Lighting, Plug_Load) with brick:isPartOf links; currently only whole-building meters exist",
    },
    {
        "id": "T05c",
        "topic": 5,
        "domain": "Energy Consumption",
        "question": "Can the building automatically optimize energy use during weekends or holidays?",
        "source": "survey",
        "expected": "scheduling / occupancy-based control strategy",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Schedule entity with hasProperty brick:Occupancy_Schedule, setback setpoints for weekend/holiday modes on HVAC and lighting",
    },
    # ── TOPIC 6: Security & Access Control ────────────────────────────────
    {
        "id": "T06a",
        "topic": 6,
        "domain": "Security & Access Control",
        "question": "How many people have accessed the building today?",
        "source": "pipeline_test",
        "expected": "access count figure",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Door_Position_Sensor or brick:Entry_Reader entities with timeseries UUID links; current TTL has only 5 Access_Control references with no time-series data wired",
    },
    {
        "id": "T06b",
        "topic": 6,
        "domain": "Security & Access Control",
        "question": "Are there any unusual access activities detected late at night?",
        "source": "survey",
        "expected": "after-hours access anomaly",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Door_Position_Sensor with isLocatedIn room links and timeseries UUID; anomaly detection needs actual access log data in MySQL",
    },
    {
        "id": "T06c",
        "topic": 6,
        "domain": "Security & Access Control",
        "question": "How to find security bottlenecks?",
        "source": "survey",
        "expected": "analysis of access choke points",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Entry_Reader instances per door with brick:isPartOf floor/zone links; need access count timeseries to identify bottlenecks analytically",
    },
    # ── TOPIC 7: Occupancy & Space Utilisation ────────────────────────────
    {
        "id": "T07a",
        "topic": 7,
        "domain": "Occupancy & Space Utilisation",
        "question": "Can the building identify underutilized space to improve efficiency?",
        "source": "survey",
        "expected": "underutilised zone analysis",
    },
    {
        "id": "T07b",
        "topic": 7,
        "domain": "Occupancy & Space Utilisation",
        "question": "Which rooms are currently closest to their maximum capacity?",
        "source": "survey",
        "expected": "occupancy near capacity list",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Room_Max_Occupancy property on each brick:Room entity, brick:Occupancy_Sensor with timeseries UUID per room; current TTL has only 10 Occupancy_Sensor instances without capacity annotations",
    },
    {
        "id": "T07c",
        "topic": 7,
        "domain": "Occupancy & Space Utilisation",
        "question": "Are there conference rooms that can be reserved for an hour?",
        "source": "survey",
        "expected": "room booking / availability",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Meeting_Room entities with brick:hasProperty brick:Room_Booking_Status; room-booking system integration (calendar API) not present in ontology",
    },
    # ── TOPIC 8: Fire Safety & Emergency ──────────────────────────────────
    {
        "id": "T08a",
        "topic": 8,
        "domain": "Fire Safety & Emergency",
        "question": "Which areas are safest in case of an emergency evacuation?",
        "source": "survey",
        "expected": "evacuation route / assembly point info",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Emergency_Exit entities with brick:isLocatedIn and brick:connectedTo adjacency links; brick:Assembly_Point location; emergency route topology",
    },
    {
        "id": "T08b",
        "topic": 8,
        "domain": "Fire Safety & Emergency",
        "question": "Does the smoke sensor log who was in the room when an alert triggered?",
        "source": "survey",
        "expected": "fire event with occupancy correlation",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Smoke_Detector with brick:isAssociatedWith brick:Occupancy_Sensor in same room; event correlation requires both sensors linked to same space entity",
    },
    {
        "id": "T08c",
        "topic": 8,
        "domain": "Fire Safety & Emergency",
        "question": "Are any fire exits currently blocked or improperly propped?",
        "source": "survey",
        "expected": "fire exit door status",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Emergency_Exit with brick:Door_Position_Sensor (isLocatedIn exit), timeseries UUID for door open/closed status",
    },
    # ── TOPIC 9: Water Management ─────────────────────────────────────────
    {
        "id": "T09a",
        "topic": 9,
        "domain": "Water Management",
        "question": "Are there sudden spikes in water usage that need attention?",
        "source": "survey",
        "expected": "water anomaly detection",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Water_Meter with timeseries UUID (current Water_Meter exists in TTL but needs hasExternalReference brick:hasTimeseriesId to connect to MySQL); no water consumption history loaded",
    },
    {
        "id": "T09b",
        "topic": 9,
        "domain": "Water Management",
        "question": "Can the Water Meter detect if a pipe or appliance has been left running or is leaking?",
        "source": "survey",
        "expected": "water leak / continuous flow detection",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Leak_Detector entities (water leak sensor class), flow rate baseline threshold annotation on brick:Water_Meter; need continuous-flow anomaly rule",
    },
    {
        "id": "T09c",
        "topic": 9,
        "domain": "Water Management",
        "question": "How does the building support water conservation during peak usage?",
        "source": "survey",
        "expected": "water conservation strategy / setpoints",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Water_Flow_Setpoint on fixtures, peak-usage schedule annotations, water reclamation / greywater reuse system entities",
    },
    # ── TOPIC 10: Waste & Recycling ───────────────────────────────────────
    {
        "id": "T10a",
        "topic": 10,
        "domain": "Waste & Recycling",
        "question": "Can the system suggest improvements for better recycling habits?",
        "source": "survey",
        "expected": "recycling recommendation",
        "ttl_gap": True,
        "ttl_note": "No waste/recycling entities at all in TTL. Need: brick:Waste_Bin (custom extension) with hasProperty brick:Fill_Level_Sensor UUID, location (isLocatedIn), waste type annotation; fill-level timeseries in MySQL",
    },
    {
        "id": "T10b",
        "topic": 10,
        "domain": "Waste & Recycling",
        "question": "How does the building manage waste during high-occupancy events?",
        "source": "survey",
        "expected": "waste management strategy during events",
        "ttl_gap": True,
        "ttl_note": "Same as T10a — also need occupancy event schedule linked to waste collection schedule; brick:Event_Schedule entity with peak_waste annotation",
    },
    # ── TOPIC 11: Renewable Energy & Solar ────────────────────────────────
    {
        "id": "T11a",
        "topic": 11,
        "domain": "Renewable Energy & Solar",
        "question": "Is there any information about solar panels on the building?",
        "source": "survey",
        "expected": "PV panel or solar generation data",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:PV_Panel (or brick:Solar_Panel) entity with brick:hasPoint brick:Solar_Irradiance_Sensor and brick:Electrical_Power_Sensor for generated kW; PV generation not present despite PV tag appearing 40 times",
    },
    {
        "id": "T11b",
        "topic": 11,
        "domain": "Renewable Energy & Solar",
        "question": "Could the building calculate carbon emissions saved by using daylight harvesting instead of LEDs?",
        "source": "survey",
        "expected": "carbon savings calculation from lighting",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Carbon_Emission_Factor annotation on brick:Electrical_Meter; needs integration of energy consumed (kWh) with grid carbon intensity factor (gCO2/kWh) stored as a building parameter",
    },
    # ── TOPIC 12: Green Spaces & Biodiversity ─────────────────────────────
    {
        "id": "T12a",
        "topic": 12,
        "domain": "Green Spaces & Biodiversity",
        "question": "Are there any insights on how indoor plants contribute to air purification?",
        "source": "survey",
        "expected": "plant / VOC correlation info",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Indoor_Plant entity (schema extension) with isLocatedIn room and associated brick:TVOC_Sensor correlation; no vegetation entities in TTL",
    },
    {
        "id": "T12b",
        "topic": 12,
        "domain": "Green Spaces & Biodiversity",
        "question": "How could sensors track biodiversity indicators like bird or insect activity on green roofs?",
        "source": "survey",
        "expected": "green roof sensor concept",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Green_Roof entity (roof zone) with associated sensor points; no exterior green space entities; would require custom Brick extension for biodiversity sensors",
    },
    # ── TOPIC 13: Health & Well-being ─────────────────────────────────────
    {
        "id": "T13a",
        "topic": 13,
        "domain": "Health & Well-being",
        "question": "Are there any environmental conditions that might affect health in this area?",
        "source": "survey",
        "expected": "health-relevant sensor summary (CO2, PM2.5, humidity, temperature)",
    },
    {
        "id": "T13b",
        "topic": 13,
        "domain": "Health & Well-being",
        "question": "What is the threshold for relative humidity before warning about mold risk?",
        "source": "survey",
        "expected": "humidity threshold / mold risk policy",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Humidity_Setpoint with annotation for mold-risk threshold (>70% RH for extended periods); need brick:hasProperty brick:Relative_Humidity_Setpoint max/min bounds on zones",
    },
    {
        "id": "T13c",
        "topic": 13,
        "domain": "Health & Well-being",
        "question": "Can the system predict a productivity dip by correlating CO2 with low motion in the afternoon?",
        "source": "survey",
        "expected": "multi-sensor correlation analysis",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:CO2_Sensor and brick:Occupancy_Sensor must share isLocatedIn the same brick:Room to enable cross-sensor correlation query; many rooms have one but not both co-located",
    },
    # ── TOPIC 14: IoT Sensors & Data Analytics ────────────────────────────
    {
        "id": "T14a",
        "topic": 14,
        "domain": "IoT Sensors & Data Analytics",
        "question": "What sensors are available in the building?",
        "source": "pipeline_test",
        "expected": "sensor discovery list",
    },
    {
        "id": "T14b",
        "topic": 14,
        "domain": "IoT Sensors & Data Analytics",
        "question": "What cross-system correlations could reveal hidden inefficiencies or comfort issues?",
        "source": "survey",
        "expected": "multi-sensor analytics recommendation",
    },
    # ── TOPIC 15: Lifts, Stairs & Internal Transport ──────────────────────
    {
        "id": "T15a",
        "topic": 15,
        "domain": "Lifts & Internal Transport",
        "question": "What is the standby energy load of the elevator system?",
        "source": "survey",
        "expected": "elevator energy data",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Elevator with brick:hasPoint brick:Electrical_Power_Sensor (UUID linked to MySQL), standby mode annotation; TTL has Elevator (14 instances) but no power sensor wiring",
    },
    {
        "id": "T15b",
        "topic": 15,
        "domain": "Lifts & Internal Transport",
        "question": "How could real-time occupancy data reduce lift wait times during peak hours?",
        "source": "survey",
        "expected": "lift demand analytics concept",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Elevator with brick:isLocatedIn floor links and brick:Occupancy_Sensor per floor lobby; need floor-level headcount timeseries to correlate with elevator calls",
    },
    # ── TOPIC 16: Parking & EV Charging ──────────────────────────────────
    {
        "id": "T16a",
        "topic": 16,
        "domain": "Parking & EV Charging",
        "question": "Are there EV charging stations in the car park?",
        "source": "survey",
        "expected": "EV charger availability / status",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:EV_Charging_Station entity with brick:hasPoint brick:Charging_State_Sensor and brick:Electrical_Power_Sensor; no EV charger entities in TTL",
    },
    {
        "id": "T16b",
        "topic": 16,
        "domain": "Parking & EV Charging",
        "question": "Does the NO2 sensor in the car park trigger exhaust fans when a car is detected?",
        "source": "survey",
        "expected": "car park ventilation control logic",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Parking_Space (or Garage) zone entity containing the NO2_Sensor and Fan equipment with explicit brick:isControlledBy relationship",
    },
    # ── TOPIC 17: Building Automation & AI ────────────────────────────────
    {
        "id": "T17a",
        "topic": 17,
        "domain": "Building Automation & AI",
        "question": "What HVAC equipment is installed in the building?",
        "source": "pipeline_test",
        "expected": "HVAC equipment list",
    },
    {
        "id": "T17b",
        "topic": 17,
        "domain": "Building Automation & AI",
        "question": "Can the building detect and reduce ghost energy from unused spaces?",
        "source": "survey",
        "expected": "phantom load / standby power detection",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Plug_Load_Meter per zone with brick:isLocatedIn room and timeseries UUID; standby threshold annotation on equipment instances; currently only bulk energy meters present",
    },
    # ── TOPIC 18: User Apps & Digital Interaction ──────────────────────────
    {
        "id": "T18a",
        "topic": 18,
        "domain": "User Apps & Digital Interaction",
        "question": "Can the system suggest a workspace based on my preferred noise and lighting levels?",
        "source": "survey",
        "expected": "personalised workspace recommendation",
    },
    {
        "id": "T18b",
        "topic": 18,
        "domain": "User Apps & Digital Interaction",
        "question": "Can you help me find a workspace close to the building entrance?",
        "source": "survey",
        "expected": "proximity-based workspace suggestion",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Room with brick:distanceToEntrance property or brick:isAdjacentTo brick:Building_Entrance; spatial proximity metadata not in TTL (floor plan manifests have geometry but ontology doesn't expose it via SPARQL)",
    },
    # ── TOPIC 19: Building Maintenance & Faults ────────────────────────────
    {
        "id": "T19a",
        "topic": 19,
        "domain": "Building Maintenance & Faults",
        "question": "Are any floors currently under maintenance?",
        "source": "survey",
        "expected": "maintenance status per floor",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Maintenance_Work_Order entity (custom) with isLocatedIn floor/zone and hasProperty brick:Maintenance_Status; no maintenance-state tracking in ontology",
    },
    {
        "id": "T19b",
        "topic": 19,
        "domain": "Building Maintenance & Faults",
        "question": "Is any equipment behaving inconsistently compared to normal operation?",
        "source": "survey",
        "expected": "equipment fault/anomaly detection",
    },
    {
        "id": "T19c",
        "topic": 19,
        "domain": "Building Maintenance & Faults",
        "question": "Can vibration sensors tell if a pump is starting to wear out?",
        "source": "survey",
        "expected": "vibration-based predictive maintenance",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Vibration_Sensor with brick:isAssociatedWith brick:Pump entity (co-located); current TTL has Pump instances and some vibration sensor references but no explicit association between them",
    },
    # ── TOPIC 20: Carbon Footprint & Net Zero ──────────────────────────────
    {
        "id": "T20a",
        "topic": 20,
        "domain": "Carbon Footprint & Net Zero",
        "question": "Are there performance indicators for overall building sustainability?",
        "source": "survey",
        "expected": "sustainability KPI overview",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Carbon_Dioxide_Emission_Sensor or building-level carbon intensity parameter; no CO2 emission (as opposed to CO2 concentration) concept in TTL; need EPC rating or carbon baseline annotation on bldg:AbacwsBuilding",
    },
    {
        "id": "T20b",
        "topic": 20,
        "domain": "Carbon Footprint & Net Zero",
        "question": "How does the building plan upgrades to meet future sustainability standards?",
        "source": "survey",
        "expected": "building improvement roadmap",
        "ttl_gap": True,
        "ttl_note": "Missing: brick:Energy_Performance_Certificate annotation with current and target EPC band, brick:RetrofitPlan entity (custom) listing planned equipment upgrades",
    },
]


def chat(question: str, session_id: str = "audit-session-001") -> Tuple[str, float, int]:
    """Send question to the orchestrator, return (response_text, latency_s, status_code)."""
    payload = {
        "model": "ontosage",
        "messages": [{"role": "user", "content": question}],
        "stream": False,
        "user": session_id,
    }
    t0 = time.time()
    try:
        status, body = _post(CHAT_URL, payload, timeout=60)
        latency = time.time() - t0
        if status == 200:
            choices = body.get("choices", [])
            if choices:
                text = choices[0].get("message", {}).get("content", "")
                return text.strip(), latency, status
        return f"[HTTP {status}] {body}", time.time() - t0, status
    except Exception as e:
        return f"[ERROR] {e}", time.time() - t0, 0


def evaluate_response(question: str, response: str, expected: str) -> Dict[str, Any]:
    """Heuristic quality assessment of a response."""
    r = response.lower()
    q = question.lower()

    has_content = len(response.strip()) > 30
    not_error = not any(
        x in r for x in ["error", "sorry, i", "i cannot", "i don't have", "no data", "unable to"]
    )
    has_number = any(c.isdigit() for c in response)
    has_unit = any(u in r for u in ["°c", "ppm", "lux", "db", "kw", "kwh", "%", "celsius"])
    decline_phrases = [
        "i don't have access",
        "not available",
        "no information",
        "cannot answer",
        "outside my",
        "i'm not able",
        "no data available",
        "no sensor",
        "cannot find",
    ]
    is_decline = any(p in r for p in decline_phrases)
    is_general_advice = any(
        p in r
        for p in [
            "typically",
            "generally",
            "in most buildings",
            "usually",
            "smart buildings typically",
            "in general",
        ]
    )

    # Score: 3=good data answer, 2=generic/advice answer, 1=decline/error, 0=error
    if has_content and not_error and not is_decline and not is_general_advice:
        score = 3
        verdict = "GOOD"
    elif has_content and (
        is_general_advice or (not is_decline and not has_unit and not has_number)
    ):
        score = 2
        verdict = "GENERIC"
    elif is_decline:
        score = 1
        verdict = "DECLINED"
    else:
        score = 0
        verdict = "ERROR"

    return {
        "score": score,
        "verdict": verdict,
        "has_number": has_number,
        "has_unit": has_unit,
        "is_decline": is_decline,
        "is_generic": is_general_advice,
        "length": len(response),
    }


def main():
    print(f"OntoSage TTL Gap Audit — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Testing {len(QUESTIONS)} questions against {CHAT_URL}\n")

    results = []
    for i, q in enumerate(QUESTIONS, 1):
        qid = q["id"]
        print(f"[{i:02d}/{len(QUESTIONS)}] {qid} ({q['domain'][:30]}) ...", end=" ", flush=True)
        response, latency, status = chat(q["question"])
        evaluation = evaluate_response(q["question"], response, q.get("expected", ""))
        record = {
            **q,
            "response": response,
            "latency_s": round(latency, 2),
            "http_status": status,
            **evaluation,
        }
        results.append(record)
        print(f"{evaluation['verdict']} ({latency:.1f}s)")
        time.sleep(0.5)

    # ──────────────────────────────────────────────────────────────────────
    # Save raw JSON
    # ──────────────────────────────────────────────────────────────────────
    raw_path = os.path.join(OUT_DIR, "ttl_gap_audit_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nRaw results saved → {raw_path}")

    # ──────────────────────────────────────────────────────────────────────
    # Generate Markdown gap-analysis report
    # ──────────────────────────────────────────────────────────────────────
    good = [r for r in results if r["verdict"] == "GOOD"]
    generic = [r for r in results if r["verdict"] == "GENERIC"]
    decline = [r for r in results if r["verdict"] in ("DECLINED", "ERROR")]
    gaps = [r for r in results if r.get("ttl_gap")]

    md = []
    md.append(f"# OntoSage TTL Gap Analysis\n")
    md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    md.append(f"**Questions tested:** {len(results)}  ")
    md.append(
        f"**Good answers:** {len(good)}  **Generic/partial:** {len(generic)}  **Declined/Error:** {len(decline)}\n"
    )
    md.append("---\n")

    md.append("## Summary by Topic Domain\n")
    md.append("| # | Domain | Questions | Good | Generic | Declined | TTL gaps |\n")
    md.append("|---|--------|-----------|------|---------|----------|----------|\n")
    by_topic: Dict[int, List] = {}
    for r in results:
        by_topic.setdefault(r["topic"], []).append(r)
    for t in sorted(by_topic):
        rows = by_topic[t]
        g = sum(1 for x in rows if x["verdict"] == "GOOD")
        gn = sum(1 for x in rows if x["verdict"] == "GENERIC")
        d = sum(1 for x in rows if x["verdict"] in ("DECLINED", "ERROR"))
        gap = sum(1 for x in rows if x.get("ttl_gap"))
        domain = rows[0]["domain"]
        md.append(f"| {t} | {domain} | {len(rows)} | {g} | {gn} | {d} | {gap} |\n")
    md.append("\n")

    md.append("---\n\n## Section A — Questions Answered Well (no TTL changes needed)\n\n")
    for r in good:
        md.append(f"### {r['id']} — {r['domain']}\n")
        md.append(f"**Question:** {r['question']}  \n")
        md.append(
            f"**Verdict:** {r['verdict']} | Latency: {r['latency_s']}s | Length: {r['length']} chars\n\n"
        )
        snippet = r["response"][:400].replace("\n", " ")
        md.append(f"> {snippet}{'...' if len(r['response']) > 400 else ''}\n\n")

    md.append(
        "---\n\n## Section B — Generic/Partial Answers (system responds but lacks real data)\n\n"
    )
    for r in generic:
        md.append(f"### {r['id']} — {r['domain']}\n")
        md.append(f"**Question:** {r['question']}  \n")
        md.append(f"**Verdict:** {r['verdict']} | Latency: {r['latency_s']}s\n\n")
        snippet = r["response"][:400].replace("\n", " ")
        md.append(f"> {snippet}{'...' if len(r['response']) > 400 else ''}\n\n")
        if r.get("ttl_gap"):
            md.append(f"**TTL Gap:** {r['ttl_note']}\n\n")

    md.append("---\n\n## Section C — Declined / Error (no useful answer returned)\n\n")
    for r in decline:
        md.append(f"### {r['id']} — {r['domain']}\n")
        md.append(f"**Question:** {r['question']}  \n")
        md.append(
            f"**Verdict:** {r['verdict']} | HTTP: {r['http_status']} | Latency: {r['latency_s']}s\n\n"
        )
        snippet = r["response"][:400].replace("\n", " ")
        md.append(f"> {snippet}{'...' if len(r['response']) > 400 else ''}\n\n")
        if r.get("ttl_gap"):
            md.append(f"**TTL Gap:** {r['ttl_note']}\n\n")

    md.append("---\n\n## Section D — TTL Triples Required (all gaps regardless of verdict)\n\n")
    md.append("This section is the primary deliverable. For each question below, adding the\n")
    md.append("described BrickSchema triples to `input/bldg1_enhancements.ttl` would enable\n")
    md.append("the system to answer the question from real ontology data rather than declining\n")
    md.append("or giving generic advice.\n\n")

    # Group gaps by domain
    by_domain: Dict[str, List] = {}
    for r in results:
        if r.get("ttl_gap"):
            by_domain.setdefault(r["domain"], []).append(r)

    for domain, rows in sorted(by_domain.items()):
        md.append(f"### {domain}\n\n")
        for r in rows:
            md.append(f"#### {r['id']} — *{r['question']}*\n\n")
            md.append(f"- **Current answer quality:** {r['verdict']}\n")
            md.append(f"- **Expected answer:** {r.get('expected', 'N/A')}\n")
            md.append(f"- **BrickSchema triples needed:**\n\n")
            md.append(f"  {r['ttl_note']}\n\n")

    md.append("---\n\n## Section E — Recommended TTL Additions (grouped by concept cluster)\n\n")
    md.append("The table below groups the required additions into concept clusters.\n")
    md.append(
        "Implement in `input/bldg1_enhancements.ttl`. Use the existing `bldg:` namespace.\n\n"
    )
    md.append("| Priority | Concept Cluster | Affects Topics | Sample Triple Pattern |\n")
    md.append("|----------|-----------------|----------------|-----------------------|\n")
    md.append(
        '| P1 | **Access Control doors with timeseries** | 6 | `bldg:MainEntrance_Door a brick:Door ; brick:isPartOf bldg:Floor_Ground ; brick:hasPoint bldg:Entry_Count_Sensor_G . bldg:Entry_Count_Sensor_G a brick:Occupancy_Sensor ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        "| P1 | **Occupancy sensors per room with max capacity** | 7, 13 | `bldg:Room_3_01 brick:hasProperty bldg:Room_3_01_MaxOccupancy . bldg:Room_3_01_MaxOccupancy a brick:Max_Occupancy ; brick:value 12 . bldg:Occupancy_Sensor_3_01 brick:isLocatedIn bldg:Room_3_01 .` |\n"
    )
    md.append(
        '| P1 | **Sub-metered electrical meters (HVAC / Lighting / Plug)** | 5, 17 | `bldg:HVAC_Meter_F3 a brick:Electrical_Meter ; brick:isPartOf bldg:Floor_3 ; brick:hasPoint bldg:HVAC_Power_F3 . bldg:HVAC_Power_F3 a brick:Electrical_Power_Sensor ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        '| P1 | **Water meters with timeseries UUIDs** | 9 | `bldg:WaterMeter_Main ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] . bldg:WaterMeter_Main brick:isPartOf bldg:AbacwsBuilding .` |\n'
    )
    md.append(
        '| P2 | **Elevator power sensors** | 15 | `bldg:Elevator_1 a brick:Elevator ; brick:isLocatedIn bldg:Floor_Ground ; brick:hasPoint bldg:Elevator_1_Power . bldg:Elevator_1_Power a brick:Electrical_Power_Sensor ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        "| P2 | **EV charging stations** | 16 | `bldg:EV_Charger_1 a brick:EV_Charging_Station ; brick:isLocatedIn bldg:Parking_Level_B1 ; brick:hasPoint bldg:EV_Charger_1_State, bldg:EV_Charger_1_Power .` |\n"
    )
    md.append(
        '| P2 | **Fire exits + emergency lighting** | 8 | `bldg:FireExit_3_North a brick:Emergency_Exit ; brick:isPartOf bldg:Floor_3 ; brick:hasPoint bldg:FireExit_3_North_Door . bldg:FireExit_3_North_Door a brick:Door_Position_Sensor ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        '| P2 | **Vibration sensors co-located with pumps** | 19 | `bldg:Vibration_Sensor_Pump_1 a brick:Vibration_Sensor ; brick:isAssociatedWith bldg:Pump_HW_1 ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        '| P2 | **PV solar panel generation sensors** | 11, 20 | `bldg:PV_Array_Roof a brick:PV_Panel ; brick:isPartOf bldg:AbacwsBuilding ; brick:hasPoint bldg:PV_Power_Sensor . bldg:PV_Power_Sensor a brick:Electrical_Power_Sensor ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        '| P3 | **Carbon intensity / EPC annotation** | 20 | `bldg:AbacwsBuilding brick:hasProperty bldg:EPC_Rating . bldg:EPC_Rating a brick:Energy_Performance_Certificate ; brick:value "B" ; bldg:carbonIntensityGCO2perkWh 233.0 .` |\n'
    )
    md.append(
        '| P3 | **Humidity mold-risk setpoints** | 13, 2 | `bldg:Floor_3 brick:hasPoint bldg:MoldRisk_Humidity_Threshold_F3 . bldg:MoldRisk_Humidity_Threshold_F3 a brick:Humidity_Setpoint ; brick:value 70.0 ; rdfs:comment "Mold risk threshold" .` |\n'
    )
    md.append(
        '| P3 | **Meeting room booking status** | 7 | `bldg:MeetingRoom_3_01 a brick:Meeting_Room ; brick:hasProperty bldg:MeetingRoom_3_01_BookingStatus . bldg:MeetingRoom_3_01_BookingStatus a brick:Occupancy_Status ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        '| P4 | **Waste/recycling bin fill sensors** | 10 | `bldg:RecycleBin_F3_Kitchen a bldg:Waste_Bin ; bldg:wasteType "recycling" ; brick:isLocatedIn bldg:Kitchen_F3 ; brick:hasPoint bldg:RecycleBin_F3_FillLevel . bldg:RecycleBin_F3_FillLevel a brick:Level_Sensor ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        '| P4 | **Lighting color temperature for circadian** | 3 | `bldg:Luminaire_3_01 a brick:Luminaire ; brick:isLocatedIn bldg:Room_3_01 ; brick:hasPoint bldg:Luminaire_3_01_CCT . bldg:Luminaire_3_01_CCT a brick:Color_Temperature_Setpoint ; ref:hasExternalReference [ref:hasTimeseriesId "<UUID>"] .` |\n'
    )
    md.append(
        '| P4 | **Green roof / outdoor ecology zone** | 12 | `bldg:Green_Roof a brick:Space ; rdfs:label "Rooftop Green Space" ; brick:isPartOf bldg:AbacwsBuilding ; brick:hasPoint bldg:GreenRoof_SoilMoisture, bldg:GreenRoof_Rainfall .` |\n'
    )
    md.append("\n")
    md.append("---\n\n*This document was auto-generated by `scripts/ttl_gap_audit.py`.*\n")
    md.append(
        "*Review Section D for per-question detail and Section E for implementation priorities.*\n"
    )

    out_path = os.path.join(OUT_DIR, "ttl_gap_analysis.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(md)
    print(f"Gap analysis saved  → {out_path}")

    # Final summary
    print(f"\n{'='*60}")
    print(f"RESULTS: {len(good)} GOOD | {len(generic)} GENERIC | {len(decline)} DECLINED")
    print(f"Topics with TTL gaps: {len(by_domain)}/20")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
