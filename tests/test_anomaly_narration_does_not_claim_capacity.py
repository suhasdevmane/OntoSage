# -*- coding: utf-8 -*-
"""An anomaly is a statistic; it is not a capacity verdict (BUG-1298).

The live answer this pins, quoted from the run of 2026-09-30:

    Two high-severity anomalies indicate that a monitored zone's occupancy sensor has spiked
    from 1.0 to 14.0 ... THIS SUGGESTS THE AREA IS CURRENTLY OVERCROWDED AND EXCEEDING SAFE
    CAPACITY LIMITS ... immediately activate the building's crowd-control protocol -- close
    adjacent access points, redirect foot traffic, and alert security ... Yes.

and, reproduced independently at 21:19 on ask 2 of 10 in the same session:

    17 readings far exceeding the safe binary range of 0.0-1.0 ... These outliers point to
    either severe overcrowding or sensor malfunctions ... could trigger fire-code violations.

`planner_agent` refuses to build a lane for the question that produced both (BUG-1244)
because the building's capacity figures are stamped "estimated ... Not certified". Three
things had to hold for the anomaly lane to make the claim anyway, and each has its own tests
below: a comfort band declared `binary` was applied to a people COUNT, a fall was called a
spike, and the narration prompt asked for a recommended action with no rules attached.
"""

import pytest

from orchestrator.agents.anomaly_agent import AnomalyDetectionAgent
from orchestrator.services.anomaly.narration_guard import (
    claims_are_supportable,
    factual_summary,
    guard,
    unfounded_claims,
)

pytestmark = pytest.mark.unit


# The two narrations measured live, verbatim.
LIVE_1 = (
    "Two high-severity anomalies indicate that a monitored zone's occupancy sensor has "
    "spiked from 1.0 to 14.0, a 1300 % increase and 4.1 sigma above the mean of 2.55. "
    "This suggests the area is currently overcrowded and exceeding safe capacity limits. "
    "Immediately activate the building's crowd-control protocol - close adjacent access "
    "points, redirect foot traffic, and alert security. Yes. The spike and extreme z-score "
    "signal a potential safety hazard."
)
LIVE_2 = (
    "The building's occupancy sensors have reported 18 high-severity anomalies, with 17 "
    "readings far exceeding the safe binary range of 0.0-1.0 and a dramatic 92 % spike "
    "(12.0 -> 1.0). These outliers point to either severe overcrowding or sensor "
    "malfunctions that could compromise safety and compliance. ... enforce temporary "
    "occupancy limits until the anomaly is resolved. Yes - the high-severity spikes pose an "
    "immediate safety risk and could trigger fire-code violations."
)

ROWS = [
    {
        "column": "value",
        "value": 14.0,
        "type": "z-score",
        "severity": "high",
        "message": "value=14.0 is 4.1σ from mean (2.55)",
    },
    {
        "column": "value",
        "value": 1.0,
        "type": "spike",
        "severity": "medium",
        "message": "value fell 92% (12.0 → 1.0)",
    },
]


class TestTheClaimIsCaught:
    def test_the_live_answer_is_caught(self):
        hits = unfounded_claims(LIVE_1, ROWS)
        assert hits, "the answer that opened BUG-1298 must not pass the guard"
        joined = " ".join(h.lower() for h in hits)
        assert "overcrowded" in joined
        assert "crowd-control" in joined or "crowd control" in joined
        assert "alert security" in joined

    def test_the_second_live_answer_is_caught(self):
        hits = unfounded_claims(LIVE_2, ROWS)
        joined = " ".join(h.lower() for h in hits)
        assert "overcrowding" in joined
        assert "occupancy limit" in joined
        assert "fire-code" in joined

    @pytest.mark.parametrize(
        "sentence",
        [
            "The area is currently overcrowded.",
            "Occupancy is exceeding the safe capacity of the room.",
            "This is above the maximum occupancy for the space.",
            "There are too many people in the zone.",
            "The reading is at capacity.",
            "Activate the crowd-control protocol.",
            "Notify the security team immediately.",
            "The floor should be evacuated.",
            "Close adjacent access points and redirect foot traffic.",
            "Call emergency services.",
        ],
    )
    def test_claim_shapes(self, sentence):
        assert unfounded_claims(sentence, ROWS), sentence


class TestItDoesNotActTooWidely:
    """Lesson #135: a guard that detects correctly and acts too widely is the failure mode."""

    @pytest.mark.parametrize(
        "sentence",
        [
            # The factual statement the lane IS allowed to make.
            "Sensor 'value' rose from 1.0 to 14.0, 4.1 standard deviations above its mean "
            "of 2.55. The location of this sensor is not recorded.",
            "Two readings are unusual for this sensor. This may be a sensor fault.",
            # The word alone is not a claim.
            "The ventilation capacity of the unit is unchanged.",
            "This is not a capacity issue.",
            "Room temperature is outside the configured comfort range.",
            "Recommended investigation: cross-check the sensor against a second reading.",
            "No anomalies were detected across 1000 sensor readings.",
        ],
    )
    def test_clean_narration_is_untouched(self, sentence):
        assert unfounded_claims(sentence, ROWS) == []
        assert guard(sentence, ROWS, 1000) == sentence

    def test_the_replacement_keeps_every_finding(self):
        out = guard(LIVE_1, ROWS, 1000)
        assert out != LIVE_1
        for row in ROWS:
            assert row["message"] in out
        assert "overcrowded" not in out.lower()
        # It is a factual statement, not a decline: the reader still gets the anomalies.
        assert "I couldn't answer" not in out
        assert "1000 readings" in out

    def test_a_capacity_bearing_row_stands_the_capacity_family_down(self):
        rows = [dict(ROWS[0], capacity=12)]
        # Family A defers to the data...
        assert unfounded_claims("The area is overcrowded.", rows) == []
        # ...family B never does: an instruction about people is not a statistic.
        assert unfounded_claims("Alert security immediately.", rows)

    def test_factual_summary_caps_and_says_what_was_not_read(self):
        many = [dict(ROWS[0], message=f"row {i}") for i in range(25)]
        out = factual_summary(many, 500)
        assert "and 15 more" in out
        assert "no capacity figure was read" in out

    def test_claims_are_supportable_is_false_for_todays_detectors(self):
        agent = AnomalyDetectionAgent()
        records = [{"Datetime": f"t{i}", "co2_ppm": 1500.0 + i} for i in range(10)]
        rows = agent._merge_anomalies(
            agent._threshold_detection(records),
            agent._zscore_detection(records),
            agent._spike_detection(records),
        )
        assert rows, "the fixture must produce anomalies for this to mean anything"
        assert claims_are_supportable(rows) is False


class TestABinaryBandIsNotAppliedToACount:
    """`occupancy: {min 0, max 1, unit "binary"}` can only fire when it does not apply."""

    def _counts(self):
        # bldg1's occupancy series are people counts; BUG-954 measured a max of 21.
        vals = [0, 1, 2, 3, 5, 8, 11, 12, 14, 12, 11, 8, 3, 1, 0]
        return [{"Datetime": f"t{i}", "occupancy_value": float(v)} for i, v in enumerate(vals)]

    def test_a_count_series_produces_no_threshold_anomaly(self):
        found = AnomalyDetectionAgent()._threshold_detection(self._counts())
        assert found == [], f"a people count is not a binary point: {found[:2]}"

    def test_a_genuinely_binary_series_is_unaffected(self):
        rows = [{"Datetime": f"t{i}", "occupancy_value": float(i % 2)} for i in range(12)]
        assert AnomalyDetectionAgent()._threshold_detection(rows) == []

    def test_a_non_binary_band_still_fires(self):
        rows = [{"Datetime": f"t{i}", "temperature_c": 18.0 + i} for i in range(20)]
        found = AnomalyDetectionAgent()._threshold_detection(rows)
        assert found, "temperature above 26 C must still be detected"
        assert any(a["severity"] == "high" for a in found)

    def test_the_message_does_not_call_a_comfort_band_a_safety_limit(self):
        rows = [{"Datetime": f"t{i}", "temperature_c": 40.0} for i in range(5)]
        for a in AnomalyDetectionAgent()._threshold_detection(rows):
            assert "safe range" not in a["message"]
            assert "comfort range" in a["message"]


class TestAFallIsNotASpike:
    def test_a_decrease_is_narrated_as_a_fall(self):
        rows = [{"Datetime": "t0", "value": 12.0}, {"Datetime": "t1", "value": 1.0}]
        found = AnomalyDetectionAgent()._spike_detection(rows)
        assert len(found) == 1
        assert found[0]["direction"] == "fell"
        assert "fell" in found[0]["message"]
        assert "spiked" not in found[0]["message"]

    def test_an_increase_is_still_narrated_as_a_rise(self):
        rows = [{"Datetime": "t0", "value": 1.0}, {"Datetime": "t1", "value": 14.0}]
        found = AnomalyDetectionAgent()._spike_detection(rows)
        assert found[0]["direction"] == "rose"
        assert "rose" in found[0]["message"]


class TestTwoSectionsOfOneAnswerCountAnomaliesDifferently:
    """ "Anomalies / Concerns: None identified" sat under two claimed high-severity anomalies.

    Not a narration mood: the two sections are produced by two detector FAMILIES over the
    same rows and narrated by two independent LLM calls, which `_assemble_multi_intent`
    concatenates with no reconciliation. `ReportAgent._detect_anomalies` is threshold-only and
    matches a comfort band by COLUMN NAME, so it is silent on the narrow store's `value`
    column; `AnomalyDetectionAgent`'s z-score and spike detectors are name-agnostic and fire
    on it. Filed as CAVEAT-1301 — pinned here so the mechanism is not re-litigated.
    """

    def _narrow_rows(self):
        # The narrow adapter's shape: the column is called `value`, carrying no modality name.
        vals = [2.0] * 30 + [40.0] + [2.0] * 30
        return [{"Datetime": f"t{i}", "value": v} for i, v in enumerate(vals)]

    def test_the_report_finds_nothing_where_the_anomaly_lane_finds_something(self):
        from orchestrator.agents.report_agent import ReportAgent

        rows = self._narrow_rows()
        anomaly_lane = AnomalyDetectionAgent()._merge_anomalies(
            AnomalyDetectionAgent()._threshold_detection(rows),
            AnomalyDetectionAgent()._zscore_detection(rows),
            AnomalyDetectionAgent()._spike_detection(rows),
        )
        report_lane = ReportAgent()._detect_anomalies(rows)

        assert anomaly_lane, "z-score/spike must fire on an unnamed numeric column"
        assert report_lane == [], "threshold-only matching on the column NAME finds nothing"

    def test_the_planner_concatenates_without_reconciling(self):
        import inspect
        import re

        from orchestrator.agents.planner_agent import PlannerAgent

        src = re.sub(r"\s+", " ", inspect.getsource(PlannerAgent._assemble_multi_intent))
        assert "join(sections)" in src.replace('"\\n\\n---\\n\\n".', "")
        # Nothing compares one section's findings against another's.
        assert "anomal" not in src.lower()


class TestTheNoDataDeclineSpeaksToTheReader:
    """`_anomaly_node`'s CAVEAT-396 rewrite is not on the planner's path."""

    @pytest.mark.asyncio
    async def test_the_default_does_not_describe_the_lanes_input(self):
        out = await AnomalyDetectionAgent().detect(None, "any anomalies?", sensor_data={})
        text = out["formatted_response"]
        assert out["success"] is False
        assert out["declined_reason"] == "no_rows_retrieved"
        assert "No sensor data available" not in text
        # It must not claim the building lacks the sensors, which an empty fetch cannot show.
        assert "does not mean the sensors are missing" in text

    def test_the_planner_calls_the_agent_without_that_node(self):
        """Why the default has to be honest: the node's two guards are bypassed here."""
        import inspect
        import re

        from orchestrator.agents.planner_agent import PlannerAgent

        src = re.sub(r"\s+", " ", inspect.getsource(PlannerAgent._run_anomaly))
        assert "AnomalyDetectionAgent().detect(" in src
        assert "_anomaly_node" not in src


class TestTheEmptyReportDeclineIsGrammatical:
    def test_no_stray_article(self):
        from orchestrator.agents.report_agent import ReportAgent

        text = ReportAgent._no_data_narrative(
            "which areas are currently overcrowded?",
            {"overview": {"sensor_count": 0}},
        )
        assert "no a sensor" not in text.lower()
        assert "no sensor of that kind" in text.lower()
