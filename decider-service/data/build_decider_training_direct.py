import os
import re
import json
from collections import OrderedDict


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
T5_PATH = os.path.join(ROOT, "Transformers", "t5_base", "abacws_bldg_timeseries_question_pairs_entities.json")
ANALYTICS_DIR = os.path.join(ROOT, "analytics-selector-service", "data")
ANALYTICS_FILES = [
    os.path.join(ANALYTICS_DIR, "analytics_training.jsonl"),
    os.path.join(ANALYTICS_DIR, "analytics_training.auto.jsonl"),
]
OUT_PATH = os.path.join(os.path.dirname(__file__), "decider_training.direct.jsonl")


TTL_PATTERNS = [
    r"\blabel\b", r"\bname\b", r"\btype\b", r"\bclass\b", r"\bcategory\b",
    r"\blocation\b", r"\bwhere is\b", r"\binstalled( in)?\b", r"\broom\b", r"\bfloor\b", r"\bzone\b",
    r"\bshow (all )?sensors\b", r"\blist( all)? sensors\b", r"\bwhich sensors\b", r"\bdescribe\b",
    r"\bconnected to\b", r"\bpart of\b", r"\bbelongs to\b", r"\bhas point\b", r"\bmetadata\b",
    r"\btimeseriesid\b", r"\buuid\b", r"\bid\b", r"\biri\b", r"\bur[iı]\b",
    r"\bhow many sensors\b", r"\bcount of sensors\b",
]

ANALYTICS_MAP = OrderedDict([
    # Specific, multi-word patterns first
    (r"failure trend|failures?", "analyze_failure_trends"),
    (r"recalibration", "analyze_recalibration_frequency"),
    (r"supply .*return .*temp", "analyze_supply_return_temp_difference"),
    (r"air flow .*variation|vary", "analyze_air_flow_variation"),
    (r"air quality index|\baqi\b", "compute_air_quality_index"),
    (r"health alert|alerts?", "generate_health_alerts"),
    (r"pressure", "analyze_pressure_trend"),
    (r"noise", "analyze_noise_levels"),
    (r"formaldehyde", "analyze_formaldehyde_levels"),
    (r"\bco2\b", "analyze_co2_levels"),
    (r"\bpm( |\d|10|2\.5|2_5|2-5)", "analyze_pm_levels"),
    (r"temperature.*humidity|humidity.*temperature", "analyze_temperature_humidity"),
    (r"temperature", "analyze_temperatures"),
    (r"humidity", "analyze_humidity"),
    (r"air quality.*trend|trend.*air quality", "analyze_air_quality_trends"),
    (r"air quality", "analyze_air_quality"),
    (r"hvac.*(anomal|issue|abnormal)", "analyze_hvac_anomalies"),
    # General analytics intents
    (r"correlat|relationship", "correlate_sensors"),
    (r"anomal|outlier|abnormal", "detect_anomalies"),
    (r"aggregate", "aggregate_sensor_data"),
    (r"trend|over time|time series", "analyze_sensor_trend"),
    (r"deviat(ion)?", "analyze_device_deviation"),
    (r"status", "analyze_sensor_status"),
    (r"forecast|predict", "forecast_downtimes"),
    # Simple statistics/values
    (r"average|avg|mean", "average"),
    (r"maximum|max|peak", "max"),
    (r"minimum|min|lowest", "min"),
    (r"sum|total", "sum"),
    (r"latest value|current value|current reading|latest reading|value|reading", "retrieve_latest_value"),
    (r"compare|difference", "compare_sensors"),
])


def ttl_only(q: str) -> bool:
    ql = (q or "").lower()
    for pat in TTL_PATTERNS:
        if re.search(pat, ql):
            return True
    # If the question clearly asks for a value or analysis, it's not TTL-only
    if re.search(r"average|avg|mean|max|min|trend|value|reading|compare|correlat|anomal|forecast|predict|sum|total|status|deviat|over time|time series", ql):
        return False
    # Default to TTL if it's a pure descriptive query
    return True


def analytics_label(q: str) -> str | None:
    ql = (q or "").lower()
    for pat, label in ANALYTICS_MAP.items():
        if re.search(pat, ql):
            return label
    return None


def load_t5_questions(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for item in data:
        q = (item.get("question") or "").strip()
        if q:
            out.append(q)
    return out


def load_analytics_pairs(files: list[str]) -> dict[str, str]:
    pairs = {}
    for p in files:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                q = (obj.get("text") or obj.get("question") or "").strip()
                lab = obj.get("label") or obj.get("analytics")
                if not q or not lab:
                    continue
                pairs[q] = lab
    return pairs


def main():
    if not os.path.exists(T5_PATH):
        raise FileNotFoundError(f"T5 file not found: {T5_PATH}")

    questions = load_t5_questions(T5_PATH)
    analytics_pairs = load_analytics_pairs(ANALYTICS_FILES)

    # Build consolidated dataset
    seen = set()
    items = []

    for q in questions:
        if q in seen:
            continue
        seen.add(q)

        # If analytics label already curated from analytics dataset, prefer it
        if q in analytics_pairs:
            items.append({"text": q, "perform": 1, "analytics": analytics_pairs[q]})
            continue

        # TTL-only?
        if ttl_only(q):
            items.append({"text": q, "perform": 0, "analytics": None})
            continue

        # Otherwise, try to map to an analytics label; if unknown, create a new descriptive label
        lab = analytics_label(q)
        if lab is None:
            # Create a new label following a consistent naming convention
            # e.g., questions about "median" → add "median"; about "95th percentile" → "percentile_95"
            ql = q.lower()
            if "median" in ql:
                lab = "median"
            elif "percentile" in ql:
                # capture first number as percentile
                m = re.search(r"(\d+)(st|nd|rd|th)?\s*percentile", ql)
                lab = f"percentile_{m.group(1)}" if m else "percentile"
            elif "variance" in ql:
                lab = "variance"
            elif "std" in ql or "standard deviation" in ql:
                lab = "stddev"
            elif "rate of change" in ql or "derivative" in ql:
                lab = "rate_of_change"
            elif "moving average" in ql:
                lab = "moving_average"
            elif "rolling" in ql:
                lab = "rolling_stats"
            elif "normalize" in ql or "normalized" in ql:
                lab = "normalize"
            elif "seasonal" in ql or "seasonality" in ql:
                lab = "seasonality"
            elif "baseline" in ql:
                lab = "baseline_compare"
            elif "distribution" in ql or "histogram" in ql:
                lab = "distribution"
            elif "kpi" in ql:
                lab = "kpi"
            else:
                lab = "general_analytics"

        items.append({"text": q, "perform": 1, "analytics": lab})

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as w:
        for obj in items:
            w.write(json.dumps(obj, ensure_ascii=False) + "\n")

    print(f"Wrote {len(items)} items -> {OUT_PATH}")


if __name__ == "__main__":
    main()
