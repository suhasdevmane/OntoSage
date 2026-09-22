"""A room's graph id is shown with the space a person writes (BUG-821).

The booking answers printed "Room1.06 is free for the next 2 hours" because the room's local name
in the graph has no space; the same room is "Room 1.06" everywhere else in the product. The id
itself is untouched (it keys the booking lookup); only what is printed changes.
"""

import pytest

from orchestrator.services.event_query_service import _room_name

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw, shown",
    [
        ("Room1.06", "Room 1.06"),
        ("Rm2.13", "Rm 2.13"),
        ("Room 1.06", "Room 1.06"),
        ("Atrium", "Atrium"),
        ("", ""),
        (None, ""),
    ],
)
def test_the_printed_name_has_the_space(raw, shown):
    assert _room_name(raw) == shown


def test_the_answer_texts_go_through_the_display_name():
    import inspect

    from orchestrator.services import event_query_service as mod

    source = inspect.getsource(mod)
    assert "{_room_name(room)} is free" in source
    # The busy wording changed when the timetable joined the bookings: one room can now be "not
    # free" for either reason, or for both. What this test is really pinning is that every branch
    # puts the room id through the display helper, so all three are checked by name.
    assert "{_room_name(room)} is not free" in source
    assert "{_room_name(room)} has no bookings" in source
    assert "_room_name(r) for r in shown" in source
    assert "{_room_name(name)}: {n} session(s)" in source
