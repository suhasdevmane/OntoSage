# -*- coding: utf-8 -*-
"""BUG-1426 (2026-10-02, the amenity half): "what time does it close?" after a reply naming
the cafe gave the BUILDING's hours.

Root cause, measured 2026-10-07: the reply says "Café" and the graph's amenity label is
"Cafe". `amenities_in_reply` compared with a plain lower(), so the accented word never
matched, `resolve_sole_floor_or_amenity_anaphor` returned None, and the co-reference rewrite
fell back to the building's own topic. Both sides are now accent-folded; the label returned
is the graph's own spelling.

The subject half of the same case (the Working Hours topic winning over Catering) is pinned
in test_bug_1439_specific_topic_beats_the_hours_frame.py.
"""
import pytest

from orchestrator.services.context_switch import (
    amenities_in_reply,
    resolve_sole_floor_or_amenity_anaphor,
)

pytestmark = pytest.mark.unit

CAFE_REPLY = "The Café (Abacws Café) is on the ground floor and is open 08:00–16:30 on weekdays."


def test_accented_reply_word_matches_unaccented_graph_label():
    assert amenities_in_reply(CAFE_REPLY, ["Cafe"]) == ["Cafe"]


def test_graph_label_keeps_its_own_spelling():
    # The rewrite must carry the graph's label, the same vocabulary the TTL route parses.
    assert amenities_in_reply(CAFE_REPLY, ["Cafe", "Canteen"]) == ["Cafe"]


def test_it_resolves_to_the_named_amenity_across_the_accent():
    out = resolve_sole_floor_or_amenity_anaphor(
        "what time does it close?", CAFE_REPLY, ["Cafe", "Canteen"]
    )
    assert out == "what time does the Cafe close?"


def test_unaccented_reply_still_matches():
    reply = "The cafe on the ground floor is open 08:00-16:30 on weekdays."
    assert amenities_in_reply(reply, ["Cafe"]) == ["Cafe"]


def test_a_word_inside_another_word_does_not_match():
    # Whole-word boundary is kept: "cafeteria" in a reply must not name "Cafe".
    reply = "The cafeteria is on floor 2."
    assert amenities_in_reply(reply, ["Cafe"]) == []


def test_several_named_amenities_stay_ambiguous():
    reply = "The Café and the Canteen both close at 16:30."
    assert (
        resolve_sole_floor_or_amenity_anaphor(
            "what time does it close?", reply, ["Cafe", "Canteen"]
        )
        is None
    )
