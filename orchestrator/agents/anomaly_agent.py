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

sys.path.append("/app")

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from orchestrator.llm_manager import llm_manager
from shared.config import settings
from shared.constants import COMFORT_RANGES as DEFAULT_COMFORT_RANGES
from shared.constants import SPIKE_PCT_THRESHOLD, Z_SCORE_THRESHOLD
from shared.models import ConversationState
from shared.utils import get_logger

logger = get_logger(__name__)


class AnomalyDetectionAgent:
    """
    Phase 4.7: Multi-strategy anomaly detection on sensor time-series data.
    """

    def __init__(
        self, comfort_ranges: Optional[Dict] = None, z_threshold: float = Z_SCORE_THRESHOLD
    ):
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
            # THE READER IS NOT THE DETECTOR (CAVEAT-396, and BUG-1298 for why it is here).
            #
            # "No sensor data available for anomaly detection" describes this method's input.
            # To a reader it reads as an outage to wait out, and it was returned for a
            # building holding 514 live occupancy series — four times in ten asks of "which
            # areas are currently overcrowded?".
            #
            # `_anomaly_node` already rewrites this when NOTHING resolved, and that fix is
            # sound. It is not reached on the planner's path: `planner_agent._run_anomaly`
            # calls this agent directly, so neither that rewrite nor BUG-395's `too_broad`
            # check runs, and the internal sentence went straight to the user. The default
            # itself therefore has to be honest about what it does and does not establish.
            return {
                "success": False,
                "anomalies": [],
                "declined_reason": "no_rows_retrieved",
                "formatted_response": (
                    "I could not retrieve any readings for this question, so there is "
                    "nothing to check for anomalies.\n\n"
                    "_That is a statement about this query, not about the building: it does "
                    "not mean the sensors are missing or that their readings are not "
                    "collected — neither follows from an empty result._"
                ),
            }

        logger.info(f"Analyzing {len(records)} records...")

        # Run all strategies
        threshold_anomalies = self._threshold_detection(records)
        zscore_anomalies = self._zscore_detection(records)
        spike_anomalies = self._spike_detection(records)

        # Merge and deduplicate
        all_anomalies = self._merge_anomalies(
            threshold_anomalies, zscore_anomalies, spike_anomalies
        )

        # Severity summary
        high = [a for a in all_anomalies if a["severity"] == "high"]
        medium = [a for a in all_anomalies if a["severity"] == "medium"]

        logger.info(
            f"Detected {len(all_anomalies)} anomalies ({len(high)} high, {len(medium)} medium)"
        )

        # LLM summary
        formatted = await self._generate_summary(user_query, all_anomalies, len(records))

        return {
            "success": True,
            "anomaly_count": len(all_anomalies),
            "high_severity": len(high),
            "medium_severity": len(medium),
            "anomalies": all_anomalies[:100],  # cap for response size
            "formatted_response": formatted,
            "data": all_anomalies[:100],  # for DataExportAgent compatibility
        }

    # ------------------------------------------------------------------
    # Strategy 1: Threshold-based
    # ------------------------------------------------------------------

    @staticmethod
    def _level_counts(records: List[Dict]) -> Dict[str, int]:
        """How many distinct numeric values each column takes, over the records given.

        Keyed on the SIGNAL rather than a modality name, the way CAVEAT-405 keyed the sweep's
        spike detector: a building whose binary points are called something else is covered
        without a literal.
        """
        levels: Dict[str, set] = {}
        for row in records:
            for col, val in row.items():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    seen = levels.setdefault(col, set())
                    if len(seen) <= 3:  # only the first few matter; stop growing the set
                        seen.add(float(val))
        return {col: len(vals) for col, vals in levels.items()}

    def _threshold_detection(self, records: List[Dict]) -> List[Dict]:
        levels = self._level_counts(records)
        anomalies = []
        for row in records:
            ts = row.get("Datetime") or row.get("timestamp") or row.get("time") or ""
            for col, val in row.items():
                if not isinstance(val, (int, float)):
                    continue
                for sensor_kw, bounds in self.comfort_ranges.items():
                    if sensor_kw.lower() in col.lower():
                        # A BAND DECLARED `binary` CAN ONLY FIRE WHEN IT DOES NOT APPLY
                        # (BUG-1298). `occupancy: {min 0, max 1, unit "binary"}` was applied
                        # to bldg1's occupancy series, which are people COUNTS reaching 21 --
                        # so every ordinary reading above 1 became a HIGH-severity anomaly
                        # whose message said "outside safe range", and the narrator read 17 of
                        # them as "severe overcrowding ... fire-code violations". A genuinely
                        # binary point never leaves [0, 1], so this bound had no true positive
                        # to lose: it fired only on series it was the wrong bound for. Skipped
                        # on the evidence of the signal, not on the modality's name.
                        if str(bounds.get("unit", "")).lower() == "binary" and (
                            levels.get(col, 0) > 2
                        ):
                            continue
                        lo, hi = bounds["min"], bounds["max"]
                        if val < lo or val > hi:
                            deviation = max(abs(val - lo) / (hi - lo), abs(val - hi) / (hi - lo))
                            severity = "high" if deviation > 0.5 else "medium"
                            anomalies.append(
                                {
                                    "column": col,
                                    "value": round(val, 3),
                                    "unit": bounds["unit"],
                                    "timestamp": str(ts),
                                    "type": "threshold",
                                    "severity": severity,
                                    # "safe" was the word that licensed the safety claim, and
                                    # COMFORT_RANGES is a comfort band, not a safety limit.
                                    "message": (
                                        f"{col}={val}{bounds['unit']} is outside the "
                                        f"configured comfort range [{lo}, {hi}]"
                                    ),
                                }
                            )
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
                    anomalies.append(
                        {
                            "column": col,
                            "value": round(val, 3),
                            "unit": "",
                            "timestamp": str(ts),
                            "type": "z-score",
                            "z_score": round(z, 2),
                            "severity": "high" if z > self.z_threshold * 1.5 else "medium",
                            "message": f"{col}={val} is {z:.1f}σ from mean ({mean:.2f})",
                        }
                    )
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
                        anomalies.append(
                            {
                                "column": col,
                                "value": round(val, 3),
                                "prev_value": round(prev[col], 3),
                                "unit": "",
                                "timestamp": str(ts),
                                "type": "spike",
                                "pct_change": round(pct_change * 100, 1),
                                "direction": "rose" if val > prev[col] else "fell",
                                "severity": "high" if pct_change > 0.75 else "medium",
                                # A FALL IS NOT A SPIKE. `pct_change` is an absolute value, so
                                # 12.0 -> 1.0 was narrated as "a dramatic 92% spike", which the
                                # model then read as "a real crowd surge" -- of a reading that
                                # had DROPPED (BUG-1298).
                                "message": (
                                    f"{col} {'rose' if val > prev[col] else 'fell'} "
                                    f"{pct_change*100:.0f}% ({prev[col]} → {val})"
                                ),
                            }
                        )
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
        from orchestrator.services.anomaly.narration_guard import factual_summary, guard

        if not anomalies:
            return f"✅ No anomalies detected across {total_records} sensor readings. All values are within acceptable ranges."

        top = anomalies[:10]
        # THE PROMPT ASKED FOR THE SENTENCE THAT WENT WRONG (BUG-1298). Its three requests
        # were an executive summary, "the most critical issue and recommended action", and
        # "whether this requires immediate attention (yes/no and why)" -- with no rules at
        # all, where the report lane's prompt carries six. What came back was
        # "immediately activate the building's crowd-control protocol ... alert security ...
        # Yes", about "a monitored zone", from a z-score. The rules below are the request;
        # `guard()` below them is the part that cannot be declined.
        prompt = f"""Summarize the following sensor anomalies in a building management context.

User Query: "{user_query}"
Total Records Analyzed: {total_records}
Anomalies Found: {len(anomalies)} ({sum(1 for a in anomalies if a['severity']=='high')} high severity)

Top Anomalies:
{chr(10).join(f"  • {a['message']} [{a['type']}] — {a['severity'].upper()} severity" for a in top)}

Provide:
1. A 2-sentence executive summary of the anomaly situation
2. The most critical issue and a recommended INVESTIGATION step
3. Whether this warrants investigation (yes/no and why)

Rules about what these findings do and do not establish:
- Every statement must follow from the anomalies listed above. Do not add a figure, a
  threshold, a limit or a place that is not there.
- NO CAPACITY WAS READ. Never say or imply that a space is overcrowded, busy, at or over
  capacity, exceeding an occupancy limit, or in breach of a fire code. None of those follow
  from a reading being unusual, and no capacity figure was supplied to you.
- A z-score or a step change says only that a value is unusual FOR THAT SENSOR. It does not
  say the value is unsafe, and it does not say what caused it.
- Never instruct anyone to alert security, call emergency services, evacuate, activate a
  protocol, close access points or redirect people. A statistic cannot support an
  instruction about people.
- Name only the sensor or column given above. If none names a room or zone, say the location
  is not recorded — do not write "a monitored zone" or invent one.
- The findings above may be sensor faults as readily as real events; say so where it applies.

Be concise and factual."""
        try:
            text = await llm_manager.generate(prompt, temperature=0.2)
        except Exception as e:
            logger.warning(f"Anomaly summary LLM failed: {e}")
            return factual_summary(anomalies, total_records)
        return guard(text, anomalies, total_records)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _extract_records(self, sensor_data: Optional[Dict]) -> List[Dict]:
        if not sensor_data:
            return []
        if isinstance(sensor_data, list):
            return [r for r in sensor_data if isinstance(r, dict)]
        if isinstance(sensor_data, dict):
            # Accept both the flat shape ({"data": [...]}) and the pipeline's
            # sql_result shape ({"results": {"data": [...]}}). Previously a
            # results-as-dict was treated as the record list and discarded, so
            # the anomaly agent saw zero records despite SQL returning rows.
            data = sensor_data.get("data")
            if data is None:
                results = sensor_data.get("results")
                if isinstance(results, dict):
                    data = results.get("data")
                elif isinstance(results, list):
                    data = results
            if isinstance(data, list):
                return [r for r in data if isinstance(r, dict)]
        return []
