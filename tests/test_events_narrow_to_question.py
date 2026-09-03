# -*- coding: utf-8 -*-
"""Anomaly episodes must be narrowed to what the question asked (BUG-399).

Measured live: *"are there any vibration anomalies on floor 9"* returned

    "at least 500 anomaly episode(s) recorded today — dropout: 472, spike: 28"
    - spike · Room4.35 (occupancy)
    - spike · Room3.06 (humidity)
    - spike · Room5.69 (occupancy)

Two things wrong at once: bldg1 has no floor 9, and not one of those episodes is vibration.
A confident, specific answer about a different modality in rooms on floors the question never
mentioned — the shape this project guards hardest against, and worse than no answer.

Every episode already carried its room and its modality. Nothing was reading them.

Both filters fail SAFE. A modality the building's own points do not use narrows nothing
rather than guessing at the nearest one, and a room-label shape this does not recognise
disables the floor filter instead of emptying the result — a building that names its rooms
differently gets the old behaviour, not a silently blank answer.
"""

import pytest

from orchestrator.services.event_query_service import _floor_of, _narrow_to_question

pytestmark = pytest.mark.unit

#: uuid -> (room, modality), the map the service already builds.
POINTS = {
    "u1": ("Room4.35", "occupancy"),
    "u2": ("Room3.06", "humidity"),
    "u3": ("Room5.69", "occupancy"),
    "u4": ("Room4.02", "temperature"),
}

EPISODES = [
    {"detector": "spike", "room": "Room4.35", "modality": "occupancy"},
    {"detector": "spike", "room": "Room3.06", "modality": "humidity"},
    {"detector": "spike", "room": "Room5.69", "modality": "occupancy"},
    {"detector": "dropout", "room": "Room4.02", "modality": "temperature"},
]


# ── the reported failure ───────────────────────────────────────────────────────────────


def test_the_exact_question_no_longer_lists_unrelated_episodes():
    out, info = _narrow_to_question(
        "are there any vibration anomalies on floor 9", EPISODES, POINTS
    )
    assert out == []
    assert "does not monitor vibration" in info["empty_reason"]
    # It must not answer with occupancy or humidity.
    assert "occupancy" not in info["empty_reason"]


def test_an_uninstrumented_modality_says_so_rather_than_listing_what_is():
    _out, info = _narrow_to_question("any radon anomalies today", EPISODES, POINTS)
    assert "does not monitor radon" in info["empty_reason"]
    assert "not a fault" in info["empty_reason"]


# ── modality narrowing ─────────────────────────────────────────────────────────────────


def test_a_named_modality_keeps_only_that_modality():
    out, info = _narrow_to_question("any humidity anomalies today", EPISODES, POINTS)
    assert info["modality"] == "humidity"
    assert [e["modality"] for e in out] == ["humidity"]


def test_a_modality_with_no_episodes_says_so_rather_than_showing_others():
    out, info = _narrow_to_question("any temperature anomalies", EPISODES[:3], POINTS)
    assert out == []
    assert "No temperature anomalies" in info["empty_reason"]


def test_naming_no_modality_keeps_everything():
    """ "Any anomalies this week?" is a legitimate whole-building question."""
    out, info = _narrow_to_question("any anomalies this week", EPISODES, POINTS)
    assert len(out) == len(EPISODES)
    assert "modality" not in info


# ── floor narrowing ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label, expected",
    [("Room4.35", "4"), ("Room3.06", "3"), ("rm 5.69", "5"), ("Green Roof", "")],
)
def test_the_floor_is_read_from_the_room_label(label, expected):
    assert _floor_of(label) == expected


def test_a_named_floor_keeps_only_that_floor():
    out, info = _narrow_to_question("any anomalies on floor 4", EPISODES, POINTS)
    assert info["floor"] == "4"
    assert {e["room"] for e in out} == {"Room4.35", "Room4.02"}


def test_a_floor_with_nothing_on_it_says_so():
    out, info = _narrow_to_question("any anomalies on floor 9", EPISODES, POINTS)
    assert out == []
    assert "floor 9" in info["empty_reason"]


def test_an_unrecognised_room_shape_disables_the_floor_filter():
    """Fail safe: a differently-named building gets the old behaviour, not a blank answer."""
    episodes = [{"detector": "spike", "room": "North Wing Lab", "modality": "occupancy"}]
    points = {"u1": ("North Wing Lab", "occupancy")}
    out, info = _narrow_to_question("any anomalies on floor 2", episodes, points)
    assert out == episodes
    assert "empty_reason" not in info


def test_modality_and_floor_narrow_together():
    out, _ = _narrow_to_question("any occupancy anomalies on floor 4", EPISODES, POINTS)
    assert [e["room"] for e in out] == ["Room4.35"]


def test_the_counts_are_rebuilt_from_the_narrowed_episodes():
    """The prose must not quote totals the payload no longer contains.

    `by_detector` and the truncation flag were derived from every fetched row. Narrowing
    without rebuilding them left the summary line citing unfiltered totals, and the grounding
    guard rejected the answer live — "a number in the text could not be traced back to the
    underlying data". That is the guard doing its job, and the same defect this narrowing
    exists to remove, moved from the episode list into the summary.
    """
    import inspect

    from orchestrator.services import event_query_service as svc

    src = inspect.getsource(svc.EventQueryService._anomaly_summary)
    narrow_at = src.find("_narrow_to_question")
    recount_at = src.find("by_detector = {}")
    assert narrow_at > 0 and recount_at > 0, "the narrowing or the recount is missing"
    assert recount_at > narrow_at, (
        "by_detector is built before the narrowing, so the prose will quote counts the "
        "filtered payload does not support"
    )
