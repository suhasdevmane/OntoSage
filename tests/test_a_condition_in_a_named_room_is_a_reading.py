"""BUG-1505: a condition asked about a NAMED room is that room's reading, not a topic.

"Is the air stuffy in room 1.06?" matched the knowledge topic 'Temperature Comfort Complaints'
(its lay terms carry "stuffy"), the subject test said the topic was the question's subject, and
`capability_measurand_is_data` stood down: the reader got the complaints procedure while the
room's CO2 sensor sat readable. A room/zone identifier plus a resolved measurand now moves it.
"""

from __future__ import annotations

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit

CO2 = [{"id": "stuffy_air", "brick_classes": ["CO2_Level_Sensor"], "modality": "co2"}]


def _ctx(q: str, subject: int = 1) -> "rc._Ctx":
    return rc._Ctx(
        query=q,
        ql=q.lower(),
        normalized={
            "intent": "capability",
            "concepts": CO2,
            "capability_amenity_subject": subject,
            "capability_amenity_facts": subject,
        },
        sr=None,
    )


@pytest.fixture(autouse=True)
def _measurand(monkeypatch):
    import orchestrator.services.grounding_guard as gg

    monkeypatch.setattr(gg, "has_measurand_concept", lambda concepts: bool(concepts))


def test_a_condition_in_a_named_room_moves_to_a_data_lane():
    assert rc._r_capability_measurand_is_data(_ctx("Is the air stuffy in room 1.06?")) not in (
        None,
        "capability",
    )


@pytest.mark.parametrize(
    "q",
    [
        "Is drinking water available on floor 3?",  # a floor is not an identifier
        "Is there a quiet room?",
        "Where is the nearest accessible toilet?",
    ],
)
def test_amenity_questions_still_keep_their_lane(q):
    assert rc._r_capability_measurand_is_data(_ctx(q)) is None


def test_the_identifier_pattern_needs_a_dotted_id():
    assert rc._NAMED_SPACE_ID_RE.search("is it stuffy in room 1.06")
    assert rc._NAMED_SPACE_ID_RE.search("zone 3.12 is noisy")
    assert not rc._NAMED_SPACE_ID_RE.search("is drinking water available on floor 3")
    assert not rc._NAMED_SPACE_ID_RE.search("a room for 10 people")
