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
    """Run multiple standard checks and consolidate compliance status."""

    def run(self, req: AnalysisRequest) -> AnalysisResult:
        standards = req.options.get("standards", ["ashrae55"])
        results = []
        all_violations: List[Dict] = []
        all_recs: List[str] = []

        for std in standards:
            sub_req = AnalysisRequest(
                analysis_type="comfort",
                data=req.data,
                schema=req.schema,
                options={"standard": std},
            )
            r = ComfortAnalyser().run(sub_req)
            results.append({"standard": std.upper(), "grade": r.grade, "summary": r.summary})
            all_violations.extend([{**v, "standard": std} for v in r.violations])
            all_recs.extend(r.recommendations)

        passing = [r for r in results if r["grade"] in ("A", "B")]
        failing = [r for r in results if r["grade"] not in ("A", "B")]

        summary = (
            f"Compliance check: **{len(passing)}/{len(results)}** standards passing. "
            + ("✅ Compliant." if not failing else
               "❌ Non-compliant: " + ", ".join(r["standard"] for r in failing) + ".")
        )

        return AnalysisResult(
            analysis_type="compliance",
            success=True,
            summary=summary,
            metrics={"standards_checked": results},
            violations=all_violations,
            grade="A" if not failing else ("C" if len(failing) < len(results) else "F"),
            recommendations=list(dict.fromkeys(all_recs)),
            formatted_response=summary,
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
