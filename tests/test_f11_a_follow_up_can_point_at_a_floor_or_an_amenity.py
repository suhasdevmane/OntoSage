# -*- coding: utf-8 -*-
"""F11 (QA-trial plan, 2026-10-04): every reply-pointing resolver matched ONLY dotted
room tokens, so "what time does it close?" after a café answer gave the BUILDING's
hours (BUG-1426), and a floor named in a reply could not be referred back to at all.

Precedence: ROOM (resolve_sole_room_anaphor, unchanged, synchronous) beats everything;
AMENITY beats a bare FLOOR number. The amenity-over-floor rule is not cosmetic -- it was
found as a REAL bug in this module's own first version, which tried the floor fallback
inside the synchronous room resolver and matched "Floor 0" in "The Café is on Floor 0,
open 08:00-16:00" before the amenity step ever ran, which would have rewritten "what
time does it close?" to "...does floor 0 close?". Floors do not have opening hours;
amenities do. resolve_sole_floor_or_amenity_anaphor checks amenity FIRST for exactly
this reason.

Amenity vocabulary comes from the graph (record_registry.held_amenity_classes), never a
hardcoded word list -- building-agnostic by construction.
"""
import pytest

from orchestrator.services.context_switch import (
    amenities_in_reply,
    floors_in_reply,
    resolve_sole_floor_or_amenity_anaphor,
    resolve_sole_room_anaphor,
)

pytestmark = pytest.mark.unit


class TestFloorsInReply:
    def test_extracts_one_floor(self):
        assert floors_in_reply("The toilet nearest Room 0.01 is on Floor 3.") == ["3"]

    def test_deduplicates_in_order(self):
        reply = "Male washroom — Floor 2. Also on Floor 2: the accessible toilet."
        assert floors_in_reply(reply) == ["2"]

    def test_several_floors_is_not_one(self):
        reply = "Rooms are on Floor 1 and Floor 2."
        assert floors_in_reply(reply) == ["1", "2"]

    def test_bare_floor_with_no_number_is_not_extracted(self):
        assert floors_in_reply("It is on the same floor.") == []


class TestResolveSoleRoomAnaphorIsUnchangedRoomOnly:
    def test_a_bare_floor_with_no_room_is_not_this_resolvers_case(self):
        """F11's floor fallback lives in resolve_sole_floor_or_amenity_anaphor, not
        here -- this resolver must stay room-only so it can stay in the synchronous
        loop unchanged."""
        reply = "The nearest fire exit is on Floor 2."
        assert resolve_sole_room_anaphor("is it open this afternoon?", reply) is None

    def test_a_named_room_still_resolves_exactly_as_before(self):
        out = resolve_sole_room_anaphor("is it free now?", "Room 3.01 is quiet.")
        assert out == "is room 3.01 free now?"


class TestAmenitiesInReply:
    LABELS = ["Café", "Reception", "Changing Places"]

    def test_finds_the_one_named_amenity(self):
        reply = "The Café is on Floor 0, open 08:00-16:00."
        assert amenities_in_reply(reply, self.LABELS) == ["Café"]

    def test_a_short_or_absent_label_never_matches(self):
        assert amenities_in_reply("nothing here", self.LABELS) == []

    def test_word_boundary_not_substring(self):
        """'Café' must not match inside an unrelated longer word."""
        assert amenities_in_reply("Cafeteria services end at 16:00.", ["Café"]) == []


class TestResolveSoleFloorOrAmenityAnaphor:
    LABELS = ["Café", "Reception"]

    def test_the_motivating_case_bug_1426(self):
        out = resolve_sole_floor_or_amenity_anaphor(
            "and what time does it close?", "The Café is on Floor 0, open 08:00-16:00.", self.LABELS
        )
        assert out == "and what time does the Café close?"

    def test_amenity_wins_over_a_floor_in_the_same_reply(self):
        """The exact live shape this precedence rule exists for: a floor number sits
        in the SAME sentence as the amenity, and the amenity must still win -- a floor
        does not have closing hours."""
        reply = "The Café is on Floor 0, open 08:00-16:00 on weekdays."
        out = resolve_sole_floor_or_amenity_anaphor("is it open now?", reply, self.LABELS)
        assert out == "is the Café open now?"
        assert "floor 0" not in out.lower()

    def test_a_bare_floor_with_no_amenity_still_resolves(self):
        reply = "The nearest fire exit is on Floor 2."
        out = resolve_sole_floor_or_amenity_anaphor(
            "is it open this afternoon?", reply, self.LABELS
        )
        assert out == "is floor 2 open this afternoon?"

    def test_a_room_in_the_reply_stands_this_resolver_down(self):
        """A room is handled by resolve_sole_room_anaphor earlier in the chain; this
        resolver must not ALSO fire for it."""
        reply = "The Café (Room 0.05) is on Floor 0."
        assert resolve_sole_floor_or_amenity_anaphor("is it open now?", reply, self.LABELS) is None

    def test_two_named_amenities_is_not_resolved(self):
        reply = "The Café and Reception are both on Floor 0."
        assert resolve_sole_floor_or_amenity_anaphor("is it open now?", reply, self.LABELS) is None

    def test_a_statement_not_a_question_is_left_alone(self):
        reply = "The Café is on Floor 0."
        assert resolve_sole_floor_or_amenity_anaphor("it is closed.", reply, self.LABELS) is None


class TestItIsWiredIntoTheRewriteChain:
    def test_the_combined_resolver_is_imported_and_called(self):
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        assert "resolve_sole_floor_or_amenity_anaphor(" in src
        assert "held_amenity_classes()" in src

    def test_the_candidate_list_picks_one_representative_term_per_class(self):
        """Regression guard: a class can declare several synonyms ('cafe', 'canteen',
        'coffee shop', ...). Found live while verifying this fix: passing every
        synonym that matches would let ONE class's two synonyms both appearing in a
        reply look like TWO different amenities to amenities_in_reply, declining as
        ambiguous when there is really just one. The call site must keep at most one
        candidate per class."""
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        block_start = src.index("for _c in _classes:")
        block_end = src.index("resolve_sole_floor_or_amenity_anaphor(", block_start)
        block = src[block_start:block_end]
        assert "break" in block, "must stop at the first matching candidate per class"

    def test_it_runs_after_the_synchronous_room_only_loop(self):
        """The room resolver (synchronous, free) must be tried BEFORE paying for a
        graph read for amenities -- a room always wins and should never pay that cost."""
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        loop_idx = src.index("for _resolver, _context in (")
        combined_idx = src.index("resolve_sole_floor_or_amenity_anaphor(")
        assert loop_idx < combined_idx

    def test_the_pre_gate_does_not_stand_down_on_a_floor_alone(self):
        """Regression guard for the bug this module's own first version shipped:
        gating the graph read on 'no floor present' would stand the WHOLE step down
        exactly when an amenity-plus-floor reply needs it most."""
        import inspect

        from orchestrator.agents.dialogue_agent import DialogueAgent

        src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
        gate_idx = src.index("resolve_sole_floor_or_amenity_anaphor(")
        gate_start = src.rindex("if (", 0, gate_idx)
        gate_block = src[gate_start:gate_idx]
        assert "floors_in_reply" not in gate_block
