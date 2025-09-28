import json
import os
import re
from typing import Dict, Any


KNOWN_FUNCTIONS = {
    "analyze_recalibration_frequency",
    "analyze_failure_trends",
    "analyze_device_deviation",
    "analyze_sensor_status",
    "analyze_air_quality_trends",
    "analyze_hvac_anomalies",
    "analyze_supply_return_temp_difference",
    "analyze_air_flow_variation",
    "analyze_sensor_trend",
    "aggregate_sensor_data",
    "correlate_sensors",
    "compute_air_quality_index",
    "generate_health_alerts",
    "detect_anomalies",
    "analyze_noise_levels",
    "analyze_air_quality",
    "analyze_formaldehyde_levels",
    "analyze_co2_levels",
    "analyze_pm_levels",
    "analyze_temperatures",
    "analyze_humidity",
    "analyze_temperature_humidity",
    "detect_potential_failures",
    "forecast_downtimes",
}


DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # 2025-02-01
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),  # 01/02/2025 or 1-2-25
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I),
]


def needs_analytics(question: str) -> bool:
    q = question.lower()
    # Strong analytic cues
    analytic_keywords = [
        "trend", "average", "mean", "median", "std", "standard deviation", "min", "max",
        "aggregate", "sum", "count", "correlate", "correlation", "compare", "comparison",
        "anomaly", "anomalies", "outlier", "deviation", "increase", "decrease", "change",
        "forecast", "predict", "prediction", "rolling", "moving average", "window",
        "latest reading", "time series", "time-series", "status on", "status at",
    ]
    if any(k in q for k in analytic_keywords):
        return True
    # Date/time range often implies time-series analytics
    if any(p.search(q) for p in DATE_PATTERNS):
        if any(x in q for x in ["from", "to", "between", "since", "until", "till", "on "]):
            return True
    # Weak cues that likely still imply analytics beyond static TTL
    weak = ["levels", "values over", "history", "historical", "recent"]
    if any(w in q for w in weak):
        return True
    return False


def guess_label(question: str) -> str:
    q = question.lower()
    # Specific mappings first
    if "recalibration" in q:
        return "analyze_recalibration_frequency"
    if "failure" in q and ("potential" in q or "predict" in q or "next" in q):
        return "detect_potential_failures"
    if "failure" in q or "downtime" in q or "fault" in q:
        return "analyze_failure_trends"
    if "deviation" in q:
        return "analyze_device_deviation"
    if "status" in q:
        return "analyze_sensor_status"
    if "air quality" in q and "trend" in q:
        return "analyze_air_quality_trends"
    if "air quality" in q:
        return "analyze_air_quality"
    if "hvac" in q:
        return "analyze_hvac_anomalies"
    if "supply" in q and "return" in q and "temperature" in q:
        return "analyze_supply_return_temp_difference"
    if "flow" in q:
        return "analyze_air_flow_variation"
    if "aggregate" in q or "aggregation" in q:
        return "aggregate_sensor_data"
    if "correlate" in q or "correlation" in q:
        return "correlate_sensors"
    if "air quality index" in q or "aqi" in q:
        return "compute_air_quality_index"
    if "alert" in q:
        return "generate_health_alerts"
    if "anomaly" in q or "outlier" in q:
        return "detect_anomalies"
    if "noise" in q or "sound" in q:
        return "analyze_noise_levels"
    if "formaldehyde" in q:
        return "analyze_formaldehyde_levels"
    if "co2" in q:
        return "analyze_co2_levels"
    if re.search(r"\bpm(\s|\d)", q):
        return "analyze_pm_levels"
    if "temperature" in q and "humidity" in q:
        return "analyze_temperature_humidity"
    if "temperature" in q:
        return "analyze_temperatures"
    if "humidity" in q:
        return "analyze_humidity"
    if "forecast" in q or "predict" in q:
        return "forecast_downtimes"
    if "trend" in q:
        return "analyze_sensor_trend"
    # Fallback
    return "custom"


def main():
    in_path = os.path.join(os.path.dirname(__file__), "decider_training.direct.jsonl")
    backup_path = in_path + ".bak"
    out_path = in_path

    if not os.path.exists(in_path):
        raise SystemExit(f"Input JSONL not found: {in_path}")

    with open(in_path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]

    updated = 0
    total = 0
    for i, ln in enumerate(lines):
        total += 1
        try:
            obj: Dict[str, Any] = json.loads(ln)
        except Exception:
            continue
        q = str(obj.get("question") or obj.get("text") or "")
        perform = int(obj.get("perform", obj.get("perform_analytics", 0)) or 0)
        analytics = obj.get("analytics")

        if needs_analytics(q):
            # Force analytics path in dataset even if function not yet implemented
            # Prefer existing analytics label if available, otherwise guess
            new_label = analytics or guess_label(q)
            # If label is not in current implemented function set, map to "custom"
            if new_label not in KNOWN_FUNCTIONS:
                new_label = "custom"
            if perform != 1 or analytics != new_label:
                obj["perform"] = 1
                obj["analytics"] = new_label
                lines[i] = json.dumps(obj, ensure_ascii=False)
                updated += 1
        else:
            # TTL-only; ensure perform is 0 and analytics is None or preserved if provided
            if perform != 0:
                obj["perform"] = 0
                # Leave analytics as-is or set to None
                obj["analytics"] = obj.get("analytics") or None
                lines[i] = json.dumps(obj, ensure_ascii=False)
                updated += 1

    # Write backup and then overwrite
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    # We wrote updated lines to backup first to be safe, now write to original
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(json.dumps({
        "total": total,
        "updated": updated,
        "input": in_path,
        "backup": backup_path,
        "note": "perform set to 1 for analytic questions with label in known set else 'custom'"
    }))


if __name__ == "__main__":
    main()
