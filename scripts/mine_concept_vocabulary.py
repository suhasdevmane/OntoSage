#!/usr/bin/env python3
"""
mine_concept_vocabulary.py — T01 of IMPLEMENTATION PLAN V3.

Mines lay-term -> building-concept vocabulary from the 5,604-question corpus
and seeds ontology/mining/concept_terms_raw.csv for human review before T02 TTL authoring.

The script uses a pre-seeded concept taxonomy (based on Brick schema classes and
common building-comfort vocabulary) enriched by example-question mining from the
master table.  No LLM required; pass --llm-enrich to add LLM cluster refinement
(requires OPENAI_API_KEY).

Usage:
    python scripts/mine_concept_vocabulary.py [--dry-run] [--llm-enrich]
    python scripts/mine_concept_vocabulary.py --corpus path/to/master_table.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = (
    REPO_ROOT
    / "paper"
    / "Survey analysis and results"
    / "outputs"
    / "master table analysis"
    / "complexity_master_table.csv"
)
OUTPUT_DIR = REPO_ROOT / "ontology" / "mining"
OUTPUT_PATH = OUTPUT_DIR / "concept_terms_raw.csv"

OUTPUT_COLUMNS = [
    "concept_id",
    "lay_terms",
    "brick_classes",
    "recipe_kind",
    "composite_of",
    "example_questions",
    "confidence",
]

# ─────────────────────────────────────────────────────────────────────────────
# Concept taxonomy seed
# ─────────────────────────────────────────────────────────────────────────────
# Each entry: (concept_id, [lay_terms], [brick_classes], recipe_kind, composite_of, confidence)
# composite_of: parent concept id (empty string if top-level)

_CONCEPT_SEED = [
    # ── Thermal ──────────────────────────────────────────────────────────────
    (
        "too_warm",
        [
            "too warm",
            "too hot",
            "overheating",
            "feels warm",
            "uncomfortably hot",
            "sweltering",
            "stuffy heat",
            "warm in here",
        ],
        ["brick:Temperature_Sensor", "brick:Zone_Air_Temperature_Sensor"],
        "threshold",
        "thermal_comfort",
        "high",
    ),
    (
        "too_cold",
        [
            "too cold",
            "too cool",
            "chilly",
            "freezing",
            "uncomfortably cold",
            "cold in here",
            "feels cold",
        ],
        ["brick:Temperature_Sensor", "brick:Zone_Air_Temperature_Sensor"],
        "threshold",
        "thermal_comfort",
        "high",
    ),
    (
        "thermal_comfort",
        [
            "thermal comfort",
            "temperature comfort",
            "comfortable temperature",
            "is it comfortable",
            "temperature okay",
        ],
        ["brick:Temperature_Sensor", "brick:Humidity_Sensor"],
        "range",
        "",
        "high",
    ),
    (
        "temperature_reading",
        [
            "temperature",
            "temp",
            "how warm",
            "how hot",
            "how cold",
            "degrees",
            "current temperature",
        ],
        [
            "brick:Temperature_Sensor",
            "brick:Zone_Air_Temperature_Sensor",
            "brick:Outside_Air_Temperature_Sensor",
        ],
        "aggregate",
        "",
        "high",
    ),
    # ── CO2 / Stuffiness ─────────────────────────────────────────────────────
    (
        "stuffiness",
        [
            "stuffy",
            "stale air",
            "airless",
            "muggy",
            "close air",
            "needs fresh air",
            "poor ventilation",
            "stifling",
        ],
        ["brick:CO2_Level_Sensor", "brick:CO2_Sensor"],
        "threshold",
        "iaq_composite",
        "high",
    ),
    (
        "co2_level",
        ["CO2", "carbon dioxide", "co2 level", "co2 concentration", "carbon dioxide level"],
        ["brick:CO2_Level_Sensor", "brick:CO2_Sensor"],
        "threshold",
        "",
        "high",
    ),
    (
        "ventilation_quality",
        ["ventilation", "air flow", "air circulation", "fresh air", "air exchange"],
        ["brick:CO2_Level_Sensor", "brick:Damper_Position_Sensor", "brick:Supply_Air_Flow_Sensor"],
        "threshold",
        "iaq_composite",
        "high",
    ),
    # ── Humidity ─────────────────────────────────────────────────────────────
    (
        "too_humid",
        [
            "too humid",
            "humid",
            "muggy air",
            "moist air",
            "damp feeling",
            "clammy",
            "sticky air",
            "high humidity",
        ],
        ["brick:Humidity_Sensor", "brick:Relative_Humidity_Sensor"],
        "threshold",
        "thermal_comfort",
        "high",
    ),
    (
        "too_dry",
        ["dry air", "low humidity", "dry", "dryness"],
        ["brick:Humidity_Sensor", "brick:Relative_Humidity_Sensor"],
        "threshold",
        "thermal_comfort",
        "high",
    ),
    (
        "humidity_reading",
        ["humidity", "relative humidity", "moisture level", "how humid", "moisture"],
        ["brick:Humidity_Sensor", "brick:Relative_Humidity_Sensor"],
        "aggregate",
        "",
        "high",
    ),
    # ── IAQ composite ─────────────────────────────────────────────────────────
    (
        "iaq_composite",
        [
            "indoor air quality",
            "IAQ",
            "air quality",
            "air quality index",
            "how clean is the air",
            "pollutant levels",
        ],
        [
            "brick:CO2_Level_Sensor",
            "brick:PM2.5_Level_Sensor",
            "brick:TVOC_Sensor",
            "brick:Air_Quality_Sensor",
        ],
        "aggregate",
        "",
        "high",
    ),
    (
        "pm25_level",
        ["particulate matter", "PM2.5", "dust", "fine particles", "aerosols"],
        ["brick:PM2.5_Level_Sensor"],
        "threshold",
        "iaq_composite",
        "medium",
    ),
    (
        "tvoc_level",
        [
            "VOC",
            "volatile organic compound",
            "chemical smell",
            "TVOC",
            "organic pollutants",
            "chemical fumes",
        ],
        ["brick:TVOC_Sensor"],
        "threshold",
        "iaq_composite",
        "medium",
    ),
    (
        "smell_odour",
        ["smell", "odour", "bad smell", "stinks", "musty", "chemical odour", "foul smell", "odor"],
        ["brick:TVOC_Sensor", "brick:CO2_Sensor"],
        "threshold",
        "iaq_composite",
        "medium",
    ),
    # ── Noise ─────────────────────────────────────────────────────────────────
    (
        "noisy",
        [
            "noisy",
            "loud",
            "too loud",
            "noise",
            "disruptive noise",
            "disturbing sounds",
            "high noise level",
        ],
        ["brick:Noise_Level_Sensor", "brick:Sound_Level_Sensor"],
        "threshold",
        "acoustic_comfort",
        "high",
    ),
    (
        "quiet_zone",
        [
            "quiet",
            "silent",
            "quiet area",
            "quiet floor",
            "low noise",
            "peaceful",
            "quiet for study",
            "acoustic comfort",
        ],
        ["brick:Noise_Level_Sensor", "brick:Sound_Level_Sensor"],
        "threshold",
        "acoustic_comfort",
        "high",
    ),
    (
        "acoustic_comfort",
        [
            "acoustic comfort",
            "sound environment",
            "noise environment",
            "comfortable for focus",
            "noise level",
        ],
        ["brick:Noise_Level_Sensor"],
        "range",
        "",
        "high",
    ),
    # ── Lighting ──────────────────────────────────────────────────────────────
    (
        "too_bright",
        ["too bright", "glare", "harsh light", "blinding", "overly lit", "too much light"],
        ["brick:Illuminance_Sensor", "brick:Luminance_Sensor"],
        "threshold",
        "lighting_comfort",
        "high",
    ),
    (
        "too_dark",
        ["too dark", "dim", "not enough light", "poor lighting", "low light", "dark"],
        ["brick:Illuminance_Sensor", "brick:Luminance_Sensor"],
        "threshold",
        "lighting_comfort",
        "high",
    ),
    (
        "lighting_comfort",
        [
            "lighting",
            "light level",
            "illuminance",
            "brightness",
            "adequate lighting",
            "lighting conditions",
        ],
        ["brick:Illuminance_Sensor", "brick:Luminance_Sensor"],
        "range",
        "",
        "high",
    ),
    (
        "natural_light",
        ["natural light", "daylight", "sunlight", "daylit", "sunlit", "daylighting"],
        ["brick:Daylight_Sensor", "brick:Illuminance_Sensor"],
        "range",
        "lighting_comfort",
        "medium",
    ),
    # ── Occupancy / Busyness ──────────────────────────────────────────────────
    (
        "crowded",
        ["crowded", "packed", "full", "too many people", "congested", "over capacity", "no space"],
        ["brick:Occupancy_Sensor", "brick:Motion_Sensor"],
        "threshold",
        "busyness",
        "high",
    ),
    (
        "busy",
        ["busy", "busyness", "how busy", "how many people", "high occupancy"],
        ["brick:Occupancy_Sensor", "brick:Motion_Sensor", "brick:People_Counter_Sensor"],
        "aggregate",
        "busyness",
        "high",
    ),
    (
        "empty_space",
        [
            "empty",
            "available",
            "vacant",
            "free space",
            "nobody there",
            "unoccupied",
            "available desk",
        ],
        ["brick:Occupancy_Sensor", "brick:Motion_Sensor"],
        "threshold",
        "busyness",
        "high",
    ),
    (
        "busyness",
        [
            "occupancy",
            "how full is it",
            "space utilization",
            "room utilization",
            "occupancy rate",
            "how occupied",
        ],
        ["brick:Occupancy_Sensor", "brick:People_Counter_Sensor"],
        "aggregate",
        "",
        "high",
    ),
    (
        "quiet_time",
        ["when is it quiet", "best time to visit", "quietest time", "least busy time", "off-peak"],
        ["brick:Occupancy_Sensor", "brick:Motion_Sensor"],
        "trend",
        "busyness",
        "high",
    ),
    # ── Energy ────────────────────────────────────────────────────────────────
    (
        "energy_waste",
        [
            "wasting energy",
            "energy waste",
            "inefficient energy",
            "energy inefficiency",
            "high energy use",
        ],
        ["brick:Electrical_Energy_Sensor"],
        "threshold",
        "energy_consumption",
        "high",
    ),
    (
        "energy_consumption",
        [
            "energy use",
            "energy consumption",
            "electricity use",
            "power consumption",
            "kWh",
            "energy usage",
        ],
        ["brick:Electrical_Energy_Sensor", "brick:Electrical_Power_Sensor"],
        "aggregate",
        "",
        "high",
    ),
    (
        "energy_cost",
        [
            "energy cost",
            "electricity bill",
            "energy spend",
            "tariff",
            "cost of electricity",
            "electricity cost",
        ],
        ["brick:Electrical_Energy_Sensor"],
        "aggregate",
        "energy_consumption",
        "high",
    ),
    (
        "peak_demand",
        ["peak demand", "peak energy", "peak hours", "peak load", "demand charges"],
        ["brick:Electrical_Energy_Sensor", "brick:Electrical_Power_Sensor"],
        "threshold",
        "energy_consumption",
        "high",
    ),
    (
        "carbon_footprint",
        [
            "carbon",
            "emissions",
            "CO2 emissions",
            "carbon footprint",
            "greenhouse gas",
            "eco-friendly",
            "green",
        ],
        ["brick:Electrical_Energy_Sensor"],
        "aggregate",
        "energy_consumption",
        "medium",
    ),
    # ── Draft / Air movement ──────────────────────────────────────────────────
    (
        "draft",
        ["drafty", "draughty", "cold draft", "cold air blowing", "draught", "windy inside"],
        [
            "brick:Supply_Air_Temperature_Sensor",
            "brick:Supply_Air_Flow_Sensor",
            "brick:Zone_Air_Temperature_Sensor",
        ],
        "correlate",
        "thermal_comfort",
        "medium",
    ),
    # ── Safety ────────────────────────────────────────────────────────────────
    (
        "fire_safety",
        ["fire", "smoke", "fire alarm", "evacuation", "fire exit", "emergency", "fire hazard"],
        ["brick:Smoke_Detector", "brick:Fire_Alarm"],
        "threshold",
        "",
        "high",
    ),
    (
        "emergency_exit",
        ["emergency exit", "evacuation route", "fire exit", "safe exit", "exit"],
        ["brick:Smoke_Detector"],
        "threshold",
        "fire_safety",
        "medium",
    ),
    # ── Water ─────────────────────────────────────────────────────────────────
    (
        "water_usage",
        ["water use", "water consumption", "water usage", "water waste", "water efficiency"],
        ["brick:Water_Flow_Sensor", "brick:Water_Level_Sensor"],
        "aggregate",
        "",
        "medium",
    ),
    (
        "water_leak",
        ["water leak", "leak", "flooding", "dripping", "water running", "pipe leak"],
        ["brick:Water_Flow_Sensor", "brick:Leak_Detector"],
        "threshold",
        "water_usage",
        "medium",
    ),
    (
        "water_quality",
        ["water quality", "drinking water", "potable water", "water safety"],
        ["brick:Water_Quality_Sensor"],
        "threshold",
        "",
        "medium",
    ),
    # ── Overall comfort composite ─────────────────────────────────────────────
    (
        "overall_comfort",
        [
            "comfortable",
            "is it comfortable",
            "comfort level",
            "working conditions",
            "pleasant environment",
        ],
        [
            "brick:Temperature_Sensor",
            "brick:Humidity_Sensor",
            "brick:CO2_Level_Sensor",
            "brick:Illuminance_Sensor",
        ],
        "range",
        "",
        "high",
    ),
    # ── Equipment / Maintenance ───────────────────────────────────────────────
    (
        "equipment_working",
        ["working", "functioning", "operational", "is it broken", "not working", "equipment fault"],
        ["brick:Fault_Sensor"],
        "threshold",
        "",
        "medium",
    ),
    (
        "lift_status",
        ["lift", "elevator", "is the lift working", "lift broken", "elevator out of service"],
        ["brick:Fault_Sensor"],
        "threshold",
        "equipment_working",
        "high",
    ),
    (
        "hvac_performance",
        [
            "HVAC",
            "heating system",
            "cooling system",
            "air conditioning",
            "AC working",
            "heating working",
        ],
        ["brick:HVAC_Zone", "brick:AHU", "brick:Zone_Air_Temperature_Sensor"],
        "threshold",
        "equipment_working",
        "high",
    ),
    # ── Space utilization ─────────────────────────────────────────────────────
    (
        "space_availability",
        [
            "available room",
            "find a desk",
            "available space",
            "free room",
            "room available",
            "desk available",
        ],
        ["brick:Occupancy_Sensor"],
        "threshold",
        "busyness",
        "high",
    ),
    (
        "underutilized_space",
        ["under-utilized", "empty room", "unused space", "underused", "wasted space"],
        ["brick:Occupancy_Sensor"],
        "threshold",
        "busyness",
        "medium",
    ),
    # ── Outdoor environment ───────────────────────────────────────────────────
    (
        "outdoor_temperature",
        ["outside temperature", "outdoor temperature", "outside weather", "external temperature"],
        ["brick:Outside_Air_Temperature_Sensor"],
        "aggregate",
        "",
        "high",
    ),
    (
        "inside_vs_outside",
        ["warmer inside", "compare inside outside", "temperature difference", "inside vs outside"],
        ["brick:Temperature_Sensor", "brick:Outside_Air_Temperature_Sensor"],
        "correlate",
        "",
        "medium",
    ),
    # ── Productivity environment ───────────────────────────────────────────────
    (
        "focus_environment",
        [
            "suitable for study",
            "good for focus",
            "work environment",
            "study environment",
            "productive space",
        ],
        ["brick:Noise_Level_Sensor", "brick:Illuminance_Sensor", "brick:CO2_Level_Sensor"],
        "range",
        "overall_comfort",
        "medium",
    ),
    (
        "meeting_room_condition",
        [
            "meeting room ready",
            "conference room condition",
            "meeting room comfortable",
            "AV working",
        ],
        ["brick:Temperature_Sensor", "brick:CO2_Level_Sensor"],
        "range",
        "overall_comfort",
        "medium",
    ),
    # ── Anomalies ─────────────────────────────────────────────────────────────
    (
        "sensor_anomaly",
        ["unusual reading", "abnormal value", "sensor fault", "unexpected spike", "outlier"],
        ["brick:Temperature_Sensor", "brick:CO2_Level_Sensor"],
        "threshold",
        "",
        "medium",
    ),
    (
        "unexpected_open_window",
        ["window left open", "open window", "door left open"],
        ["brick:Window_Position_Sensor", "brick:Door_Position_Sensor"],
        "threshold",
        "",
        "medium",
    ),
    # ── Trends & forecasts ────────────────────────────────────────────────────
    (
        "temperature_trend",
        [
            "temperature trend",
            "getting warmer",
            "warming up",
            "cooling down",
            "temperature history",
        ],
        ["brick:Temperature_Sensor"],
        "trend",
        "temperature_reading",
        "high",
    ),
    (
        "energy_trend",
        [
            "energy trend",
            "energy over time",
            "energy increasing",
            "energy pattern",
            "energy history",
        ],
        ["brick:Electrical_Energy_Sensor"],
        "trend",
        "energy_consumption",
        "high",
    ),
    (
        "occupancy_trend",
        [
            "occupancy trend",
            "busier over time",
            "occupancy pattern",
            "occupancy history",
            "when peak occupancy",
        ],
        ["brick:Occupancy_Sensor"],
        "trend",
        "busyness",
        "high",
    ),
    # ── Compliance ────────────────────────────────────────────────────────────
    (
        "ashrae_compliance",
        ["ASHRAE", "ASHRAE 55", "thermal standard", "comfort standard", "ASHRAE compliance"],
        ["brick:Temperature_Sensor", "brick:Humidity_Sensor"],
        "range",
        "thermal_comfort",
        "medium",
    ),
    (
        "co2_compliance",
        [
            "WHO limit",
            "CO2 standard",
            "air quality standard",
            "CO2 regulation",
            "ventilation standard",
        ],
        ["brick:CO2_Level_Sensor"],
        "threshold",
        "co2_level",
        "medium",
    ),
    # ── Calendar / bookings ───────────────────────────────────────────────────
    (
        "room_booking",
        ["booked", "booking", "reserved", "is room booked", "room schedule", "room calendar"],
        [],
        "aggregate",
        "",
        "high",
    ),
    (
        "after_hours",
        ["after hours", "outside working hours", "overnight", "weekend", "outside business hours"],
        ["brick:Occupancy_Sensor", "brick:Electrical_Energy_Sensor"],
        "aggregate",
        "",
        "medium",
    ),
    # ── Recommendations ───────────────────────────────────────────────────────
    (
        "window_guidance",
        ["should windows be opened", "open windows", "natural ventilation recommendation"],
        ["brick:Outside_Air_Temperature_Sensor", "brick:CO2_Level_Sensor"],
        "correlate",
        "",
        "medium",
    ),
    (
        "setpoint_recommendation",
        ["setpoint", "target temperature", "recommended temperature", "adjust temperature"],
        ["brick:Temperature_Setpoint", "brick:Temperature_Sensor"],
        "range",
        "",
        "medium",
    ),
    (
        "energy_saving_tip",
        [
            "save energy",
            "reduce energy",
            "energy saving",
            "lower energy use",
            "efficiency improvement",
        ],
        ["brick:Electrical_Energy_Sensor"],
        "aggregate",
        "energy_consumption",
        "medium",
    ),
    # ── People flow / wayfinding ──────────────────────────────────────────────
    (
        "wayfinding",
        ["how do I get to", "directions to", "find room", "where is", "route to", "navigate to"],
        [],
        "aggregate",
        "",
        "high",
    ),
    (
        "congestion_hotspot",
        ["congestion", "bottleneck", "crowded corridor", "busy area", "flow problem"],
        ["brick:Occupancy_Sensor", "brick:Motion_Sensor"],
        "aggregate",
        "busyness",
        "medium",
    ),
    # ── Sustainability ────────────────────────────────────────────────────────
    (
        "solar_output",
        ["solar", "solar panels", "solar energy", "PV output", "photovoltaic", "renewable energy"],
        ["brick:Electrical_Power_Sensor"],
        "aggregate",
        "energy_consumption",
        "medium",
    ),
    (
        "green_certification",
        ["BREEAM", "LEED", "green building", "sustainability rating", "energy certificate"],
        [],
        "aggregate",
        "",
        "low",
    ),
    # ── Forecast ──────────────────────────────────────────────────────────────
    (
        "future_temperature",
        [
            "will it warm up",
            "temperature forecast",
            "predict temperature",
            "expected temperature",
            "forecast temperature",
        ],
        ["brick:Temperature_Sensor"],
        "trend",
        "temperature_reading",
        "high",
    ),
    (
        "future_energy",
        ["energy forecast", "predict energy", "expected energy use", "future energy demand"],
        ["brick:Electrical_Energy_Sensor"],
        "trend",
        "energy_consumption",
        "medium",
    ),
    # ── Maintenance records ────────────────────────────────────────────────────
    (
        "last_service",
        [
            "last serviced",
            "maintenance history",
            "when was it serviced",
            "service record",
            "last maintenance",
        ],
        [],
        "aggregate",
        "",
        "medium",
    ),
    (
        "equipment_condition",
        ["equipment condition", "equipment health", "needs repair", "equipment status"],
        ["brick:Fault_Sensor"],
        "threshold",
        "equipment_working",
        "medium",
    ),
    # ── Governance / meta ─────────────────────────────────────────────────────
    (
        "data_privacy",
        ["what do you monitor", "data collected", "privacy", "who sees my data", "data about me"],
        [],
        "aggregate",
        "",
        "medium",
    ),
    (
        "system_capability",
        [
            "can you",
            "are you able to",
            "what can you do",
            "system capability",
            "what do you measure",
        ],
        [],
        "aggregate",
        "",
        "high",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Corpus miner
# ─────────────────────────────────────────────────────────────────────────────


def load_corpus(corpus_path: Path) -> List[str]:
    """Load non-GK question text from master table CSV."""
    questions: List[str] = []
    if not corpus_path.exists():
        print(f"[mine_vocab] WARNING: corpus not found at {corpus_path}", file=sys.stderr)
        return questions
    with open(corpus_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = (row.get("question") or "").strip()
            if not q:
                continue
            ab = (row.get("answer_basis") or "").strip().lower()
            if ab == "general-knowledge":
                continue
            questions.append(q)
    return questions


def find_example_questions(
    lay_terms: List[str], questions: List[str], max_examples: int = 3
) -> List[str]:
    """Return up to max_examples questions that contain any lay term."""
    patterns = [re.compile(re.escape(t.lower())) for t in lay_terms]
    found: List[str] = []
    for q in questions:
        q_lower = q.lower()
        if any(p.search(q_lower) for p in patterns):
            found.append(q)
            if len(found) >= max_examples:
                break
    return found


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def build_rows(questions: List[str]) -> List[Dict]:
    rows = []
    for (
        concept_id,
        lay_terms,
        brick_classes,
        recipe_kind,
        composite_of,
        confidence,
    ) in _CONCEPT_SEED:
        examples = find_example_questions(lay_terms, questions)
        rows.append(
            {
                "concept_id": concept_id,
                "lay_terms": "|".join(lay_terms),
                "brick_classes": "|".join(brick_classes),
                "recipe_kind": recipe_kind,
                "composite_of": composite_of,
                "example_questions": " || ".join(examples),
                "confidence": confidence,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine building concept vocabulary from corpus.")
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH, help="Path to master_table CSV")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Output CSV path")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing")
    args = parser.parse_args()

    questions = load_corpus(args.corpus)
    print(f"[mine_vocab] loaded {len(questions)} non-GK questions from corpus")

    rows = build_rows(questions)

    covered = sum(1 for r in rows if r["example_questions"])
    print(f"[mine_vocab] concepts: {len(rows)}, with examples: {covered}/{len(rows)}")

    # Stats
    top_level = [r for r in rows if not r["composite_of"]]
    print(
        f"[mine_vocab] top-level concepts: {len(top_level)}, component concepts: {len(rows) - len(top_level)}"
    )

    recipe_kinds = {}
    for r in rows:
        recipe_kinds[r["recipe_kind"]] = recipe_kinds.get(r["recipe_kind"], 0) + 1
    print(f"[mine_vocab] recipe_kind distribution: {json.dumps(recipe_kinds)}")

    if args.dry_run:
        print("[mine_vocab] --dry-run: skipping file write")
        print(f"[mine_vocab] would write {len(rows)} rows to {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[mine_vocab] wrote {len(rows)} rows -> {args.output}")
    print("[mine_vocab] NEXT: review concept_terms_raw.csv before running T02 (csv_to_hbco.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
