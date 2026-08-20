# -*- coding: utf-8 -*-
"""BUG-196: a ranking that names no preferred end must still be answerable.

'Rank all zones by average CO2 over the last week.' is a clear question. The
compiler LLM emits ``direction: null`` for it — correctly, since the user stated
a criterion and no preference — and the compiler used to discard the constraint,
leaving nothing mappable and producing 'I couldn't map part of your request'.
For CO2 the better end is a health standard, not a taste, so it can be supplied.
For temperature it IS a taste, so it must still be asked.
"""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.compiler import _infer_direction
from orchestrator.services.deliberation.cqir import DecisionKind, Direction
from orchestrator.services.deliberation.scorer import (
    DEFAULT_ANCHORS,
    DEFAULT_PREFERENCE,
)

pytestmark = pytest.mark.unit

RANK = DecisionKind.RANK_ALL


class TestStandardsBackedModalities:
    @pytest.mark.parametrize(
        "modality,expected",
        [
            ("co2", Direction.MINIMIZE),
            ("pm25", Direction.MINIMIZE),
            ("noise", Direction.MINIMIZE),
            ("illuminance", Direction.MAXIMIZE),
        ],
    )
    def test_the_standard_supplies_the_missing_end(self, modality, expected):
        assert _infer_direction(modality, RANK, None) is expected

    def test_it_applies_to_superlatives_and_single_picks_too(self):
        for kind in (DecisionKind.SUPERLATIVE, DecisionKind.SELECT_ONE):
            assert _infer_direction("co2", kind, None) is Direction.MINIMIZE


class TestWhereTheBetterEndIsGenuinelyAPreference:
    @pytest.mark.parametrize(
        "modality",
        [
            "temperature",
            "humidity",
            "occupancy",
            "door_contact",
            "window_contact",
            "water_flow",
            "energy_submeter",  # no calibrated band on purpose (BUG-180)
        ],
    )
    def test_these_still_ask_rather_than_guess(self, modality):
        """Warmest or coolest? Busiest or emptiest? Only the user knows."""
        assert _infer_direction(modality, RANK, None) is None

    def test_an_unknown_modality_is_never_invented_for(self):
        assert _infer_direction("unicorn_density", RANK, None) is None


class TestThresholdBlocksInference:
    def test_a_stated_number_makes_direction_load_bearing(self):
        """'Rooms below 800ppm' and 'above 800ppm' differ ONLY in direction."""
        assert _infer_direction("co2", RANK, 800.0) is None

    def test_zero_is_a_stated_threshold_not_a_missing_one(self):
        assert _infer_direction("co2", RANK, 0.0) is None


class TestListMatchingIsExcluded:
    def test_a_matching_query_without_a_bound_is_not_a_ranking(self):
        assert _infer_direction("co2", DecisionKind.LIST_MATCHING, None) is None


class TestTableIntegrity:
    def test_every_preference_has_a_calibrated_band_to_justify_it(self):
        """The direction claims one end is better; the anchor is the citation."""
        for modality in DEFAULT_PREFERENCE:
            assert modality in DEFAULT_ANCHORS, f"{modality} asserts a better end with no band"
            assert DEFAULT_ANCHORS[modality].citation, f"{modality} has no citation"

    def test_comfort_band_modalities_are_absent_by_design(self):
        for modality in ("temperature", "humidity", "occupancy"):
            assert modality not in DEFAULT_PREFERENCE
