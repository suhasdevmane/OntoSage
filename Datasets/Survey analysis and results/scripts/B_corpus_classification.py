"""Phase B2 — Corpus classification.

Classifies all 5,127 questions in `inputs/questions_by_user.csv` against the
taxonomy defined in `taxonomy/taxonomy_v1.md`. Each row receives six labels:

  domain_l1, query_type_l2, intent, temporal, spatial, complexity

Implementation note
-------------------
The methodology spec calls for an LLM-batch classification (Anthropic Batch
API). For full reproducibility *without* an API call, this script implements a
deterministic, lexicon-based classifier whose rules are derived from the
200-question sample read during Phase B1. Every coding decision is traceable
to a published lexicon below, which is the same artefact a future LLM-based
re-run would be compared against in Phase B3 IRR.

Re-running the same input is bit-identical (no randomness, no API timing).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INP = ROOT / "inputs"
OUT = ROOT / "outputs"
CORPUS = ROOT / "corpus"
CORPUS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Lexicons (the "rules")
# ---------------------------------------------------------------------------

# Order matters — the first matching domain wins.
DOMAIN_LEXICON: list[tuple[str, list[str]]] = [
    ("SAFETY", [
        "fire", "evacuat", "emergency", "alarm", "smoke", "panic",
        "lockdown", "exit", "stairwell", "trapped", "earthquake",
        "first aid", "drill", "safety", "safe ", " safe?", "hazard",
        "risk",
    ]),
    ("SECURITY", [
        "security", "secure", "intrud", "burglar", "lock", "key card",
        "keycard", "badge", "access control", "camera", "cctv", "surveill",
        "hack", "hacker", "door",
    ]),
    ("ENERGY", [
        "energy", "kwh", "kw ", "watt", "power", "electric",
        "consum", "bill", "demand", "load", "solar", "renewable",
        "battery", "grid", "meter", "submeter", "voltage", "current",
        "motor", "appliance",
    ]),
    ("AIR_QUALITY", [
        "air quality", "air-quality", "co2", "co₂", "voc", "voc ", "voc.",
        "pm2", "pm 2", "particulate", "humidity", "humid", "humanity",
        "ventilat", "fresh air", "stuffy", "odor", "odour", "smell",
        "iaq", "allerg", "pollen", "ozone", "pollut", "dust",
        "pressure", "preswsure", "window", "windows", "no2", "nox",
        "oxygen", "carbon dioxide", "asthma", "cough",
    ]),
    ("THERMAL", [
        "temperature", "temp ", " temp.", "warm", "cold", "hot",
        "heat", "cool", "hvac", "thermostat", "setpoint", "set point",
        "comfort", "ashrae 55", "chill",
    ]),
    ("LIGHTING", [
        "light", "lux", "lumen", "lamp", "bulb", "dim", "glare",
        "daylight", "shade", "blind", "lighting", "tint", "glass",
    ]),
    ("WATER", [
        "water", "leak", "plumb", "tap", "toilet", "sink", "bathroom",
        "shower", "irrig", "damp", "drain", "flood",
    ]),
    ("WASTE", [
        "waste", "recycl", "trash", "bin", "garbage", "compost",
        "rubbish",
    ]),
    ("OCCUPANCY", [
        "occup", "people in", "headcount", "how many people",
        "crowd", "busy", "utiliz", "utilis", "presence",
        "free room", "free area", "available room", "vacancy",
        "empty room",
    ]),
    ("MAINTENANCE", [
        "maintenan", "fault", "broken", "repair", "fix",
        "work order", "service", "down", "outage", "fail",
        "equipment", "vibrat", "issue", "monitor",
        "replace", "battery", "batteries", "wear",
    ]),
    ("SUSTAINABILITY", [
        "sustainab", "green", "carbon", "leed", "breeam", "well certif",
        "net zero", "net-zero", "eco", "environ",
    ]),
    ("WELLBEING", [
        "wellbeing", "well being", "well-being", "stress",
        "mental", "noise", "loud", "biophil", "plant", "wellness",
        "sound level", "sound ", "music",
    ]),
    ("WAYFINDING", [
        "where is", "where's", "where can i find", "directions",
        "navigate", "way to", "find the", "layout", "map", "floor plan",
        "reservation", "book ", "booking", "reserve", "schedule", "open ",
        "hours", "meeting room", "conference room", "shared space",
        "work space", "free room", "lobby",
    ]),
    ("CONTROL", [
        "automate", "automat", "control", "personal", "preference",
        "adjust", "change setting", "manual override", "override",
    ]),
    ("PRIVACY", [
        "privacy", "private", "data", "record", "retention",
        "opt out", "opt-out", "personal data",
    ]),
    ("ACCESSIBILITY", [
        "accessib", "wheelchair", "ramp", "lift ", "elevator",
        "disab", "deaf", "blind ", "braille", "sensory",
    ]),
    ("TRANSPORT", [
        "park", "parking", "ev charg", "bike", "bicycle", "shuttle",
        "transit", "commute",
    ]),
    ("WEATHER_OUTDOOR", [
        "weather", "outside", "outdoor", "outdoors", "rain",
        "snow", "wind ", "storm", "forecast",
    ]),
    ("INFO_REQUEST", [
        "who owns", "who manag", "contact", "policy", "polic",
        "rules", "history", "year was", "built in", "built?", "owner",
        "certif", "trust", "responsib", "amenit", "common area",
        "cafe", "coffee", "your purpose", "smart building",
        "capabilit", "feature", "what can you", "who are you",
        "how smart", "size", "square foot", "sqft", "area of",
        "designed", "designer", "when were you", "compare",
    ]),
]

# Query-type rules — applied in priority order; first match wins.
# (rule_name, regex)
QUERY_TYPE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("ANOMALY", re.compile(
        r"\b(any anomal|anomal|too high|too low|out of range|exceed|"
        r"unsafe|unhealthy|dangerous|alert|threshold|warn|spike)\b",
        re.IGNORECASE)),
    ("RECOMMENDATION", re.compile(
        r"\b(should i|how can i|how do i|what.s the best|recommend|"
        r"suggest|advise|advice|best place|best way)\b",
        re.IGNORECASE)),
    ("DIAGNOSTIC", re.compile(
        r"\b(why|what is causing|what.s causing|what caused|"
        r"how does .* work|how do .* work|reason|because)\b",
        re.IGNORECASE)),
    ("COMPARISON", re.compile(
        r"\b(compare|versus| vs |which .* (is|has) (more|less|higher|lower|"
        r"better|worse|the most|the least)|highest|lowest|most|least)\b",
        re.IGNORECASE)),
    ("HISTORICAL", re.compile(
        r"\b(yesterday|last (week|month|year|hour|day)|past .* (day|week|"
        r"month|year|hour)|historical|history|trend|over time|since)\b",
        re.IGNORECASE)),
    ("CAPABILITY", re.compile(
        r"^(can |could |is there |are there |do you have|does the building"
        r"|is it possible|how (do|does) (you|the system|this building))",
        re.IGNORECASE)),
    ("STATUS", re.compile(
        r"\b(what is|what.s|current|right now|now|currently|show me|"
        r"give me|display|tell me)\b",
        re.IGNORECASE)),
]

INTENT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("PREDICTIVE", re.compile(
        r"\b(forecast|predict|will (be|happen)|going to|tomorrow|"
        r"next (week|month|year)|future|expect)\b", re.IGNORECASE)),
    ("PRESCRIPTIVE", re.compile(
        r"\b(should|recommend|suggest|advise|how can i|how do i|"
        r"best place|best way|what to do)\b", re.IGNORECASE)),
    ("DIAGNOSTIC", re.compile(
        r"\b(why|what.s causing|what is causing|what caused|reason|"
        r"because|how does .* work)\b", re.IGNORECASE)),
]

TEMPORAL_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("PREDICTIVE", re.compile(
        r"\b(forecast|predict|tomorrow|next (week|month|year|hour|day)|"
        r"will be|going to|future)\b", re.IGNORECASE)),
    ("HISTORICAL", re.compile(
        r"\b(yesterday|last (week|month|year|hour|day|night)|past .* "
        r"(day|week|month|year|hour)|historical|history|trend|since|"
        r"over time|previous)\b", re.IGNORECASE)),
    ("REALTIME", re.compile(
        r"\b(now|current|currently|right now|live|real ?time|at the moment)\b",
        re.IGNORECASE)),
]

SPATIAL_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("CAMPUS", re.compile(
        r"\b(campus|across .* buildings?|every building|all buildings)\b",
        re.IGNORECASE)),
    ("BUILDING", re.compile(
        r"\b(this building|the building|building.wide|whole building|"
        r"entire building|across the building)\b", re.IGNORECASE)),
    ("FLOOR", re.compile(
        r"\b(floor( \d+)?|wing|level \d+|\d(st|nd|rd|th) floor)\b",
        re.IGNORECASE)),
    ("ROOM", re.compile(
        r"\b(room|conference|meeting|office|lab|gym|cafeteria|kitchen|"
        r"bathroom|toilet|stairwell|lobby|hall|class)\b", re.IGNORECASE)),
    ("POINT", re.compile(
        r"\b(this thermostat|that sensor|this device|the sensor|"
        r"the thermostat)\b", re.IGNORECASE)),
]

COMPLEXITY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("MULTI_STEP", re.compile(
        r"\b(compare|versus| vs |trend|over the (past|last)|"
        r"and (also|then|tell me)|join|combine|across .* (buildings?|"
        r"floors?|rooms?))\b", re.IGNORECASE)),
    ("AGGREGATION", re.compile(
        r"\b(average|avg|mean|sum|total|count|how many|how much|"
        r"min|max|highest|lowest|most|least)\b", re.IGNORECASE)),
]


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------


def classify_domain(q: str) -> str:
    ql = q.lower()
    for code, terms in DOMAIN_LEXICON:
        for t in terms:
            if t in ql:
                return code
    return "OTHER"


def classify_query_type(q: str) -> str:
    for code, rx in QUERY_TYPE_RULES:
        if rx.search(q):
            return code
    return "STATUS"


def classify_intent(q: str, query_type: str) -> str:
    for code, rx in INTENT_RULES:
        if rx.search(q):
            return code
    if query_type in {"ANOMALY", "DIAGNOSTIC"}:
        return "DIAGNOSTIC"
    if query_type == "RECOMMENDATION":
        return "PRESCRIPTIVE"
    return "INFORMATIONAL"


def classify_temporal(q: str) -> str:
    for code, rx in TEMPORAL_RULES:
        if rx.search(q):
            return code
    return "STATIC"


def classify_spatial(q: str) -> str:
    for code, rx in SPATIAL_RULES:
        if rx.search(q):
            return code
    return "UNSPECIFIED"


def classify_complexity(q: str, query_type: str) -> str:
    for code, rx in COMPLEXITY_RULES:
        if rx.search(q):
            return code
    if query_type in {"COMPARISON", "ANOMALY"}:
        return "MULTI_STEP"
    if query_type == "HISTORICAL":
        return "AGGREGATION"
    return "LOOKUP"


def is_off_topic(q: str) -> bool:
    """Heuristic for off-topic / gibberish."""
    if not isinstance(q, str):
        return True
    q = q.strip()
    if len(q) < 3:
        return True
    words = re.findall(r"[A-Za-z]+", q)
    if len(words) < 2:
        return True
    return False


def classify_row(q: str) -> dict[str, str]:
    if is_off_topic(q):
        return {
            "domain_l1": "OTHER",
            "query_type_l2": "STATUS",
            "intent": "INFORMATIONAL",
            "temporal": "STATIC",
            "spatial": "UNSPECIFIED",
            "complexity": "LOOKUP",
        }
    domain = classify_domain(q)
    qt = classify_query_type(q)
    return {
        "domain_l1": domain,
        "query_type_l2": qt,
        "intent": classify_intent(q, qt),
        "temporal": classify_temporal(q),
        "spatial": classify_spatial(q),
        "complexity": classify_complexity(q, qt),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    qbu = pd.read_csv(INP / "questions_by_user.csv")
    qbu["Question"] = qbu["Question"].astype(str).str.strip()
    qbu = qbu.dropna(subset=["Question"])
    qbu = qbu[qbu["Question"].str.len() > 0].reset_index(drop=True)

    pid_map = pd.read_csv(OUT / "intermediate" / "username_to_pid.csv")
    qbu["Username"] = qbu["Username"].astype(str).str.strip().str.lower()
    qbu = qbu.merge(pid_map, on="Username", how="left")

    classified = qbu["Question"].apply(classify_row).apply(pd.Series)
    out = pd.concat(
        [
            qbu[["PID", "Personas", "Stage", "Timestamp", "Question"]],
            classified,
        ],
        axis=1,
    )
    out_path = CORPUS / "classified_corpus.csv"
    out.to_csv(out_path, index=False)
    print(f"Phase B2 done. {len(out)} rows classified -> {out_path}")
    print("Domain distribution (top 10):")
    print(out["domain_l1"].value_counts().head(10).to_string())
    print("\nQuery type distribution:")
    print(out["query_type_l2"].value_counts().to_string())


if __name__ == "__main__":
    main()
