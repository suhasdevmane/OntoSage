"""A person who has never seen this building can still ask about it (TODO-629).

"Is it stuffy anywhere in the building?" reached the capability lane, which probed 274 sensors
and returned the row-budget refusal — honest, and useless to someone who cannot be expected to
know which floor to narrow to. The building could already answer the same question phrased as
"which room is the stuffiest": the only thing between the two was a pattern that required the
word "room".

That made the building's ability to answer depend on the questioner already knowing how to
phrase it, which is the opposite of the zero-knowledge coverage this project is for.
"""

import pytest

from orchestrator.services.routing_contract import (
    EXISTENTIAL_COMFORT_RE,
    apply_contract,
)

pytestmark = pytest.mark.unit


def _route(query: str, intent: str = "capability"):
    norm = {
        "intent": intent,
        "entities": [],
        "analytics": intent == "analytics",
        "general": intent == "general",
    }
    apply_contract(query, norm, stage="parse")
    return norm["intent"]


@pytest.mark.parametrize(
    "query",
    [
        "Is it stuffy anywhere in the building?",
        "is it too warm anywhere right now",
        "Is there anywhere quiet I can work?",
        "are any rooms too cold at the moment",
        "is anywhere noisy right now",
        "Is it humid anywhere?",
        "are any spaces crowded",
        "is somewhere draughty",
    ],
)
def test_an_existential_comfort_question_reaches_the_ranking_lane(query):
    assert _route(query) == "deliberate", query


@pytest.mark.parametrize(
    "query",
    [
        # No condition word: a facility lookup, which the capability lane owns.
        "Is there a cafe anywhere?",
        "is there anywhere to park",
        "are there any toilets on this floor",
        # No existential scope: a plain reading question.
        "Is it warm in room 5.01?",
        "is the building stuffy in room 3.10",
    ],
)
def test_a_question_missing_either_half_is_left_where_it_was(query):
    """Both halves are required: a condition word AND an existential scope. Either alone
    belongs to a lane that already answers it."""
    assert _route(query) == "capability", query


def test_a_lane_that_owns_its_own_refusal_is_not_hijacked():
    """Control declines actions and the privacy lane refuses; a comfort word must not move
    either. They are not in this rule's intent set for that reason."""
    for intent in ("control", "privacy_refusal"):
        assert _route("is it too warm anywhere", intent=intent) == intent


@pytest.mark.parametrize("intent", ["maintenance", "complaint"])
def test_a_comfort_question_mis_tagged_as_a_fault_still_ends_up_ranking(intent):
    """"Is it too warm anywhere" is a QUESTION, not a fault report. The contract already
    moves it out of the report lane (comfort_question_not_report); this rule then takes it
    the rest of the way, so the chain ends where the question belongs rather than half way."""
    assert _route("is it too warm anywhere", intent=intent) == "deliberate"


@pytest.mark.parametrize(
    "query",
    [
        "Is it stuffy anywhere in the building?",
        "is there anywhere cool to sit",
    ],
)
def test_the_pattern_matches_both_word_orders(query):
    """People write it both ways: condition-then-scope and scope-then-condition."""
    assert EXISTENTIAL_COMFORT_RE.search(query)


def test_the_rule_sits_where_the_contract_says():
    """Every matching rule is applied and the LAST wins, so position is behaviour."""
    from orchestrator.services.routing_contract import PARSE_STAGE_RULES

    names = [r.name for r in PARSE_STAGE_RULES]
    assert (
        names.index("existential_comfort_is_deliberate")
        == names.index("superlative_room_takeover") + 1
    )


def test_no_building_literal_in_the_vocabulary():
    """The condition words describe how a space feels; none names a building or a room."""
    from orchestrator.services.routing_contract import _CONDITION_ADJECTIVES

    assert "bldg" not in _CONDITION_ADJECTIVES.lower()
    assert "abacws" not in _CONDITION_ADJECTIVES.lower()


@pytest.mark.parametrize(
    "intent", ["compliance", "observability", "discovery", "metadata", "analytics"]
)
def test_the_shape_is_claimed_whichever_lane_the_classifier_guessed(intent):
    """"Is it too warm anywhere right now?" was classified `compliance`, and that lane handed
    the model a prompt with no question in it — "No question was provided." after 116s. The
    shape is claimed wherever the classifier puts it rather than chased lane by lane."""
    assert _route("Is it too warm anywhere right now?", intent=intent) == "deliberate"


def test_whole_building_scope_is_not_an_unresolved_place():
    """The compiler recorded "anywhere in the building" as a term it failed to map, which
    made the whole query unexecutable and asked the user to drop the only word that said
    "look everywhere" (TODO-629)."""
    from orchestrator.services.deliberation.compiler import _is_whole_building_scope

    for phrase in (
        "anywhere in the building",
        "anywhere",
        "the whole building",
        "building-wide",
        "all floors",
        "every room",
        "across the building",
        "overall",
    ):
        assert _is_whole_building_scope(phrase), phrase


def test_a_named_place_is_still_a_place():
    """The scope test must not swallow real anchors, or a question about one room would be
    answered about the building."""
    from orchestrator.services.deliberation.compiler import _is_whole_building_scope

    for phrase in ("floor 3", "room 5.01", "near the cafe", "level 2", "the noisy rooms"):
        assert not _is_whole_building_scope(phrase), phrase
