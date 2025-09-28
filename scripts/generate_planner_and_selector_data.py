import json
import os
import re
from collections import defaultdict


T5_FILE = os.path.join(
    "Transformers",
    "t5_base",
    "abacws_bldg_timeseries_question_pairs_entities.json",
)

# Outputs
PLANNER_OUT = os.path.join(
    "planner-service", "data", "planner_training.auto.jsonl"
)
SELECTOR_OUT = os.path.join(
    "analytics-selector-service", "data", "analytics_training.auto.jsonl"
)


def route_from_question(q: str) -> str:
    ql = (q or "").lower()
    # Correlation
    if re.search(r"\bcorrelat(e|ion|ing)\b|relationship", ql):
        return "correlate"
    # Anomalies / failures
    if re.search(r"\b(anomal|outlier|abnormal)\w*|potential failure|failures?\b", ql):
        return "anomaly"
    # Timeseries analysis (trends, ranges, historical, forecast)
    if re.search(
        r"trend|over the (past|last)|from \d|historical|time series|regression|forecast|seasonal|periodicity",
        ql,
    ):
        return "timeseries"
    # Metric-like queries (point or aggregate values)
    if re.search(
        r"average|avg|mean|max(imum)?|min(imum)?|latest|current|value|reading|status|sum|total",
        ql,
    ):
        return "metric"
    # Listing style (generic show/list sensors) — not very present in this dataset
    if re.search(r"\blist\b|which sensors|show (all )?sensors|where are the sensors", ql):
        return "listing"
    # Descriptive (label/type/location/details)
    if re.search(r"label|type|class|category|location|installed|where is|what sensor is", ql):
        return "describe"
    return "describe"


def analytics_label_from_question(q: str) -> str | None:
    ql = (q or "").lower()
    # Order matters: pick the most specific first
    if "recalibration" in ql:
        return "analyze_recalibration_frequency"
    if "failure trend" in ql or re.search(r"failure(s)?\b", ql):
        return "analyze_failure_trends"
    if "deviat" in ql and "temperature" not in ql and "humidity" not in ql:
        return "analyze_device_deviation"
    if "sensor status" in ql or re.search(r"\bstatus\b", ql):
        return "analyze_sensor_status"
    if "air quality trend" in ql or ("air quality" in ql and "trend" in ql):
        return "analyze_air_quality_trends"
    if "hvac" in ql and re.search(r"anomal|issue|abnormal", ql):
        return "analyze_hvac_anomalies"
    if "supply" in ql and "return" in ql and "temp" in ql:
        return "analyze_supply_return_temp_difference"
    if "air flow" in ql and ("variation" in ql or "vary" in ql):
        return "analyze_air_flow_variation"
    if "correlat" in ql or "relationship" in ql:
        return "correlate_sensors"
    if "air quality index" in ql or re.search(r"\baqi\b", ql):
        return "compute_air_quality_index"
    if "health alert" in ql or "alerts" in ql:
        return "generate_health_alerts"
    if re.search(r"anomal|outlier|abnormal", ql):
        return "detect_anomalies"
    if "noise" in ql:
        return "analyze_noise_levels"
    if "formaldehyde" in ql:
        return "analyze_formaldehyde_levels"
    if re.search(r"\bco2\b", ql):
        return "analyze_co2_levels"
    if re.search(r"\bpm( |\d|10|2\.5|2_5|2-5)", ql):
        return "analyze_pm_levels"
    # Temperature + humidity together first
    if "temperature" in ql and "humidity" in ql:
        return "analyze_temperature_humidity"
    if "temperature" in ql:
        return "analyze_temperatures"
    if "humidity" in ql:
        return "analyze_humidity"
    if "air quality" in ql:
        return "analyze_air_quality"
    if "aggregate" in ql:
        return "aggregate_sensor_data"
    if "potential failure" in ql or "failures" in ql:
        return "detect_potential_failures"
    if "forecast" in ql and ("downtime" in ql or "downtimes" in ql):
        return "forecast_downtimes"
    if "trend" in ql or "time series" in ql:
        return "analyze_sensor_trend"
    # Not every question maps to an analytics function — return None to skip
    return None


def main():
    if not os.path.exists(T5_FILE):
        raise FileNotFoundError(f"T5 file not found at {T5_FILE}")

    with open(T5_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Planner dataset
    planner_items = []
    # Analytics selector dataset
    selector_items = []

    # Dedup helpers
    seen_planner = set()
    seen_selector = set()

    for item in data:
        q = item.get("question", "").strip()
        if not q:
            continue

        # Planner routing label
        route = route_from_question(q)
        key_p = (q, route)
        if key_p not in seen_planner:
            planner_items.append({"text": q, "label": route})
            seen_planner.add(key_p)

        # Analytics function label (only when we can confidently map)
        alabel = analytics_label_from_question(q)
        if alabel is not None:
            key_s = (q, alabel)
            if key_s not in seen_selector:
                selector_items.append({"text": q, "label": alabel})
                seen_selector.add(key_s)

    os.makedirs(os.path.dirname(PLANNER_OUT), exist_ok=True)
    os.makedirs(os.path.dirname(SELECTOR_OUT), exist_ok=True)

    with open(PLANNER_OUT, "w", encoding="utf-8") as f:
        for obj in planner_items:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    with open(SELECTOR_OUT, "w", encoding="utf-8") as f:
        for obj in selector_items:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(
        f"Wrote {len(planner_items)} planner items -> {PLANNER_OUT}\n"
        f"Wrote {len(selector_items)} selector items -> {SELECTOR_OUT}"
    )


if __name__ == "__main__":
    main()
