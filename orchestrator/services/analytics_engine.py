"""
Phase 6.2 — Deterministic Analytics Expansion
===============================================
Extends the OntoSage analytics pipeline with a library of deterministic,
pre-coded computation functions. These are faster, more reproducible, and
more reliable than asking the LLM to write code, and cover the most common
building performance analysis patterns.

Modules:
  ComfortAnalyser    — ASHRAE 55 / WELL / EN 15251 comfort bands
  EnergyAnalyser     — Energy patterns: peak detection, schedules, EUI
  AirQualityAnalyser — IAQ: CO2, PM2.5, VOC grade scoring
  OccupancyAnalyser  — Utilisation rates, density, schedule inference
  TrendAnalyser      — Statistical trend detection (Mann-Kendall, slopes)
  ComplianceChecker  — Multi-standard compliance report generation

Usage:
    from orchestrator.services.analytics_engine import AnalyticsEngine, AnalysisRequest

    engine = AnalyticsEngine()
    result = await engine.run(AnalysisRequest(
        analysis_type="comfort",
        data=sql_rows,
        schema={"temperature": "temperature", "humidity": "humidity"},
        options={"standard": "ashrae55"},
    ))
"""
from __future__ import annotations

import json
import math
import os
import statistics
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

_STANDARDS_DIR = Path(__file__).resolve().parent.parent / "data" / "standards"

# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisRequest:
    analysis_type: str                # "comfort","energy","iaq","occupancy","trend","compliance"
    data: List[Dict[str, Any]]        # list of row dicts (from SQL results)
    schema: Dict[str, str]            # column alias → actual column name
    unit: str = "metric"              # "metric" | "imperial"
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    analysis_type: str
    success: bool
    summary: str
    metrics: Dict[str, Any]
    violations: List[Dict]
    grade: Optional[str]              # A/B/C/D/F
    recommendations: List[str]
    formatted_response: str


# ─────────────────────────────────────────────────────────────────────────────
# Comfort Standards
# ─────────────────────────────────────────────────────────────────────────────

def _load_comfort_standards() -> Dict:
    """Load comfort standards from JSON; convert lists to tuples for range checks."""
    path = _STANDARDS_DIR / "comfort_standards.json"
    try:
        with open(path) as f:
            raw = json.load(f)
        standards = {}
        for key, cfg in raw.items():
            standards[key] = {
                k: tuple(v) for k, v in cfg.items()
                if isinstance(v, list) and len(v) == 2
            }
        return standards
    except Exception as e:
        logger.warning(f"Failed to load {path}, using built-in defaults: {e}")
        return {
            "ashrae55": {"temperature": (20.0, 26.0), "humidity": (30.0, 60.0), "co2": (0, 1000)},
            "well": {"temperature": (20.0, 25.5), "humidity": (30.0, 60.0), "co2": (0, 900), "pm25": (0, 15)},
            "en15251": {"temperature": (20.0, 26.0), "humidity": (25.0, 65.0), "co2": (0, 1200)},
        }

def _load_iaq_grades() -> List[Dict]:
    path = _STANDARDS_DIR / "iaq_grades.json"
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {path}, using built-in defaults: {e}")
        return [
            {"grade": "A", "co2_max": 800,  "pm25_max": 10,  "label": "Excellent"},
            {"grade": "B", "co2_max": 1000, "pm25_max": 15,  "label": "Good"},
            {"grade": "C", "co2_max": 1200, "pm25_max": 25,  "label": "Fair"},
            {"grade": "D", "co2_max": 1500, "pm25_max": 35,  "label": "Poor"},
            {"grade": "F", "co2_max": 9999, "pm25_max": 9999, "label": "Very Poor"},
        ]

COMFORT_STANDARDS = _load_comfort_standards()
IAQ_GRADES = _load_iaq_grades()

# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _extract_numeric(rows: List[Dict], col: str) -> List[float]:
    """Extract non-None numeric values for a column."""
    result = []
    for r in rows:
        val = r.get(col)
        if val is not None:
            try:
                result.append(float(val))
            except (TypeError, ValueError):
                pass
    return result


def _stats(values: List[float]) -> Dict:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None, "std": None, "median": None}
    return {
        "count":  len(values),
        "mean":   round(statistics.mean(values), 2),
        "min":    round(min(values), 2),
        "max":    round(max(values), 2),
        "std":    round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
        "median": round(statistics.median(values), 2),
    }


def _pct_in_range(values: List[float], lo: float, hi: float) -> float:
    if not values:
        return 0.0
    return round(sum(1 for v in values if lo <= v <= hi) / len(values) * 100, 1)


def _grade_from_pct(pct_ok: float) -> str:
    if pct_ok >= 95: return "A"
    if pct_ok >= 85: return "B"
    if pct_ok >= 75: return "C"
    if pct_ok >= 60: return "D"
    return "F"


# ─────────────────────────────────────────────────────────────────────────────
# Analysers
# ─────────────────────────────────────────────────────────────────────────────

class ComfortAnalyser:
    """ASHRAE 55 / WELL / EN 15251 thermal comfort analysis."""

    def run(self, req: AnalysisRequest) -> AnalysisResult:
        standard = req.options.get("standard", "ashrae55")
        bands = COMFORT_STANDARDS.get(standard, COMFORT_STANDARDS["ashrae55"])
        schema = req.schema
        data = req.data

        metrics: Dict[str, Any] = {}
        violations: List[Dict] = []
        overall_pcts: List[float] = []
        recommendations: List[str] = []

        for alias, (lo, hi) in bands.items():
            col = schema.get(alias, alias)
            vals = _extract_numeric(data, col)
            if not vals:
                continue
            s = _stats(vals)
            pct = _pct_in_range(vals, lo, hi)
            metrics[alias] = {**s, "pct_in_range": pct, "range": [lo, hi]}
            overall_pcts.append(pct)

            if pct < 95:
                n_out = int((100 - pct) * len(vals) / 100)
                severity = "high" if pct < 75 else "medium"
                violations.append({
                    "parameter": alias, "standard": standard,
                    "expected_range": [lo, hi],
                    "pct_in_range": pct, "n_violations": n_out,
                    "severity": severity,
                })
                if alias == "temperature":
                    if s["mean"] and s["mean"] > hi:
                        recommendations.append(f"Reduce cooling setpoint — avg {alias} {s['mean']}°C exceeds {hi}°C target.")
                    else:
                        recommendations.append(f"Increase heating setpoint — avg {alias} {s['mean']}°C below {lo}°C target.")
                elif alias == "humidity":
                    recommendations.append(f"Review humidification/dehumidification — avg RH {s['mean']}% outside {lo}-{hi}% range.")
                elif alias == "co2":
                    recommendations.append(f"Increase ventilation rate — avg CO₂ {s['mean']} ppm exceeds limit of {hi} ppm.")

        pct_ok = statistics.mean(overall_pcts) if overall_pcts else 0.0
        grade = _grade_from_pct(pct_ok)

        v_lines = ""
        if violations:
            v_lines = "\n\n**Violations detected:**\n" + "\n".join(
                f"  • {v['parameter'].title()}: {v['pct_in_range']}% in range "
                f"(expected ≥95%) — {v['n_violations']} readings out-of-range" for v in violations
            )

        r_lines = ""
        if recommendations:
            r_lines = "\n\n**Recommendations:**\n" + "\n".join(f"  • {r}" for r in recommendations)

        summary = (
            f"Comfort analysis ({standard.upper()}) — **Grade {grade}** "
            f"({pct_ok:.1f}% readings within comfort bands). "
            f"{len(violations)} parameter(s) failing."
        )

        return AnalysisResult(
            analysis_type="comfort",
            success=True,
            summary=summary,
            metrics=metrics,
            violations=violations,
            grade=grade,
            recommendations=recommendations,
            formatted_response=summary + v_lines + r_lines,
        )


class EnergyAnalyser:
    """Energy pattern analysis: peak, off-hours, EUI estimation."""

    BUSINESS_HOURS = (7, 19)  # 07:00–19:00 local time

    def run(self, req: AnalysisRequest) -> AnalysisResult:
        col = req.schema.get("energy", req.schema.get("value", "value"))
        vals = _extract_numeric(req.data, col)
        if not vals:
            return AnalysisResult("energy", False, "No energy data.", {}, [], None, [],
                                  "No energy data available.")

        s = _stats(vals)
        peak = max(vals)
        peak_idx = vals.index(peak)
        baseline = statistics.median(vals)
        peak_ratio = round(peak / baseline, 2) if baseline > 0 else None

        # Simple peak detection
        peaks = [v for v in vals if v > s["mean"] + 1.5 * (s["std"] or 0)]
        n_peaks = len(peaks)
        load_factor = round(s["mean"] / peak, 2) if peak > 0 else None

        recommendations = []
        if peak_ratio and peak_ratio > 2.0:
            recommendations.append(
                f"Peak demand is {peak_ratio}× baseline — consider demand response or load shifting."
            )
        if load_factor and load_factor < 0.6:
            recommendations.append(
                "Low load factor detected — consider rightsizing HVAC equipment."
            )

        grade = "A" if (n_peaks == 0 and (load_factor or 1) > 0.7) else \
                "B" if n_peaks <= 2 else "C" if n_peaks <= 5 else "D"

        summary = (
            f"Energy analysis — **Grade {grade}**. "
            f"Mean: {s['mean']}, Peak: {peak} ({n_peaks} peak events), "
            f"Load factor: {load_factor}."
        )
        rec_lines = "\n".join(f"  • {r}" for r in recommendations)
        return AnalysisResult(
            analysis_type="energy",
            success=True,
            summary=summary,
            metrics={**s, "peak": peak, "n_peaks": n_peaks, "load_factor": load_factor},
            violations=[],
            grade=grade,
            recommendations=recommendations,
            formatted_response=summary + (f"\n\n**Recommendations:**\n{rec_lines}" if rec_lines else ""),
        )


class AirQualityAnalyser:
    """IAQ grading: CO2, PM2.5, VOC."""

    def run(self, req: AnalysisRequest) -> AnalysisResult:
        schema = req.schema
        data = req.data
        metrics: Dict[str, Any] = {}

        co2_col  = schema.get("co2",  "co2")
        pm25_col = schema.get("pm25", "pm25")

        co2_vals  = _extract_numeric(data, co2_col)
        pm25_vals = _extract_numeric(data, pm25_col)

        co2_mean  = statistics.mean(co2_vals)  if co2_vals  else None
        pm25_mean = statistics.mean(pm25_vals) if pm25_vals else None

        if co2_vals:  metrics["co2"]  = _stats(co2_vals)
        if pm25_vals: metrics["pm25"] = _stats(pm25_vals)

        # Determine grade
        grade = "F"
        for band in IAQ_GRADES:
            co2_ok  = co2_mean  is None or co2_mean  <= band["co2_max"]
            pm25_ok = pm25_mean is None or pm25_mean <= band["pm25_max"]
            if co2_ok and pm25_ok:
                grade = band["grade"]
                break

        grade_label = next((b["label"] for b in IAQ_GRADES if b["grade"] == grade), "Unknown")

        recommendations = []
        if co2_mean and co2_mean > 1000:
            recommendations.append(f"CO₂ avg {co2_mean:.0f} ppm — increase fresh air ventilation by ≥20%.")
        if pm25_mean and pm25_mean > 15:
            recommendations.append(f"PM2.5 avg {pm25_mean:.1f} µg/m³ — upgrade filters to MERV-13 or higher.")

        summary = f"Indoor Air Quality — **Grade {grade}** ({grade_label})."
        if co2_mean:  summary += f" CO₂ avg: {co2_mean:.0f} ppm."
        if pm25_mean: summary += f" PM2.5 avg: {pm25_mean:.1f} µg/m³."

        return AnalysisResult(
            analysis_type="iaq",
            success=True,
            summary=summary,
            metrics=metrics,
            violations=[],
            grade=grade,
            recommendations=recommendations,
            formatted_response=summary + (
                "\n\n**Recommendations:**\n" + "\n".join(f"  • {r}" for r in recommendations)
                if recommendations else ""
            ),
        )


class TrendAnalyser:
    """Statistical trend analysis (Mann-Kendall + linear slope)."""

    def run(self, req: AnalysisRequest) -> AnalysisResult:
        col = req.schema.get("value", list(req.schema.values())[0] if req.schema else "value")
        vals = _extract_numeric(req.data, col)

        if len(vals) < 3:
            return AnalysisResult("trend", False, "Insufficient data for trend analysis.",
                                  {}, [], None, [],
                                  "Need at least 3 data points for trend analysis.")

        # Simple Mann-Kendall trend test (tau sign)
        concordant = discordant = 0
        n = len(vals)
        for i in range(n - 1):
            for j in range(i + 1, n):
                diff = vals[j] - vals[i]
                if diff > 0: concordant += 1
                elif diff < 0: discordant += 1

        tau = (concordant - discordant) / (n * (n - 1) / 2)

        # Linear slope (least squares)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(vals)
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(vals))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0.0

        if abs(tau) < 0.1:
            trend_dir, trend_strength = "stable", "no"
        elif tau > 0:
            trend_dir = "increasing"
            trend_strength = "strong" if tau > 0.5 else "moderate" if tau > 0.3 else "weak"
        else:
            trend_dir = "decreasing"
            trend_strength = "strong" if tau < -0.5 else "moderate" if tau < -0.3 else "weak"

        unit = req.options.get("unit_label", "units")
        summary = (
            f"Trend analysis: **{trend_strength.capitalize()} {trend_dir}** trend detected "
            f"(Mann-Kendall τ={tau:.3f}, slope={slope:+.4f} {unit}/step)."
        )

        return AnalysisResult(
            analysis_type="trend",
            success=True,
            summary=summary,
            metrics={"tau": round(tau, 4), "slope": round(slope, 6),
                     "direction": trend_dir, "strength": trend_strength,
                     "n_points": n, **_stats(vals)},
            violations=[],
            grade=None,
            recommendations=([
                f"Values are {trend_dir} at {abs(slope):.3f} per interval. Consider scheduled maintenance review."
            ] if trend_strength in ("moderate", "strong") else []),
            formatted_response=summary,
        )


class ComplianceChecker:
    """
    Multi-standard compliance checker producing PhD-level analysis reports.

    For each measured parameter the checker computes full descriptive statistics
    (mean, median, σ, min, max, percentiles) and evaluates:
      • % of readings within the standard's threshold band
      • Magnitude and direction of violations
      • Severity tier (critical / moderate / borderline)
      • Recommended corrective actions with normative references

    Supported standards (auto-selected when data is available):
      ASHRAE 55-2023   — operative temperature & humidity
      ASHRAE 62.1-2022 — ventilation / CO₂ / PM2.5 / VOC
      WELL v2          — holistic IEQ (temperature, humidity, CO₂, PM, VOC, illuminance)
      EN 16798-1:2019  — European IEQ categories I–III
      BREEAM 2018      — Hea 02 (IAQ) + Hea 04 (thermal comfort)
      CIBSE Guide A    — UK thermal comfort guidance
    """

    # Severity thresholds (% of readings out-of-range)
    _CRITICAL_PCT  = 25.0   # >25% out → critical
    _MODERATE_PCT  =  5.0   # 5-25%   → moderate
    # <5% out → borderline (still flagged but minor)

    # Standard-name aliases for the StandardsEngine
    _STD_MAP = {
        "ashrae55":   "ashrae55",
        "ashrae":     "ashrae55",
        "ashrae 55":  "ashrae55",
        "ashrae62":   "ashrae621",
        "ashrae 62":  "ashrae621",
        "ashrae621":  "ashrae621",
        "well":       "well_v2",
        "well_v2":    "well_v2",
        "breeam":     "breeam",
        "en15251":    "en15251",
        "en16798":    "en15251",
        "cibse":      "cibse_kg2",
        "iso50001":   "iso50001",
    }

    # Column-name → StandardsEngine parameter key
    _COL_PARAM_MAP = [
        ({"temperature", "temp", "air_temp", "temp_c", "air_temperature"},        "temp_c"),
        ({"humidity", "rh", "relative_humidity", "humidity_rh"},                   "humidity_rh"),
        ({"co2", "co2_ppm", "carbon_dioxide"},                                     "co2_ppm"),
        ({"pm25", "pm2_5", "pm25_ugm3", "particulate"},                            "pm25_ugm3"),
        ({"tvoc", "voc", "tvoc_ppb", "total_voc"},                                 "tvoc_ppb"),
        ({"illuminance", "lux", "illuminance_lux"},                                "illuminance_lux"),
        ({"eui", "eui_kwh_m2_year", "energy_use_intensity"},                       "eui_kwh_m2_year"),
    ]

    def _map_schema_to_readings(
        self, data: List[Dict], schema: Dict[str, str]
    ) -> Dict[str, Dict]:
        """
        Return a dict of {param_key: {"values": [...], "col": col_name}} for
        every parameter we can find in the data.
        """
        found: Dict[str, Dict] = {}
        all_cols = set()
        if data:
            all_cols = {k.lower() for k in data[0].keys()}

        for aliases, param_key in self._COL_PARAM_MAP:
            # Look in schema first, then directly in column names
            matched_col = None
            for alias in aliases:
                if alias in schema:
                    matched_col = schema[alias]
                    break
            if not matched_col:
                for col in all_cols:
                    if col in aliases or any(a in col for a in aliases):
                        matched_col = col
                        break
            if matched_col:
                vals = _extract_numeric(data, matched_col)
                if vals:
                    found[param_key] = {"values": vals, "col": matched_col}
        return found

    def _stats_extended(self, vals: List[float]) -> Dict[str, Any]:
        """Descriptive statistics for a parameter series."""
        n = len(vals)
        mean_ = statistics.mean(vals)
        median_ = statistics.median(vals)
        stdev_ = statistics.pstdev(vals) if n > 1 else 0.0
        sorted_v = sorted(vals)
        p5  = sorted_v[max(0, int(0.05 * n))]
        p25 = sorted_v[max(0, int(0.25 * n))]
        p75 = sorted_v[min(n - 1, int(0.75 * n))]
        p95 = sorted_v[min(n - 1, int(0.95 * n))]
        return {
            "n": n, "mean": round(mean_, 2), "median": round(median_, 2),
            "stdev": round(stdev_, 2),
            "min": round(min(vals), 2), "max": round(max(vals), 2),
            "p5": round(p5, 2), "p25": round(p25, 2),
            "p75": round(p75, 2), "p95": round(p95, 2),
        }

    def _pct_outside(self, vals: List[float], lo: Optional[float], hi: Optional[float]) -> float:
        outside = sum(
            1 for v in vals
            if (hi is not None and v > hi) or (lo is not None and v < lo)
        )
        return round(outside / len(vals) * 100, 1) if vals else 0.0

    def _severity(self, pct_outside: float) -> str:
        if pct_outside >= self._CRITICAL_PCT:
            return "CRITICAL"
        if pct_outside >= self._MODERATE_PCT:
            return "MODERATE"
        return "BORDERLINE"

    def run(self, req: AnalysisRequest) -> AnalysisResult:
        from orchestrator.services.standards_engine import get_standards_engine

        engine      = get_standards_engine()
        data        = req.data
        schema      = req.schema
        param_data  = self._map_schema_to_readings(data, schema)

        if not param_data:
            return AnalysisResult(
                analysis_type="compliance",
                success=False,
                summary="Insufficient sensor data for compliance analysis.",
                metrics={}, violations=[], grade=None, recommendations=[],
                formatted_response=(
                    "**Compliance Analysis — Insufficient Data**\n\n"
                    "No measurable environmental parameters (temperature, humidity, CO₂, etc.) "
                    "were found in the current dataset. Please ensure sensor data is available "
                    "for the selected zone and time period."
                ),
            )

        # ── Determine applicable standards from available parameters ──────────
        standards_to_run: List[str] = req.options.get("standards", [])
        if not standards_to_run:
            # Auto-select standards based on available parameters
            if "temp_c" in param_data or "humidity_rh" in param_data:
                standards_to_run += ["ashrae55", "well_v2", "en15251", "breeam"]
            if "co2_ppm" in param_data or "pm25_ugm3" in param_data or "tvoc_ppb" in param_data:
                standards_to_run += ["ashrae621", "well_v2", "breeam"]
            # Deduplicate while preserving order
            seen = set()
            standards_to_run = [s for s in standards_to_run if not (s in seen or seen.add(s))]

        if not standards_to_run:
            standards_to_run = ["ashrae55"]

        # ── Per-parameter descriptive statistics ──────────────────────────────
        param_stats: Dict[str, Dict] = {
            p: self._stats_extended(d["values"]) for p, d in param_data.items()
        }

        # Build a "snapshot" reading using the mean of each parameter for the
        # StandardsEngine point-in-time check
        snapshot: Dict[str, float] = {p: param_stats[p]["mean"] for p in param_stats}

        # ── Run StandardsEngine for each applicable standard ──────────────────
        std_results: List[Dict] = []
        all_violations: List[Dict] = []
        all_recs: List[str] = []

        for std_id in standards_to_run:
            eng_id = self._STD_MAP.get(std_id.lower().replace(" ", ""), std_id)
            check = engine.check(eng_id, snapshot)
            if "error" in check:
                continue

            std_violations = [c for c in check.get("checks", []) if c["status"] != "compliant"]
            std_pass = check.get("overall_status") in ("compliant", "borderline")

            # Enrich with time-series statistics
            enriched_checks = []
            for c in check.get("checks", []):
                param = c["parameter"]
                ts = param_stats.get(param, {})
                thr = c.get("threshold", {})
                lo = thr.get("min")
                hi = thr.get("max")
                vals = param_data.get(param, {}).get("values", [])
                pct_out = self._pct_outside(vals, lo, hi) if vals else None
                severity = self._severity(pct_out) if pct_out is not None and pct_out > 0 else None
                enriched_checks.append({
                    **c,
                    "statistics": ts,
                    "pct_outside_threshold": pct_out,
                    "severity": severity,
                })
                if pct_out is not None and pct_out > 0:
                    all_violations.append({
                        **c,
                        "standard_id": eng_id,
                        "pct_outside": pct_out,
                        "severity": severity,
                        "statistics": ts,
                    })

            std_results.append({
                "standard_id":     eng_id,
                "standard_name":   check.get("standard"),
                "overall_status":  check.get("overall_status"),
                "compliance_score": check.get("compliance_score"),
                "references":      check.get("references", []),
                "checks":          enriched_checks,
                "violations_count": len(std_violations),
            })

            # Recommendations
            for c in enriched_checks:
                if c["status"] != "compliant":
                    lo = c["threshold"].get("min")
                    hi = c["threshold"].get("max")
                    val = c["value"]
                    unit = c["unit"]
                    label = c["label"]
                    refs = ", ".join(check.get("references", []))
                    if hi is not None and val > hi:
                        all_recs.append(
                            f"**{label}** ({val}{unit}) exceeds the {check['standard']} "
                            f"maximum of {hi}{unit} — reduce by {round(val - hi, 2)}{unit}. "
                            f"[{refs}]"
                        )
                    elif lo is not None and val < lo:
                        all_recs.append(
                            f"**{label}** ({val}{unit}) is below the {check['standard']} "
                            f"minimum of {lo}{unit} — increase by {round(lo - val, 2)}{unit}. "
                            f"[{refs}]"
                        )

        # Deduplicate recommendations
        all_recs = list(dict.fromkeys(all_recs))

        # ── Overall grade ─────────────────────────────────────────────────────
        critical_viol = sum(1 for v in all_violations if v.get("severity") == "CRITICAL")
        moderate_viol = sum(1 for v in all_violations if v.get("severity") == "MODERATE")
        if critical_viol > 0:
            overall_grade = "F" if critical_viol >= 3 else "D"
        elif moderate_viol > 0:
            overall_grade = "C"
        elif all_violations:
            overall_grade = "B"
        else:
            overall_grade = "A"

        passing_stds = [r for r in std_results if r["overall_status"] == "compliant"]
        borderline_stds = [r for r in std_results if r["overall_status"] == "borderline"]
        failing_stds = [r for r in std_results if r["overall_status"] == "non_compliant"]

        # ── Build PhD-level markdown report ───────────────────────────────────
        n_samples = max((param_stats.get(p, {}).get("n", 0) for p in param_stats), default=0)
        report_lines: List[str] = []

        # Header
        report_lines += [
            "## Indoor Environmental Quality (IEQ) Compliance Report",
            "",
            f"**Overall Compliance Grade: {overall_grade}**  ",
            f"Standards assessed: {len(std_results)}  |  "
            f"Passing: {len(passing_stds)}  |  "
            f"Borderline: {len(borderline_stds)}  |  "
            f"Failing: {len(failing_stds)}  ",
            f"Dataset: {n_samples:,} sensor readings  |  "
            f"Parameters: {', '.join(param_stats.keys())}",
            "",
        ]

        # Executive summary
        if not all_violations:
            exec_summary = (
                "All measured environmental parameters are within the required thresholds "
                "across all assessed standards. The zone demonstrates full IEQ compliance."
            )
        else:
            exec_summary = (
                f"Analysis identified {len(all_violations)} parameter–standard violation(s) "
                f"({critical_viol} critical, {moderate_viol} moderate). "
                f"Corrective action is recommended to restore compliant conditions."
            )
        report_lines += ["### Executive Summary", "", exec_summary, ""]

        # Descriptive statistics table
        report_lines += ["### Measured Parameters — Descriptive Statistics", ""]
        report_lines += ["| Parameter | n | Mean | Median | σ | Min | Max | P5 | P95 | Unit |"]
        report_lines += ["|-----------|---|------|--------|---|-----|-----|----|-----|------|"]
        _PARAM_UNITS = {
            "temp_c": "°C", "humidity_rh": "%RH", "co2_ppm": "ppm",
            "pm25_ugm3": "µg/m³", "tvoc_ppb": "ppb", "illuminance_lux": "lux",
        }
        for p, s in param_stats.items():
            unit = _PARAM_UNITS.get(p, "")
            report_lines.append(
                f"| {p} | {s['n']} | {s['mean']} | {s['median']} | {s['stdev']} "
                f"| {s['min']} | {s['max']} | {s['p5']} | {s['p95']} | {unit} |"
            )
        report_lines += [""]

        # Per-standard results
        report_lines += ["### Compliance Assessment by Standard", ""]
        for r in std_results:
            status_icon = "✅" if r["overall_status"] == "compliant" else (
                "⚠️" if r["overall_status"] == "borderline" else "❌"
            )
            score_pct = round(r["compliance_score"] * 100, 1)
            report_lines += [
                f"#### {status_icon} {r['standard_name']}",
                f"Score: **{score_pct}%** compliant  |  Status: **{r['overall_status'].replace('_', ' ').title()}**",
                "",
            ]
            if r["checks"]:
                report_lines += ["| Parameter | Value | Threshold | Status | % Outside | Severity |"]
                report_lines += ["|-----------|-------|-----------|--------|-----------|----------|"]
                for c in r["checks"]:
                    thr = c["threshold"]
                    lo = thr.get("min", "—")
                    hi = thr.get("max", "—")
                    thr_str = f"{lo}–{hi} {c['unit']}" if lo != "—" and hi != "—" else (
                        f"≤{hi} {c['unit']}" if hi != "—" else f"≥{lo} {c['unit']}"
                    )
                    pct_out = c.get("pct_outside_threshold")
                    pct_str = f"{pct_out}%" if pct_out is not None else "—"
                    sev = c.get("severity") or "—"
                    st_icon = "✅" if c["status"] == "compliant" else (
                        "⚠️" if c["status"] == "borderline" else "❌"
                    )
                    report_lines.append(
                        f"| {c['label']} | {c['value']}{c['unit']} | {thr_str} "
                        f"| {st_icon} {c['status'].replace('_', ' ').title()} "
                        f"| {pct_str} | {sev} |"
                    )
            refs = "  ".join(f"`{r_}`" for r_ in r["references"])
            if refs:
                report_lines += ["", f"*References: {refs}*"]
            report_lines += [""]

        # Violations summary
        if all_violations:
            report_lines += ["### Violations Detail", ""]
            by_sev: Dict[str, List] = {"CRITICAL": [], "MODERATE": [], "BORDERLINE": []}
            for v in all_violations:
                by_sev.setdefault(v.get("severity", "BORDERLINE"), []).append(v)
            for sev, vlist in by_sev.items():
                if vlist:
                    icon = "🔴" if sev == "CRITICAL" else ("🟡" if sev == "MODERATE" else "🔵")
                    report_lines += [f"**{icon} {sev}**"]
                    for v in vlist:
                        lo = v["threshold"].get("min")
                        hi = v["threshold"].get("max")
                        val = v["value"]
                        unit = v["unit"]
                        direction = (
                            f"{round(val - hi, 2)}{unit} above limit" if hi and val > hi else
                            f"{round(lo - val, 2)}{unit} below minimum" if lo and val < lo else "out of range"
                        )
                        stats_ = v.get("statistics", {})
                        report_lines.append(
                            f"- **{v['label']}** [{v['standard_id'].upper()}]: "
                            f"mean {val}{unit} ({direction}), "
                            f"{v.get('pct_outside', 0):.1f}% of readings outside threshold "
                            f"(σ={stats_.get('stdev', '—')}{unit})"
                        )
                    report_lines += [""]

        # Recommendations
        if all_recs:
            report_lines += ["### Corrective Action Recommendations", ""]
            for i, rec in enumerate(all_recs, 1):
                report_lines.append(f"{i}. {rec}")
            report_lines += [""]

        # Normative references
        all_refs = []
        for r in std_results:
            all_refs.extend(r.get("references", []))
        unique_refs = list(dict.fromkeys(all_refs))
        if unique_refs:
            report_lines += ["### Normative References", ""]
            for ref in unique_refs:
                report_lines.append(f"- {ref}")

        formatted = "\n".join(report_lines)
        summary = (
            f"IEQ Compliance Grade **{overall_grade}** — "
            f"{len(passing_stds)}/{len(std_results)} standards passing, "
            f"{len(all_violations)} violation(s) detected "
            f"({critical_viol} critical, {moderate_viol} moderate)."
        )

        return AnalysisResult(
            analysis_type="compliance",
            success=True,
            summary=summary,
            metrics={
                "standards_checked": std_results,
                "parameter_statistics": param_stats,
                "violation_count": len(all_violations),
                "critical_violations": critical_viol,
                "moderate_violations": moderate_viol,
            },
            violations=all_violations,
            grade=overall_grade,
            recommendations=all_recs,
            formatted_response=formatted,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main AnalyticsEngine
# ─────────────────────────────────────────────────────────────────────────────

class AnalyticsEngine:
    """
    Dispatcher for deterministic analytics modules.
    Maps analysis_type strings to analyser classes.
    """

    _ANALYSERS = {
        "comfort":    ComfortAnalyser,
        "energy":     EnergyAnalyser,
        "iaq":        AirQualityAnalyser,
        "air_quality":AirQualityAnalyser,
        "trend":      TrendAnalyser,
        "compliance": ComplianceChecker,
    }

    async def run(self, req: AnalysisRequest) -> AnalysisResult:
        """Dispatch request to the appropriate analyser."""
        analyser_cls = self._ANALYSERS.get(req.analysis_type)
        if not analyser_cls:
            return AnalysisResult(
                analysis_type=req.analysis_type,
                success=False,
                summary=f"Unknown analysis type: {req.analysis_type!r}",
                metrics={},
                violations=[],
                grade=None,
                recommendations=[],
                formatted_response=(
                    f"Analysis type '{req.analysis_type}' not supported. "
                    f"Available: {', '.join(self._ANALYSERS.keys())}."
                ),
            )

        try:
            analyser = analyser_cls()
            result = analyser.run(req)
            logger.info(f"Analytics [{req.analysis_type}]: grade={result.grade}, "
                        f"violations={len(result.violations)}")
            return result
        except Exception as e:
            logger.error(f"Analytics [{req.analysis_type}] failed: {e}", exc_info=True)
            return AnalysisResult(
                analysis_type=req.analysis_type,
                success=False,
                summary=f"Analysis failed: {e}",
                metrics={},
                violations=[],
                grade=None,
                recommendations=[],
                formatted_response="An error occurred during analytics computation.",
            )

    def available_types(self) -> List[str]:
        return list(self._ANALYSERS.keys())
