# -*- coding: utf-8 -*-
"""G4/G6 (2026-10-04): a pure, non-editing detector for two self-contradicting narration
shapes found live. Advisory only -- it counts, it never rewrites an answer. The project's
own narration-editing pipeline (narration_validators.py) is explicitly flagged as risky to
extend without a live measurement period; this module exists so that measurement can start
without touching that pipeline at all.
"""
import pytest

from orchestrator.services.narration_contradiction import (
    compliance_contradiction,
    range_contradiction,
)

pytestmark = pytest.mark.unit

G6_LIVE_ANSWER = (
    "**Last comfortable reading: 2026‑10‑02 11:45:13**.\n"
    "At that time the Room 5.08 — Academic Office temperature was 24.38 °C, which is "
    "✅ compliant with ASHRAE 55 (20–26 °C).\n"
    "The Room 5.08 — Academic Office CO₂ was 1052 ppm, ⚠️ compliant with ASHRAE 62.1 "
    "(≤1100 ppm) but ❌ non‑compliant with WELL v2 and BREEAM Hea 02 (both ≤1000 ppm).\n"
    "Thus, the last time Room 5.08 met all listed comfort and air‑quality standards was at "
    "2026‑10‑02 11:45:13."
)

G5_CLEAN_ANSWER = (
    "Room 5.08 is currently comfortable: temperature 23.1 °C (compliant with ASHRAE 55) and "
    "CO2 780 ppm (compliant with every applicable standard)."
)

BUG_1405_LIVE_HEADLINE = (
    "**Across the building temperature is averaging 27.6 °C**, ranging from 7.2 to 71.0 °C.\n\n"
    "| Floor | Now °C |\n|---|---|\n"
    "| Floor 0 | 23.8 |\n| Floor 1 | 23.6 |\n| Floor 2 | 23.7 |\n| Floor 3 | 23.7 |\n"
    "| Floor 4 | 23.9 |\n| Floor 5 | 24.2 |"
)

CONSISTENT_HEADLINE = (
    "**Across the building temperature is averaging 23.8 °C**, ranging from 23.6 to 24.2 °C.\n\n"
    "| Floor | Now °C |\n|---|---|\n"
    "| Floor 0 | 23.8 |\n| Floor 1 | 23.6 |\n| Floor 2 | 23.7 |\n| Floor 3 | 23.7 |\n"
    "| Floor 4 | 23.9 |\n| Floor 5 | 24.2 |"
)

# The live false positive this detector produced on its first measured pass
# (docs/phase0/tail_O_2026-10-01_occupant_part2.md.jsonl): a Mean/Lowest/Highest/Sensors
# table where the Rooftop row's OWN Lowest/Highest columns substantiate the wide headline
# range -- a fix should not flag the very answer that is explaining its outlier correctly.
MULTI_COLUMN_TABLE_SUBSTANTIATES_HEADLINE = (
    "**Across the building temperature is averaging 27.6 °C**, ranging from 7.2 to 71.0 °C.\n\n"
    "| Floor | Now °C | Lowest | Highest | Sensors |\n|---|---|---|---|---|\n"
    "| Floor 0 | 23.9 | 20.2 | 24.6 | 19 |\n"
    "| Floor 1 | 23.0 | 15.4 | 24.3 | 16 |\n"
    "| Floor Rooftop | 50.6 | 7.2 | 71.0 | 8 |"
)


class TestComplianceContradiction:
    def test_the_live_shape_is_detected(self):
        c = compliance_contradiction(G6_LIVE_ANSWER)
        assert c is not None
        assert "met all" in c.lower()

    def test_a_clean_claim_with_no_contradicting_marker_is_not_flagged(self):
        assert compliance_contradiction(G5_CLEAN_ANSWER) is None

    def test_a_marker_with_no_full_compliance_claim_is_not_flagged(self):
        text = "The CO2 reading is ❌ non-compliant with BREEAM Hea 02."
        assert compliance_contradiction(text) is None

    @pytest.mark.parametrize("bad", [None, "", 123, [], {}])
    def test_malformed_input_never_raises(self, bad):
        assert compliance_contradiction(bad) is None


class TestRangeContradiction:
    def test_the_bug_1405_shape_is_detected(self):
        r = range_contradiction(BUG_1405_LIVE_HEADLINE)
        assert r is not None
        assert "27.6" in r

    def test_a_consistent_headline_is_not_flagged(self):
        assert range_contradiction(CONSISTENT_HEADLINE) is None

    def test_fewer_than_three_table_rows_is_not_enough_to_judge(self):
        text = "Averaging 50 °C, ranging from 10 to 90 °C.\n| Floor 0 | 23.8 |\n| Floor 1 | 23.6 |"
        assert range_contradiction(text) is None

    def test_a_multi_column_table_whose_lowest_highest_cells_cover_the_headline_is_not_flagged(
        self,
    ):
        """Regression for the detector's own first-measured false positive: reading only
        the first numeric column (Now/Mean) and ignoring Lowest/Highest flagged the exact
        answer that explains its outlier correctly."""
        assert range_contradiction(MULTI_COLUMN_TABLE_SUBSTANTIATES_HEADLINE) is None

    def test_no_headline_shape_is_not_flagged(self):
        assert range_contradiction("The temperature is 23.5 degC in room 2.01.") is None

    @pytest.mark.parametrize("bad", [None, "", 123, [], {}])
    def test_malformed_input_never_raises(self, bad):
        assert range_contradiction(bad) is None


class TestLogContradictionsNeverFailsOrEdits:
    def test_logging_does_not_raise_on_a_broken_logger(self):
        from orchestrator.services.narration_contradiction import log_contradictions

        class _BrokenLogger:
            def info(self, *a, **k):
                raise RuntimeError("boom")

        log_contradictions(_BrokenLogger(), G6_LIVE_ANSWER)  # must not raise

    def test_logging_calls_info_exactly_once_per_shape_found(self):
        from orchestrator.services.narration_contradiction import log_contradictions

        calls = []

        class _Logger:
            def info(self, msg):
                calls.append(msg)

        log_contradictions(_Logger(), G6_LIVE_ANSWER)
        assert len(calls) == 1
        assert "compliance claim" in calls[0]
