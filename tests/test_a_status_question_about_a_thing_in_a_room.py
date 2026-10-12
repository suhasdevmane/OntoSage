# -*- coding: utf-8 -*-
"""CAVEAT-1627: "is it working?" after "Drinking water — Room 3.17" asks about the drinking water.

The room resolver rewrote it to "is room 3.17 working?" and the room's light and noise sensors
were reported. A status question about a reply whose lead names a thing in a room is left to the
rewrite, which reads the conversation.
"""

from __future__ import annotations

import pytest

from orchestrator.services.context_switch import resolve_sole_room_anaphor

pytestmark = pytest.mark.unit

AMENITY = (
    "Here is what I found for **Abacws Building**:\n\n"
    "**Drinking water — Room 3.17, Staff Common Room** — Drinking water in Room 3.17."
)


@pytest.mark.parametrize("q", ["is it working?", "is it out of order?", "is it broken?"])
def test_a_status_question_about_a_thing_in_a_room_is_not_the_room(q):
    assert resolve_sole_room_anaphor(q, AMENITY) is None


def test_other_follow_ups_still_take_the_room():
    assert resolve_sole_room_anaphor("is it free this afternoon?", AMENITY) == (
        "is room 3.17 free this afternoon?"
    )


def test_a_reply_about_the_room_itself_still_resolves():
    assert resolve_sole_room_anaphor("is it working?", "Room 2.13 is a meeting room.") == (
        "is room 2.13 working?"
    )
