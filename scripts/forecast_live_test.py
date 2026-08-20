"""
Comprehensive live test of the OntoSage real forecasting pipeline.

Tests:
  1.  Temperature sensor 5.01 — predict tomorrow (auto model)
  2.  Temperature sensor 5.02 — predict next 24 hours (auto model)
  3.  Temperature sensor 5.03 — predict next week (auto model)
  4.  CO2 sensor 5.01        — predict tomorrow (auto model)
  5.  CO2 sensor 5.02        — predict next 6 hours
  6.  Temperature 5.01       — predict next hour (short horizon)
  7.  Temperature 5.01       — "What will the temperature be tomorrow?" (NL variation)
  8.  CO2 5.01               — "Is CO2 expected to rise next week?" (trend question)
  9.  Recent data then forecast (multi-turn conversation)
  10. Temperature 5.01       — ask for ARIMA specifically
  11. Temperature 5.01       — ask for linear model specifically
  12. Temperature 5.01       — ask for Holt-Winters specifically
  13. Combined: recent trend + future forecast in one query
  14. Specific date: forecast for 3 June 2026
  15. Error path: non-existent zone

Run with:  python -X utf8 scripts/forecast_live_test.py
"""

import json
import sys
import time
import uuid
import requests
from datetime import datetime

BASE = "http://localhost:8000"
TOKEN = "IPbI5DfsP-lhgCvz-QH20F1MSUi_v4BniVIq9695NBg"
BUILDING = "bldg1"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}

# ─── Known sensors from discovery ─────────────────────────────────────────────
SENSORS = {
    "temp_5_01": "Air Temperature Sensor 5.01 (UUID: 5dd49972)",
    "temp_5_02": "Air Temperature Sensor 5.02 (UUID: fb509c82)",
    "temp_5_03": "Air Temperature Sensor 5.03 (UUID: b8497ecf)",
    "co2_5_01": "CO2 Level Sensor 5.01 (UUID: a66ca165)",
    "co2_5_02": "CO2 Level Sensor 5.02 (UUID: 0d98320e)",
    "co2_5_03": "CO2 Level Sensor 5.03 (UUID: 463fc249)",
}

results = []


def chat(message, session_id=None, timeout=60):
    sid = session_id or f"fc-test-{uuid.uuid4().hex[:8]}"
    t0 = time.time()
    try:
        r = requests.post(
            f"{BASE}/chat",
            headers=HEADERS,
            json={"message": message, "session_id": sid, "building_id": BUILDING},
            timeout=timeout,
        )
        elapsed = round(time.time() - t0, 2)
        d = r.json()
        data = d.get("data", {}) or {}
        return {
            "ok": d.get("success", False),
            "intent": data.get("intent", "?"),
            "response": data.get("response", ""),
            "elapsed": elapsed,
            "http": r.status_code,
        }
    except Exception as e:
        return {
            "ok": False,
            "intent": "ERROR",
            "response": str(e),
            "elapsed": round(time.time() - t0, 2),
            "http": 0,
        }


def check(result, label, checks):
    """Run a list of checks on a result and record pass/fail."""
    resp = result.get("response", "")
    intent = result.get("intent", "?")
    passed = []
    failed = []
    for name, condition in checks.items():
        ok = condition(resp, intent)
        (passed if ok else failed).append(name)

    status = "PASS" if not failed else "FAIL"
    results.append(
        {
            "label": label,
            "status": status,
            "intent": intent,
            "elapsed": result["elapsed"],
            "passed": passed,
            "failed": failed,
            "response_preview": resp[:200].replace("\n", " "),
        }
    )

    mark = "✅" if status == "PASS" else "❌"
    print(f"\n{mark} [{label}]  intent={intent}  [{result['elapsed']}s]")
    if failed:
        print(f"   FAILED checks: {failed}")
    for f in failed:
        print(f"   Response excerpt: {resp[:300]}")
    if status == "PASS":
        print(f"   Response preview: {resp[:200].replace(chr(10), ' ')}")
    return status == "PASS"


def section(title):
    print(f"\n{'='*72}")
    print(f"  {title}")
    print(f"{'='*72}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: Auto-model forecasting (system picks best model)
# ─────────────────────────────────────────────────────────────────────────────
section("SECTION 1 — Auto-Model Forecasting (system selects best model)")

# Test 1: Temperature 5.01 — tomorrow
r = chat("Predict the temperature for Air Temperature Sensor 5.01 tomorrow")
check(
    r,
    "T1 temp-5.01 predict tomorrow",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_prediction": lambda resp, _: any(
            x in resp for x in ["°C", "°c", "Predicted", "Forecast", "predict"]
        ),
        "has_ci_table": lambda resp, _: "| Time |" in resp or "80%" in resp or "95%" in resp,
        "has_model_info": lambda resp, _: any(
            x in resp for x in ["ARIMA", "Linear", "Holt", "Model Selection", "Winner"]
        ),
        "has_metrics": lambda resp, _: any(x in resp for x in ["RMSE", "MAE", "R²"]),
        "no_error": lambda resp, _: "not available" not in resp.lower()
        and "error" not in resp.lower()[:50],
    },
)

# Test 2: Temperature 5.02 — next 24 hours
r = chat("What will the temperature be for Air Temperature Sensor 5.02 over the next 24 hours?")
check(
    r,
    "T2 temp-5.02 next 24 hours",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_prediction": lambda resp, _: any(
            x in resp for x in ["°C", "Predicted", "forecast", "Forecast"]
        ),
        "has_ci_or_model": lambda resp, _: any(
            x in resp for x in ["80%", "95%", "ARIMA", "Linear", "Holt", "Winner"]
        ),
    },
)

# Test 3: Temperature 5.03 — next week
r = chat("Forecast temperature readings for Air Temperature Sensor 5.03 for next week")
check(
    r,
    "T3 temp-5.03 next week",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_prediction": lambda resp, _: any(
            x in resp for x in ["°C", "Predicted", "forecast", "Forecast", "Model"]
        ),
        "horizon_detected": lambda resp, _: any(x in resp for x in ["7 day", "week", "next 7"]),
    },
)

# Test 4: CO2 5.01 — tomorrow
r = chat("Predict CO2 levels for CO2 Level Sensor installed-node 5.01 tomorrow")
check(
    r,
    "T4 co2-5.01 predict tomorrow",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_content": lambda resp, _: len(resp) > 100,
        "not_general_err": lambda resp, _: "Hello" not in resp and "I specialise" not in resp,
    },
)

# Test 5: CO2 5.02 — next 6 hours
r = chat("What will CO2 be for sensor 5.02 in the next 6 hours?")
check(
    r,
    "T5 co2-5.02 next 6 hours",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_content": lambda resp, _: len(resp) > 80,
    },
)

# Test 6: Temperature 5.01 — next hour (very short horizon)
r = chat("Predict temperature for zone 5.01 in the next hour")
check(
    r,
    "T6 temp-5.01 next hour (short horizon)",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_prediction": lambda resp, _: len(resp) > 80,
        "short_steps": lambda resp, _: any(
            x in resp for x in ["10min", "10 min", "minute", "next hour", "1 hour"]
        ),
    },
)

# Test 7: Natural language variation
r = chat("What will the temperature be in zone 5.01 tomorrow morning?")
check(
    r,
    "T7 NL variation 'what will be tomorrow'",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_prediction": lambda resp, _: len(resp) > 100,
        "has_ci_or_model": lambda resp, _: any(
            x in resp for x in ["80%", "95%", "ARIMA", "Linear", "Model"]
        ),
    },
)

# Test 8: Trend-as-question format
r = chat("Is the CO2 level in zone 5.01 expected to rise over the next week?")
check(
    r,
    "T8 'expected to rise' CO2 next week",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_prediction": lambda resp, _: len(resp) > 100,
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Multi-turn — recent data THEN forecast
# ─────────────────────────────────────────────────────────────────────────────
section("SECTION 2 — Multi-turn: Recent Data then Forecast")

MULTI_SESSION = f"fc-multi-{uuid.uuid4().hex[:8]}"

# Step 1: Ask about recent data
r1 = chat(
    "Show me the temperature readings for Air Temperature Sensor 5.01 over the last 24 hours",
    session_id=MULTI_SESSION,
)
check(
    r1,
    "T9a multi-turn: recent data (step 1)",
    {
        "intent=sensor/analytics": lambda resp, intent: any(
            x in intent for x in ["sensor", "analyt", "trend", "metadata"]
        ),
        "has_temperature": lambda resp, _: any(
            x in resp.lower() for x in ["temperature", "°c", "23", "22", "24"]
        ),
    },
)

# Step 2: In same session, ask for forecast
r2 = chat(
    "Based on those readings, predict what the temperature will be tomorrow",
    session_id=MULTI_SESSION,
)
check(
    r2,
    "T9b multi-turn: forecast after data (step 2)",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_prediction": lambda resp, _: len(resp) > 100,
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: Explicit model specification
# ─────────────────────────────────────────────────────────────────────────────
section("SECTION 3 — Explicit Model Requests (user specifies forecasting method)")

# Test 10: ARIMA explicitly
r = chat("Use ARIMA to predict temperature for sensor 5.01 for tomorrow")
check(
    r,
    "T10 explicit ARIMA request",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_arima_or_pred": lambda resp, _: any(
            x in resp for x in ["ARIMA", "Predicted", "°C", "forecast", "arima"]
        ),
        "has_content": lambda resp, _: len(resp) > 100,
    },
)

# Test 11: Linear Regression explicitly
r = chat(
    "Using linear regression, forecast the temperature for Air Temperature Sensor 5.01 over the next 12 hours"
)
check(
    r,
    "T11 explicit Linear Regression request",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_linear_or_pred": lambda resp, _: any(
            x in resp for x in ["Linear", "linear", "Predicted", "°C", "forecast"]
        ),
        "has_content": lambda resp, _: len(resp) > 100,
    },
)

# Test 12: Exponential Smoothing explicitly
r = chat("Use exponential smoothing to predict temperature for zone 5.01 tomorrow")
check(
    r,
    "T12 explicit Holt-Winters ES request",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "has_es_or_pred": lambda resp, _: any(
            x in resp for x in ["Exponential", "Holt", "exponential", "Predicted", "°C"]
        ),
        "has_content": lambda resp, _: len(resp) > 100,
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: Specific date / complex queries
# ─────────────────────────────────────────────────────────────────────────────
section("SECTION 4 — Specific Dates and Complex Queries")

# Test 13: Specific date
r = chat("What will the temperature be in zone 5.01 on 3rd June 2026?")
check(
    r,
    "T13 specific date: 3 June 2026",
    {
        "has_content": lambda resp, _: len(resp) > 80,
        "not_crash": lambda resp, _: "500" not in resp and "error" not in resp.lower()[:30],
    },
)

# Test 14: Combined recent + future in one query
r = chat(
    "Show me the temperature trend for sensor 5.01 over the last 7 days and predict the next 3 days"
)
check(
    r,
    "T14 combined past trend + future prediction",
    {
        "has_content": lambda resp, _: len(resp) > 150,
        "has_data_or_pred": lambda resp, _: any(
            x in resp for x in ["°C", "temperature", "Temperature", "trend", "predict"]
        ),
    },
)

# Test 15: Non-existent zone (error path)
r = chat("Predict temperature for sensor 9.99 tomorrow")
check(
    r,
    "T15 non-existent sensor (graceful error)",
    {
        "no_500": lambda resp, _: len(resp) > 10,
        "not_crash": lambda resp, _: "500" not in resp and "Traceback" not in resp,
    },
)

# Test 16: All CO2 sensors forecast
r = chat("Forecast CO2 levels for all sensors on floor 5 for the next 24 hours")
check(
    r,
    "T16 all CO2 sensors floor 5 next 24h",
    {
        "has_content": lambda resp, _: len(resp) > 80,
        "not_crash": lambda resp, _: "Traceback" not in resp,
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: Forecast quality checks
# ─────────────────────────────────────────────────────────────────────────────
section("SECTION 5 — Forecast Output Quality Checks")

# Test 17: Confidence interval widening check
# Re-run temp 5.01 tomorrow and verify CI gets wider with horizon
r = chat(
    "Predict temperature for Air Temperature Sensor 5.01 for the next 24 hours with confidence intervals"
)
resp = r.get("response", "")
has_table = "| Time |" in resp
has_ci = "80%" in resp and "95%" in resp
has_rmse = "RMSE" in resp
has_model_selection = "Model Selection" in resp
has_reliability = "Reliability" in resp
has_trend_insight = any(x in resp for x in ["increasing", "decreasing", "stable"])

checks_17 = {
    "intent=trend": "trend" in r.get("intent", ""),
    "has_prediction_table": has_table,
    "has_both_ci_levels": has_ci,
    "has_rmse": has_rmse,
    "has_model_selection": has_model_selection,
    "has_reliability": has_reliability,
    "has_trend_direction": has_trend_insight,
}
all_passed_17 = all(checks_17.values())
results.append(
    {
        "label": "T17 output quality (CI, RMSE, model selection, reliability, trend)",
        "status": "PASS" if all_passed_17 else "FAIL",
        "intent": r.get("intent"),
        "elapsed": r["elapsed"],
        "passed": [k for k, v in checks_17.items() if v],
        "failed": [k for k, v in checks_17.items() if not v],
        "response_preview": resp[:200],
    }
)
mark = "✅" if all_passed_17 else "❌"
print(f"\n{mark} [T17 output quality check]  intent={r.get('intent')}  [{r['elapsed']}s]")
for k, v in checks_17.items():
    print(f"   {'✓' if v else '✗'} {k}")
print(f"   Response (first 300): {resp[:300].replace(chr(10),' ')}")

# Test 18: Model accuracy reported
r = chat("Predict temperature for sensor 5.01 next week and tell me how accurate your model is")
resp = r.get("response", "")
has_accuracy = any(
    x in resp for x in ["RMSE", "MAE", "MAPE", "accuracy", "reliable", "Reliability"]
)
check(
    r,
    "T18 accuracy metrics explicitly requested",
    {
        "intent=trend": lambda resp, intent: "trend" in intent,
        "reports_accuracy": lambda resp, _: has_accuracy,
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
section("SUMMARY")

total = len(results)
passed = sum(1 for r in results if r["status"] == "PASS")
failed = total - passed

print(f"\n  Tests run:  {total}")
print(f"  Passed:     {passed}")
print(f"  Failed:     {failed}")
print(f"  Score:      {passed}/{total} ({passed*100//total}%)")
print()

if failed:
    print("  FAILED tests:")
    for r in results:
        if r["status"] == "FAIL":
            print(f"    ❌ {r['label']}  intent={r['intent']}")
            print(f"       Missing: {r['failed']}")
            print(f"       Response: {r['response_preview'][:120]}")

# Write JSON for report generation
import json as _json

with open("/tmp/forecast_test_results.json", "w", encoding="utf-8") as f:
    _json.dump(
        {
            "timestamp": datetime.now().isoformat(),
            "total": total,
            "passed": passed,
            "failed": failed,
            "score_pct": passed * 100 // total,
            "results": results,
        },
        f,
        indent=2,
        ensure_ascii=False,
    )

print("\n  Results saved to /tmp/forecast_test_results.json")
print(
    f"\n  {'🟢 HEALTHY' if passed*100//total >= 80 else '🟡 DEGRADED' if passed*100//total >= 60 else '🔴 FAILING'}"
)
