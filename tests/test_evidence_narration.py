# -*- coding: utf-8 -*-
"""Proxy labelling, omission reasons and honest refusals (V6-T14/T30/T35).

One principle across all three: **a limitation is only useful if stated in terms the reader
can act on.** "Data unavailable" leaves someone unable to tell a broken sensor from a
permission boundary; "restricted at your access level, and here is the request route" does
not.
"""

import pytest

from orchestrator.services.evidence.narration import (
    adequacy_note,
    collect_omissions,
    describe_not_assessable,
    describe_omission,
    describe_omissions,
    label_proxy,
    status_badge,
)
from shared.models import (
    AnswerStatus,
    OmissionReason,
    OmittedCriterion,
    SpatialAdequacy,
)

pytestmark = pytest.mark.unit

ROOM = "http://x/Room2.15"
CORRIDOR = "http://x/Corridor2"


# ── T14: proxy labelling ─────────────────────────────────────────────────────


def test_proxy_is_named_not_merely_hedged():
    """'This may not reflect the room' is unactionable; naming the corridor is not."""
    text = label_proxy(ROOM, CORRIDOR, "it is outside the room", "900 ppm", "14:02")
    assert "Corridor2" in text
    assert "Room2.15" in text
    assert "900 ppm" in text
    assert "14:02" in text


def test_proxy_answer_declines_the_room_level_claim():
    text = label_proxy(ROOM, CORRIDOR, "it is outside the room", "900 ppm")
    assert "no sensor inside" in text
    assert "not a measurement of" in text


def test_proxy_without_a_value_still_explains_itself():
    text = label_proxy(ROOM, None, "no sensor relates to this space")
    assert "Room2.15" in text
    assert text.endswith(".")


# ── T30: omission reasons ────────────────────────────────────────────────────


def test_restricted_is_worded_differently_from_missing():
    """Collapsing them tells a user data does not exist when they simply may not see it."""
    restricted = describe_omission(
        OmittedCriterion(criterion="occupancy", reason=OmissionReason.RESTRICTED)
    )
    missing = describe_omission(
        OmittedCriterion(criterion="occupancy", reason=OmissionReason.MISSING)
    )
    assert restricted != missing
    assert "exists" in restricted and "route to request" in restricted
    assert "no source" in missing


def test_not_instrumented_is_distinct_from_not_connected():
    """Different remedies: install a sensor, versus connect the data."""
    a = describe_omission(
        OmittedCriterion(criterion="noise", reason=OmissionReason.NOT_INSTRUMENTED)
    )
    b = describe_omission(OmittedCriterion(criterion="noise", reason=OmissionReason.MISSING))
    assert a != b
    assert "does not measure" in a


def test_every_reason_has_wording():
    for reason in OmissionReason:
        text = describe_omission(OmittedCriterion(criterion="x", reason=reason))
        assert "was omitted" in text


def test_omission_block_is_empty_when_nothing_was_omitted():
    assert describe_omissions([]) == ""


def test_omission_block_lists_each_criterion():
    text = describe_omissions(
        [
            OmittedCriterion(criterion="noise", reason=OmissionReason.NOT_INSTRUMENTED),
            OmittedCriterion(criterion="occupancy", reason=OmissionReason.RESTRICTED),
        ]
    )
    assert "Not covered" in text
    assert "noise" in text and "occupancy" in text


def test_collect_omissions_finds_what_was_asked_but_not_used():
    """Structural, not narrated: the criterion the model forgets is the one that mattered."""
    out = collect_omissions(
        requested=["temperature", "noise", "occupancy"],
        used=["temperature"],
        reason_for={"occupancy": OmissionReason.RESTRICTED},
    )
    assert {o.criterion for o in out} == {"noise", "occupancy"}
    assert next(o for o in out if o.criterion == "occupancy").reason is OmissionReason.RESTRICTED
    assert next(o for o in out if o.criterion == "noise").reason is OmissionReason.MISSING


def test_collect_omissions_is_case_insensitive():
    assert collect_omissions(["Temperature"], ["temperature"]) == []


# ── T35: refusal as an answer ────────────────────────────────────────────────


def test_refusal_carries_reason_and_remedy():
    """Without both, a grader cannot tell a justified refusal from giving up."""
    text = describe_not_assessable(
        "the newest reading is three days old", "restart the publisher for co2_data"
    )
    assert "Not assessable" in text
    assert "three days old" in text
    assert "What would make this answerable" in text
    assert "co2_data" in text


def test_refusal_without_a_remedy_still_states_a_reason():
    text = describe_not_assessable("no sensor covers this space")
    assert "Not assessable" in text
    assert "No sensor covers this space" in text


def test_a_reasonless_refusal_still_says_something_specific():
    """A bare refusal is the failure mode; the fallback must not be empty."""
    text = describe_not_assessable("")
    assert "does not support an answer" in text


# ── status badges ────────────────────────────────────────────────────────────


def test_every_status_has_a_plain_english_badge():
    for status in AnswerStatus:
        badge = status_badge(status)
        assert badge and "—" in badge


def test_a_prediction_cannot_read_as_a_measurement():
    """The distinction the six-status taxonomy exists to make visible."""
    assert "forecast" in status_badge(AnswerStatus.PREDICTED)
    assert "measured directly" in status_badge(AnswerStatus.OBSERVED)
    assert status_badge(AnswerStatus.PREDICTED) != status_badge(AnswerStatus.OBSERVED)


def test_inferred_says_it_was_not_measured():
    assert "not measured" in status_badge(AnswerStatus.INFERRED)


# ── adequacy notes ───────────────────────────────────────────────────────────


def test_in_room_evidence_needs_no_note():
    """Noise costs attention; the normal case should be silent."""
    assert adequacy_note(SpatialAdequacy.IN_ROOM) == ""


def test_served_zone_and_proxy_are_worded_differently():
    a = adequacy_note(SpatialAdequacy.SERVED_ZONE)
    b = adequacy_note(SpatialAdequacy.PROXY)
    assert a != b
    assert "validated zone" in a
    assert "nearby" in b


def test_proxy_note_uses_the_specific_reason_when_given():
    assert adequacy_note(SpatialAdequacy.PROXY, "the corridor outside") == "the corridor outside"
