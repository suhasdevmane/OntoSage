"""
Shared constants for OntoSage.
Import from here instead of defining locally in each agent.
"""
from typing import Dict

# ---------------------------------------------------------------------------
# Sensor comfort / safe operating ranges (building-agnostic defaults).
# Keys match the normalised sensor type strings used in anomaly_agent and
# report_agent.  Override per building via settings or building_config.yaml.
# ---------------------------------------------------------------------------
COMFORT_RANGES: Dict[str, Dict] = {
    "temperature": {"min": 18.0, "max": 26.0,   "unit": "°C"},
    "humidity":    {"min": 30.0, "max": 70.0,   "unit": "%"},
    "co2":         {"min": 0.0,  "max": 1000.0, "unit": "ppm"},
    "voc":         {"min": 0.0,  "max": 500.0,  "unit": "ppb"},
    "occupancy":   {"min": 0.0,  "max": 1.0,    "unit": "binary"},
    "pressure":    {"min": 950.0,"max": 1050.0, "unit": "hPa"},
    "light":       {"min": 0.0,  "max": 2000.0, "unit": "lux"},
    "sound":       {"min": 0.0,  "max": 85.0,   "unit": "dB"},
    "pm2":         {"min": 0.0,  "max": 35.0,   "unit": "µg/m³"},
    "pm10":        {"min": 0.0,  "max": 50.0,   "unit": "µg/m³"},
}

# ---------------------------------------------------------------------------
# Anomaly detection thresholds — configurable via settings in future.
# ---------------------------------------------------------------------------
Z_SCORE_THRESHOLD: float = 2.5    # flag if |z-score| > this
SPIKE_PCT_THRESHOLD: float = 0.40  # flag if reading changes > 40 % in one step

# ---------------------------------------------------------------------------
# Visualisation / analytics keyword lists used in routing decisions.
# ---------------------------------------------------------------------------
VIZ_KEYWORDS = frozenset(["plot", "chart", "graph", "visualize", "visualise", "show", "display"])

ANALYTICS_KEYWORDS = frozenset([
    "average", "avg", "mean", "max", "maximum", "min", "minimum",
    "sum", "total", "count", "trend", "history", "compare", "analysis",
    "statistics", "stats", "over time", "range", "distribution",
])
