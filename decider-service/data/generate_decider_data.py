import json
import os
import re

# Input T5 dataset used previously
T5_FILE = os.path.join(
    "..", "..", "Transformers", "t5_base", "abacws_bldg_timeseries_question_pairs_entities.json"
)

OUT_PATH = os.path.join(".", "decider_training.auto.jsonl")


def is_ttl_only(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in [
        "label", "type", "class", "category", "installed", "location",
        "where is", "which sensor", "which sensors", "list sensors", "show sensors",
    ])


def analytics_label_from_question(q: str) -> str | None:
    ql = (q or "").lower()
    if "recalibration" in ql:
        return "analyze_recalibration_frequency"
    if re.search(r"failure(s)?\b", ql):
        return "analyze_failure_trends"
    if "deviat" in ql and "temperature" not in ql and "humidity" not in ql:
        return "analyze_device_deviation"
    if re.search(r"\bstatus\b", ql):
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
    if any(k in ql for k in ["average", "avg", "mean"]):
        return "average"
    if any(k in ql for k in ["maximum", "max", "peak"]):
        return "max"
    if any(k in ql for k in ["minimum", "min", "lowest"]):
        return "min"
    if any(k in ql for k in ["sum", "total", "aggregate"]):
        return "sum"
    return None


def main():
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), T5_FILE))
    out = os.path.abspath(os.path.join(os.path.dirname(__file__), OUT_PATH))

    if not os.path.exists(src):
        raise FileNotFoundError(f"T5 dataset not found at {src}")

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    n = 0
    with open(out, "w", encoding="utf-8") as w:
        for item in data:
            q = (item.get("question") or "").strip()
            if not q:
                continue
            ttl_only = is_ttl_only(q)
            if ttl_only:
                obj = {"text": q, "perform": 0, "analytics": None}
            else:
                label = analytics_label_from_question(q)
                obj = {"text": q, "perform": 1, "analytics": label or "analyze_sensor_trend"}
            w.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1

    print(f"Wrote {n} items -> {out}")


if __name__ == "__main__":
    main()
