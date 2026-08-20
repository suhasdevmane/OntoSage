# -*- coding: utf-8 -*-
"""BUG-197: 'above' with no number cannot rank anything.

BELOW/ABOVE are filter directions — they mean something only against a value.
When the compiler answers a ranking with one and no threshold, the scorer
substitutes the anchor's own edge, and for CO2 that edge (420 ppm) sits below
every occupied room. Every candidate then scores 1.0 and the ranking degenerates
into alphabetical order wearing a ranking's clothes.
"""

from __future__ import annotations

import pytest

from orchestrator.services.deliberation.compiler import (
    _fold_unbounded_threshold_direction,
)
from orchestrator.services.deliberation.cqir import (
    Constraint,
    DecisionKind,
    Direction,
    Hardness,
)
from orchestrator.services.deliberation.scorer import DEFAULT_ANCHORS, _utility

pytestmark = pytest.mark.unit

CO2 = DEFAULT_ANCHORS["co2"]
ROOM_VALUES = [520.0, 780.0, 1150.0, 640.0]  # four rooms, genuinely different


def _c(direction, threshold=None, modality="co2"):
    return Constraint(
        modality=modality, direction=direction, hardness=Hardness.SOFT, threshold=threshold
    )


class TestTheDegeneracyItself:
    def test_unbounded_above_scores_every_room_identically(self):
        """The bug, demonstrated: four different rooms, one score."""
        c = _c(Direction.ABOVE)
        scores = {_utility(c, v, CO2) for v in ROOM_VALUES}
        assert scores == {1.0}, "expected the degenerate tie this fold exists to prevent"

    def test_after_the_fold_the_rooms_separate(self):
        c = _c(Direction.ABOVE)
        _fold_unbounded_threshold_direction([c], DecisionKind.RANK_ALL)
        scores = [_utility(c, v, CO2) for v in ROOM_VALUES]
        assert len(set(scores)) == len(ROOM_VALUES), f"still tied: {scores}"


class TestPolarityIsPreserved:
    def test_above_becomes_maximize_so_the_highest_still_wins(self):
        c = _c(Direction.ABOVE)
        _fold_unbounded_threshold_direction([c], DecisionKind.RANK_ALL)
        assert c.direction is Direction.MAXIMIZE
        assert _utility(c, 1150.0, CO2) > _utility(c, 520.0, CO2)

    def test_below_becomes_minimize_so_the_lowest_still_wins(self):
        c = _c(Direction.BELOW)
        _fold_unbounded_threshold_direction([c], DecisionKind.RANK_ALL)
        assert c.direction is Direction.MINIMIZE
        assert _utility(c, 520.0, CO2) > _utility(c, 1150.0, CO2)


class TestWhatMustNotBeTouched:
    def test_a_stated_threshold_keeps_its_filter_meaning(self):
        c = _c(Direction.BELOW, threshold=800.0)
        _fold_unbounded_threshold_direction([c], DecisionKind.RANK_ALL)
        assert c.direction is Direction.BELOW and c.threshold == 800.0

    def test_list_matching_keeps_its_under_specification(self):
        """'Which rooms are above?' is a broken filter, not a ranking to rescue."""
        c = _c(Direction.ABOVE)
        _fold_unbounded_threshold_direction([c], DecisionKind.LIST_MATCHING)
        assert c.direction is Direction.ABOVE

    @pytest.mark.parametrize("d", [Direction.MINIMIZE, Direction.MAXIMIZE, Direction.NEAR_VALUE])
    def test_non_threshold_directions_pass_through(self, d):
        c = _c(d)
        _fold_unbounded_threshold_direction([c], DecisionKind.RANK_ALL)
        assert c.direction is d

    def test_a_zero_threshold_counts_as_stated(self):
        c = _c(Direction.ABOVE, threshold=0.0)
        _fold_unbounded_threshold_direction([c], DecisionKind.RANK_ALL)
        assert c.direction is Direction.ABOVE


class TestAppliesAcrossRankingKinds:
    @pytest.mark.parametrize(
        "kind", [DecisionKind.RANK_ALL, DecisionKind.SUPERLATIVE, DecisionKind.SELECT_ONE]
    )
    def test_every_ranking_decision_is_folded(self, kind):
        c = _c(Direction.ABOVE)
        _fold_unbounded_threshold_direction([c], kind)
        assert c.direction is Direction.MAXIMIZE

    def test_all_constraints_in_the_program_are_folded(self):
        cs = [_c(Direction.ABOVE), _c(Direction.BELOW, modality="noise")]
        _fold_unbounded_threshold_direction(cs, DecisionKind.RANK_ALL)
        assert [x.direction for x in cs] == [Direction.MAXIMIZE, Direction.MINIMIZE]
