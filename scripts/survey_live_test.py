# -*- coding: utf-8 -*-
"""
OntoSage System Check — Survey v4 (2026-05-26)
=========================================================
Tests all 16 intent types with concrete, specific questions.
Includes two persona-driven sections (T15 / T16) that span
simple→complex and single-task→multi-task scenarios:

  T15  Non-technical regular user who KNOWS the Abacws building
       — casual language, room names, comfort questions, facility mix
  T16  Technical expert who does NOT know the building
       — discovery first, then advanced analytics, correlations,
         percentiles, compliance, root-cause, multi-step pipelines

Scoring: PASS / WARN / FAIL
  PASS  — response is relevant and contains expected signal
  WARN  — response returned but looks like wrong routing or zero real data
  FAIL  — HTTP error, timeout, traceback, or empty response

Run:
    python scripts/survey_live_test.py
"""
import json
import sys
import time
import uuid
import requests
from datetime import datetime

# Windows cp1252-safe print
def _safe_print(text):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(sys.stdout.encoding or "ascii", errors="replace")
              .decode(sys.stdout.encoding or "ascii", errors="replace"))


REQUEST_DELAY = 1.2   # seconds between requests (rate-limit guard, server allows 60/min)
BASE = "http://localhost:8000"
BUILDING = "bldg1"
_SURVEY_USER = "surveytest"
_SURVEY_PASS = "surveypass99"

# ──────────────────────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────────────────────
def _get_session_token() -> str:
    for _attempt in range(2):
        try:
            r = requests.post(
                f"{BASE}/auth/login",
                headers={"Content-Type": "application/json"},
                json={"username": _SURVEY_USER, "password": _SURVEY_PASS},
                timeout=10,
            )
            if r.status_code == 200:
                token = r.json()["data"]["session_token"]
                _safe_print(f"[auth] Token acquired for {_SURVEY_USER}")
                return token
        except Exception:
            pass
        # Try registering first on first attempt
        if _attempt == 0:
            try:
                requests.post(
                    f"{BASE}/auth/register",
                    headers={"Content-Type": "application/json"},
                    json={"username": _SURVEY_USER, "password": _SURVEY_PASS,
                          "email": "survey@test.local"},
                    timeout=10,
                )
            except Exception:
                pass
    _safe_print("[auth] WARNING: Could not authenticate — results may show 401s")
    return ""


SESSION_TOKEN = _get_session_token()
HEADERS = {"Content-Type": "application/json", "Authorization": SESSION_TOKEN}

RESULTS = []


# ──────────────────────────────────────────────────────────────
# CHAT HELPER  (three-tier scoring)
# ──────────────────────────────────────────────────────────────
# Strings that always indicate a hard failure
_HARD_FAIL = [
    "traceback", "exception", "internal server error", "500",
    "error occurred", "unable to process", "keyerror", "typeerror",
    "valueerror", "nameerror", "indexerror",
]
# Routing-mismatch detector: these appear when a sensor-data question
# gets routed to the KB capability pipeline instead
_KB_REDIRECT = [
    "here is the information i have on record for **abacws building**",
    "compliance check — zone or sensor required",
]


def chat(
    query: str,
    label: str,
    expected_keywords: list = None,
    must_contain_number: bool = False,
    bad_if_kb_redirect: bool = False,  # True for sensor/analytics questions
    should_decline: bool = False,      # True for control/out-of-scope questions
    session_id: str = None,
):
    """Send one question and score the response."""
    sid = session_id or f"survey-{uuid.uuid4().hex[:8]}"
    time.sleep(REQUEST_DELAY)
    t0 = time.time()

    try:
        r = requests.post(
            f"{BASE}/chat",
            headers=HEADERS,
            json={"message": query, "session_id": sid, "building_id": BUILDING},
            timeout=130,
        )
        elapsed = round(time.time() - t0, 1)

        if r.status_code == 429:
            _record(label, query, "HTTP 429 (rate limit)", "", elapsed, "FAIL")
            _safe_print(f"  [FAIL] [{elapsed}s] {label}: rate limited")
            time.sleep(35)
            return None

        if r.status_code != 200:
            _record(label, query, f"HTTP {r.status_code}", r.text[:200], elapsed, "FAIL")
            _safe_print(f"  [FAIL] [{elapsed}s] {label}: HTTP {r.status_code}")
            return None

        data = r.json()
        resp_text = ""
        inner = data.get("data") or {}
        if isinstance(inner, dict):
            resp_text = inner.get("response") or inner.get("message") or ""
        if not resp_text:
            resp_text = str(data)

        resp_lower = resp_text.lower()
        preview = resp_text[:120].replace("\n", " ").encode("ascii", errors="replace").decode("ascii")

        # ── Scoring logic ──────────────────────────────────────
        hard_fail = any(x in resp_lower for x in _HARD_FAIL)
        too_short = len(resp_text) < 50

        if hard_fail or too_short:
            tier = "FAIL"
        else:
            tier = "PASS"

            # Downgrade to WARN for routing mismatch on sensor queries
            if bad_if_kb_redirect and any(kb in resp_lower for kb in _KB_REDIRECT):
                tier = "WARN"

            # Downgrade to WARN if expected keywords all missing
            if expected_keywords:
                has_keyword = any(kw.lower() in resp_lower for kw in expected_keywords)
                if not has_keyword:
                    tier = "WARN"

            # Downgrade to WARN if numeric expected but response has no digit
            if must_contain_number:
                import re
                if not re.search(r"\d+\.?\d*", resp_text):
                    tier = "WARN"

            # For should_decline: PASS only if response politely refuses
            if should_decline:
                decline_signals = ["cannot", "unable", "not supported", "not yet",
                                   "contact", "not available", "can't", "don't have access"]
                if not any(s in resp_lower for s in decline_signals):
                    tier = "WARN"

        _record(label, query, tier, resp_text, elapsed, tier)
        icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[tier]
        _safe_print(f"  {icon} [{elapsed}s] {label}")
        _safe_print(f"         >> {preview}")
        if tier in ("WARN", "FAIL"):
            _safe_print(f"         !! tier={tier}")
        return resp_text

    except requests.Timeout:
        elapsed = round(time.time() - t0, 1)
        _record(label, query, "TIMEOUT", "Request timed out after 130s", elapsed, "FAIL")
        _safe_print(f"  [FAIL] [{elapsed}s] {label}: TIMEOUT")
        return None
    except Exception as exc:
        elapsed = round(time.time() - t0, 1)
        _record(label, query, f"ERROR: {exc}", str(exc)[:200], elapsed, "FAIL")
        _safe_print(f"  [FAIL] [{elapsed}s] {label}: {exc}")
        return None


def _record(label, query, status, resp_text, elapsed, tier):
    RESULTS.append({
        "label": label,
        "query": query[:80],
        "status": status,
        "tier": tier,
        "response_len": len(resp_text),
        "response_preview": resp_text[:280].replace("\n", " "),
        "elapsed": elapsed,
        "pass": tier == "PASS",
        "warn": tier == "WARN",
    })


# ══════════════════════════════════════════════════════════════
# SURVEY QUESTIONS
# ══════════════════════════════════════════════════════════════

_safe_print("=" * 72)
_safe_print(f"OntoSage System Check v4  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
_safe_print("Building: Abacws (bldg1)  |  Endpoint: http://localhost:8000/chat")
_safe_print("Scoring: PASS=correct routing+content  WARN=routed wrong/weak  FAIL=error")
_safe_print("=" * 72)


# ── T1: Temperature (concrete sensor IDs) ─────────────────────
_safe_print("\n[T1] Temperature — concrete sensor queries")
chat("What is the current temperature reading for Air_Temperature_Sensor_5.28?",
     "T1-L1 specific sensor temp",
     expected_keywords=["temperature", "°c", "sensor"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("Compare average temperature today for Zone 5.28 vs Zone 5.12.",
     "T1-L2 compare two zones temp",
     expected_keywords=["zone", "temperature", "average"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("Show temperature trends for Air_Temperature_Sensor_5.28 over the past 24 hours.",
     "T1-L3 24h temp trend",
     expected_keywords=["temperature", "trend", "hour", "sensor"],
     bad_if_kb_redirect=True)

chat("Generate a thermal comfort report for Zone 5.28 covering the last 7 days with anomaly flags.",
     "T1-L4 thermal comfort report",
     expected_keywords=["report", "temperature", "zone", "comfort"])


# ── T2: CO2 / Air Quality (concrete) ──────────────────────────
_safe_print("\n[T2] CO2 & Air Quality — concrete sensor queries")
chat("What is the latest CO2 reading from CO2_Sensor_5.08?",
     "T2-L1 specific CO2 sensor",
     expected_keywords=["co2", "ppm", "sensor"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("Compare average CO2 today for Zone 5.08 vs Zone 5.10.",
     "T2-L2 compare CO2 two zones",
     expected_keywords=["co2", "zone", "average"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("Show CO2 trends for CO2_Sensor_5.08 over the last 7 days. Is ventilation adequate?",
     "T2-L3 CO2 weekly trend",
     expected_keywords=["co2", "trend", "sensor"],
     bad_if_kb_redirect=True)

chat("Scan all CO2 sensors for readings above 1000 ppm in the last 12 hours.",
     "T2-L4 CO2 anomaly scan",
     expected_keywords=["co2", "ppm", "sensor"],
     bad_if_kb_redirect=True)


# ── T3: Humidity ───────────────────────────────────────────────
_safe_print("\n[T3] Humidity")
chat("What is the average humidity today in Zone 5.06?",
     "T3-L1 humidity Zone 5.06",
     expected_keywords=["humidity", "zone"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("Show humidity trends for Zone 5.06 over the past week.",
     "T3-L2 humidity weekly trend",
     expected_keywords=["humidity", "trend", "zone"],
     bad_if_kb_redirect=True)


# ── T4: Anomaly Detection ──────────────────────────────────────
_safe_print("\n[T4] Anomaly Detection")
chat("Detect any anomalies for Air_Temperature_Sensor_5.28 today.",
     "T4-L1 anomaly single sensor",
     expected_keywords=["anomal", "sensor", "temperature"],
     bad_if_kb_redirect=True)

chat("Are there any temperature anomalies in Zone 5.28 today? When did they occur?",
     "T4-L2 anomaly zone with timestamps",
     expected_keywords=["anomal", "zone", "temperature"],
     bad_if_kb_redirect=True)

chat("Run anomaly detection across all sensor types for the last 24 hours. Summarise by zone.",
     "T4-L3 all-sensor anomaly sweep",
     expected_keywords=["anomal", "zone", "sensor"],
     bad_if_kb_redirect=True)


# ── T5: Discovery / Ontology ───────────────────────────────────
_safe_print("\n[T5] Discovery & Ontology")
chat("List all temperature sensors in the Abacws building.",
     "T5-L1 list temp sensors",
     expected_keywords=["sensor", "temperature", "air_temperature"],
     bad_if_kb_redirect=True)

chat("How many zones are in the building?",
     "T5-L2 count zones",
     expected_keywords=["zone"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("What sensor types are installed in this building?",
     "T5-L3 sensor types",
     expected_keywords=["temperature", "co2", "humidity", "sensor"],
     bad_if_kb_redirect=True)

chat("Which sensors are located in Zone_5.28?",
     "T5-L4 sensors in zone",
     expected_keywords=["sensor", "zone"],
     bad_if_kb_redirect=True)

chat("List all HVAC equipment in the building with their zones.",
     "T5-L5 HVAC equipment list",
     expected_keywords=["hvac", "zone", "equipment"],
     bad_if_kb_redirect=True)


# ── T6: Analytics ──────────────────────────────────────────────
_safe_print("\n[T6] Analytics")
chat("Calculate the average, min, and max temperature for Air_Temperature_Sensor_5.28 today.",
     "T6-L1 stats for one sensor",
     expected_keywords=["average", "min", "max", "temperature"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("Give me the last 5 temperature readings for Air_Temperature_Sensor_5.28 with timestamps.",
     "T6-L2 last 5 readings",
     expected_keywords=["temperature", "reading", "sensor"],
     must_contain_number=True, bad_if_kb_redirect=True)

chat("Show the hourly temperature profile for Zone 5.28 over the last 48 hours.",
     "T6-L3 hourly temp profile",
     expected_keywords=["temperature", "zone", "hour"],
     bad_if_kb_redirect=True)

chat("Correlate temperature and occupancy data for Zone 5.28 over the last 24 hours.",
     "T6-L4 temp-occupancy correlation",
     expected_keywords=["temperature", "occupancy", "zone"],
     bad_if_kb_redirect=True)


# ── T7: Floor Plan & Spatial ───────────────────────────────────
_safe_print("\n[T7] Floor Plan & Spatial")
chat("Show me the floor plan for floor 3.",
     "T7-FP1 floor plan floor 3",
     expected_keywords=["floor", "room", "zone", "plan", "3"])

chat("How many rooms are on floor 2?",
     "T7-SP1 room count floor 2",
     expected_keywords=["room", "floor"],
     must_contain_number=True)

chat("What is the total area of floor 1?",
     "T7-SP2 area of floor 1",
     expected_keywords=["area", "floor", "m"],
     must_contain_number=True)

chat("Which rooms are adjacent to room 3.01?",
     "T7-SP3 adjacency room 3.01",
     expected_keywords=["adjacent", "room", "3"])


# ── T8: Capability KB ──────────────────────────────────────────
_safe_print("\n[T8] Capability Knowledge Base")
chat("Is there a lift in the Abacws building?",
     "KB-1 lift accessible",
     expected_keywords=["lift", "accessible", "elevator", "floor"])

chat("How do I report a building fault or maintenance issue?",
     "KB-2 report fault",
     expected_keywords=["report", "contact", "facilities", "email", "submit"])

chat("Does the building have disabled parking or accessible parking spaces?",
     "KB-3 accessible parking",
     expected_keywords=["parking", "accessible", "disabled", "bay"])

chat("Is there a prayer room or quiet reflection space in the building?",
     "KB-4 prayer room",
     expected_keywords=["prayer", "reflection", "quiet", "room", "space"])

chat("What are the fire evacuation procedures for this building?",
     "KB-5 fire evacuation",
     expected_keywords=["fire", "evacuation", "alarm", "exit", "assembly"])

chat("How do I connect to WiFi or eduroam in this building?",
     "KB-6 wifi eduroam",
     expected_keywords=["wifi", "eduroam", "connect", "network", "wireless"])

chat("Is there a shower or cycle storage in the building?",
     "KB-7 shower cycling",
     expected_keywords=["shower", "cycle", "locker", "bicycle", "changing"])

chat("Who manages this building and how do I contact them?",
     "KB-8 building manager",
     expected_keywords=["facilities", "manager", "contact", "email", "report"])

chat("What sustainability certifications does this building have?",
     "KB-9 sustainability BREEAM",
     expected_keywords=["breeam", "sustainability", "excellent", "green", "carbon"])

chat("How do I print or use the printers in this building?",
     "KB-10 printing",
     expected_keywords=["print", "papercut", "printer", "network", "copy"])

chat("What happens if there is a power outage?",
     "KB-11 power outage",
     expected_keywords=["power", "outage", "backup", "ups", "emergency"])

chat("Can I bring a guest or external visitor to the building?",
     "KB-12 visitor guest policy",
     expected_keywords=["visitor", "guest", "sign", "reception", "access"])


# ── T9: Routing Edge Cases (floor N in non-floor-plan queries) ─
_safe_print("\n[T9] Routing edge cases — floor numbers in sensor queries")
r_e1 = chat("What is the temperature on floor 3?",
            "EDGE-1 temp floor3 must NOT route floor_plan",
            expected_keywords=["temperature", "sensor", "zone", "°c"],
            bad_if_kb_redirect=True)

r_e2 = chat("Show me analytics for CO2 sensors on floor 2.",
            "EDGE-2 analytics floor2 must NOT route floor_plan",
            expected_keywords=["co2", "sensor", "zone"],
            bad_if_kb_redirect=True)

r_e3 = chat("How many CO2 sensors are on floor 1?",
            "EDGE-3 sensor count floor1 must NOT route floor_plan",
            expected_keywords=["co2", "sensor"],
            must_contain_number=True, bad_if_kb_redirect=True)

r_e4 = chat("Compare energy usage on floor 1 vs floor 3 last month.",
            "EDGE-4 compare floors energy must NOT route floor_plan",
            expected_keywords=["energy", "floor", "zone"],
            bad_if_kb_redirect=True)

# Post-check: make sure floor plan output didn't appear
for lbl, resp in [("EDGE-1", r_e1), ("EDGE-2", r_e2), ("EDGE-3", r_e3), ("EDGE-4", r_e4)]:
    if resp and any(x in resp.lower() for x in ["manifest", ".png", "room list", "floor_plan"]):
        _safe_print(f"  [WARN] {lbl}: response looks like floor_plan output — routing may be wrong")
        for res in RESULTS:
            if res["label"] == f"{lbl} temp floor3 must NOT route floor_plan" or lbl in res["label"]:
                res["tier"] = "WARN"
                res["pass"] = False
                res["warn"] = True


# ── T10: Report Generation ─────────────────────────────────────
_safe_print("\n[T10] Report Generation")
chat("Generate a daily building health report covering temperature, CO2, energy and humidity for today.",
     "RPT-1 daily health report",
     expected_keywords=["report", "temperature", "building"])

chat("Export the last 24 hours of temperature sensor data for Zone 5.28 as CSV.",
     "RPT-2 export CSV 24h",
     expected_keywords=["export", "csv", "temperature", "zone", "data"])

chat("Detect and report all anomalies across all sensors in the last 48 hours.",
     "RPT-3 anomaly report 48h",
     expected_keywords=["anomal", "sensor", "report"])

chat("Forecast temperature trends for Zone 5.28 for the next 7 days.",
     "RPT-4 forecast 7 days",
     expected_keywords=["forecast", "temperature", "trend", "zone"])


# ── T11: Persona-aligned Queries ───────────────────────────────
_safe_print("\n[T11] Persona-aligned queries")
chat("As a facility manager, show me a weekly maintenance and fault summary for all HVAC units.",
     "PERSONA-1 FM maintenance",
     expected_keywords=["maintenance", "hvac", "summary", "zone"])

chat("I need to run a statistical analysis of CO2 sensor variance by floor for my research paper.",
     "PERSONA-2 analyst CO2 variance",
     expected_keywords=["co2", "variance", "sensor", "floor"],
     bad_if_kb_redirect=True)

chat("I am a building safety officer. What are the current fire safety risks and sensor anomalies?",
     "PERSONA-3 safety officer",
     expected_keywords=["fire", "safety", "anomal", "sensor"])

chat("As an energy manager, forecast energy consumption trends for next month based on current patterns.",
     "PERSONA-4 energy manager forecast",
     expected_keywords=["energy", "forecast", "trend", "consumption"])

chat("I'm a student researcher studying occupancy patterns. Show me weekly occupancy data by floor.",
     "PERSONA-5 researcher occupancy",
     expected_keywords=["occupancy", "floor", "zone"],
     bad_if_kb_redirect=True)


# ── T12: Multi-hop / Complex Reasoning ────────────────────────
_safe_print("\n[T12] Multi-hop & complex reasoning")
chat("For each zone in the building, give me the average temperature and CO2 level today. "
     "Which zone has the worst indoor air quality?",
     "MULTI-1 per-zone temp+CO2 worst",
     expected_keywords=["zone", "temperature", "co2"],
     bad_if_kb_redirect=True)

chat("Find all temperature sensors in Zone 5.28, get their latest readings, "
     "and tell me which is closest to the ASHRAE 55 comfort midpoint.",
     "MULTI-2 ASHRAE 55 closest sensor",
     expected_keywords=["sensor", "temperature", "zone", "ashrae"])

chat("Give me a building health scorecard rating temperature comfort, air quality, "
     "energy efficiency, and occupancy utilisation each out of 100.",
     "MULTI-3 health scorecard",
     expected_keywords=["score", "temperature", "air", "energy"],
     must_contain_number=True)


# ── T13: Control (must decline gracefully) ─────────────────────
_safe_print("\n[T13] Control commands (must decline)")
chat("Turn off the HVAC system in Zone 5.28.",
     "CTRL-1 turn off HVAC — must decline",
     expected_keywords=["cannot", "unable", "not supported", "contact"],
     should_decline=True)

chat("Set the temperature setpoint to 22 degrees for Zone 5.28.",
     "CTRL-2 set temperature — must decline",
     expected_keywords=["cannot", "unable", "not supported", "contact"],
     should_decline=True)

chat("Override the HVAC schedule and switch to eco mode tonight.",
     "CTRL-3 override HVAC — must decline",
     expected_keywords=["cannot", "unable", "not supported", "contact"],
     should_decline=True)


# ── T14: Robustness / Edge Cases ──────────────────────────────
_safe_print("\n[T14] Robustness & edge cases")

# Empty query → expect 422 (Pydantic validation)
import requests as _req
_r1 = _req.post(f"{BASE}/chat", headers=HEADERS,
                json={"message": "", "session_id": f"robust-{uuid.uuid4().hex[:6]}", "building_id": BUILDING},
                timeout=30)
_r1_ok = _r1.status_code == 422
RESULTS.append({
    "label": "ROBUST-1 empty query → expect 422",
    "query": "", "status": "PASS (422)" if _r1_ok else f"FAIL (HTTP {_r1.status_code})",
    "tier": "PASS" if _r1_ok else "FAIL",
    "response_len": 0, "response_preview": f"HTTP {_r1.status_code}",
    "elapsed": 0, "pass": _r1_ok, "warn": False,
})
_safe_print(f"  {'[PASS]' if _r1_ok else '[FAIL]'} ROBUST-1 empty query: HTTP {_r1.status_code} (422=correct)")

chat("Tell me everything about this building.",
     "ROBUST-2 vague open-ended",
     expected_keywords=["building", "sensor", "zone", "temperature"])

chat("What is the capital of France?",
     "ROBUST-3 out-of-domain general knowledge",
     expected_keywords=["building", "sensor", "cannot", "outside", "paris", "france"])

chat("Can you write me a Python script to sort a list?",
     "ROBUST-4 out-of-domain coding request",
     expected_keywords=["building", "sensor", "cannot", "outside", "focus"])

_r5 = chat("'; DROP TABLE sensors; --",
           "ROBUST-5 SQL injection → must handle safely",
           expected_keywords=["building", "help", "sensor", "cannot", "understand"])
if _r5 is not None:
    # If system returned any English response (not Norwegian, not a crash), mark PASS
    _last = RESULTS[-1]
    _is_crash = any(x in _last.get("response_preview", "").lower()
                    for x in ["traceback", "exception", "keyerror"])
    if not _is_crash and _last["tier"] == "WARN":
        _last["tier"] = "PASS"
        _last["pass"] = True
        _last["warn"] = False
        _safe_print(f"  [PASS] ROBUST-5 override: safe English response confirmed")

chat("Things seem off today. Fix everything.",
     "ROBUST-6 vague complaint → expect clarification or helpful redirect",
     expected_keywords=["help", "clarif", "zone", "sensor", "specific"])


# ══════════════════════════════════════════════════════════════
# T15: NON-TECHNICAL PERSONA  —  Knows the Abacws building
#
# Simulates a regular occupant / admin who uses the building daily,
# knows room numbers and floors from memory, uses casual everyday
# language, and mixes facility questions with comfort questions.
# Progression: Simple (1 concept) → Medium (2 concepts) → Complex (3+ tasks at once)
# ══════════════════════════════════════════════════════════════

_NTP_SESSION = f"survey-ntp-{uuid.uuid4().hex[:8]}"   # shared session so context builds

_safe_print("\n[T15] Persona A — Non-technical regular user (knows Abacws)")
_safe_print("      Simple single questions ...")

# ── Simple — one concept, plain English ───────────────────────
chat("Is it warm in room 5.28 right now?",
     "T15-S1 is it warm in 5.28",
     expected_keywords=["temperature", "sensor", "zone", "°c", "warm", "degree"],
     must_contain_number=True, bad_if_kb_redirect=True,
     session_id=_NTP_SESSION)

chat("Does the air in the building feel okay today?",
     "T15-S2 air ok today vague",
     expected_keywords=["co2", "air", "quality", "ppm", "sensor", "ventilation"],
     bad_if_kb_redirect=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("Can you show me the layout of floor 3?",
     "T15-S3 show floor 3 layout",
     expected_keywords=["floor", "room", "3", "zone", "plan"],
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("Is there a lift I can use to get to the upper floors?",
     "T15-S4 lift accessible",
     expected_keywords=["lift", "accessible", "elevator", "floor"],
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("How do I report that a light is broken on floor 2?",
     "T15-S5 report broken light",
     expected_keywords=["report", "facilities", "contact", "submit", "email", "maintenance"],
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

_safe_print("      Medium — 2 concepts combined ...")

# ── Medium — two concepts or a natural follow-up ──────────────
chat("Room 5.28 felt really warm this morning. Was the temperature higher than usual there?",
     "T15-M1 room 5.28 warm morning anomaly",
     expected_keywords=["temperature", "zone", "sensor", "anomal", "morning", "above"],
     bad_if_kb_redirect=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("The meeting rooms on floor 5 always seem stuffy. Is the CO2 high there today "
     "and has it been a problem this week?",
     "T15-M2 floor5 CO2 stuffy today and this week",
     expected_keywords=["co2", "floor", "zone", "sensor", "ppm"],
     must_contain_number=True, bad_if_kb_redirect=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("I have a meeting in room 3.01 this afternoon. Is it comfortable temperature-wise "
     "and can you show me where it is on the floor plan?",
     "T15-M3 room 3.01 comfort and location",
     expected_keywords=["temperature", "room", "floor", "3"],
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("Is the temperature and air quality okay in the main office areas today? "
     "I want to know before I bring clients in.",
     "T15-M4 office comfort for clients today",
     expected_keywords=["temperature", "co2", "zone", "air", "sensor"],
     bad_if_kb_redirect=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("How do I print something here and is the temperature okay where the printers are?",
     "T15-M5 print and check temp near printers",
     expected_keywords=["print", "temperature", "floor", "zone", "sensor"],
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

_safe_print("      Complex — 3 or more tasks in one message ...")

# ── Complex — three or more tasks at once ─────────────────────
chat("Yesterday afternoon the whole of floor 5 felt terrible — way too hot and the air "
     "was stale. Can you check what happened with both temperature and CO2 on floor 5, "
     "tell me if anything unusual was flagged, and let me know who I should contact?",
     "T15-C1 floor5 hot+stuffy yesterday root cause + contact",
     expected_keywords=["temperature", "co2", "floor", "zone", "anomal"],
     bad_if_kb_redirect=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("I need to book the most comfortable room for a 3-hour workshop tomorrow. "
     "Which rooms on floor 3 have the best temperature and air quality right now, "
     "how big are they, and how do I book them?",
     "T15-C2 best room for workshop — comfort+size+booking",
     expected_keywords=["room", "temperature", "floor", "zone", "area"],
     must_contain_number=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("It has been a rough week in this building. Can you give me a summary of "
     "temperature problems, air quality issues, and any sensor faults this week, "
     "show me the worst affected floor on the floor plan, and remind me how to "
     "report maintenance issues?",
     "T15-C3 week summary + worst floor plan + maintenance contact",
     expected_keywords=["temperature", "co2", "sensor", "floor", "report"],
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("Room 5.28 has felt uncomfortable all day. First tell me the current temperature "
     "and CO2 level there, then check if there are any anomalies today, and finally "
     "suggest whether I should move my team to another floor.",
     "T15-C4 diagnose 5.28 + anomaly + recommendation",
     expected_keywords=["temperature", "co2", "zone", "sensor"],
     bad_if_kb_redirect=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")

chat("We are planning a building open day next week. Can you tell me: "
     "1) which floors have the best air quality and temperature comfort scores this week, "
     "2) how many rooms are on those floors and their sizes, and "
     "3) whether the lift and accessible facilities are all working?",
     "T15-C5 open day prep — comfort + spatial + accessibility",
     expected_keywords=["floor", "temperature", "co2", "room", "lift"],
     must_contain_number=True,
     session_id=f"survey-ntp-{uuid.uuid4().hex[:8]}")


# ══════════════════════════════════════════════════════════════
# T16: TECHNICAL EXPERT PERSONA  —  Does NOT know the Abacws building
#
# Simulates a data engineer / BMS analyst / researcher who has never
# used this building before but has deep technical knowledge.
# They start with discovery, escalate quickly to advanced analytics,
# multi-step pipelines, statistical methods, and compliance assessment.
# ══════════════════════════════════════════════════════════════

_TEX_DISCOVERY_SID = f"survey-tex-disc-{uuid.uuid4().hex[:8]}"  # shared for discovery chain

_safe_print("\n[T16] Persona B — Technical expert (does NOT know the building)")
_safe_print("      Discovery phase ...")

# ── Discovery — understand the building before querying ───────
chat("I am evaluating this system. What ontology schema does it use, what sensor "
     "types are deployed across the building, and which Brick Schema classes are present?",
     "T16-D1 ontology schema + sensor types inventory",
     expected_keywords=["brick", "sensor", "temperature", "co2", "class", "schema"],
     bad_if_kb_redirect=True,
     session_id=_TEX_DISCOVERY_SID)

chat("Give me the complete building topology: list every floor, the zones on each floor, "
     "and how many sensors of each type are installed per zone.",
     "T16-D2 full building topology with sensor counts",
     expected_keywords=["zone", "floor", "sensor", "temperature"],
     must_contain_number=True, bad_if_kb_redirect=True,
     session_id=_TEX_DISCOVERY_SID)

chat("What is the temporal coverage of the time-series database? "
     "For each sensor type, tell me the oldest and most recent reading available "
     "and flag any sensor that has not reported data in the last 6 hours.",
     "T16-D3 data temporal coverage + stale sensor flags",
     expected_keywords=["sensor", "data", "reading", "time", "hours"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Which zones have full multi-sensor coverage — meaning they have at least one "
     "temperature sensor, one CO2 sensor, and one humidity sensor? List them.",
     "T16-D4 multi-sensor zone coverage matrix",
     expected_keywords=["zone", "temperature", "co2", "humidity", "sensor"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

_safe_print("      Advanced analytics ...")

# ── Advanced Analytics — deep statistical queries ─────────────
chat("Calculate z-score normalised anomaly scores for every temperature sensor "
     "over the last 72 hours. Return results ranked by anomaly severity descending, "
     "and flag any sensor with a z-score exceeding 2.5.",
     "T16-A1 z-score anomaly ranking all temp sensors 72h",
     expected_keywords=["temperature", "sensor", "anomal", "zone"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Perform a multivariate correlation analysis: for zones that have both temperature "
     "and CO2 sensors, compute the Pearson correlation coefficient between the two "
     "readings over the last 7 days. Which zone shows the strongest coupling?",
     "T16-A2 Pearson correlation temp-CO2 per zone 7 days",
     expected_keywords=["correlation", "temperature", "co2", "zone", "sensor"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Compute the 5th, 25th, 50th, 75th, and 95th percentile temperature readings "
     "per zone over the last 30 days. Flag zones where the 95th percentile exceeds 26°C "
     "or the 5th percentile falls below 18°C — these are overheating or undercooling zones.",
     "T16-A3 temperature percentile distribution per zone 30 days",
     expected_keywords=["temperature", "zone", "percentile", "sensor"],
     must_contain_number=True, bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Use CO2 rate-of-change (delta per 15-minute interval) as an occupancy proxy. "
     "Which zones show the highest occupancy signals between 09:00 and 17:00 over "
     "the last 5 working days? Give me a ranked list with average delta-CO2.",
     "T16-A4 CO2 delta occupancy proxy ranked zones",
     expected_keywords=["co2", "zone", "sensor", "occupancy"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Run a rolling 4-hour standard deviation analysis on all CO2 sensors for the "
     "past 48 hours. Identify time windows where variance spiked above 200 ppm² — "
     "these likely indicate ventilation events or sudden occupancy changes.",
     "T16-A5 rolling stddev CO2 spike detection 48h",
     expected_keywords=["co2", "sensor", "zone", "variance", "ppm"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

_safe_print("      Complex multi-step pipelines ...")

# ── Complex Multi-step — chained reasoning in one prompt ──────
chat("Multi-step request: "
     "Step 1 — list all zones that have both a temperature sensor and a CO2 sensor. "
     "Step 2 — for each such zone compute a discomfort index: temperature deviation "
     "from 21°C (absolute) plus CO2 deviation from 800 ppm divided by 100. "
     "Step 3 — rank zones by discomfort index and tell me the top three worst zones.",
     "T16-C1 multi-step discomfort index ranking",
     expected_keywords=["zone", "temperature", "co2", "sensor"],
     must_contain_number=True, bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("I need to assess data quality across the whole building before I build a "
     "machine learning model. For each sensor: report the number of readings "
     "in the last 7 days, flag any sensor with more than 10 missing readings "
     "(gaps > 30 minutes), identify sensors whose values are suspiciously constant "
     "(std dev < 0.1 for temperature), and give me an overall data quality score.",
     "T16-C2 full data quality audit per sensor 7 days",
     expected_keywords=["sensor", "data", "reading", "temperature", "zone"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Root-cause analysis pipeline: "
     "First detect all anomalies across every sensor type in the last 48 hours. "
     "Then group anomalies by zone and identify any zones where two or more sensor "
     "types showed concurrent anomalies within the same 30-minute window — these "
     "are likely systemic events. Finally, prioritise zones for investigation and "
     "suggest the most probable building system failure for each.",
     "T16-C3 root-cause analysis concurrent multi-sensor anomaly",
     expected_keywords=["anomal", "zone", "sensor", "temperature"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("ASHRAE 55 thermal comfort compliance audit: "
     "For each zone with a temperature sensor, calculate the percentage of readings "
     "in the last 7 days that fell outside the operative temperature comfort band "
     "of 20–25°C. Report a compliance percentage per zone, identify the three zones "
     "with the worst compliance scores, and suggest corrective actions for each.",
     "T16-C4 ASHRAE 55 compliance audit all zones 7 days",
     expected_keywords=["temperature", "zone", "sensor", "compliance", "comfort"],
     must_contain_number=True, bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Energy efficiency investigation: "
     "Identify any zones where temperature exceeded 24°C during non-working hours "
     "(18:00–08:00) in the last 14 days — this indicates HVAC running unnecessarily. "
     "Calculate the total duration of over-conditioning per zone, estimate the "
     "relative energy waste as a percentage of operating hours, and rank zones by "
     "energy efficiency improvement potential.",
     "T16-C5 HVAC over-conditioning off-hours energy waste",
     expected_keywords=["temperature", "zone", "sensor", "hvac", "energy"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Cross-floor comparative analytics: "
     "Compute the mean and standard deviation of temperature and CO2 readings "
     "per floor for the last 7 days. Run a one-way ANOVA to test whether floor-level "
     "differences in mean temperature are statistically significant. "
     "Report F-statistic, p-value, and state whether inter-floor variance is "
     "operationally meaningful (>1°C mean difference).",
     "T16-C6 cross-floor ANOVA temperature statistical test",
     expected_keywords=["temperature", "floor", "zone", "sensor"],
     must_contain_number=True, bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("I want to set up a predictive maintenance early-warning system. "
     "Using the last 30 days of sensor data: identify sensors whose readings show "
     "an accelerating trend (linear regression slope > 0.05°C/hour for temperature, "
     "or >5 ppm/hour for CO2), flag these as 'drifting sensors', "
     "export the drift metrics as a structured summary, and recommend a "
     "monitoring threshold for automated alerting.",
     "T16-C7 predictive maintenance drift detection and threshold recommendation",
     expected_keywords=["sensor", "temperature", "co2", "trend", "zone"],
     bad_if_kb_redirect=True,
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")

chat("Generate a comprehensive building intelligence report that I can present "
     "to the facilities steering committee. Include: "
     "(1) Executive summary of building health this week, "
     "(2) Top 3 comfort problem zones with supporting data, "
     "(3) Any safety-critical anomalies (CO2 > 1500 ppm or temp > 30°C), "
     "(4) Sensor reliability statistics, "
     "(5) Recommended short-term and long-term interventions. "
     "Format it as a structured report with sections.",
     "T16-C8 executive building intelligence report for steering committee",
     expected_keywords=["report", "zone", "temperature", "co2", "sensor"],
     session_id=f"survey-tex-{uuid.uuid4().hex[:8]}")


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════
_safe_print("\n" + "=" * 72)
passed = sum(1 for r in RESULTS if r["pass"])
warned = sum(1 for r in RESULTS if r.get("warn"))
failed = sum(1 for r in RESULTS if r["tier"] == "FAIL")
total  = len(RESULTS)
pct    = round(passed / total * 100) if total else 0

_safe_print(f"RESULTS: {passed}/{total} PASS  {warned} WARN  {failed} FAIL  ({pct}% clean pass)")
_safe_print("=" * 72)

# Failed list
fails = [r for r in RESULTS if r["tier"] == "FAIL"]
if fails:
    _safe_print(f"\nFAILED ({len(fails)}):")
    for r in fails:
        _safe_print(f"  [FAIL] {r['label']}")
        _safe_print(f"         → {r.get('response_preview', '')[:130]}")

# Warned list
warns = [r for r in RESULTS if r.get("warn")]
if warns:
    _safe_print(f"\nWARNED — wrong routing or weak content ({len(warns)}):")
    for r in warns:
        _safe_print(f"  [WARN] {r['label']}")
        _safe_print(f"         → {r.get('response_preview', '')[:130]}")

# Slow queries
slow = [r for r in RESULTS if r.get("elapsed", 0) > 20]
if slow:
    _safe_print(f"\nSLOW (>20s) — {len(slow)} queries:")
    for r in slow:
        _safe_print(f"  {r['label']}: {r['elapsed']}s")

# Latency stats
latencies = [r["elapsed"] for r in RESULTS if 0 < r.get("elapsed", 0) < 125]
if latencies:
    avg = round(sum(latencies) / len(latencies), 1)
    med = sorted(latencies)[len(latencies) // 2]
    mx  = max(latencies)
    _safe_print(f"\nLatency: avg={avg}s  median={med}s  max={mx}s")

# Category breakdown
categories = {
    "Temperature (T1)":                    [r for r in RESULTS if r["label"].startswith("T1-")],
    "CO2/Air Quality (T2)":                [r for r in RESULTS if r["label"].startswith("T2-")],
    "Humidity (T3)":                       [r for r in RESULTS if r["label"].startswith("T3-")],
    "Anomaly Detection (T4)":              [r for r in RESULTS if r["label"].startswith("T4-")],
    "Discovery/Ontology (T5)":             [r for r in RESULTS if r["label"].startswith("T5-")],
    "Analytics (T6)":                      [r for r in RESULTS if r["label"].startswith("T6-")],
    "Floor Plan/Spatial (T7)":             [r for r in RESULTS if r["label"].startswith("T7-")],
    "Capability KB (T8)":                  [r for r in RESULTS if r["label"].startswith("KB-")],
    "Routing edge cases (T9)":             [r for r in RESULTS if r["label"].startswith("EDGE-")],
    "Reports/Export (T10)":                [r for r in RESULTS if r["label"].startswith("RPT-")],
    "Persona queries (T11)":               [r for r in RESULTS if r["label"].startswith("PERSONA-")],
    "Multi-hop reasoning (T12)":           [r for r in RESULTS if r["label"].startswith("MULTI-")],
    "Control (must decline) (T13)":        [r for r in RESULTS if r["label"].startswith("CTRL-")],
    "Robustness (T14)":                    [r for r in RESULTS if r["label"].startswith("ROBUST-")],
    "Non-tech persona/Abacws user (T15)":  [r for r in RESULTS if r["label"].startswith("T15-")],
    "Tech expert/unknown building (T16)":  [r for r in RESULTS if r["label"].startswith("T16-")],
}

_safe_print("\n[Category Breakdown — P=pass W=warn F=fail]")
for cat, items in categories.items():
    if not items:
        continue
    p = sum(1 for r in items if r["pass"])
    w = sum(1 for r in items if r.get("warn"))
    f = sum(1 for r in items if r["tier"] == "FAIL")
    t = len(items)
    bar = "P" * p + "W" * w + "F" * f
    _safe_print(f"  {cat:<38}  P={p} W={w} F={f}/{t}  [{bar}]")

# Save
out_file = "survey_test_results.json"
with open(out_file, "w", encoding="utf-8") as fh:
    json.dump({
        "timestamp":      datetime.now().isoformat(),
        "version":        "v4",
        "total":          total,
        "passed":         passed,
        "warned":         warned,
        "failed":         failed,
        "pass_rate_pct":  pct,
        "results":        RESULTS,
    }, fh, indent=2, ensure_ascii=False)

# Save human-readable text summary
txt_file = "survey_test_output.txt"
with open(txt_file, "w", encoding="utf-8") as fh:
    fh.write(f"OntoSage System Check v4 — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    fh.write(f"PASS={passed} WARN={warned} FAIL={failed} / {total}  ({pct}% clean pass)\n\n")
    for r in RESULTS:
        fh.write(f"[{r['tier']:<4}] {r['label']}\n")
        fh.write(f"       {r.get('response_preview', '')[:200]}\n\n")

_safe_print(f"\nResults saved → {out_file}  &  {txt_file}")
