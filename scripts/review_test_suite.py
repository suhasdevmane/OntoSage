"""
OntoSage Comprehensive Review Test Suite
Runs live intent routing, capability KB, multi-intent, persona, edge case, and performance tests.
"""

import json
import sys
import time
import uuid
import requests

BASE = "http://localhost:8000"
TOKEN = "TKd0ilQPY4Dta6vqCIUKnWRPK55NHrRgjL6j9wTHK5o"
BUILDING = "bldg1"

HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"


def chat(message, session_id=None, building_id=None, personas=None, timeout=45):
    """Send a chat message and return parsed response."""
    if session_id is None:
        session_id = f"review-{uuid.uuid4().hex[:8]}"
    payload = {"message": message, "session_id": session_id, "building_id": building_id or BUILDING}
    if personas:
        payload["personas"] = personas
    try:
        t0 = time.time()
        r = requests.post(f"{BASE}/chat", headers=HEADERS, json=payload, timeout=timeout)
        elapsed = time.time() - t0
        d = r.json()
        data = d.get("data", {}) or {}
        return {
            "success": d.get("success", False),
            "intent": data.get("intent", "unknown"),
            "response": data.get("response", ""),
            "route": data.get("pipeline_route", data.get("route", "")),
            "elapsed": elapsed,
            "status_code": r.status_code,
            "raw": d,
        }
    except Exception as e:
        return {"success": False, "intent": "ERROR", "response": str(e), "route": "", "elapsed": 0, "status_code": 0}


def check_intent(result, expected_intents, label):
    """Check if result intent matches expected (list of acceptable intents)."""
    got = result.get("intent", "unknown").lower()
    ok = any(e.lower() in got or got in e.lower() for e in expected_intents)
    status = PASS if ok else FAIL
    resp_preview = result.get("response", "")[:100].replace("\n", " ")
    print(f"  {status} {label}")
    print(f"         intent={got}  expected={expected_intents}  [{result['elapsed']:.1f}s]")
    print(f"         response: {resp_preview}")
    return ok


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4: Intent Routing Matrix
# ─────────────────────────────────────────────────────────────────────────────
section("PHASE 4 — INTENT ROUTING MATRIX (16 intents + 4 hijack tests)")

ROUTING_TESTS = [
    # (query, [acceptable_intents], label)
    ("What is the current CO2 level in zone 3?",            ["sensor_data","analytics","sparql"],          "sensor_data"),
    ("Show average temperature trend for floor 2 last week",["analytics","sensor_data"],                   "analytics"),
    ("What sensor types are installed in this building?",   ["discovery","sparql","general"],              "discovery"),
    ("Generate an energy report for last month",            ["report","analytics"],                        "report"),
    ("Were there any temperature spikes in the last 24 hours?", ["anomaly","analytics","sensor_data"],    "anomaly"),
    ("Compare CO2 levels between floor 1 and floor 3",      ["comparison","analytics"],                    "comparison"),
    ("Export sensor data for zone 5 as CSV",                ["export"],                                    "export"),
    ("Predict temperature for tomorrow afternoon",          ["forecast","analytics"],                      "forecast"),
    ("Show me floor 3 layout",                              ["floor_plan"],                                "floor_plan"),
    ("How many rooms are on floor 2?",                      ["spatial_query","spatial"],                   "spatial_query"),
    ("What maintenance work is scheduled this week?",       ["maintenance","report","general"],            "maintenance"),
    ("Does this building have fire evacuation procedures?", ["capability","general_knowledge"],             "capability"),
    ("Hello, what can you help me with?",                   ["general","general_knowledge","clarification"],"general"),
    ("Turn off the lights in room 3.01",                    ["control","general","clarification"],         "control_unsupported"),
    ("It",                                                  ["clarification","general"],                   "clarification"),
    ("Alert me if CO2 exceeds 1000 ppm in any zone",        ["alert","anomaly","sensor_data"],             "alert"),
]

routing_pass = 0
routing_total = len(ROUTING_TESTS)

for query, expected, label in ROUTING_TESTS:
    result = chat(query)
    if check_intent(result, expected, label):
        routing_pass += 1

# Hijack prevention tests - floor keywords must NOT steal data queries
print("\n  --- Anti-hijack tests: floor mentions must NOT route to floor_plan ---")
HIJACK_TESTS = [
    ("What is the temperature on floor 3?",            ["sensor_data","analytics","sparql","general_knowledge"],  "temperature-on-floor → NOT floor_plan"),
    ("Show me analytics for floor 2 sensors",          ["analytics","sensor_data"],                               "analytics-for-floor → NOT floor_plan"),
    ("How many CO2 sensors are on floor 1?",           ["discovery","sparql","spatial_query","general_knowledge"],"CO2-count-on-floor → NOT floor_plan"),
    ("Compare energy usage on floor 1 vs floor 3",     ["comparison","analytics"],                                "energy-compare-floor → NOT floor_plan"),
]

hijack_pass = 0
for query, expected, label in HIJACK_TESTS:
    result = chat(query)
    got = result.get("intent", "").lower()
    # Hijack = incorrectly routed to floor_plan
    hijacked = "floor_plan" in got
    ok = not hijacked and any(e.lower() in got or got in e.lower() for e in expected)
    status = PASS if ok else FAIL
    resp = result.get("response", "")[:100].replace("\n", " ")
    print(f"  {status} {label}")
    print(f"         intent={got} hijacked={'YES' if hijacked else 'NO'}  [{result['elapsed']:.1f}s]")
    if ok:
        hijack_pass += 1

routing_score = routing_pass + hijack_pass
routing_total_all = routing_total + len(HIJACK_TESTS)
print(f"\n  ROUTING SCORE: {routing_score}/{routing_total_all} ({routing_score*100//routing_total_all}%)")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5: Capability KB Coverage
# ─────────────────────────────────────────────────────────────────────────────
section("PHASE 5 — CAPABILITY KB COVERAGE (12 categories)")

KB_TESTS = [
    ("What are the fire evacuation procedures?",                    "fire safety"),
    ("What happens if there is a power outage in the building?",    "power outage"),
    ("How do I access the building after hours?",                   "access control"),
    ("Where can I park near the building?",                         "parking"),
    ("How do I print from my laptop in this building?",             "printing"),
    ("Is there a prayer room or quiet room in the building?",       "wellbeing/quiet room"),
    ("Does the building track my location or movements?",           "data privacy"),
    ("Who manages this building and who should I contact?",         "building contact"),
    ("Can I bring a visitor or guest to the building?",             "visitor policy"),
    ("The office is too cold — who do I contact about comfort?",    "thermal comfort"),
    ("How do I connect to WiFi in this building?",                  "WiFi"),
    ("What green or sustainability certifications does this building have?", "sustainability"),
]

kb_pass = 0
kb_total = len(KB_TESTS)
for query, category in KB_TESTS:
    result = chat(query)
    resp = result.get("response", "").lower()
    got_intent = result.get("intent", "").lower()
    # KB success = intent is capability OR response contains substantive content (not just "I don't know")
    has_content = len(resp) > 80 and not any(x in resp for x in ["i don't know", "i cannot", "no information", "not sure about", "not have information"])
    is_capability = "capability" in got_intent or has_content
    status = PASS if is_capability else FAIL
    print(f"  {status} [{category}] intent={got_intent}")
    print(f"         response: {resp[:120].replace(chr(10),' ')}")
    if is_capability:
        kb_pass += 1

print(f"\n  KB SCORE: {kb_pass}/{kb_total} ({kb_pass*100//kb_total}%)")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 6: Multi-Intent Decomposition
# ─────────────────────────────────────────────────────────────────────────────
section("PHASE 6 — MULTI-INTENT DECOMPOSITION")

MULTI_TESTS = [
    (
        "Show me the floor 3 layout and also tell me how many rooms are there on that floor",
        ["floor_plan", "spatial_query", "planner"],
        "floor_plan + spatial_query compound",
    ),
    (
        "First tell me the current CO2 levels on floor 2 and then generate an energy report for last week",
        ["planner", "analytics", "sensor_data", "report"],
        "sensor_data + report compound",
    ),
    (
        "What sensors are installed in this building and also show me floor 1 layout",
        ["planner", "discovery", "floor_plan"],
        "discovery + floor_plan compound",
    ),
]

multi_pass = 0
for query, expected, label in MULTI_TESTS:
    result = chat(query)
    got = result.get("intent", "").lower()
    resp = result.get("response", "")[:150].replace("\n", " ")
    ok = any(e.lower() in got or got in e.lower() for e in expected)
    status = PASS if ok else WARN  # WARN not FAIL — multi-intent is optional upgrade
    print(f"  {status} {label}")
    print(f"         intent={got}  [{result['elapsed']:.1f}s]")
    print(f"         response: {resp}")
    if ok:
        multi_pass += 1

print(f"\n  MULTI-INTENT SCORE: {multi_pass}/{len(MULTI_TESTS)}")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 7: Persona Blending
# ─────────────────────────────────────────────────────────────────────────────
section("PHASE 7 — PERSONA × INTENT SPOT-CHECK")

PERSONA_TESTS = [
    ("Show me a maintenance report for HVAC systems this week", ["facility_manager"],           ["report","analytics","maintenance"],    "facility_manager → report"),
    ("What is the energy consumption trend for floor 2?",       ["energy_manager"],             ["analytics","sensor_data"],             "energy_manager → analytics"),
    ("Is there a quiet room available on floor 3?",             ["occupant"],                   ["capability","floor_plan","general"],   "occupant → capability"),
    ("What are the fire evacuation assembly points?",           ["safety_officer"],             ["capability","general_knowledge"],     "safety_officer → capability"),
    ("Run a statistical analysis of CO2 sensor variance by floor", ["analyst"],                 ["analytics","sensor_data"],             "analyst → analytics"),
    # Blended persona test
    ("What should I prioritise for building efficiency this week?", ["facility_manager","energy_manager"], ["analytics","report","general_knowledge"], "blended persona → analytics/report"),
]

persona_pass = 0
for query, personas, expected_intents, label in PERSONA_TESTS:
    result = chat(query, personas=personas)
    got = result.get("intent", "").lower()
    resp = result.get("response", "")[:120].replace("\n", " ")
    ok = any(e.lower() in got or got in e.lower() for e in expected_intents)
    status = PASS if ok else FAIL
    print(f"  {status} {label}  persona={personas}")
    print(f"         intent={got}  [{result['elapsed']:.1f}s]")
    print(f"         response: {resp}")
    if ok:
        persona_pass += 1

print(f"\n  PERSONA SCORE: {persona_pass}/{len(PERSONA_TESTS)}")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 8: Edge Cases
# ─────────────────────────────────────────────────────────────────────────────
section("PHASE 8 — EDGE CASES")

edge_pass = 0
edge_total = 0

def edge(label, fn):
    global edge_pass, edge_total
    edge_total += 1
    try:
        ok, detail = fn()
        status = PASS if ok else FAIL
        print(f"  {status} {label}: {detail}")
        if ok:
            edge_pass += 1
    except Exception as e:
        print(f"  {FAIL} {label}: EXCEPTION {e}")

# Empty query
def test_empty():
    r = chat("")
    ok = r["status_code"] in (200, 400, 422)  # should not crash (500)
    return ok, f"status={r['status_code']} intent={r.get('intent','?')}"
edge("Empty query (no 500)", test_empty)

# Very long query (500 chars)
def test_long():
    q = "What is the current temperature and CO2 level in every single zone and floor of this building? " * 6
    r = chat(q[:500])
    ok = r["status_code"] not in (500, 0)
    return ok, f"status={r['status_code']} intent={r.get('intent','?')[:30]}"
edge("500-char query (no 500)", test_long)

# SQL injection attempt
def test_sqli():
    r = chat("'; DROP TABLE sensors; --")
    ok = r["success"] and "error" not in r.get("response", "").lower()[:50]
    return ok, f"intent={r.get('intent','?')} response_safe={'yes' if ok else 'no'}"
edge("SQL injection treated as NL", test_sqli)

# Non-English query
def test_nonen():
    r = chat("Quelle est la température au 3ème étage?")
    ok = r["status_code"] not in (500, 0) and len(r.get("response", "")) > 20
    return ok, f"status={r['status_code']} intent={r.get('intent','?')}"
edge("Non-English query (no crash)", test_nonen)

# Unknown building
def test_unknown_bldg():
    try:
        payload = {"message": "What sensors exist?", "session_id": f"edge-{uuid.uuid4().hex[:6]}", "building_id": "bldg99"}
        r = requests.post(f"{BASE}/chat", headers=HEADERS, json=payload, timeout=30)
        ok = r.status_code != 500
        return ok, f"status={r.status_code}"
    except Exception as e:
        return False, str(e)
edge("Unknown building_id (no 500)", test_unknown_bldg)

# Multi-floor ambiguous — must NOT go to floor_plan
def test_multi_floor():
    r = chat("Compare floor 1 and floor 3 temperatures")
    got = r.get("intent", "").lower()
    ok = "floor_plan" not in got
    return ok, f"intent={got} floor_plan_hijack={'NO' if ok else 'YES'}"
edge("Multi-floor compare → NOT floor_plan", test_multi_floor)

# Sensor + floor — must NOT go to floor_plan
def test_sensor_floor():
    r = chat("CO2 readings floor 2 last hour")
    got = r.get("intent", "").lower()
    ok = "floor_plan" not in got
    return ok, f"intent={got} floor_plan_hijack={'NO' if ok else 'YES'}"
edge("Sensor+floor → NOT floor_plan", test_sensor_floor)

print(f"\n  EDGE CASE SCORE: {edge_pass}/{edge_total}")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 9: Cache Behaviour
# ─────────────────────────────────────────────────────────────────────────────
section("PHASE 9 — CACHE BEHAVIOUR")

cache_pass = 0

# 9a: Same query twice with different sessions should be consistent
q_cap = "Does the building have fire evacuation procedures?"
r1 = chat(q_cap, session_id=f"cache-a1-{uuid.uuid4().hex[:6]}")
r2 = chat(q_cap, session_id=f"cache-a2-{uuid.uuid4().hex[:6]}")
same_intent = r1.get("intent","").lower() == r2.get("intent","").lower()
print(f"  {'✅ PASS' if same_intent else '❌ FAIL'} Cache consistency: same query → same intent")
print(f"         r1_intent={r1.get('intent')} r2_intent={r2.get('intent')}")
if same_intent:
    cache_pass += 1

# 9b: Temperature-on-floor cached result should NOT become floor_plan
q_temp = "What is the temperature on floor 3?"
r_cold = chat(q_temp, session_id=f"cache-b1-{uuid.uuid4().hex[:6]}")
r_warm = chat(q_temp, session_id=f"cache-b2-{uuid.uuid4().hex[:6]}")
cold_ok = "floor_plan" not in r_cold.get("intent","").lower()
warm_ok = "floor_plan" not in r_warm.get("intent","").lower()
cache_floor_ok = cold_ok and warm_ok
print(f"  {'✅ PASS' if cache_floor_ok else '❌ FAIL'} Temperature-on-floor not hijacked (cold+warm)")
print(f"         cold_intent={r_cold.get('intent')} warm_intent={r_warm.get('intent')}")
if cache_floor_ok:
    cache_pass += 1

# 9c: Response cache in Redis
import subprocess
redis_keys = subprocess.run(
    ["docker", "exec", "redis-memory-store", "redis-cli", "dbsize"],
    capture_output=True, text=True
).stdout.strip()
print(f"  ℹ️  Redis total keys: {redis_keys}")
print(f"\n  CACHE SCORE: {cache_pass}/2")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 10: Performance Spot-Check
# ─────────────────────────────────────────────────────────────────────────────
section("PHASE 10 — PERFORMANCE SPOT-CHECK")

perf_queries = [
    ("What is the current temperature in zone 3?",                 "sensor_query"),
    ("What is the current temperature in zone 3?",                 "sensor_query_warm"),
    ("Show average temperature trend for floor 2 last week",        "analytics_query"),
    ("What floor plan does floor 2 look like?",                     "floor_plan_query"),
]

perf_pass = 0
for query, label in perf_queries:
    r = chat(query)
    elapsed = r["elapsed"]
    threshold = 15.0  # 15s hard limit
    ok = elapsed < threshold and r["status_code"] != 0
    status = PASS if ok else FAIL
    note = f"{elapsed:.1f}s" + (" ⚠️ SLOW" if elapsed > 8 else "")
    print(f"  {status} [{label}]: {note} intent={r.get('intent','?')}")
    if ok:
        perf_pass += 1

print(f"\n  PERFORMANCE SCORE: {perf_pass}/{len(perf_queries)}")


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
section("FINAL SCORES SUMMARY")
print(f"  Intent Routing (incl. hijack):  {routing_score}/{routing_total_all}")
print(f"  Capability KB:                   {kb_pass}/{kb_total}")
print(f"  Multi-Intent Decomposition:      {multi_pass}/{len(MULTI_TESTS)}")
print(f"  Persona × Intent:                {persona_pass}/{len(PERSONA_TESTS)}")
print(f"  Edge Cases:                      {edge_pass}/{edge_total}")
print(f"  Cache Behaviour:                 {cache_pass}/2")
print(f"  Performance:                     {perf_pass}/{len(perf_queries)}")
total_pass = routing_score + kb_pass + multi_pass + persona_pass + edge_pass + cache_pass + perf_pass
total_all = routing_total_all + kb_total + len(MULTI_TESTS) + len(PERSONA_TESTS) + edge_total + 2 + len(perf_queries)
pct = total_pass * 100 // total_all
print(f"\n  OVERALL: {total_pass}/{total_all} ({pct}%)")
print(f"  {'🟢 HEALTHY' if pct >= 80 else '🟡 DEGRADED' if pct >= 60 else '🔴 FAILING'}")
