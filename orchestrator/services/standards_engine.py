"""
Compliance Standards Engine — CAP-04
=====================================
Provides BREEAM, WELL v2, ISO 50001, EN 15251, and ASHRAE 55 thresholds
for compliance checking against live sensor readings.

Usage:
    from orchestrator.services.standards_engine import StandardsEngine

    engine = StandardsEngine()
    result = engine.check("breeam", {"co2_ppm": 850, "temp_c": 22.5})
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Built-in standards (embedded to avoid file dependencies; override via JSON)
# ─────────────────────────────────────────────────────────────────────────────

_BUILT_IN_STANDARDS: Dict[str, Any] = {
    "ashrae55": {
        "name": "ASHRAE 55 — Thermal Environmental Conditions for Human Occupancy",
        "version": "2023",
        "parameters": {
            "temp_c": {
                "summer": {
                    "min": 23.0,
                    "max": 26.0,
                    "unit": "°C",
                    "label": "Operative Temperature (summer)",
                },
                "winter": {
                    "min": 20.0,
                    "max": 23.5,
                    "unit": "°C",
                    "label": "Operative Temperature (winter)",
                },
            },
            "humidity_rh": {"min": 20.0, "max": 60.0, "unit": "%RH", "label": "Relative Humidity"},
        },
        "credits": None,
        "references": ["ASHRAE 55-2023 §5.3"],
    },
    "ashrae621": {
        "name": "ASHRAE 62.1 — Ventilation and Indoor Air Quality",
        "version": "2022",
        "parameters": {
            "co2_ppm": {
                "default": {"max": 1100, "guideline": 700, "unit": "ppm", "label": "CO2 (office)"},
            },
            "pm25_ugm3": {"max": 35.0, "unit": "µg/m³", "label": "PM2.5 (24h avg)"},
            "tvoc_ppb": {"max": 500, "unit": "ppb", "label": "Total VOC"},
        },
        "credits": None,
        "references": ["ASHRAE 62.1-2022 Table 6-1"],
    },
    "well_v2": {
        "name": "WELL Building Standard v2 — Air Quality",
        "version": "2",
        "url": "https://www.wellcertified.com",
        "features": {
            "air": {
                "co2_ppm": {"max": 1000, "unit": "ppm", "label": "CO2 (A01)"},
                "pm25_ugm3": {"max": 15.0, "unit": "µg/m³", "label": "PM2.5 annual avg (A03)"},
                "pm10_ugm3": {"max": 50.0, "unit": "µg/m³", "label": "PM10 24h avg (A03)"},
                "tvoc_ppb": {"max": 500, "unit": "ppb", "label": "Total VOC (A04)"},
                "humidity_rh": {
                    "min": 30.0,
                    "max": 60.0,
                    "unit": "%RH",
                    "label": "Relative Humidity (A07)",
                },
                "temp_c": {
                    "min": 19.0,
                    "max": 26.0,
                    "unit": "°C",
                    "label": "Thermal Comfort (T01)",
                },
            },
            "light": {
                "illuminance_lux": {
                    "min": 300,
                    "unit": "lux",
                    "label": "Illuminance task area (L01)",
                },
            },
        },
        "credits": "WELL Certification",
        "references": ["WELL v2 Feature A01, A03, A04, A07, T01, L01"],
    },
    "breeam": {
        "name": "BREEAM UK New Construction / In-Use",
        "version": "2018",
        "url": "https://bregroup.com/breeam",
        "credits": {
            "Hea 02": {
                "description": "Indoor air quality",
                "thresholds": {
                    "co2_ppm": {"max": 1000, "unit": "ppm", "label": "CO2 (occupied hours)"},
                    "tvoc_ppb": {"max": 300, "unit": "ppb", "label": "Total VOC (post-occupancy)"},
                    "pm25_ugm3": {"max": 25.0, "unit": "µg/m³", "label": "PM2.5"},
                    "pm10_ugm3": {"max": 40.0, "unit": "µg/m³", "label": "PM10"},
                },
            },
            "Hea 04": {
                "description": "Thermal comfort",
                "thresholds": {
                    "temp_c": {
                        "min": 19.0,
                        "max": 25.0,
                        "unit": "°C",
                        "label": "Operative Temperature",
                    },
                    "humidity_rh": {
                        "min": 40.0,
                        "max": 70.0,
                        "unit": "%RH",
                        "label": "Relative Humidity",
                    },
                },
            },
        },
        "references": ["BREEAM UK New Construction 2018 SD5076 §Hea 02, Hea 04"],
    },
    "iso50001": {
        "name": "ISO 50001:2018 — Energy Management Systems",
        "version": "2018",
        "url": "https://www.iso.org/standard/69426.html",
        "requirements": {
            "description": "ISO 50001 is a management system standard. Compliance requires establishing an Energy Baseline (EnB), defining Energy Performance Indicators (EnPIs), and demonstrating continual improvement.",
            "key_clauses": {
                "6.3": "Energy baseline establishment",
                "6.4": "Energy performance indicators",
                "6.5": "Energy data collection plan",
                "9.1": "Monitoring, measurement, analysis",
                "10.2": "Nonconformity and corrective action",
            },
            "energy_performance": {
                "eui_kwh_m2_year": {
                    "office_target": 100,
                    "office_good": 75,
                    "unit": "kWh/m²/year",
                    "label": "Energy Use Intensity (UK office benchmark)",
                },
                "carbon_kgco2_m2_year": {
                    "office_target": 30,
                    "unit": "kgCO₂/m²/year",
                    "label": "Carbon Intensity (UK office benchmark)",
                },
            },
        },
        "references": ["ISO 50001:2018", "CIBSE TM54", "ESOS Phase 3"],
    },
    "en15251": {
        "name": "EN 15251 / EN 16798-1 — Indoor Environmental Quality Criteria",
        "version": "EN 16798-1:2019",
        "categories": {
            "I": {
                "description": "High (sensitive occupants including disabled and elderly)",
                "temp_heating_c": {"min": 21.0, "max": 23.0, "unit": "°C"},
                "temp_cooling_c": {"min": 23.5, "max": 25.5, "unit": "°C"},
                "co2_above_outdoor_ppm": {"max": 550, "unit": "ppm above outdoor (~760 absolute)"},
            },
            "II": {
                "description": "Normal (new and renovated buildings)",
                "temp_heating_c": {"min": 20.0, "max": 24.0, "unit": "°C"},
                "temp_cooling_c": {"min": 23.0, "max": 26.0, "unit": "°C"},
                "co2_above_outdoor_ppm": {"max": 800, "unit": "ppm above outdoor (~1010 absolute)"},
            },
            "III": {
                "description": "Moderate (existing buildings)",
                "temp_heating_c": {"min": 19.0, "max": 25.0, "unit": "°C"},
                "temp_cooling_c": {"min": 22.0, "max": 27.0, "unit": "°C"},
                "co2_above_outdoor_ppm": {
                    "max": 1350,
                    "unit": "ppm above outdoor (~1560 absolute)",
                },
            },
        },
        "references": ["EN 16798-1:2019", "BS EN 15251:2007 (superseded)"],
    },
    "cibse_kg2": {
        "name": "CIBSE Guide A / TM52 / TM59 — Thermal Comfort & Overheating (UK)",
        "version": "2015/2017",
        "categories": {
            "temp_c": {
                "min": 21.0,
                "max": 25.0,
                "unit": "°C",
                "label": "Operative temperature (average office)",
            },
            "co2_ppm": {"max": 1000, "unit": "ppm", "label": "CO2 guidance limit"},
            "humidity_rh": {
                "min": 40.0,
                "max": 70.0,
                "unit": "%RH",
                "label": "Relative humidity guidance",
            },
            "temp_c_tm52_extreme": {
                "max": 28.0,
                "unit": "°C",
                "label": "TM52 Overheating threshold (absolute)",
            },
        },
        "references": [
            "CIBSE Guide A 2015 §1.3",
            "CIBSE TM52 Overheating criteria",
            "CIBSE TM59 Design methodology",
        ],
    },
    "leed_v41": {
        "name": "LEED v4.1 O+M — Indoor Environmental Quality",
        "version": "v4.1",
        "url": "https://www.usgbc.org/leed/v41",
        "parameters": {
            "co2_ppm": {"max": 1000, "unit": "ppm", "label": "CO2 Concentration (IEQ limit)"},
            "tvoc_ppb": {"max": 500, "unit": "µg/m³", "label": "Total VOC"},
            "pm25_ugm3": {"max": 12.0, "unit": "µg/m³", "label": "PM2.5 (annual limit)"},
            "pm10_ugm3": {"max": 50.0, "unit": "µg/m³", "label": "PM10 (annual limit)"},
            "formaldehyde_ppb": {"max": 27.0, "unit": "ppb", "label": "Formaldehyde"},
            "ozone_ppb": {"max": 51.0, "unit": "ppb", "label": "Ozone (Averaging over 8 hours)"},
        },
        "credits": "EQ Credit: Indoor Environmental Quality Performance",
        "references": ["LEED v4.1 Operations and Maintenance"],
    },
    "nabers_ieq": {
        "name": "NABERS Indoor Environment (Australia)",
        "version": "v1.2",
        "url": "https://www.nabers.gov.au",
        "parameters": {
            "temp_c": {
                "min": 20.0,
                "max": 26.0,
                "unit": "°C",
                "label": "Temperature Range (Core Target)",
            },
            "humidity_rh": {"min": 30.0, "max": 60.0, "unit": "%RH", "label": "Humidity Range"},
            "co2_ppm": {"max": 800, "unit": "ppm", "label": "CO2 Base Target (<800 ppm)"},
            "pm10_ugm3": {"max": 50.0, "unit": "µg/m³", "label": "PM10 Limit"},
            "tvoc_ppb": {"max": 500, "unit": "µg/m³", "label": "TVOC Maximum"},
            "illuminance_lux": {
                "min": 320,
                "max": 400,
                "unit": "lux",
                "label": "Task Lighting Target",
            },
        },
        "references": ["NABERS Rules for Indoor Environment for Offices"],
    },
    "green_star": {
        "name": "Green Star Buildings (Australia / GBCA)",
        "version": "v1",
        "url": "https://new.gbca.org.au",
        "parameters": {
            "co2_ppm": {"max": 800, "unit": "ppm", "label": "CO2 (Continuous Limit)"},
            "tvoc_ppb": {"max": 500, "unit": "µg/m³", "label": "TVOC (Clean Air Category)"},
            "pm25_ugm3": {"max": 10.0, "unit": "µg/m³", "label": "PM2.5 (High Performance Rating)"},
            "pm10_ugm3": {"max": 40.0, "unit": "µg/m³", "label": "PM10 Threshold"},
            "illuminance_lux": {"min": 160, "unit": "lux", "label": "Minimum Ambient Light"},
        },
        "references": ["Green Star Buildings v1 (Good Practice Credit)"],
    },
    "ashrae_90_1": {
        "name": "ASHRAE 90.1 — Energy Standard for Buildings",
        "version": "2022",
        "parameters": {
            "eui_kwh_m2_year": {
                "max": 120.0,
                "unit": "kWh/m²/yr",
                "label": "Baseline Target EUI (Office)",
            },
            "lighting_power_density_wm2": {
                "max": 9.6,
                "unit": "W/m²",
                "label": "LPD (Office Areas)",
            },
        },
        "references": ["ASHRAE 90.1-2022 Appendix G"],
    },
    "osha_safety": {
        "name": "OSHA / Safe Work / HSE (Industrial Safety & Health Hazards)",
        "version": "Current",
        "parameters": {
            "co2_ppm": {
                "max": 5000,
                "unit": "ppm",
                "label": "CO2 (8-hour Workplace Exposure Limit)",
            },
            "co_ppm": {
                "max": 50.0,
                "unit": "ppm",
                "label": "Carbon Monoxide (Time-Weighted Average)",
            },
            "pm25_ugm3": {
                "max": 5000.0,
                "unit": "µg/m³",
                "label": "Respirable Dust/PM2.5 Absolute Max",
            },
            "temp_c": {
                "min": 16.0,
                "max": 38.0,
                "unit": "°C",
                "label": "Extreme Safety Bounds (Non-Office)",
            },
        },
        "references": ["OSHA PEL", "HSE EH40 (UK)", "Safe Work Australia WES"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass-style dict builder
# ─────────────────────────────────────────────────────────────────────────────


def _make_check(
    parameter: str,
    value: float,
    threshold: Dict,
    status: str,
    margin: float,
    unit: str,
    label: str,
    standard: str,
    credit: str = "",
) -> Dict:
    return {
        "parameter": parameter,
        "label": label,
        "value": value,
        "unit": unit,
        "status": status,  # "compliant", "non_compliant", "borderline"
        "margin": round(margin, 2),
        "threshold": threshold,
        "standard": standard,
        "credit": credit,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main engine
# ─────────────────────────────────────────────────────────────────────────────


class StandardsEngine:
    """
    Checks sensor readings against built-in compliance standards.

    Supports BREEAM, WELL v2, ISO 50001, EN 15251, ASHRAE 55, ASHRAE 62.1, CIBSE.

    Usage:
        engine = StandardsEngine()
        result = engine.check("breeam", {"co2_ppm": 950, "temp_c": 23.5})
    """

    BORDERLINE_MARGIN_FACTOR = 0.10  # 10% within threshold = "borderline"

    def __init__(self, custom_standards_dir: Optional[str] = None):
        self._standards = dict(_BUILT_IN_STANDARDS)
        # Load any custom JSON overrides from data/standards/
        if custom_standards_dir:
            self._load_custom(Path(custom_standards_dir))
        else:
            _default_dir = Path(__file__).resolve().parent.parent / "data" / "standards"
            if _default_dir.exists():
                self._load_custom(_default_dir)

    def _load_custom(self, standards_dir: Path):
        """Load JSON override files from a standards directory."""
        for json_file in standards_dir.glob("*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
                key = json_file.stem  # filename without extension
                self._standards[key] = data
                logger.debug(f"StandardsEngine: loaded custom standard from {json_file}")
            except Exception as e:
                logger.warning(f"StandardsEngine: error loading {json_file}: {e}")

    def list_standards(self) -> List[str]:
        """Return list of available standard IDs."""
        return list(self._standards.keys())

    def get_standard(self, standard_id: str) -> Optional[Dict]:
        """Return a standard definition dict."""
        return self._standards.get(standard_id.lower().replace("-", "_").replace(" ", "_"))

    def check(
        self,
        standard_id: str,
        readings: Dict[str, float],
        season: str = "auto",
        en15251_category: str = "II",
    ) -> Dict[str, Any]:
        """
        Check readings against a standard.

        Args:
            standard_id:        e.g. "breeam", "well_v2", "ashrae55"
            readings:           {parameter: value} dict (e.g. {"co2_ppm": 850, "temp_c": 22.5})
            season:             "summer", "winter", "auto" (auto uses temp heuristic)
            en15251_category:   "I", "II", or "III" (only used for EN 15251)

        Returns:
            {
                "standard": str,
                "overall_status": "compliant" | "non_compliant" | "borderline",
                "compliance_score": float (0.0–1.0),
                "checks": [per-parameter check dicts],
                "summary": str,
                "references": [str],
            }
        """
        std = self.get_standard(standard_id)
        if not std:
            return {"error": f"Unknown standard: {standard_id}. Available: {self.list_standards()}"}

        checks: List[Dict] = []

        if standard_id == "breeam":
            checks = self._check_breeam(readings, std)
        elif standard_id in ("well_v2", "well"):
            checks = self._check_well_v2(readings, std)
        elif standard_id == "ashrae55":
            checks = self._check_ashrae55(readings, std, season)
        elif standard_id == "ashrae621":
            checks = self._check_ashrae621(readings, std)
        elif standard_id == "iso50001":
            checks = self._check_iso50001(readings, std)
        elif standard_id == "en15251":
            checks = self._check_en15251(readings, std, en15251_category, season)
        elif standard_id == "cibse_kg2":
            checks = self._check_simple(readings, std.get("categories", {}), std["name"])
        else:
            checks = self._generic_check(readings, std)

        # Compute overall status
        statuses = [c["status"] for c in checks]
        if "non_compliant" in statuses:
            overall = "non_compliant"
        elif "borderline" in statuses:
            overall = "borderline"
        elif checks:
            overall = "compliant"
        else:
            overall = "no_data"

        compliant_count = sum(1 for c in checks if c["status"] == "compliant")
        score = compliant_count / len(checks) if checks else 1.0

        summary = self._build_summary(standard_id, std, checks, overall)

        return {
            "standard": std.get("name", standard_id),
            "standard_id": standard_id,
            "overall_status": overall,
            "compliance_score": round(score, 3),
            "checks": checks,
            "summary": summary,
            "references": std.get("references", []),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Per-standard checkers
    # ─────────────────────────────────────────────────────────────────────────

    def _check_breeam(self, readings, std) -> List[Dict]:
        checks = []
        for credit_id, credit in std.get("credits", {}).items():
            for param, threshold in credit.get("thresholds", {}).items():
                if param in readings:
                    checks.append(
                        self._eval_threshold(
                            param, readings[param], threshold, std["name"], credit_id
                        )
                    )
        return checks

    def _check_well_v2(self, readings, std) -> List[Dict]:
        checks = []
        for _feature, params in std.get("features", {}).items():
            for param, threshold in params.items():
                if param in readings:
                    checks.append(
                        self._eval_threshold(param, readings[param], threshold, std["name"])
                    )
        return checks

    def _check_ashrae55(self, readings, std, season) -> List[Dict]:
        checks = []
        params = std.get("parameters", {})
        # Determine season automatically from temp
        if season == "auto":
            temp = readings.get("temp_c", 20)
            season = "summer" if temp >= 24 else "winter"
        for param, variants in params.items():
            if param in readings:
                if isinstance(variants, dict) and any(k in variants for k in ("min", "max")):
                    threshold = variants
                else:
                    threshold = variants.get(season, list(variants.values())[0])
                checks.append(self._eval_threshold(param, readings[param], threshold, std["name"]))
        return checks

    def _check_ashrae621(self, readings, std) -> List[Dict]:
        checks = []
        for param, data in std.get("parameters", {}).items():
            if param in readings:
                threshold = data.get("default", data)
                checks.append(self._eval_threshold(param, readings[param], threshold, std["name"]))
        return checks

    def _check_iso50001(self, readings, std) -> List[Dict]:
        checks = []
        energy_perf = std.get("requirements", {}).get("energy_performance", {})
        for param, threshold in energy_perf.items():
            if param in readings:
                target = threshold.get("office_target") or threshold.get("office_good", 0)
                value = readings[param]
                unit = threshold.get("unit", "")
                label = threshold.get("label", param)
                margin = target - value
                pct = abs(margin) / target if target else 0
                if value <= target:
                    status = "compliant"
                elif pct <= self.BORDERLINE_MARGIN_FACTOR:
                    status = "borderline"
                else:
                    status = "non_compliant"
                checks.append(
                    _make_check(
                        param, value, {"target": target}, status, margin, unit, label, std["name"]
                    )
                )
        return checks

    def _check_en15251(self, readings, std, category, season) -> List[Dict]:
        checks = []
        cat = std.get("categories", {}).get(category, {})
        if not cat:
            return checks
        if "co2_above_outdoor_ppm" in cat and "co2_ppm" in readings:
            t = cat["co2_above_outdoor_ppm"]
            # Approximate absolute limit = outdoor CO2 (~420 ppm) + allowed delta
            absolute_max = 420 + t["max"]
            check_t = {
                "max": absolute_max,
                "unit": "ppm",
                "label": f"CO2 absolute max (EN16798 Cat {category})",
            }
            checks.append(
                self._eval_threshold("co2_ppm", readings["co2_ppm"], check_t, std["name"])
            )
        key = "temp_cooling_c" if season == "summer" else "temp_heating_c"
        if key in cat and "temp_c" in readings:
            t = cat[key].copy()
            t["label"] = f"Temperature (EN16798 Cat {category}, {season})"
            checks.append(self._eval_threshold("temp_c", readings["temp_c"], t, std["name"]))
        return checks

    def _check_simple(self, readings, thresholds, std_name) -> List[Dict]:
        checks = []
        for param, threshold in thresholds.items():
            if param in readings:
                checks.append(self._eval_threshold(param, readings[param], threshold, std_name))
        return checks

    def _generic_check(self, readings, std) -> List[Dict]:
        checks = []
        for section in std.values():
            if isinstance(section, dict):
                for param, threshold in section.items():
                    if param in readings and isinstance(threshold, dict):
                        checks.append(
                            self._eval_threshold(
                                param, readings[param], threshold, std.get("name", "")
                            )
                        )
        return checks

    def _eval_threshold(
        self,
        param: str,
        value: float,
        threshold: Dict,
        std_name: str,
        credit: str = "",
    ) -> Dict:
        """Evaluate a single parameter against a threshold dict."""
        max_val = threshold.get("max")
        min_val = threshold.get("min")
        unit = threshold.get("unit", "")
        label = threshold.get("label", param.replace("_", " ").title())

        violations = 0
        margin = 0.0

        if max_val is not None:
            excess = value - max_val
            if excess > 0:
                violations += 1
                pct = excess / max_val if max_val else 0
                margin = -excess
                status = "borderline" if pct <= self.BORDERLINE_MARGIN_FACTOR else "non_compliant"
            else:
                margin = max_val - value

        if min_val is not None and violations == 0:
            deficit = min_val - value
            if deficit > 0:
                violations += 1
                pct = deficit / min_val if min_val else 0
                margin = -deficit
                status = "borderline" if pct <= self.BORDERLINE_MARGIN_FACTOR else "non_compliant"
            else:
                margin = min(margin, value - min_val) if max_val else value - min_val

        if violations == 0:
            status = "compliant"

        return _make_check(param, value, threshold, status, margin, unit, label, std_name, credit)

    def _build_summary(self, standard_id, std, checks, overall) -> str:
        """Build a human-readable compliance summary."""
        total = len(checks)
        if total == 0:
            return f"No measurable parameters found in readings for {std.get('name', standard_id)}."

        compliant = sum(1 for c in checks if c["status"] == "compliant")
        non_compliant = [c for c in checks if c["status"] == "non_compliant"]
        borderline = [c for c in checks if c["status"] == "borderline"]

        parts = [f"{std.get('name', standard_id)}: {compliant}/{total} parameters compliant."]

        if non_compliant:
            violated = ", ".join(f"{c['label']} ({c['value']}{c['unit']})" for c in non_compliant)
            parts.append(f"❌ Non-compliant: {violated}.")

        if borderline:
            border = ", ".join(f"{c['label']} ({c['value']}{c['unit']})" for c in borderline)
            parts.append(f"⚠️ Borderline: {border}.")

        if overall == "compliant":
            parts.append("✅ All measured parameters are within standard thresholds.")

        return " ".join(parts)


# Module-level singleton
_engine_instance: Optional[StandardsEngine] = None


def get_standards_engine() -> "StandardsEngine":
    """Return the shared StandardsEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = StandardsEngine()
    return _engine_instance
