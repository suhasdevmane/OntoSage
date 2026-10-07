# -*- coding: utf-8 -*-
"""Owner rule (2026-10-07): count-vs-status is read from the sensor's Brick CLASS, not its label.

`counts_people`/`is_headcount` used to judge whether a series counts people purely from whether
its LABEL contained a status word ("status", "state", "flag", "detected", "presence"). A
building's naming convention can disagree with that in both directions:

* a STATUS point whose label happens to carry none of those words reads as a counter and
  inflates a headcount sum (BUG-954's shape, one level down);
* a genuine COUNTING point whose label happens to carry one of those words ("...Detected...")
  is wrongly dropped from the sum, undercounting it instead.

Both are now settled by the graph's own class when it resolves to one of the two unambiguous
Brick classes (`Occupancy_Status`, `Occupancy_Count_Sensor`); the label is read only when the
class is absent or is one BOTH populations share (`Occupancy_Sensor`, `Motion_Sensor` —
CAVEAT-207's genuine ambiguity).
"""

from __future__ import annotations

import pytest

from orchestrator.services.aggregate_support import counts_people, is_headcount

pytestmark = pytest.mark.unit


def test_a_status_point_with_no_status_word_in_its_label_is_not_counted():
    """Old, label-only behaviour would have counted this: no status word in the label at all."""
    label = "Room 5.01 Occupancy [persons]"
    # proof the label alone reads as a counter (the pre-fix result)
    assert counts_people(label) is True
    assert counts_people(label, brick_class="Occupancy_Status") is False


def test_a_counting_point_with_a_status_word_in_its_label_is_still_counted():
    """Old, label-only behaviour would have dropped this: "Detected" matches a status word."""
    label = "Room 5.01 Occupancy Detected Count [persons]"
    # proof the label alone reads as NOT a counter (the pre-fix result)
    assert counts_people(label) is False
    assert counts_people(label, brick_class="Occupancy_Count_Sensor") is True


def test_the_genuinely_ambiguous_classes_still_fall_back_to_the_label():
    """Occupancy_Sensor and Motion_Sensor are shared by both populations (CAVEAT-207): the class
    alone cannot settle it, so the label is still read, exactly as before."""
    assert counts_people("Room 5.01 occupancy [persons]", brick_class="Occupancy_Sensor") is True
    assert counts_people("Room 5.01 occupancy status", brick_class="Occupancy_Sensor") is False


def test_is_headcount_sums_the_classes_correctly_where_the_labels_would_have_misled():
    """A mix of mislabelled status and counting points: the class-based reading is used wherever
    one resolves, and the sum is unaffected by a naming convention."""
    labels = [
        "Room 5.01 Occupancy [persons]",  # status point, no status word in the label
        "Room 5.02 Occupancy Detected Count [persons]",  # counting point, has a status word
    ]
    classes = ["Occupancy_Status", "Occupancy_Count_Sensor"]
    assert is_headcount("occupancy", labels, ["count", "count"], classes) is True
    # the single real counter, found only via its class, is what makes this a headcount question
    only_status = ["Room 5.01 Occupancy [persons]"]
    assert is_headcount("occupancy", only_status, ["count"], ["Occupancy_Status"]) is False


def test_classes_may_be_omitted_or_shorter_than_labels_without_raising():
    labels = ["Room 5.01 occupancy [persons]", "Room 5.02 occupancy [persons]"]
    assert is_headcount("occupancy", labels, ["count", "count"]) is True
    assert is_headcount("occupancy", labels, ["count", "count"], ["Occupancy_Status"]) is True
