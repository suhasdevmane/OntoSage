# -*- coding: utf-8 -*-
"""A follow-up that points at the PREVIOUS REPLY is resolved from it, deterministically
(Phase 1.2 of the QA-trial plan, 2026-10-02).

Measured on the 20-conversation battery (docs/phase0/conversations/): every follow-up that
supplied a value worked ("2.01" after "which room?"), and every one that pointed at what the
assistant had just said failed --

    "what is the temperature in the first one?"   after a list of ten rooms -> no rewrite, a decline
    "how warm is it there?"                        after three kitchens -> a CORRECT rewrite
                                                   ("room 2.66") REJECTED by the BUG-940 guard,
                                                   then answered building-wide
    "what is the status of that report?"           after "logged as REP-EF64E3" -> the id dropped,
                                                   the generic complaints topic

Three deterministic resolvers read the reply being replied to, and only it: an ordinal picks
the Nth room of its list; "that report" takes the REP id; "there"/"it" may bind the reply's
ONLY room and, when the reply named several, the system ASKS which. BUG-940's case -- a room
from a reply six turns back -- is still refused.
"""

import pytest

from orchestrator.services import context_switch as cs

pytestmark = pytest.mark.unit

LIST_REPLY = (
    "**10 of 18 meeting rooms have no booking today**: Room 2.13, Room 2.15, Room 3.13, "
    "Room 3.16, Room 3.27, Room 4.11, Room 4.12, Room 5.15, Room 5.16, Room 5.17"
)
KITCHENS = (
    "**The building records a Kitchen on floors 2, 3 and 5:** Room 2.66, Room 3.18, Room 5.26"
)
ONE_ROOM = "The most recent reading shows 23.65 °C in room 2.01."
TICKET = "✅ Thank you — your **maintenance request** has been logged as **REP-EF64E3**."


class TestPlacesInReply:
    def test_ordered_and_deduplicated(self):
        assert cs.places_in_reply(LIST_REPLY)[:3] == ["2.13", "2.15", "3.13"]
        assert cs.places_in_reply(KITCHENS + " Room 2.66 again") == ["2.66", "3.18", "5.26"]
        assert cs.places_in_reply("no rooms here") == []


class TestOrdinal:
    def test_the_first_one_is_the_first_listed_room(self):
        out = cs.resolve_ordinal("what is the temperature in the first one?", LIST_REPLY)
        assert out == "what is the temperature in room 2.13?"

    def test_the_last_one(self):
        assert "room 5.17" in cs.resolve_ordinal("is the last one booked?", LIST_REPLY)

    def test_beyond_the_list_is_none(self):
        assert cs.resolve_ordinal("the fifth one?", KITCHENS) is None

    def test_no_ordinal_is_none(self):
        assert cs.resolve_ordinal("what about room 2.01?", LIST_REPLY) is None


class TestReportReference:
    def test_that_report_takes_the_id(self):
        assert cs.resolve_report_reference("what is the status of that report?", TICKET) == (
            "what is the status of REP-EF64E3?"
        )

    def test_no_id_in_the_reply_is_none(self):
        assert cs.resolve_report_reference("what is the status of that report?", ONE_ROOM) is None


class TestTheGuardsException:
    def test_there_binds_the_replys_only_room(self):
        assert cs.previous_reply_named_it(
            "and the CO2 there?", "What is the CO2 level in room 2.01?", ONE_ROOM
        )

    def test_there_does_not_bind_one_of_several(self):
        """Three kitchens: the rewrite's choice of 2.66 is a guess, and is still refused."""
        assert not cs.previous_reply_named_it(
            "how warm is it there?", "How warm is it in room 2.66?", KITCHENS
        )
        assert cs.ambiguous_reference("how warm is it there?", KITCHENS) == ["2.66", "3.18", "5.26"]

    def test_an_ordinal_binds_the_nth(self):
        assert cs.previous_reply_named_it(
            "the first one?", "What is the temperature in room 2.13?", LIST_REPLY
        )
        assert not cs.previous_reply_named_it(
            "the first one?", "What is the temperature in room 5.17?", LIST_REPLY
        )

    def test_bug_940s_case_is_still_refused(self):
        """The room came from a reply that is NOT the one being replied to."""
        assert not cs.previous_reply_named_it(
            "what is the humidity in there right now?",
            "What is the humidity in Telecommunications Room 1.34?",
            "Floor 3 averaged 22.9 °C and floor 4 22.8 °C.",
        )
        assert cs.ambiguous_reference("in there?", "Floor 3 averaged 22.9 °C.") == []

    def test_a_follow_up_that_names_its_own_place_is_not_this_case(self):
        assert not cs.previous_reply_named_it(
            "what about room 2.01?", "What is the occupancy of room 2.01?", LIST_REPLY
        )


class TestSoleRoomAnaphor:
    def test_it_becomes_the_replys_only_room(self):
        reply = "The only workspace that satisfies both is **WS-02**, Room 1.06 (floor 1). Room 1.06 again."
        assert cs.resolve_sole_room_anaphor("is it free this afternoon?", reply) == (
            "is room 1.06 free this afternoon?"
        )

    def test_there_becomes_in_the_room(self):
        assert cs.resolve_sole_room_anaphor("and the CO2 there?", ONE_ROOM) == (
            "and the CO2 in room 2.01?"
        )
        assert cs.resolve_sole_room_anaphor("how warm is it in there?", ONE_ROOM) == (
            "how warm is it in room 2.01?"
        )

    def test_several_rooms_or_none_is_none(self):
        assert cs.resolve_sole_room_anaphor("is it free?", KITCHENS) is None
        assert cs.resolve_sole_room_anaphor("is it free?", "Floor 3 averaged 22.9 °C.") is None

    def test_acting_on_the_previous_result_is_left_alone(self):
        assert cs.resolve_sole_room_anaphor("plot it?", ONE_ROOM) is None
        assert cs.resolve_sole_room_anaphor("forecast it for 6 hours?", ONE_ROOM) is None
        assert cs.acts_on_previous_result("compare both")

    def test_a_statement_or_a_named_place_is_left_alone(self):
        assert cs.resolve_sole_room_anaphor("it is cold", ONE_ROOM) is None
        assert cs.resolve_sole_room_anaphor("is it warmer than room 3.01?", ONE_ROOM) is None


class TestLocationStatement:
    def test_i_am_in_room_reasks_the_nearest_question_from_there(self):
        out = cs.resolve_location_statement("I am in room 3.01", "where's the nearest toilet?")
        assert out == "where's the nearest toilet from room 3.01?"

    def test_a_floor_works_too(self):
        assert cs.resolve_location_statement("I'm on floor 2", "Where is the nearest exit?") == (
            "Where is the nearest exit from floor 2?"
        )

    def test_not_after_a_question_that_named_its_start(self):
        assert (
            cs.resolve_location_statement("I am in room 3.01", "nearest toilet to room 2.01?")
            is None
        )
        assert cs.resolve_location_statement("I am in room 3.01", "toilet from room 2.01?") is None

    def test_a_question_is_not_a_statement(self):
        assert cs.resolve_location_statement("am I in room 3.01?", "nearest toilet?") is None
        assert cs.resolve_location_statement("I am in room 3.01 and it is cold", "x?") is None


class TestPairReference:
    def test_the_two_are_the_users_two_rooms(self):
        out = cs.resolve_pair_reference(
            "which of the two is busier?",
            ["How many people are in room 1.06 right now?", "what about room 2.01?"],
        )
        assert out == "which of room 1.06 and room 2.01 is busier?"

    def test_one_or_three_rooms_is_none(self):
        assert cs.resolve_pair_reference("which of the two is busier?", ["room 1.06?"]) is None
        assert (
            cs.resolve_pair_reference(
                "which of the two is busier?", ["room 1.06", "room 2.01", "room 3.01"]
            )
            is None
        )

    def test_rooms_named_by_a_reply_do_not_count(self):
        """Only the user's own turns are read -- the list is of USER texts by construction."""
        assert cs.resolve_pair_reference("both?", []) is None


class TestAReportIdIsAStatusLookup:
    @pytest.mark.parametrize(
        "q,intent",
        [
            ("what is the status of REP-5C28ED?", "capability"),
            ("any update on my report?", "general"),
            ("what is the status of REP-5C28ED?", "maintenance"),
        ],
    )
    def test_routes_to_the_intake_node(self, q, intent):
        from orchestrator.services.routing_contract import apply_contract

        n = {"intent": intent}
        apply_contract(q, n, stage="parse")
        assert n["intent"] == "maintenance"

    def test_a_question_without_an_id_is_not_captured(self):
        from orchestrator.services.routing_contract import apply_contract

        n = {"intent": "asset_state"}
        apply_contract("what is the status of the lift?", n, stage="parse")
        assert n["intent"] == "asset_state"


class TestARaisedClarificationSurvivesTheConceptStage:
    def test_the_rescue_rule_stands_down_on_the_marker(self, monkeypatch):
        from orchestrator.services import routing_contract as rc
        from orchestrator.services import grounding_guard

        monkeypatch.setattr(grounding_guard, "is_building_specific", lambda q, c=None: True)
        n = {
            "intent": "clarification",
            "concepts": [],
            "clarification_raised": ["ambiguous_follow_up"],
        }
        rc.apply_contract("how warm is it there?", n, stage="concept")
        assert n["intent"] == "clarification"
        n = {"intent": "clarification", "concepts": []}
        rc.apply_contract("how warm is it there?", n, stage="concept")
        assert n["intent"] == "analytics", "without the marker the rescue still rescues"

    def test_the_orchestrator_passes_the_marker(self):
        import inspect

        from orchestrator.workflow import _orchestrator

        src = inspect.getsource(_orchestrator)
        assert '"clarification_raised": [' in src
        assert 'if r in ("ambiguous_follow_up", "unbound_spatial_deixis")' in src


class TestWhatCanIAskYou:
    def test_is_a_self_question(self):
        from orchestrator.services.self_description import is_self_question

        assert is_self_question("what can I ask you?")
        assert not is_self_question("what can I ask about the building?")


class TestItIsWired:
    def test_the_rewrite_resolves_deterministically_first(self):
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        assert src.index("(resolve_report_reference, _previous_reply)") < src.index(
            "llm_manager.generate"
        )
        assert "(resolve_location_statement, _previous_user_q)" in src
        assert "(resolve_pair_reference, _earlier_user)" in src
        assert "(resolve_sole_room_anaphor, _previous_reply)" in src
        assert "previous_reply_named_it(latest, rewritten, _previous_reply)" in src
        assert "coref_ambiguous_places" in src
        # BEFORE the follow-up gate: on the live re-ask the gate had kept every ordinal and
        # location statement away from the resolvers (2026-10-02).
        assert src.index("(resolve_ordinal, _previous_reply)") < src.index(
            "if not _is_followup_query(latest)"
        )
        assert src.index("ambiguous_reference(latest, _previous_reply)") < src.index(
            "llm_manager.generate"
        )

    def test_the_follow_up_gate_reads_words_not_whitespace(self):
        from orchestrator.agents.dialogue_agent import _is_followup_query

        assert _is_followup_query("what is the temperature in the first one?")

    def test_the_ambiguous_case_becomes_a_clarification(self):
        import inspect

        from orchestrator.agents import dialogue_agent

        src = inspect.getsource(dialogue_agent)
        assert '"routing_rules_applied": ["ambiguous_follow_up"]' in src
