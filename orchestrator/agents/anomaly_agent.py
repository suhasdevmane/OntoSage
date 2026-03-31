"""
AnomalyDetectionAgent — Phase 4.7 (Anomaly Detection Intent)
=============================================================
Detects statistical and threshold-based anomalies in sensor time-series data.

Strategies:
  1. Threshold-based: compare against comfort range bounds (comfort_ranges dict)
  2. Z-score statistical: flag values > N standard deviations from mean
  3. Spike detection: flag values that jump > X% from previous reading

Usage:
    from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent
    agent = AnomalyDetectionAgent()
    result = await agent.detect(state, user_query, sensor_data=sql_result)
"""
import sys
sys.path.append('/app')

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from shared.config import settings
from shared.constants import COMFORT_RANGES as DEFAULT_COMFORT_RANGES, Z_SCORE_THRESHOLD, SPIKE_PCT_THRESHOLD
from shared.models import ConversationState
from shared.utils import get_logger
from orchestrator.llm_manager import llm_manager

logger = get_logger(__name__)


class AnomalyDetectionAgent:
    """
    Phase 4.7: Multi-strategy anomaly detection on sensor time-series data.
    """

    def __init__(self, comfort_ranges: Optional[Dict] = None, z_threshold: float = Z_SCORE_THRESHOLD):
        self.comfort_ranges = comfort_ranges or DEFAULT_COMFORT_RANGES
        self.z_threshold = z_threshold

    async def detect(
        self,
        state: ConversationState,
        user_query: str,
        sensor_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run all anomaly detection strategies and return a structured report.

        Returns:
            success: bool
            anomalies: List[dict]  — each has: column, value, timestamp, type, severity, message
            summary: str           — natural-language summary
            formatted_response: str
        """
        logger.info("=" * 70)
        logger.info("🚨 ANOMALY DETECTION AGENT: Running detection")
        logger.info("=" * 70)

        records = self._extract_records(sensor_data)
        if not records:
            return {
                "success": False,
                "anomalies": [],
                "formatted_response": "No sensor data available for anomaly detection.",
            }

        logger.info(f"Analyzing {len(records)} records...")

        # Run all strategies
        threshold_anomalies = self._threshold_detection(records)
        zscore_anomalies = self._zscore_detection(records)
        spike_anomalies = self._spike_detection(records)

        # Merge and deduplicate
        all_anomalies = self._merge_anomalies(threshold_anomalies, zscore_anomalies, spike_anomalies)

        # Severity summary
        high = [a for a in all_anomalies if a["severity"] == "high"]
        medium = [a for a in all_anomalies if a["severity"] == "medium"]

        logger.info(f"Detected {len(all_anomalies)} anomalies ({len(high)} high, {len(medium)} medium)")

        # LLM summary
        formatted = await self._generate_summary(user_query, all_anomalies, len(records))

        return {
            "success": True,
            "anomaly_count": len(all_anomalies),
            "high_severity": len(high),
            "medium_severity": len(medium),
            "anomalies": all_anomalies[:100],  # cap for response size
            "formatted_response": formatted,
            "data": all_anomalies[:100],       # for DataExportAgent compatibility
        }

    # ------------------------------------------------------------------
    # Strategy 1: Threshold-based
    # ------------------------------------------------------------------

    def _threshold_detection(self, records: List[Dict]) -> List[Dict]:
        anomalies = []
        for row in records:
            ts = row.get("Datetime") or row.get("timestamp") or row.get("time") or ""
            for col, val in row.items():
                if not isinstance(val, (int, float)):
                    continue
                for sensor_kw, bounds in self.comfort_ranges.items():
                    if sensor_kw.lower() in col.lower():
                        lo, hi = bounds["min"], bounds["max"]
                        if val < lo or val > hi:
                            deviation = max(abs(val - lo) / (hi - lo), abs(val - hi) / (hi - lo))
                            severity = "high" if deviation > 0.5 else "medium"
                            anomalies.append({
                                "column": col,
                                "value": round(val, 3),
                                "unit": bounds["unit"],
                                "timestamp": str(ts),
                                "type": "threshold",
                                "severity": severity,
                                "message": f"{col}={val}{bounds['unit']} is outside safe range [{lo}, {hi}]",
                            })
        return anomalies

    # ------------------------------------------------------------------
    # Strategy 2: Z-score (statistical)
    # ------------------------------------------------------------------

    def _zscore_detection(self, records: List[Dict]) -> List[Dict]:
        # Collect per-column numeric series
        series: Dict[str, List[Tuple[float, Any]]] = {}
        for row in records:
            ts = row.get("Datetime") or row.get("timestamp") or ""
            for col, val in row.items():
                if isinstance(val, (int, float)):
                    series.setdefault(col, []).append((val, ts))

        anomalies = []
        for col, pts in series.items():
            if len(pts) < 5:
                continue
            vals = [p[0] for p in pts]
            mean = sum(vals) / len(vals)
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            if std < 1e-9:
                continue
            for val, ts in pts:
                z = abs(val - mean) / std
                if z > self.z_threshold:
                    anomalies.append({
                        "column": col,
                        "value": round(val, 3),
                        "unit": "",
                        "timestamp": str(ts),
                        "type": "z-score",
                        "z_score": round(z, 2),
                        "severity": "high" if z > self.z_threshold * 1.5 else "medium",
                        "message": f"{col}={val} is {z:.1f}σ from mean ({mean:.2f})",
                    })
        return anomalies

    # ------------------------------------------------------------------
    # Strategy 3: Spike detection
    # ------------------------------------------------------------------

    def _spike_detection(self, records: List[Dict]) -> List[Dict]:
        anomalies = []
        prev: Dict[str, float] = {}
        for row in records:
            ts = row.get("Datetime") or row.get("timestamp") or ""
            for col, val in row.items():
                if not isinstance(val, (int, float)):
                    continue
                if col in prev and prev[col] != 0:
                    pct_change = abs((val - prev[col]) / prev[col])
                    if pct_change > SPIKE_PCT_THRESHOLD:
                        anomalies.append({
                            "column": col,
                            "value": round(val, 3),
                            "prev_value": round(prev[col], 3),
                            "unit": "",
                            "timestamp": str(ts),
                            "type": "spike",
                            "pct_change": round(pct_change * 100, 1),
                            "severity": "high" if pct_change > 0.75 else "medium",
                            "message": f"{col} spiked {pct_change*100:.0f}% ({prev[col]} → {val})",
                        })
                prev[col] = val
        return anomalies

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def _merge_anomalies(self, *lists) -> List[Dict]:
        """Deduplicate anomalies by (column, timestamp, type)."""
        seen = set()
        merged = []
        for lst in lists:
            for a in lst:
                key = (a.get("column"), a.get("timestamp"), a.get("type"))
                if key not in seen:
                    seen.add(key)
                    merged.append(a)
        # Sort by severity (high first)
        merged.sort(key=lambda x: 0 if x["severity"] == "high" else 1)
        return merged

    # ------------------------------------------------------------------
    # LLM summary
    # ------------------------------------------------------------------

    async def _generate_summary(
        self, user_query: str, anomalies: List[Dict], total_records: int
    ) -> str:
        if not anomalies:
            return f"✅ No anomalies detected across {total_records} sensor readings. All values are within acceptable ranges."

        top = anomalies[:10]
        prompt = f"""Summarize the following sensor anomalies in a building management context.

User Query: "{user_query}"
Total Records Analyzed: {total_records}
Anomalies Found: {len(anomalies)} ({sum(1 for a in anomalies if a['severity']=='high')} high severity)

Top Anomalies:
{chr(10).join(f"  • {a['message']} [{a['type']}] — {a['severity'].upper()} severity" for a in top)}

Provide:
1. A 2-sentence executive summary of the anomaly situation
2. The most critical issue and recommended action
3. Whether this requires immediate attention (yes/no and why)

Be concise and actionable."""
        try:
            return await llm_manager.generate(prompt, temperature=0.2)
        except Exception as e:
            logger.warning(f"Anomaly summary LLM failed: {e}")
            lines = [f"⚠️ {len(anomalies)} anomalies detected in {total_records} readings:"]
            for a in top:
                lines.append(f"  • [{a['severity'].upper()}] {a['message']}")
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _extract_records(self, sensor_data: Optional[Dict]) -> List[Dict]:
        if not sensor_data:
            return []
        if isinstance(sensor_data, list):
            return [r for r in sensor_data if isinstance(r, dict)]
        if isinstance(sensor_data, dict):
            data = sensor_data.get("data") or sensor_data.get("results") or []
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
        return []
